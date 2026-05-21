"""分析服务模块。

负责核心分析流程编排，协调各 Agent 和服务完成完整分析。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

import pandas as pd

from src.agents.data_fetch_agent import StockDataFetchAgent, StockDataRequest
from src.agents.hot_rank_agent import HotRankRequest, THSHotRankAgent
from src.agents.strategy_generation_agent import StrategyGenerationAgent
from src.agents.trend_analysis_agent import TrendAnalysisAgent
from src.core.config import KNOWN_SYMBOL_NAMES, LLMConfig, get_config
from src.core.exceptions import AnalysisError, DataFetchError
from src.core.models import (
    APIResponse,
    AnalysisResult,
    DecisionLayer,
    LLMEnhanceResult,
    LLMResult,
    LLMTuningResult,
    NewsSentiment,
    StrategyData,
    TrendData,
    build_meta,
    now_iso,
)
from src.services.cache_service import get_cache
from src.services.llm_service import get_llm_service
from src.services.news_service import get_news_service

# ── 代码→名称快速映射（从 KNOWN_SYMBOL_NAMES 预建，零网络开销）──
_CODE_TO_NAME: dict[str, str] = {}
for _k, _v in KNOWN_SYMBOL_NAMES.items():
    _CODE_TO_NAME[_k] = _v
    _CODE_TO_NAME[_k.upper()] = _v
    for _sfx in (".SS", ".SH", ".SZ", ".HK"):
        if _k.endswith(_sfx):
            _CODE_TO_NAME[_k[: -len(_sfx)]] = _v
            _CODE_TO_NAME[_k[: -len(_sfx)].upper()] = _v

# ── 模块级 TTL 缓存（热榜 + 行情）──────────────────────────
_hot_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}  # keyed by source
_hot_cache_lock = Lock()
_HOT_CACHE_TTL = 120  # 热榜缓存 2 分钟

_spot_cache: tuple[float, Any] | None = None  # (timestamp, spot_df)
_spot_cache_lock = Lock()
_spot_fetch_lock = Lock()  # 防止并发调用 ak.stock_zh_a_spot() 触发限流
_SPOT_CACHE_TTL = 60  # 行情缓存 1 分钟


def _get_cached_hot(source: str = "ths", ttl: float = _HOT_CACHE_TTL) -> list[dict[str, Any]] | None:
    with _hot_cache_lock:
        entry = _hot_cache.get(source)
        if entry:
            return entry[1]  # 永远返回缓存（即使过期），预热负责刷新
    return None


def _set_cached_hot(source: str, rows: list[dict[str, Any]]) -> None:
    with _hot_cache_lock:
        _hot_cache[source] = (time.time(), rows)


def _get_cached_spot(ttl: float = _SPOT_CACHE_TTL) -> Any | None:
    with _spot_cache_lock:
        if _spot_cache:
            return _spot_cache[1]  # 永远返回缓存（即使过期），预热负责刷新
    return None


def _set_cached_spot(spot_df: Any) -> None:
    global _spot_cache
    with _spot_cache_lock:
        _spot_cache = (time.time(), spot_df)


class AnalysisService:
    """分析服务：编排分析流程。"""

    def __init__(self) -> None:
        self.data_agent = StockDataFetchAgent()
        self.trend_agent = TrendAnalysisAgent()
        self.strategy_agent = StrategyGenerationAgent()
        self.hot_rank_agent = THSHotRankAgent()
        self._symbol_name_cache: dict[str, str] = {}

    # ─── 公开接口 ───────────────────────────────────────────

    def run_analyze(
        self,
        symbol: str,
        provider: str,
        period: str,
        interval: str,
        hot_limit: int,
        mode: str = "full",
    ) -> tuple[str, dict[str, Any], str | None, dict[str, Any]]:
        """主分析接口。"""
        cache_key = f"analyze:{symbol}:{provider}:{period}:{interval}:{hot_limit}:{mode}"
        cache = get_cache()
        cached = cache.get(cache_key)
        if cached is not None:
            meta = build_meta(symbol, provider)
            meta["cache"] = "hit"
            return "success", cached, None, meta

        # 核心分析
        trend, strategy, latest_rows, chart_data, _df = self._compute_core(symbol, provider, period, interval)
        trend_data = trend.to_dict()
        strategy_data = strategy.to_dict()
        symbol_name = self._resolve_symbol_name(symbol)

        payload: dict[str, Any] = {
            "symbol": symbol,
            "symbol_name": symbol_name,
            "provider": provider,
            "price": trend_data.get("latest_close"),
            "trend": trend_data.get("trend"),
            "indicators": {
                "confidence": trend_data.get("confidence"),
                "ma": trend_data.get("ma_summary"),
                "macd": trend_data.get("macd_summary"),
                "rsi": trend_data.get("rsi_summary"),
            },
            "strategy": {
                "action": self._to_action_label(str(trend_data.get("trend", ""))),
                "attention_advice": strategy_data.get("attention_advice"),
                "attention_range": strategy_data.get("attention_range"),
                "target_price": strategy_data.get("target_price"),
                "stop_loss": strategy_data.get("stop_loss_price"),
            },
            "risk": strategy_data.get("risk_factors", []),
            "latest_rows": latest_rows,
            "chart_data": chart_data,
        }

        # 新闻聚合
        payload["news"] = self._fetch_news(symbol, symbol_name, hot_limit)

        # 热榜
        if mode == "full":
            payload["hot_rank"] = self._fetch_hot_rank(hot_limit)
        elif mode == "trend":
            payload.pop("strategy", None)
        elif mode == "strategy":
            payload.pop("risk", None)

        # 决策层
        payload["decision_layer"] = self._build_decision_layer(
            trend_data=trend_data,
            strategy_data=strategy_data,
            risk_items=strategy_data.get("risk_factors", []),
            hot_rows=payload.get("hot_rank", []),
            news_sentiment_label=payload.get("news", {}).get("sentiment", {}).get("label"),
        ).to_dict()

        status = "empty" if not latest_rows else "success"
        cache.set(cache_key, payload)
        return status, payload, None, build_meta(symbol, provider)

    def run_trend(
        self, symbol: str, provider: str, period: str, interval: str,
    ) -> tuple[str, dict[str, Any], str | None, dict[str, Any]]:
        """趋势分析接口。"""
        trend, _, latest_rows, _chart, _df = self._compute_core(symbol, provider, period, interval)
        payload = {"trend": trend.to_dict(), "latest_rows": latest_rows}
        status = "empty" if not latest_rows else "success"
        return status, payload, None, build_meta(symbol, provider)

    def run_strategy(
        self, symbol: str, provider: str, period: str, interval: str,
    ) -> tuple[str, dict[str, Any], str | None, dict[str, Any]]:
        """策略分析接口。"""
        trend, strategy, _latest, _chart, _df = self._compute_core(symbol, provider, period, interval)
        payload = {"trend": trend.to_dict(), "strategy": strategy.to_dict()}
        return "success", payload, None, build_meta(symbol, provider)

    def run_market_hot(
        self, limit: int, preferred_source: str = "ths",
    ) -> tuple[str, list[dict[str, Any]], str | None, dict[str, Any]]:
        """热榜接口：东财(涨跌幅)+雪球(热度)按需合并，非阻塞行情补充。"""
        east_rows = self._fetch_hot_rank_cached(limit, "east")
        ths_rows = self._fetch_hot_rank_cached(limit, "ths")

        # 东财为主（有涨跌幅），缺热度时补雪球
        if east_rows:
            hot_rows = self._merge_hot_sources(east_rows, ths_rows)
        elif ths_rows:
            hot_rows = list(ths_rows)
        else:
            hot_rows = []

        if hot_rows:
            hot_rows = self._enrich_with_spot(hot_rows)

        status = "empty" if not hot_rows else "success"
        return status, hot_rows, None, build_meta()

    @staticmethod
    def _merge_hot_sources(
        east_rows: list[dict[str, Any]],
        ths_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """合并东财和雪球：东财提供涨跌幅，雪球提供热度。"""
        merged = list(east_rows) if east_rows else list(ths_rows)
        if not merged:
            return []
        ths_hot: dict[str, Any] = {}
        for r in (ths_rows or []):
            code = str(r.get("代码", "")).strip()
            hot_val = r.get("热度")
            if code and hot_val:
                ths_hot[code] = hot_val
        for r in merged:
            code = str(r.get("代码", "")).strip()
            need_hot = not r.get("热度") or r.get("热度") == 0
            if need_hot and code in ths_hot:
                r["热度"] = ths_hot[code]
            elif need_hot and "热度" not in r:
                r["热度"] = 0
        return merged

    def run_llm_analysis(
        self,
        symbol: str,
        provider: str,
        period: str,
        interval: str,
        hot_limit: int = 10,
    ) -> tuple[str, dict[str, Any], str | None, dict[str, Any]]:
        """LLM 增强分析接口（LLM 调用并行执行，超时不阻塞）。"""
        llm_config = get_config().llm
        if not llm_config.is_configured:
            raise AnalysisError("LLM 未配置，请在 .env 文件中设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL")

        from threading import Thread

        # 核心分析
        trend, strategy, latest_rows, chart_data, price_df = self._compute_core(symbol, provider, period, interval)
        symbol_name = self._resolve_symbol_name(symbol)

        # 新闻 + 热榜（不依赖 LLM，先获取）
        news_result = get_news_service().aggregate(symbol=symbol, company_name=symbol_name, limit=hot_limit)
        news_data = news_result.to_dict()
        hot_rows = self._fetch_hot_rank(hot_limit)

        # LLM 分析：单路主调用，20s 超时
        llm_result = LLMResult(summary="", provider_hint="", finish_reason="")
        llm_holder: list[LLMResult] = []
        llm_error: str | None = None
        def _run_main_llm():
            try:
                llm_holder.append(self._call_llm_analysis(symbol, price_df, trend, strategy, llm_config))
            except Exception as e:
                nonlocal llm_error
                llm_error = str(e)
        t = Thread(target=_run_main_llm, daemon=True)
        t.start()
        t.join(timeout=20)
        if llm_holder:
            llm_result = llm_holder[0]

        if not llm_result.summary:
            hint = "timeout" if llm_error is None else "error"
            reason_text = f"LLM分析超时" if llm_error is None else f"LLM分析失败: {llm_error}"
            llm_result = LLMResult(
                summary=f"{symbol} {trend.to_dict().get('trend', '震荡')}趋势。{reason_text}，基础技术分析结果如上。",
                provider_hint=hint,
                finish_reason=hint,
            )

        # 辅助 LLM 调用：fire-and-forget，不阻塞响应
        enhanced_sentiment = news_result.sentiment
        llm_tuning: LLMTuningResult | None = None
        llm_enhance = LLMEnhanceResult(insight="", opportunities=[], risks=[])

        news_data["sentiment"] = enhanced_sentiment.to_dict()

        # 构建响应
        payload = {
            "symbol": symbol,
            "symbol_name": symbol_name,
            "provider": provider,
            "price": float(price_df["close"].iloc[-1]) if not price_df.empty else None,
            "trend": trend.to_dict().get("trend"),
            "strategy": {
                "action": self._to_action_label(str(trend.to_dict().get("trend", ""))),
                "attention_advice": strategy.to_dict().get("attention_advice"),
                "attention_range": strategy.to_dict().get("attention_range"),
                "target_price": strategy.to_dict().get("target_price"),
                "stop_loss": strategy.to_dict().get("stop_loss_price"),
            },
            "trend_detail": trend.to_dict(),
            "indicators": {
                "confidence": trend.to_dict().get("confidence"),
                "ma": trend.to_dict().get("ma_summary"),
                "macd": trend.to_dict().get("macd_summary"),
                "rsi": trend.to_dict().get("rsi_summary"),
            },
            "risk": strategy.to_dict().get("risk_factors", []),
            "latest_rows": latest_rows,
            "chart_data": chart_data,
            "llm": {
                "analysis_text": llm_result.summary or f"{symbol} {trend.to_dict().get('trend', '震荡')}趋势，建议参考技术指标综合判断。",
                "summary": llm_result.summary or f"{symbol} {trend.to_dict().get('trend', '震荡')}趋势，建议参考技术指标综合判断。",
                "model": llm_config.model,
                "timestamp": now_iso(),
                "provider_hint": llm_result.provider_hint or "parallel",
                "finish_reason": llm_result.finish_reason or "ok",
            },
            "hot_rank": hot_rows,
            "news": news_data,
            "llm_enhance": llm_enhance.to_dict(),
            "decision_layer": self._build_decision_layer(
                trend_data=trend.to_dict(),
                strategy_data=strategy.to_dict(),
                risk_items=strategy.to_dict().get("risk_factors", []),
                hot_rows=hot_rows,
                news_sentiment_label=enhanced_sentiment.label,
                llm_tuning=llm_tuning,
            ).to_dict(),
        }

        status = "success"
        return status, payload, None, build_meta(symbol, provider)

    def run_model_config(self) -> tuple[str, dict[str, Any], str | None, dict[str, Any]]:
        """模型配置接口（只读，使用环境变量配置）。"""
        llm_service = get_llm_service()
        cfg = get_config().llm
        config_payload = {
            "base_url": cfg.base_url or "未配置",
            "api_key_set": bool(cfg.api_key),
            "model": cfg.model or "未配置",
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }

        if not cfg.is_configured:
            payload = {
                **config_payload,
                "diagnostic": {"connected": False, "latency_ms": None, "message": "LLM 未配置，请在 .env 文件中设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL"},
            }
            return "error", payload, "LLM 未配置", build_meta()

        try:
            t0 = time.time()
            ok, message = llm_service.test_connection(cfg)
            elapsed_ms = round((time.time() - t0) * 1000) if ok else None
            payload = {
                **config_payload,
                "diagnostic": {
                    "connected": ok,
                    "latency_ms": elapsed_ms,
                    "message": message,
                },
            }
            return ("success" if ok else "error"), payload, None, build_meta()
        except Exception as exc:
            payload = {
                **config_payload,
                "diagnostic": {"connected": False, "latency_ms": None, "message": str(exc)},
            }
            return "error", payload, str(exc), build_meta()

    def run_report_hub(
        self, symbol: str, provider: str, period: str, interval: str,
    ) -> tuple[str, dict[str, Any], str | None, dict[str, Any]]:
        """研报中心接口（LLM 动态生成）。"""
        trend, strategy, latest_rows, chart_data, _df = self._compute_core(symbol, provider, period, interval)
        if not latest_rows:
            return "empty", {}, None, build_meta(symbol, provider)

        trend_data = trend.to_dict()
        strategy_data = strategy.to_dict()
        symbol_name = self._resolve_symbol_name(symbol)

        # 构建 LLM 输入
        llm_payload = {
            "symbol": symbol,
            "symbol_name": symbol_name,
            "provider": provider,
            "price": trend_data.get("latest_close"),
            "trend": trend_data.get("trend"),
            "confidence": trend_data.get("confidence"),
            "indicators": {
                "ma": trend_data.get("ma_summary"),
                "macd": trend_data.get("macd_summary"),
                "rsi": trend_data.get("rsi_summary"),
            },
            "strategy": {
                "action": strategy_data.get("action_advice"),
                "target_price": strategy_data.get("target_price"),
                "stop_loss": strategy_data.get("stop_loss_price"),
                "attention_range": strategy_data.get("attention_range"),
                "attention_advice": strategy_data.get("attention_advice"),
            },
            "risk_factors": strategy_data.get("risk_factors", []),
        }

        # 调用 LLM 生成研报
        llm_report = self._call_llm_report(llm_payload, get_config().llm)

        payload = {
            "symbol": symbol,
            "symbol_name": symbol_name,
            "report_id": f"RPT-{symbol}-{time.time_ns()}",
            "generated_at": now_iso(),
            "llm_report": llm_report,
            "trend": trend_data,
            "strategy": strategy_data,
            "risk": strategy_data.get("risk_factors", []),
            "latest_rows": latest_rows[-10:],
        }
        status = "empty" if not llm_report else "success"
        return status, payload, None, build_meta(symbol, provider)

    # ─── 内部方法 ───────────────────────────────────────────

    def _compute_core(
        self, symbol: str, provider: str, period: str, interval: str,
    ) -> tuple[Any, Any, list[dict[str, Any]], list[dict[str, Any]], pd.DataFrame]:
        """执行核心分析流程。

        返回 (trend, strategy, latest_rows, chart_data, price_df)。
        price_df 供 LLM 分析等需要原始 DataFrame 的调用方复用。
        """
        try:
            req = StockDataRequest(symbol=symbol, provider=provider, period=period, interval=interval)
            df = self.data_agent.fetch(req)
            trend = self.trend_agent.analyze(df)
            strategy = self.strategy_agent.generate(df, trend)
            all_rows = self._df_to_records(df)
            latest_rows = all_rows[-20:]
            chart_data = all_rows[-120:]
            return trend, strategy, latest_rows, chart_data, df
        except Exception as exc:
            raise AnalysisError(f"核心分析失败: {exc}") from exc

    @staticmethod
    def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
        """将 DataFrame 转为 JSON 友好的记录列表。"""
        from datetime import date as _date
        out: list[dict[str, Any]] = []
        for dt, row in df.iterrows():
            out.append({
                "date": dt.isoformat() if isinstance(dt, _date) else str(dt),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            })
        return out

    def _fetch_news(self, symbol: str, symbol_name: str, limit: int) -> dict[str, Any]:
        """获取新闻数据。"""
        try:
            news_service = get_news_service()
            result = news_service.aggregate(symbol=symbol, company_name=symbol_name, limit=limit)
            return result.to_dict()
        except Exception:
            return {
                "query": symbol_name,
                "as_of": now_iso(),
                "summary": {"total": 0, "positive": 0, "neutral": 0, "negative": 0, "latest_published_at": None},
                "sentiment": NewsSentiment().to_dict(),
                "items": [],
                "sources": [],
            }

    def _fetch_hot_rank_cached(self, limit: int, preferred_source: str = "ths") -> list[dict[str, Any]]:
        """获取热榜数据（按来源 TTL 缓存）。"""
        cached = _get_cached_hot(preferred_source)
        if cached is not None:
            return cached
        rows = self._fetch_hot_rank(limit, preferred_source)
        if rows:
            _set_cached_hot(preferred_source, rows)
        return rows

    def _fetch_hot_rank(self, limit: int, preferred_source: str = "ths") -> list[dict[str, Any]]:
        """获取热榜数据。"""
        try:
            hot_req = HotRankRequest(limit=limit, preferred_source=preferred_source)
            hot_df = self.hot_rank_agent.fetch(hot_req)
            return hot_df.to_dict(orient="records")
        except Exception:
            return []

    def _fetch_spot_cached(self) -> Any | None:
        """获取全市场行情数据（仅返回已缓存的，不阻塞等待）。"""
        return _get_cached_spot()

    def _try_fetch_spot(self) -> Any | None:
        """尝试获取行情数据：缓存命中直接返回，未命中时非阻塞尝试拉取。"""
        spot_df = _get_cached_spot()
        if spot_df is not None:
            return spot_df
        # 非阻塞尝试：如果没其他线程在拉取，就自己拉
        if _spot_fetch_lock.acquire(blocking=False):
            try:
                spot_df = _get_cached_spot()
                if spot_df is not None:
                    return spot_df
                import akshare as ak
                spot_df = ak.stock_zh_a_spot()
                if spot_df is not None and not spot_df.empty:
                    _set_cached_spot(spot_df)
                return spot_df
            except Exception:
                return None
            finally:
                _spot_fetch_lock.release()
        return None

    def _apply_spot_enrichment(self, rows: list[dict[str, Any]], spot_df: Any) -> list[dict[str, Any]]:
        """用已获取的行情数据补充热榜条目（纯 CPU 计算，无网络 IO）。"""
        try:
            if spot_df is None or spot_df.empty:
                return rows
            code_col = next((c for c in spot_df.columns if "代码" in str(c)), None)
            price_col = next((c for c in spot_df.columns if "最新价" in str(c)), None)
            chg_col = next((c for c in spot_df.columns if "涨跌幅" in str(c)), None)
            vol_col = next((c for c in spot_df.columns if "成交量" in str(c)), None)
            amt_col = next((c for c in spot_df.columns if "成交额" in str(c)), None)
            if not code_col:
                return rows
            spot_map: dict[str, Any] = {}
            for _, srow in spot_df.iterrows():
                sc = str(srow.get(code_col, "")).strip()
                spot_map[sc] = srow
                # akshare 代码格式可能是 sh600519 / sz000001，也存无前缀版本
                if len(sc) >= 2 and sc[:2] in ("sh", "sz", "bj", "SH", "SZ", "BJ"):
                    spot_map[sc[2:]] = srow
            for row in rows:
                code = str(row.get("代码", "")).replace(".SS", "").replace(".SZ", "").replace(".SH", "")
                if code in spot_map:
                    s = spot_map[code]
                    if price_col: row["最新价"] = float(s.get(price_col, 0) or 0)
                    if chg_col: row["涨跌幅"] = f"{float(s.get(chg_col, 0) or 0):+.2f}%"
                    if vol_col: row["成交量"] = int(s.get(vol_col, 0) or 0)
                    if amt_col: row["成交额"] = float(s.get(amt_col, 0) or 0)
        except Exception:
            pass
        return rows

    def _enrich_with_spot(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """用实时行情数据补充热榜条目（缓存优先，非阻塞拉取）。"""
        spot_df = self._try_fetch_spot()
        if spot_df is None:
            return rows
        return self._apply_spot_enrichment(rows, spot_df)

    def _call_llm_analysis(
        self,
        symbol: str,
        price_df: pd.DataFrame,
        trend: Any,
        strategy: Any,
        config: LLMConfig,
    ) -> LLMResult:
        """调用 LLM 分析。失败时返回规则生成的摘要。"""
        from src.agents.llm_analysis_agent import LLMAnalysisAgent

        try:
            llm_agent = LLMAnalysisAgent()
            result = llm_agent.analyze(
                symbol=symbol,
                price_df=price_df,
                trend_result=trend,
                strategy_result=strategy,
                config=config,
            )
            return LLMResult(
                summary=result.summary,
                provider_hint=result.provider_hint,
                finish_reason=result.finish_reason,
            )
        except Exception:
            trend_str = trend.to_dict().get("trend", "震荡")
            return LLMResult(
                summary=f"{symbol} 当前趋势为{trend_str}，建议参考技术指标综合判断。",
                provider_hint="fallback",
                finish_reason="llm_error",
            )

    def _call_llm_decision_tuning(
        self,
        symbol: str,
        trend: Any,
        strategy: Any,
        hot_rows: list[dict[str, Any]],
        sentiment: NewsSentiment,
        config: LLMConfig,
    ) -> LLMTuningResult | None:
        """调用 LLM 决策微调。"""
        try:
            llm_service = get_llm_service()
            trend_dict = trend.to_dict()
            strategy_dict = strategy.to_dict()

            payload = {
                "symbol": symbol,
                "trend": trend_dict,
                "strategy": strategy_dict,
                "risk": {"level": self._assess_risk_level(strategy_dict.get("risk_factors", [])), "items": strategy_dict.get("risk_factors", [])},
                "news_sentiment": sentiment.label,
                "news_confidence": sentiment.confidence,
                "base_score": self._calculate_base_score(trend_dict, strategy_dict, hot_rows, sentiment),
            }

            data = llm_service.call_with_prompt("decision_prompt", payload, config)
            return LLMTuningResult(
                decision=str(data.get("decision", "观望")).strip(),
                confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                score_adjustment=max(-10, min(10, int(round(float(data.get("score_adjustment", 0)))))),
                summary=str(data.get("summary", "规则评分基础上完成微调。")).strip()[:30],
                reasoning=[str(x).strip() for x in data.get("reasoning", []) if str(x).strip()][:3],
            )
        except Exception:
            return None

    def _call_llm_enhance(
        self,
        trend: Any,
        strategy: Any,
        news_items: list[Any],
        config: LLMConfig,
    ) -> LLMEnhanceResult:
        """调用 LLM 深度增强。"""
        try:
            llm_service = get_llm_service()
            payload = {
                "trend": trend.to_dict(),
                "strategy": strategy.to_dict(),
                "risk": strategy.to_dict().get("risk_factors", []),
                "news": [
                    {"source": x.source, "title": x.title, "summary": x.summary}
                    for x in news_items[:10]
                ],
            }
            data = llm_service.call_with_prompt("llm_enhance_prompt", payload, config)
            return LLMEnhanceResult(
                insight=str(data.get("insight", "暂无深度洞察。")).strip()[:50],
                opportunities=[str(x).strip() for x in data.get("opportunities", []) if str(x).strip()][:2],
                risks=[str(x).strip() for x in data.get("risks", []) if str(x).strip()][:2],
            )
        except Exception:
            return LLMEnhanceResult(
                insight="暂无深度洞察。",
                opportunities=["关注趋势延续性与量能确认。", "关注回调后的风险收益比改善。"],
                risks=["警惕短期波动放大导致回撤。", "关注政策与流动性扰动风险。"],
            )

    def _call_llm_report(
        self,
        payload: dict[str, Any],
        config: LLMConfig,
    ) -> dict[str, Any]:
        """调用 LLM 生成研报。"""
        try:
            llm_service = get_llm_service()
            data = llm_service.call_with_prompt("report_prompt", payload, config)
            return {
                "summary": str(data.get("summary", "")).strip(),
                "trend_analysis": data.get("trend_analysis", {}),
                "strategy_advice": data.get("strategy_advice", {}),
                "risk_warnings": data.get("risk_warnings", []),
                "overall_score": data.get("overall_score", {}),
            }
        except Exception:
            # LLM 未配置或调用失败时返回默认结构
            return {
                "summary": f"{payload.get('symbol', '')} 当前趋势为 {payload.get('trend', '未知')}，建议观望。",
                "trend_analysis": {
                    "ma_status": "数据加载中",
                    "macd_signal": "数据加载中",
                    "rsi_zone": "数据加载中",
                    "trend_probability": "中",
                    "analysis": "LLM 服务未配置或调用失败，仅显示基础分析数据。",
                },
                "strategy_advice": {
                    "action": payload.get("strategy", {}).get("action", "观望"),
                    "target_price": payload.get("strategy", {}).get("target_price"),
                    "stop_loss": payload.get("strategy", {}).get("stop_loss"),
                    "position": "轻仓",
                    "preconditions": ["请配置 LLM 服务以获取详细策略建议"],
                    "advice": "请在 .env 文件中配置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 以启用 AI 研报生成功能。",
                },
                "risk_warnings": [
                    {"risk": r, "trigger": "持续关注", "impact": "中"} for r in payload.get("risk_factors", [])[:3]
                ],
                "overall_score": {"technical": 50, "risk_reward": 50, "comprehensive": 50},
            }

    def _build_decision_layer(
        self,
        trend_data: dict[str, Any],
        strategy_data: dict[str, Any],
        risk_items: list[Any],
        hot_rows: list[dict[str, Any]],
        news_sentiment_label: str | None = None,
        llm_tuning: LLMTuningResult | None = None,
    ) -> DecisionLayer:
        """构建决策层。"""
        trend_for_score = self._build_trend_for_score(trend_data)
        risk_level = self._assess_risk_level(risk_items)
        sentiment = news_sentiment_label or self._infer_sentiment_from_hot(hot_rows)

        base_score = self._calculate_base_score_from_factors(trend_for_score, risk_level, sentiment)

        # 策略约束
        strategy_action = str(strategy_data.get("action_advice") or strategy_data.get("action") or "").lower()
        if any(token in strategy_action for token in ["减仓", "观望", "hold", "reduce"]):
            base_score = min(base_score, 74)
        if any(token in strategy_action for token in ["回避", "清仓", "avoid", "exit"]):
            base_score = min(base_score, 34)

        score_adjustment = 0
        decision = self._decision_from_score(base_score)
        confidence = round(max(0.1, min(0.9, 0.35 + (base_score / 100.0) * 0.55)), 2)
        summary = f"规则评分{base_score}，建议{decision}"
        reasoning = [
            f"趋势方向={trend_for_score['direction']}，强度={trend_for_score['strength']}。",
            f"风险等级={risk_level}，进行风险约束。",
            f"情绪={sentiment}，作为辅助修正。",
        ]

        if llm_tuning is not None:
            score_adjustment = max(-10, min(10, llm_tuning.score_adjustment))
            final_score = max(0, min(100, base_score + score_adjustment))
            decision = llm_tuning.decision or self._decision_from_score(final_score)
            confidence = round(max(0.0, min(1.0, llm_tuning.confidence)), 2)
            summary = llm_tuning.summary or summary
            reasoning = llm_tuning.reasoning[:3] if llm_tuning.reasoning else reasoning
            score = final_score
        else:
            score = base_score

        return DecisionLayer(
            decision=decision,
            confidence=confidence,
            score=score,
            summary=summary[:30],
            reasoning=reasoning[:3],
            base_score=base_score,
            score_adjustment=score_adjustment,
        )

    def _resolve_symbol_name(self, symbol: str) -> str:
        """解析股票名称（预建映射 → 热榜缓存 → 在线查询）。"""
        key = symbol.strip().upper()
        if not key:
            return "-"
        if key in self._symbol_name_cache:
            return self._symbol_name_cache[key]

        # 1. 预建代码→名称映射（零网络延迟，覆盖 60+ 常见股票）
        name = _CODE_TO_NAME.get(key) or _CODE_TO_NAME.get(key.upper())
        if name:
            self._symbol_name_cache[key] = name
            return name

        # 2. 热榜名称缓存（由热榜接口动态构建，覆盖更广）
        try:
            from src.api.app import _get_name_cache
            hot_names = _get_name_cache()
            if hot_names:
                # 代码→名称（反向搜索热榜缓存）
                for _n, _c in hot_names.items():
                    if _c.upper() == key:
                        self._symbol_name_cache[key] = _n
                        return _n
        except Exception:
            pass

        # 3. 在线查询（akshare → yfinance，仅在前两步未命中时）
        name = key
        cn_code = self.data_agent._to_cn_code(key)
        if cn_code:
            try:
                import akshare as ak
                info_df = ak.stock_individual_info_em(symbol=cn_code)
                if info_df is not None and not info_df.empty:
                    item_col = "item" if "item" in info_df.columns else "项目"
                    value_col = "value" if "value" in info_df.columns else "值"
                    for _, row in info_df.iterrows():
                        item = str(row.get(item_col, ""))
                        if "简称" in item or "名称" in item:
                            candidate = str(row.get(value_col, "")).strip()
                            if candidate:
                                name = candidate
                                break
            except Exception:
                name = key
        else:
            try:
                import yfinance as yf
                yahoo_symbol = self.data_agent._to_yahoo_symbol(key)
                info = yf.Ticker(yahoo_symbol).info
                candidate = str(info.get("shortName") or info.get("longName") or "").strip()
                if candidate:
                    name = candidate
            except Exception:
                name = key

        self._symbol_name_cache[key] = name
        return name

    @staticmethod
    def _to_action_label(trend: str) -> str:
        if trend == "上涨":
            return "buy"
        if trend == "下跌":
            return "sell"
        return "hold"

    @staticmethod
    def _build_trend_for_score(trend_data: dict[str, Any]) -> dict[str, str]:
        trend = str(trend_data.get("trend", "")).strip()
        confidence = float(trend_data.get("confidence", 0.5))
        if confidence > 1.0:
            confidence = confidence / 100.0
        confidence = max(0.0, min(1.0, confidence))

        direction = "sideways"
        if trend == "上涨":
            direction = "up"
        elif trend == "下跌":
            direction = "down"

        strength = "strong" if confidence >= 0.72 else "normal"
        return {"direction": direction, "strength": strength}

    @staticmethod
    def _assess_risk_level(risk_items: list[Any]) -> str:
        if not risk_items:
            return "low"
        text = " ".join(str(item) for item in risk_items).lower()
        severe_words = ["极端", "爆仓", "崩盘", "black swan", "liquidity crisis", "重大", "清仓", "回避"]
        high_words = ["高风险", "回撤", "波动", "杠杆", "监管", "违约", "不确定"]
        if any(word in text for word in severe_words):
            return "high"
        if any(word in text for word in high_words) or len(risk_items) >= 4:
            return "medium"
        return "low"

    @staticmethod
    def _infer_sentiment_from_hot(hot_rows: list[dict[str, Any]]) -> str:
        if not hot_rows:
            return "neutral"
        pct_values: list[float] = []
        for row in hot_rows[:10]:
            raw = row.get("涨跌幅") or row.get("涨跌幅%") or row.get("change_pct") or row.get("pct_chg")
            if raw is None:
                continue
            try:
                pct_values.append(float(str(raw).replace("%", "")))
            except Exception:
                continue
        if not pct_values:
            return "neutral"
        mean_pct = sum(pct_values) / len(pct_values)
        if mean_pct >= 1.2:
            return "positive"
        if mean_pct <= -1.2:
            return "negative"
        return "neutral"

    @staticmethod
    def _calculate_base_score_from_factors(trend: dict[str, str], risk_level: str, sentiment: str) -> int:
        score = 50
        if trend["direction"] == "up":
            score += 15
        elif trend["direction"] == "down":
            score -= 15
        if trend["strength"] == "strong":
            score += 5
        if risk_level == "high":
            score -= 25
        elif risk_level == "medium":
            score -= 10
        if sentiment == "positive":
            score += 5
        elif sentiment == "negative":
            score -= 5
        return max(0, min(100, score))

    def _calculate_base_score(
        self,
        trend_data: dict[str, Any],
        strategy_data: dict[str, Any],
        hot_rows: list[dict[str, Any]],
        sentiment: NewsSentiment,
    ) -> int:
        trend_for_score = self._build_trend_for_score(trend_data)
        risk_level = self._assess_risk_level(strategy_data.get("risk_factors", []))
        return self._calculate_base_score_from_factors(trend_for_score, risk_level, sentiment.label)

    @staticmethod
    def _decision_from_score(score: int) -> str:
        if score >= 78:
            return "强烈看多"
        if score >= 62:
            return "偏多"
        if score >= 45:
            return "观望"
        if score >= 30:
            return "偏空"
        return "强烈回避"


def safe_response(callable_fn, *args, **kwargs) -> dict[str, Any]:
    """安全包装服务调用，统一异常处理。"""
    try:
        status, data, error, meta = callable_fn(*args, **kwargs)
        code = 0 if status in {"success", "empty"} else 1
        message = "success" if status == "success" else ("empty" if status == "empty" else (error or "error"))
        return {"code": code, "message": message, "status": status, "data": data, "error": error, "meta": meta}
    except Exception as exc:
        return {
            "code": 1,
            "message": str(exc),
            "status": "error",
            "data": None,
            "error": str(exc),
            "meta": {"timestamp": now_iso()},
        }

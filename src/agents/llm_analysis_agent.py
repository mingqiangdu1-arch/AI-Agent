from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib import error, request

import pandas as pd

from .strategy_generation_agent import StrategyResult
from .trend_analysis_agent import TrendAnalysisResult


@dataclass
class LLMAnalysisConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.2
    max_tokens: int = 800


@dataclass
class LLMAnalysisResult:
    summary: str
    provider_hint: str
    finish_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMDecisionTuningResult:
    decision: str
    confidence: float
    score_adjustment: int
    summary: str
    reasoning: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMAnalysisAgent:
    """Use an OpenAI-compatible endpoint to generate a narrative investment analysis."""

    def analyze(
        self,
        symbol: str,
        price_df: pd.DataFrame,
        trend_result: TrendAnalysisResult,
        strategy_result: StrategyResult,
        config: LLMAnalysisConfig,
    ) -> LLMAnalysisResult:
        endpoint = self._resolve_chat_endpoint(config.base_url)
        payload = {
            "model": config.model,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是资深A股/美股投研分析助手。请基于输入的结构化数据输出简洁、可执行、风险导向的中文分析。"
                        "不得承诺收益，不得给出绝对化结论。"
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_user_prompt(symbol, price_df, trend_result, strategy_result),
                },
            ],
        }

        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=25) as resp:
                content = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
            raise RuntimeError(f"LLM 接口调用失败: HTTP {exc.code} {detail[:240]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"LLM 接口不可达: {exc.reason}") from exc

        try:
            data = json.loads(content)
            choice = data["choices"][0]
            summary = choice["message"]["content"]
            finish_reason = str(choice.get("finish_reason", ""))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("LLM 返回格式异常，无法解析分析结果。") from exc

        return LLMAnalysisResult(
            summary=str(summary).strip(),
            provider_hint=endpoint,
            finish_reason=finish_reason,
        )

    def tune_decision_layer(
        self,
        symbol: str,
        trend: dict[str, Any],
        strategy: dict[str, Any],
        risk: dict[str, Any],
        hot: dict[str, Any],
        base_score: int,
        config: LLMAnalysisConfig,
    ) -> LLMDecisionTuningResult:
        endpoint = self._resolve_chat_endpoint(config.base_url)
        payload = {
            "model": config.model,
            "temperature": min(max(config.temperature, 0.0), 0.5),
            "max_tokens": min(max(int(config.max_tokens), 256), 900),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个量化投研决策辅助系统。你将收到 trend、strategy、risk、hot、base_score。"
                        "你必须只输出 JSON，字段固定为 decision/confidence/score_adjustment/summary/reasoning。"
                        "score_adjustment 必须是 -10 到 +10 的整数。不要输出 score。"
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_decision_tuning_prompt(
                        symbol=symbol,
                        trend=trend,
                        strategy=strategy,
                        risk=risk,
                        hot=hot,
                        base_score=base_score,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        }

        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=25) as resp:
                content = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
            raise RuntimeError(f"LLM 决策微调调用失败: HTTP {exc.code} {detail[:240]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"LLM 决策微调接口不可达: {exc.reason}") from exc

        try:
            data = json.loads(content)
            raw = str(data["choices"][0]["message"]["content"]).strip()
            parsed = self._parse_json_object(raw)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("LLM 决策微调返回格式异常，无法解析。") from exc

        decision = str(parsed.get("decision", "")).strip() or "观望"
        confidence = float(parsed.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        adjustment_raw = parsed.get("score_adjustment", 0)
        try:
            adjustment = int(round(float(adjustment_raw)))
        except Exception:
            adjustment = 0
        adjustment = max(-10, min(10, adjustment))

        summary = str(parsed.get("summary", "")).strip()
        if not summary:
            summary = "规则评分基础上完成微调。"
        if len(summary) > 30:
            summary = summary[:30]

        reasoning_raw = parsed.get("reasoning", [])
        if isinstance(reasoning_raw, list):
            reasoning = [str(item).strip() for item in reasoning_raw if str(item).strip()][:3]
        else:
            reasoning = []
        while len(reasoning) < 3:
            reasoning.append("信号信息有限，保持审慎。")

        return LLMDecisionTuningResult(
            decision=decision,
            confidence=round(confidence, 2),
            score_adjustment=adjustment,
            summary=summary,
            reasoning=reasoning,
        )

    def test_connection(self, config: LLMAnalysisConfig) -> tuple[bool, str]:
        endpoint = self._resolve_chat_endpoint(config.base_url)
        payload = {
            "model": config.model,
            "temperature": 0.0,
            "max_tokens": 16,
            "messages": [
                {"role": "system", "content": "你是API连通性检测助手。"},
                {"role": "user", "content": "回复: ok"},
            ],
        }

        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=20) as resp:
                content = resp.read().decode("utf-8")
            data = json.loads(content)
            _ = data["choices"][0]["message"]["content"]
            return True, f"连接成功: {endpoint}"
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
            return False, f"HTTP {exc.code}: {detail[:180]}"
        except Exception as exc:
            return False, str(exc)

    def generate_hot_rank(
        self,
        config: LLMAnalysisConfig,
        limit: int = 10,
        market_hint: str = "A股",
        source_label: str = "LLM推断",
    ) -> pd.DataFrame:
        count = max(1, min(int(limit), 20))
        endpoint = self._resolve_chat_endpoint(config.base_url)
        payload = {
            "model": config.model,
            "temperature": min(max(config.temperature, 0.0), 0.8),
            "max_tokens": max(512, int(config.max_tokens)),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是财经信息整理助手。请输出结构化 JSON，不要输出任何额外解释。"
                        "优先检索并参考同花顺(10jqka)当日热门个股信息。"
                        "当无法确认实时数据时，基于近期公开市场关注度给出合理候选并保持字段完整。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"请给出{market_hint}热榜 TOP{count}，只输出 JSON 数组。"
                        "优先依据同花顺(10jqka)当日热榜信息。"
                        "每个元素必须包含字段：排名(整数)、代码(字符串)、名称(字符串)、热度(数值)、涨跌幅(字符串，示例:+1.23%/ -0.56%)。"
                        "禁止输出 markdown 说明。"
                    ),
                },
            ],
        }

        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=25) as resp:
                content = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
            raise RuntimeError(f"LLM 热榜调用失败: HTTP {exc.code} {detail[:240]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"LLM 热榜接口不可达: {exc.reason}") from exc

        try:
            data = json.loads(content)
            raw_text = str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("LLM 热榜返回格式异常，无法解析。") from exc

        rows = self._parse_hot_rank_json(raw_text)
        if not rows:
            raise RuntimeError("LLM 热榜解析后为空。")

        normalized: list[dict[str, Any]] = []
        for item in rows[:count]:
            rank = int(item.get("排名", len(normalized) + 1))
            code = str(item.get("代码", "")).strip().upper()
            name = str(item.get("名称", "")).strip()
            hot = item.get("热度", 0)
            chg = str(item.get("涨跌幅", "")).strip()
            normalized.append(
                {
                    "来源": source_label,
                    "排名": rank,
                    "代码": code,
                    "名称": name,
                    "热度": float(hot) if str(hot).strip() else 0.0,
                    "涨跌幅": chg,
                }
            )

        out = pd.DataFrame(normalized)
        out = out.sort_values("排名").reset_index(drop=True)
        return out

    @staticmethod
    def _resolve_chat_endpoint(base_url: str) -> str:
        cleaned = base_url.strip().rstrip("/")
        if cleaned.endswith("/chat/completions"):
            return cleaned
        if cleaned.endswith("/openai"):
            return f"{cleaned}/chat/completions"
        if re.search(r"/v\d+$", cleaned):
            return f"{cleaned}/chat/completions"
        return f"{cleaned}/v1/chat/completions"

    @staticmethod
    def _parse_hot_rank_json(raw_text: str) -> list[dict[str, Any]]:
        text = raw_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            if text.endswith("```"):
                text = text[:-3].strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass

        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            return []
        return []

    @staticmethod
    def _parse_json_object(raw_text: str) -> dict[str, Any]:
        text = raw_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            if text.endswith("```"):
                text = text[:-3].strip()

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
        return {}

    @staticmethod
    def _build_decision_tuning_prompt(
        symbol: str,
        trend: dict[str, Any],
        strategy: dict[str, Any],
        risk: dict[str, Any],
        hot: dict[str, Any],
        base_score: int,
    ) -> str:
        payload = {
            "symbol": symbol,
            "trend": trend,
            "strategy": strategy,
            "risk": risk,
            "hot": hot,
            "base_score": base_score,
            "task": {
                "decision": ["强烈看多", "偏多", "观望", "偏空", "强烈回避"],
                "score_adjustment_range": [-10, 10],
                "constraints": [
                    "风险高时必须下调评分",
                    "情绪极端时降低confidence",
                    "不允许大幅偏离base_score",
                ],
            },
            "output_schema": {
                "decision": "string",
                "confidence": "float_0_to_1",
                "score_adjustment": "int_-10_to_10",
                "summary": "string_max_30_chars",
                "reasoning": ["string", "string", "string"],
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _build_user_prompt(
        symbol: str,
        price_df: pd.DataFrame,
        trend_result: TrendAnalysisResult,
        strategy_result: StrategyResult,
    ) -> str:
        """构建LLM分析提示词。精简数据，减少token消耗。"""
        latest_rows = price_df.tail(5).copy()
        latest_rows.index = latest_rows.index.astype(str)
        compact_rows = latest_rows[["open", "high", "low", "close", "volume"]].to_dict(orient="index")

        trend_dict = trend_result.to_dict()
        strategy_dict = strategy_result.to_dict()

        prompt_payload = {
            "symbol": symbol.upper(),
            "trend": {
                "direction": trend_dict.get("trend"),
                "confidence": trend_dict.get("confidence"),
                "ma": trend_dict.get("ma_summary"),
                "macd": trend_dict.get("macd_summary"),
                "rsi": trend_dict.get("rsi_summary"),
            },
            "strategy": {
                "advice": strategy_dict.get("attention_advice"),
                "target": strategy_dict.get("target_price"),
                "stop_loss": strategy_dict.get("stop_loss_price"),
            },
            "recent_5days": compact_rows,
            "risk_alerts": trend_dict.get("risk_alerts", []),
        }
        return json.dumps(prompt_payload, ensure_ascii=False)

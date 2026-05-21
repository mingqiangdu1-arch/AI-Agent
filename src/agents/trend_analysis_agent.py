from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


@dataclass
class TrendAnalysisResult:
    """趋势分析结果，基于技术分析三大假设和价量时空四要素。"""

    trend: str  # 上涨/下跌/震荡
    confidence: float  # 置信度 0-1
    ma_summary: str  # 均线系统摘要
    macd_summary: str  # MACD动能摘要
    rsi_summary: str  # RSI强弱摘要
    risk_alerts: list[str]  # 风险提示列表
    latest_close: float  # 最新收盘价

    # 新增字段：更详细的分析维度
    ma_details: dict[str, Any] = field(default_factory=dict)  # 均线详细数据
    macd_details: dict[str, Any] = field(default_factory=dict)  # MACD详细数据
    rsi_details: dict[str, Any] = field(default_factory=dict)  # RSI详细数据
    volume_analysis: dict[str, Any] = field(default_factory=dict)  # 量价分析
    trend_strength: str = "normal"  # 趋势强度：strong/normal/weak

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrendAnalysisAgent:
    """Agent 2: 基于历史行情输出趋势研判与风险提示。"""

    def analyze(self, price_df: pd.DataFrame) -> TrendAnalysisResult:
        """执行趋势分析，基于技术分析三大假设。

        假设1：市场行为涵盖一切信息 - 分析价格和成交量
        假设2：价格沿趋势方式演变 - 识别趋势方向
        假设3：历史会重演 - 使用经典技术指标
        """
        if isinstance(price_df.columns, pd.MultiIndex):
            if price_df.columns.nlevels >= 2:
                lvl0 = set(price_df.columns.get_level_values(0))
                need = {"open", "high", "low", "close", "volume"}
                if need.intersection(lvl0):
                    price_df = price_df.copy()
                    price_df.columns = price_df.columns.get_level_values(0)
                else:
                    price_df = price_df.copy()
                    price_df.columns = price_df.columns.get_level_values(-1)

        required_cols = {"open", "high", "low", "close", "volume"}
        missing = required_cols - set(price_df.columns)
        if missing:
            raise ValueError(f"输入数据缺少必要字段: {sorted(missing)}")

        df = price_df.copy().sort_index()
        if len(df) < 35:
            raise ValueError("趋势分析至少需要 35 条交易日数据。")

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        volume = df["volume"].astype(float)

        # ─── 均线系统（MA）────────────────────────────────
        # 短期：MA5/MA10，中期：MA20，长期：MA60
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean() if len(close) >= 60 else ma20

        # ─── MACD系统 ──────────────────────────────────────
        # EMA(12) - EMA(26) = DIFF
        # DEA = DIFF的9日EMA
        # MACD = 2 × (DIFF - DEA)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal

        # ─── RSI系统 ───────────────────────────────────────
        # RSI(14) = A / (A + B) × 100
        # A = 14日内上涨幅度之和
        # B = 14日内下跌幅度之和的绝对值
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))

        # ─── ATR（平均真实波幅）─────────────────────────────
        # 用于策略生成中的止损止盈计算
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()

        # ─── 提取最新值 ────────────────────────────────────
        latest_close = float(close.iloc[-1])
        latest_ma5 = float(ma5.iloc[-1])
        latest_ma10 = float(ma10.iloc[-1])
        latest_ma20 = float(ma20.iloc[-1])
        latest_ma60 = float(ma60.iloc[-1]) if pd.notna(ma60.iloc[-1]) else latest_ma20
        latest_macd = float(macd.iloc[-1])
        latest_signal = float(signal.iloc[-1])
        latest_hist = float(hist.iloc[-1])
        latest_rsi = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0
        latest_atr = float(atr14.iloc[-1]) if pd.notna(atr14.iloc[-1]) else latest_close * 0.02

        # ─── 趋势判断（基于假设2：价格沿趋势方式演变）──────
        trend, confidence = self._judge_trend(
            latest_close=latest_close,
            ma5=latest_ma5,
            ma10=latest_ma10,
            ma20=latest_ma20,
            ma60=latest_ma60,
            macd=latest_macd,
            signal=latest_signal,
            hist=latest_hist,
        )

        # ─── 趋势强度判断 ──────────────────────────────────
        trend_strength = self._judge_trend_strength(
            confidence=confidence,
            ma_alignment=(latest_close > latest_ma5 > latest_ma10 > latest_ma20) or
                         (latest_close < latest_ma5 < latest_ma10 < latest_ma20),
            macd_strength=abs(latest_hist),
            atr_ratio=latest_atr / latest_close if latest_close > 0 else 0,
        )

        # ─── 量价分析（基于价量时空四要素）─────────────────
        volume_analysis = self._analyze_volume(close, volume, trend)

        # ─── 生成摘要 ──────────────────────────────────────
        ma_summary = self._build_ma_summary(latest_close, latest_ma5, latest_ma10, latest_ma20)
        macd_summary = self._build_macd_summary(latest_macd, latest_signal, latest_hist)
        rsi_summary = self._build_rsi_summary(latest_rsi)

        # ─── 风险提示 ──────────────────────────────────────
        risk_alerts = self._build_risk_alerts(
            close=close,
            volume=volume,
            latest_rsi=latest_rsi,
            latest_macd=latest_macd,
            latest_signal=latest_signal,
            trend=trend,
            volume_analysis=volume_analysis,
        )

        return TrendAnalysisResult(
            trend=trend,
            confidence=confidence,
            ma_summary=ma_summary,
            macd_summary=macd_summary,
            rsi_summary=rsi_summary,
            risk_alerts=risk_alerts,
            latest_close=latest_close,
            ma_details={
                "ma5": latest_ma5,
                "ma10": latest_ma10,
                "ma20": latest_ma20,
                "ma60": latest_ma60,
                "alignment": self._get_ma_alignment(latest_close, latest_ma5, latest_ma10, latest_ma20),
            },
            macd_details={
                "diff": latest_macd,
                "dea": latest_signal,
                "macd_hist": latest_hist,
                "above_zero": latest_macd > 0 and latest_signal > 0,
                "golden_cross": latest_macd > latest_signal and latest_hist > 0,
            },
            rsi_details={
                "rsi14": latest_rsi,
                "zone": self._get_rsi_zone(latest_rsi),
                "overbought": latest_rsi >= 70,
                "oversold": latest_rsi <= 30,
            },
            volume_analysis=volume_analysis,
            trend_strength=trend_strength,
        )

    @staticmethod
    def _judge_trend(
        latest_close: float,
        ma5: float,
        ma10: float,
        ma20: float,
        ma60: float,
        macd: float,
        signal: float,
        hist: float,
    ) -> tuple[str, float]:
        """趋势判断，基于均线系统和MACD。

        规则：
        - 多头排列（价格>MA5>MA10>MA20）→ 上涨
        - 空头排列（价格<MA5<MA10<MA20）→ 下跌
        - 其他情况 → 震荡

        置信度计算：
        - 基础分 0.55
        - 每个确认信号 +0.1
        - 上限 0.95
        """
        score = 0

        # 均线排列信号（核心信号）
        if latest_close > ma5 > ma10 > ma20:
            score += 2  # 多头排列
        elif latest_close < ma5 < ma10 < ma20:
            score -= 2  # 空头排列

        # MACD信号（动能确认）
        if macd > signal:
            score += 1  # DIFF > DEA，动能偏多
        else:
            score -= 1  # DIFF < DEA，动能偏空

        if hist > 0:
            score += 1  # MACD柱状线为正
        else:
            score -= 1  # MACD柱状线为负

        # 趋势判断
        if score >= 2:
            return "上涨", min(0.95, 0.55 + 0.1 * score)
        if score <= -2:
            return "下跌", min(0.95, 0.55 + 0.1 * abs(score))
        return "震荡", 0.58

    @staticmethod
    def _judge_trend_strength(
        confidence: float,
        ma_alignment: bool,
        macd_strength: float,
        atr_ratio: float,
    ) -> str:
        """判断趋势强度。

        强趋势条件：
        - 置信度 >= 0.72
        - 均线完全排列
        - MACD柱状线较强
        """
        if confidence >= 0.72 and ma_alignment:
            return "strong"
        if confidence <= 0.55 or (atr_ratio > 0.03 and not ma_alignment):
            return "weak"
        return "normal"

    @staticmethod
    def _get_ma_alignment(close: float, ma5: float, ma10: float, ma20: float) -> str:
        """获取均线排列状态。"""
        if close > ma5 > ma10 > ma20:
            return "bullish"  # 多头排列
        if close < ma5 < ma10 < ma20:
            return "bearish"  # 空头排列
        return "mixed"  # 交错

    @staticmethod
    def _get_rsi_zone(rsi: float) -> str:
        """获取RSI所在区间。"""
        if rsi >= 80:
            return "extreme_overbought"  # 极度超买
        if rsi >= 70:
            return "overbought"  # 超买
        if rsi >= 60:
            return "bullish"  # 偏强
        if rsi >= 40:
            return "neutral"  # 中性
        if rsi >= 30:
            return "bearish"  # 偏弱
        if rsi >= 20:
            return "oversold"  # 超卖
        return "extreme_oversold"  # 极度超卖

    @staticmethod
    def _analyze_volume(
        close: pd.Series,
        volume: pd.Series,
        trend: str,
    ) -> dict[str, Any]:
        """量价分析，基于价量时空四要素。

        核心原则：
        - 价涨量增：正常上涨
        - 价创新高量未创新高：潜在反转
        - 高位放量滞涨：可能见顶
        """
        if len(close) < 20 or len(volume) < 20:
            return {"status": "insufficient_data"}

        # 计算量比（5日均量/20日均量）
        vol_5 = float(volume.tail(5).mean())
        vol_20 = float(volume.tail(20).mean())
        vol_ratio = vol_5 / max(vol_20, 1)

        # 计算近期涨跌幅
        recent_return = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) if len(close) >= 6 else 0

        # 量价关系判断
        if trend == "上涨":
            if vol_ratio >= 1.2:
                volume_status = "healthy"  # 价涨量增，健康上涨
                volume_hint = "成交量放大配合上涨，趋势有效"
            elif vol_ratio < 0.85 and recent_return > 0.03:
                volume_status = "divergence"  # 量价背离
                volume_hint = "价格上行但成交量萎缩，需警惕背离"
            else:
                volume_status = "normal"
                volume_hint = "成交量与价格关系正常"
        elif trend == "下跌":
            if vol_ratio > 1.2:
                volume_status = "panic"  # 放量下跌
                volume_hint = "下跌伴随放量，抛压较重"
            else:
                volume_status = "normal"
                volume_hint = "下跌过程中成交量正常"
        else:
            volume_status = "neutral"
            volume_hint = "震荡行情，成交量无明显特征"

        return {
            "vol_ratio": round(vol_ratio, 2),
            "vol_5_avg": round(vol_5, 0),
            "vol_20_avg": round(vol_20, 0),
            "recent_return": round(recent_return * 100, 2),
            "status": volume_status,
            "hint": volume_hint,
        }

    @staticmethod
    def _build_ma_summary(close: float, ma5: float, ma10: float, ma20: float) -> str:
        if close > ma5 > ma10 > ma20:
            return "短中期均线呈多头排列，价格位于均线上方。"
        if close < ma5 < ma10 < ma20:
            return "短中期均线呈空头排列，价格位于均线下方。"
        return "均线排列交错，趋势一致性一般。"

    @staticmethod
    def _build_macd_summary(macd: float, signal: float, hist: float) -> str:
        if macd > signal and hist > 0:
            return "MACD 位于信号线上方，动能偏多。"
        if macd < signal and hist < 0:
            return "MACD 位于信号线下方，动能偏空。"
        return "MACD 与信号线接近，短线动能不明显。"

    @staticmethod
    def _build_rsi_summary(rsi: float) -> str:
        if rsi >= 70:
            return f"RSI={rsi:.1f}，处于偏高区间，存在超买风险。"
        if rsi <= 30:
            return f"RSI={rsi:.1f}，处于偏低区间，存在超卖反弹可能。"
        return f"RSI={rsi:.1f}，处于中性区间。"

    @staticmethod
    def _build_risk_alerts(
        close: pd.Series,
        volume: pd.Series,
        latest_rsi: float,
        latest_macd: float,
        latest_signal: float,
        trend: str,
        volume_analysis: dict[str, Any] | None = None,
    ) -> list[str]:
        """构建风险提示，基于技术分析原理。

        风险信号来源：
        1. 量价背离（价量时空四要素）
        2. RSI超买超卖（反趋势类指标）
        3. MACD动能减弱（趋势类指标）
        """
        alerts: list[str] = []

        # 量价分析风险
        if volume_analysis:
            if volume_analysis.get("status") == "divergence":
                alerts.append("价格上行但成交量未同步放大，需警惕量价背离。")
            elif volume_analysis.get("status") == "panic":
                alerts.append("下跌伴随放量，短期抛压偏强。")

        # RSI风险（基于RSI指标原理：>70超买，<30超卖）
        if latest_rsi >= 70:
            alerts.append("RSI进入超买区间（≥70），需防范短线回调。")
        elif latest_rsi >= 80:
            alerts.append("RSI处于极度超买区间（≥80），回调风险较高。")
        elif latest_rsi <= 30:
            alerts.append("RSI进入超卖区间（≤30），波动可能加大。")
        elif latest_rsi <= 20:
            alerts.append("RSI处于极度超卖区间（≤20），可能出现反弹。")

        # MACD风险（基于MACD原理：DIFF与DEA的关系）
        if latest_macd < latest_signal and trend == "上涨":
            alerts.append("趋势偏多但MACD转弱（DIFF<DEA），注意节奏变化。")

        # 默认提示
        if not alerts:
            alerts.append("当前未出现显著异常信号，仍需结合市场环境动态跟踪。")

        return alerts

    @staticmethod
    def render_text_report(result: TrendAnalysisResult) -> str:
        lines = [
            f"趋势判断: {result.trend} (置信度 {result.confidence:.2f})",
            f"最新收盘价: {result.latest_close:.2f}",
            f"均线摘要: {result.ma_summary}",
            f"MACD 摘要: {result.macd_summary}",
            f"RSI 摘要: {result.rsi_summary}",
            "风险提示:",
        ]
        lines.extend([f"- {msg}" for msg in result.risk_alerts])
        return "\n".join(lines)

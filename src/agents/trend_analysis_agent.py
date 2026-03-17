from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass
class TrendAnalysisResult:
    trend: str
    confidence: float
    ma_summary: str
    macd_summary: str
    rsi_summary: str
    risk_alerts: list[str]
    latest_close: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrendAnalysisAgent:
    """Agent 2: 基于历史行情输出趋势研判与风险提示。"""

    def analyze(self, price_df: pd.DataFrame) -> TrendAnalysisResult:
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
        volume = df["volume"].astype(float)

        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))

        latest_close = float(close.iloc[-1])
        latest_ma5 = float(ma5.iloc[-1])
        latest_ma10 = float(ma10.iloc[-1])
        latest_ma20 = float(ma20.iloc[-1])
        latest_macd = float(macd.iloc[-1])
        latest_signal = float(signal.iloc[-1])
        latest_hist = float(hist.iloc[-1])
        latest_rsi = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0

        trend, confidence = self._judge_trend(
            latest_close=latest_close,
            ma5=latest_ma5,
            ma10=latest_ma10,
            ma20=latest_ma20,
            macd=latest_macd,
            signal=latest_signal,
            hist=latest_hist,
        )

        ma_summary = self._build_ma_summary(latest_close, latest_ma5, latest_ma10, latest_ma20)
        macd_summary = self._build_macd_summary(latest_macd, latest_signal, latest_hist)
        rsi_summary = self._build_rsi_summary(latest_rsi)
        risk_alerts = self._build_risk_alerts(
            close=close,
            volume=volume,
            latest_rsi=latest_rsi,
            latest_macd=latest_macd,
            latest_signal=latest_signal,
            trend=trend,
        )

        return TrendAnalysisResult(
            trend=trend,
            confidence=confidence,
            ma_summary=ma_summary,
            macd_summary=macd_summary,
            rsi_summary=rsi_summary,
            risk_alerts=risk_alerts,
            latest_close=latest_close,
        )

    @staticmethod
    def _judge_trend(
        latest_close: float,
        ma5: float,
        ma10: float,
        ma20: float,
        macd: float,
        signal: float,
        hist: float,
    ) -> tuple[str, float]:
        score = 0

        if latest_close > ma5 > ma10 > ma20:
            score += 2
        elif latest_close < ma5 < ma10 < ma20:
            score -= 2

        if macd > signal:
            score += 1
        else:
            score -= 1

        if hist > 0:
            score += 1
        else:
            score -= 1

        if score >= 2:
            return "上涨", min(0.95, 0.55 + 0.1 * score)
        if score <= -2:
            return "下跌", min(0.95, 0.55 + 0.1 * abs(score))
        return "震荡", 0.58

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
    ) -> list[str]:
        alerts: list[str] = []

        recent_return = (close.iloc[-1] / close.iloc[-6]) - 1 if len(close) >= 6 else 0
        vol_ratio = volume.iloc[-5:].mean() / max(volume.iloc[-20:].mean(), 1)

        if trend == "上涨" and vol_ratio < 0.85 and recent_return > 0.03:
            alerts.append("价格上行但成交量未同步放大，需警惕量价背离。")

        if trend == "下跌" and vol_ratio > 1.2:
            alerts.append("下跌伴随放量，短期抛压偏强。")

        if latest_rsi >= 70:
            alerts.append("指标进入超买区间，需防范短线回调。")
        elif latest_rsi <= 30:
            alerts.append("指标进入超卖区间，波动可能加大。")

        if latest_macd < latest_signal and trend == "上涨":
            alerts.append("趋势偏多但 MACD 转弱，注意节奏变化。")

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

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from .trend_analysis_agent import TrendAnalysisResult


@dataclass
class StrategyResult:
    attention_advice: str
    attention_range: str
    target_price: float
    stop_loss_price: float
    risk_factors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StrategyGenerationAgent:
    """Agent 3: 基于趋势结果生成结构化策略建议。"""

    def generate(self, price_df: pd.DataFrame, trend_result: TrendAnalysisResult) -> StrategyResult:
        required_cols = {"high", "low", "close"}
        missing = required_cols - set(price_df.columns)
        if missing:
            raise ValueError(f"输入数据缺少必要字段: {sorted(missing)}")

        df = price_df.copy().sort_index()
        if len(df) < 25:
            raise ValueError("策略生成至少需要 25 条交易日数据。")

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        ma10 = float(close.rolling(10).mean().iloc[-1])
        ma20 = float(close.rolling(20).mean().iloc[-1])
        latest_close = float(close.iloc[-1])

        tr = pd.concat(
            [
                (high - low),
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr14 = float(tr.rolling(14).mean().iloc[-1])
        atr14 = atr14 if atr14 > 0 else latest_close * 0.015

        if trend_result.trend == "上涨":
            attention_advice = "建议近期关注"
            entry_low = min(ma10, latest_close * 0.985)
            entry_high = max(ma10, latest_close * 1.005)
            target_price = latest_close + 2.0 * atr14
            stop_loss = min(ma20, latest_close - 1.2 * atr14)
        elif trend_result.trend == "震荡":
            attention_advice = "建议观察为主，择机轻仓"
            entry_low = min(ma20, latest_close * 0.98)
            entry_high = max(ma10, latest_close * 1.01)
            target_price = latest_close + 1.2 * atr14
            stop_loss = latest_close - 1.1 * atr14
        else:
            attention_advice = "暂不建议主动关注，等待企稳信号"
            entry_low = min(ma20, latest_close * 0.97)
            entry_high = min(ma10, latest_close * 0.99)
            target_price = latest_close + 0.8 * atr14
            stop_loss = latest_close - 0.8 * atr14

        risk_factors = list(trend_result.risk_alerts)
        if trend_result.confidence < 0.62:
            risk_factors.append("当前趋势置信度较低，建议降低仓位。")

        if stop_loss >= target_price:
            target_price = latest_close + 1.2 * atr14
            stop_loss = latest_close - 1.0 * atr14

        return StrategyResult(
            attention_advice=attention_advice,
            attention_range=f"{entry_low:.2f} - {entry_high:.2f}",
            target_price=round(target_price, 2),
            stop_loss_price=round(stop_loss, 2),
            risk_factors=risk_factors,
        )

    @staticmethod
    def render_text_report(result: StrategyResult) -> str:
        lines = [
            f"关注建议: {result.attention_advice}",
            f"关注区间: {result.attention_range}",
            f"目标价格: {result.target_price:.2f}",
            f"止损价格: {result.stop_loss_price:.2f}",
            "风险提示:",
        ]
        lines.extend([f"- {item}" for item in result.risk_factors])
        return "\n".join(lines)

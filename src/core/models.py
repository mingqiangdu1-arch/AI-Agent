"""统一数据模型定义。

定义服务层和 API 层共享的数据结构，确保类型安全。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


# ─── 分析结果模型 ───────────────────────────────────────────────


@dataclass
class TrendData:
    """趋势分析结果。"""

    trend: str  # 上涨/下跌/震荡
    confidence: float
    ma_summary: str
    macd_summary: str
    rsi_summary: str
    risk_alerts: list[str]
    latest_close: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyData:
    """策略生成结果。"""

    attention_advice: str
    attention_range: str
    target_price: float
    stop_loss_price: float
    risk_factors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsSentiment:
    """新闻情绪分析结果。"""

    label: Literal["positive", "neutral", "negative"] = "neutral"
    score: float = 0.0
    confidence: float = 0.2
    reasoning: list[str] = field(default_factory=lambda: ["信息有限，保持中性评估。"] * 3)
    distribution: dict[str, int] = field(
        default_factory=lambda: {"positive": 0, "neutral": 0, "negative": 0}
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsItem:
    """单条新闻。"""

    source: str
    title: str
    summary: str
    url: str
    published_at: str
    sentiment_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsResult:
    """新闻聚合结果。"""

    query: str
    as_of: str
    summary: dict[str, Any]
    sentiment: NewsSentiment
    items: list[NewsItem]
    sources: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sentiment"] = self.sentiment.to_dict()
        return data


@dataclass
class DecisionLayer:
    """投资决策层结果。"""

    decision: str  # 强烈看多/偏多/观望/偏空/强烈回避
    confidence: float
    score: int
    summary: str
    reasoning: list[str]
    base_score: int = 0
    score_adjustment: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMResult:
    """LLM 分析结果。"""

    summary: str
    provider_hint: str
    finish_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMTuningResult:
    """LLM 决策微调结果。"""

    decision: str
    confidence: float
    score_adjustment: int
    summary: str
    reasoning: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMEnhanceResult:
    """LLM 深度增强结果。"""

    insight: str
    opportunities: list[str]
    risks: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─── 复合结果模型 ───────────────────────────────────────────────


@dataclass
class AnalysisResult:
    """完整分析结果。"""

    symbol: str
    symbol_name: str
    provider: str
    price: float | None = None
    trend: str | None = None
    indicators: dict[str, Any] = field(default_factory=dict)
    strategy: dict[str, Any] = field(default_factory=dict)
    risk: list[str] = field(default_factory=list)
    latest_rows: list[dict[str, Any]] = field(default_factory=list)
    hot_rank: list[dict[str, Any]] = field(default_factory=list)
    news: dict[str, Any] = field(default_factory=dict)
    decision_layer: DecisionLayer | None = None
    llm: dict[str, Any] | None = None
    llm_enhance: LLMEnhanceResult | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "symbol": self.symbol,
            "symbol_name": self.symbol_name,
            "provider": self.provider,
            "price": self.price,
            "trend": self.trend,
            "indicators": self.indicators,
            "strategy": self.strategy,
            "risk": self.risk,
            "latest_rows": self.latest_rows,
            "hot_rank": self.hot_rank,
            "news": self.news,
        }
        if self.decision_layer:
            data["decision_layer"] = self.decision_layer.to_dict()
        if self.llm:
            data["llm"] = self.llm
        if self.llm_enhance:
            data["llm_enhance"] = self.llm_enhance.to_dict()
        return data


# ─── API 响应模型 ───────────────────────────────────────────────


@dataclass
class APIResponse:
    """统一 API 响应。"""

    code: int = 0
    message: str = "success"
    status: Literal["success", "error", "empty", "loading"] = "success"
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "status": self.status,
            "data": self.data,
            "error": self.error,
            "meta": self.meta,
        }


# ─── 工具函数 ───────────────────────────────────────────────────


def now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()


def build_meta(symbol: str | None = None, provider: str | None = None) -> dict[str, Any]:
    """构建标准 meta 字段。"""
    return {
        "timestamp": now_iso(),
        "symbol": symbol,
        "provider": provider,
    }

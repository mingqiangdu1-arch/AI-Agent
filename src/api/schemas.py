from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ProviderType = Literal["auto", "yahoo", "stooq", "akshare"]
AnalyzeMode = Literal["full", "trend", "strategy"]


class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol, e.g. 600519.SS or AAPL")
    provider: ProviderType = "auto"
    period: str = "6mo"
    interval: str = "1d"
    hot_limit: int = Field(10, ge=1, le=50)
    mode: AnalyzeMode = "full"


class TrendRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol, e.g. 600519.SS or AAPL")
    provider: ProviderType = "auto"
    period: str = "6mo"
    interval: str = "1d"


class StrategyRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol, e.g. 600519.SS or AAPL")
    provider: ProviderType = "auto"
    period: str = "6mo"
    interval: str = "1d"


class MarketHotRequest(BaseModel):
    limit: int = Field(10, ge=1, le=50)
    preferred_source: str = "ths"


class LLMAnalysisRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol, e.g. 600519.SS or AAPL")
    provider: ProviderType = "auto"
    period: str = "6mo"
    interval: str = "1d"
    hot_limit: int = Field(10, ge=1, le=50)


class ModelConfigRequest(BaseModel):
    pass


class ReportHubRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol, e.g. 600519.SS or AAPL")
    provider: ProviderType = "auto"
    period: str = "6mo"
    interval: str = "1d"


class APIResponse(BaseModel):
    code: int = 0
    message: str = "success"
    status: Literal["success", "error", "empty", "loading"]
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

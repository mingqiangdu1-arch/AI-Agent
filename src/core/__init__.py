"""核心模块：配置、数据模型、异常定义。"""

from .config import AppConfig, CacheConfig, LLMConfig, NewsConfig, get_config, reload_config
from .exceptions import (
    AnalysisError,
    AppError,
    ConfigError,
    DataFetchError,
    LLMError,
    NewsAggregationError,
)
from .models import (
    APIResponse,
    AnalysisResult,
    DecisionLayer,
    LLMEnhanceResult,
    LLMResult,
    LLMTuningResult,
    NewsItem,
    NewsResult,
    NewsSentiment,
    StrategyData,
    TrendData,
    build_meta,
    now_iso,
)

__all__ = [
    # Config
    "AppConfig",
    "CacheConfig",
    "LLMConfig",
    "NewsConfig",
    "get_config",
    "reload_config",
    # Exceptions
    "AppError",
    "AnalysisError",
    "ConfigError",
    "DataFetchError",
    "LLMError",
    "NewsAggregationError",
    # Models
    "APIResponse",
    "AnalysisResult",
    "DecisionLayer",
    "LLMEnhanceResult",
    "LLMResult",
    "LLMTuningResult",
    "NewsItem",
    "NewsResult",
    "NewsSentiment",
    "StrategyData",
    "TrendData",
    "build_meta",
    "now_iso",
]

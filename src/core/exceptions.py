"""统一异常定义。

定义业务异常层次结构，便于上层统一捕获和处理。
"""

from __future__ import annotations


class AppError(Exception):
    """应用基础异常。"""

    def __init__(self, message: str, code: str = "APP_ERROR") -> None:
        super().__init__(message)
        self.code = code


class DataFetchError(AppError):
    """数据获取异常。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="DATA_FETCH_ERROR")


class AnalysisError(AppError):
    """分析过程异常。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="ANALYSIS_ERROR")


class LLMError(AppError):
    """LLM 调用异常。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="LLM_ERROR")


class ConfigError(AppError):
    """配置异常。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="CONFIG_ERROR")


class NewsAggregationError(AppError):
    """新闻聚合异常。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="NEWS_AGGREGATION_ERROR")

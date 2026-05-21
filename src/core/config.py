"""统一配置管理模块。

集中管理 LLM、缓存、数据源等配置，支持环境变量和运行时覆盖。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LLMConfig:
    """LLM 调用配置。"""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    max_tokens: int = 800

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def with_overrides(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMConfig:
        return LLMConfig(
            base_url=(base_url or self.base_url).strip(),
            api_key=(api_key or self.api_key).strip(),
            model=(model or self.model).strip(),
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
        )


@dataclass(frozen=True)
class CacheConfig:
    """缓存配置。"""

    ttl_seconds: int = 300
    max_entries: int = 128


@dataclass(frozen=True)
class NewsConfig:
    """新闻聚合配置。"""

    juhe_api_key: str = ""
    gnews_api_key: str = ""
    finnhub_api_key: str = ""
    default_limit: int = 20


@dataclass(frozen=True)
class AppConfig:
    """应用全局配置。"""

    llm: LLMConfig = field(default_factory=LLMConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    news: NewsConfig = field(default_factory=NewsConfig)

    @classmethod
    def from_env(cls) -> AppConfig:
        """从环境变量加载配置。"""

        def _float(key: str, default: str) -> float:
            try:
                return float(os.getenv(key, default))
            except (ValueError, TypeError):
                return float(default)

        def _int(key: str, default: str) -> int:
            try:
                return int(os.getenv(key, default))
            except (ValueError, TypeError):
                return int(default)

        return cls(
            llm=LLMConfig(
                base_url=os.getenv("LLM_BASE_URL", "").strip(),
                api_key=os.getenv("LLM_API_KEY", "").strip(),
                model=os.getenv("LLM_MODEL", "").strip(),
                temperature=_float("LLM_TEMPERATURE", "0.2"),
                max_tokens=_int("LLM_MAX_TOKENS", "800"),
            ),
            cache=CacheConfig(
                ttl_seconds=_int("CACHE_TTL_SECONDS", "300"),
                max_entries=_int("CACHE_MAX_ENTRIES", "128"),
            ),
            news=NewsConfig(
                juhe_api_key=os.getenv("JUHE_API_KEY", "").strip(),
                gnews_api_key=os.getenv("GNEWS_API_KEY", "").strip(),
                finnhub_api_key=os.getenv("FINNHUB_API_KEY", "").strip(),
                default_limit=_int("NEWS_DEFAULT_LIMIT", "20"),
            ),
        )


# 全局配置单例
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """获取全局配置（懒加载）。"""
    global _config
    if _config is None:
        _config = AppConfig.from_env()
    return _config


def reload_config() -> AppConfig:
    """重新加载配置。"""
    global _config
    _config = AppConfig.from_env()
    return _config


# 已知股票名称映射（代码 → 名称）
KNOWN_SYMBOL_NAMES: dict[str, str] = {
    # 美股
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com Inc.",
    "TSLA": "Tesla Inc.",
    "META": "Meta Platforms Inc.",
    "NVDA": "NVIDIA Corp.",
    "NFLX": "Netflix Inc.",
    "BABA": "Alibaba Group",
    "AMD": "Advanced Micro Devices",
    "INTC": "Intel Corporation",
    "BA": "Boeing Company",
    # A股 (沪市)
    "600519": "贵州茅台", "600519.SS": "贵州茅台", "600519.SH": "贵州茅台",
    "600036": "招商银行", "600036.SS": "招商银行",
    "601318": "中国平安", "601318.SS": "中国平安",
    "600030": "中信证券", "600030.SS": "中信证券",
    "600887": "伊利股份", "600887.SS": "伊利股份",
    "600276": "恒瑞医药", "600276.SS": "恒瑞医药",
    "600900": "长江电力", "600900.SS": "长江电力",
    "601166": "兴业银行", "601166.SS": "兴业银行",
    "601398": "工商银行", "601398.SS": "工商银行",
    "601939": "建设银行", "601939.SS": "建设银行",
    "601988": "中国银行", "601988.SS": "中国银行",
    "600585": "海螺水泥", "600585.SS": "海螺水泥",
    "601888": "中国中免", "601888.SS": "中国中免",
    "601012": "隆基绿能", "601012.SS": "隆基绿能",
    "600809": "山西汾酒", "600809.SS": "山西汾酒",
    "601991": "大唐发电", "601991.SS": "大唐发电",
    # A股 (深市)
    "000001": "平安银行", "000001.SZ": "平安银行",
    "000858": "五粮液", "000858.SZ": "五粮液",
    "002594": "比亚迪", "002594.SZ": "比亚迪",
    "300750": "宁德时代", "300750.SZ": "宁德时代",
    "000333": "美的集团", "000333.SZ": "美的集团",
    "000651": "格力电器", "000651.SZ": "格力电器",
    "002415": "海康威视", "002415.SZ": "海康威视",
    "000725": "京东方A", "000725.SZ": "京东方A",
    "002714": "牧原股份", "002714.SZ": "牧原股份",
    "300059": "东方财富", "300059.SZ": "东方财富",
    "000568": "泸州老窖", "000568.SZ": "泸州老窖",
    "002475": "立讯精密", "002475.SZ": "立讯精密",
    "300124": "汇川技术", "300124.SZ": "汇川技术",
    "000063": "中兴通讯", "000063.SZ": "中兴通讯",
    "002230": "科大讯飞", "002230.SZ": "科大讯飞",
    "000002": "万科A", "000002.SZ": "万科A",
    "002142": "宁波银行", "002142.SZ": "宁波银行",
    # 港股
    "00700": "腾讯控股", "00700.HK": "腾讯控股",
    "09988": "阿里巴巴-SW", "09988.HK": "阿里巴巴-SW",
    "03690": "美团-W", "03690.HK": "美团-W",
    "01810": "小米集团-W", "01810.HK": "小米集团-W",
    "09618": "京东集团-SW", "09618.HK": "京东集团-SW",
    "09999": "网易-S", "09999.HK": "网易-S",
    "02318": "中国平安", "02318.HK": "中国平安",
    "00941": "中国移动", "00941.HK": "中国移动",
    "00883": "中国海洋石油", "00883.HK": "中国海洋石油",
    "01211": "比亚迪股份", "01211.HK": "比亚迪股份",
    "02269": "药明生物", "02269.HK": "药明生物",
    "09888": "百度集团-SW", "09888.HK": "百度集团-SW",
}

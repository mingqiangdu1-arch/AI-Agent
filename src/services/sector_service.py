"""板块推荐服务模块。

获取热门板块和板块内股票推荐。
"""

from __future__ import annotations

import time
from typing import Any

from src.core.models import now_iso


class SectorService:
    """板块推荐服务。"""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._cache_ttl = 300  # 5 分钟缓存

    def get_hot_sectors(self, limit: int = 10) -> dict[str, Any]:
        """获取热门板块（使用同花顺数据源，比东方财富更稳定）。"""
        cache_key = f"hot_sectors_{limit}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        try:
            import akshare as ak
        except ModuleNotFoundError:
            return {"error": "akshare not installed", "sectors": []}

        try:
            df = ak.stock_board_industry_summary_ths()
            if df is None or df.empty:
                return {"error": "获取板块数据为空", "sectors": []}

            # 按涨跌幅排序，取前 N 个
            col_change = _pick_col(df, ["涨跌幅", "change_pct"])
            df = df.sort_values(col_change, ascending=False).head(limit) if col_change else df.head(limit)

            sectors = []
            for _, row in df.iterrows():
                sector = {
                    "rank": _int(_col_val(row, df, ["序号", "rank"])),
                    "name": str(_col_val(row, df, ["板块", "板块名称", "name"])),
                    "change_pct": _float(_col_val(row, df, ["涨跌幅", "change_pct"])),
                    "turnover": _float(_col_val(row, df, ["换手率", "turnover"])),
                    "up_count": _int(_col_val(row, df, ["上涨家数", "up_count"])),
                    "down_count": _int(_col_val(row, df, ["下跌家数", "down_count"])),
                    "leading_stock": str(_col_val(row, df, ["领涨股", "leading_stock"])),
                    "leading_stock_pct": _float(_col_val(row, df, ["领涨股-涨跌幅", "leading_change"])),
                    "leading_stock_price": _float(_col_val(row, df, ["领涨股-最新价", "leading_price"])),
                }
                sectors.append(sector)

            result = {
                "sectors": sectors,
                "total": len(df),
                "updated_at": now_iso(),
            }
            self._set_cache(cache_key, result)
            return result

        except Exception as exc:
            return {"error": str(exc), "sectors": []}

    def get_sector_summary(self, limit: int = 5) -> dict[str, Any]:
        """获取板块摘要。"""
        hot_result = self.get_hot_sectors(limit=limit)
        return {
            "sectors": hot_result.get("sectors", []),
            "error": hot_result.get("error"),
            "updated_at": now_iso(),
        }

    def _get_cache(self, key: str) -> dict[str, Any] | None:
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                return data
            del self._cache[key]
        return None

    def _set_cache(self, key: str, data: dict[str, Any]) -> None:
        self._cache[key] = (data, time.time())


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _pick_col(df, candidates: list[str]) -> str | None:
    for col in df.columns:
        if str(col) in candidates:
            return str(col)
    for col in df.columns:
        col_str = str(col)
        if any(c in col_str for c in candidates):
            return str(col)
    return None

def _col_val(row, df, candidates: list[str]) -> Any:
    col = _pick_col(df, candidates)
    if col:
        return row.get(col)
    return 0


# 全局板块服务实例
_sector_service: SectorService | None = None


def get_sector_service() -> SectorService:
    global _sector_service
    if _sector_service is None:
        _sector_service = SectorService()
    return _sector_service

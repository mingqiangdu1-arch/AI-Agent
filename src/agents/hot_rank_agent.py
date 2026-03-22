from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass
class HotRankRequest:
    limit: int = 20


class THSHotRankAgent:
    """同花顺热榜抓取 Agent（优先通过 akshare）。"""

    def fetch(self, request: HotRankRequest) -> pd.DataFrame:
        try:
            import akshare as ak  # type: ignore
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "未安装 akshare。请先执行: .\\.venv\\Scripts\\python.exe -m pip install akshare"
            ) from exc

        call_errors: list[str] = []
        raw: pd.DataFrame | None = None

        for fn_name in ["stock_hot_rank_wc", "stock_hot_rank_ths", "stock_hot_rank_10jqka"]:
            fn = getattr(ak, fn_name, None)
            if not callable(fn):
                continue
            try:
                maybe_df = fn()
                if isinstance(maybe_df, pd.DataFrame) and not maybe_df.empty:
                    raw = maybe_df
                    break
            except Exception as exc:
                call_errors.append(f"{fn_name}: {exc}")

        if raw is None:
            detail = " | ".join(call_errors) if call_errors else "未找到可用热榜接口"
            raise RuntimeError(f"同花顺热榜获取失败: {detail}")

        df = self._normalize(raw)
        return df.head(max(1, request.limit))

    @staticmethod
    def _pick_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
        for col in df.columns:
            if str(col) in candidates:
                return str(col)
        for col in df.columns:
            col_str = str(col).lower()
            if any(k.lower() in col_str for k in candidates):
                return str(col)
        return None

    def _normalize(self, raw: pd.DataFrame) -> pd.DataFrame:
        df = raw.copy()

        code_col = self._pick_column(df, ["代码", "股票代码", "symbol", "证券代码"])
        name_col = self._pick_column(df, ["股票简称", "名称", "股票名称", "name"])
        rank_col = self._pick_column(df, ["当前排名", "排名", "rank", "热度排名"])
        hot_col = self._pick_column(df, ["热度", "人气", "关注度", "热度值"])
        chg_col = self._pick_column(df, ["涨跌幅", "涨跌幅%", "change", "涨跌"])

        selected = []
        rename_map: dict[str, str] = {}

        if rank_col:
            selected.append(rank_col)
            rename_map[rank_col] = "排名"
        if code_col:
            selected.append(code_col)
            rename_map[code_col] = "代码"
        if name_col:
            selected.append(name_col)
            rename_map[name_col] = "名称"
        if hot_col:
            selected.append(hot_col)
            rename_map[hot_col] = "热度"
        if chg_col:
            selected.append(chg_col)
            rename_map[chg_col] = "涨跌幅"

        if not selected:
            # 接口字段变化时至少返回前几列，避免页面完全不可用。
            selected = [str(c) for c in df.columns[:5]]

        out = df[selected].rename(columns=rename_map).copy()

        if "排名" in out.columns:
            out = out.sort_values(by="排名", ascending=True)

        out.insert(0, "来源", "同花顺热榜")
        out = out.reset_index(drop=True)
        return out

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import pandas as pd

from src.core.config import KNOWN_SYMBOL_NAMES

# 反向映射：名称 → 代码
_NAME_TO_CODE: dict[str, str] = {v: k for k, v in KNOWN_SYMBOL_NAMES.items()}


@dataclass
class HotRankRequest:
    limit: int = 20
    preferred_source: str = "ths"


class THSHotRankAgent:
    """热榜抓取 Agent，多源容错：东财 → 雪球 → 百度。"""

    def fetch(self, request: HotRankRequest) -> pd.DataFrame:
        limit = max(1, request.limit)
        try:
            import akshare as ak  # type: ignore
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "未安装 akshare。请先执行: pip install akshare"
            ) from exc

        call_errors: list[str] = []

        # 1. 东财热榜（最完整，优先尝试）
        for fn_name in ("stock_hot_rank_em",):
            fn = getattr(ak, fn_name, None)
            if not callable(fn):
                continue
            for attempt in range(2):
                try:
                    maybe_df = fn()
                    if isinstance(maybe_df, pd.DataFrame) and not maybe_df.empty:
                        df = self._normalize_em(maybe_df)
                        return df.head(limit)
                except Exception as exc:
                    call_errors.append(f"{fn_name}[{attempt+1}]: {exc}")
                    if attempt == 0:
                        time.sleep(0.5)

        # 2. 雪球关注（有代码，可靠）
        try:
            maybe_df = ak.stock_hot_deal_xq()
            if isinstance(maybe_df, pd.DataFrame) and not maybe_df.empty:
                df = self._normalize_xq(maybe_df)
                return df.head(limit)
        except Exception as exc:
            call_errors.append(f"xueqiu_hot_deal: {exc}")

        # 3. 百度热搜（稳定但无代码，最后兜底）
        try:
            from datetime import date as _date

            today_str = _date.today().strftime("%Y%m%d")
            maybe_df = ak.stock_hot_search_baidu(symbol="A股", date=today_str, time="今日")
            if isinstance(maybe_df, pd.DataFrame) and not maybe_df.empty:
                df = self._normalize_baidu(maybe_df)
                return df.head(limit)
        except Exception as exc:
            call_errors.append(f"baidu_hot_search: {exc}")

        detail = " | ".join(call_errors) if call_errors else "未找到可用热榜接口"
        raise RuntimeError(f"热榜获取失败: {detail}")

    def _normalize_em(self, raw: pd.DataFrame) -> pd.DataFrame:
        """东财热榜标准化。"""
        df = raw.copy()
        code_col = self._pick_column(df, ["代码", "股票代码", "symbol"])
        name_col = self._pick_column(df, ["股票简称", "名称", "股票名称", "name"])
        rank_col = self._pick_column(df, ["当前排名", "排名", "rank"])
        hot_col = self._pick_column(df, ["热度", "人气", "关注度"])
        chg_col = self._pick_column(df, ["涨跌幅", "涨跌幅%", "change"])

        selected, rename_map = [], {}
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
            selected = [str(c) for c in df.columns[:5]]

        out = df[selected].rename(columns=rename_map).copy()
        # 清洗代码格式：SH600519 → 600519
        if "代码" in out.columns:
            out["代码"] = out["代码"].astype(str).str.replace(r"^(SH|SZ|BJ)", "", regex=True)
        if "排名" in out.columns:
            out = out.sort_values(by="排名", ascending=True)
        out.insert(0, "来源", "东方财富热榜")
        return out.reset_index(drop=True)

    def _normalize_baidu(self, raw: pd.DataFrame) -> pd.DataFrame:
        """百度热搜标准化。输入列: 名称/代码, 涨跌幅, 综合热度。"""
        df = raw.copy()
        out = pd.DataFrame()

        # 解析 名称/代码 字段
        name_code_col = df.columns[0]
        names, codes = [], []
        for val in df[name_code_col]:
            text = str(val).strip()
            # 尝试分离 "名称 代码" 或 "名称(代码)"
            match = re.match(r"^(.+?)\s*[\(（](\d{6}|\w+)[\)）]?\s*$", text)
            if match:
                names.append(match.group(1).strip())
                codes.append(match.group(2).strip())
            else:
                names.append(text)
                # 通过已知映射反查代码
                codes.append(_NAME_TO_CODE.get(text, _NAME_TO_CODE.get(text.lower(), "--")))

        out["排名"] = range(1, len(df) + 1)
        out["代码"] = codes
        out["名称"] = names
        out["热度"] = df.iloc[:, 2].values if len(df.columns) > 2 else 0
        out["涨跌幅"] = df.iloc[:, 1].values if len(df.columns) > 1 else "--"
        out.insert(0, "来源", "百度热搜")
        return out.reset_index(drop=True)

    def _normalize_xq(self, raw: pd.DataFrame) -> pd.DataFrame:
        """雪球关注标准化。输入列: 股票代码, 股票简称, 关注, 最新价。"""
        df = raw.copy()
        out = pd.DataFrame()
        out["排名"] = range(1, len(df) + 1)

        # 转换 SH600519 → 600519.SS 格式
        raw_codes = df.iloc[:, 0].astype(str)
        codes = []
        for c in raw_codes:
            c = c.strip()
            if c.startswith("SH"):
                codes.append(f"{c[2:]}.SS")
            elif c.startswith("SZ"):
                codes.append(f"{c[2:]}.SZ")
            else:
                codes.append(c)
        out["代码"] = codes
        out["名称"] = df.iloc[:, 1].values
        out["热度"] = df.iloc[:, 2].values if len(df.columns) > 2 else 0
        out["涨跌幅"] = "--"
        out.insert(0, "来源", "雪球关注")
        return out.reset_index(drop=True)

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

    @classmethod
    def build_name_code_map(cls) -> dict[str, str]:
        """构建股票名称→代码映射（从雪球和东财热榜抓取）。"""
        import akshare as ak
        name_code: dict[str, str] = {}

        # 从雪球获取（有代码，可靠）
        try:
            df = ak.stock_hot_deal_xq()
            if df is not None and not df.empty:
                code_col = cls._pick_column(df, ["股票代码", "symbol", "代码"])
                name_col = cls._pick_column(df, ["股票简称", "name", "名称"])
                if code_col and name_col:
                    for _, row in df.iterrows():
                        code = str(row.get(code_col, "")).strip()
                        name = str(row.get(name_col, "")).strip()
                        if code and name and code != "nan":
                            code = code.replace("SH", "").replace("SZ", "").replace("BJ", "")
                            name_code[name] = code
                            name_code[name.lower()] = code
        except Exception:
            pass

        # 从东财热榜补充
        try:
            fn = getattr(ak, "stock_hot_rank_em", None)
            if callable(fn):
                df = fn()
                if df is not None and not df.empty:
                    code_col = cls._pick_column(df, ["代码", "symbol"])
                    name_col = cls._pick_column(df, ["股票名称", "股票简称", "name", "名称"])
                    if code_col and name_col:
                        for _, row in df.iterrows():
                            code = str(row.get(code_col, "")).strip()
                            name = str(row.get(name_col, "")).strip()
                            if code and name and code != "nan":
                                code = code.replace("SH", "").replace("SZ", "").replace("BJ", "")
                                name_code.setdefault(name, code)
                                name_code.setdefault(name.lower(), code)
        except Exception:
            pass

        return name_code

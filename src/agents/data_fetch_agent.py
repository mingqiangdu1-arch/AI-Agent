from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from io import StringIO
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass
class StockDataRequest:
    symbol: str
    period: str = "6mo"
    interval: str = "1d"
    provider: str = "auto"


class StockDataFetchAgent:
    """Agent 1: 拉取并标准化股票历史行情数据。

    股票类型判断：
    - A 股：6 位纯数字，或 .SS/.SH/.SZ 后缀
    - 港股：5 位纯数字（如 00700）
    - 美股：纯字母代码（如 AAPL、MSFT）

    数据源回退链：
    - A 股：东方财富 → 腾讯 → 网易163 → Yahoo → Stooq
    - 港股：akshare 港股 → Yahoo → Stooq
    - 美股：akshare 美股 → Yahoo → Stooq
    """

    REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}

    PROXY_ERROR_HINT = (
        "检测到代理连接失败。请检查网络代理设置，"
        "或临时清理 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 环境变量。"
    )

    def fetch(self, request: StockDataRequest) -> pd.DataFrame:
        symbol = request.symbol.strip().upper()
        if not symbol:
            raise ValueError("股票代码不能为空。")

        provider = request.provider.lower()
        valid_providers = {"auto", "yahoo", "stooq", "akshare", "eastmoney", "tencent", "netease"}
        if provider not in valid_providers:
            raise ValueError(f"provider 仅支持 {'/'.join(sorted(valid_providers))}")

        errors: list[str] = []
        stock_type = self._get_stock_type(symbol)

        # A 股数据源回退链
        if stock_type == "a_share":
            a_share_providers = self._get_a_share_providers(provider)
            for p in a_share_providers:
                try:
                    return self._fetch_a_share(symbol, p, request.period, request.interval)
                except Exception as exc:
                    errors.append(f"{p}: {exc}")
                    if provider == p:
                        raise ValueError(f"{p} 获取失败: {exc}") from exc

        # 港股数据源回退链
        if stock_type == "hk":
            hk_providers = self._get_hk_providers(provider)
            for p in hk_providers:
                try:
                    return self._fetch_hk(symbol, p, request.period, request.interval)
                except Exception as exc:
                    errors.append(f"{p}: {exc}")
                    if provider == p:
                        raise ValueError(f"{p} 获取失败: {exc}") from exc

        # 美股数据源回退链
        if stock_type == "us":
            us_providers = self._get_us_providers(provider)
            for p in us_providers:
                try:
                    return self._fetch_us(symbol, p, request.period, request.interval)
                except Exception as exc:
                    errors.append(f"{p}: {exc}")
                    if provider == p:
                        raise ValueError(f"{p} 获取失败: {exc}") from exc

        # 其他国际股票：Yahoo → Stooq
        if provider in {"auto", "yahoo"}:
            try:
                return self._fetch_from_yahoo(
                    symbol=self._to_yahoo_symbol(symbol),
                    period=request.period,
                    interval=request.interval,
                )
            except Exception as exc:
                errors.append(f"Yahoo: {exc}")
                if provider == "yahoo":
                    raise ValueError(f"Yahoo 获取失败: {exc}") from exc

        if provider in {"auto", "stooq"}:
            try:
                return self._fetch_from_stooq(symbol=symbol)
            except Exception as exc:
                errors.append(f"Stooq: {exc}")
                if provider == "stooq":
                    raise ValueError(f"Stooq 获取失败: {exc}") from exc

        error_text = " | ".join(errors) if errors else "未知错误"
        raise ValueError(
            f"未获取到股票 {symbol} 的行情数据。"
            f"建议：A 股使用 6 位代码（如 600519 / 000001），港股使用 5 位代码（如 00700），美股直接输入代码（如 AAPL）。"
            f"详情: {error_text}"
        )

    # ─── 股票类型判断 ─────────────────────────────────

    @staticmethod
    def _get_stock_type(symbol: str) -> str:
        """判断股票类型：a_share / hk / us / other"""
        s = symbol.strip().upper()

        # A 股：6 位纯数字
        if s.isdigit() and len(s) == 6:
            return "a_share"
        # A 股：.SS/.SH/.SZ 后缀 (600519.SS)
        if s.endswith((".SS", ".SH", ".SZ")):
            code = s.split(".")[0]
            if code.isdigit() and len(code) == 6:
                return "a_share"
        # A 股：SH/SZ 前缀 (SH601991, SZ000001)
        if s.startswith(("SH", "SZ")) and len(s) == 8:
            code = s[2:]
            if code.isdigit() and len(code) == 6:
                return "a_share"

        # 港股：5 位纯数字（00700, 09988 等）
        if s.isdigit() and len(s) == 5:
            return "hk"
        # 港股：带 .HK 后缀
        if s.endswith(".HK"):
            return "hk"

        # 美股：纯字母（AAPL, MSFT, BRK.A 等）
        if s.replace(".", "").isalpha():
            return "us"

        return "other"

    def _get_a_share_providers(self, provider: str) -> list[str]:
        """返回 A 股数据源尝试顺序。"""
        if provider == "auto":
            return ["tencent", "netease", "eastmoney"]
        if provider == "akshare":
            return ["tencent", "netease", "eastmoney"]
        return [provider]

    def _get_hk_providers(self, provider: str) -> list[str]:
        """返回港股数据源尝试顺序。"""
        if provider == "auto":
            return ["akshare_hk", "yahoo", "stooq"]
        if provider == "akshare":
            return ["akshare_hk"]
        return [provider]

    def _get_us_providers(self, provider: str) -> list[str]:
        """返回美股数据源尝试顺序。"""
        if provider == "auto":
            return ["akshare_us", "yahoo", "stooq"]
        if provider == "akshare":
            return ["akshare_us"]
        return [provider]

    # ─── A 股数据获取 ─────────────────────────────────

    def _fetch_a_share(self, symbol: str, provider: str, period: str, interval: str) -> pd.DataFrame:
        """分发到具体的 A 股数据源。"""
        code = self._to_cn_code(symbol)
        if not code:
            raise ValueError(f"仅支持 A 股 6 位代码，当前为: {symbol}")

        if provider == "eastmoney":
            return self._fetch_from_eastmoney(code, period, interval)
        if provider == "tencent":
            return self._fetch_from_tencent(code, period, interval)
        if provider == "netease":
            return self._fetch_from_netease(code, period, interval)
        if provider == "yahoo":
            return self._fetch_from_yahoo(self._to_yahoo_symbol(symbol), period, interval)
        if provider == "stooq":
            return self._fetch_from_stooq(symbol)
        raise ValueError(f"未知的 A 股数据源: {provider}")

    def _fetch_from_eastmoney(self, code: str, period: str, interval: str) -> pd.DataFrame:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise ValueError("未安装 akshare，请执行: pip install akshare") from exc

        try:
            raw = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="")
        except Exception as exc:
            if self._is_proxy_error(exc):
                raise ValueError(f"{exc}；{self.PROXY_ERROR_HINT}") from exc
            raise

        if raw is None or raw.empty:
            raise ValueError("返回空数据")

        col_map = {"日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "volume"}
        missing = [c for c in col_map if c not in raw.columns]
        if missing:
            raise ValueError(f"缺少字段: {missing}")

        df = raw[list(col_map.keys())].rename(columns=col_map).copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").set_index("date")
        df.index = df.index.date
        df.index.name = "date"
        return self._slice_by_period(df, period, interval)

    def _fetch_from_tencent(self, code: str, period: str, interval: str) -> pd.DataFrame:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise ValueError("未安装 akshare，请执行: pip install akshare") from exc

        prefix = "sh" if code.startswith(("6", "9")) else "sz"
        symbol_tx = f"{prefix}{code}"

        end_date = date.today().strftime("%Y%m%d")
        days = self._period_to_days(period)
        start_date = (date.today() - timedelta(days=days)).strftime("%Y%m%d")

        try:
            raw = ak.stock_zh_a_hist_tx(symbol=symbol_tx, start_date=start_date, end_date=end_date, adjust="qfq")
        except Exception as exc:
            if self._is_proxy_error(exc):
                raise ValueError(f"{exc}；{self.PROXY_ERROR_HINT}") from exc
            raise

        if raw is None or raw.empty:
            raise ValueError("返回空数据")

        col_map = {"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "amount": "volume"}
        missing = [c for c in ["date", "open", "high", "low", "close"] if c not in raw.columns]
        if missing:
            raise ValueError(f"缺少字段: {missing}")

        df = raw[["date", "open", "high", "low", "close", "amount"]].rename(columns=col_map).copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").set_index("date")
        df.index = df.index.date
        df.index.name = "date"
        return self._slice_by_period(df, period, interval)

    def _fetch_from_netease(self, code: str, period: str, interval: str) -> pd.DataFrame:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise ValueError("未安装 akshare，请执行: pip install akshare") from exc

        prefix = "sh" if code.startswith(("6", "9")) else "sz"
        symbol_163 = f"{prefix}{code}"

        end_date = date.today().strftime("%Y%m%d")
        days = self._period_to_days(period)
        start_date = (date.today() - timedelta(days=days)).strftime("%Y%m%d")

        try:
            raw = ak.stock_zh_a_daily(symbol=symbol_163, start_date=start_date, end_date=end_date, adjust="qfq")
        except Exception as exc:
            if self._is_proxy_error(exc):
                raise ValueError(f"{exc}；{self.PROXY_ERROR_HINT}") from exc
            raise

        if raw is None or raw.empty:
            raise ValueError("返回空数据")

        col_map = {"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
        missing = [c for c in col_map if c not in raw.columns]
        if missing:
            raise ValueError(f"缺少字段: {missing}")

        df = raw[list(col_map.keys())].rename(columns=col_map).copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").set_index("date")
        df.index = df.index.date
        df.index.name = "date"
        return self._slice_by_period(df, period, interval)

    # ─── 港股数据获取 ─────────────────────────────────

    def _fetch_hk(self, symbol: str, provider: str, period: str, interval: str) -> pd.DataFrame:
        """分发到具体的港股数据源。"""
        if provider == "akshare_hk":
            code = symbol.replace(".HK", "").strip()
            return self._fetch_from_akshare_hk(code, period, interval)
        if provider == "yahoo":
            return self._fetch_from_yahoo(self._to_yahoo_symbol(symbol), period, interval)
        if provider == "stooq":
            return self._fetch_from_stooq(symbol)
        raise ValueError(f"未知的港股数据源: {provider}")

    def _fetch_from_akshare_hk(self, code: str, period: str, interval: str) -> pd.DataFrame:
        """通过 akshare 获取港股数据。"""
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise ValueError("未安装 akshare，请执行: pip install akshare") from exc

        try:
            raw = ak.stock_hk_daily(symbol=code, adjust="qfq")
        except Exception as exc:
            if self._is_proxy_error(exc):
                raise ValueError(f"{exc}；{self.PROXY_ERROR_HINT}") from exc
            raise

        if raw is None or raw.empty:
            raise ValueError("返回空数据")

        col_map = {"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
        missing = [c for c in col_map if c not in raw.columns]
        if missing:
            raise ValueError(f"缺少字段: {missing}")

        df = raw[list(col_map.keys())].rename(columns=col_map).copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").set_index("date")
        df.index = df.index.date
        df.index.name = "date"
        return self._slice_by_period(df, period, interval)

    # ─── 美股数据获取 ─────────────────────────────────

    def _fetch_us(self, symbol: str, provider: str, period: str, interval: str) -> pd.DataFrame:
        """分发到具体的美股数据源。"""
        if provider == "akshare_us":
            return self._fetch_from_akshare_us(symbol, period, interval)
        if provider == "yahoo":
            return self._fetch_from_yahoo(symbol, period, interval)
        if provider == "stooq":
            return self._fetch_from_stooq(symbol)
        raise ValueError(f"未知的美股数据源: {provider}")

    def _fetch_from_akshare_us(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        """通过 akshare 获取美股数据。"""
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise ValueError("未安装 akshare，请执行: pip install akshare") from exc

        try:
            raw = ak.stock_us_daily(symbol=symbol, adjust="qfq")
        except Exception as exc:
            if self._is_proxy_error(exc):
                raise ValueError(f"{exc}；{self.PROXY_ERROR_HINT}") from exc
            raise

        if raw is None or raw.empty:
            raise ValueError("返回空数据")

        col_map = {"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
        missing = [c for c in col_map if c not in raw.columns]
        if missing:
            raise ValueError(f"缺少字段: {missing}")

        df = raw[list(col_map.keys())].rename(columns=col_map).copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").set_index("date")
        df.index = df.index.date
        df.index.name = "date"
        return self._slice_by_period(df, period, interval)

    # ─── Yahoo Finance ────────────────────────────────

    def _fetch_from_yahoo(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        raw = yf.download(tickers=symbol, period=period, interval=interval, auto_adjust=False, progress=False)
        if raw.empty:
            raise ValueError("返回空数据（可能为 Yahoo 限流或网络限制）")

        raw = self._normalize_yahoo_raw(raw)
        col_map = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
        missing = [c for c in col_map if c not in raw.columns]
        if missing:
            raise ValueError(f"缺少字段: {missing}")

        df = raw[list(col_map.keys())].rename(columns=col_map).copy()
        df.index = pd.to_datetime(df.index).date
        df.index.name = "date"
        return df

    @staticmethod
    def _normalize_yahoo_raw(raw: pd.DataFrame) -> pd.DataFrame:
        if isinstance(raw.columns, pd.MultiIndex):
            if raw.columns.nlevels >= 2:
                level0 = set(raw.columns.get_level_values(0))
                if {"Open", "High", "Low", "Close", "Volume"}.intersection(level0):
                    raw = raw.copy()
                    raw.columns = raw.columns.get_level_values(0)
                else:
                    raw = raw.copy()
                    raw.columns = raw.columns.get_level_values(-1)
            else:
                raw = raw.copy()
                raw.columns = [str(c[0]) for c in raw.columns]
        return raw

    # ─── Stooq ────────────────────────────────────────

    def _fetch_from_stooq(self, symbol: str) -> pd.DataFrame:
        stooq_symbol = self._to_stooq_symbol(symbol)
        url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
        try:
            with urlopen(url, timeout=15) as response:
                csv_text = response.read().decode("utf-8", errors="ignore")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ValueError(f"请求失败: {exc}") from exc

        if not csv_text.strip():
            raise ValueError("返回空响应")

        try:
            raw = pd.read_csv(StringIO(csv_text))
        except pd.errors.EmptyDataError as exc:
            raise ValueError("返回内容不可解析") from exc

        if raw.empty or "Date" not in raw.columns:
            raise ValueError("返回空数据")

        col_map = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
        missing = [c for c in col_map if c not in raw.columns]
        if missing:
            raise ValueError(f"缺少字段: {missing}")

        raw = raw[raw["Close"].notna()].copy()
        raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
        raw = raw.dropna(subset=["Date"]).sort_values("Date")

        df = raw[["Date", *col_map.keys()]].set_index("Date").rename(columns=col_map)
        df.index = df.index.date
        df.index.name = "date"
        return df

    # ─── 工具方法 ─────────────────────────────────────

    @staticmethod
    def _slice_by_period(df: pd.DataFrame, period: str, interval: str) -> pd.DataFrame:
        base = {"1mo": 25, "3mo": 75, "6mo": 130, "1y": 260, "2y": 520}.get(period, 260)
        rows = max(8, base // 5) if interval == "1wk" else base
        return df.tail(rows) if rows > 0 else df

    @staticmethod
    def _period_to_days(period: str) -> int:
        return {"1mo": 35, "3mo": 95, "6mo": 190, "1y": 370, "2y": 740}.get(period, 370)

    @staticmethod
    def _is_proxy_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(k in text for k in ["proxyerror", "unable to connect to proxy", "httpsconnectionpool", "remote end closed connection"])

    @staticmethod
    def _to_yahoo_symbol(symbol: str) -> str:
        s = symbol.strip().upper()
        # A 股转 Yahoo 格式
        if s.isdigit() and len(s) == 6:
            return f"{s}.SS" if s.startswith(("6", "9")) else f"{s}.SZ"
        if s.endswith(".SH"):
            return f"{s.split('.')[0]}.SS"
        # 港股转 Yahoo 格式
        if s.isdigit() and len(s) == 5:
            return f"{s}.HK"
        return s

    @staticmethod
    def _to_stooq_symbol(symbol: str) -> str:
        s = symbol.strip().upper()
        if s.isdigit() and len(s) == 6:
            return f"{s}.cn".lower()
        if s.endswith((".SS", ".SH", ".SZ")):
            return f"{s.split('.')[0]}.cn"
        # 港股转 Stooq 格式
        if s.isdigit() and len(s) == 5:
            return f"{s}.hk".lower()
        if s.endswith(".HK"):
            return f"{s.split('.')[0]}.hk".lower()
        return s.lower()

    @staticmethod
    def _to_cn_code(symbol: str) -> Optional[str]:
        s = symbol.strip().upper()
        if s.isdigit() and len(s) == 6:
            return s
        # 后缀形式: 600519.SS, 600519.SH
        if s.endswith((".SS", ".SH", ".SZ")):
            code = s.split(".")[0]
            if code.isdigit() and len(code) == 6:
                return code
        # 前缀形式: SH601991, SZ000001
        if s.startswith(("SH", "SZ")) and len(s) == 8:
            code = s[2:]
            if code.isdigit() and len(code) == 6:
                return code
        return None

    @classmethod
    def _is_a_share_symbol(cls, symbol: str) -> bool:
        return cls._to_cn_code(symbol) is not None

    def fetch_to_records(self, request: StockDataRequest) -> list[dict]:
        df = self.fetch(request)
        return [
            {
                "date": dt.isoformat() if isinstance(dt, date) else str(dt),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            }
            for dt, row in df.iterrows()
        ]

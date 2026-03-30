from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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
    """Agent 1: 拉取并标准化股票历史行情数据。"""

    REQUIRED_COLUMNS = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }

    STOOQ_COLUMNS = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }

    AK_COLUMNS = {
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
    }

    PROXY_ERROR_HINT = (
        "检测到代理连接失败。可尝试切换 --provider auto/stooq/mock，"
        "或检查并临时清理 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 环境变量。"
    )

    def fetch(self, request: StockDataRequest) -> pd.DataFrame:
        symbol = request.symbol.strip().upper()
        if not symbol:
            raise ValueError("股票代码不能为空。")
        yahoo_symbol = self._to_yahoo_symbol(symbol)

        provider = request.provider.lower()
        if provider not in {"auto", "yahoo", "stooq", "akshare", "mock"}:
            raise ValueError("provider 仅支持 auto / yahoo / stooq / akshare / mock")

        if provider == "mock":
            return self._fetch_mock(symbol=symbol)

        errors: list[str] = []

        is_a_share = self._is_a_share_symbol(symbol)

        if provider in {"auto", "akshare"} and is_a_share:
            try:
                return self._fetch_from_akshare(symbol=symbol, period=request.period, interval=request.interval)
            except Exception as exc:
                errors.append(f"AkShare: {exc}")
                if provider == "akshare":
                    raise ValueError(f"AkShare 获取失败: {exc}") from exc

        if provider in {"auto", "yahoo"}:
            try:
                return self._fetch_from_yahoo(symbol=yahoo_symbol, period=request.period, interval=request.interval)
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

        if provider in {"auto", "akshare"} and not is_a_share and provider == "akshare":
            raise ValueError(f"AkShare 目前仅支持 A 股 6 位代码，当前为: {symbol}")

        if provider == "auto":
            return self._fetch_mock(symbol=symbol)

        error_text = " | ".join(errors) if errors else "未知错误"
        raise ValueError(
            (
                f"未获取到股票 {symbol} 的行情数据。"
                f"建议尝试：A 股使用 6 位代码或显式后缀（如 300209.SZ / 600519.SS），"
                f"并切换 --provider auto/stooq/mock。详情: {error_text}"
            )
        )

    def _fetch_from_yahoo(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        raw = yf.download(
            tickers=symbol,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
        )

        if raw.empty:
            raise ValueError("返回空数据（可能为 Yahoo 限流或网络限制）")

        raw = self._normalize_yahoo_raw(raw)

        missing = [col for col in self.REQUIRED_COLUMNS if col not in raw.columns]
        if missing:
            raise ValueError(f"行情数据缺少必要字段: {missing}")

        df = raw[list(self.REQUIRED_COLUMNS)].rename(columns=self.REQUIRED_COLUMNS).copy()
        df.index = pd.to_datetime(df.index).date
        df.index.name = "date"
        return df

    @staticmethod
    def _normalize_yahoo_raw(raw: pd.DataFrame) -> pd.DataFrame:
        # yfinance 在部分版本/参数下会返回 MultiIndex 列，例如 ("Open", "AAPL")。
        if isinstance(raw.columns, pd.MultiIndex):
            if raw.columns.nlevels >= 2:
                # 优先保留价格字段这一层，若方向相反则保留最后一层价格字段。
                level0 = set(raw.columns.get_level_values(0))
                expected = {"Open", "High", "Low", "Close", "Volume"}
                if expected.intersection(level0):
                    raw = raw.copy()
                    raw.columns = raw.columns.get_level_values(0)
                else:
                    raw = raw.copy()
                    raw.columns = raw.columns.get_level_values(-1)
            else:
                raw = raw.copy()
                raw.columns = [str(c[0]) for c in raw.columns]
        return raw

    def _fetch_from_akshare(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise ValueError("未安装 akshare，请先安装依赖。") from exc

        code = self._to_cn_code(symbol)
        if not code:
            raise ValueError(f"仅支持 A 股 6 位代码，当前为: {symbol}")

        try:
            raw = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="")
        except Exception as exc:
            if self._is_proxy_connection_error(exc):
                raise ValueError(f"{exc}；{self.PROXY_ERROR_HINT}") from exc
            raise
        if raw is None or raw.empty:
            raise ValueError("返回空数据")

        missing = [col for col in self.AK_COLUMNS if col not in raw.columns]
        if missing:
            raise ValueError(f"行情数据缺少必要字段: {missing}")

        df = raw[["日期", *self.AK_COLUMNS.keys()]].copy()
        df = df.rename(columns=self.AK_COLUMNS)
        df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
        df = df.dropna(subset=["日期"]).sort_values("日期")
        df = df.set_index("日期")
        df.index = df.index.date
        df.index.name = "date"

        rows = self._rows_by_period(period=period, interval=interval)
        if rows > 0:
            df = df.tail(rows)
        return df

    @staticmethod
    def _is_proxy_connection_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(
            key in text
            for key in [
                "proxyerror",
                "unable to connect to proxy",
                "httpsconnectionpool",
                "remote end closed connection without response",
            ]
        )

    @staticmethod
    def _rows_by_period(period: str, interval: str) -> int:
        base = {
            "1mo": 25,
            "3mo": 75,
            "6mo": 130,
            "1y": 260,
            "2y": 520,
        }.get(period, 260)
        if interval == "1wk":
            return max(8, base // 5)
        return base

    def _fetch_from_stooq(self, symbol: str) -> pd.DataFrame:
        stooq_symbol = self._to_stooq_symbol(symbol)
        url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"

        try:
            with urlopen(url, timeout=15) as response:
                csv_text = response.read().decode("utf-8", errors="ignore")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ValueError(f"请求失败: {exc}") from exc

        if not csv_text.strip():
            raise ValueError("返回空响应（可能被网络/代理拦截）")

        try:
            raw = pd.read_csv(StringIO(csv_text))
        except pd.errors.EmptyDataError as exc:
            raise ValueError("返回内容不可解析（可能被网络层替换或拦截）") from exc
        if raw.empty or "Date" not in raw.columns:
            raise ValueError("返回空数据")

        expected = ["Open", "High", "Low", "Close", "Volume"]
        missing = [col for col in expected if col not in raw.columns]
        if missing:
            raise ValueError(f"行情数据缺少必要字段: {missing}")

        raw = raw[raw["Close"].notna()].copy()
        raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
        raw = raw.dropna(subset=["Date"]).sort_values("Date")

        df = raw[["Date", *expected]].set_index("Date")
        df = df.rename(columns=self.STOOQ_COLUMNS)
        df.index = df.index.date
        df.index.name = "date"
        return df

    def _fetch_mock(self, symbol: str) -> pd.DataFrame:
        # 生成可复现的调试行情，方便离线联调后续 Agent。
        rng = np.random.default_rng(abs(hash(symbol)) % (2**32))
        dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=180)

        base = 100 + rng.normal(0, 1)
        returns = rng.normal(0.0008, 0.018, size=len(dates))
        close = base * np.cumprod(1 + returns)

        open_p = close * (1 + rng.normal(0.0, 0.004, size=len(dates)))
        high = np.maximum(open_p, close) * (1 + rng.uniform(0.001, 0.015, size=len(dates)))
        low = np.minimum(open_p, close) * (1 - rng.uniform(0.001, 0.015, size=len(dates)))
        volume = rng.integers(800_000, 8_000_000, size=len(dates))

        df = pd.DataFrame(
            {
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            },
            index=dates.date,
        )
        df.index.name = "date"
        return df.round({"open": 2, "high": 2, "low": 2, "close": 2})

    @staticmethod
    def _to_stooq_symbol(symbol: str) -> str:
        s = symbol.strip().upper()

        if s.isdigit() and len(s) == 6:
            return f"{s}.cn".lower()

        if s.endswith((".SS", ".SH", ".SZ")):
            code = s.split(".")[0]
            if code.isdigit() and len(code) == 6:
                return f"{code}.cn"

        return s.lower()

    @staticmethod
    def _to_yahoo_symbol(symbol: str) -> str:
        s = symbol.strip().upper()

        if s.isdigit() and len(s) == 6:
            if s.startswith(("6", "9")):
                return f"{s}.SS"
            return f"{s}.SZ"

        if s.endswith(".SH"):
            code = s.split(".")[0]
            if code.isdigit() and len(code) == 6:
                return f"{code}.SS"

        return s

    @staticmethod
    def _to_cn_code(symbol: str) -> Optional[str]:
        s = symbol.strip().upper()
        if s.isdigit() and len(s) == 6:
            return s
        if s.endswith((".SS", ".SH", ".SZ")):
            code = s.split(".")[0]
            if code.isdigit() and len(code) == 6:
                return code
        return None

    @classmethod
    def _is_a_share_symbol(cls, symbol: str) -> bool:
        return cls._to_cn_code(symbol) is not None

    def fetch_to_records(self, request: StockDataRequest) -> list[dict]:
        df = self.fetch(request)
        records = []
        for dt, row in df.iterrows():
            records.append(
                {
                    "date": dt.isoformat() if isinstance(dt, date) else str(dt),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]),
                }
            )
        return records

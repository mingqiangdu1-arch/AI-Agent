from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error, parse, request


@dataclass
class NewsItem:
    source: str
    title: str
    summary: str
    url: str
    published_at: str
    sentiment_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsAggregationResult:
    query: str
    as_of: str
    summary: dict[str, Any]
    sentiment: dict[str, Any]
    items: list[dict[str, Any]]
    sources: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NewsAggregationAgent:
    """Aggregate market news from Juhe, GNews and Finnhub with normalized sentiment output."""

    POSITIVE_WORDS = {
        "上涨",
        "利好",
        "突破",
        "增长",
        "超预期",
        "改善",
        "盈利",
        "创新高",
        "回购",
        "buy",
        "bullish",
        "upgrade",
        "beat",
        "growth",
        "surge",
        "record high",
    }

    NEGATIVE_WORDS = {
        "下跌",
        "利空",
        "回撤",
        "亏损",
        "暴跌",
        "减持",
        "风险",
        "承压",
        "违约",
        "sell",
        "bearish",
        "downgrade",
        "miss",
        "decline",
        "plunge",
        "warning",
    }

    def aggregate(self, symbol: str, company_name: str | None = None, limit: int = 20) -> NewsAggregationResult:
        cleaned_symbol = symbol.strip().upper()
        query = company_name.strip() if company_name else cleaned_symbol
        max_items = max(6, min(int(limit), 50))

        all_items: list[NewsItem] = []
        source_status: list[dict[str, Any]] = []

        juhe_rows, juhe_err = self._fetch_juhe(query=query, symbol=cleaned_symbol, limit=max_items)
        all_items.extend(juhe_rows)
        source_status.append({"name": "juhe", "count": len(juhe_rows), "status": "ok" if not juhe_err else "error", "error": juhe_err})

        gnews_rows, gnews_err = self._fetch_gnews(query=query, limit=max_items)
        all_items.extend(gnews_rows)
        source_status.append({"name": "gnews", "count": len(gnews_rows), "status": "ok" if not gnews_err else "error", "error": gnews_err})

        finnhub_rows, finnhub_err = self._fetch_finnhub(symbol=cleaned_symbol, limit=max_items)
        all_items.extend(finnhub_rows)
        source_status.append(
            {"name": "finnhub", "count": len(finnhub_rows), "status": "ok" if not finnhub_err else "error", "error": finnhub_err}
        )

        unique: dict[str, NewsItem] = {}
        for item in all_items:
            key = f"{item.title}|{item.url}".strip().lower()
            if key not in unique:
                unique[key] = item

        normalized = list(unique.values())
        normalized.sort(key=lambda x: x.published_at, reverse=True)
        normalized = normalized[:max_items]

        sentiment = self._analyze_sentiment(normalized)
        summary = {
            "total": len(normalized),
            "positive": sentiment["distribution"]["positive"],
            "neutral": sentiment["distribution"]["neutral"],
            "negative": sentiment["distribution"]["negative"],
            "latest_published_at": normalized[0].published_at if normalized else None,
        }

        return NewsAggregationResult(
            query=query,
            as_of=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            sentiment=sentiment,
            items=[x.to_dict() for x in normalized],
            sources=source_status,
        )

    def _fetch_juhe(self, query: str, symbol: str, limit: int) -> tuple[list[NewsItem], str | None]:
        api_key = os.getenv("JUHE_API_KEY", "").strip()
        if not api_key:
            return [], "missing JUHE_API_KEY"

        # Juhe 财经资讯接口字段会随套餐变动，采用宽松解析。
        params = parse.urlencode({"type": "caijing", "key": api_key}, encoding="utf-8")
        url = f"http://v.juhe.cn/toutiao/index?{params}"
        try:
            payload = self._request_json(url)
            rows = ((payload or {}).get("result") or {}).get("data") or []
            out: list[NewsItem] = []
            for row in rows:
                title = str(row.get("title") or "").strip()
                if not title:
                    continue
                if query not in title and symbol not in title:
                    continue
                summary = str(row.get("author_name") or row.get("category") or "").strip()
                news_url = str(row.get("url") or "").strip()
                published_at = self._parse_time(row.get("date"))
                sentiment_score = self._score_text(f"{title} {summary}")
                out.append(
                    NewsItem(
                        source="juhe",
                        title=title,
                        summary=summary,
                        url=news_url,
                        published_at=published_at,
                        sentiment_score=sentiment_score,
                    )
                )
                if len(out) >= limit:
                    break
            return out, None
        except Exception as exc:
            return [], str(exc)

    def _fetch_gnews(self, query: str, limit: int) -> tuple[list[NewsItem], str | None]:
        api_key = os.getenv("GNEWS_API_KEY", "").strip()
        if not api_key:
            return [], "missing GNEWS_API_KEY"

        params = parse.urlencode(
            {
                "q": query,
                "lang": "zh,en",
                "sortby": "publishedAt",
                "max": min(limit, 20),
                "token": api_key,
            },
            encoding="utf-8",
        )
        url = f"https://gnews.io/api/v4/search?{params}"
        try:
            payload = self._request_json(url)
            rows = (payload or {}).get("articles") or []
            out: list[NewsItem] = []
            for row in rows:
                title = str(row.get("title") or "").strip()
                if not title:
                    continue
                summary = str(row.get("description") or "").strip()
                news_url = str(row.get("url") or "").strip()
                published_at = self._parse_time(row.get("publishedAt"))
                sentiment_score = self._score_text(f"{title} {summary}")
                out.append(
                    NewsItem(
                        source="gnews",
                        title=title,
                        summary=summary,
                        url=news_url,
                        published_at=published_at,
                        sentiment_score=sentiment_score,
                    )
                )
            return out[:limit], None
        except Exception as exc:
            return [], str(exc)

    def _fetch_finnhub(self, symbol: str, limit: int) -> tuple[list[NewsItem], str | None]:
        api_key = os.getenv("FINNHUB_API_KEY", "").strip()
        if not api_key:
            return [], "missing FINNHUB_API_KEY"

        today = datetime.now(timezone.utc).date()
        from_day = today - timedelta(days=14)
        params = parse.urlencode(
            {
                "symbol": symbol,
                "from": from_day.isoformat(),
                "to": today.isoformat(),
                "token": api_key,
            },
            encoding="utf-8",
        )
        url = f"https://finnhub.io/api/v1/company-news?{params}"
        try:
            rows = self._request_json(url)
            if not isinstance(rows, list):
                return [], "unexpected finnhub payload"
            out: list[NewsItem] = []
            for row in rows:
                title = str(row.get("headline") or "").strip()
                if not title:
                    continue
                summary = str(row.get("summary") or "").strip()
                news_url = str(row.get("url") or "").strip()
                published_at = self._parse_time(row.get("datetime"))
                sentiment_score = self._score_text(f"{title} {summary}")
                out.append(
                    NewsItem(
                        source="finnhub",
                        title=title,
                        summary=summary,
                        url=news_url,
                        published_at=published_at,
                        sentiment_score=sentiment_score,
                    )
                )
            out.sort(key=lambda x: x.published_at, reverse=True)
            return out[:limit], None
        except Exception as exc:
            return [], str(exc)

    @staticmethod
    def _request_json(url: str) -> Any:
        req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
        try:
            with request.urlopen(req, timeout=20) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
            raise RuntimeError(f"HTTP {exc.code}: {detail[:180]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"URL Error: {exc.reason}") from exc

        try:
            return json.loads(text)
        except Exception as exc:
            raise RuntimeError("invalid json response") from exc

    @staticmethod
    def _parse_time(value: Any) -> str:
        if value is None:
            return datetime.now(timezone.utc).isoformat()

        if isinstance(value, (int, float)):
            # finnhub datetime is unix timestamp seconds.
            ts = float(value)
            if ts > 1e12:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        text = str(value).strip()
        if not text:
            return datetime.now(timezone.utc).isoformat()

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.strptime(text, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                continue

        return datetime.now(timezone.utc).isoformat()

    def _score_text(self, text: str) -> float:
        lowered = (text or "").lower()
        pos = sum(1 for kw in self.POSITIVE_WORDS if kw in lowered)
        neg = sum(1 for kw in self.NEGATIVE_WORDS if kw in lowered)
        if pos == 0 and neg == 0:
            return 0.0
        raw = (pos - neg) / max(pos + neg, 1)
        return max(-1.0, min(1.0, round(raw, 3)))

    def _analyze_sentiment(self, items: list[NewsItem]) -> dict[str, Any]:
        if not items:
            return {
                "label": "neutral",
                "score": 0.0,
                "confidence": 0.2,
                "distribution": {"positive": 0, "neutral": 0, "negative": 0},
            }

        positive = 0
        neutral = 0
        negative = 0
        total_score = 0.0
        for item in items:
            s = item.sentiment_score
            total_score += s
            if s > 0.15:
                positive += 1
            elif s < -0.15:
                negative += 1
            else:
                neutral += 1

        mean_score = total_score / len(items)
        if mean_score > 0.12:
            label = "positive"
        elif mean_score < -0.12:
            label = "negative"
        else:
            label = "neutral"

        confidence = min(0.95, 0.35 + abs(mean_score) * 0.5 + min(len(items), 20) * 0.015)
        return {
            "label": label,
            "score": round(mean_score, 3),
            "confidence": round(confidence, 2),
            "distribution": {
                "positive": positive,
                "neutral": neutral,
                "negative": negative,
            },
        }

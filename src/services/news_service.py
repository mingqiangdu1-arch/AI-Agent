"""新闻聚合服务模块。

整合新闻获取、情绪分析和 LLM 增强。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error, parse, request

from src.core.config import NewsConfig, get_config
from src.core.exceptions import NewsAggregationError
from src.core.models import NewsItem, NewsResult, NewsSentiment, now_iso
from src.services.llm_service import LLMService, get_llm_service


class NewsService:
    """新闻聚合服务。"""

    POSITIVE_WORDS = {
        "上涨", "利好", "突破", "增长", "超预期", "改善", "盈利", "创新高", "回购",
        "buy", "bullish", "upgrade", "beat", "growth", "surge", "record high",
    }

    NEGATIVE_WORDS = {
        "下跌", "利空", "回撤", "亏损", "暴跌", "减持", "风险", "承压", "违约",
        "sell", "bearish", "downgrade", "miss", "decline", "plunge", "warning",
    }

    def __init__(
        self,
        config: NewsConfig | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        self._config = config or get_config().news
        self._llm = llm_service or get_llm_service()

    def aggregate(
        self,
        symbol: str,
        company_name: str | None = None,
        limit: int = 20,
    ) -> NewsResult:
        """聚合并分析新闻。"""
        cleaned_symbol = symbol.strip().upper()
        query = company_name.strip() if company_name else cleaned_symbol
        max_items = max(6, min(int(limit), 50))

        all_items: list[NewsItem] = []
        source_status: list[dict[str, Any]] = []

        # 东方财富新闻（免费，无需 API Key）
        em_rows, em_err = self._fetch_eastmoney_news(symbol=cleaned_symbol, limit=max_items)
        all_items.extend(em_rows)
        source_status.append({"name": "eastmoney", "count": len(em_rows), "status": "ok" if not em_err else "error", "error": em_err})

        # 并行获取各数据源（需要 API Key）
        juhe_rows, juhe_err = self._fetch_juhe(query=query, symbol=cleaned_symbol, limit=max_items)
        all_items.extend(juhe_rows)
        source_status.append({"name": "juhe", "count": len(juhe_rows), "status": "ok" if not juhe_err else "error", "error": juhe_err})

        gnews_rows, gnews_err = self._fetch_gnews(query=query, limit=max_items)
        all_items.extend(gnews_rows)
        source_status.append({"name": "gnews", "count": len(gnews_rows), "status": "ok" if not gnews_err else "error", "error": gnews_err})

        finnhub_rows, finnhub_err = self._fetch_finnhub(symbol=cleaned_symbol, limit=max_items)
        all_items.extend(finnhub_rows)
        source_status.append({"name": "finnhub", "count": len(finnhub_rows), "status": "ok" if not finnhub_err else "error", "error": finnhub_err})

        # 去重并排序
        unique: dict[str, NewsItem] = {}
        for item in all_items:
            key = f"{item.title}|{item.url}".strip().lower()
            if key not in unique:
                unique[key] = item

        normalized = sorted(unique.values(), key=lambda x: x.published_at, reverse=True)[:max_items]

        # 基础情绪分析
        sentiment = self._analyze_sentiment(normalized)
        summary = {
            "total": len(normalized),
            "positive": sentiment.distribution["positive"],
            "neutral": sentiment.distribution["neutral"],
            "negative": sentiment.distribution["negative"],
            "latest_published_at": normalized[0].published_at if normalized else None,
        }

        return NewsResult(
            query=query,
            as_of=now_iso(),
            summary=summary,
            sentiment=sentiment,
            items=normalized,
            sources=source_status,
        )

    def enhance_sentiment_with_llm(
        self,
        result: NewsResult,
        symbol: str,
        company_name: str,
        config: Any | None = None,
    ) -> NewsSentiment:
        """使用 LLM 增强情绪分析。"""
        if not self._llm.is_configured():
            return result.sentiment

        try:
            payload = {
                "symbol": symbol,
                "symbol_name": company_name,
                "news_summary": result.summary,
                "news_items": [
                    {
                        "source": x.source,
                        "title": x.title,
                        "summary": x.summary,
                        "published_at": x.published_at,
                    }
                    for x in result.items[:10]
                ],
            }
            llm_data = self._llm.call_with_prompt("news_sentiment_prompt", payload, config)
            return self._normalize_llm_sentiment(llm_data, result.sentiment)
        except Exception:
            return result.sentiment

    def _fetch_eastmoney_news(self, symbol: str, limit: int) -> tuple[list[NewsItem], str | None]:
        """从东方财富获取股票新闻（免费，无需 API Key）。"""
        try:
            import akshare as ak
        except ModuleNotFoundError:
            return [], "akshare not installed"

        try:
            df = ak.stock_news_em(symbol=symbol)
            if df is None or df.empty:
                return [], None

            out: list[NewsItem] = []
            for _, row in df.iterrows():
                title = str(row.get("新闻标题") or "").strip()
                if not title:
                    continue

                summary = str(row.get("新闻内容") or "").strip()
                if len(summary) > 200:
                    summary = summary[:200] + "..."

                news_url = str(row.get("新闻链接") or "").strip()
                source = str(row.get("文章来源") or "东方财富").strip()
                published_at = self._parse_time(row.get("发布时间"))
                sentiment_score = self._score_text(f"{title} {summary}")

                out.append(NewsItem(
                    source=f"eastmoney/{source}",
                    title=title,
                    summary=summary,
                    url=news_url,
                    published_at=published_at,
                    sentiment_score=sentiment_score,
                ))
                if len(out) >= limit:
                    break

            return out, None
        except Exception as exc:
            return [], str(exc)

    def _fetch_juhe(self, query: str, symbol: str, limit: int) -> tuple[list[NewsItem], str | None]:
        api_key = self._config.juhe_api_key
        if not api_key:
            return [], "missing JUHE_API_KEY"

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
                out.append(NewsItem(
                    source="juhe",
                    title=title,
                    summary=summary,
                    url=news_url,
                    published_at=published_at,
                    sentiment_score=sentiment_score,
                ))
                if len(out) >= limit:
                    break
            return out, None
        except Exception as exc:
            return [], str(exc)

    def _fetch_gnews(self, query: str, limit: int) -> tuple[list[NewsItem], str | None]:
        api_key = self._config.gnews_api_key
        if not api_key:
            return [], "missing GNEWS_API_KEY"

        params = parse.urlencode({
            "q": query,
            "lang": "zh,en",
            "sortby": "publishedAt",
            "max": min(limit, 20),
            "token": api_key,
        }, encoding="utf-8")
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
                out.append(NewsItem(
                    source="gnews",
                    title=title,
                    summary=summary,
                    url=news_url,
                    published_at=published_at,
                    sentiment_score=sentiment_score,
                ))
            return out[:limit], None
        except Exception as exc:
            return [], str(exc)

    def _fetch_finnhub(self, symbol: str, limit: int) -> tuple[list[NewsItem], str | None]:
        api_key = self._config.finnhub_api_key
        if not api_key:
            return [], "missing FINNHUB_API_KEY"

        today = datetime.now(timezone.utc).date()
        from_day = today - timedelta(days=14)
        params = parse.urlencode({
            "symbol": symbol,
            "from": from_day.isoformat(),
            "to": today.isoformat(),
            "token": api_key,
        }, encoding="utf-8")
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
                out.append(NewsItem(
                    source="finnhub",
                    title=title,
                    summary=summary,
                    url=news_url,
                    published_at=published_at,
                    sentiment_score=sentiment_score,
                ))
            out.sort(key=lambda x: x.published_at, reverse=True)
            return out[:limit], None
        except Exception as exc:
            return [], str(exc)

    def _score_text(self, text: str) -> float:
        lowered = (text or "").lower()
        pos = sum(1 for kw in self.POSITIVE_WORDS if kw in lowered)
        neg = sum(1 for kw in self.NEGATIVE_WORDS if kw in lowered)
        if pos == 0 and neg == 0:
            return 0.0
        raw = (pos - neg) / max(pos + neg, 1)
        return max(-1.0, min(1.0, round(raw, 3)))

    def _analyze_sentiment(self, items: list[NewsItem]) -> NewsSentiment:
        if not items:
            return NewsSentiment()

        positive = neutral = negative = 0
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
        return NewsSentiment(
            label=label,
            score=round(mean_score, 3),
            confidence=round(confidence, 2),
            distribution={"positive": positive, "neutral": neutral, "negative": negative},
        )

    def _normalize_llm_sentiment(self, data: dict[str, Any], fallback: NewsSentiment) -> NewsSentiment:
        label = str(data.get("sentiment", data.get("label", fallback.label))).strip().lower()
        if label not in {"positive", "neutral", "negative"}:
            label = "neutral"

        raw_score = data.get("score")
        if raw_score is None:
            raw_score = {"positive": 0.6, "neutral": 0.0, "negative": -0.6}.get(label, 0.0)
        score = round(max(-1.0, min(1.0, float(raw_score))), 3)

        confidence = float(data.get("confidence", fallback.confidence))
        confidence = round(max(0.0, min(1.0, confidence)), 2)

        reasons = data.get("reasoning", fallback.reasoning)
        if isinstance(reasons, list):
            reasoning = [str(x).strip() for x in reasons if str(x).strip()][:3]
        else:
            reasoning = fallback.reasoning

        return NewsSentiment(
            label=label,
            score=score,
            confidence=confidence,
            reasoning=reasoning,
            distribution=fallback.distribution,
        )

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
            return now_iso()

        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        text = str(value).strip()
        if not text:
            return now_iso()

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.strptime(text, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                continue

        return now_iso()


# 全局新闻服务实例
_news_service: NewsService | None = None


def get_news_service() -> NewsService:
    """获取全局新闻服务实例。"""
    global _news_service
    if _news_service is None:
        _news_service = NewsService()
    return _news_service

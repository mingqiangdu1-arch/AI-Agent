from __future__ import annotations

import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# 加载 .env 文件
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from src.api.schemas import (
    APIResponse,
    AnalyzeRequest,
    LLMAnalysisRequest,
    MarketHotRequest,
    ModelConfigRequest,
    ReportHubRequest,
    StrategyRequest,
    TrendRequest,
)
from src.core.config import KNOWN_SYMBOL_NAMES
from src.core.models import now_iso
from src.services.analysis_service import AnalysisService, safe_response
from src.services.sector_service import get_sector_service

# 反向映射：名称 → 代码
_NAME_TO_CODE: dict[str, str] = {}
for _k, _v in KNOWN_SYMBOL_NAMES.items():
    if not _k.endswith((".SS", ".SH", ".SZ", ".HK")):
        _NAME_TO_CODE[_v] = _k
        _NAME_TO_CODE[_v.lower()] = _k


ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend_v2"

app = FastAPI(title="AI 投研 Agent V2 API", version="2.0.0")
service = AnalysisService()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


@app.get("/", response_model=None)
def index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend not found. Open /docs for API usage."}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze", response_model=APIResponse)
def analyze(payload: AnalyzeRequest) -> dict:
    return safe_response(
        service.run_analyze,
        symbol=payload.symbol,
        provider=payload.provider,
        period=payload.period,
        interval=payload.interval,
        hot_limit=payload.hot_limit,
        mode=payload.mode,
    )


@app.post("/trend", response_model=APIResponse)
def trend(payload: TrendRequest) -> dict:
    return safe_response(
        service.run_trend,
        symbol=payload.symbol,
        provider=payload.provider,
        period=payload.period,
        interval=payload.interval,
    )


@app.post("/strategy", response_model=APIResponse)
def strategy(payload: StrategyRequest) -> dict:
    return safe_response(
        service.run_strategy,
        symbol=payload.symbol,
        provider=payload.provider,
        period=payload.period,
        interval=payload.interval,
    )


@app.post("/market_hot", response_model=APIResponse)
def market_hot(payload: MarketHotRequest) -> dict:
    return safe_response(
        service.run_market_hot,
        limit=payload.limit,
        preferred_source=payload.preferred_source,
    )


@app.post("/llm_analysis", response_model=APIResponse)
def llm_analysis(payload: LLMAnalysisRequest) -> dict:
    return safe_response(
        service.run_llm_analysis,
        symbol=payload.symbol,
        provider=payload.provider,
        period=payload.period,
        interval=payload.interval,
        hot_limit=payload.hot_limit,
    )


@app.post("/model_config", response_model=APIResponse)
def model_config() -> dict:
    return safe_response(service.run_model_config)


# 研报缓存（内存，最多保留20份）
_report_cache: list[dict] = []
_report_lock = threading.Lock()

@app.post("/report_hub", response_model=APIResponse)
def report_hub(payload: ReportHubRequest) -> dict:
    result = safe_response(
        service.run_report_hub,
        symbol=payload.symbol,
        provider=payload.provider,
        period=payload.period,
        interval=payload.interval,
    )
    if result.get("status") == "success" and result.get("data"):
        report_data = dict(result["data"])
        report_data["_cached_at"] = now_iso()
        with _report_lock:
            _report_cache.insert(0, report_data)
            if len(_report_cache) > 20:
                _report_cache.pop()
    return result

@app.get("/report_list")
def report_list() -> dict:
    """返回已缓存的研报列表。"""
    with _report_lock:
        snap = list(_report_cache)
    summaries = []
    for r in snap:
        try:
            report = r.get("llm_report", {})
            scores = report.get("overall_score", {}) if isinstance(report, dict) else {}
            summaries.append({
                "symbol": r.get("symbol"),
                "symbol_name": r.get("symbol_name"),
                "report_id": r.get("report_id"),
                "generated_at": r.get("generated_at"),
                "score": scores.get("comprehensive") or scores.get("technical") or 50,
                "trend": r.get("trend", {}).get("trend", "") if isinstance(r.get("trend"), dict) else (r.get("trend") or ""),
            })
        except Exception:
            continue
    return {"code": 0, "message": "success", "status": "success", "data": summaries, "error": None, "meta": {"count": len(summaries)}}

@app.get("/report_detail/{report_id}")
def report_detail(report_id: str) -> dict:
    """获取指定研报详情。"""
    with _report_lock:
        snap = list(_report_cache)
    for r in snap:
        if r.get("report_id") == report_id:
            return {"code": 0, "message": "success", "status": "success", "data": r, "error": None, "meta": {}}
    return {"code": 1, "message": "研报不存在", "status": "error", "data": None, "error": "report not found", "meta": {}}



@app.post("/sector_recommend", response_model=APIResponse)
def sector_recommend() -> dict:
    """板块推荐接口。"""
    try:
        sector_service = get_sector_service()
        data = sector_service.get_sector_summary(limit=8)
        return {"code": 0, "message": "success", "status": "success", "data": data, "error": None, "meta": {}}
    except Exception as exc:
        return {"code": 1, "message": str(exc), "status": "error", "data": None, "error": str(exc), "meta": {}}


# 热榜名称→代码缓存（TTL 5 分钟）
_hot_name_cache: dict[str, str] | None = None
_hot_name_cache_ts: float = 0.0
_hot_name_lock = threading.Lock()
_NAME_CACHE_TTL = 300

# 代码→名称快速映射（从 KNOWN_SYMBOL_NAMES 预建，零网络开销）
_CODE_TO_NAME: dict[str, str] = {}
for _k, _v in KNOWN_SYMBOL_NAMES.items():
    _CODE_TO_NAME[_k] = _v
    _CODE_TO_NAME[_k.upper()] = _v
    # 带后缀的也加无后缀版本
    for _sfx in (".SS", ".SH", ".SZ", ".HK"):
        if _k.endswith(_sfx):
            _CODE_TO_NAME[_k[: -len(_sfx)]] = _v
            _CODE_TO_NAME[_k[: -len(_sfx)].upper()] = _v


def _get_name_cache() -> dict[str, str]:
    global _hot_name_cache, _hot_name_cache_ts
    now = time.time()
    if _hot_name_cache is not None and (now - _hot_name_cache_ts) < _NAME_CACHE_TTL:
        return _hot_name_cache
    # 避免并发重复构建
    with _hot_name_lock:
        if _hot_name_cache is not None and (now - _hot_name_cache_ts) < _NAME_CACHE_TTL:
            return _hot_name_cache
        from src.agents.hot_rank_agent import THSHotRankAgent
        _hot_name_cache = THSHotRankAgent.build_name_code_map()
        _hot_name_cache_ts = time.time()
        return _hot_name_cache


@app.get("/resolve_symbol")
def resolve_symbol(name: str = "") -> dict:
    """双向解析：名称→代码 或 代码→名称（零网络延迟优先）。"""
    if not name or not name.strip():
        return {"code": "", "name": name, "found": False}

    cleaned = name.strip()

    # ── 方向 1: 代码 → 名称（零网络延迟）──
    stock_name = _CODE_TO_NAME.get(cleaned) or _CODE_TO_NAME.get(cleaned.upper())
    if stock_name:
        return {"code": cleaned, "name": stock_name, "found": True}

    # ── 方向 2: 名称 → 代码（零网络延迟）──
    code = _NAME_TO_CODE.get(cleaned) or _NAME_TO_CODE.get(cleaned.lower())
    if code:
        return {"code": code, "name": cleaned, "found": True}

    # ── 方向 3: 热榜名称→代码（有网络开销，仅在前两步未命中时）──
    try:
        name_cache = _get_name_cache()
        code = name_cache.get(cleaned) or name_cache.get(cleaned.lower())
        if code:
            return {"code": code, "name": cleaned, "found": True}
        # 反过来：热榜也可能有代码→名称映射
        for _n, _c in name_cache.items():
            if _c == cleaned:
                return {"code": cleaned, "name": _n, "found": True}
    except Exception:
        pass

    return {"code": "", "name": cleaned, "found": False}


# ── 启动预热 ──────────────────────────────────────────────
@app.on_event("startup")
def _preheat_caches():
    """后台预热：提前拉取名称映射、行情数据、热榜数据（并行）。"""

    def _warm():
        # 1. 名称→代码映射
        try:
            _get_name_cache()
        except Exception:
            pass
        # 2. 行情 + 热榜并行获取
        # 顺序执行预热（避免并发限流）：spot → hot(east) → hot(ths)
        def _fetch_spot():
            try:
                from src.services.analysis_service import _set_cached_spot
                import akshare as ak
                spot = ak.stock_zh_a_spot()
                if spot is not None and not spot.empty:
                    _set_cached_spot(spot)
            except Exception:
                pass

        def _fetch_hot(src: str):
            try:
                from src.services.analysis_service import _set_cached_hot
                from src.agents.hot_rank_agent import HotRankRequest, THSHotRankAgent
                agent = THSHotRankAgent()
                hot_df = agent.fetch(HotRankRequest(limit=50, preferred_source=src))
                _set_cached_hot(src, hot_df.to_dict(orient="records"))
            except Exception:
                pass

        _fetch_spot()
        time.sleep(2)
        _fetch_hot("east")
        time.sleep(2)
        _fetch_hot("ths")

    threading.Thread(target=_warm, daemon=True).start()


@app.get("/market_summary")
def market_summary() -> dict:
    """市场指数摘要。"""
    import time as _time
    from datetime import date as _date, timedelta as _tdelta
    import akshare as ak

    indices = [
        ("sh000001", "上证指数"),
        ("sz399001", "深证成指"),
        ("sz399006", "创业板指"),
    ]
    result: list[dict] = []
    today = _date.today()

    for code, name in indices:
        try:
            df = ak.stock_zh_index_daily(symbol=code)
            if df is not None and not df.empty:
                # Get two most recent rows for change calculation
                recent = df.tail(2)
                curr = float(recent.iloc[-1]["close"])
                prev = float(recent.iloc[-2]["close"]) if len(recent) >= 2 else curr
                chg = round(curr - prev, 2)
                chg_pct = round((curr - prev) / prev * 100, 2) if prev != 0 else 0
                result.append({
                    "name": name,
                    "code": code,
                    "price": curr,
                    "change": chg,
                    "change_pct": chg_pct,
                    "updated": str(recent.iloc[-1].get("date", today)),
                })
        except Exception:
            result.append({"name": name, "code": code, "price": None, "change": 0, "change_pct": 0, "updated": str(today)})

    return {"code": 0, "message": "success", "status": "success", "data": result, "error": None, "meta": {}}



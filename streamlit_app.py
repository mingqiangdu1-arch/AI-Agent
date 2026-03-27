from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

import pandas as pd

from src.agents.data_fetch_agent import StockDataFetchAgent, StockDataRequest
from src.agents.hot_rank_agent import HotRankRequest, THSHotRankAgent
from src.agents.llm_analysis_agent import LLMAnalysisAgent, LLMAnalysisConfig
from src.agents.strategy_generation_agent import StrategyGenerationAgent
from src.agents.trend_analysis_agent import TrendAnalysisAgent


LLM_PROVIDER_PRESETS = {
    "阿里百炼(Qwen)": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "env_keys": ["DASHSCOPE_API_KEY", "OPENAI_API_KEY"],
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "env_keys": ["OPENAI_API_KEY"],
    },
    "Gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "env_keys": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "env_keys": ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"],
    },
    "Moonshot(Kimi)": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "env_keys": ["MOONSHOT_API_KEY", "OPENAI_API_KEY"],
    },
    "智谱(GLM)": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
        "env_keys": ["ZHIPUAI_API_KEY", "OPENAI_API_KEY"],
    },
    "OpenRouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "env_keys": ["OPENROUTER_API_KEY", "OPENAI_API_KEY"],
    },
    "硅基流动(SiliconFlow)": {
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
        "env_keys": ["SILICONFLOW_API_KEY", "OPENAI_API_KEY"],
    },
    "火山方舟(Ark)": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "",
        "env_keys": ["ARK_API_KEY", "VOLCENGINE_API_KEY", "OPENAI_API_KEY"],
    },
    "自定义(OpenAI兼容)": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "env_keys": ["OPENAI_API_KEY"],
    },
}


STOCK_NAME_CACHE_TTL = timedelta(hours=12)
STOCK_NAME_CACHE: dict[str, tuple[datetime, str]] = {}


def _load_ui_deps():
    try:
        import plotly.graph_objects as go  # type: ignore
        import streamlit as st  # type: ignore
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "缺少可视化依赖，请先执行: .\\.venv\\Scripts\\python.exe -m pip install streamlit plotly"
        ) from exc
    return st, go


def run_pipeline(symbol: str, provider: str, period: str, interval: str, llm_config: LLMAnalysisConfig | None):
    data_agent = StockDataFetchAgent()
    trend_agent = TrendAnalysisAgent()
    strategy_agent = StrategyGenerationAgent()
    llm_agent = LLMAnalysisAgent()

    request = StockDataRequest(
        symbol=symbol,
        provider=provider,
        period=period,
        interval=interval,
    )
    df = data_agent.fetch(request)
    trend_result = trend_agent.analyze(df)
    strategy_result = strategy_agent.generate(df, trend_result)

    llm_result = None
    llm_error = None
    if llm_config is not None:
        try:
            llm_result = llm_agent.analyze(
                symbol=symbol,
                price_df=df,
                trend_result=trend_result,
                strategy_result=strategy_result,
                config=llm_config,
            )
        except Exception as exc:
            llm_error = str(exc)

    return df, trend_result, strategy_result, llm_result, llm_error


def fetch_hot_rank(limit: int) -> pd.DataFrame:
    agent = THSHotRankAgent()
    return agent.fetch(HotRankRequest(limit=limit, preferred_source="ths"))


def resolve_stock_display_name(symbol: str, provider: str) -> str:
    symbol_clean = symbol.strip().upper()
    if not symbol_clean:
        return "未知标的"

    cache_key = f"{provider}:{symbol_clean}"
    now = datetime.now()
    cached = STOCK_NAME_CACHE.get(cache_key)
    if cached is not None:
        cached_at, cached_name = cached
        if now - cached_at <= STOCK_NAME_CACHE_TTL:
            return cached_name

    resolved_name = symbol_clean

    code_match = re.match(r"^(\d{6})(?:\.[A-Z]{2})?$", symbol_clean)
    if provider != "mock" and code_match:
        code = code_match.group(1)
        try:
            import akshare as ak  # type: ignore

            info_df = ak.stock_individual_info_em(symbol=code)
            if not info_df.empty:
                item_col = "item" if "item" in info_df.columns else "项目"
                value_col = "value" if "value" in info_df.columns else "值"
                if item_col in info_df.columns and value_col in info_df.columns:
                    for key in ["股票简称", "证券简称", "名称"]:
                        row = info_df[info_df[item_col].astype(str).str.contains(key, na=False)]
                        if not row.empty:
                            name = str(row.iloc[0][value_col]).strip()
                            if name:
                                resolved_name = f"{name} ({symbol_clean})"
                                STOCK_NAME_CACHE[cache_key] = (now, resolved_name)
                                return resolved_name
        except Exception:
            pass

    try:
        import yfinance as yf

        yahoo_symbol = StockDataFetchAgent._to_yahoo_symbol(symbol_clean)
        ticker = yf.Ticker(yahoo_symbol)
        info = ticker.info if hasattr(ticker, "info") else {}
        name = str(info.get("shortName") or info.get("longName") or "").strip()
        if name:
            resolved_name = f"{name} ({symbol_clean})"
            STOCK_NAME_CACHE[cache_key] = (now, resolved_name)
            return resolved_name
    except Exception:
        pass

    STOCK_NAME_CACHE[cache_key] = (now, resolved_name)
    return resolved_name


def detect_market_type(symbol: str) -> str:
    s = symbol.strip().upper()
    if re.match(r"^\d{6}(\.(SS|SZ|SH|BJ))?$", s):
        return "domestic"
    if s.endswith((".SS", ".SZ", ".SH", ".BJ", ".HK")):
        return "domestic"
    return "international"


def get_market_colors(market_type: str) -> dict[str, str]:
    # 国内市场习惯: 红涨绿跌；海外常见: 绿涨红跌。
    if market_type == "domestic":
        return {
            "up": "#F44336",
            "down": "#4CAF50",
            "neutral": "#F2C94C",
        }
    return {
        "up": "#4CAF50",
        "down": "#F44336",
        "neutral": "#F2C94C",
    }


def _parse_percent_like(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _style_change_cell(value, market_colors: dict[str, str]) -> str:
    numeric = _parse_percent_like(value)
    if numeric is None:
        return ""
    if numeric > 0:
        return f"color: {market_colors['up']}; font-weight: 600;"
    if numeric < 0:
        return f"color: {market_colors['down']}; font-weight: 600;"
    return f"color: {market_colors['neutral']};"


def build_candlestick(df: pd.DataFrame, symbol_display: str, go, market_type: str):
    data = df.copy().sort_index()
    data = data.tail(120)
    x_axis = pd.to_datetime(data.index.astype(str))
    colors = get_market_colors(market_type)

    ma10 = data["close"].rolling(10).mean()
    ma20 = data["close"].rolling(20).mean()
    ma30 = data["close"].rolling(30).mean()
    volume = data["volume"].astype(float)

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=x_axis,
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["close"],
            name="K线",
            increasing=dict(line=dict(color=colors["up"]), fillcolor=colors["up"]),
            decreasing=dict(line=dict(color=colors["down"]), fillcolor=colors["down"]),
        )
    )
    fig.add_trace(go.Scatter(x=x_axis, y=ma10, mode="lines", name="MA10", line=dict(width=2, color="#6FCF97")))
    fig.add_trace(go.Scatter(x=x_axis, y=ma20, mode="lines", name="MA20", line=dict(width=2, color="#56CCF2")))
    fig.add_trace(go.Scatter(x=x_axis, y=ma30, mode="lines", name="MA30", line=dict(width=2, color="#F2C94C")))
    fig.add_trace(
        go.Bar(
            x=x_axis,
            y=volume,
            name="Volume",
            yaxis="y2",
            marker=dict(color="#5B6574", opacity=0.5),
        )
    )
    fig.update_layout(
        title=f"{symbol_display} 近120日价格走势",
        xaxis_title="日期",
        yaxis_title="价格",
        yaxis2=dict(title="成交量", overlaying="y", side="right", showgrid=False),
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        paper_bgcolor="#1A1D23",
        plot_bgcolor="#1A1D23",
        font=dict(color="#E8EDF5"),
        height=520,
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def inject_styles(st) -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600;700&display=swap');

html, body, [class*="css"]  {
    font-family: 'Noto Sans SC', sans-serif;
}

.stApp {
    background: radial-gradient(circle at 10% 10%, #1B202A 0%, #101115 45%);
    color: #F2F4F7;
}

div[data-testid="stVerticalBlock"] > div:has(> .gem-header) {
    background: #101115;
    border: 1px solid #2A2E37;
    border-radius: 12px;
    padding: 0.65rem 1rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
}

.gem-header-title {
    font-size: 1.2rem;
    font-weight: 700;
    letter-spacing: 0.2px;
}

.gem-subtle {
    color: #A0A6AD;
    font-size: 0.85rem;
}

.gem-parameter-card {
    background: #141821;
    border: 1px solid #2A2E37;
    border-radius: 12px;
    padding: 0.9rem;
    margin-top: 0.75rem;
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.25);
}

.gem-card {
    background: #1A1D23;
    border: 1px solid #2A2E37;
    border-radius: 12px;
    padding: 0.9rem 1rem;
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.22);
}

.gem-metric-label {
    color: #A0A6AD;
    font-size: 0.86rem;
}

.gem-metric-value {
    font-size: 1.65rem;
    font-weight: 700;
    color: #F2F4F7;
}

.trend-up {
    color: #4CAF50;
}

.trend-down {
    color: #F44336;
}

.trend-flat {
    color: #F2C94C;
}

.gem-alert {
    background: rgba(244, 67, 54, 0.15);
    border: 1px solid rgba(244, 67, 54, 0.45);
    color: #F8D7DA;
    border-radius: 10px;
    padding: 0.65rem 0.8rem;
    margin-bottom: 0.8rem;
}

.gem-ok {
    background: rgba(66, 133, 244, 0.15);
    border: 1px solid rgba(66, 133, 244, 0.45);
    color: #DCE8FF;
    border-radius: 10px;
    padding: 0.65rem 0.8rem;
    margin-bottom: 0.8rem;
}

div[data-testid="stButton"] > button {
    border-radius: 10px;
    border: 1px solid #3A4354;
    background: #1E2430;
    color: #F2F4F7;
    transition: all 0.2s ease;
}

div[data-testid="stButton"] > button:hover {
    border-color: #5A6A85;
    transform: translateY(-1px);
}

div[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(90deg, #3B82F6 0%, #4285F4 100%);
    border-color: #4285F4;
}

.gem-status-pill {
    display: inline-block;
    border-radius: 999px;
    padding: 0.16rem 0.55rem;
    font-size: 0.75rem;
    margin-left: 0.45rem;
    border: 1px solid #3A4354;
    color: #DCE8FF;
    background: rgba(66, 133, 244, 0.2);
}

.gem-status-pill.ok {
    border-color: rgba(76, 175, 80, 0.6);
    color: #D9F7E0;
    background: rgba(76, 175, 80, 0.2);
}

.gem-status-pill.bad {
    border-color: rgba(244, 67, 54, 0.6);
    color: #F8D7DA;
    background: rgba(244, 67, 54, 0.2);
}

.gem-confidence-track {
    width: 100%;
    height: 8px;
    margin-top: 0.55rem;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.1);
    overflow: hidden;
}

.gem-confidence-fill {
    height: 100%;
    border-radius: 999px;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def get_effective_model(provider_name: str, model_input: str) -> str:
    preset = LLM_PROVIDER_PRESETS.get(provider_name, LLM_PROVIDER_PRESETS["Gemini"])
    fallback_model = str(preset.get("model", "")).strip()
    manual_model = model_input.strip()
    return manual_model or fallback_model


def detect_provider_by_api_key(api_key: str, current_provider: str) -> str | None:
    key = api_key.strip()
    if not key:
        return None
    if key.startswith("AIza"):
        return "Gemini"
    if key.startswith("sk-or-"):
        return "OpenRouter"
    if key.startswith("dsk-"):
        return "DeepSeek"
    if key.startswith("sk-"):
        # sk- keys are used by multiple providers; in Gemini default context, prefer DeepSeek.
        if current_provider in {"Gemini", "DeepSeek"}:
            return "DeepSeek"
        return "OpenAI"
    return None


def build_analysis_report_markdown(
    symbol_display: str,
    trend_result,
    strategy_result,
    llm_result,
) -> str:
    lines = [
        f"# AI 投研分析报告 - {symbol_display}",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- 声明: 本报告仅用于投研辅助，不构成任何投资建议。",
        "",
        "## 一、趋势分析",
        f"- 趋势判断: {trend_result.trend}",
        f"- 趋势置信度: {trend_result.confidence:.2f}",
        f"- 最新收盘价: {trend_result.latest_close:.2f}",
        f"- 均线摘要: {trend_result.ma_summary}",
        f"- MACD 摘要: {trend_result.macd_summary}",
        f"- RSI 摘要: {trend_result.rsi_summary}",
        "- 风险提示:",
    ]
    lines.extend([f"  - {x}" for x in trend_result.risk_alerts])

    lines.extend(
        [
            "",
            "## 二、策略建议",
            f"- 关注建议: {strategy_result.attention_advice}",
            f"- 关注区间: {strategy_result.attention_range}",
            f"- 目标价格: {strategy_result.target_price:.2f}",
            f"- 止损价格: {strategy_result.stop_loss_price:.2f}",
            "- 主要风险:",
        ]
    )
    lines.extend([f"  - {x}" for x in strategy_result.risk_factors])

    if llm_result is not None and str(llm_result.summary).strip():
        lines.extend(
            [
                "",
                "## 三、AI 深度解读（LLM）",
                str(llm_result.summary).strip(),
            ]
        )

    return "\n".join(lines)


def render_header(st):
    left, right1, right2, right3, right4 = st.columns([8, 1.2, 1.2, 1.2, 1.2])
    with left:
        status_class = ""
        status_text = "未测试"
        if st.session_state.get("llm_conn_status") is True:
            status_class = "ok"
            status_text = "API连通正常"
        elif st.session_state.get("llm_conn_status") is False:
            status_class = "bad"
            status_text = "API连通异常"

        st.markdown(
            (
                f'<div class="gem-header"><span class="gem-header-title">📈 AI 投研 Agent</span>'
                f'<span class="gem-status-pill {status_class}">{status_text}</span></div>'
            ),
            unsafe_allow_html=True,
        )
    with right1:
        with st.popover("⚙️ 设置", use_container_width=True):
            st.caption("API 设置")
            auto_detect = st.toggle("自动识别服务与模型", value=bool(st.session_state.auto_detect_provider), key="cfg_auto_detect")

            show_key = st.toggle("显示 API Key", value=False, key="cfg_show_key")
            api_key_input = st.text_input(
                "API Key",
                value=st.session_state.api_key,
                type="default" if show_key else "password",
                key="cfg_api_key",
            )

            provider_name = st.session_state.provider_name
            base_url = st.session_state.base_url
            model = st.session_state.model

            detected_provider = detect_provider_by_api_key(api_key_input, st.session_state.provider_name)
            if auto_detect:
                if detected_provider:
                    detected_preset = LLM_PROVIDER_PRESETS[detected_provider]
                    st.caption(f"已识别服务：{detected_provider}，将使用默认模型 {detected_preset['model'] or '需手动填写'}")
                elif api_key_input.strip():
                    st.caption("未能从 Key 唯一识别服务，将使用当前配置继续。")

            with st.expander("高级配置（可选）", expanded=not auto_detect):
                provider_name = st.selectbox(
                    "模型服务",
                    options=list(LLM_PROVIDER_PRESETS.keys()),
                    index=list(LLM_PROVIDER_PRESETS.keys()).index(st.session_state.provider_name),
                    key="cfg_provider_name",
                    disabled=auto_detect,
                )
                preset = LLM_PROVIDER_PRESETS[provider_name]
                base_url = st.text_input(
                    "Base URL",
                    value=st.session_state.base_url or preset["base_url"],
                    key="cfg_base_url",
                    disabled=auto_detect,
                )
                model = st.text_input(
                    "模型名称（留空使用默认）",
                    value=st.session_state.model,
                    key="cfg_model",
                    disabled=auto_detect,
                )
                st.caption(f"默认模型：{preset['model'] or '该服务需手动填写模型'}")
                if provider_name == "Gemini":
                    st.caption("Gemini 请使用 GEMINI_API_KEY 或 GOOGLE_API_KEY，不会读取 OPENAI_API_KEY。")

            temperature = st.slider("Temperature", min_value=0.0, max_value=1.0, value=float(st.session_state.temperature), step=0.1, key="cfg_temperature")
            max_tokens = st.slider("Max Tokens", min_value=256, max_value=4096, value=int(st.session_state.max_tokens), step=64, key="cfg_max_tokens")
            enabled = st.toggle("启用 AI 增强分析", value=bool(st.session_state.llm_enabled), key="cfg_llm_enabled")

            if st.button("测试连接", use_container_width=True):
                test_provider = provider_name
                test_base_url = base_url.strip()
                test_model = model.strip()
                if auto_detect and detected_provider:
                    test_provider = detected_provider
                    test_base_url = LLM_PROVIDER_PRESETS[detected_provider]["base_url"]
                    test_model = ""

                test_preset = LLM_PROVIDER_PRESETS.get(test_provider, LLM_PROVIDER_PRESETS["Gemini"])
                test_key = api_key_input.strip()
                if not test_key:
                    for env_name in test_preset["env_keys"]:
                        env_value = os.getenv(env_name)
                        if env_value:
                            test_key = env_value
                            break

                effective_test_model = get_effective_model(test_provider, test_model)
                if not test_key:
                    st.warning("请先输入 API Key，或配置对应环境变量后再测试连接。")
                elif not effective_test_model:
                    st.warning("当前服务未配置默认模型，请先填写模型名称。")
                else:
                    tester = LLMAnalysisAgent()
                    ok, message = tester.test_connection(
                        LLMAnalysisConfig(
                            base_url=test_base_url,
                            api_key=test_key,
                            model=effective_test_model,
                            temperature=float(temperature),
                            max_tokens=int(max_tokens),
                        )
                    )
                    if ok:
                        st.session_state.llm_conn_status = True
                        st.session_state.llm_conn_message = message
                        if auto_detect and detected_provider:
                            detected_apply = LLM_PROVIDER_PRESETS[detected_provider]
                            st.session_state.provider_name = detected_provider
                            st.session_state.base_url = detected_apply["base_url"]
                            st.session_state.model = ""
                        st.success(f"连通性通过：{message}")
                    else:
                        st.session_state.llm_conn_status = False
                        st.session_state.llm_conn_message = message
                        st.error(f"连通性失败：{message}")

            if st.button("保存", use_container_width=True):
                st.session_state.auto_detect_provider = bool(auto_detect)
                if auto_detect and detected_provider:
                    auto_preset = LLM_PROVIDER_PRESETS[detected_provider]
                    st.session_state.provider_name = detected_provider
                    st.session_state.base_url = auto_preset["base_url"]
                    st.session_state.model = ""
                else:
                    st.session_state.provider_name = provider_name
                    st.session_state.base_url = base_url.strip()
                    st.session_state.model = model.strip()
                st.session_state.api_key = api_key_input.strip()
                st.session_state.temperature = float(temperature)
                st.session_state.max_tokens = int(max_tokens)
                st.session_state.llm_enabled = bool(enabled)
                effective_model = get_effective_model(st.session_state.provider_name, st.session_state.model)
                if effective_model:
                    st.toast(f"设置已保存（服务：{st.session_state.provider_name}，模型：{effective_model}）", icon="✅")
                else:
                    st.toast("设置已保存（请填写模型名称）", icon="⚠️")
    with right2:
        if st.button("📷", use_container_width=True, help="截图建议：Windows 使用 Win + Shift + S"):
            st.toast("请使用系统截图快捷键 Win + Shift + S", icon="📸")
    with right3:
        if st.button("Stop", use_container_width=True):
            st.toast("当前无后台任务可停止", icon="⏹️")
    with right4:
        if st.button("Deploy", use_container_width=True):
            st.toast("可按 README 指引部署到 Streamlit Cloud", icon="🚀")


def ensure_state(st) -> None:
    if "run_once" not in st.session_state:
        st.session_state.run_once = False
    if "provider_name" not in st.session_state:
        st.session_state.provider_name = "Gemini"
    if "base_url" not in st.session_state:
        st.session_state.base_url = LLM_PROVIDER_PRESETS["Gemini"]["base_url"]
    if "model" not in st.session_state:
        st.session_state.model = ""
    if "api_key" not in st.session_state:
        st.session_state.api_key = ""
    if "temperature" not in st.session_state:
        st.session_state.temperature = 0.2
    if "max_tokens" not in st.session_state:
        st.session_state.max_tokens = 1200
    if "llm_enabled" not in st.session_state:
        st.session_state.llm_enabled = False
    if "auto_detect_provider" not in st.session_state:
        st.session_state.auto_detect_provider = True
    if "llm_conn_status" not in st.session_state:
        st.session_state.llm_conn_status = None
    if "llm_conn_message" not in st.session_state:
        st.session_state.llm_conn_message = ""


def render_page() -> None:
    st, go = _load_ui_deps()
    st.set_page_config(page_title="AI 投研 Agent", page_icon="📈", layout="wide")
    inject_styles(st)
    ensure_state(st)
    render_header(st)
    st.caption("免责声明：本产品仅用于投研辅助，不构成任何投资建议。")

    st.markdown('<div class="gem-parameter-card">', unsafe_allow_html=True)
    p1, p2, p3, p4, p5 = st.columns([2.5, 1.2, 1.2, 1.2, 1.2])
    with p1:
        symbol = st.text_input("股票代码", value="600519.SS", help="如 300209 / 600519.SS / AAPL")
    with p2:
        provider = st.selectbox("数据源", options=["auto", "akshare", "stooq", "yahoo", "mock"], index=0)
    with p3:
        period = st.selectbox("周期", options=["1mo", "3mo", "6mo", "1y", "2y"], index=2)
    with p4:
        interval = st.selectbox("K线间隔", options=["1d", "1wk"], index=0)
    with p5:
        st.caption("&nbsp;")
        run_btn = st.button("开始分析", type="primary", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if run_btn:
        st.session_state.run_once = True

    if not st.session_state.run_once:
        st.info("点击左侧‘开始分析’查看图表与策略结果。")
        return

    if not symbol.strip():
        st.markdown('<div class="gem-alert">股票代码不能为空</div>', unsafe_allow_html=True)
        return

    symbol_display = resolve_stock_display_name(symbol.strip(), provider)
    market_type = detect_market_type(symbol.strip())
    market_colors = get_market_colors(market_type)

    llm_config: LLMAnalysisConfig | None = None
    if st.session_state.llm_enabled:
        preset = LLM_PROVIDER_PRESETS.get(st.session_state.provider_name, LLM_PROVIDER_PRESETS["Gemini"])
        env_key = ""
        matched_env_name = ""
        for key_name in preset["env_keys"]:
            value = os.getenv(key_name)
            if value:
                env_key = value
                matched_env_name = key_name
                break

        effective_key = st.session_state.api_key.strip() or env_key
        llm_config = LLMAnalysisConfig(
            base_url=st.session_state.base_url.strip() or preset["base_url"],
            api_key=effective_key,
            model=get_effective_model(st.session_state.provider_name, st.session_state.model),
            temperature=float(st.session_state.temperature),
            max_tokens=int(st.session_state.max_tokens),
        )

        if not effective_key:
            st.markdown('<div class="gem-alert">已启用 AI 增强分析，但未提供 API Key。当前将仅展示基础分析。</div>', unsafe_allow_html=True)
        elif st.session_state.provider_name == "Gemini" and not effective_key.startswith("AIza"):
            st.markdown('<div class="gem-alert">当前看起来不是 Gemini API Key。请检查是否使用了 AI Studio 生成的 Key（通常以 AIza 开头）。</div>', unsafe_allow_html=True)
        elif not llm_config.model:
            st.markdown('<div class="gem-alert">当前服务未配置默认模型，请在设置中填写模型名称。</div>', unsafe_allow_html=True)
        elif not st.session_state.api_key.strip():
            st.markdown(
                f'<div class="gem-ok">已使用环境变量中的 API Key（{matched_env_name}）。</div>',
                unsafe_allow_html=True,
            )

    try:
        with st.spinner("正在拉取数据并生成分析..."):
            df, trend_result, strategy_result, llm_result, llm_error = run_pipeline(
                symbol.strip(), provider, period, interval, llm_config
            )
    except Exception as exc:
        st.error(f"分析失败: {exc}")
        st.stop()

    latest_change = 0.0
    if len(df) >= 2:
        latest_change = (float(df["close"].iloc[-1]) / float(df["close"].iloc[-2]) - 1.0) * 100

    vol_20 = float(df["close"].pct_change().tail(20).std() * (20**0.5) * 100) if len(df) >= 22 else 0.0
    vol_ratio = float(df["volume"].tail(5).mean() / max(df["volume"].tail(20).mean(), 1)) if len(df) >= 20 else 1.0

    trend_class = "trend-flat"
    trend_icon = "↔"
    if trend_result.trend == "上涨":
        trend_class = "trend-up"
        trend_icon = "↗"
    elif trend_result.trend == "下跌":
        trend_class = "trend-down"
        trend_icon = "↘"

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        trend_color = (
            market_colors["up"]
            if trend_result.trend == "上涨"
            else market_colors["down"] if trend_result.trend == "下跌" else market_colors["neutral"]
        )
        confidence_pct = max(0, min(100, int(trend_result.confidence * 100)))
        st.markdown(
            (
                f'<div class="gem-card"><div class="gem-metric-label">趋势判断</div>'
                f'<div class="gem-metric-value {trend_class}" style="color:{trend_color};">{trend_icon} {trend_result.trend}</div>'
                f'<div class="gem-subtle">信赖度 {trend_result.confidence:.2f}</div>'
                f'<div class="gem-confidence-track"><div class="gem-confidence-fill" style="width:{confidence_pct}%;background:{trend_color};"></div></div></div>'
            ),
            unsafe_allow_html=True,
        )
    with c2:
        change_color = market_colors["up"] if latest_change >= 0 else market_colors["down"]
        st.markdown(
            f'<div class="gem-card"><div class="gem-metric-label">最新收盘价</div><div class="gem-metric-value">{trend_result.latest_close:.2f}</div><div style="color:{change_color};font-size:0.95rem;">{latest_change:+.2f}%</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        risk_title = strategy_result.risk_factors[0] if strategy_result.risk_factors else "暂无"
        st.markdown(
            f'<div class="gem-card"><div class="gem-metric-label">主要风险</div><div style="font-size:1rem;line-height:1.55;">⚠️ {risk_title}</div></div>',
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f'<div class="gem-card"><div class="gem-metric-label">市场波动/量能</div><div style="font-size:1rem;line-height:1.55;">20日波动: {vol_20:.2f}%<br>量比(5/20): {vol_ratio:.2f}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown(f'<div class="gem-ok">当前标的：{symbol_display}</div>', unsafe_allow_html=True)
    if st.session_state.llm_conn_message:
        st.caption(f"LLM 连通性: {st.session_state.llm_conn_message}")

    st.markdown('<div class="gem-card">', unsafe_allow_html=True)
    st.plotly_chart(build_candlestick(df, symbol_display, go, market_type), use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    left, right = st.columns(2)

    with left:
        st.markdown('<div class="gem-card">', unsafe_allow_html=True)
        st.subheader("AI 市场趋势分析")
        st.markdown(f"- 均线摘要: {trend_result.ma_summary}")
        st.markdown(f"- MACD 摘要: {trend_result.macd_summary}")
        st.markdown(f"- RSI 摘要: {trend_result.rsi_summary}")
        st.markdown("- 风险提示:")
        for item in trend_result.risk_alerts:
            st.markdown(f"  - {item}")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="gem-card">', unsafe_allow_html=True)
        st.subheader("投资策略建议")
        st.markdown(f"- 关注建议: {strategy_result.attention_advice}")
        st.markdown(f"- 关注区间: {strategy_result.attention_range}")
        st.markdown(f"- 目标价格: {strategy_result.target_price:.2f}")
        st.markdown(f"- 止损价格: {strategy_result.stop_loss_price:.2f}")
        st.markdown("- 主要风险:")
        for item in strategy_result.risk_factors:
            st.markdown(f"  - {item}")
        st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.llm_enabled:
        st.markdown('<div class="gem-card">', unsafe_allow_html=True)
        st.subheader("AI 深度解读（LLM）")
        st.caption(f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if llm_config is not None and not llm_config.api_key:
            st.markdown('<div class="gem-alert">已启用 AI 增强分析，但尚未提供 API Key。当前仅展示基础分析结果。</div>', unsafe_allow_html=True)
        elif llm_error:
            st.markdown(f'<div class="gem-alert">AI 增强分析暂不可用，已回退基础分析：{llm_error}</div>', unsafe_allow_html=True)
        elif llm_result is not None:
            st.markdown(llm_result.summary)
            st.caption(f"模型接口: {llm_result.provider_hint}")
            if llm_result.finish_reason.lower() in {"length", "max_tokens"}:
                st.markdown('<div class="gem-alert">本次 AI 输出疑似被长度截断。可提高 Max Tokens 后重试。</div>', unsafe_allow_html=True)
            elif len(llm_result.summary.strip()) < 120:
                st.markdown('<div class="gem-ok">本次 AI 输出较短，建议提高 Max Tokens 或切换更强模型后重试。</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="gem-ok">AI 增强分析未返回结果，当前仅展示基础分析。</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="gem-card">', unsafe_allow_html=True)
    st.subheader("最近交易数据")
    show_df = df.tail(30).copy()
    show_df["涨跌幅(%)"] = (show_df["close"].pct_change() * 100).round(2)
    show_df["涨跌幅(%)"] = show_df["涨跌幅(%)"].map(lambda x: "" if pd.isna(x) else f"{x:+.2f}%")
    show_df.index = show_df.index.astype(str)
    show_df_styled = show_df.style.map(
        lambda v: _style_change_cell(v, market_colors),
        subset=["涨跌幅(%)"],
    )
    st.dataframe(show_df_styled, use_container_width=True)
    report_text = build_analysis_report_markdown(symbol_display, trend_result, strategy_result, llm_result)
    st.download_button(
        "下载分析报告（Markdown）",
        data=report_text,
        file_name=f"analysis_report_{symbol.strip().upper()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        mime="text/markdown",
        use_container_width=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="gem-card">', unsafe_allow_html=True)
    st.subheader("热榜 TOP10")
    try:
        hot_df = fetch_hot_rank(10)
        if "涨跌幅" in hot_df.columns:
            hot_df_styled = hot_df.style.map(
                lambda v: _style_change_cell(v, market_colors),
                subset=["涨跌幅"],
            )
            st.dataframe(hot_df_styled, use_container_width=True)
        else:
            st.dataframe(hot_df, use_container_width=True)
    except Exception as exc:
        st.markdown(f'<div class="gem-alert">热榜暂不可用: {exc}</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    try:
        render_page()
    except ModuleNotFoundError as exc:
        print(str(exc))

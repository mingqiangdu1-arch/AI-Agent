from __future__ import annotations

import pandas as pd

from src.agents.data_fetch_agent import StockDataFetchAgent, StockDataRequest
from src.agents.strategy_generation_agent import StrategyGenerationAgent
from src.agents.trend_analysis_agent import TrendAnalysisAgent


def _load_ui_deps():
    try:
        import plotly.graph_objects as go  # type: ignore
        import streamlit as st  # type: ignore
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "缺少可视化依赖，请先执行: .\\.venv\\Scripts\\python.exe -m pip install streamlit plotly"
        ) from exc
    return st, go


def run_pipeline(symbol: str, provider: str, period: str, interval: str):
    data_agent = StockDataFetchAgent()
    trend_agent = TrendAnalysisAgent()
    strategy_agent = StrategyGenerationAgent()

    request = StockDataRequest(
        symbol=symbol,
        provider=provider,
        period=period,
        interval=interval,
    )
    df = data_agent.fetch(request)
    trend_result = trend_agent.analyze(df)
    strategy_result = strategy_agent.generate(df, trend_result)
    return df, trend_result, strategy_result


def build_candlestick(df: pd.DataFrame, symbol: str, go):
    data = df.copy().sort_index()
    data = data.tail(120)
    x_axis = pd.to_datetime(data.index.astype(str))

    ma10 = data["close"].rolling(10).mean()
    ma20 = data["close"].rolling(20).mean()

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=x_axis,
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["close"],
            name="K线",
        )
    )
    fig.add_trace(go.Scatter(x=x_axis, y=ma10, mode="lines", name="MA10", line=dict(width=2)))
    fig.add_trace(go.Scatter(x=x_axis, y=ma20, mode="lines", name="MA20", line=dict(width=2)))
    fig.update_layout(
        title=f"{symbol.upper()} 近120日价格走势",
        xaxis_title="日期",
        yaxis_title="价格",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        height=520,
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def render_page() -> None:
    st, go = _load_ui_deps()
    st.set_page_config(page_title="AI 投研 Agent", page_icon="📈", layout="wide")
    st.title("AI 投研 Agent - 分析结果展示")
    st.caption("仅用于投研辅助，不构成投资建议。")

    with st.sidebar:
        st.subheader("参数设置")
        symbol = st.text_input("股票代码", value="600519.SS", help="如 300209 / 600519.SS / AAPL")
        provider = st.selectbox("数据源", options=["auto", "stooq", "yahoo", "mock"], index=0)
        period = st.selectbox("周期", options=["1mo", "3mo", "6mo", "1y", "2y"], index=2)
        interval = st.selectbox("K线间隔", options=["1d", "1wk"], index=0)
        run_btn = st.button("开始分析", type="primary", use_container_width=True)

    if "run_once" not in st.session_state:
        st.session_state.run_once = False

    if run_btn:
        st.session_state.run_once = True

    if not st.session_state.run_once:
        st.info("点击左侧‘开始分析’查看图表与策略结果。")
        return

    if not symbol.strip():
        st.error("股票代码不能为空")
        return

    try:
        with st.spinner("正在拉取数据并生成分析..."):
            df, trend_result, strategy_result = run_pipeline(symbol.strip(), provider, period, interval)
    except Exception as exc:
        st.error(f"分析失败: {exc}")
        st.stop()

    c1, c2, c3 = st.columns(3)
    c1.metric("趋势判断", trend_result.trend)
    c2.metric("趋势置信度", f"{trend_result.confidence:.2f}")
    c3.metric("最新收盘价", f"{trend_result.latest_close:.2f}")

    st.plotly_chart(build_candlestick(df, symbol, go), use_container_width=True)

    left, right = st.columns(2)

    with left:
        st.subheader("AI 市场趋势分析")
        st.markdown(f"- 均线摘要: {trend_result.ma_summary}")
        st.markdown(f"- MACD 摘要: {trend_result.macd_summary}")
        st.markdown(f"- RSI 摘要: {trend_result.rsi_summary}")
        st.markdown("- 风险提示:")
        for item in trend_result.risk_alerts:
            st.markdown(f"  - {item}")

    with right:
        st.subheader("投资策略建议")
        st.markdown(f"- 关注建议: {strategy_result.attention_advice}")
        st.markdown(f"- 关注区间: {strategy_result.attention_range}")
        st.markdown(f"- 目标价格: {strategy_result.target_price:.2f}")
        st.markdown(f"- 止损价格: {strategy_result.stop_loss_price:.2f}")
        st.markdown("- 主要风险:")
        for item in strategy_result.risk_factors:
            st.markdown(f"  - {item}")

    st.subheader("最近交易数据")
    show_df = df.tail(30).copy()
    show_df.index = show_df.index.astype(str)
    st.dataframe(show_df, use_container_width=True)


if __name__ == "__main__":
    try:
        render_page()
    except ModuleNotFoundError as exc:
        print(str(exc))

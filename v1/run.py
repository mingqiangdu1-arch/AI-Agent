from __future__ import annotations

import argparse
import json
from src.agents.data_fetch_agent import StockDataFetchAgent, StockDataRequest
from src.agents.strategy_generation_agent import StrategyGenerationAgent
from src.agents.trend_analysis_agent import TrendAnalysisAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AI 投研 Agent 统一启动入口（测试阶段推荐）"
    )
    parser.add_argument("--symbol", default=None, help="股票代码，如 600519.SS / AAPL；不传则运行时输入")
    parser.add_argument(
        "--module",
        choices=["data", "trend", "strategy"],
        default="strategy",
        help="执行模块：data / trend / strategy",
    )
    parser.add_argument(
        "--provider",
        choices=["auto", "yahoo", "stooq", "akshare", "mock"],
        default="auto",
        help="默认真实数据（auto: Yahoo/Stooq 失败自动回退 AkShare）；可切换 mock",
    )
    parser.add_argument("--period", default="6mo", help="数据周期，如 1mo/6mo/1y")
    parser.add_argument("--interval", default="1d", help="K 线间隔，如 1d/1wk")
    parser.add_argument("--limit", type=int, default=20, help="仅 data 模块时展示最近 N 条")
    parser.add_argument("--format", choices=["table", "json"], default="table", help="输出格式")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    symbol = args.symbol
    if not symbol:
        symbol = input("请输入股票代码（如 300209 / 600519.SS / AAPL）: ").strip()
    if not symbol:
        raise ValueError("未输入股票代码，程序已退出。")

    data_agent = StockDataFetchAgent()
    request = StockDataRequest(
        symbol=symbol,
        period=args.period,
        interval=args.interval,
        provider=args.provider,
    )
    df = data_agent.fetch(request)

    if args.module == "data":
        if args.format == "json":
            print(json.dumps(data_agent.fetch_to_records(request)[-args.limit :], ensure_ascii=False, indent=2))
            return
        print(f"股票: {symbol.upper()} | 数据源: {args.provider}")
        print(df.tail(args.limit).to_string())
        return

    trend_agent = TrendAnalysisAgent()
    trend_result = trend_agent.analyze(df)

    if args.module == "trend":
        if args.format == "json":
            print(json.dumps(trend_result.to_dict(), ensure_ascii=False, indent=2))
            return
        print(f"股票: {symbol.upper()} | 数据源: {args.provider}")
        print(trend_agent.render_text_report(trend_result))
        return

    strategy_agent = StrategyGenerationAgent()
    strategy_result = strategy_agent.generate(df, trend_result)

    if args.format == "json":
        payload = {
            "trend": trend_result.to_dict(),
            "strategy": strategy_result.to_dict(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"股票: {symbol.upper()} | 数据源: {args.provider}")
    print("[趋势分析]")
    print(trend_agent.render_text_report(trend_result))
    print("\n[策略建议]")
    print(strategy_agent.render_text_report(strategy_result))


if __name__ == "__main__":
    main()

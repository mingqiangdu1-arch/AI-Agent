from __future__ import annotations

import argparse
import json

from agents.data_fetch_agent import StockDataFetchAgent, StockDataRequest
from agents.strategy_generation_agent import StrategyGenerationAgent
from agents.trend_analysis_agent import TrendAnalysisAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI 投研 Agent - 模块1/2/3: 数据获取 + 趋势分析 + 策略生成")
    parser.add_argument("symbol", help="股票代码，如 600519.SS 或 AAPL")
    parser.add_argument(
        "--module",
        choices=["data", "trend", "strategy"],
        default="data",
        help="执行模块：data=仅输出行情，trend=趋势分析，strategy=策略建议",
    )
    parser.add_argument("--period", default="6mo", help="数据周期，如 1mo/6mo/1y")
    parser.add_argument("--interval", default="1d", help="K 线间隔，如 1d/1wk")
    parser.add_argument(
        "--provider",
        choices=["auto", "yahoo", "stooq", "akshare", "mock"],
        default="auto",
        help="数据源，A 股下 auto 优先 AkShare，再回退 Yahoo/Stooq；mock 用于离线调试",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="输出格式",
    )
    parser.add_argument("--limit", type=int, default=20, help="最多展示最近 N 条记录")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    data_agent = StockDataFetchAgent()
    request = StockDataRequest(
        symbol=args.symbol,
        period=args.period,
        interval=args.interval,
        provider=args.provider,
    )

    df = data_agent.fetch(request)
    out_df = df.tail(args.limit)

    if args.module == "trend":
        trend_agent = TrendAnalysisAgent()
        result = trend_agent.analyze(df)
        if args.format == "json":
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return
        print(
            f"股票: {args.symbol.upper()} | 周期: {args.period} | 间隔: {args.interval} | 数据源: {args.provider}"
        )
        print(trend_agent.render_text_report(result))
        return

    if args.module == "strategy":
        trend_agent = TrendAnalysisAgent()
        strategy_agent = StrategyGenerationAgent()
        trend_result = trend_agent.analyze(df)
        result = strategy_agent.generate(df, trend_result)
        if args.format == "json":
            payload = {
                "trend": trend_result.to_dict(),
                "strategy": result.to_dict(),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        print(
            f"股票: {args.symbol.upper()} | 周期: {args.period} | 间隔: {args.interval} | 数据源: {args.provider}"
        )
        print("[趋势分析]")
        print(trend_agent.render_text_report(trend_result))
        print("\n[策略建议]")
        print(strategy_agent.render_text_report(result))
        return

    if args.format == "json":
        print(json.dumps(data_agent.fetch_to_records(request)[-args.limit :], ensure_ascii=False, indent=2))
        return

    print(
        f"股票: {args.symbol.upper()} | 周期: {args.period} | 间隔: {args.interval} | 数据源: {args.provider}"
    )
    print(out_df.to_string())


if __name__ == "__main__":
    main()

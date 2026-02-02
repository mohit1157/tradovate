#!/usr/bin/env python3
"""
Main entry point for the Autonomous Trading Bot.

Usage:
    python run_bot.py

Or with custom config:
    python run_bot.py --symbol MNQH5 --demo
"""

import asyncio
import argparse
import signal
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from src.bot.trading_bot import TradingBot, BotConfig


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Autonomous Futures Trading Bot with Tradovate"
    )

    parser.add_argument(
        "--symbol",
        type=str,
        default=os.getenv("TRADING_SYMBOL", "MNQH5"),
        help="Trading symbol (e.g., MNQH5, MESH5)",
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        default=True,
        help="Use demo/sim environment (default: True)",
    )

    parser.add_argument(
        "--live",
        action="store_true",
        help="Use live environment (WARNING: real money!)",
    )

    parser.add_argument(
        "--no-sentiment",
        action="store_true",
        help="Disable sentiment analysis, use technicals only",
    )

    parser.add_argument(
        "--max-contracts",
        type=int,
        default=int(os.getenv("MAX_CONTRACTS", "1")),
        help="Maximum contracts per trade",
    )

    parser.add_argument(
        "--max-daily-loss",
        type=float,
        default=float(os.getenv("MAX_DAILY_LOSS", "500")),
        help="Maximum daily loss before kill switch",
    )

    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_args()

    # Print banner
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║       AUTONOMOUS FUTURES TRADING BOT - TRADOVATE             ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  Technical Analysis: EMA Crossover + ATR Risk Management     ║
    ║  Sentiment Analysis: Twitter, Reddit, News + Gemini AI       ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

    # Check for required credentials
    username = os.getenv("TRADOVATE_USERNAME")
    password = os.getenv("TRADOVATE_PASSWORD")

    if not username or not password:
        print("ERROR: Missing Tradovate credentials!")
        print()
        print("Please set the following environment variables in .env:")
        print("  TRADOVATE_USERNAME=your_username")
        print("  TRADOVATE_PASSWORD=your_password")
        print()
        print("Optional API key authentication:")
        print("  TRADOVATE_CID=your_client_id")
        print("  TRADOVATE_SECRET=your_api_secret")
        print()
        print("Get credentials from: https://trader.tradovate.com/")
        sys.exit(1)

    # Determine environment
    demo = not args.live

    if not demo:
        print("=" * 60)
        print("WARNING: LIVE TRADING MODE - REAL MONEY AT RISK!")
        print("=" * 60)
        confirm = input("Type 'YES' to confirm live trading: ")
        if confirm != "YES":
            print("Aborting.")
            sys.exit(0)

    # Create bot config
    config = BotConfig(
        username=username,
        password=password,
        app_id=os.getenv("TRADOVATE_APP_ID"),
        cid=int(os.getenv("TRADOVATE_CID")) if os.getenv("TRADOVATE_CID") else None,
        secret=os.getenv("TRADOVATE_SECRET"),
        demo=demo,
        symbols=[args.symbol],
        max_contracts=args.max_contracts,
        max_daily_loss=args.max_daily_loss,
        use_sentiment=not args.no_sentiment,
        use_technicals=True,
    )

    print(f"Environment: {'DEMO' if demo else 'LIVE'}")
    print(f"Symbol: {args.symbol}")
    print(f"Max Contracts: {args.max_contracts}")
    print(f"Max Daily Loss: ${args.max_daily_loss}")
    print(f"Sentiment Analysis: {'Enabled' if config.use_sentiment else 'Disabled'}")
    print()

    # Create and start bot
    bot = TradingBot(config)

    # Handle shutdown gracefully
    def shutdown_handler(signum, frame):
        print("\nShutting down...")
        asyncio.create_task(bot.stop())

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Start bot
    if await bot.start():
        print()
        print("Bot is running. Press Ctrl+C to stop.")
        print("-" * 60)

        # Keep running
        while bot._running:
            await asyncio.sleep(10)

            # Print status periodically
            status = bot.get_status()
            om_stats = status.get("order_manager", {})
            print(
                f"[{status['symbols'][0]}] "
                f"Daily P&L: ${om_stats.get('daily_pnl', 0):.2f} | "
                f"Trades: {om_stats.get('daily_trades', 0)} | "
                f"Positions: {om_stats.get('open_positions', 0)}"
            )

    else:
        print("Failed to start bot!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

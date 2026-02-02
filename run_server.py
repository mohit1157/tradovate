#!/usr/bin/env python3
"""
Entry point for running the signal server.

Usage:
    python run_server.py

Or with uvicorn directly:
    uvicorn src.server.signal_server:app --host 127.0.0.1 --port 8787
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


def main():
    import uvicorn
    from config.settings import settings

    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║     AUTONOMOUS FUTURES TRADING BOT - SIGNAL SERVER           ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  Sentiment Analysis powered by:                              ║
    ║    • Google Gemini AI                                        ║
    ║    • Twitter/X sentiment                                     ║
    ║    • Reddit sentiment                                        ║
    ║    • Financial news                                          ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

    print(f"Starting server on http://{settings.server_host}:{settings.server_port}")
    print(f"Signal endpoint: http://{settings.server_host}:{settings.server_port}/signal?symbol=MNQ")
    print(f"Health endpoint: http://{settings.server_host}:{settings.server_port}/health")
    print()
    print("Press Ctrl+C to stop the server")
    print("-" * 60)

    uvicorn.run(
        "src.server.signal_server:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()

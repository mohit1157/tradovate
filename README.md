# Autonomous Futures Trading Bot

An AI-powered autonomous futures trading bot that integrates NinjaTrader 8 with sentiment analysis from social media (Twitter/X, Reddit) and financial news, using Google Gemini for intelligent decision making.

## Features

### Sentiment Analysis
- **Twitter/X Integration**: Real-time sentiment from financial Twitter, tracking cashtags and influential accounts
- **Reddit Integration**: Monitors r/wallstreetbets, r/futures, r/stocks and other trading subreddits
- **News Integration**: Aggregates sentiment from major financial news sources (NewsAPI, Alpha Vantage)
- **Gemini AI**: Uses Google's Gemini Pro for advanced sentiment analysis and decision making

### Trading Execution (NinjaTrader 8)
- **Technical Analysis**: EMA crossover strategy with ATR-based risk management
- **External Signal Mode**: Receives AI-powered signals from the sentiment analysis server
- **Hybrid Approach**: Combines sentiment with technical signals for better decisions

### Risk Management
- **Daily Loss Limits**: Automatic kill switch when daily loss exceeds threshold
- **Trade Limits**: Maximum trades per day to prevent overtrading
- **Position Sizing**: Confidence-based position sizing
- **Trailing Stops**: Optional ATR-based trailing stops
- **Cooldown Period**: Minimum time between trades

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA SOURCES                              │
├──────────────┬──────────────┬──────────────┬────────────────┤
│   Twitter    │    Reddit    │    News      │  Market Data   │
└──────┬───────┴──────┬───────┴──────┬───────┴────────┬───────┘
       │              │              │                │
       └──────────────┼──────────────┘                │
                      ▼                               │
       ┌──────────────────────────────┐              │
       │    GEMINI AI ANALYZER        │              │
       │    (Sentiment Analysis)      │              │
       └──────────────┬───────────────┘              │
                      ▼                               │
       ┌──────────────────────────────┐              │
       │    SIGNAL SERVER (Python)    │              │
       │    http://127.0.0.1:8787     │              │
       └──────────────┬───────────────┘              │
                      │ HTTP Polling                  │
                      ▼                               ▼
       ┌──────────────────────────────────────────────┐
       │         NINJATRADER 8 STRATEGY               │
       │         (AutonomousFuturesBot.cs)            │
       └──────────────────────────────────────────────┘
                      │
                      ▼
              ┌───────────────┐
              │ Futures Market │
              └───────────────┘
```

## Quick Start

### 1. Prerequisites

- Python 3.9+
- NinjaTrader 8
- API Keys:
  - Google Gemini API (required)
  - Twitter API v2 (optional)
  - Reddit API (optional)
  - NewsAPI (optional)

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/mohit1157/tradovate.git
cd tradovate

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your API keys
```

### 3. Configure API Keys

Edit `.env` file with your API keys:

```bash
# Required
GEMINI_API_KEY=your_gemini_api_key

# Optional (for enhanced sentiment)
TWITTER_BEARER_TOKEN=your_twitter_bearer_token
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
NEWS_API_KEY=your_news_api_key
```

### 4. Run the Signal Server

```bash
python run_server.py
```

The server will start at `http://127.0.0.1:8787`

### 5. Install NinjaTrader Strategy

1. Copy `src/Strategies/AutonomousFuturesBot.cs` to:
   ```
   Documents\NinjaTrader 8\bin\Custom\Strategies\
   ```

2. Open NinjaTrader 8
3. Go to Tools → NinjaScript Editor
4. Press F5 to compile

### 6. Apply Strategy to Chart

1. Open a chart (e.g., MNQ, ES)
2. Right-click → Strategies → AutonomousFuturesBot
3. Configure settings:
   - Enable "Use External Signals" for AI-powered trading
   - Set your risk parameters
   - Start in **Sim mode** first!

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/signal?symbol=MNQ` | GET | Get trading signal for symbol |
| `/health` | GET | Service health check |
| `/metrics` | GET | Performance metrics |
| `/kill?reason=xxx` | POST | Activate kill switch |
| `/resume` | POST | Resume trading |
| `/record-trade?pnl=xxx` | POST | Record trade P&L |

### Signal Response Format

```json
{
    "action": "BUY",
    "qty": 1,
    "confidence": 0.75
}
```

## Configuration

### Trading Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `CONFIDENCE_THRESHOLD` | 0.55 | Minimum confidence to execute trade |
| `MAX_DAILY_LOSS` | 500.0 | Daily loss limit in dollars |
| `MAX_TRADES_PER_DAY` | 10 | Maximum trades per day |
| `COOLDOWN_SECONDS` | 30 | Seconds between trades |

### Sentiment Weights

| Source | Default Weight | Description |
|--------|---------------|-------------|
| Twitter | 0.3 | Weight for Twitter sentiment |
| Reddit | 0.3 | Weight for Reddit sentiment |
| News | 0.4 | Weight for news sentiment |

## Project Structure

```
tradovate/
├── config/
│   └── settings.py          # Configuration management
├── src/
│   ├── collectors/          # Data collection
│   │   ├── twitter_collector.py
│   │   ├── reddit_collector.py
│   │   └── news_collector.py
│   ├── sentiment/           # Sentiment analysis
│   │   ├── gemini_analyzer.py
│   │   ├── text_processor.py
│   │   └── aggregator.py
│   ├── decision/            # Signal generation
│   │   ├── signal_generator.py
│   │   └── risk_calculator.py
│   ├── server/              # HTTP API server
│   │   └── signal_server.py
│   ├── database/            # Trade journaling
│   │   └── repository.py
│   └── Strategies/          # NinjaTrader strategy
│       └── AutonomousFuturesBot.cs
├── docs/
│   ├── ARCHITECTURE.md      # System architecture
│   └── EXTERNAL_SIGNALS.md  # Signal integration guide
├── .env.example             # Environment template
├── requirements.txt         # Python dependencies
├── run_server.py           # Server entry point
└── README.md
```

## Safety Features

1. **Kill Switch**: Automatically stops trading when daily loss limit is reached
2. **Service Health Check**: Falls back to technical signals if AI service is down
3. **Confidence Threshold**: Only executes trades above minimum confidence
4. **Position Limits**: Maximum contracts per trade and per day
5. **Session Close**: Automatically exits positions before session close

## NinjaTrader Strategy Parameters

### Mode Configuration
| Parameter | Default | Description |
|-----------|---------|-------------|
| Use External Signals | false | Enable AI-powered sentiment signals |
| External Signal URL | http://127.0.0.1:8787/signal?symbol={SYMBOL} | Signal server URL |
| Minimum Confidence | 0.55 | Minimum confidence to execute |

### Technical Strategy
| Parameter | Default | Description |
|-----------|---------|-------------|
| Fast EMA Period | 9 | Fast EMA period |
| Slow EMA Period | 21 | Slow EMA period |
| ATR Period | 14 | ATR calculation period |

### Risk Management
| Parameter | Default | Description |
|-----------|---------|-------------|
| Stop Loss (ATR x) | 1.5 | Stop loss ATR multiplier |
| Profit Target (ATR x) | 2.0 | Profit target ATR multiplier |
| Max Contracts | 1 | Maximum contracts per trade |
| Cooldown (seconds) | 30 | Seconds between trades |

### Advanced Risk
| Parameter | Default | Description |
|-----------|---------|-------------|
| Enable Daily Loss Limit | true | Enable daily loss protection |
| Max Daily Loss ($) | 500 | Stop trading at this loss |
| Max Trades Per Day | 10 | Maximum daily trades |
| Enable Trailing Stop | false | Use trailing stop instead |

## Development

### Running Tests

```bash
pytest tests/
```

### Code Structure

- **Collectors**: Gather data from external sources (Twitter, Reddit, News)
- **Sentiment**: Process and analyze text using Gemini AI
- **Decision**: Generate trading signals with risk management
- **Server**: FastAPI server exposing signals via HTTP

## Disclaimer

**IMPORTANT**: This software is for educational purposes only.

- **Paper trade first**: Always test in simulation before using real money
- **No guarantees**: Past performance does not guarantee future results
- **Risk of loss**: Trading futures involves substantial risk of loss
- **Your responsibility**: You are solely responsible for your trading decisions

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please read our contributing guidelines before submitting PRs.

## Support

- Issues: [GitHub Issues](https://github.com/mohit1157/tradovate/issues)
- Documentation: See `/docs` folder

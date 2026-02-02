# Autonomous Futures Trading Bot

An AI-powered autonomous futures trading bot that connects directly to **Tradovate** for execution, with sentiment analysis from social media (Twitter/X, Reddit) and financial news, using Google Gemini for intelligent decision making.

**Works on Mac, Linux, and Windows** - No NinjaTrader required!

## Features

### Market Data & Execution (Tradovate)
- **Real-time Market Data**: Live quotes, DOM, and tick data via WebSocket
- **Direct Order Execution**: Place market, limit, stop, and bracket orders
- **Position Management**: Track positions and P&L in real-time
- **Cross-Platform**: Runs on Mac, Linux, Windows - no Windows-only software needed

### Technical Analysis
- **EMA Crossover Strategy**: Fast/slow EMA with configurable periods
- **ATR-based Risk Management**: Dynamic stops and targets based on volatility
- **Real-time Indicator Calculation**: Updates with every new bar

### Sentiment Analysis
- **Twitter/X Integration**: Real-time sentiment from financial Twitter
- **Reddit Integration**: Monitors r/wallstreetbets, r/futures, r/stocks
- **News Integration**: Aggregates from NewsAPI, Alpha Vantage
- **Gemini AI**: Advanced sentiment analysis and decision making

### Risk Management
- **Daily Loss Limits**: Automatic kill switch when limit reached
- **Trade Limits**: Maximum trades per day
- **Position Sizing**: Confidence-based sizing
- **Cooldown Period**: Prevents overtrading

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    SENTIMENT SOURCES                         │
├──────────────┬──────────────┬───────────────────────────────┤
│   Twitter    │    Reddit    │    News APIs                   │
└──────┬───────┴──────┬───────┴──────┬────────────────────────┘
       └──────────────┼──────────────┘
                      ▼
       ┌──────────────────────────────┐
       │       GEMINI AI ANALYZER     │
       │     (Sentiment Analysis)     │
       └──────────────┬───────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              PYTHON TRADING BOT (runs on any OS)            │
├─────────────────────────────────────────────────────────────┤
│  • Live market data via WebSocket                           │
│  • Technical indicators (EMA, ATR)                          │
│  • Combines sentiment + technical signals                   │
│  • Risk management & position sizing                        │
│  • Order execution via REST API                             │
└─────────────────────────────────────────────────────────────┘
                      │
                      ▼ (WebSocket + REST API)
              ┌───────────────┐
              │   TRADOVATE   │
              │   (Sim/Live)  │
              └───────────────┘
                      │
                      ▼
              ┌───────────────┐
              │ Futures Market│
              │ (CME, etc.)   │
              └───────────────┘
```

## Quick Start

### 1. Prerequisites

- **Python 3.9+**
- **Tradovate Account** (free demo available at [trader.tradovate.com](https://trader.tradovate.com))
- **API Keys**:
  - Gemini API (required for sentiment) - free at [makersuite.google.com](https://makersuite.google.com/app/apikey)
  - Twitter, Reddit, News APIs (optional)

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/mohit1157/tradovate.git
cd tradovate

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
```

### 3. Configure Credentials

Edit `.env` file:

```bash
# REQUIRED: Tradovate credentials
TRADOVATE_USERNAME=your_username
TRADOVATE_PASSWORD=your_password

# REQUIRED for sentiment: Gemini API
GEMINI_API_KEY=your_gemini_api_key

# OPTIONAL: Social media APIs for enhanced sentiment
TWITTER_BEARER_TOKEN=your_twitter_token
REDDIT_CLIENT_ID=your_reddit_id
REDDIT_CLIENT_SECRET=your_reddit_secret
NEWS_API_KEY=your_news_api_key
```

### 4. Run the Bot

```bash
# Run with default settings (demo mode, MNQH5)
python run_bot.py

# Or with custom options
python run_bot.py --symbol MESH5 --max-contracts 2

# Technical only mode (no sentiment)
python run_bot.py --no-sentiment

# LIVE TRADING (use with caution!)
python run_bot.py --live
```

## Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--symbol` | MNQH5 | Trading symbol |
| `--demo` | true | Use demo environment |
| `--live` | false | Use live environment (real money!) |
| `--no-sentiment` | false | Disable sentiment, use technicals only |
| `--max-contracts` | 1 | Maximum contracts per trade |
| `--max-daily-loss` | 500 | Daily loss limit |

## Configuration

### Trading Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_CONTRACTS` | 1 | Maximum contracts per trade |
| `MAX_DAILY_LOSS` | 500.0 | Kill switch threshold |
| `MAX_TRADES_PER_DAY` | 10 | Trade count limit |
| `COOLDOWN_SECONDS` | 30 | Minimum time between trades |
| `CONFIDENCE_THRESHOLD` | 0.55 | Minimum signal confidence |

### Technical Indicators

| Parameter | Default | Description |
|-----------|---------|-------------|
| `FAST_EMA` | 9 | Fast EMA period |
| `SLOW_EMA` | 21 | Slow EMA period |
| `ATR_PERIOD` | 14 | ATR calculation period |
| `STOP_ATR_MULT` | 1.5 | Stop loss = ATR × this |
| `TARGET_ATR_MULT` | 2.0 | Take profit = ATR × this |

### Sentiment Weights

| Source | Weight | Description |
|--------|--------|-------------|
| Twitter | 0.3 | Social media sentiment |
| Reddit | 0.3 | Community sentiment |
| News | 0.4 | Professional news |

## Project Structure

```
tradovate/
├── config/
│   └── settings.py           # Configuration
├── src/
│   ├── tradovate/            # Tradovate API integration
│   │   ├── client.py         # REST API client
│   │   ├── websocket_client.py  # WebSocket for live data
│   │   ├── market_data.py    # Market data handler
│   │   └── order_manager.py  # Order & position management
│   ├── indicators/
│   │   └── indicators.py     # EMA, ATR calculations
│   ├── collectors/           # Social media/news collection
│   ├── sentiment/            # Gemini AI analysis
│   ├── decision/             # Signal generation
│   ├── bot/
│   │   └── trading_bot.py    # Main trading bot
│   └── server/               # Optional HTTP signal server
├── .env.example              # Environment template
├── requirements.txt          # Python dependencies
├── run_bot.py               # Main entry point
└── README.md
```

## Safety Features

1. **Demo Mode Default**: Starts in simulation by default
2. **Kill Switch**: Auto-stops when daily loss limit reached
3. **Trade Limits**: Prevents overtrading
4. **Confidence Threshold**: Only trades on high-confidence signals
5. **Position Limits**: Maximum contracts enforced
6. **Live Mode Confirmation**: Requires typing "YES" to confirm

## Tradovate Symbol Format

Futures symbols in Tradovate follow this format: `{ROOT}{MONTH}{YEAR}`

| Month | Code |
|-------|------|
| January | F |
| February | G |
| March | H |
| April | J |
| May | K |
| June | M |
| July | N |
| August | Q |
| September | U |
| October | V |
| November | X |
| December | Z |

**Examples:**
- `MNQH5` = Micro Nasdaq March 2025
- `MESH5` = Micro S&P March 2025
- `ESZ4` = E-mini S&P December 2024

## Development

### Running Tests

```bash
pytest tests/
```

### Project Components

- **Tradovate Client**: REST API for authentication, orders, account data
- **WebSocket Client**: Real-time quotes, DOM, charts, order updates
- **Market Data Handler**: Stores and processes live data
- **Technical Indicators**: EMA, ATR calculations
- **Sentiment Analysis**: Twitter, Reddit, News → Gemini AI
- **Signal Generator**: Combines all signals into trading decisions
- **Risk Calculator**: Position sizing, daily limits

## Disclaimer

**IMPORTANT**: This software is for educational purposes only.

- **Always start with demo/sim trading**
- **No guarantees of profit** - trading futures involves substantial risk
- **You are responsible** for your own trading decisions
- **Past performance** does not guarantee future results

## API Keys Guide

### Tradovate (Required)
1. Go to [trader.tradovate.com](https://trader.tradovate.com)
2. Create a free demo account
3. Use your login credentials in `.env`

### Gemini AI (Required for sentiment)
1. Go to [makersuite.google.com](https://makersuite.google.com/app/apikey)
2. Create a free API key
3. Add to `.env` as `GEMINI_API_KEY`

### Twitter (Optional)
1. Go to [developer.twitter.com](https://developer.twitter.com)
2. Create a project and get Bearer Token
3. Add to `.env` as `TWITTER_BEARER_TOKEN`

### Reddit (Optional)
1. Go to [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Create a "script" application
3. Add client ID and secret to `.env`

### NewsAPI (Optional)
1. Go to [newsapi.org](https://newsapi.org)
2. Get a free API key
3. Add to `.env` as `NEWS_API_KEY`

## License

MIT License - See LICENSE file for details

## Support

- Issues: [GitHub Issues](https://github.com/mohit1157/tradovate/issues)
- Documentation: See `/docs` folder

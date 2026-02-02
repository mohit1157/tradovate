# Autonomous Futures Trading Bot - System Architecture

## Overview

This system is a hybrid autonomous futures trading bot that combines:
1. **Technical Analysis** - EMA crossovers, ATR-based risk management
2. **Sentiment Analysis** - Social media (Twitter/X, Reddit) and news sentiment
3. **AI Decision Layer** - Google Gemini for intelligent signal generation
4. **Execution Layer** - NinjaTrader 8 for order execution

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA COLLECTION LAYER                              │
├─────────────────┬─────────────────┬─────────────────┬───────────────────────┤
│   Twitter/X     │     Reddit      │   News APIs     │   Market Data         │
│   Collector     │    Collector    │   Collector     │   (via NinjaTrader)   │
└────────┬────────┴────────┬────────┴────────┬────────┴───────────┬───────────┘
         │                 │                 │                     │
         └─────────────────┼─────────────────┘                     │
                           │                                       │
                           ▼                                       │
┌─────────────────────────────────────────────────────────────────┐│
│                    SENTIMENT ANALYSIS LAYER                      ││
├─────────────────────────────────────────────────────────────────┤│
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ││
│  │ Text Processor  │  │ Gemini AI       │  │ Sentiment       │  ││
│  │ & Cleaner       │──│ Sentiment       │──│ Aggregator      │  ││
│  │                 │  │ Analyzer        │  │                 │  ││
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  ││
└──────────────────────────────┬──────────────────────────────────┘│
                               │                                   │
                               ▼                                   │
┌─────────────────────────────────────────────────────────────────┐│
│                      DECISION ENGINE                             ││
├─────────────────────────────────────────────────────────────────┤│
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ││
│  │ Sentiment       │  │ Market Regime   │  │ Risk            │  ││
│  │ Signals         │──│ Detector        │──│ Calculator      │  ││
│  │                 │  │                 │  │                 │  ││
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  ││
│                              │                                   ││
│                              ▼                                   ││
│                    ┌─────────────────┐                          ││
│                    │ Signal          │                          ││
│                    │ Generator       │◄─────────────────────────┘│
│                    │                 │    Technical Signals      │
│                    └────────┬────────┘                          │
└─────────────────────────────┼───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SIGNAL SERVER (HTTP API)                    │
├─────────────────────────────────────────────────────────────────┤
│  • REST API endpoint: GET /signal?symbol={SYMBOL}               │
│  • Health endpoint: GET /health                                  │
│  • Metrics endpoint: GET /metrics                                │
│  • WebSocket for real-time updates (optional)                   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               │ HTTP Polling (2s intervals)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    NINJATRADER EXECUTION LAYER                   │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Signal          │  │ Position        │  │ Order           │  │
│  │ Processor       │──│ Manager         │──│ Executor        │  │
│  │                 │  │                 │  │                 │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                  │
│  • EMA Crossover (fallback)                                     │
│  • ATR-based stops/targets                                      │
│  • Risk controls (max contracts, cooldown, daily loss limit)    │
│  • Kill switch capability                                       │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                    ┌─────────────────┐
                    │ Futures Market  │
                    │ (Sim/Live)      │
                    └─────────────────┘
```

## Component Details

### 1. Data Collection Layer

#### Twitter/X Collector (`src/collectors/twitter_collector.py`)
- Uses Twitter API v2 for real-time and historical tweets
- Searches for futures-related keywords and cashtags ($ES, $NQ, $MNQ, etc.)
- Filters by influential accounts and engagement metrics
- Rate limiting and retry logic built-in

#### Reddit Collector (`src/collectors/reddit_collector.py`)
- Monitors subreddits: r/wallstreetbets, r/futures, r/stocks, r/trading
- Tracks posts and comments mentioning target instruments
- Weighs by upvotes, awards, and comment sentiment
- Uses PRAW (Python Reddit API Wrapper)

#### News Collector (`src/collectors/news_collector.py`)
- Integrates with multiple news APIs:
  - NewsAPI.org for general financial news
  - Alpha Vantage News Sentiment
  - Finnhub News API
- Filters for market-moving events
- Categorizes by relevance score

### 2. Sentiment Analysis Layer

#### Text Processor (`src/sentiment/text_processor.py`)
- Cleans and normalizes text (removes URLs, handles emojis, etc.)
- Extracts financial entities (tickers, prices, percentages)
- Handles financial slang and abbreviations

#### Gemini Sentiment Analyzer (`src/sentiment/gemini_analyzer.py`)
- Uses Google Gemini Pro for advanced sentiment analysis
- Custom prompts for financial context
- Outputs:
  - Sentiment score (-1.0 to +1.0)
  - Confidence level (0.0 to 1.0)
  - Key themes/topics
  - Urgency indicator

#### Sentiment Aggregator (`src/sentiment/aggregator.py`)
- Combines sentiment from multiple sources
- Applies time-decay weighting (recent data weighted higher)
- Source reliability weighting
- Outputs composite sentiment score

### 3. Decision Engine

#### Market Regime Detector (`src/decision/regime_detector.py`)
- Identifies market conditions: trending, ranging, volatile
- Uses volatility metrics (ATR, VIX proxy)
- Adjusts strategy parameters based on regime

#### Risk Calculator (`src/decision/risk_calculator.py`)
- Position sizing based on account risk
- Maximum daily loss tracking
- Correlation-adjusted exposure

#### Signal Generator (`src/decision/signal_generator.py`)
- Combines sentiment + technical + regime signals
- Applies confidence thresholds
- Generates final BUY/SELL/HOLD decision
- Uses Gemini for final decision validation

### 4. Signal Server

#### Enhanced Signal Server (`src/server/signal_server.py`)
- Production-ready HTTP server (FastAPI/Flask)
- Endpoints:
  - `GET /signal?symbol={SYMBOL}` - Trading signal
  - `GET /health` - Health check
  - `GET /metrics` - Performance metrics
  - `POST /kill` - Emergency stop
- Caching layer for performance
- Request logging and monitoring

### 5. NinjaTrader Execution Layer

#### Enhanced Strategy (`src/Strategies/AutonomousFuturesBot.cs`)
- All existing functionality plus:
  - Daily loss limit (kill switch)
  - Maximum trades per day
  - Trailing stop option
  - Position size optimization
  - Connection recovery logic

## Data Flow

```
1. Data Collection (continuous, parallel)
   ├── Twitter: Every 30 seconds
   ├── Reddit: Every 60 seconds
   └── News: Every 5 minutes

2. Sentiment Processing (on new data)
   ├── Clean and normalize text
   ├── Send to Gemini for analysis
   └── Store in sentiment cache

3. Signal Generation (every 2 seconds)
   ├── Aggregate recent sentiment (5-min window)
   ├── Detect market regime
   ├── Calculate risk parameters
   ├── Generate signal with confidence
   └── Cache result

4. Signal Delivery (on request)
   └── NinjaTrader polls /signal endpoint

5. Trade Execution (in NinjaTrader)
   ├── Validate signal confidence
   ├── Check risk limits
   ├── Execute order
   └── Set brackets (stop/target)
```

## Configuration

All configuration via environment variables or `config/settings.yaml`:

```yaml
# API Keys
twitter_api_key: ${TWITTER_API_KEY}
twitter_api_secret: ${TWITTER_API_SECRET}
reddit_client_id: ${REDDIT_CLIENT_ID}
reddit_client_secret: ${REDDIT_CLIENT_SECRET}
news_api_key: ${NEWS_API_KEY}
gemini_api_key: ${GEMINI_API_KEY}

# Trading Parameters
symbols:
  - MNQ
  - MES
  - ES
  - NQ

confidence_threshold: 0.55
max_daily_loss: 500.0
max_trades_per_day: 10
cooldown_seconds: 30

# Sentiment Weights
sentiment_weights:
  twitter: 0.3
  reddit: 0.3
  news: 0.4

# Server
server_host: 127.0.0.1
server_port: 8787
```

## Database Schema

SQLite database for trade journal and sentiment history:

```sql
-- Trades table
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    symbol TEXT,
    action TEXT,
    quantity INTEGER,
    entry_price REAL,
    exit_price REAL,
    pnl REAL,
    sentiment_score REAL,
    confidence REAL,
    regime TEXT
);

-- Sentiment history
CREATE TABLE sentiment_history (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    symbol TEXT,
    source TEXT,
    raw_text TEXT,
    sentiment_score REAL,
    confidence REAL,
    themes TEXT
);

-- Daily performance
CREATE TABLE daily_performance (
    date DATE PRIMARY KEY,
    total_trades INTEGER,
    winning_trades INTEGER,
    total_pnl REAL,
    max_drawdown REAL
);
```

## Deployment

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your API keys

# Run signal server
python -m src.server.signal_server

# In NinjaTrader: Apply AutonomousFuturesBot to chart
```

### Production
- Use systemd/supervisor for process management
- Enable SSL/TLS for signal server
- Set up monitoring (Prometheus/Grafana)
- Configure alerts (email, Slack, Discord)

## Security Considerations

1. **API Keys**: Never commit to git, use environment variables
2. **Signal Server**: Run on localhost only, or use authentication
3. **Rate Limiting**: Respect API rate limits to avoid bans
4. **Kill Switch**: Always have manual override capability
5. **Paper Trading**: Test thoroughly in simulation before live

## Future Enhancements

- [ ] Multi-symbol portfolio management
- [ ] Advanced ML models for prediction
- [ ] Options sentiment integration
- [ ] Order flow analysis
- [ ] Backtesting framework
- [ ] Mobile app for monitoring
- [ ] Discord/Telegram bot integration

"""Central configuration - one program, three markets: crypto | pse | global."""

PORT = 8950

MARKETS = ["crypto", "pse", "global"]
CURRENCY = {"crypto": "$", "pse": "₱", "global": "$"}
MARKET_LABELS = {"crypto": "Crypto", "pse": "PSE Stocks", "global": "Global Stocks"}

# ----------------------------------------------------------------- watchlists
# Crypto: seeds the watchlist on first run; editable in the app.
CRYPTO_WATCHLIST = [
    ("bitcoin", "BTC", "Bitcoin"),
    ("ethereum", "ETH", "Ethereum"),
    ("binancecoin", "BNB", "BNB"),
    ("solana", "SOL", "Solana"),
    ("ripple", "XRP", "XRP"),
    ("cardano", "ADA", "Cardano"),
    ("dogecoin", "DOGE", "Dogecoin"),
    ("tron", "TRX", "TRON"),
    ("avalanche-2", "AVAX", "Avalanche"),
    ("chainlink", "LINK", "Chainlink"),
    ("polkadot", "DOT", "Polkadot"),
    ("litecoin", "LTC", "Litecoin"),
    ("stellar", "XLM", "Stellar"),
    ("bitcoin-cash", "BCH", "Bitcoin Cash"),
    ("uniswap", "UNI", "Uniswap"),
    ("hyperliquid", "HYPE", "Hyperliquid"),
    ("sui", "SUI", "Sui"),
    ("near", "NEAR", "NEAR Protocol"),
    ("aave", "AAVE", "Aave"),
    ("hedera-hashgraph", "HBAR", "Hedera"),
]

# PSE: the watchlist is ALL listed companies, synced automatically from the
# PSE Edge company directory - nothing to configure here.

# Global: starter list of liquid US names + broad ETFs; editable in the app.
GLOBAL_WATCHLIST = [
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("NVDA", "NVIDIA"),
    ("GOOGL", "Alphabet"),
    ("AMZN", "Amazon"),
    ("META", "Meta Platforms"),
    ("TSLA", "Tesla"),
    ("AVGO", "Broadcom"),
    ("JPM", "JPMorgan Chase"),
    ("V", "Visa"),
    ("MA", "Mastercard"),
    ("COST", "Costco"),
    ("XOM", "Exxon Mobil"),
    ("JNJ", "Johnson & Johnson"),
    ("SCHD", "Schwab US Dividend ETF"),
    ("VOO", "Vanguard S&P 500 ETF"),
    ("QQQ", "Invesco Nasdaq-100 ETF"),
    ("VTI", "Vanguard Total Market ETF"),
]

# ----------------------------------------------------------------- news feeds
NEWS_FEEDS = {
    "crypto": [
        ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
        ("Cointelegraph", "https://cointelegraph.com/rss"),
        ("Decrypt", "https://decrypt.co/feed"),
        ("The Block", "https://www.theblock.co/rss.xml"),
        ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/"),
        ("CryptoSlate", "https://cryptoslate.com/feed/"),
    ],
    "pse": [
        ("BusinessWorld", "https://www.bworldonline.com/feed/"),
        ("Inquirer Business", "https://business.inquirer.net/feed"),
        ("Philstar Business", "https://www.philstar.com/rss/business"),
        ("GMA Money", "https://data.gmanetwork.com/gno/rss/money/feed.xml"),
    ],
    "global": [
        ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
        ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("Investing.com", "https://www.investing.com/rss/news_25.rss"),
    ],
}

# ------------------------------------------------------------------ intervals
# (seconds) - tuned to stay well within each free data source's limits
INTERVALS = {
    # crypto quotes now also feed price history (via the sparkline in the same
    # call), so they're the main CoinGecko cost. Budget: the whole key is the
    # website's now (local app deleted 2026-07-08), so spend ~8.3k of the
    # 10k/month Demo quota: 206+48+24 = ~278 calls/day, margin for searches.
    # EMERGENCY MODE (2026-07-12): Neon transfer meter at 4.95/5 GB - signal
    # sweeps throttled hard to stretch the last ~50 MB until the Supabase
    # migration lands. Revert signals to 900/3600/3600 in the cutover deploy.
    "crypto": {"quotes": 420, "top100": 1800, "global": 3600,
               "history": 600, "news": 900, "signals": 3600},
    "pse":    {"quotes": 300, "directory": 7 * 86400, "fundamentals": 25,
               "dividends": 6 * 3600, "news": 900, "signals": 14400},
    "global": {"quotes": 300, "history": 60, "metrics": 120,
               "indices": 600, "news": 900, "signals": 14400},
}

# Signal sweeps read a bounded history window instead of each asset's full
# stored history (Neon egress protection). Windows are sized so every
# indicator keeps its exact pre-window basis: the long SMA uses up to 168
# closes, so the window must hold >=168 closes for the densest asset -
# crypto is hourly 24/7 (8d > 168h ✓); global has ~7 trading-hour bars/day
# (35d ≈ 168+ bars ✓); PSE thin names record ~1 close/day, so 90d = the
# full retention period, i.e. byte-identical to the pre-window behavior.
SIGNAL_WINDOW_DAYS = {"crypto": 8, "pse": 90, "global": 35}

HISTORY_REFRESH_MINUTES = {"crypto": 45, "global": 120}
HISTORY_DAYS = 30            # hourly history fetched per request (crypto)
HISTORY_KEEP_DAYS = 90
FUNDAMENTALS_REFRESH_DAYS = 3   # PSE Edge per-company refresh cadence
METRICS_REFRESH_HOURS = 12      # Finnhub fundamentals refresh cadence

# Advisor: cap the number of not-owned "idea" cards for huge universes
ADVISOR_MAX_IDEAS = {"crypto": None, "pse": 15, "global": 12}

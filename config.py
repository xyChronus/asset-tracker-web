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
    "crypto": {"quotes": 420, "top100": 1800, "global": 3600,
               "history": 600, "news": 900, "signals": 900},
    "pse":    {"quotes": 300, "directory": 7 * 86400, "fundamentals": 25,
               "dividends": 6 * 3600, "news": 900, "signals": 3600},
    "global": {"quotes": 300, "history": 60, "metrics": 120,
               "indices": 600, "news": 900, "signals": 3600},
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

# PSE symbols excluded from the whole system (watchlist, signals, charts,
# predictions): suspended or trade-dead names that only add noise. Criterion
# (checked 2026-08-13 against ~10y of stored closes): no price change for
# 180+ days, or no recorded trade at all. The directory sync skips these and
# removes any existing rows, so a re-sync can't resurrect them.
# To REINSTATE one: remove it here; the next directory sync re-adds it, and
# deleting its entry from the kv key histfill:pse re-fetches deep history.
PSE_EXCLUDED = {
    "AAA",    # Asia Amalgamated - no trades in stored history (~10y suspended)
    "AR",     # Abra Mining - suspended, last trade 2021-03
    "BH",     # BHI Holdings - last trade 2023-04
    "BMM",    # Bogo-Medellin Milling - last trade 2022-12
    "COAL",   # Coal Asia - frozen since 2025-12
    "CYBR",   # Cyber Bay - last trade 2021-06
    "EG",     # IP E-Game Ventures - last trade 2017-05
    "I",      # I-Remit - frozen since 2025-05
    "MJC",    # Manila Jockey Club - suspended, last trade 2023-05
    "MJIC",   # MJC Investments - suspended, last trade 2023-05
    "PNX",    # Phoenix Petroleum - suspended, last trade 2024-05
    "ROX",    # Roxas Holdings - last trade 2024-05
    "TUBIG",  # Tubig Pilipinas - frozen since 2025-12
    "MGH", "NXGEN", "PNC", "PORT", "PTT",   # no trades in stored history
}

# Exchange trading holidays: date -> holiday name, per market. The advisor
# and the schedulers treat these exactly like weekends.
# MAINTENANCE: extend each December for the coming year.
#  - "global" (NYSE/Nasdaq) publishes years ahead - 2026 and 2027 are final.
#  - "pse" follows Philippine proclamations, which can ADD special
#    non-working days mid-year (and Eid dates move with the lunar calendar);
#    update this list when Malacañang proclaims new ones.
MARKET_HOLIDAYS = {
    "pse": {
        "2026-01-01": "New Year's Day",
        "2026-02-17": "Chinese New Year",
        "2026-03-20": "Eid'l Fitr",              # proclaimed date
        "2026-04-02": "Maundy Thursday",
        "2026-04-03": "Good Friday",
        "2026-04-09": "Araw ng Kagitingan",
        "2026-05-01": "Labor Day",
        "2026-05-27": "Eid'l Adha",              # proclaimed date
        "2026-06-12": "Independence Day",
        "2026-08-21": "Ninoy Aquino Day",
        "2026-08-31": "National Heroes Day",
        "2026-11-02": "All Souls' Day",
        "2026-11-30": "Bonifacio Day",
        "2026-12-08": "Feast of the Immaculate Conception",
        "2026-12-24": "Christmas Eve",
        "2026-12-25": "Christmas Day",
        "2026-12-30": "Rizal Day",
        "2026-12-31": "New Year's Eve",
    },
    "global": {
        "2026-01-01": "New Year's Day",
        "2026-01-19": "Martin Luther King Jr. Day",
        "2026-02-16": "Washington's Birthday",
        "2026-04-03": "Good Friday",
        "2026-05-25": "Memorial Day",
        "2026-06-19": "Juneteenth",
        "2026-07-03": "Independence Day (observed)",
        "2026-09-07": "Labor Day",
        "2026-11-26": "Thanksgiving",
        "2026-12-25": "Christmas Day",
        "2027-01-01": "New Year's Day",
        "2027-01-18": "Martin Luther King Jr. Day",
        "2027-02-15": "Washington's Birthday",
        "2027-03-26": "Good Friday",
        "2027-05-31": "Memorial Day",
        "2027-06-18": "Juneteenth (observed)",
        "2027-07-05": "Independence Day (observed)",
        "2027-09-06": "Labor Day",
        "2027-11-25": "Thanksgiving",
        "2027-12-24": "Christmas Day (observed)",
    },
}

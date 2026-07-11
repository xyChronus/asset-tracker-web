# 📊 Asset Tracker — Changelog

All notable changes to the Asset Tracker (desktop app + website), oldest first.
Format loosely follows Keep a Changelog / semantic versioning.
Web-only items are marked **(web)**.

---

## [0.1.0] — 2026-07-03 — Initial build
### Added
- Local crypto tracker (Flask app at `127.0.0.1:8950`, launched by a `.bat`)
- Live prices (CoinGecko) + news from 6 crypto outlets
- Dashboard (value, cost basis, P/L, value chart, allocation pie, holdings, market situation, news)
- Portfolio (manual buy/sell logging, history, realized P/L) seeded from your Google Sheet
- Market (market cap, dominance, plain-English summary, top 100)
- Watchlist & Signals (20 coins; RSI / moving-average / MACD / momentum)
- Charts (hourly history) and News tabs

## [0.2.0] — 2026-07-03 — The Advisor
### Added
- Portfolio-aware recommendation engine: TRIM / SELL PART / TAKE PROFIT / BUY MORE / BUY / WATCH / HOLD, sized, with reasoning and the headlines behind each call
- "Today's Plan" strip on the dashboard
### Fixed
- 9 bugs caught by a multi-agent review (trim math, rounding vs position clamp, crash on missing price, news-wording misreads, a data race, an executable-link security hole, unwatched-held-coin coverage)

## [0.3.0] — 2026-07-03 — Three markets
### Added
- Market switcher: 🪙 Crypto · 🇵🇭 PSE · 🌎 Global — each with its own portfolio, advisor, watchlist, charts, news
- **PSE**: all 283 listed companies; EPS, P/E, dividends (only ones catchable by ex-date); phisix quotes + PSE Edge fundamentals
- **Global**: Finnhub + Yahoo data; 18-ticker starter list
### Changed
- Advisor generalized for stock fundamentals (P/E, dividend yield, 52-week position) and per-market currency
- Database migrated to a market-scoped structure (v1 backup kept)

## [0.4.0] — 2026-07-04 — Identity & docs
### Changed
- Renamed **Crypto Tracker → Investment Tracker → Asset Tracker** (folder, launcher, branding)
### Added
- Desktop shortcut + custom app icon
- Setup guide (`SETUP_GUIDE.md`) + uploaded to Google Drive as a formatted Doc

## [0.5.0] — 2026-07-05 — Usability & wallets
### Added
- **Wallet / budget per market** → automatic cash tracking, Total Wallet Worth + Cash Available cards; advisor sizes buys to your bankroll and caps them at available cash
- **"✓ Done"** on suggestions (dismiss for the day; auto-clears when you log a matching trade)
- **Searchable asset pickers** (type-to-find) on Portfolio and Charts; filter box on every watchlist
- **Bundled Python** in the share zip so friends install nothing
### Fixed
- Windows "fake Python" detection bug that blocked first-time setup

## [0.6.0] — 2026-07-06 — Depth & accuracy
### Added
- **Fear & Greed index** on the crypto dashboard and in the advisor briefing
- **Budget return %** on the wallet card
### Changed
- PSE price history **backfilled** (months of daily closes) so charts and signals weren't blank
- Real crypto transactions re-imported from your authoritative list; pseudo PSE portfolio (AEV/URC/JFC) added

## [1.0.0] — 2026-07-06 — 🚀 The website (multi-user)
### Added
- Public multi-user website at **asset-tracker-1bxg.onrender.com** (Render hosting + Neon cloud database) **(web)**
- **Invite-only accounts**; first account is the admin; each member's portfolio is fully private **(web)**
- Shared market data collection; per-user portfolios, budgets, watchlists, dismissals, advisories **(web)**
- Your existing data migrated in as the first account **(web)**

## [1.0.1] — 2026-07-06 — Launch fixes
### Fixed
- Free-tier boot overload that briefly made the site flicker **(web)**
- Missing crypto price history after a server sleep **(web)**
- 8-hour timezone shift on the portfolio chart (server now runs on Manila time) **(web)**

## [1.1.0] — 2026-07-07 — Live-site hardening
### Added
- **UptimeRobot keep-alive** so the free server never sleeps **(web)**
- **Members panel** for the admin — who joined + invite-code usage **(web)**
- **Change password** (self-service Account panel) **(web)**
- **Market-hours awareness** — buy/sell suggestions pause when an exchange is closed (PSE + US hours in Manila time; crypto 24/7) and show when they resume
- **Display-currency switch** — Auto / USD / PHP with a live exchange rate
- **Complete website user guide** — web page + Google Doc

## [1.2.0] — 2026-07-07 — Advice you can act on
### Added
- **Trading styles** — Scalper / Day / Swing / Long-Term; the advisor re-tunes how eager it is to buy, how fast it takes profit, and how much it weighs fundamentals
- **Numbered buy/sell score** shown on the watchlist, signal cards, and advisor cards
- **Accept button** on suggestions — logs the trade at the live price in one click
- **Editable transactions** — a ✎ button to correct a logged trade's price, date, quantity or amount
- **Estimate-discrepancy consent** — required checkbox at signup + a note on the login page **(web)**

## [1.2.1] — 2026-07-07 — Fix
### Fixed
- Long-Term trading style was too eager to BUY on thin fundamentals and overstated confidence (found by an adversarial code review). Fundamentals emphasis is now expressed by a per-style buy threshold; the default Swing style is unchanged.

## [1.3.0] — 2026-07-07 — Data resilience
### Added
- Wired in five data-provider API keys, giving every market a primary source **plus at least one automatic fallback**:
  - Finnhub → **real-time** US stock prices (primary for global)
  - CoinGecko demo key → faster crypto, fewer rate-limit stalls (primary for crypto)
  - Twelve Data + Alpha Vantage → backups for global stocks
  - CoinMarketCap → backup for crypto prices
- Global-stock quote chain: Finnhub → Yahoo → Twelve Data → Alpha Vantage
- Crypto price chain: CoinGecko → CoinMarketCap (keeps prices live during a CoinGecko outage)
### Notes
- TradingView was evaluated and declined (no free API; scraping breaks their terms — a legal risk for a monetizable site).

## [1.4.0] — 2026-07-07 — Transaction fees
### Added
- Optional **Fee** field on every buy/sell (in the market's currency). Buy fees fold into your cost basis; sell fees come off your proceeds; both reduce available cash — so profit/loss and cash reflect what you actually paid.
- Fee column in the transaction history; total fees paid tracked in the portfolio summary.

## [1.5.0] — 2026-07-07 — Hot & Cold
### Added
- **Hot & Cold movement flags** on the advisor: big moves get surfaced as awareness flags — up/down **8%+ in 24h**, **15%+ over the week**, or a held position down **15%+ from your average buy**.
- A new **Hot & Cold strip** at the top of the Advisor tab, matching flag chips on each card, and **Heads-up** lines on the dashboard's Today plan.
- Flags are raw-movement only and run **independent of the buy/sell call**, so a sharp drop registers even when the technical read looks oversold. They're awareness, not instructions — the final call is always yours.

## [1.8.1] — 2026-07-08 — Leaner on the crypto data API
### Changed
- Cut background CoinGecko usage by ~90% (from ~2–3k calls/day to under ~200) to stay well within the free-tier monthly limit. Crypto price history is now taken from data the price call already returns instead of a second per-coin call, and the refresh timers were relaxed (crypto prices update roughly every 10 minutes). Signals and charts are unaffected.

## [1.8.4] — 2026-07-11 — Database diet, reviewed
### Fixed
- An independent review of the database diet confirmed 8 subtle issues, all now fixed: the PSE/global history windows were widened so the long-term trend average keeps its exact original math (verified byte-identical for PSE), newly added global stocks get their signal right after backfill instead of waiting up to an hour, and several rare timing races in the new memory cache (a slow read overwriting a newer value; news updates being missed by the advisor for 15 minutes; failed database writes leaving memory out of sync) were closed.

## [1.8.3] — 2026-07-10 — Database diet
### Changed
- Cut the site's database traffic ~15-fold after a Neon transfer-quota alert (4.1 of 5 GB used). The signal engine now reads only the recent price window it actually uses (verified: identical signals) instead of every asset's full history every few minutes; frequently-read market snapshots are served from the app's memory instead of re-fetched from the database on every page refresh; and idle background jobs stop polling for work that's already done. More headroom as more friends join.

## [1.8.2] — 2026-07-10 — Faster crypto refresh
### Changed
- With the desktop app retired, the website has the whole CoinGecko allowance to itself — so crypto prices now refresh **every 7 minutes** (was 10) and the Top-100 market table **every 30 minutes** (was hourly). Uses ~8.3k of the 10k monthly quota, with margin to spare.

## [1.8.0] — 2026-07-08 — Signals on your holdings
### Added
- The Dashboard's **Holdings** table now has a **Signal** column — the same BUY / HOLD / WATCH / SELL read (with its numbered score) you already see on the Watchlist, now right beside each position you own. Sort by it to line up your strongest buy-signals or weakest holds at a glance.

## [1.7.1] — 2026-07-08 — Fear & Greed explainer
### Added
- A small **ⓘ info bubble** next to the crypto **Fear & Greed** score (Dashboard and Market tab). Hover it for a plain-language explanation: what the 0–100 score means, the Extreme Fear → Extreme Greed scale, and the contrarian read — with the reminder that it's one input among many, not a signal on its own.

## [1.7.0] — 2026-07-08 — Sortable tables
### Added
- **Click any column header to sort** — on the Dashboard's Holdings table and on every Watchlist tab (Crypto, PSE, Global). Click once for high→low, again to reverse; a ▲/▼ arrow marks the active column and blanks always sink to the bottom. Sort by value, price, day change, P/E, dividend yield, market cap, signal score — whatever you're comparing at the moment.

## [1.6.0] — 2026-07-07 — Sturdier Philippine-stock data
### Changed
- **Company figures for PSE stocks** (P/E, 52-week high/low, book value, earnings) now come from **Finnhub** first, replacing the fragile PSE Edge scrape that frequently left these fields blank. Edge stays on as an automatic fallback.
- **Price resilience:** if the free community price feed (phisix) goes down, your PSE **holdings** now keep pricing from Finnhub instead of going blank — so your portfolio value stays correct through an outage. Prices recover to the full market feed automatically when phisix is back.
### Notes
- Uses the free Finnhub key already in the app — no new cost. Sets the stage for an optional paid EODHD upgrade (bulk prices, history and dividends) later.

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

## [1.6.0] — 2026-07-07 — Sturdier Philippine-stock data
### Changed
- **Company figures for PSE stocks** (P/E, 52-week high/low, book value, earnings) now come from **Finnhub** first, replacing the fragile PSE Edge scrape that frequently left these fields blank. Edge stays on as an automatic fallback.
- **Price resilience:** if the free community price feed (phisix) goes down, your PSE **holdings** now keep pricing from Finnhub instead of going blank — so your portfolio value stays correct through an outage. Prices recover to the full market feed automatically when phisix is back.
### Notes
- Uses the free Finnhub key already in the app — no new cost. Sets the stage for an optional paid EODHD upgrade (bulk prices, history and dividends) later.

## [1.7.0] — 2026-07-08 — Sortable tables
### Added
- **Click any column header to sort** — on the Dashboard's Holdings table and on every Watchlist tab (Crypto, PSE, Global). Click once for high→low, again to reverse; a ▲/▼ arrow marks the active column and blanks always sink to the bottom. Sort by value, price, day change, P/E, dividend yield, market cap, signal score — whatever you're comparing at the moment.

## [1.7.1] — 2026-07-08 — Fear & Greed explainer
### Added
- A small **ⓘ info bubble** next to the crypto **Fear & Greed** score (Dashboard and Market tab). Hover it for a plain-language explanation: what the 0–100 score means, the Extreme Fear → Extreme Greed scale, and the contrarian read — with the reminder that it's one input among many, not a signal on its own.

## [1.8.0] — 2026-07-08 — Signals on your holdings
### Added
- The Dashboard's **Holdings** table now has a **Signal** column — the same BUY / HOLD / WATCH / SELL read (with its numbered score) you already see on the Watchlist, now right beside each position you own. Sort by it to line up your strongest buy-signals or weakest holds at a glance.

## [1.8.1] — 2026-07-08 — Leaner on the crypto data API
### Changed
- Cut background CoinGecko usage by ~90% (from ~2–3k calls/day to under ~200) to stay well within the free-tier monthly limit. Crypto price history is now taken from data the price call already returns instead of a second per-coin call, and the refresh timers were relaxed (crypto prices update roughly every 10 minutes). Signals and charts are unaffected.

## [1.8.2] — 2026-07-10 — Faster crypto refresh
### Changed
- With the desktop app retired, the website has the whole CoinGecko allowance to itself — so crypto prices now refresh **every 7 minutes** (was 10) and the Top-100 market table **every 30 minutes** (was hourly). Uses ~8.3k of the 10k monthly quota, with margin to spare.

## [1.8.3] — 2026-07-10 — Database diet
### Changed
- Cut the site's database traffic ~15-fold after a Neon transfer-quota alert (4.1 of 5 GB used). The signal engine now reads only the recent price window it actually uses (verified: identical signals) instead of every asset's full history every few minutes; frequently-read market snapshots are served from the app's memory instead of re-fetched from the database on every page refresh; and idle background jobs stop polling for work that's already done. More headroom as more friends join.

## [1.8.4] — 2026-07-11 — Database diet, reviewed
### Fixed
- An independent review of the database diet confirmed 8 subtle issues, all now fixed: the PSE/global history windows were widened so the long-term trend average keeps its exact original math (verified byte-identical for PSE), newly added global stocks get their signal right after backfill instead of waiting up to an hour, and several rare timing races in the new memory cache (a slow read overwriting a newer value; news updates being missed by the advisor for 15 minutes; failed database writes leaving memory out of sync) were closed.

## [1.9.0] — 2026-07-12 — New database home
### Changed
- Moved the database from Neon to **Supabase (Singapore)** — same city as the app server. A full quota audit showed Neon's free plan meters how many hours the database engine runs (100/month), which an always-on tracker burns through in ~16 days; Supabase's free instance is built to run 24/7 with no such meter. All data (every transaction, watchlist, wallet and setting — 76k rows) was copied and verified row-for-row before the switch. The temporary signal-refresh slowdown from the emergency throttle is reverted.

## [1.10.0] — 2026-07-20 — Trade like you mean it: TP/SL plans, notes & stats
### Added
- **🎯 Take-profit / 🛑 stop-loss plans** on every position: click **Plan** in the Dashboard's Holdings table to set your exit prices (with live risk-to-reward math as you type). When a level is crossed, the position lights up across the app — Hot & Cold strip, advisor cards, and a **"🎯 TARGET HIT / 🛑 STOP HIT"** line at the top of Today's Plan with a one-click **Log sell**. The tracker never trades for you — it tells you when *your own plan* says act, and the call stays yours.
- **📝 Position notes** — jot *why* you bought right on the plan. Future-you reviewing a trade will thank past-you.
- **📊 Your Trading Stats** on the Portfolio tab: win rate, average win vs loss, profit factor, best & worst trades, and total fees — honest feedback from your own record, whether you're paper trading or logging real trades.
- **Suggested TP/SL** *(user request)*: every advisor **BUY / BUY MORE** idea now shows a starting plan tuned to your trading style (e.g. Swing: 🎯 +25% / 🛑 −12.5%, always risk:reward 1:2), and the plan editor offers a one-click **Use suggested** — a starting point, not a rule.

## [1.10.1] — 2026-07-21 — TP/SL reviewed & hardened
### Fixed
- An independent 20-agent review of the TP/SL feature confirmed 16 issues, all fixed before launch. Highlights: plan-triggered **Log sell** now sells your exact position quantity (no rounding dust or overselling from stale numbers); stop/target hits **stay visible while the market is closed** and can be dismissed for the day ("letting it run" is a valid call); the advisor never says BUY MORE on a position whose own stop has tripped — your plan outranks its opinion; tiny-price coins display properly; malformed prices can't break the dashboard; backup encryption hardened; trading stats are honest about small sample sizes.
- Crypto price history now keeps recording **even when CoinGecko is unavailable** (fed from the backup price source) — so signals stay alive through an outage or an exhausted monthly quota.

## [1.10.2] — 2026-07-21 — Suggestions first
### Changed
- The Dashboard's **Plan** column now leads with the advisor's **suggested TP/SL** for every position (shown as dashed chips) — you see the AI's numbers without clicking anything. Click them to adopt the suggestion as your own plan (the editor comes pre-filled — just hit Save) or adjust first. Your saved plan replaces the suggestion in the column.

## [1.11.0] — 2026-07-23 — Suggestions that actually study the chart
### Changed
- Suggested TP/SL levels are now **deduced from each asset's own data** instead of flat percentages: the engine measures the asset's real day-to-day volatility (so Bitcoin gets tighter levels than a meme coin), scales it to your trading-style horizon, tucks the stop **below the nearest real support level**, and sets the target **just under the nearest resistance or 52-week high** — selling into strength, the way traders actually plan. Every suggestion explains its reasoning in plain words, e.g. *"Swing Trader horizon, sized to this asset's own volatility (typical day: ±2.3%); stop tucked below the nearest support level; target set just under the 52-week high."*
- Guardrails keep every suggestion sane for your style, the risk-to-reward is always shown honestly, and an explanation is never attached to a number it doesn't match (independently reviewed: 9 findings, all fixed; validated over 1,532 suggestions across every asset with zero failures).
- All of this analysis rides inside the signal engine's existing data pass — zero extra API calls or database load.

## [1.11.1] — 2026-07-25 — Sell All & a tidier changelog
### Added
- A **Sell all** button on every Dashboard holding — one click to log dumping the entire position at the current live price (with a confirmation first, exact quantity, no leftover dust). Any take-profit/stop-loss plan on the position retires automatically once it's closed.
### Fixed
- This changelog is back in strict oldest-first order, and the missing v1.9.0 "New database home" entry (the Supabase move) was restored — it had been accidentally merged into v1.10.0.

## [1.12.0] — 2026-07-26 — The advisor stops chasing (user feedback release)
### Changed
- **No more buying the top** *(user feedback)*: an asset already up big over the past month **and** sitting near its highs no longer gets a fresh BUY — it shows as WATCH with the honest reason ("buying now is chasing someone else's rally") and the calmer entry price it would rather wait for. Instead, the advisor now spots **pullbacks in strength**: a solid month-long uptrend resting at its recent average is exactly the entry the old engine skipped — now it's suggested, with "buying the dip in strength usually beats buying the breakout." Strong fundamentals can override the chase gate (growth, not froth), scalpers are exempt, and nothing changes for positions you already hold.
- **Earnings dates are now an input** *(leading indicator)*: no fresh buy suggestions within 3 days of a company's earnings report ("results can gap the price sharply either way — this guide would rather react to real numbers than guess them"), and any card with a report inside a week carries a 📅 flag. Covers all US stocks; PSE best-effort.
- **Deeper fundamentals** *(user feedback — "global markets subpar")*: profit growth, revenue growth, return on equity, debt load and price-to-book now vote on every stock — in plain words on the cards — including a new value-trap warning: a low P/E with shrinking profits is no longer called "cheap."
- **Market weather**: when the S&P 500 is below its 50-day trend, when most PSE names are below their own 1-month trend, or when crypto Fear & Greed hits an extreme, the advisor raises the bar for new buys and halves their size — and says so in the briefing. It only ever gets more careful, never more aggressive.

## [1.12.1] — 2026-07-26 — More indicators in the contest, and the full ballot on every card
### Added
- **🌱 Basing flag** *(user idea)*: an asset that fell hard (25%+ over the month) but has stopped falling — holding unusually steady near its lows — gets flagged: "sellers may be tiring; one to watch." When the recovery is actually settling (RSI off the floor, no bad news), it also earns a modest vote in the conviction contest. Calibrated against live data so it marks a handful of genuine candidates, not half the market.
- **⚡ Coiled-quiet flag** *(user idea, honest version)*: a normally-active name gone dead quiet for weeks is flagged as coiled — "big moves often follow quiet spells, **in either direction**." Deliberately direction-neutral and vote-less: the data says stagnation predicts a move, not which way.
- **Full reasoning on every card**: expand "Full reasoning — how this call was made" on any advisor card to see the complete ballot — 📈 Technicals with each vote, 📰 News with the headlines behind the score, 🏢 Fundamentals factor by factor, any special reads, every gate that intervened, and the conviction total. The indicators compete; the strongest side wins; now you can watch the count.

## [1.13.0] — 2026-07-27 — 🔮 The Predict tab
### Added
- A new **Predict** tab: pick any asset and see a **price projection** for 7/30/90 days — the classic "draw a line over the chart" technique done statistically (a best-fit trend over the price history), tilted slightly by today's news sentiment and technical signal, inside an **uncertainty cone** sized to that asset's own volatility. The bands honestly widen with time: they show where ~68% and ~90% of ordinary outcomes land — a range, never a promise.
- **What analysts say**: for US and PSE stocks, the panel shows real Wall-Street recommendation counts (Strong Buy / Buy / Hold / Sell) and whether the Street got more or less bullish versus last month.
- **Full method disclosure** on the tab itself: every projection explains its trend slope, its volatility cone, and its news/signal tilt in plain numbers — plus the reminder that sudden shocks are not predictable by anyone, including this tool.

## [1.13.1] — 2026-07-27 — Predicted Movers on the Dashboard
### Added
- The Dashboard now shows **Predicted Movers — 30 days**: the three assets projecting furthest **up** and furthest **down** by their own price-trend math, refreshed a few times a day. Click any row to jump to its full projection. Same honest framing as the Predictions tab: where things likely land *if recent behavior persists* — ranges, not promises.
### Changed
- The Predictions tab is now labeled simply **Predictions**.

## [1.13.2] — 2026-07-28 — Tighter profit targets across every style
### Changed
- Take-profit thresholds and suggested TP/SL levels lowered across all trading styles — they were running too high, especially for fast styles. New take-profit triggers: **Scalper ~+2%** (in and out quickly, small wins, follow the momentum), **Day ~+4%**, **Swing ~+15%**, **Long-Term ~+40%**. The suggested-plan ranges tightened to match (e.g. Scalper plans now target +1.6–6% instead of +3–12%), and the deduced per-asset suggestions stay volatility-aware inside the new bands. The advisor will bank profits noticeably earlier — closer to how each style actually trades.

## [1.13.3] — 2026-07-28 — Predictions convenience & swing at 10%
### Added
- The Predictions tab now shows **your current holdings as one-click chips** — tap any position you own to see its projection instantly, no typing.
### Changed
- **Swing Trader** take-profit moved from ~15% to **~10%** — 10% swings are the decision-makers now, with suggested plans re-centered to match (targets +6–20%, stops −3–10%).
- The Dashboard's **Predicted Movers** panel expanded from 3 to **10 per side** — a fuller picture of where the market's trends are pointing.

## [1.14.0] — 2026-07-31 — Forecasts on the Advisor
### Added
- Every Advisor card now carries a **Trend projection line — where the price points in 7, 15 and 30 days** if its recent trend simply continues, with the projected prices spelled out (anchored at the card's live price). Click it to jump straight to the full Predictions chart — which adds the uncertainty cone and a small news tilt on top of the same trend fit.
### Notes
- The projection is context, not a vote: it's drawn from the same price history the technicals already score, so it deliberately does **not** move the conviction number — and the advisor's call can point the other way, since it weighs shorter-term signals. Point estimates, not a promise; the final call stays yours.
### Fixed
- A 12-finding adversarial review pass (this feature + the previously unreviewed predictions engine): Predictions charts now read ~24× less data per draw; junk URL parameters return a clean error instead of a crash; a failed projection no longer leaves the previous asset's chart on screen; jumping to Predictions for an asset you hold but don't watch now labels the picker correctly; stock 30-day horizons unified at 21 trading days everywhere.

## [1.15.0] — 2026-07-31 — Profit measured against the whole pot
### Added
- **Wallet-level take-profit**: alongside each style's per-position target, the advisor now watches what a position's gain does to your **whole wallet**. A big position (up to the concentration cap) gets its take-profit call as soon as its gain alone has moved the whole pot by the style's threshold (Scalper 0.6% · Day 1.1% · Swing 2.4% · Long-Term 7.5%) — momentum-cooling still required, and the card says exactly which target fired. Small positions still need their full per-position target.
- Every sell-side card now shows what the sale actually **banks as a % of your whole wallet** — the number that compounds across many small trades.
- **Rotation ideas for Scalper and Day styles**: each take-profit card points the freed cash at up to two current buy-side ideas from the same analysis, so small banked wins go straight back to work. Ideas you've marked done-today are never suggested.
### Fixed
- A 15-finding adversarial review of this feature **plus the v1.12.1 basing/coiled + reasoning-ledger release** (previously unreviewed): single-position portfolios can no longer trigger take-profit far below the advertised target; the Long-Term wallet threshold was mathematically unreachable (now 7.5%); all wording says "portfolio" instead of "wallet" when no budget is set; a too-small-to-sell demotion now retracts the sale argument and is recorded in the Gates ledger (as are cash shortfalls, confidence caps, your-plan-outranks-us demotions, and market-closed holds); the basing flag no longer quotes a price level the asset may be well above; style descriptions updated to disclose the early wallet-level trigger.

## [1.16.0] — 2026-07-31 — The long view
### Added
- **Full price history on the Charts tab** — new **1Y** and **Max** ranges. Max reaches as far back as our free data sources go: **PSE ~10 years** of official daily closes, **global stocks their entire listed life** (GE draws from 1962), **crypto ~1 year** (provider limit; downloads once the monthly data budget resets). After the one-time download, history grows forever at zero API cost from data we already collect.
- A **"Back in ⟨date⟩ / Since then"** readout under long-range charts — see at a glance whether an asset climbed from 0.1 to 10 or crawled from 5 to 10.
- **7d and 30d columns** on the Dashboard holdings table (sortable, like everything else).
- **Click any holding's name — or its Day/7d/30d cell — to jump straight to its chart.**
### Fixed
- A 15-finding adversarial review of the new collectors before launch: rate-limited downloads now wait politely instead of silently giving up (or stalling other collectors); transient network flakes retry instead of stranding assets with empty charts; weekly/monthly source bars are stamped on their true closing dates and half-finished periods are never stored; long-range charts space points evenly in time; every tooltip shows the point's exact date; all copy states honestly how deep each market's record goes.

## [1.17.0] — 2026-08-01 — Forgotten passwords
### Added
- **"Forgot password?" on the sign-in page.** The site is invite-only, so resets go through the person who runs it: tap the link, flag your request, and ask them for a **one-time reset code** — then set a new password with it. Codes work once and expire after 24 hours.
- **Password column in the Members panel** (admin): a red **RESET ASKED** badge when someone requests a reset, **CODE OUT** while a code is live, **CODE LOCKED** if too many wrong tries paused it — plus a one-click **Reset code** button. The code is shown to the admin exactly once; only its scrambled form is ever stored.
- **Changing or resetting a password now signs out every other device** on that account — the point of a reset when you think someone else got in. Changing your own password keeps you signed in where you are.
- An emergency recovery path for the admin's own account (a secret key kept in the hosting dashboard), so the one person who hands out codes can't get permanently locked out.
### Fixed
- A 15-finding adversarial security review before launch, then a second pass over the fixes: the sign-in page can't be used to discover which emails have accounts; a stranger can't flood guesses to keep someone locked out (attempts pause and heal, and a fresh code restores access instantly); an unauthenticated visitor can't exhaust the server's memory through the request form; and every message says exactly what the site does — including that it sends no notifications, so you still have to message the admin yourself.

## [1.17.1] — 2026-08-01 — Reset hardening follow-up
### Fixed
- The reset form's per-device guess limit now identifies visitors correctly behind the hosting provider's proxies (measured on the live service rather than assumed). Previously it would have lumped every visitor together, letting one person exhaust the whole site's allowance and block everyone else's resets.

## [1.18.0] — 2026-08-10 — Living within the free tier
### Changed
- **The site no longer polls in the background.** A tab you leave open in another window now uses zero data until you look at it again, and refreshes immediately when you return. Open tabs quietly re-downloading everything every 2 minutes were using far more of the database's monthly data allowance than the actual trading.
- Auto-refresh interval relaxed from 2 to 5 minutes, and the heavy full-market list is only re-fetched on the Watchlist tab where live prices matter.
- **Stock signals now recompute during market hours** instead of hourly around the clock — prices can't move while an exchange is shut, so the extra sweeps only cost data.
- Watchlist trend sparklines for stocks are drawn from stored daily closes and now cover **30 days instead of 7** (the column is labelled accordingly) — a longer view for fewer rows.
### Notes
- Triggered by a Supabase fair-use warning on 2026-08-10. Measured, not guessed: browser polling was the dominant cost (up to ~39 GB/month with tabs left open), signal sweeps ~3.3 GB/month. Projected usage after these changes is roughly **1.8 GB/month against the 5 GB allowance**, with no loss of information — only of repetition.

## [1.19.0] — 2026-08-10 — Your advisor, your way
### Added
- **Trailing stops** — a stop-loss that follows the price up, always staying your chosen % below its highest point since you set it, and never moving down. Locks in gains automatically on the way up; re-saving restarts it from the current price.
- **Trailing-buy alerts** — after you sell (or while you wait), the tracker watches the bottom and flags when the price has rebounded your chosen % off its low. Survives selling the position; clears itself after 30 days.
- **Enter TP/SL as percentages** — the plan editor has a price / "% from current" switch, converting live with risk:reward shown.
- **Industry-aware news** — stories now carry 🏭 sector chips (banks ▲, energy ▼ …) showing which industries they touch and the headline's tone. The advisor folds sector news into each stock's score too — gently, capped at ±0.5 of the ±3 direct-news scale, with its own line in the Full-reasoning ledger. Stories naming the company directly are never counted twice, and syndicated copies of one story count once.
- **Aggressiveness setting** (Account panel) — Cautious halves buy sizes and raises the bar to act; Aggressive sizes ×1.5 and acts on earlier signals (labelled honestly when it does). Never changes the sell side.
- **Portfolio spread setting** — Focused / Balanced / Spread out moves the concentration cap ±10 points around your style's baseline; buys always stop at or below your own trim line, whatever the combination.
- **%/$ display switch** above Holdings — the Day/7d/30d columns show percentages or money, your choice per device, and sort by whichever is shown.
### Fixed
- A 13-finding adversarial review before launch (plus hand-verification where the review tooling hit limits): buy suggestions can no longer build a position the same engine would immediately trim; re-saving a trailing plan genuinely restarts it (the old stop can't fossilize); the plan editor no longer risks wiping levels when an asset briefly has no live price; sector keywords match whole words only ("ore" no longer tags half the feed as mining); the example headline always argues the same direction as the score; plan alerts keep their dashboard slot over mere price movers.

## [1.19.1] — 2026-08-10 — $ mode clarity
### Fixed
- Money amounts on the dashboard now always show plain cents (−$0.30, not −$0.3012) — the extra decimals belonged to tiny coin prices, not to P/L and day-move figures.
- In $ mode, hovering a Day/7d/30d figure now explains exactly what it is: the market's move over that window at your current position size — not your personal profit, which stays in the P/L columns. (Sharp catch from the admin: a 7-day figure can legitimately exceed your total P/L if you bought mid-window.)

## [1.20.0] — 2026-08-11 — Spread that fits your wallet
### Added
- **Position counts now consider wallet size.** Each market wallet is classed smaller/bigger (under ₱100k for PSE, under $2,000 for crypto & global) and your spread setting maps to a healthy band of names — Focused on a smaller wallet means about **3–5 companies** (calibration credit: the admin's investor contact). The Account panel states the numbers.
- **At your limit, the advisor says rotate — not accumulate.** A good setup on a new name becomes a WATCH explaining that another name would spread the wallet too thin, and points at your weakest-rated holding as the natural funding source. Adding to what you already own stays allowed — that's consolidation.
- **Rotation thoughts in the briefing** — when a clearly weak holding coexists with a clearly strong candidate, the briefing names the pair, quoting the 30-day trend only when it genuinely agrees. Sell strength into strength; the final call stays yours.
- Briefing nudges when you're outside your band: too many names ("consolidate into your strongest picks") or too few with idle cash.
### Fixed
- Review round (6 findings): wording says "portfolio" not "wallet" when no budget is set (and the band notes it's judged from invested positions); a demoted card can no longer claim a halved buy size it doesn't have; the rotation thought never endorses a name whose own card says to wait (earnings/chasing gates); the room-to-add nudge counts against the band floor honestly.

## [1.20.1] — 2026-08-12 — Honest charts for stocks that never trade
### Fixed
- Charts for rarely-traded / suspended names (e.g. Asia Amalgamated) no longer look broken: a perfectly flat price gets a properly padded axis and a plain-language note — the price genuinely hasn't moved, and thinly traded names are worth knowing about before buying in. (Reported by the admin.)
- Those same names no longer show **RSI 100 → STRONG SELL**: zero price movement made the math degenerate into fake "overbought" readings. A stock with no meaningful movement in the window now reads WAIT — "technical reads need movement."
- The Max-range note now distinguishes "deeper history still downloading" from "that's everything the data sources have" — for six PSE names the exchange itself serves no chart history, and the site now says so instead of promising more.
### Notes
- Full system check alongside: collectors fresh, deep-history backfill complete on all three markets (crypto's year filled after the provider's quota reset), 572k stored daily closes with zero bad values, advisor builds clean for every member, site healthy.

## [1.21.0] — 2026-08-12 — Suggestions you can resize
### Added
- **Accepting a suggestion now opens a small editor** — the suggested amount is prefilled but fully editable (with live quantity conversion at the current price), and you can add your broker/exchange fee before it's logged. The suggestion is a starting point; the size is yours. (Requested by the admin.)
### Fixed
- **Buy sizing now follows your Portfolio spread setting.** Starter buys were a flat 5% of the wallet no matter what; a "Focused" user whose own setting means 3–5 names was being handed 5% crumbs. Starters now size to your name band — Focused ≈15% of the wallet, Balanced ≈11%, Spread ≈8% (smaller wallets slightly larger, capped at 25%) — and each BUY card says exactly how it was sized. (Also reported by the admin.)

## [1.22.0] — 2026-08-13 — Trades, wallet in view, no pocket-change advice
### Changed
- **The Portfolio tab is now called "Trades"** — it's where buying and selling happens; "Portfolio" and "Holdings" meant the same thing. (The dashboard's value chart is now labelled "Holdings Value" to match.)
### Added
- **Your wallet, right on the Trades tab**: cash available, money in positions, and your budget — visible where you log trades, so you always know what's left to spend.
### Fixed
- **No more suggestions to spend your last few pesos.** With ₱700 left of a ₱20,700 wallet, the advisor was still proposing buys — technically affordable, practically silly. The minimum meaningful buy now scales with your wallet and settings (a third of your starter size — spread setting and aggressiveness included), and the card explains it: "your remaining cash is below a meaningful buy for your settings (~₱753, about 4% of your wallet) — spending the last few pesos just feeds fees." (Reported by the admin, from his own wallet.)

## [1.22.1] — 2026-08-13 — Delisting the dead
### Removed
- **Asia Amalgamated (AAA)** removed from the whole system — watchlist, signals, charts, predictions — at the admin's request: it hasn't been allowed to trade in about a decade. The exchange directory sync now maintains an exclusion list, so re-syncs can't quietly bring it back. Five more names share the identical zero-movement profile (MGH, NXGEN, PNC, PORT, PTT) and can be excluded with one word each when the admin decides.

## [1.22.2] — 2026-08-13 — Suspended PSE stocks removed
### Removed
- **17 more suspended or trade-dead PSE names removed** (18 total with AAA): Abra Mining, BHI Holdings, Bogo-Medellin, Coal Asia, Cyber Bay, IP E-Game, I-Remit, Manila Jockey Club, MJC Investments, Phoenix Petroleum, Roxas Holdings, Tubig Pilipinas, and five shells with no recorded trades at all (MGH, NXGEN, PNC, PORT, PTT). Criterion: no price change in 180+ days, measured against ~10 years of stored closes. Nobody held or targeted any of them. The PSE universe is now 265 genuinely tradeable companies, and the exchange-directory sync keeps the dead ones out. Reinstating any name is a one-line change if the exchange lifts a suspension.

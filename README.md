# 📊 Asset Tracker (web)

Multi-user portfolio tracker and advisor for crypto, the Philippine Stock
Exchange, and global stocks. Flask + Postgres; one gunicorn worker hosts a
shared background data collector (prices, news, fundamentals, signals), while
portfolios, budgets, watchlists and advisories are per user. Invite-only
registration; the first registered account becomes the admin.

## Run

Set `DATABASE_URL` (Postgres) and `SECRET_KEY`, optionally `FINNHUB_API_KEY`
and `COINGECKO_API_KEY`, then:

    gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT app:app

Exactly one worker — it owns the shared data collector. Signals and advisor
suggestions shown by this app are automated heuristics, not financial advice.

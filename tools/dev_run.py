"""Run the web app locally for UI verification WITHOUT the background
collectors (RUN_SCHEDULER=0), against the DATABASE_URL in .env.

    python tools/dev_run.py    ->  http://127.0.0.1:8951
"""

import os
import sys

os.environ["RUN_SCHEDULER"] = "0"
os.environ.setdefault("SECRET_KEY", "dev-local-only")

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)
os.chdir(root)
with open(os.path.join(root, ".env"), encoding="utf-8") as f:
    for line in f:
        if line.startswith("DATABASE_URL="):
            os.environ["DATABASE_URL"] = line.split("=", 1)[1].strip()

import app  # noqa: E402  (import starts nothing - scheduler is disabled)

# NOT Flask's threaded dev server: it spawns a thread per request, and every
# thread opens its own session on the Supabase pooler (15 in total, shared
# with production). A page load's burst of ~10 parallel calls then starves
# the live site. Single-threaded, a local run holds one request session
# (plus the advisor worker's), released after 90 s idle by db's janitor.
app.app.run(host="127.0.0.1", port=8951, threaded=False)

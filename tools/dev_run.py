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

app.app.run(host="127.0.0.1", port=8951, threaded=True)

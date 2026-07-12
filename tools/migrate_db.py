"""Copy the Asset Tracker database from Neon to a new Postgres host.

Usage:
    python tools/migrate_db.py                      -> dry run: source inventory only
    python tools/migrate_db.py "<TARGET_DB_URL>"    -> full copy + verify

Reads the SOURCE from DATABASE_URL in .env (Neon). Pure psycopg - no pg_dump
needed. The DB is small (tens of MB), so a straight row copy is fine.
Safe to re-run: target tables are truncated before each copy.
"""

import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from psycopg.rows import dict_row

import db  # for SCHEMA only - we do not use its connection helpers here


def env_source_url():
    envp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    with open(envp, encoding="utf-8") as f:
        for line in f:
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("DATABASE_URL not found in .env")


def table_names():
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", db.SCHEMA)


def inventory(cur, tables):
    out = {}
    for t in tables:
        out[t] = cur.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
    return out


def main():
    src_url = env_source_url()
    tables = table_names()
    print(f"tables in schema: {tables}")

    src = psycopg.connect(src_url, row_factory=dict_row)
    src_counts = inventory(src.cursor(), tables)
    print("SOURCE (Neon) row counts:")
    for t, n in src_counts.items():
        print(f"  {t:20} {n:>8,}")

    if len(sys.argv) < 2:
        print("\nDry run complete (no target given).")
        return

    tgt_url = sys.argv[1]
    tgt = psycopg.connect(tgt_url, row_factory=dict_row)
    tgt.autocommit = False
    tcur = tgt.cursor()

    print("\n1) creating schema on target...")
    tcur.execute(db.SCHEMA)
    # the same idempotent migrations db.init() applies on boot
    tcur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS trading_style TEXT DEFAULT 'swing'")
    tcur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS agreed_terms BOOLEAN DEFAULT FALSE")
    tcur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS fee DOUBLE PRECISION DEFAULT 0")
    tgt.commit()

    print("1b) column-diff safety net...")
    scur0 = src.cursor()
    for t in tables:
        src_cols = {r["column_name"]: r["data_type"] for r in scur0.execute(
            "SELECT column_name, data_type FROM information_schema.columns"
            " WHERE table_name=%s AND table_schema='public'", (t,)).fetchall()}
        tgt_cols = {r["column_name"] for r in tcur.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name=%s AND table_schema='public'", (t,)).fetchall()}
        for c, dtype in src_cols.items():
            if c not in tgt_cols:
                print(f"   adding missing column {t}.{c} ({dtype})")
                tcur.execute(f'ALTER TABLE {t} ADD COLUMN "{c}" {dtype}')
    tgt.commit()

    print("2) copying rows...")
    scur = src.cursor()
    for t in tables:
        cols = [r["column_name"] for r in scur.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name=%s AND table_schema='public' ORDER BY ordinal_position",
            (t,)).fetchall()]
        col_list = ", ".join(cols)
        rows = scur.execute(f"SELECT {col_list} FROM {t}").fetchall()
        tcur.execute(f"TRUNCATE {t}")
        if rows:
            ph = ", ".join(["%s"] * len(cols))
            tcur.executemany(
                f"INSERT INTO {t} ({col_list}) VALUES ({ph})",
                [tuple(r[c] for c in cols) for r in rows])
        tgt.commit()
        print(f"   {t:20} {len(rows):>8,} rows")

    print("3) fixing SERIAL sequences...")
    for r in tcur.execute("""
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema='public' AND column_default LIKE 'nextval%'""").fetchall():
        t, c = r["table_name"], r["column_name"]
        tcur.execute(
            f"SELECT setval(pg_get_serial_sequence('{t}','{c}'),"
            f" (SELECT COALESCE(MAX({c}), 1) FROM {t}))")
        val = tcur.fetchone()["setval"]
        print(f"   {t}.{c} sequence -> {val}")
    tgt.commit()

    print("4) verifying...")
    tgt_counts = inventory(tcur, tables)
    ok = True
    for t in tables:
        match = src_counts[t] == tgt_counts[t]
        ok &= match
        print(f"   {t:20} src={src_counts[t]:>8,} tgt={tgt_counts[t]:>8,} {'OK' if match else 'MISMATCH!'}")
    # spot-check kv payloads byte-for-byte
    for r in scur.execute("SELECT key, value FROM kv ORDER BY key LIMIT 5").fetchall():
        tv = tcur.execute("SELECT value FROM kv WHERE key=%s", (r["key"],)).fetchone()
        same = tv and tv["value"] == r["value"]
        ok &= bool(same)
        print(f"   kv[{r['key']}] payload {'OK' if same else 'MISMATCH!'}")
    # prove inserts work post-sequence-fix (rolled back)
    tcur.execute("INSERT INTO users (email, password_hash, created) VALUES ('__migtest__','x','x') RETURNING id")
    print(f"   test INSERT users -> id {tcur.fetchone()['id']} (rolling back)")
    tgt.rollback()

    print("\nMIGRATION " + ("VERIFIED OK" if ok else "HAS MISMATCHES - DO NOT CUT OVER"))
    src.close(); tgt.close()


if __name__ == "__main__":
    main()

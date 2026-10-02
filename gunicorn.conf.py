"""gunicorn reads this file from the working directory on its own.

Render's gunicorn loads the app in the master process (preload) and forks
the worker that serves requests. Anything started at import time therefore
runs in the master - which is where the shared data collector ended up
(2026-10-02: collector in pid 58, requests served by pid 61 from a snapshot
cache it never saw refreshed). post_fork runs in the worker, right after the
fork: the one place the collector may live, because it writes what this
same process serves.
"""


def post_fork(server, worker):
    import app as _app   # already imported under preload; imports it otherwise
    _app.ensure_scheduler()

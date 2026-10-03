"""DB connection helper. DATABASE_URL comes from the environment (compose).

Uses psycopg3 in autocommit-friendly blocking mode. All schema creation is
idempotent so restarts and existing volumes are safe.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")


def is_configured() -> bool:
    return bool(DATABASE_URL)


@contextmanager
def conn():
    import psycopg

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set — copy .env.example to .env")
    with psycopg.connect(DATABASE_URL) as c:
        yield c

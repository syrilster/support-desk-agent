"""Postgres schema and seed data (customers, orders, refunds)."""
import os

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()


def connect() -> psycopg.Connection:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set. Add it to .env")
    return psycopg.connect(url, row_factory=dict_row)

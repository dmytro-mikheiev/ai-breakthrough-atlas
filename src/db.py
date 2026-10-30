"""Two-table PostgreSQL storage; credentials never enter experiment settings."""

import os
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from .settings import ROOT

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS books (
    id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, source_path TEXT UNIQUE NOT NULL,
    content_hash TEXT NOT NULL, ingestion JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id BIGSERIAL PRIMARY KEY, book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL, text TEXT NOT NULL, embedding VECTOR(1024) NOT NULL,
    UNIQUE(book_id, chunk_index)
);
"""


@contextmanager
def connect():
    load_dotenv(ROOT / ".env")
    try:
        conn = psycopg.connect(
            os.getenv(
                "DATABASE_URL",
                "postgresql://capabilities:local-development-only@localhost:55432/capabilities",
            ),
            row_factory=dict_row,
            connect_timeout=5,
        )
    except psycopg.Error:
        raise RuntimeError(
            "Database unavailable. Start Docker Compose and check local connection settings."
        ) from None
    with conn:
        yield conn


def initialize(conn):
    conn.execute(SCHEMA)
    register_vector(conn)


def corpus(conn, settings):
    rows = conn.execute(
        "SELECT * FROM books WHERE source_path = ANY(%s) ORDER BY source_path", (settings.books,)
    ).fetchall()
    if len(rows) != len(settings.books):
        raise ValueError("Selected books are not ingested. Run ingestion first.")
    if any(b["ingestion"] != settings.ingestion() for b in rows):
        raise ValueError("Chunk/embedding settings changed. Re-ingest selected books first.")
    return rows

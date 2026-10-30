"""Local text ingestion and BGE-M3 embeddings. No inference API calls."""

import hashlib
import re
from functools import lru_cache

from .settings import BOOKS


def source_text(raw):
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    start = re.search(r"\*\*\* START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", text, re.I)
    end = re.search(r"\*\*\* END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", text, re.I)
    return text[start.end() if start else 0 : end.start() if end else len(text)].strip()


def chunks(text, size=350, overlap=70):
    if not 0 <= overlap < size:
        raise ValueError("Require 0 <= overlap < chunk size")
    spans = list(re.finditer(r"\S+", text))
    for i in range(0, len(spans), size - overlap):
        stop = min(i + size, len(spans))
        yield text[spans[i].start() : spans[stop - 1].end()]
        if stop == len(spans):
            break


@lru_cache(maxsize=1)
def encoder(model, revision):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model, revision=revision)


def embed(texts, settings):
    import numpy as np

    model = encoder(settings.embedding_model, settings.embedding_revision)
    # Refuse silent tokenizer truncation rather than losing source evidence.
    lengths = [len(model.tokenizer.encode(t, truncation=False)) for t in texts]
    if max(lengths, default=0) > model.max_seq_length:
        raise ValueError("Text exceeds embedding context; reduce chunk_words")
    vectors = model.encode(
        texts, normalize_embeddings=True, batch_size=8, show_progress_bar=len(texts) > 8
    )
    if vectors.shape != (len(texts), 1024) or not np.isfinite(vectors).all():
        raise ValueError("Invalid BGE-M3 embeddings")
    return vectors


def book_needs_ingestion(name, settings):
    """Check the stored filename, content hash and embedding/chunk settings."""
    from .db import connect, initialize

    path = BOOKS / name
    if path.resolve().parent != BOOKS.resolve():
        raise ValueError("Book path escapes data")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with connect() as conn:
        initialize(conn)
        book = conn.execute("SELECT * FROM books WHERE source_path=%s", (name,)).fetchone()
    return not book or book["content_hash"] != digest or book["ingestion"] != settings.ingestion()


def ingest(settings, names):
    from psycopg.types.json import Jsonb

    from .db import connect, initialize

    if not names:
        raise ValueError("No .txt books found in data/books")
    settings = settings.model_copy(update={"books": names})
    settings = type(settings).model_validate(settings.model_dump())
    result = []
    with connect() as conn:
        initialize(conn)
    for name in names:
        path = BOOKS / name
        if path.resolve().parent != BOOKS.resolve():
            raise ValueError("Book path escapes data")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        with connect() as conn:
            initialize(conn)
            # Transaction-scoped lock prevents duplicate refreshes by concurrent loaders.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (name,))
            old = conn.execute("SELECT * FROM books WHERE source_path=%s", (name,)).fetchone()
            if old and old["content_hash"] == digest and old["ingestion"] == settings.ingestion():
                result.append({"book": name, "status": "unchanged"})
                print(f"Unchanged: {name}", flush=True)
                continue
            parts = list(chunks(source_text(raw), settings.chunk_words, settings.overlap_words))
            if not parts:
                raise ValueError(f"Empty source: {name}")
            print(f"Embedding {name}: {len(parts)} chunks", flush=True)
            vectors = embed(parts, settings)
            book = conn.execute(
                """INSERT INTO books(title,source_path,content_hash,ingestion)
                VALUES (%s,%s,%s,%s) ON CONFLICT(source_path) DO UPDATE SET
                title=EXCLUDED.title,content_hash=EXCLUDED.content_hash,
                ingestion=EXCLUDED.ingestion RETURNING id""",
                (
                    path.stem,
                    name,
                    digest,
                    Jsonb(settings.ingestion()),
                ),
            ).fetchone()
            conn.execute("DELETE FROM chunks WHERE book_id=%s", (book["id"],))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks(book_id,chunk_index,text,embedding) VALUES (%s,%s,%s,%s)",
                    [(book["id"], i, t, v) for i, (t, v) in enumerate(zip(parts, vectors))],
                )
            result.append({"book": name, "status": "loaded", "chunks": len(parts)})
    return result

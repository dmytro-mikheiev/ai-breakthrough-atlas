"""Dense retrieval for one research question, with a separate limit per book."""

import hashlib

from .settings import BOOKS


def retrieve(settings):
    from pgvector.psycopg import register_vector

    from .db import connect, corpus
    from .ingest import embed

    chunks = []
    with connect() as conn:
        register_vector(conn)
        books = corpus(conn, settings)
        for book in books:
            if (
                hashlib.sha256((BOOKS / book["source_path"]).read_bytes()).hexdigest()
                != book["content_hash"]
            ):
                raise ValueError(
                    "Source changed since ingestion. Re-ingest before a new experiment."
                )
        vector = embed([settings.question], settings)[0]
        for book in books:
            selected = conn.execute(
                """SELECT id,book_id,chunk_index,text FROM chunks WHERE book_id=%s
                ORDER BY embedding <=> %s, id LIMIT %s""",
                (book["id"], vector, settings.top_k),
            ).fetchall()
            chunks.extend(
                dict(chunk, source_path=book["source_path"], title=book["title"])
                for chunk in selected
            )
    print(f"Retrieved {len(chunks)} chunks for classification.")
    return chunks

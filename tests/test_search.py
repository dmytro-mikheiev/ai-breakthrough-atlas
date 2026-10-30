"""Retrieval boundaries checked without a running database or embedding download."""

import hashlib
from unittest.mock import MagicMock

import pytest

from src import db, ingest, search
from tests.helpers import defaults


def test_retrieves_per_book_limit_and_source_metadata(tmp_path, monkeypatch):
    settings = defaults().model_copy(update={"books": ["First.txt", "Second.txt"], "top_k": 2})
    books = []
    for index, name in enumerate(settings.books, 1):
        (tmp_path / name).write_text(name)
        books.append(
            dict(
                id=index,
                source_path=name,
                title=name[:-4],
                ingestion=settings.ingestion(),
                content_hash=hashlib.sha256((tmp_path / name).read_bytes()).hexdigest(),
            )
        )
    conn = MagicMock()
    conn.__enter__.return_value = conn

    def execute(sql, params):
        result = MagicMock()
        if "FROM books" in sql:
            assert params == (settings.books,)
            result.fetchall.return_value = books
        else:
            book_id, vector, limit = params
            assert "ORDER BY embedding <=>" in sql
            assert vector == [0.1] and limit == 2
            # Second book contains only one candidate: do not invent a second chunk.
            result.fetchall.return_value = [
                dict(id=book_id * 10 + i, book_id=book_id, chunk_index=i, text=f"Passage {i}")
                for i in range(2 if book_id == 1 else 1)
            ]
        return result

    conn.execute.side_effect = execute
    monkeypatch.setattr(db, "connect", lambda: conn)
    monkeypatch.setattr("pgvector.psycopg.register_vector", lambda _: None)
    monkeypatch.setattr(search, "BOOKS", tmp_path)
    embedding_calls = []

    def embed(texts, config):
        embedding_calls.append(texts)
        assert config is settings
        return [[0.1]]

    monkeypatch.setattr(ingest, "embed", embed)
    chunks = search.retrieve(settings)
    assert embedding_calls == [[settings.question]]
    assert [c["source_path"] for c in chunks] == ["First.txt", "First.txt", "Second.txt"]
    assert [c["title"] for c in chunks] == ["First", "First", "Second"]
    (tmp_path / "First.txt").write_text("Changed after ingestion")
    with pytest.raises(ValueError, match="Source changed"):
        search.retrieve(settings)
    assert len(embedding_calls) == 1


@pytest.mark.parametrize(
    "rows, message", [([], "not ingested"), ([{"ingestion": {}}], "settings changed")]
)
def test_corpus_rejects_missing_books_or_stale_embeddings(rows, message):
    settings = defaults().model_copy(update={"books": ["First.txt"]})
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = rows
    with pytest.raises(ValueError, match=message):
        db.corpus(conn, settings)

"""Focused software checks using synthetic evidence; not a quality benchmark."""

import hashlib
import json
import os
import sys

import httpx
import pytest

from src import experiments
from src import facts as locations
from src.experiments import load_experiment, load_or_run_experiment, path_for
from src.facts import validate
from src.ingest import chunks, source_text
from tests.helpers import defaults


def example():
    quote = "In 1960 Example Lab demonstrated a machine that learned to recognize shapes."
    raw = dict(
        year=1960,
        breakthrough="Machine learned shape recognition.",
        location_name="Example Lab",
        source_quote=quote,
        latitude=None,
        longitude=None,
    )
    chunk = dict(
        id=127,
        book_id=1,
        title="Synthetic AI History",
        source_path="test.txt",
        text=quote,
        publication_year=1962,
    )
    return raw, chunk


def runner(settings):
    return [validate(*example())]


def fingerprints(root):
    return {
        p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in root.glob("facts_*")
    }


def test_replay_never_calls_services_or_mutates(tmp_path, monkeypatch):
    settings = defaults()
    raw, chunk = example()
    raw["year"] = None
    expected = [validate(raw, chunk)]
    load_or_run_experiment("baseline", settings, tmp_path, lambda _: expected)
    before = fingerprints(tmp_path)
    changed = settings.model_copy(update={"model": "different-model"})

    def forbidden(*args, **kwargs):
        pytest.fail("Service or write invoked during replay")

    monkeypatch.setattr(experiments, "run_pipeline", forbidden)
    monkeypatch.setattr(experiments, "save_experiment", forbidden)
    monkeypatch.setitem(sys.modules, "src.search", None)
    monkeypatch.setitem(sys.modules, "src.extract", None)
    monkeypatch.setitem(sys.modules, "src.classify", None)
    monkeypatch.setitem(sys.modules, "src.ingest", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    facts = load_or_run_experiment("baseline", changed, tmp_path)
    assert facts == expected
    assert list(tmp_path.iterdir()) == [path_for("baseline", tmp_path)]
    assert fingerprints(tmp_path) == before


def test_empty_and_invalid_json(tmp_path):
    load_or_run_experiment("empty", defaults(), tmp_path, lambda s: [])
    assert load_experiment("empty", tmp_path) == []
    json_path = path_for("empty", tmp_path)
    json_path.write_text("broken")
    with pytest.raises(ValueError, match="Invalid facts JSON"):
        load_or_run_experiment("empty", defaults(), tmp_path, runner)
    json_path.unlink()
    with pytest.raises(ValueError, match="not found"):
        load_experiment("empty", tmp_path)


@pytest.mark.parametrize("name", ["../bad", "Upper", ""])
def test_names(name, tmp_path):
    with pytest.raises(ValueError):
        load_or_run_experiment(name, defaults(), tmp_path, runner)


def test_failed_runner_no_completed_output(tmp_path):
    def fail(settings):
        raise RuntimeError("Simulated failure")

    with pytest.raises(RuntimeError):
        load_or_run_experiment("failed", defaults(), tmp_path, fail)
    assert not list(tmp_path.glob("facts_*"))


def test_failed_json_publish_leaves_no_result(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("Simulated disk failure")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(OSError):
        load_or_run_experiment("failed", defaults(), tmp_path, runner)
    assert list(tmp_path.iterdir()) == []


def test_chunking_preserves_text_and_strips_boilerplate():
    text = "one  two\nthree four five six"
    assert list(chunks(text, 4, 1)) == ["one  two\nthree four", "four five six"]
    assert (
        source_text(
            b"notice *** START OF THE PROJECT GUTENBERG EBOOK X *** body *** END OF THE PROJECT GUTENBERG EBOOK X *** license"
        )
        == "body"
    )


def mock_client(monkeypatch, handler):
    from src import extract

    client_type = httpx.Client
    monkeypatch.setattr(
        extract.httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler)),
    )
    return extract


def test_openai_contract_and_retries(monkeypatch):
    raw, passage = example()
    calls = []

    def handler(request):
        assert str(request.url) == "https://api.openai.com/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-5-mini"
        assert payload["reasoning_effort"] == "low"
        assert payload["max_completion_tokens"] == 3000
        assert "reasoning" not in payload and "provider" not in payload
        assert "max_tokens" not in payload
        assert "temperature" not in payload and "random_seed" not in payload
        assert payload["response_format"]["type"] == "json_schema"
        assert "facts" in payload["response_format"]["json_schema"]["schema"]["properties"]
        calls.append(payload)
        if len(calls) == 1:
            return httpx.Response(429)
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"facts": [dict(raw, chunk_id=str(passage["id"]))]}
                            )
                        },
                    }
                ],
            },
        )

    module = mock_client(monkeypatch, handler)
    monkeypatch.setattr("src.inference.time.sleep", lambda _: None)
    facts, stats = module.extract([passage], defaults(), "test-secret")
    assert len(facts) == 1 and stats["api_calls"] == 2
    assert "test-secret" not in json.dumps([facts, stats])


@pytest.mark.parametrize(
    "response",
    [
        {"choices": [{"finish_reason": "length", "message": {"content": '{"facts": []}'}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]},
        {"echo": "test-secret"},
    ],
)
def test_bad_api_response_aborts(monkeypatch, response):
    module = mock_client(monkeypatch, lambda r: httpx.Response(200, json=response))
    with pytest.raises(RuntimeError) as error:
        module.extract([example()[1]], defaults(), "test-secret")
    assert "test-secret" not in str(error.value)


def test_exact_fields_dates_and_coordinates():
    raw, chunk = example()
    fact = locations.validate(raw, chunk)
    assert list(fact) == locations.FIELDS
    assert fact["book_name"] == chunk["title"] and fact["chunk_id"] == "127"
    assert fact["latitude"] is fact["longitude"] is None
    assert fact["location"] == "undefined"
    assert fact["year"] == 1960
    raw["year"] = None
    assert locations.validate(raw, chunk)["year"] is None
    chunk.pop("publication_year")
    assert locations.validate(raw, chunk)["year"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"location_name": "Example Lab, New York, USA"},
        {"source_quote": "Invented evidence"},
        {"year": 1956},
        {"latitude": 42.0},
        {"book_name": "Invented title"},
    ],
)
def test_rejects_unsupported_fields(change):
    raw, chunk = example()
    raw.update(change)
    with pytest.raises(ValueError):
        locations.validate(raw, chunk)


def test_same_undated_fact_deduplicates_across_books():
    raw, chunk = example()
    raw["year"] = None
    duplicate = dict(chunk, id=128, title="Second Book", publication_year=2000)
    facts = locations.deduplicate([validate(raw, chunk), validate(raw, duplicate)])
    assert len(facts) == 1 and facts[0]["year"] is None


def test_new_pipeline_saves_json_only(tmp_path, monkeypatch):
    from src import search

    raw, passage = example()
    monkeypatch.setattr(search, "retrieve", lambda settings: [passage])
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")

    def handler(request):
        assert request.url.host == "api.openai.com"
        if request.url.path == "/v1/decisions":
            return httpx.Response(
                200,
                json={
                    "answers": [
                        {
                            "type": "choice",
                            "name": "relevant",
                            "choice": "keep",
                            "confidence": 0.9,
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"facts": [dict(raw, chunk_id=str(passage["id"]))]}
                            )
                        },
                    }
                ]
            },
        )

    mock_client(monkeypatch, handler)
    facts = load_or_run_experiment("new_run", defaults(), tmp_path)
    assert len(facts) == 1
    assert [p.name for p in tmp_path.iterdir()] == ["facts_new_run.json"]


@pytest.mark.parametrize("batch_size", [1, 10])
def test_batches_preserve_sources_and_reject_wrong_chunk_evidence(monkeypatch, batch_size):
    raw, template = example()
    passages = [
        dict(template, id=127 + i, title=f"Book {i}", text=template["text"] + f" Passage {i}.")
        for i in range(11)
    ]
    sent = []

    def handler(request):
        payload = json.loads(request.content)
        batch = json.loads(payload["messages"][1]["content"])["chunks"]
        sent.append(batch)
        assert payload["max_completion_tokens"] == min(16000, 3000 * len(batch))
        properties = payload["response_format"]["json_schema"]["schema"]["$defs"]["ExtractedFact"][
            "properties"
        ]
        assert "chunk_id" in properties and "book_name" not in properties
        generated = [
            dict(
                raw,
                chunk_id=c["chunk_id"],
                year=None,
                source_quote=c["text"],
                breakthrough=f"Recognizer {c['chunk_id']}",
            )
            for c in batch
        ]
        # Valid evidence from another chunk must not be assigned to this chunk.
        first_id = int(batch[0]["chunk_id"]) - 127
        generated.append(dict(generated[0], source_quote=passages[(first_id + 1) % 11]["text"]))
        generated.append(dict(generated[0], chunk_id="outside-batch"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"facts": generated})},
                    }
                ]
            },
        )

    module = mock_client(monkeypatch, handler)
    settings = defaults().model_copy(update={"extractor_batch_size": batch_size})
    facts, stats = module.extract(passages, settings, "test-secret")
    assert [len(b) for b in sent] == ([1] * 11 if batch_size == 1 else [10, 1])
    assert [c["text"] for batch in sent for c in batch] == [p["text"] for p in passages]
    assert len(facts) == 11 and stats["api_calls"] == len(sent)
    assert stats["rejected"] == {"unsupported_quote": len(sent), "unknown_chunk_id": len(sent)}
    by_id = {str(p["id"]): p for p in passages}
    for fact in facts:
        source = by_id[fact["chunk_id"]]
        assert fact["book_name"] == source["title"]
        assert fact["year"] is None
        assert fact["source_quote"] == source["text"]


def test_ingestion_stores_filename_and_chunks(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from src import db, ingest

    name = "Synthetic Book.txt"
    (tmp_path / name).write_text("Example Lab demonstrated a learning machine.")
    conn, manager = MagicMock(), MagicMock()
    manager.__enter__.return_value = conn
    conn.execute.return_value.fetchone.side_effect = [None, {"id": 10}]
    monkeypatch.setattr(db, "connect", lambda: manager)
    monkeypatch.setattr(db, "initialize", lambda _: None)
    monkeypatch.setattr(ingest, "BOOKS", tmp_path)
    monkeypatch.setattr(ingest, "embed", lambda texts, settings: [[0.0] * 1024 for _ in texts])

    result = ingest.ingest(defaults(), [name])
    assert result == [{"book": name, "status": "loaded", "chunks": 1}]
    insert = next(
        call for call in conn.execute.call_args_list if "INSERT INTO books" in call.args[0]
    )
    assert insert.args[1][0:2] == ("Synthetic Book", name)
    assert "publication_year" not in insert.args[0]
    rows = conn.cursor.return_value.__enter__.return_value.executemany.call_args.args[1]
    assert len(rows) == 1 and rows[0][0] == 10
    assert sorted(p.name for p in tmp_path.iterdir()) == [name]


def test_book_check_detects_missing_changed_and_current_sources(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from src import db, ingest

    path = tmp_path / "Example.txt"
    path.write_text("Example book content.")
    settings = defaults()
    current = {
        "content_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "ingestion": settings.ingestion(),
    }
    conn, manager = MagicMock(), MagicMock()
    manager.__enter__.return_value = conn
    conn.execute.return_value.fetchone.side_effect = [
        None,
        current,
        dict(current, content_hash="changed"),
        dict(current, ingestion={}),
    ]
    monkeypatch.setattr(db, "connect", lambda: manager)
    monkeypatch.setattr(db, "initialize", lambda _: None)
    monkeypatch.setattr(ingest, "BOOKS", tmp_path)
    assert [ingest.book_needs_ingestion(path.name, settings) for _ in range(4)] == [
        True,
        False,
        True,
        True,
    ]
    assert all(call.args[1] == (path.name,) for call in conn.execute.call_args_list)


def test_notebook_checks_each_book_and_skips_checks_for_saved_experiments(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import nbformat

    from src import ingest
    from src.settings import ROOT

    notebook = nbformat.read(ROOT / "notebooks/analysis.ipynb", as_version=4)
    source = next(
        c.source
        for c in notebook.cells
        if c.cell_type == "code" and "for book in SELECTED_BOOKS:" in c.source
    )
    events = []
    path = tmp_path / "facts_saved.json"
    monkeypatch.setattr(experiments, "path_for", lambda name: path)

    def check(book, settings):
        events.append(("check", book))
        return book == "new.txt"

    monkeypatch.setattr(ingest, "book_needs_ingestion", check)
    monkeypatch.setattr(ingest, "ingest", lambda settings, books: events.append(("ingest", books)))

    def load(name, settings):
        events.append(("load", name))
        return []

    namespace = dict(
        EXPERIMENT_NAME=SimpleNamespace(value="saved"),
        settings=defaults(),
        SELECTED_BOOKS=["current.txt", "new.txt"],
        load_or_run_experiment=load,
    )
    exec(source, namespace)
    assert events == [
        ("check", "current.txt"),
        ("check", "new.txt"),
        ("ingest", ["new.txt"]),
        ("load", "saved"),
    ]
    path.write_text("[]")
    events.clear()
    exec(source, namespace)
    assert events == [("load", "saved")]


def test_missing_openai_key_stops_before_retrieval(tmp_path, monkeypatch):
    from src import search

    monkeypatch.setattr("dotenv.load_dotenv", lambda *args: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(search, "retrieve", lambda settings: pytest.fail("Unexpected retrieval"))
    with pytest.raises(ValueError, match="Set OPENAI_API_KEY"):
        load_or_run_experiment("missing_key", defaults(), tmp_path)
    assert not list(tmp_path.iterdir())

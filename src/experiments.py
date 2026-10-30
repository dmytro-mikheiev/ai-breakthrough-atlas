"""Save and replay extraction results as JSON arrays."""

import json
import os
import re
import tempfile
from pathlib import Path

from . import facts as schema
from .settings import OUTPUTS, ROOT, Settings


def path_for(name, root=OUTPUTS):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ValueError("Use 1–64 lowercase letters, digits, hyphens or underscores")
    root = Path(root).resolve()
    path = root / f"facts_{name}.json"
    if path.is_symlink() or path.resolve().parent != root:
        raise ValueError("JSON path must stay inside results directory")
    return path


def load_experiment(name, root=OUTPUTS):
    path = path_for(name, root)
    if not path.exists():
        raise ValueError(f"Saved JSON not found: {name}")
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("Expected a JSON array")
        return [schema.LocationFact.model_validate(row).model_dump() for row in rows]
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise ValueError(f"Invalid facts JSON: {name}") from None


def save_experiment(name, facts, root=OUTPUTS, overwrite=False):
    path = path_for(name, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            [schema.LocationFact.model_validate(fact).model_dump() for fact in facts],
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    if overwrite and path.exists() and path.read_text() == payload:
        return path
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    try:
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def run_pipeline(settings):
    from dotenv import load_dotenv

    from .classify import filter_chunks
    from .extract import extract
    from .search import retrieve

    load_dotenv(ROOT / ".env")
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise ValueError(
            "Set OPENAI_API_KEY in the project .env file before starting a new experiment"
        )
    chunks = retrieve(settings)
    if not chunks:
        return []
    chunks = filter_chunks(chunks, settings, key)
    if not chunks:
        return []
    facts, stats = extract(chunks, settings, key)
    if key in json.dumps(facts):
        raise RuntimeError("Secret found in generated facts; JSON not saved")
    print(
        f"API calls: {stats['api_calls']}; rejected candidates: {sum(stats['rejected'].values())}."
    )
    return facts


def load_or_run_experiment(name, settings, root=OUTPUTS, runner=None):
    if path_for(name, root).exists():
        return load_experiment(name, root)
    facts = (runner or run_pipeline)(Settings.model_validate(settings))
    save_experiment(name, facts, root)
    return load_experiment(name, root)

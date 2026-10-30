"""Batched OpenAI extraction with per-chunk evidence validation."""

import json
from collections import Counter

import httpx
from pydantic import ValidationError

from . import facts as schema
from .inference import post_json


def extract(chunks, settings, api_key):
    if not api_key or not api_key.strip():
        raise ValueError("OpenAI API key is required for a new run")
    if len(chunks) > settings.max_calls:
        raise ValueError(
            "Unique chunks exceed max_calls. Reduce Top K/books or explicitly increase the limit."
        )
    if api_key in settings.model_dump_json():
        raise ValueError("Secret found in experiment settings; remove it before running")
    stats = {"api_calls": 0}
    accepted, rejected = [], Counter()
    payload = {
        "model": settings.model,
        "reasoning_effort": settings.reasoning_effort,
        "max_completion_tokens": settings.max_tokens,
        "messages": [
            {
                "role": "system",
                "content": settings.prompt
                + "\nResearch question:\n"
                + settings.question
                + "\nInput contains independent chunks with chunk_id and text. "
                "Return each fact with its source chunk_id exactly as supplied. "
                "Use only that chunk for the fact; never combine evidence across chunks.",
            },
            {"role": "user", "content": ""},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "book_facts",
                "schema": schema.ExtractionResult.model_json_schema(),
                "strict": True,
            },
        },
    }
    with httpx.Client(timeout=120) as client:
        for start in range(0, len(chunks), settings.extractor_batch_size):
            batch = chunks[start : start + settings.extractor_batch_size]
            sources = {str(chunk["id"]): chunk for chunk in batch}
            payload["messages"][1]["content"] = json.dumps(
                {
                    "chunks": [
                        {"chunk_id": key, "text": chunk["text"]} for key, chunk in sources.items()
                    ]
                },
                ensure_ascii=False,
            )
            # Scale the output allowance for larger batches, capped at 16,000 tokens.
            payload["max_completion_tokens"] = min(16000, settings.max_tokens * len(batch))
            data, calls = post_json(
                client, settings.api_endpoint, payload, api_key, settings.max_retries
            )
            stats["api_calls"] += calls
            try:
                choice = data["choices"][0]
                if choice["finish_reason"] != "stop":
                    raise ValueError("Incomplete generation")
                parsed = json.loads(choice["message"]["content"])
                if set(parsed) != {"facts"} or not isinstance(parsed["facts"], list):
                    raise ValueError("Invalid facts response")
            except (KeyError, IndexError, TypeError, ValueError):
                raise RuntimeError(
                    "Incomplete or invalid structured response. No experiment saved."
                ) from None
            for raw in parsed["facts"]:
                try:
                    raw = schema.ExtractedFact.model_validate(raw).model_dump()
                    chunk_id = raw.pop("chunk_id")
                    if chunk_id not in sources:
                        raise ValueError("unknown_chunk_id")
                    fact = schema.validate(raw, sources[chunk_id])
                    accepted.append(fact)
                except ValidationError:
                    rejected["schema_invalid"] += 1
                except ValueError as error:
                    rejected[str(error)] += 1
            print(
                f"Extracted chunks {start + 1}–{start + len(batch)}/{len(chunks)}; "
                f"accepted {len(accepted)}, rejected {sum(rejected.values())}.",
                flush=True,
            )
    stats["rejected"] = dict(rejected)
    return schema.deduplicate(accepted), stats

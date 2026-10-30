"""OpenAI Decisions software contract checks; not a relevance or historical quality evaluation."""

import json

import httpx
import pytest

from src import classify
from tests.helpers import defaults


def test_filter_preserves_uncertain_and_drops_only_confident_negatives(monkeypatch):
    responses = iter([("keep", 1), ("drop", 0.8), ("drop", 0.79), ("uncertain", 1)])
    settings = defaults()
    settings.classifier_criteria["keep"] = "Custom notebook criterion"
    chunks = [dict(id=i, text=f"Synthetic passage {i}") for i in range(4)]

    def handler(request):
        payload = json.loads(request.content)
        assert str(request.url) == classify.ENDPOINT
        assert payload["model"] == settings.classifier_model
        assert payload["model"] == "gpt-6-luna"
        assert "state" not in payload
        assert len(payload["questions"]) == 1
        question = payload["questions"][0]
        assert question["name"] == "relevant"
        assert settings.classifier_prompt in question["instructions"]
        assert {
            c["value"]: c["description"] for c in question["choices"]
        } == settings.classifier_criteria
        assert settings.question in question["instructions"]
        assert question["type"] == "choice" and {c["value"] for c in question["choices"]} == {
            "keep",
            "drop",
            "uncertain",
        }
        choice, confidence = next(responses)
        return httpx.Response(
            200,
            json={
                "answers": [
                    {
                        "type": "choice",
                        "name": "relevant",
                        "choice": choice,
                        "confidence": confidence,
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(classify.httpx, "Client", lambda **kwargs: client)
    kept = classify.filter_chunks(chunks, settings, "test-secret")
    assert [c["id"] for c in kept] == [0, 2, 3]
    assert len(chunks) == 4 and kept[0] is chunks[0]


@pytest.mark.parametrize(
    "answers",
    [
        [{"type": "refusal", "name": "relevant"}],
        [{"type": "choice", "name": "wrong", "choice": "drop", "confidence": 1}],
        [],
        [{"type": "choice", "name": "relevant", "choice": "drop", "confidence": True}],
    ],
)
def test_invalid_or_refused_decisions_abort(monkeypatch, answers):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"answers": answers})
        )
    )
    monkeypatch.setattr(classify.httpx, "Client", lambda **kwargs: client)
    with pytest.raises(RuntimeError, match="Invalid OpenAI decision response"):
        classify.filter_chunks([dict(text="Synthetic passage")], defaults(), "test-secret")

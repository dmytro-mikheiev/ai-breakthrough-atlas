"""OpenAI Decisions keeps promising passages; only confident negatives are dropped."""

import math

import httpx

from .inference import post_json

ENDPOINT = "https://api.openai.com/v1/decisions"


def decision(client, payload, settings, api_key):
    data, _ = post_json(client, ENDPOINT, payload, api_key, settings.max_retries)
    try:
        answers = data["answers"]
        if not isinstance(answers, list) or len(answers) != 1:
            raise ValueError("Expected one decision")
        answer = answers[0]
        confidence = answer["confidence"]
        if (
            answer["type"] != "choice"
            or answer["name"] != "relevant"
            or answer["choice"] not in settings.classifier_criteria
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Invalid decision")
        return answer
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Invalid OpenAI decision response; experiment not saved.") from None


def filter_chunks(chunks, settings, api_key):
    if not api_key or not api_key.strip():
        raise ValueError("OpenAI API key is required for classification")
    if api_key in settings.model_dump_json():
        raise ValueError("Secret found in experiment settings; remove it before running")
    kept = []
    instructions = settings.classifier_prompt + "\nResearch question:\n" + settings.question
    with httpx.Client(timeout=120) as client:
        for index, chunk in enumerate(chunks, 1):
            answer = decision(
                client,
                {
                    "model": settings.classifier_model,
                    "input": chunk["text"],
                    "questions": [
                        {
                            "type": "choice",
                            "name": "relevant",
                            "instructions": instructions,
                            "choices": [
                                {"value": label, "description": description}
                                for label, description in settings.classifier_criteria.items()
                            ],
                        }
                    ],
                },
                settings,
                api_key,
            )
            if (
                answer["choice"] != "drop"
                or answer["confidence"] < settings.classifier_drop_confidence
            ):
                kept.append(chunk)
            if index % 10 == 0:
                print(f"Classified {index}/{len(chunks)} chunks.", flush=True)
    print(f"Classifier: {len(kept)} kept; {len(chunks) - len(kept)} dropped.")
    return kept

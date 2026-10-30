"""Shared OpenAI HTTP handling: bounded retries and secret-free errors."""

import time

import httpx


def post_json(client, endpoint, payload, api_key, max_retries):
    for attempt in range(max_retries + 1):
        try:
            response = client.post(
                endpoint, json=payload, headers={"Authorization": f"Bearer {api_key}"}
            )
        except httpx.HTTPError:
            response = None
        status = response.status_code if response is not None else 0
        if status == 200:
            try:
                if api_key in response.text:
                    raise ValueError("Secret echoed")
                return response.json(), attempt + 1
            except (ValueError, TypeError):
                raise RuntimeError(
                    "Unsafe or invalid API response; experiment not saved."
                ) from None
        print(f"OpenAI call failed (HTTP {status or 'network'}); attempt {attempt + 1}.")
        if status not in {0, 408, 429, 500, 502, 503, 504} or attempt == max_retries:
            raise RuntimeError(
                f"OpenAI request failed (HTTP {status or 'network'}); experiment not saved."
            ) from None
        delay = 2**attempt
        if response is not None:
            try:
                delay = max(delay, min(60, float(response.headers.get("retry-after", 0))))
            except ValueError:
                pass
        time.sleep(delay)

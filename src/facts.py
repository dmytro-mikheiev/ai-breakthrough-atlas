"""Source-backed AI breakthroughs with inline location-resolution status."""

import hashlib
import json
import re
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .settings import StrictModel


def whitespace(text):
    return " ".join(text.split())


def canonical(text):
    return whitespace(text).casefold()


class RawLocationFact(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    year: int | None = Field(ge=1600, le=2100)
    breakthrough: str = Field(min_length=1)
    location_name: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    latitude: None
    longitude: None


class ExtractedFact(RawLocationFact):
    chunk_id: str = Field(min_length=1)


class ExtractionResult(StrictModel):
    facts: list[ExtractedFact]


class LocationFact(RawLocationFact):
    location: Literal["undefined", "defined", "unknown", "ambiguous"]
    latitude: float | None = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(ge=-180, le=180, allow_inf_nan=False)
    book_name: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_coordinates(self):
        resolved = self.location in {"defined", "ambiguous"}
        if resolved != (self.latitude is not None) or resolved != (self.longitude is not None):
            raise ValueError("Location status and coordinates disagree")
        return self


FIELDS = [
    "year",
    "breakthrough",
    "location_name",
    "location",
    "source_quote",
    "latitude",
    "longitude",
    "book_name",
    "chunk_id",
]


def identity(fact):
    """Internal deduplication key; never added to public fact objects."""
    claim = [fact["year"], canonical(fact["breakthrough"]), canonical(fact["location_name"])]
    return hashlib.sha256(json.dumps(claim, ensure_ascii=False).encode()).hexdigest()


def validate(raw, chunk):
    fact = RawLocationFact.model_validate(raw).model_dump()
    quote = whitespace(fact["source_quote"])
    if quote not in whitespace(chunk["text"]):
        raise ValueError("unsupported_quote")
    if canonical(fact["location_name"]) not in canonical(quote):
        raise ValueError("unsupported_location")
    if fact["year"] is not None and not re.search(rf"\b{fact['year']}\b", quote):
        raise ValueError("unsupported_year")
    fact.update(location="undefined", book_name=chunk["title"], chunk_id=str(chunk["id"]))
    fact = LocationFact.model_validate(fact).model_dump()
    return {key: fact[key] for key in FIELDS}


def deduplicate(facts):
    unique = {}
    for fact in facts:
        unique.setdefault(identity(fact), fact)
    return [unique[key] for key in sorted(unique)]

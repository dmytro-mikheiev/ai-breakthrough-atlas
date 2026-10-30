"""Synthetic GeoNames records test inline statuses and in-place persistence."""

import json
import zipfile

import pytest

from src.experiments import load_experiment, path_for, save_experiment
from src.facts import LocationFact, validate
from src.geocode import name_key, normalize_locations, prepare_geonames, update_locations
from tests.test_core import example


def dataset(tmp_path, monkeypatch):
    def row(identifier, name, aliases, latitude=40, feature="UNIV"):
        fields = [
            str(identifier),
            name,
            name,
            aliases,
            str(latitude),
            "-70",
            "S",
            feature,
            "US",
            "",
            "MA",
        ]
        return "\t".join(fields + [""] * 8)

    with zipfile.ZipFile(tmp_path / "US.zip", "w") as archive:
        archive.writestr(
            "US.txt",
            "\n".join(
                [
                    row(1, "Example Institute", "E.I.,Éxample Institute"),
                    row(2, "Springfield", "", latitude=41),
                    row(3, "Springfield", "", latitude=42),
                    row(4, "Shared", "", latitude=44, feature="BLDG"),
                    row(5, "Example University", "Shared", latitude=45),
                ]
            ),
        )
    monkeypatch.setattr("src.geocode.httpx.stream", lambda *a, **k: pytest.fail("Network used"))
    return prepare_geonames(folder=tmp_path)


def fact(location):
    return dict(validate(*example()), location_name=location)


def test_aliases_ambiguity_unknown_and_original_names(tmp_path, monkeypatch):
    db = dataset(tmp_path, monkeypatch)
    assert name_key("Éxample Institute") == name_key("Example Institute")
    assert name_key("東京") == "東京"
    originals = [
        fact(name)
        for name in [
            "E.I.",
            "Example Institute’s computer",
            "Springfield",
            "Unknown Lab",
            "Example Institute and Springfield",
        ]
    ]
    before = json.dumps(originals)
    resolved = normalize_locations(originals, db)
    assert [f["location"] for f in resolved] == [
        "defined",
        "defined",
        "ambiguous",
        "unknown",
        "ambiguous",
    ]
    assert resolved[0]["latitude"] == 40 and resolved[0]["longitude"] == -70
    assert resolved[2]["latitude"] == 41  # First candidate wins when scores tie.
    assert resolved[3]["latitude"] is resolved[3]["longitude"] is None
    assert [f["location_name"] for f in resolved] == [f["location_name"] for f in originals]
    assert json.dumps(originals) == before
    stamp = db.stat().st_mtime_ns
    assert prepare_geonames(folder=tmp_path) == db and db.stat().st_mtime_ns == stamp


def test_better_institution_match_and_manual_override(tmp_path, monkeypatch):
    db = dataset(tmp_path, monkeypatch)
    source = dict(fact("Shared"), source_quote="University research at Shared.")
    result = normalize_locations([source], db)[0]
    assert result["latitude"] == 45 and result["location"] == "ambiguous"
    overridden = normalize_locations([fact("Springfield")], db, {"Springfield": 3})[0]
    assert overridden["latitude"] == 42 and overridden["location"] == "defined"
    assert (
        normalize_locations([fact("Springfield")], db, {"Springfield": None})[0]["location"]
        == "unknown"
    )
    with pytest.raises(ValueError, match="ID missing"):
        normalize_locations([fact("Springfield")], db, {"Springfield": 999})


def test_updates_same_file_and_skips_processed_records(tmp_path, monkeypatch):
    db = dataset(tmp_path, monkeypatch)
    processed = dict(fact("Already resolved"), location="ambiguous", latitude=10, longitude=20)
    original = [fact("E.I."), fact("Unknown Lab"), processed]
    save_experiment("pilot", original, tmp_path)
    result = update_locations("pilot", db, root=tmp_path)
    path = path_for("pilot", tmp_path)
    assert json.loads(path.read_text()) == result == load_experiment("pilot", tmp_path)
    assert result[2] == processed
    assert [f["location"] for f in result] == ["defined", "unknown", "ambiguous"]
    assert [p.name for p in tmp_path.glob("facts_*")] == ["facts_pilot.json"]
    stamp = path.stat().st_mtime_ns
    monkeypatch.setattr(
        "src.geocode.prepare_geonames", lambda *a: pytest.fail("No undefined facts")
    )
    assert update_locations("pilot", root=tmp_path) == result
    assert path.stat().st_mtime_ns == stamp


@pytest.mark.parametrize(
    "status,lat,lon",
    [
        ("defined", None, None),
        ("ambiguous", 40, None),
        ("undefined", 40, -70),
        ("unknown", 40, -70),
        ("defined", 100, -70),
    ],
)
def test_status_and_coordinates_must_agree(status, lat, lon):
    with pytest.raises(ValueError):
        LocationFact.model_validate(
            dict(fact("Test"), location=status, latitude=lat, longitude=lon)
        )

"""Offline GeoNames matching updates undefined locations in the facts file."""

import csv
import hashlib
import io
import json
import re
import sqlite3
import unicodedata
import zipfile
from pathlib import Path

import httpx

from .settings import DATA, OUTPUTS

BASE_URL = "https://download.geonames.org/export/dump/"
GEO = DATA / "geonames"


def name_key(name):
    text = unicodedata.normalize("NFKD", name).casefold().replace(".", "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


def prepare_geonames(country_codes=("US",), folder=GEO):
    """Download once, then build/reuse a local index from frozen country ZIPs."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    sources = {}
    for code in sorted(set(country_codes)):
        if not re.fullmatch(r"[A-Z]{2}", code):
            raise ValueError("GeoNames country codes must be two uppercase letters")
        path = folder / f"{code}.zip"
        if not path.exists():
            with httpx.stream(
                "GET", BASE_URL + path.name, timeout=120, follow_redirects=True
            ) as response:
                response.raise_for_status()
                temporary = path.with_suffix(".part")
                try:
                    with temporary.open("wb") as handle:
                        for block in response.iter_bytes():
                            handle.write(block)
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
        with path.open("rb") as handle:
            sources[code] = {
                "url": BASE_URL + path.name,
                "sha256": hashlib.file_digest(handle, "sha256").hexdigest(),
            }

    if not sources:
        raise ValueError("Select at least one GeoNames country")
    snapshot = json.dumps({"index_version": 3, "sources": sources}, sort_keys=True)
    manifest = folder / "snapshot.json"
    if not manifest.exists() or manifest.read_text() != snapshot + "\n":
        manifest.write_text(snapshot + "\n")
    database = folder / "places.sqlite"
    if database.exists():
        with sqlite3.connect(database) as conn:
            if conn.execute("SELECT snapshot FROM metadata").fetchone()[0] == snapshot:
                return database
    temporary = folder / "places.building.sqlite"
    temporary.unlink(missing_ok=True)
    try:
        with sqlite3.connect(temporary) as conn:
            conn.executescript("""
                CREATE TABLE metadata(snapshot TEXT NOT NULL);
                CREATE TABLE places(id INTEGER PRIMARY KEY, name TEXT, lat REAL, lon REAL,
                    country TEXT, admin TEXT, feature TEXT);
                CREATE TABLE names(name TEXT, id INTEGER, PRIMARY KEY(name,id));
            """)
            conn.execute("INSERT INTO metadata VALUES (?)", (snapshot,))
            for code in sources:
                with zipfile.ZipFile(folder / f"{code}.zip") as archive:
                    with archive.open(f"{code}.txt") as raw:
                        for row in csv.reader(
                            io.TextIOWrapper(raw, encoding="utf-8"), delimiter="\t"
                        ):
                            if row[6] not in {"A", "P", "S"}:
                                continue
                            lat, lon = float(row[4]), float(row[5])
                            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                                raise ValueError("Invalid GeoNames coordinates")
                            conn.execute(
                                "INSERT INTO places VALUES (?,?,?,?,?,?,?)",
                                (
                                    int(row[0]),
                                    row[1],
                                    lat,
                                    lon,
                                    row[8],
                                    row[10],
                                    row[6] + "." + row[7],
                                ),
                            )
                            names = {name_key(n) for n in [row[1], row[2], *row[3].split(",")] if n}
                            conn.executemany(
                                "INSERT OR IGNORE INTO names VALUES (?,?)",
                                [(n, int(row[0])) for n in names],
                            )
        temporary.replace(database)
    finally:
        temporary.unlink(missing_ok=True)
    return database



def embedded_institution(conn, location):
    """Find the longest complete institution alias, then narrow by geographic context."""
    words = name_key(location).split()
    for size in range(len(words) - 1, 1, -1):
        matches = {}
        contexts = []
        for start in range(len(words) - size + 1):
            prefix = " ".join(words[:start])
            # A museum or other distinct site is not interchangeable with its institution.
            if prefix and not re.fullmatch(r"(?:(?:the|at|in|of)\s*)+", prefix) and not re.search(
                r"\b(?:university|institute|laboratory|school|college)\b", prefix
            ):
                continue
            alias = " ".join(words[start:start + size])
            rows = conn.execute(
                """SELECT p.* FROM places p JOIN names n ON p.id=n.id
                   WHERE n.name=? AND p.feature IN ('S.UNIV','S.SCH','S.RSCH')
                   ORDER BY p.id""", (alias,),
            ).fetchall()
            if rows:
                matches.update((row["id"], row) for row in rows)
                contexts.append(words[:start] + words[start + size:])
        if not matches:
            continue
        # Equal-length institution names may describe different places. Retain ambiguity.
        candidates = list(matches.values())
        if len(contexts) != 1:
            return candidates
        context = " ".join(contexts[0])
        context = re.sub(r"\bmass\b", "massachusetts", context)
        context = re.sub(r"\bn h\b", "new hampshire", context)
        tokens = context.split()
        areas = {}
        for length in range(len(tokens), 0, -1):
            for start in range(len(tokens) - length + 1):
                alias = " ".join(tokens[start:start + length])
                # Ignore connectors and very short aliases such as 'in'.
                if len(alias) < 3 or alias in {"the", "and", "at", "of"}:
                    continue
                for row in conn.execute(
                    """SELECT p.* FROM places p JOIN names n ON p.id=n.id
                       WHERE n.name=? AND (p.feature LIKE 'A.%' OR p.feature LIKE 'P.%')""",
                    (alias,),
                ):
                    areas[row["id"]] = row
        def score(candidate):
            return sum(
                area["country"] == candidate["country"]
                and (area["feature"] == "A.PCLI" or area["admin"] == candidate["admin"])
                for area in areas.values()
            )
        best = max(map(score, candidates))
        if areas and not best:
            return []  # Explicit geography conflicts with every candidate.
        return [candidate for candidate in candidates if score(candidate) == best]
    return []


def normalize_locations(facts, database, overrides=None):
    """Resolve undefined/unknown entries; preserve source names and resolved facts."""
    from .facts import LocationFact

    overrides = overrides or {}
    result = []
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        for original in facts:
            fact = LocationFact.model_validate(original).model_dump()
            if fact["location"] not in {"undefined", "unknown"}:
                result.append(fact)
                continue
            location = fact["location_name"]
            parts = re.split(r"(?:['’]s|(?<=s)['’])\s", location, maxsplit=1)
            equipment = len(parts) == 2 and re.search(
                r"\b(?:computer|calculator|analy[sz]er|ENIAC|IBM|machine)\b", parts[1], re.I
            )
            query = parts[0].strip() if equipment else location.strip()
            multiple = bool(
                re.search(r";|,\s+and\s", location, re.I) or re.search(r"\s+and\s", query, re.I)
            )
            candidates = []
            if location in overrides:
                selected_id = overrides[location]
                if selected_id is not None:
                    candidates = conn.execute(
                        "SELECT * FROM places WHERE id=?", (selected_id,)
                    ).fetchall()
                    if not candidates:
                        raise ValueError(f"Reviewed GeoNames ID missing: {selected_id}")
            else:
                queries = (
                    re.split(r";|,\s*(?:and\s+)?|\s+and\s+", location) if multiple else [query]
                )
                seen = set()
                for item in queries:
                    item = re.split(r"(?:['’]s|(?<=s)['’])\s", item, maxsplit=1)[0].strip()
                    for candidate in conn.execute(
                        """SELECT p.* FROM places p JOIN names n ON p.id=n.id
                            WHERE n.name=? ORDER BY p.id""",
                        (name_key(item),),
                    ).fetchall():
                        if candidate["id"] not in seen:
                            seen.add(candidate["id"])
                            candidates.append(candidate)
                if not candidates:
                    candidates = embedded_institution(conn, location)
            if candidates:
                institution = bool(
                    re.search(
                        r"university|institute|laborator|school|college",
                        location + " " + fact["source_quote"],
                        re.I,
                    )
                )

                def score(candidate):
                    institution_match = institution and candidate["feature"] in {
                        "S.UNIV",
                        "S.SCH",
                        "S.RSCH",
                    }
                    return (
                        int(institution_match),
                        int(name_key(candidate["name"]) == name_key(query)),
                    )

                # max retains the first candidate when ranking scores tie.
                selected = max(candidates, key=score)
                fact.update(
                    latitude=selected["lat"],
                    longitude=selected["lon"],
                    location="ambiguous" if len(candidates) > 1 or multiple else "defined",
                )
            else:
                fact.update(location="unknown", latitude=None, longitude=None)
            result.append(LocationFact.model_validate(fact).model_dump())
    return result


def update_locations(name, database=None, country_codes=("US",), overrides=None, root=OUTPUTS):
    """Retry unresolved facts and atomically update the same experiment JSON."""
    from .experiments import load_experiment, save_experiment

    facts = load_experiment(name, root)
    if not any(fact["location"] in {"undefined", "unknown"} for fact in facts):
        return facts
    database = database or prepare_geonames(country_codes)
    updated = normalize_locations(facts, database, overrides)
    if updated != facts:
        save_experiment(name, updated, root, overwrite=True)
    return updated

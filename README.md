# AI breakthroughs from historical books

**Question:** Where did breakthroughs in artificial intelligence happen?

This local proof of concept turns book passages into a table of AI achievements,
locations and years, with quotations reviewers can inspect. A notebook displays facts, a status pie chart and an interactive Folium map after GeoNames matching updates coordinates.

## Run locally

Uses Python 3.12.13, pinned in `.python-version`. Requires [uv](https://docs.astral.sh/uv/)
and Docker Desktop for new experiments.

```sh
uv sync --frozen
test -f .env || cp .env.example .env
# Add OPENAI_API_KEY to .env. Never put keys in notebook cells.
docker compose up -d --wait
uv run jupyter lab notebooks/analysis.ipynb
```

On Apple Silicon Macs, use native ARM Python. If installation selects an Intel/Rosetta
interpreter and fails to install PyTorch, run:

```sh
uv sync --frozen --python cpython-3.12.13-macos-aarch64-none
```

This recreates an incompatible project virtual environment with native ARM Python.
The pinned PyTorch release has no Intel macOS wheel.

BGE-M3 runs locally and downloads its pinned weights on first ingestion (about 2.3 GB).
PostgreSQL/pgvector runs in Docker. BGE-M3 selects available hardware automatically.

For saved results, only Python dependencies and Jupyter are needed. Use experiment name
`ai_breakthrough_locations_experiment_1` to load the included JSON: no Docker, API key,
embedding download or GeoNames download is needed because its locations are already processed.
Map tiles and browser resources still require internet.

For new experiments, configure `.env` and start Docker as shown above.
`QUESTION`, `TOP_K`, `CLASSIFIER_PROMPT`, `CLASSIFIER_MODEL`, `CLASSIFIER_DROP_CONFIDENCE`, `CLASSIFIER_CRITERIA`,
`EXTRACTOR_PROMPT`, `EXTRACTOR_MODEL`, `EXTRACTOR_BATCH_SIZE` and selected books are editable there.
Running the experiment cell loads its JSON if it exists. Otherwise it runs extraction
and saves a new file automatically. No `RUN_EXPERIMENT` flag is needed.
The commented notebook loop prepares `SELECTED_BOOKS` before new experiments. For each
book it calls `book_needs_ingestion`, logs the decision, and calls `ingest(settings, [book])`
only when needed. The database stores filenames in `books.source_path`; changed content
or chunk/embedding settings also trigger refresh. Saved experiments skip this loop.
Existing experiment names load the current saved facts without inference calls.

## Retrieval and filtering

Dense search retrieves up to `TOP_K` chunks per selected book for the single research
question (50 by default). OpenAI Decisions (`gpt-6-luna`) judges whether each passage contains
a potential AI achievement or relevant early-computing milestone. A location is not
required for classification. GPT-5 mini extracts the kept passages and still requires
a source-backed location for each saved fact.
Both use the same OpenAI API key.
Its notebook instructions are separate from the extraction prompt; an explicit year
is optional. Only a `drop` decision at confidence >= 0.8 is discarded; all other
passages go to GPT-5 mini for extraction. This cutoff is provisional, not evaluated.
Extraction sends kept chunks in sequential batches of 10. Change `EXTRACTOR_BATCH_SIZE`
in the notebook to adjust this. Each returned fact identifies its source chunk; Python
checks that ID belongs to the batch, validates quotations against that specific chunk,
and supplies book metadata. Output allowance scales with batch size, capped at 16,000
tokens per request. Truncated responses stop the run without saving partial results.

Choose books with `SELECTED_BOOKS`; `TOP_K` limits candidate chunks per book. The notebook
sets `max_calls=TOP_K * len(SELECTED_BOOKS)`, allowing extraction of every retrieved
candidate without a fixed 150-chunk limit. Batches still contain up to `EXTRACTOR_BATCH_SIZE` chunks.
The notebook prints retrieved, kept, dropped and extracted counts. These are not
quality scores. Classification failure stops the run without saving partial facts.
Existing experiment names skip both hosted models; use a new name to apply changes.
Book embeddings are reused. No keyword search, RRF, or additional result files.

Classification uses [OpenAI Decisions](https://developers.openai.com/api/docs/guides/decisions),
and extraction uses [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
with strict JSON output. Only confident negative decisions are dropped; refusals or
malformed responses stop the run without saving partial facts.

## Output and evidence

Each fact stores:

```json
{
  "year": 1962,
  "breakthrough": "Description of the achievement",
  "location_name": "Source place name",
  "location": "undefined",
  "source_quote": "Exact supporting passage",
  "latitude": null,
  "longitude": null,
  "book_name": "Source title",
  "chunk_id": "127"
}
```

This is a format example, not an extracted historical claim. Python checks quote,
location_name and explicit year, supplies book/chunk metadata, and sets initial location
status to undefined. Missing event years remain null; publication years are never substituted. Each extraction saves one
JSON array; no per-run config sidecar. Literal checks do not establish historical truth.

## Offline location resolution

The additional notebook step calls `update_locations` from `src/geocode.py`. It processes
facts with `location="undefined"` or `location="unknown"` and updates the **same** facts JSON. No run flag,
second export, resolution-report file or extra output name is needed.

| Status | Meaning | Coordinates |
|---|---|---|
| undefined | Not processed yet | null |
| defined | One match, or reviewed override | Filled |
| unknown | No match | null |
| ambiguous | Multiple candidates or places; one selected | Filled |

GeoNames names and alternate names are matched after case/accent/punctuation
normalization and removal of equipment suffixes. If an exact name fails, look for the
longest complete institution name within the text and use city/state/country context
to narrow its matches. Original names remain unchanged. For ambiguous matches, prefer
institutional features when context names an institution, then exact primary names;
equal scores use the first available candidate. Ambiguous points are best guesses,
not verified historical sites. Original source place text remains in `location_name`.

Unknown locations are retried on rerun; defined and ambiguous locations are skipped. `LOCATION_OVERRIDES` can specify a reviewed
GeoNames ID or None. To retry a processed fact, set location to undefined and clear
both coordinates first. No model API is used for this step.

First use downloads selected country ZIPs (US default, approximately 71 MB); matching
then runs offline against a rebuildable SQLite index. Add `GEONAMES_COUNTRIES` codes
for sources outside the US. ZIP snapshots remain local with dataset attribution.

Data © [GeoNames](https://www.geonames.org/), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
See [GeoNames dataset documentation](https://download.geonames.org/export/dump/readme.txt).

## Notebook map

The final cell plots facts with coordinates on a Folium/OpenStreetMap map. Nearby
facts are clustered; click clusters to zoom or expand them, then click dots for year,
achievement, source location, book and status. Defined dots are green; ambiguous dots
are orange. Facts without coordinates are omitted. Map tiles and browser resources
require internet. This view uses existing facts and makes no model/geocoding calls.

The final two notebook sections evaluate geocoding coverage (defined facts divided
by all extracted facts) and provide the map as a geographic sanity check. Coverage
and visual inspection do not establish historical accuracy or extraction recall.

## Repository

```text
notebooks/analysis.ipynb   Editable settings, run/replay, GeoNames results
src/                     Ingest, retrieve, classify, extract, validate and save
data/books/*.txt         Fifteen title-named books
data/results/            Facts JSON arrays updated in place
data/geonames/           Frozen country ZIPs, source metadata and local name index
tests/                   Focused software checks with synthetic evidence
Architecture.md          Components, boundaries and data flow
AGENTS.md                AI coding guidance and disclosure
```

Add UTF-8 books directly to `data/books/` and enable their filenames in the notebook.
They are ingested automatically when starting a new experiment. Book titles come from filenames without `.txt`; no manifest is needed.
See [book sources](docs/sources.md).

## Checks and assessment status

```sh
uv run pytest -q
uv run ruff check src tests
```

Tests cover evidence/date/location checks, null coordinates, deduplication,
classification, retrieval limits, stale book detection, API handling, JSON persistence
and processed-location skipping. They use synthetic data and mock model responses;
they are not a historical gold benchmark.

Baseline evaluation and before/after benchmarking remain **deferred at the user's
request**. Those required assessment deliverables are not complete. No improvement is
claimed. The app supports only the current geographic schema.

Inference uses OpenAI directly: `gpt-6-luna` for Decisions and `gpt-5-mini` for extraction.
Set `OPENAI_API_KEY` in `.env`. Git excludes local credentials, country ZIPs, SQLite
indexes and generated results except the included example experiment.

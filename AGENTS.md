# AI coding guidance and disclosure

Built with OpenAI Codex from the supplied specification and subsequent user instructions.
The user remains responsible for understanding and explaining the submitted project.

- Keep a small, locally runnable proof of concept, below roughly 2,048 code lines.
- Application logic stays in `src/`; notebook holds editable question, prompt and model.
- Current question: Where did breakthroughs in artificial intelligence happen?
- Facts contain year, breakthrough, location_name, location, source_quote, latitude,
  longitude, book_name and chunk_id. location_name preserves source place text;
  location is undefined/defined/unknown/ambiguous. New extractions start undefined.
- Preserve literal evidence. Copy source locations without adding assumed geography.
- Use an explicitly supported event year; otherwise keep year null. Never substitute publication year.
- Keep books intact in `data/books/`. Titles come from filenames; no book manifest.
  Current generated results belong in `data/results/`.
- Keep the commented per-book check/log/ingest loop visible in the notebook for new
  experiments. Database checks and embedding details stay in Python helpers; there
  is no hidden ingestion loop in extraction. Skip unchanged books and saved experiments.
- Existing experiment names load saved facts without database or inference calls. The GeoNames step
  updates undefined and unknown facts in that same JSON file; no second export file.
- Extraction sends sequential batches, with EXTRACTOR_BATCH_SIZE editable in the notebook
  (default 10). Each returned chunk_id must belong to its batch; Python supplies book_name
  and validates evidence against that chunk. Saved fact schema stays unchanged. Output
  allowance scales from 3,000 tokens per chunk to a maximum of 16,000 per request.
- Use dense-only retrieval for a single question: up to TOP_K chunks per selected book.
- OpenAI Decisions (gpt-6-luna) filters candidates before direct GPT-5 mini extraction.
  Notebook holds editable CLASSIFIER_MODEL/PROMPT/CRITERIA/DROP_CONFIDENCE and
  EXTRACTOR_MODEL/PROMPT separately. Decision labels stay keep/drop/uncertain.
  Drop only confident negatives (default 0.8); keep uncertain decisions. No quality claim.
  Classification does not require a location; extraction still requires source-backed place evidence.
- Use local BGE-M3/PostgreSQL and direct OpenAI inference. Read OPENAI_API_KEY from
  `.env`. Keep classifier/extractor model, prompt and criteria editable in notebook.
  Do not reintroduce intermediary provider routing or obsolete credentials.
- Never expose secrets in cells, outputs, logs or configuration. Use `.env`/masked input.
- Notebook evaluation reports geocoding coverage and a visual geographic sanity check.
  These do not measure historical accuracy or extraction recall. No gold benchmark
  has been supplied. Never invent facts or quality scores; software tests are not quality evidence.
- Do not commit, push or publish without user instruction.
- GeoNames matching runs offline after snapshots download. For multiple candidates,
  rank institutional context and exact names; ties use first available candidate.
  Fill ambiguous coordinates and mark ambiguous. Unknown matches retain null coordinates.
- Each extraction saves only a facts JSON. Do not create per-run config sidecars or
  reintroduce settings snapshots and stored extraction diagnostics.

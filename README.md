# Olist SQL agent: text-to-SQL with a local LLM

Ask a question about a database in plain English. A local model (via Ollama) writes SQLite SQL, the agent runs it on a **read-only** connection, reads errors and suspicious results, and retries. It also accepts your own CSV or SQLite files (see "Bring your own data"). The point of this repo is the **measurement**: a fixed question set, strict scoring, and an honest account of what helped, what didn't, and where it still fails.

![demo](docs/demo.gif) <!-- TODO: record a short GIF of `python src\app.py` and save it as docs\demo.gif -->

## Results

Models: `qwen2.5-coder:7b` and `qwen2.5-coder:14b` through Ollama, 8k context, temperature 0, CPU only (16 GB RAM, no GPU). Scored by **execution accuracy**: the returned rows must match a hand-checked gold query. Scoring is strict: extra columns, or numbers returned as text, count as wrong.

| Configuration | Main set (46) | Held-out (15) | SQL crashes (main) | Avg time per question (main / held-out) |
|---|---|---|---|---|
| 7B, one-shot baseline | 33 (71.7%) | 8 (53.3%) | 3 | 10 s / 15 s |
| 7B, + retry loop | 34 (73.9%) | 9 (60.0%) | 1 | 9 s / 12 s |
| 7B, + retry loop + code-side hints | 36 (78.3%) | 10 (66.7%) | 0 | 10 s / 12 s |
| 14B, one-shot baseline | 39 (84.8%) | 9 (60.0%) | 2 | 20 s / 34 s |
| 14B, + retry loop + code-side hints | **41 (89.1%)** | 10 (66.7%) | 0 | 18 s / 22 s |

**Read these numbers with care.** One question is worth about 2 points on the main set and 6.7 points on the held-out set, so differences of 1-3 questions may be noise.

### What helped

- **Code-side hints** (`src/agent_checked.py`). When SQL fails with "no such column", the code tells the model which table that column lives in. When a `col = 'text'` filter matches nothing, the code finds close stored spellings (with `difflib`) and says so. Together with the retry loop, these removed every SQL crash on the main set. They read the database at runtime, so they need no hand-written notes and are not specific to Olist.
- **A bigger model.** With the identical one-shot prompt, the 14B scored 6 questions higher than the 7B on the main set (39 vs 33) and 1 higher on the held-out set (9 vs 8). It is about 2x slower per question on CPU. With the hints on, the 14B's held-out score equals the 7B's (10/15 each), so I cannot say how much of the main-set gain would carry over to new questions.

### What didn't help (kept in the repo)

- **Plain retry loop:** +1 question on the main set. It turns crashes into other failures (it dropped a needed join, or gave up and refused). It cannot fix SQL that runs and returns a plausible but wrong number.
- **Free-form exploration tools** (`src/agent_explore.py`: the model may ask for `VALUES: table.column` or `SAMPLE: table` before answering). On the one question I tried, the 7B used the tools and then refused an answerable question, even after I added a prompt rule and a challenge message. I did not run a full evaluation of this agent, so this is an observation, not a measured result. Moving the checking into code (the hints above) worked where asking the model to explore did not.
- **"Return only the asked-for columns" prompt rule** (`USE_SHAPE=1`): 35/46 vs 36/46 on the main set, no change on the held-out set, and it made the model answer one more question it should have refused.
- **Hand-written schema notes** (`data/schema_notes.txt`, `USE_NOTES=1`): implemented but never evaluated. I decided that a tool needing a human-written data dictionary for every new database defeats the goal.

## Where it still fails

Analysis of the 7B one-shot baseline (13 of 46 questions failed), checked by hand against the gold queries. None of the gold queries turned out to be wrong.

- **A misleading schema.** `customers.customer_id` is generated per order; `customer_unique_id` identifies the person. The model counts orders when asked for people. The hints cannot catch this, because the query runs and returns a plausible number.
- **Misread meaning.** Summing `order_item_id` (it is a line number, not a quantity) instead of counting rows; counting item rows instead of distinct orders; using `payment_installments > 1` for "more than one payment type".
- **Wrong column location and guessed values.** Asking `products` for an English category name that lives in the translation table; writing `'perfumary'` instead of `'perfumery'`. The code-side hints fixed these.
- **Invented data.** "Profit margin" and "cost of goods sold" get an answer built from freight value, although the database has no cost data. Both appear in the failures of every configuration I looked at.
- **Output shape.** Correct logic, but an extra column or `'11'` instead of `11`. The strict scorer counts these as wrong (3 questions). I report this rather than loosening the scorer after seeing the failures.
- **An unexplained refusal.** The 7B refused "How many unique customers live in the state of RJ?" in every configuration. I have not diagnosed why.

<!-- TODO: add 2-3 lines on what the 14B still gets wrong, after running:
     python eval\show_failures.py eval\results\checked_qwen-sql14.json -->

## Limitations

- **Small eval set.** 46 main questions plus 15 held-out. The code-side hints were designed after seeing failures on the main set, so main-set gains are flattered. The held-out questions use the same database and were also written after seeing those failures, so they are "held out from the hints", not independent.
- **Only one database is measured at scale.** All the numbers in the results table are on Olist. The upload feature (below) was tried on one other dataset with a handful of questions, which shows it can work on new data but is too small to give a reliable accuracy figure.
- **Gold queries** were drafted with an AI assistant and verified by me against the data. Some questions may still be ambiguous (ties, "most" by rows vs by orders).
- **Local models only.** Results are for the named Qwen models. A stronger hosted model would likely score higher; I did not measure one.

## Bring your own data

The demo (`python src\app.py`) can also answer questions about your own data. Open **Use your own data**, upload up to 10 CSV files (50 MB each) or one SQLite file, and click **Load my data**. No hand-written notes are needed.

How it works (`src/schema_tools.py`):
- CSVs are loaded into a temporary SQLite file, with column names cleaned up and duplicates made unique. A single `.db` file is used as it is.
- The schema description is generated from the data: row counts, column types, NULL counts, a few sample values per column, declared foreign keys if there are any, and a list of column names shared between tables (likely join keys). If the description gets too long for the model's context, the sample values are dropped.
- The same agent, safety layer and code-side hints run on the upload. Queries use the read-only connection, so uploaded data can't be modified.

**What I tested.** I tried it on one other dataset: **[TODO: dataset name, number of tables, license]**, with **[TODO: N]** questions whose answers I worked out by hand from the CSVs before asking. Result: **[TODO: X of N correct]** with `[TODO: model name]`. **[TODO: 1-2 sentences on what failed, e.g. wrong join, double counting, a question that should have been refused.]**

**Limits, stated plainly:**
- This is a small test, not a benchmark. It shows the pipeline works on data it was not built for. It does not give a reliable accuracy number.
- CSVs have no declared keys, so the agent guesses joins from matching column names. Tables whose keys have different names, or columns whose meaning is not obvious from the name (like Olist's `customer_id`), are where I'd expect it to fail.
- Your files stay on your machine, but the schema, including a few sample values per column, is sent to whatever server `LLM_BASE_URL` points at. With local Ollama that is your own computer.
- Not supported: schema-only upload (without data there is nothing to run), and a mix of CSV and SQLite files.

## Safety

Read-only SQLite connection (`mode=ro`), `SELECT`/`WITH` only, a single statement, a 200-row cap and a 10 s timeout (`src/db.py`, covered by tests).

## Run it

Windows Command Prompt syntax; paths and `set` differ on macOS/Linux (use `export VAR=value` and `source .venv/bin/activate`).

```bat
git clone https://github.com/<your-username>/<your-repo>
cd <your-repo>
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

1. Download the [Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) from Kaggle into `data\raw\`. License: **TODO: copy the license line from the Kaggle page.** The raw files are not committed.
2. Build the database and the schema description:
   ```bat
   python src\build_db.py
   python src\describe_schema.py
   ```
3. Create the model (8k context, temperature 0) and set the environment:
   ```bat
   ollama pull qwen2.5-coder:7b
   ollama create qwen-sql -f Modelfile
   set LLM_BASE_URL=http://localhost:11434/v1
   set LLM_API_KEY=ollama
   set LLM_MODEL=qwen-sql
   ```
   For the 14B comparison, use `Modelfile14` and `qwen-sql14` the same way.
4. Launch the demo, run the evals, or run the tests:
   ```bat
   python src\app.py
   python eval\run_eval.py --checked
   python eval\run_eval.py --checked --questions eval\heldout.json
   python eval\summary.py
   python -m pytest -q
   ```

The first question is slow because the model loads into memory. After that, expect roughly 5-35 s per question on CPU, depending on the model.

Any OpenAI-compatible server works: the code only reads `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL`.

## Layout

- `src/`: `db.py` (safe query runner), `baseline.py` (one-shot), `agent.py` (retry loop), `agent_checked.py` (retry loop + hints), `agent_explore.py` (negative result), `schema_tools.py` (upload loading and schema generation), `app.py` (Gradio demo), `build_db.py`, `describe_schema.py`
- `eval/`: `questions.json`, `heldout.json`, `run_eval.py`, `show_failures.py`, `summary.py`, `results/` (every run's per-question output)
- `tests/`: safety-layer, scoring and upload tests
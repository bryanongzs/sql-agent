r"""Gradio demo. Run from the project root:  python src\app.py

Uses the checked agent (retry loop + code-side hints). Needs Ollama running.
Ask about the built-in Olist database, or upload your own CSV / SQLite files.
"""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("LLM_BASE_URL", "http://localhost:11434/v1")
os.environ.setdefault("LLM_API_KEY", "ollama")
os.environ.setdefault("LLM_MODEL", "qwen-sql")

import gradio as gr  # noqa: E402
import pandas as pd  # noqa: E402

from agent_checked import run_agent  # noqa: E402
from db import DB_PATH, MAX_ROWS, QueryError, run_query  # noqa: E402
from schema_tools import describe_schema, load_uploads  # noqa: E402

EXAMPLES = [
    "How many orders were placed in November 2017?",
    "Which three states have the most sellers?",
    "How many products are in the category 'perfumery' (English category name)?",
    "Delete all orders that were canceled.",
]
OLIST_MSG = "Using the built-in Olist database."


def _paths(files) -> list:
    return [Path(f if isinstance(f, str) else f.name) for f in files]


def on_upload(files):
    if not files:
        return None, "Choose one or more CSV files (or one SQLite file) first."
    try:
        out = Path(tempfile.mkdtemp(prefix="sqlagent_"))
        db_path, report = load_uploads(_paths(files), out)
        schema = describe_schema(db_path)
    except Exception as e:
        return None, f"Could not load the files: {e}"
    msg = "**Loaded your data.** Questions now run against it.\n\n" + "\n".join(f"- {r}" for r in report)
    msg += f"\n\nSchema description: {len(schema):,} characters."
    if len(schema) > 12000:
        msg += " This is large, so a small model's context window may cut part of it off."
    return {"db_path": str(db_path), "schema": schema}, msg


def on_reset():
    return None, OLIST_MSG


def ask(question: str, session):
    question = (question or "").strip()
    if not question:
        return "Type a question first.", "", None
    if session:
        db_path, schema, label = session["db_path"], session["schema"], "your upload"
    else:
        if not DB_PATH.exists():
            return ("No database loaded. Upload files below, or build the Olist "
                    "database (see the README).", "", None)
        db_path, schema, label = None, None, "Olist"
    try:
        pred = run_agent(question, db_path=db_path, schema=schema)
    except Exception as e:  # model not running, wrong env vars, etc.
        return f"Could not get an answer from the model: {e}", "", None

    steps = pred.get("steps", 1)
    if pred["kind"] == "refuse":
        return f"**Refused** after {steps} step(s): {pred['reason']}", "", None

    sql = pred["sql"]
    try:
        res = run_query(sql, db_path=db_path)
    except QueryError as e:
        return f"The final query still failed after {steps} step(s): {e}", sql, None

    df = pd.DataFrame(res["rows"], columns=res["columns"])
    note = f"{len(df)} row(s), {steps} step(s), database: {label}, model `{os.environ['LLM_MODEL']}`"
    if res["truncated"]:
        note += f" (showing the first {MAX_ROWS} rows)"
    return note, sql, df


with gr.Blocks(title="SQL agent") as demo:
    session = gr.State(None)
    gr.Markdown(
        "# SQL agent\nAsk a question in plain English. The agent writes SQL, runs it on a "
        "read-only copy of the database, and retries on errors. A small local model can be "
        "wrong: always check the SQL."
    )
    with gr.Accordion("Use your own data (optional)", open=False):
        gr.Markdown(
            "Upload CSV files (up to 10, 50 MB each) or one SQLite file. CSVs are loaded into a "
            "temporary local database; the agent guesses joins from matching column names. "
            "Your files stay on this machine, but the schema, including a few sample values "
            "per column, is sent to the model at `LLM_BASE_URL`."
        )
        files = gr.File(label="Files", file_count="multiple",
                        file_types=[".csv", ".db", ".sqlite", ".sqlite3"])
        with gr.Row():
            load_btn = gr.Button("Load my data")
            reset_btn = gr.Button("Back to Olist")
        upload_status = gr.Markdown(OLIST_MSG)
    question = gr.Textbox(label="Question", lines=2)
    button = gr.Button("Ask", variant="primary")
    status = gr.Markdown()
    sql_box = gr.Code(language="sql", label="SQL")
    table = gr.Dataframe(label="Result")
    gr.Examples(examples=EXAMPLES, inputs=question, label="Examples (for the Olist database)")

    load_btn.click(on_upload, files, [session, upload_status])
    reset_btn.click(on_reset, None, [session, upload_status])
    button.click(ask, [question, session], [status, sql_box, table])
    question.submit(ask, [question, session], [status, sql_box, table])

if __name__ == "__main__":
    demo.launch()
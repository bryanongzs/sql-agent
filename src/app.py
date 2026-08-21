r"""Gradio demo. Run from the project root:  python src\app.py

Uses the checked agent (retry loop + code-side hints). Needs Ollama running.
"""
import os

os.environ.setdefault("LLM_BASE_URL", "http://localhost:11434/v1")
os.environ.setdefault("LLM_API_KEY", "ollama")
os.environ.setdefault("LLM_MODEL", "qwen-sql")

import gradio as gr  # noqa: E402
import pandas as pd  # noqa: E402

from agent_checked import run_agent  # noqa: E402
from db import MAX_ROWS, QueryError, run_query  # noqa: E402

EXAMPLES = [
    "How many orders were placed in November 2017?",
    "Which three states have the most sellers?",
    "How many products are in the category 'perfumery' (English category name)?",
    "What is the average review score for delivered orders that arrived late?",
    "Delete all orders that were canceled.",
]


def ask(question: str):
    question = (question or "").strip()
    if not question:
        return "Type a question first.", "", None
    try:
        pred = run_agent(question)
    except Exception as e:  # model not running, wrong env vars, etc.
        return f"Could not get an answer from the model: {e}", "", None

    steps = pred.get("steps", 1)
    if pred["kind"] == "refuse":
        return f"**Refused** after {steps} step(s): {pred['reason']}", "", None

    sql = pred["sql"]
    try:
        res = run_query(sql)
    except QueryError as e:
        return f"The final query still failed after {steps} step(s): {e}", sql, None

    df = pd.DataFrame(res["rows"], columns=res["columns"])
    note = f"{len(df)} row(s), {steps} step(s), model `{os.environ['LLM_MODEL']}`"
    if res["truncated"]:
        note += f" (showing the first {MAX_ROWS} rows)"
    return note, sql, df


with gr.Blocks(title="Olist SQL agent") as demo:
    gr.Markdown(
        "# Olist SQL agent\nAsk a question in plain English. The agent writes SQL, "
        "runs it on a read-only copy of the database, and retries on errors. "
        "A small local model can be wrong: always check the SQL."
    )
    question = gr.Textbox(label="Question", lines=2)
    button = gr.Button("Ask", variant="primary")
    status = gr.Markdown()
    sql_box = gr.Code(language="sql", label="SQL")
    table = gr.Dataframe(label="Result")
    gr.Examples(examples=EXAMPLES, inputs=question)
    button.click(ask, question, [status, sql_box, table])
    question.submit(ask, question, [status, sql_box, table])

if __name__ == "__main__":
    demo.launch()
r"""One-shot text-to-SQL: question in, SQL (or a refusal) out. No retries.

Quick test from the project root:
    python src\baseline.py "How many orders are there?"
Switches (environment variables, off by default):
    USE_NOTES=1  append data\schema_notes.txt to the Olist prompt
    USE_SHAPE=1  add the "return only the asked-for columns" rule
"""
import os
import re
import sys
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "data" / "schema.txt"
SCHEMA = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""

USE_NOTES = os.environ.get("USE_NOTES") == "1"
USE_SHAPE = os.environ.get("USE_SHAPE") == "1"
NOTES = ""
if USE_NOTES:
    NOTES = (ROOT / "data" / "schema_notes.txt").read_text(encoding="utf-8")
SHAPE_RULE = ("\n\nOUTPUT SHAPE:\nReturn only the columns the question asks for, with no "
              "extra count or total columns. Return numbers as numbers, not text.")

HEADER = (
    "You are a data analyst. Write one SQLite query that answers the user's "
    "question about the database described below.\n\n"
    "Rules:\n"
    "- Output only the SQL query, nothing else.\n"
    "- Write a single SELECT statement.\n"
    "- If the question cannot be answered from this database, or asks to change "
    "data, reply exactly: REFUSE: <short reason>\n\n"
    "DATABASE SCHEMA:\n"
)


def build_system_prompt(schema: str, notes: str = "") -> str:
    return (HEADER + schema
            + (("\n\nNOTES ABOUT THE DATA:\n" + notes) if notes else "")
            + (SHAPE_RULE if USE_SHAPE else ""))


# The default prompt (Olist). Identical to the one used for all reported results.
SYSTEM_PROMPT = build_system_prompt(SCHEMA, NOTES if USE_NOTES else "")


def get_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        timeout=900,
    )


def parse_reply(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    if text.upper().startswith("REFUSE"):
        return {"kind": "refuse", "sql": None, "reason": text, "raw": text}
    return {"kind": "sql", "sql": text, "reason": None, "raw": text}


def generate(question: str, schema=None) -> dict:
    prompt = build_system_prompt(schema) if schema is not None else SYSTEM_PROMPT
    resp = get_client().chat.completions.create(
        model=os.environ["LLM_MODEL"],
        temperature=0,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": question},
        ],
    )
    return parse_reply(resp.choices[0].message.content)


if __name__ == "__main__":
    print(f"Schema: {len(SCHEMA):,} chars; notes {'ON' if USE_NOTES else 'off'}; "
          f"shape {'ON' if USE_SHAPE else 'off'}")
    q = " ".join(sys.argv[1:]) or "How many orders are there?"
    print(generate(q))
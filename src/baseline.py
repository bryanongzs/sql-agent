"""One-shot text-to-SQL: question in, SQL (or a refusal) out. No retries.

Quick test from the project root:
    python src\baseline.py "How many orders are there?"
"""
import os
import re
import sys
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / "data" / "schema.txt").read_text(encoding="utf-8")

SYSTEM_PROMPT = (
    "You are a data analyst. Write one SQLite query that answers the user's "
    "question about the database described below.\n\n"
    "Rules:\n"
    "- Output only the SQL query, nothing else.\n"
    "- Write a single SELECT statement.\n"
    "- If the question cannot be answered from this database, or asks to change "
    "data, reply exactly: REFUSE: <short reason>\n\n"
    "DATABASE SCHEMA:\n" + SCHEMA
)


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


def generate(question: str) -> dict:
    resp = get_client().chat.completions.create(
        model=os.environ["LLM_MODEL"],
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
    )
    return parse_reply(resp.choices[0].message.content)


if __name__ == "__main__":
    print(f"Schema is {len(SCHEMA):,} characters")
    q = " ".join(sys.argv[1:]) or "How many orders are there?"
    print(generate(q))
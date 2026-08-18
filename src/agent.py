r"""SQL agent: write SQL, run it, read errors/empty results, retry (max 4 steps).

Quick test from the project root:
    python src\agent.py "How many products are in the category 'perfumery'?"
"""
import os
import sys

from baseline import SYSTEM_PROMPT, get_client, parse_reply
from db import QueryError, run_query

MAX_STEPS = 4


def run_agent(question: str, max_steps: int = MAX_STEPS) -> dict:
    client = get_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    last_sql = None
    for step in range(1, max_steps + 1):
        resp = client.chat.completions.create(
            model=os.environ["LLM_MODEL"], temperature=0, messages=messages)
        raw = resp.choices[0].message.content
        pred = parse_reply(raw)
        if pred["kind"] == "refuse":
            return {**pred, "steps": step}

        last_sql = pred["sql"]
        messages.append({"role": "assistant", "content": raw})
        try:
            result = run_query(last_sql)
        except QueryError as e:
            feedback = (f"That query failed with this error: {e}\n"
                        "Check the schema for the correct table and column names. "
                        "Reply with only the corrected SQL query.")
        else:
            if result["rows"]:
                return {**pred, "steps": step}
            feedback = ("That query ran but returned no rows. Check your filters, "
                        "values, and joins against the schema. Reply with only the "
                        "corrected SQL query, or REFUSE: <reason> if the data "
                        "cannot answer the question.")
        messages.append({"role": "user", "content": feedback})

    return {"kind": "sql", "sql": last_sql, "reason": None, "raw": last_sql, "steps": max_steps}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "How many orders are there?"
    print(run_agent(q))
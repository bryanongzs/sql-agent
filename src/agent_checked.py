r"""SQL agent with code-side checks: retry loop + smarter error hints + value check.

Quick test from the project root:
    python src\agent_checked.py "How many products are in the category 'perfumery' (English category name)?"
Pass db_path and schema to run_agent() to use a different database.
"""
import difflib
import os
import re
import sys

from baseline import SYSTEM_PROMPT, build_system_prompt, get_client, parse_reply
from db import QueryError, run_query

MAX_STEPS = 4
LIT_RE = re.compile(r"(?:\w+\.)?(\w+)\s*=\s*'([^']*)'")


def _q(name: str) -> str:
    return name.replace('"', '""')


def _tables(db) -> list:
    sql = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    return [r[0] for r in run_query(sql, db_path=db)["rows"]]


def _columns(table: str, db) -> list:
    sql = f"SELECT name FROM pragma_table_info('{table.replace(chr(39), chr(39) * 2)}')"
    return [r[0] for r in run_query(sql, db_path=db)["rows"]]


def _owners(col: str, db) -> list:
    return [t for t in _tables(db) if col in _columns(t, db)]


def error_hint(msg: str, db=None) -> str:
    try:
        m = re.search(r"no such column: (?:\w+\.)?(\w+)", msg)
        if m:
            col = m.group(1)
            owners = _owners(col, db)
            if owners:
                return (f"Hint: the column '{col}' is not in the table you used it with. "
                        f"It exists in: {', '.join(owners)}. Join that table.")
            return f"Hint: no table has a column named '{col}'. Check the schema."
        if "no such table" in msg:
            return f"Hint: the tables are: {', '.join(_tables(db))}."
    except QueryError:
        pass
    return ""


def value_hint(sql: str, db=None) -> str:
    """If a filter like col = 'text' matches nothing but a close value exists, say so."""
    for col, lit in LIT_RE.findall(sql):
        try:
            owners = _owners(col, db)
            if not owners:
                continue
            if any(run_query(f'SELECT 1 FROM "{_q(t)}" WHERE "{_q(col)}" = \'{lit}\' LIMIT 1',
                             db_path=db)["rows"] for t in owners):
                continue
            pool = []
            for t in owners:
                pool += [str(r[0]) for r in run_query(
                    f'SELECT DISTINCT "{_q(col)}" FROM "{_q(t)}" '
                    f'WHERE "{_q(col)}" IS NOT NULL LIMIT 5000', db_path=db)["rows"]]
        except QueryError:
            continue
        close = difflib.get_close_matches(lit, pool, n=3, cutoff=0.8)
        if close:
            return (f"Hint: the value '{lit}' does not exist in column '{col}'. "
                    f"Closest stored values: {', '.join(close)}.")
    return ""


def run_agent(question: str, max_steps: int = MAX_STEPS, db_path=None, schema=None) -> dict:
    client = get_client()
    prompt = build_system_prompt(schema) if schema is not None else SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": question},
    ]
    last_sql = None
    for step in range(1, max_steps + 1):
        resp = client.chat.completions.create(
            model=os.environ["LLM_MODEL"], temperature=0, messages=messages)
        raw = resp.choices[0].message.content
        if os.environ.get("AGENT_DEBUG"):
            print(f"[step {step}] {raw}\n")
        pred = parse_reply(raw)
        if pred["kind"] == "refuse":
            return {**pred, "steps": step}

        last_sql = pred["sql"]
        messages.append({"role": "assistant", "content": raw})
        try:
            result = run_query(last_sql, db_path=db_path)
        except QueryError as e:
            feedback = (f"That query failed with this error: {e}\n{error_hint(str(e), db_path)}\n"
                        "Reply with only the corrected SQL query.")
        else:
            hint = value_hint(last_sql, db_path)
            if hint:
                feedback = f"The query ran, but: {hint}\nReply with only the corrected SQL query."
            elif not result["rows"]:
                feedback = ("That query ran but returned no rows. Check your filters, values "
                            "and joins against the schema. Reply with only the corrected SQL "
                            "query, or REFUSE: <reason> if the data cannot answer the question.")
            else:
                return {**pred, "steps": step}
        if step == max_steps:
            break
        messages.append({"role": "user", "content": feedback})

    return {"kind": "sql", "sql": last_sql, "reason": None, "raw": last_sql, "steps": max_steps}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "How many orders are there?"
    print(run_agent(q))
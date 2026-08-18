r"""SQL agent that can explore the database before answering.

Replies the model can send:  SQL | REFUSE: reason | VALUES: table.column [~ text]
| SAMPLE: table. Errors and empty results are fed back, as in agent.py.

Quick test from the project root:
    python src\agent_explore.py "How many products are in the category 'perfumery'?"
"""
import os
import re
import sys

from baseline import SYSTEM_PROMPT, get_client, parse_reply
from db import QueryError, run_query

MAX_STEPS = 6
MAX_VALUES = 40
CELL = 40

TOOL_RULES = """

EXPLORING THE DATABASE:
Exception to "output only the SQL query": before writing the final query you may
explore, by replying with exactly one line in one of these formats:
  VALUES: table.column            -> shows the most common values of that column with counts
  VALUES: table.column ~ text     -> same, but only values containing that text
  SAMPLE: table                   -> shows 3 example rows of that table
Use VALUES before filtering on a text value, so you use the exact spelling stored
in the data. Use SAMPLE if you are unsure what a column or ID means. Explore only
when it helps; when you are ready, reply with only the SQL query.

Before replying REFUSE, check every table in the schema, not just the one you sampled.
A sample of one table does not show the whole database: if another table could hold
what you need (for example a translation or lookup table), join it. Reply REFUSE only
when no table in the schema could answer the question, or when it asks to change data."""

PROMPT = SYSTEM_PROMPT + TOOL_RULES

CHALLENGE = ("Re-read your own reason for refusing. If it says another table, a join, "
             "or a different column would supply what is missing, then the database CAN "
             "answer the question: write the SQL query. Reply REFUSE again only if no "
             "table could answer it, or if the request is to change data. "
             "Reply with only the SQL query, or REFUSE: <reason>.")

EXPLORE_RE = re.compile(r"(?is)^\s*(?:```\w*\s*)?(VALUES|SAMPLE)\s*:\s*([^\n]+)")
TARGET_RE = re.compile(r"^([A-Za-z_]\w*)\.([A-Za-z_]\w*)(?:\s*~\s*(.+))?$")


def _tables() -> list:
    return [r[0] for r in run_query("SELECT name FROM sqlite_master WHERE type='table'")["rows"]]


def _columns(table: str) -> list:
    return [r[0] for r in run_query(f'SELECT name FROM pragma_table_info("{table}")')["rows"]]


def _cell(v) -> str:
    return str(v)[:CELL]


def explore(kind: str, arg: str) -> str:
    arg = arg.strip().strip("`").strip()
    try:
        tables = _tables()
        if kind == "SAMPLE":
            if arg not in tables:
                return f"Unknown table '{arg}'. Tables: {', '.join(tables)}"
            res = run_query(f'SELECT * FROM "{arg}" LIMIT 3')
            lines = [" | ".join(res["columns"])]
            lines += [" | ".join(_cell(v) for v in row) for row in res["rows"]]
            return "\n".join(lines)

        m = TARGET_RE.match(arg)
        if not m:
            return "Use the format  VALUES: table.column  or  VALUES: table.column ~ text"
        table, col, needle = m.group(1), m.group(2), m.group(3)
        if table not in tables:
            return f"Unknown table '{table}'. Tables: {', '.join(tables)}"
        if col not in _columns(table):
            return f"Table '{table}' has no column '{col}'. Its columns: {', '.join(_columns(table))}"
        where = ""
        if needle:
            safe = needle.strip().strip("'\"").replace("'", "''")
            where = f" WHERE \"{col}\" LIKE '%{safe}%'"
        res = run_query(f'SELECT "{col}", COUNT(*) FROM "{table}"{where} '
                        f'GROUP BY "{col}" ORDER BY 2 DESC LIMIT {MAX_VALUES}')
        if not res["rows"]:
            return "No matching values."
        lines = [f"Most common values of {table}.{col} (up to {MAX_VALUES}):"]
        lines += [f"{_cell(v)}  ({n})" for v, n in res["rows"]]
        return "\n".join(lines)
    except QueryError as e:
        return f"Exploration failed: {e}"


def run_agent(question: str, max_steps: int = MAX_STEPS) -> dict:
    client = get_client()
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": question},
    ]
    last_sql = None
    challenged = False
    for step in range(1, max_steps + 1):
        resp = client.chat.completions.create(
            model=os.environ["LLM_MODEL"], temperature=0, messages=messages)
        raw = resp.choices[0].message.content
        if os.environ.get("AGENT_DEBUG"):
            print(f"[step {step}] {raw}\n")
        messages.append({"role": "assistant", "content": raw})
        last_step_next = step + 1 == max_steps
        tail = (" This is your last step: reply with only the SQL query, or REFUSE: <reason>."
                if last_step_next else "")

        m = EXPLORE_RE.match(raw)
        if m and step < max_steps:
            result = explore(m.group(1).upper(), m.group(2))
            messages.append({"role": "user", "content":
                             f"Result:\n{result}\n\nNow explore more or reply with only the SQL query." + tail})
            continue

        pred = parse_reply(raw)
        if pred["kind"] == "refuse":
            if not challenged and step < max_steps:
                challenged = True
                messages.append({"role": "user", "content": CHALLENGE + tail})
                continue
            return {**pred, "steps": step}
        if m:  # asked to explore on the final step
            break

        last_sql = pred["sql"]
        try:
            result = run_query(last_sql)
        except QueryError as e:
            feedback = (f"That query failed with this error: {e}\n"
                        "Check the schema for the correct table and column names, "
                        "or explore. Reply with only the corrected SQL query." + tail)
        else:
            if result["rows"]:
                return {**pred, "steps": step}
            feedback = ("That query ran but returned no rows. Check your filters, values "
                        "and joins; you can explore with VALUES or SAMPLE. Reply with "
                        "only the corrected SQL query, or REFUSE: <reason> if the data "
                        "cannot answer the question." + tail)
        messages.append({"role": "user", "content": feedback})

    if last_sql is None:
        return {"kind": "refuse", "sql": None, "reason": "ran out of steps",
                "raw": "REFUSE: ran out of steps while exploring", "steps": max_steps}
    return {"kind": "sql", "sql": last_sql, "reason": None, "raw": last_sql, "steps": max_steps}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "How many orders are there?"
    print(run_agent(q))
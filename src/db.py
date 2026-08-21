r"""Safe query execution against a SQLite database.

Safety: read-only connection, SELECT/WITH only, row cap, time limit.
db_path defaults to the Olist database; pass another path for uploaded data.
"""
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "olist.db"

MAX_ROWS = 200
TIMEOUT_SECONDS = 10


class QueryError(Exception):
    """Raised when a query is rejected or fails. The message goes back to the agent."""


def connect_ro(db_path=None) -> sqlite3.Connection:
    """Open a read-only connection. mode=ro means even a sneaky write fails."""
    path = Path(db_path) if db_path else DB_PATH
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def run_query(sql: str, max_rows: int = MAX_ROWS, timeout: float = TIMEOUT_SECONDS,
              db_path=None) -> dict:
    cleaned = sql.strip().rstrip(";").strip()
    first_word = cleaned.split(None, 1)[0].upper() if cleaned else ""
    if first_word not in ("SELECT", "WITH"):
        raise QueryError("Only SELECT queries are allowed.")
    if ";" in cleaned:
        raise QueryError("Only a single statement is allowed.")

    conn = connect_ro(db_path)
    deadline = time.monotonic() + timeout
    # returning 1 from the handler aborts the running query
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 100_000)
    try:
        cur = conn.execute(cleaned)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(max_rows + 1)
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            raise QueryError(f"Query exceeded the {timeout}s time limit.") from e
        raise QueryError(str(e)) from e
    except sqlite3.Error as e:
        raise QueryError(str(e)) from e
    finally:
        conn.close()

    truncated = len(rows) > max_rows
    return {"columns": columns, "rows": rows[:max_rows], "truncated": truncated}


if __name__ == "__main__":
    print(run_query("SELECT COUNT(*) AS n FROM orders"))
    for bad in ["DROP TABLE orders", "SELECT 1; DELETE FROM orders", "SELECT * FROM nope"]:
        try:
            run_query(bad)
        except QueryError as e:
            print(f"Rejected: {bad!r} -> {e}")
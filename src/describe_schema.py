"""Print a schema description (tables, columns, sample values, shared keys)
and save it to data/schema.txt for use in the LLM prompt.

Run from the project root:  python src\describe_schema.py
"""
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "olist.db"
OUT_PATH = ROOT / "data" / "schema.txt"


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    lines = []
    key_cols = defaultdict(list)

    for t in tables:
        n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        lines.append(f"TABLE {t} ({n:,} rows)")
        for _, col, ctype, *_ in conn.execute(f'PRAGMA table_info("{t}")'):
            distinct = conn.execute(
                f'SELECT COUNT(DISTINCT "{col}") FROM "{t}"').fetchone()[0]
            nulls = conn.execute(
                f'SELECT COUNT(*) FROM "{t}" WHERE "{col}" IS NULL').fetchone()[0]
            if distinct <= 12:
                vals = [str(r[0]) for r in conn.execute(
                    f'SELECT DISTINCT "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL LIMIT 12')]
                sample = "values: " + ", ".join(vals)
            else:
                vals = [str(r[0]) for r in conn.execute(
                    f'SELECT "{col}" FROM "{t}" WHERE "{col}" IS NOT NULL LIMIT 2')]
                sample = "e.g. " + ", ".join(vals)
            null_note = f", {nulls:,} NULLs" if nulls else ""
            lines.append(f"  - {col} ({ctype}){null_note}  [{sample}]")
            if col.endswith("_id") or col.endswith("_prefix") or col.endswith("_name"):
                key_cols[col].append(t)
        lines.append("")

    lines.append("SHARED COLUMNS (likely join keys):")
    for col, ts in sorted(key_cols.items()):
        if len(ts) > 1:
            lines.append(f"  {col}: {', '.join(ts)}")

    text = "\n".join(lines)
    OUT_PATH.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nSaved to {OUT_PATH}")
    conn.close()


if __name__ == "__main__":
    main()
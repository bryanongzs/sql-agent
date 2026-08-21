r"""Load uploaded CSV/SQLite files into a temporary database and describe its schema."""
import re
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path

import pandas as pd

from db import connect_ro

MAX_FILES = 10
MAX_MB = 50
CSV_EXT = (".csv",)
SQLITE_EXT = (".db", ".sqlite", ".sqlite3")


def _ident(name, fallback: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip()).strip("_").lower()
    if not s:
        s = fallback
    if s[0].isdigit():
        s = "n_" + s
    if s.startswith("sqlite"):
        s = "t_" + s
    return s


def _unique(names: list) -> list:
    seen, out = set(), []
    for n in names:
        cand, k = n, 2
        while cand in seen:
            cand, k = f"{n}_{k}", k + 1
        seen.add(cand)
        out.append(cand)
    return out


def _free(name: str, used: set) -> str:
    cand, k = name, 2
    while cand in used:
        cand, k = f"{name}_{k}", k + 1
    return cand


def _read_csv(p: Path):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(p, encoding=enc)
            if df.shape[1] == 1:  # maybe a ; or tab delimited file
                alt = pd.read_csv(p, encoding=enc, sep=None, engine="python")
                if alt.shape[1] > 1:
                    df = alt
            return df
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError:
            return None
        except pd.errors.ParserError as e:
            raise ValueError(f"Could not parse {p.name}: {e}") from e
    raise ValueError(f"Could not read {p.name} (unknown text encoding).")


def load_uploads(paths, out_dir):
    """Build out_dir/upload.db from CSV files, or copy a single SQLite file.
    Returns (db_path, report_lines). Raises ValueError with a readable message."""
    paths = [Path(p) for p in paths]
    if not paths:
        raise ValueError("No files given.")
    if len(paths) > MAX_FILES:
        raise ValueError(f"Too many files (max {MAX_FILES}).")
    for p in paths:
        if p.suffix.lower() not in CSV_EXT + SQLITE_EXT:
            raise ValueError(f"Unsupported file type: {p.name} (use .csv, .db, .sqlite or .sqlite3).")
        if p.stat().st_size > MAX_MB * 1024 * 1024:
            raise ValueError(f"{p.name} is larger than {MAX_MB} MB.")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "upload.db"

    sqlite_files = [p for p in paths if p.suffix.lower() in SQLITE_EXT]
    if sqlite_files:
        if len(paths) != 1:
            raise ValueError("Upload either one SQLite file or CSV files, not a mix.")
        shutil.copyfile(sqlite_files[0], db_path)
        try:
            conn = connect_ro(db_path)
            n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            conn.close()
        except sqlite3.Error as e:
            raise ValueError(f"That is not a readable SQLite file: {e}") from e
        if n == 0:
            raise ValueError("The SQLite file has no tables.")
        return db_path, [f"Copied {sqlite_files[0].name} ({n} tables)."]

    conn = sqlite3.connect(db_path)
    used, report = set(), []
    try:
        for p in paths:
            df = _read_csv(p)
            if df is None or df.empty or len(df.columns) == 0:
                report.append(f"Skipped {p.name}: no data rows.")
                continue
            df.columns = _unique([_ident(c, f"col{i + 1}") for i, c in enumerate(df.columns)])
            name = _free(_ident(p.stem, "table"), used)
            used.add(name)
            df.to_sql(name, conn, index=False, chunksize=50_000)
            for col in df.columns:
                if col == "id" or col.endswith("_id"):
                    conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{name}_{col}" '
                                 f'ON "{name}"("{col}")')
            report.append(f"{p.name} -> table {name} ({len(df):,} rows, {len(df.columns)} columns)")
        conn.commit()
    finally:
        conn.close()
    if not used:
        raise ValueError("No usable tables: every file was empty.")
    return db_path, report


def _q(name: str) -> str:
    return name.replace('"', '""')


def _describe(db_path, samples: bool) -> str:
    conn = connect_ro(db_path)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name")]
    lines, owners, fks = [], defaultdict(list), []

    for t in tables:
        n = conn.execute(f'SELECT COUNT(*) FROM "{_q(t)}"').fetchone()[0]
        lines.append(f"TABLE {t} ({n:,} rows)")
        for _, col, ctype, *_ in conn.execute(f'PRAGMA table_info("{_q(t)}")'):
            owners[col].append(t)
            nulls = conn.execute(
                f'SELECT COUNT(*) FROM "{_q(t)}" WHERE "{_q(col)}" IS NULL').fetchone()[0]
            null_note = f", {nulls:,} NULLs" if nulls else ""
            sample = ""
            if samples:
                distinct = conn.execute(
                    f'SELECT COUNT(DISTINCT "{_q(col)}") FROM "{_q(t)}"').fetchone()[0]
                limit = 12 if distinct <= 12 else 2
                vals = [str(r[0])[:40] for r in conn.execute(
                    f'SELECT DISTINCT "{_q(col)}" FROM "{_q(t)}" '
                    f'WHERE "{_q(col)}" IS NOT NULL LIMIT {limit}')]
                sample = ("  [values: " if distinct <= 12 else "  [e.g. ") + ", ".join(vals) + "]"
            lines.append(f"  - {col} ({ctype}){null_note}{sample}")
        for row in conn.execute(f'PRAGMA foreign_key_list("{_q(t)}")'):
            fks.append(f"  {t}.{row[3]} -> {row[2]}.{row[4]}")
        lines.append("")

    if fks:
        lines.append("DECLARED FOREIGN KEYS:")
        lines += fks
        lines.append("")
    lines.append("SHARED COLUMNS (likely join keys):")
    shared = {c: ts for c, ts in owners.items() if len(ts) > 1}
    if shared:
        for c, ts in sorted(shared.items()):
            lines.append(f"  {c}: {', '.join(ts)}")
    else:
        lines.append("  (no column name appears in more than one table)")
    conn.close()
    return "\n".join(lines)


def describe_schema(db_path, max_chars: int = 12000) -> str:
    """Schema text for the prompt. Drops sample values if the text gets too long for 8k context."""
    text = _describe(db_path, samples=True)
    if len(text) > max_chars:
        text = _describe(db_path, samples=False)
    return text
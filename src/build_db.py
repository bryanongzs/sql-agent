"""Build data/olist.db (SQLite) from the raw Olist CSVs in data/raw/.

Run from the project root:  python src\build_db.py
"""
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "olist.db"


def table_name(csv_path: Path) -> str:
    name = csv_path.stem
    if name.startswith("olist_"):
        name = name[len("olist_"):]
    if name.endswith("_dataset"):
        name = name[: -len("_dataset")]
    return name


def main() -> None:
    csvs = sorted(RAW.glob("*.csv"))
    if not csvs:
        raise SystemExit(f"No CSV files found in {RAW}")

    if DB_PATH.exists():
        DB_PATH.unlink()  # rebuild from scratch every time

    conn = sqlite3.connect(DB_PATH)
    for csv in csvs:
        name = table_name(csv)
        df = pd.read_csv(csv)
        df.to_sql(name, conn, index=False, chunksize=50_000)
        # index every *_id column so joins are fast
        for col in df.columns:
            if col.endswith("_id"):
                conn.execute(f'CREATE INDEX "idx_{name}_{col}" ON "{name}"("{col}")')
        print(f"{name:40s} {len(df):>9,} rows, {len(df.columns)} columns")
    conn.commit()
    conn.close()
    print(f"\nBuilt {DB_PATH}")


if __name__ == "__main__":
    main()
"""Show every non-correct result next to the gold SQL.

Run from the project root:  python eval\show_failures.py [results_file]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
questions = {q["id"]: q for q in json.loads(
    (ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))}

path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval" / "results" / "baseline_qwen-sql.json"
records = json.loads(path.read_text(encoding="utf-8"))

for r in records:
    if r["status"] == "correct":
        continue
    q = questions[r["id"]]
    print("=" * 70)
    print(f'#{r["id"]} [{r["category"]}] {r["status"]}')
    print("Q:     ", q["question"])
    print("GOLD:  ", q.get("gold_sql", "(should refuse)"))
    print("MODEL: ", r["prediction"])
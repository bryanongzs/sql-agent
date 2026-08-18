"""Evaluate text-to-SQL by execution accuracy. Run from the project root.

  python eval\run_eval.py --check-gold            (validate the gold queries)
  python eval\run_eval.py --baseline --limit 5    (try a few questions)
  python eval\run_eval.py --baseline              (full run, slow)

Matching rules: column names are ignored; row order is ignored unless the
question is marked "ordered"; floats match within 0.051 (gold rounds to at
most 1 decimal); extra or missing columns count as wrong.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from db import QueryError, run_query  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.json"
RESULTS_DIR = ROOT / "eval" / "results"
TOLERANCE = 0.051


def load_questions() -> list:
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))


def cells_equal(a, b) -> bool:
    both_numbers = isinstance(a, (int, float)) and isinstance(b, (int, float))
    if both_numbers and (isinstance(a, float) or isinstance(b, float)):
        return abs(a - b) <= TOLERANCE
    return a == b


def sort_key(row) -> list:
    return [str(round(v, 1)) if isinstance(v, float) else str(v) for v in row]


def results_match(pred_rows, gold_rows, ordered: bool) -> bool:
    if len(pred_rows) != len(gold_rows):
        return False
    if not ordered:
        pred_rows = sorted(pred_rows, key=sort_key)
        gold_rows = sorted(gold_rows, key=sort_key)
    for p, g in zip(pred_rows, gold_rows):
        if len(p) != len(g) or not all(cells_equal(x, y) for x, y in zip(p, g)):
            return False
    return True


def check_gold(questions: list) -> None:
    errors = 0
    for q in questions:
        if q["expect"] == "refuse":
            print(f'{q["id"]:>3}  [refuse] {q["question"]}')
            continue
        try:
            res = run_query(q["gold_sql"])
            first = res["rows"][0] if res["rows"] else None
            flag = "   <-- EMPTY/NULL" if (first is None or first[0] is None) else ""
            print(f'{q["id"]:>3}  {len(res["rows"]):>3} rows  first={str(first)[:70]}{flag}')
        except QueryError as e:
            errors += 1
            print(f'{q["id"]:>3}  ERROR: {e}')
    print(f"\n{errors} gold queries failed.")


def score(q: dict, pred: dict) -> str:
    if q["expect"] == "refuse":
        return "correct" if pred["kind"] == "refuse" else "should_have_refused"
    if pred["kind"] == "refuse":
        return "wrong_refusal"
    try:
        got = run_query(pred["sql"])
    except QueryError:
        return "sql_error"
    want = run_query(q["gold_sql"])
    return "correct" if results_match(got["rows"], want["rows"], q.get("ordered", False)) else "wrong_result"


def run_baseline(questions: list, limit) -> None:
    from baseline import generate

    model = os.environ.get("LLM_MODEL", "unknown")
    records = []
    for q in questions[:limit]:
        t0 = time.time()
        try:
            pred = generate(q["question"])
            status = score(q, pred)
        except Exception as e:  # LLM/connection problems
            pred = {"kind": "error", "sql": None, "raw": str(e)}
            status = "llm_error"
        secs = round(time.time() - t0, 1)
        print(f'{q["id"]:>3} {status:<20} {secs:>6}s  {q["question"][:60]}')
        records.append({"id": q["id"], "category": q["category"], "status": status,
                        "seconds": secs, "prediction": pred.get("sql") or pred.get("raw")})

    total = len(records)
    correct = sum(r["status"] == "correct" for r in records)
    print(f"\nOverall: {correct}/{total} correct ({100 * correct / total:.1f}%)")
    by_cat = defaultdict(lambda: [0, 0])
    for r in records:
        by_cat[r["category"]][1] += 1
        by_cat[r["category"]][0] += r["status"] == "correct"
    for cat, (c, n) in sorted(by_cat.items()):
        print(f"  {cat:<10} {c}/{n}")
    print("Statuses:", dict(Counter(r["status"] for r in records)))

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"baseline_{model.replace(':', '_')}.json"
    out.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Saved {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-gold", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    qs = load_questions()
    if args.check_gold:
        check_gold(qs)
    elif args.baseline:
        run_baseline(qs, args.limit)
    else:
        ap.print_help()
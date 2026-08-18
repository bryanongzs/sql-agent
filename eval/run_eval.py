r"""Evaluate text-to-SQL by execution accuracy. Run from the project root.

  python eval\run_eval.py --check-gold            (validate the gold queries)
  python eval\run_eval.py --baseline              (one-shot, full run)
  python eval\run_eval.py --agent                 (retry loop, full run)
  python eval\run_eval.py --explore               (retry loop + exploration)
  add --questions eval\heldout.json to use the held-out set
  add --limit N to run only the first N questions
Set USE_NOTES=1 to include data\schema_notes.txt in the prompt.

Matching rules (strict): column names are ignored; row order is ignored unless
the question is marked "ordered"; floats match within 0.051; extra or missing
columns count as wrong; text '11' does not equal integer 11.
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

DEFAULT_QUESTIONS = ROOT / "eval" / "questions.json"
RESULTS_DIR = ROOT / "eval" / "results"
TOLERANCE = 0.051


def load_questions(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8"))


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


def run_eval(questions: list, limit, mode: str, q_stem: str) -> None:
    if mode == "agent":
        from agent import run_agent as generate
    elif mode == "explore":
        from agent_explore import run_agent as generate
    elif mode == "checked":
        from agent_checked import run_agent as generate
    else:
        from baseline import generate

    model = os.environ.get("LLM_MODEL", "unknown")
    notes = os.environ.get("USE_NOTES") == "1"
    print(f"mode={mode} model={model} notes={'ON' if notes else 'off'} questions={q_stem}\n")
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
        steps = pred.get("steps", 1)
        print(f'{q["id"]:>3} {status:<20} {secs:>6}s  steps={steps}  {q["question"][:50]}')
        records.append({"id": q["id"], "category": q["category"], "status": status,
                        "seconds": secs, "steps": steps,
                        "prediction": pred.get("sql") or pred.get("raw")})

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
    name = f"{mode}_{model.replace(':', '_')}"
    if notes:
        name += "_notes"
    if q_stem != "questions":
        name += f"_{q_stem}"
    out = RESULTS_DIR / f"{name}.json"
    out.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Saved {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-gold", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--agent", action="store_true")
    ap.add_argument("--explore", action="store_true")
    ap.add_argument("--checked", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    args = ap.parse_args()
    qs = load_questions(args.questions)
    if args.check_gold:
        check_gold(qs)
    elif args.baseline:
        run_eval(qs, args.limit, "baseline", args.questions.stem)
    elif args.agent:
        run_eval(qs, args.limit, "agent", args.questions.stem)
    elif args.explore:
        run_eval(qs, args.limit, "explore", args.questions.stem)
    elif args.checked:
        run_eval(qs, args.limit, "checked", args.questions.stem)
    else:
        ap.print_help()
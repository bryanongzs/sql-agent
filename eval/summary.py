r"""Print one line per saved results file.

Run from the project root:  python eval\summary.py
"""
import json
from collections import Counter
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "eval" / "results"

for p in sorted(RESULTS.glob("*.json")):
    recs = json.loads(p.read_text(encoding="utf-8"))
    n = len(recs)
    ok = sum(r["status"] == "correct" for r in recs)
    steps = sum(r.get("steps", 1) for r in recs) / n
    secs = sum(r["seconds"] for r in recs) / n
    statuses = dict(Counter(r["status"] for r in recs))
    print(f"{p.name:<45} {ok:>2}/{n:<2} ({100 * ok / n:4.1f}%)  "
          f"avg steps {steps:.1f}  avg {secs:.0f}s  {statuses}")
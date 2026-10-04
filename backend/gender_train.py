"""
Build and evaluate the given-name gender lexicon (offline tooling).

    python -m backend.gender_train build  <labelled.xlsx> [--out backend/data/given_name_gender.json]
    python -m backend.gender_train cv     <labelled.xlsx> [--folds 5]

The labelled workbook must have a "Full Name" column formatted
"LASTNAME, FIRST [SECOND] MIDDLE" and a "Gender" column of M/F.  Only
aggregated given-name counts are written (no surnames, no individual rows).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gender as G  # noqa: E402

DEFAULT_OUT = G.LEXICON_PATH
MIN_TOTAL = 2


def load_records(xlsx: str, sheet: str = "Attendance") -> list[tuple[list[str], list[str], str]]:
    """Return [(surname_tokens, given_tokens(with suffix kept), sex)]."""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb[sheet]
    rows = ws.iter_rows(values_only=True)
    header = [str(h or "").strip().lower() for h in next(rows)]
    ni, gi = header.index("full name"), header.index("gender")
    out = []
    for r in rows:
        name, sex = r[ni], (r[gi] or "")
        sex = str(sex).strip().upper()[:1]
        if not name or sex not in ("M", "F") or "," not in str(name):
            continue
        sur, given = str(name).split(",", 1)
        out.append((G.normalize_tokens(sur), G.normalize_tokens(given), sex))
    return out


def build_lexicon(records, min_total: int = MIN_TOTAL, sur_min: int = 2) -> G.Lexicon:
    """Aggregate given-name counts, excluding tokens that are mainly surnames."""
    sur = Counter(t for s, _, _ in records for t in s)
    first: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    later: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for _, given, sex in records:
        names, _sfx = G.split_given(given)
        if names and names[0] in G.MARIA_PREFIXES and names[0] == "MA":
            names = names[1:]  # MA. is a prefix; the real first name follows
            maria_prefixed = True
        else:
            maria_prefixed = False
        k = 0 if sex == "M" else 1
        for i, t in enumerate(names):
            (first if i == 0 else later)[t][k] += 1
        if maria_prefixed:
            first["MA"][1] += 1
    # name-type level ending/prefix statistics (all first tokens, incl. singletons)
    endings: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    prefixes: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for t, (m, f) in first.items():
        if len(t) < 3:
            continue
        pm = m / (m + f)
        for k in (1, 2, 3, 4):
            if len(t) > k:
                endings[t[-k:]][0] += pm
                endings[t[-k:]][1] += 1 - pm
        for k in (3, 4):
            if len(t) > k:
                prefixes[t[:k]][0] += pm
                prefixes[t[:k]][1] += 1 - pm
    endings = {a: v for a, v in endings.items() if sum(v) >= 3}
    prefixes = {a: v for a, v in prefixes.items() if sum(v) >= 3}
    first_tot = {t: sum(v) for t, v in first.items()}
    # drop surname-like tokens from the "later" table (middle names are mother's surnames)
    for t in list(later):
        if sur[t] >= sur_min and sur[t] > first_tot.get(t, 0):
            del later[t]
    total = {t: sum(first.get(t, (0, 0))) + sum(later.get(t, (0, 0))) for t in set(first) | set(later)}
    keep = {t for t, n in total.items() if n >= min_total}
    f2 = {t: v for t, v in first.items() if t in keep}
    l2 = {t: v for t, v in later.items() if t in keep}
    meta = {
        "description": "Aggregated given-name counts [male, female] from a labelled Bohol student corpus. "
        "'first' = token seen as first given name, 'later' = token seen after the first (surname-like tokens removed). "
        "Tokens with total count < 2 dropped; no surnames or personal records.",
        "n_records": len(records),
        "min_total": min_total,
    }
    return G.Lexicon(f2, l2, meta, endings, prefixes)


def evaluate(records, lex: G.Lexicon, use_mid_split: bool = False):
    """Predict each record; return list of (sex_true, sex_pred, conf, first_token_seen)."""
    res = []
    for _, given, sex in records:
        first = given[0] if given else ""
        rest = " ".join(given[1:])
        # simulate a PDF that gives only the first token as first_name and the rest in full_given
        pred, conf, _ = G.infer_sex(first, "", " ".join(given), lexicon=lex)
        res.append((sex, pred, conf, first in lex.first or first in lex.later))
    return res


def summarize(res) -> dict:
    n = len(res)
    cov = [r for r in res if r[1]]
    acc = sum(r[0] == r[1] for r in cov) / max(1, len(cov))
    hi = [r for r in cov if r[2] >= 0.8]
    acc_hi = sum(r[0] == r[1] for r in hi) / max(1, len(hi))
    unseen = [r for r in res if not r[3]]
    unseen_cov = [r for r in unseen if r[1]]
    return {
        "n": n,
        "coverage": len(cov) / n,
        "accuracy_covered": acc,
        "overall_correct": sum(r[0] == r[1] for r in res) / n,
        "n_hi": len(hi),
        "coverage_hi": len(hi) / n,
        "accuracy_hi": acc_hi,
        "unseen_n": len(unseen),
        "unseen_coverage": len(unseen_cov) / max(1, len(unseen)),
        "unseen_accuracy": sum(r[0] == r[1] for r in unseen_cov) / max(1, len(unseen_cov)),
    }


def cross_validate(records, folds: int = 5, seed: int = 13):
    idx = list(range(len(records)))
    random.Random(seed).shuffle(idx)
    allres = []
    for k in range(folds):
        test = [records[i] for i in idx[k::folds]]
        train = [records[i] for j, i in enumerate(idx) if j % folds != k]
        lex = build_lexicon(train)
        allres.extend(evaluate(test, lex))
    return allres


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("xlsx")
    b.add_argument("--out", default=str(DEFAULT_OUT))
    c = sub.add_parser("cv")
    c.add_argument("xlsx")
    c.add_argument("--folds", type=int, default=5)
    c.add_argument("--errors", type=int, default=0, help="print N misclassified examples (local debugging only)")
    args = ap.parse_args(argv)
    recs = load_records(args.xlsx)
    if args.cmd == "build":
        lex = build_lexicon(recs)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(lex.to_json(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"wrote {args.out}: {len(lex.first)} first, {len(lex.later)} later tokens from {len(recs)} records")
    else:
        res = cross_validate(recs, args.folds)
        for k, v in summarize(res).items():
            print(f"{k}: {v:.4f}" if isinstance(v, float) else f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

"""Analyze the grammatical shape of every word-ban criterion: dump the full description
with ban-word positions and negation-cue positions annotated, plus the text between the
negation cue and the nearest ban word. This is the evidence base for the grammatical-shape
fix: we need to see, for each criterion, whether the negation cue directly precedes the
ban word (prohibition template) or scopes over a different verb (false positive)."""
import re
import sys
import tomllib
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from word_ban_false_trigger_check import (  # noqa: E402
    ALL_BAN_WORDS,
    CLUSTER_WINDOW,
    NEGATION_CUE_RE,
    NEGATION_WINDOW,
    _detect_word_ban,
)

ROOT = Path(r"C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready")


def annotate(description: str) -> dict:
    """Return positions of ban words and negation cues in the description."""
    ban_occ = []
    for word in ALL_BAN_WORDS:
        for m in re.finditer(rf"\b{re.escape(word)}\b", description, re.IGNORECASE):
            ban_occ.append((m.start(), m.end(), word))
    ban_occ.sort()
    neg_occ = []
    for m in NEGATION_CUE_RE.finditer(description):
        neg_occ.append((m.start(), m.end(), m.group(0).lower()))
    neg_occ.sort()
    return {"ban_occ": ban_occ, "neg_occ": neg_occ}


def analyze():
    task_dirs = sorted(d for d in ROOT.iterdir() if d.is_dir())
    rows = []
    for task_dir in task_dirs:
        tests_dir = task_dir / "tests"
        if not tests_dir.is_dir():
            continue
        for jt in sorted(tests_dir.glob("deliverables*/judge.toml")):
            rel = str(jt.relative_to(task_dir)).replace("\\", "/")
            try:
                data = tomllib.loads(jt.read_text(encoding="utf-8"))
            except Exception:
                continue
            for c in data.get("criterion") or []:
                desc = c.get("description") or ""
                is_ban, finance_banned = _detect_word_ban(desc)
                if not is_ban:
                    continue
                ann = annotate(desc)
                # unique ban words
                uniq = sorted({w for _, _, w in ann["ban_occ"]})
                # For each negation, find nearest ban word and the text between
                pairs = []
                for ns, ne, nw in ann["neg_occ"]:
                    best = None
                    for bs, be, bw in ann["ban_occ"]:
                        dist = bs - ne  # positive if ban word after negation
                        if best is None or abs(dist) < abs(best[0]):
                            best = (dist, bs, be, bw)
                    if best:
                        dist, bs, be, bw = best
                        if dist >= 0:
                            between = desc[ne:bs].strip()
                        else:
                            between = "(ban-before-neg) " + desc[be:ns].strip()
                        pairs.append({
                            "neg": nw,
                            "neg_pos": ns,
                            "ban": bw,
                            "ban_pos": bs,
                            "dist": dist,
                            "between": between[:60],
                        })
                rows.append({
                    "task": task_dir.name,
                    "group": rel,
                    "criterion": c.get("name"),
                    "weight": c.get("weight"),
                    "finance_banned": finance_banned,
                    "n_unique": len(uniq),
                    "unique_bans": uniq,
                    "desc": desc,
                    "pairs": pairs,
                })

    # Sort: 1-unique first (the critical cases), then 2+ unique
    rows.sort(key=lambda r: (r["n_unique"], r["task"]))

    print(f"Total word-ban criteria: {len(rows)}")
    one = [r for r in rows if r["n_unique"] == 1]
    multi = [r for r in rows if r["n_unique"] >= 2]
    print(f"  1 unique ban word: {len(one)}")
    print(f"  2+ unique ban words: {len(multi)}")

    print("\n" + "=" * 90)
    print("1-UNIQUE-BAN CRITERIA (the critical set for the fix):")
    print("=" * 90)
    for r in one:
        print(f"\n--- {r['task']} [{r['group']}/{r['criterion']}] w={r['weight']} ---")
        print(f"  unique_bans: {r['unique_bans']}  finance_banned: {r['finance_banned']}")
        print(f"  FULL DESC: {r['desc']}")
        for p in r["pairs"]:
            tag = "BEFORE" if p["dist"] >= 0 else "AFTER"
            print(f"  neg '{p['neg']}'@{p['neg_pos']} -> ban '{p['ban']}'@{p['ban_pos']} "
                  f"[{tag}, dist={p['dist']}] between: \"{p['between']}\"")

    print("\n" + "=" * 90)
    print("2+-UNIQUE-BAN CRITERIA (sample of first 20):")
    print("=" * 90)
    for r in multi[:20]:
        print(f"\n--- {r['task']} [{r['group']}/{r['criterion']}] w={r['weight']} ---")
        print(f"  unique_bans: {r['unique_bans']}  finance_banned: {r['finance_banned']}")
        print(f"  FULL DESC: {r['desc']}")
        for p in r["pairs"]:
            tag = "BEFORE" if p["dist"] >= 0 else "AFTER"
            print(f"  neg '{p['neg']}'@{p['neg_pos']} -> ban '{p['ban']}'@{p['ban_pos']} "
                  f"[{tag}, dist={p['dist']}] between: \"{p['between']}\"")


if __name__ == "__main__":
    analyze()

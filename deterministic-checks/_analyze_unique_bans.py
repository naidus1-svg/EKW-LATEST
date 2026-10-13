"""Analyze all 600 tasks: for each criterion that currently passes _detect_word_ban,
report the unique ban word count. This lets us check whether requiring 2+ unique ban
words would kill any genuine word-bans among the other 67 fail tasks."""
import sys
import tomllib
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from word_ban_false_trigger_check import _detect_word_ban, ALL_BAN_WORDS

import re

ROOT = Path(r"C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready")

def count_unique_bans(desc):
    """Count unique ban words in description."""
    words = set()
    for word in ALL_BAN_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", desc, re.IGNORECASE):
            words.add(word.lower())
    return words

def analyze():
    one_unique_fires = []
    multi_unique_fires = []
    total_ban_criteria = 0
    
    task_dirs = sorted(d for d in ROOT.iterdir() if d.is_dir())
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
                total_ban_criteria += 1
                # Count unique ban words in the description
                all_bans_in_desc = count_unique_bans(desc)
                n_unique = len(all_bans_in_desc)
                entry = {
                    "task": task_dir.name,
                    "group": rel,
                    "criterion": c.get("name"),
                    "weight": c.get("weight"),
                    "finance_banned": finance_banned,
                    "n_unique_bans": n_unique,
                    "unique_bans": sorted(all_bans_in_desc),
                    "desc": desc[:200],
                }
                if n_unique < 2:
                    one_unique_fires.append(entry)
                else:
                    multi_unique_fires.append(entry)
    
    print(f"Total word-ban criteria detected (current logic): {total_ban_criteria}")
    print(f"  With 1 unique ban word (would STOP firing with fix): {len(one_unique_fires)}")
    print(f"  With 2+ unique ban words (would KEEP firing): {len(multi_unique_fires)}")
    
    print("\n" + "=" * 80)
    print(f"ALL {len(one_unique_fires)} tasks with 1 unique ban word (examine for genuine word-bans):")
    print("=" * 80)
    for e in one_unique_fires:
        print(f"\n--- {e['task']} [{e['group']}/{e['criterion']}] w={e['weight']} ---")
        print(f"  finance_banned: {e['finance_banned']}")
        print(f"  unique_bans: {e['unique_bans']}")
        print(f"  desc: {e['desc']}")
    
    # Also count unique tasks
    one_unique_tasks = set(e["task"] for e in one_unique_fires)
    multi_unique_tasks = set(e["task"] for e in multi_unique_fires)
    print(f"\n\nTasks with 1-unique-ban criteria: {len(one_unique_tasks)}")
    print(f"Tasks with 2+-unique-ban criteria: {len(multi_unique_tasks)}")
    overlap = one_unique_tasks & multi_unique_tasks
    print(f"Tasks in BOTH categories: {len(overlap)} (these would still fire via multi-unique criteria)")
    only_one = one_unique_tasks - multi_unique_tasks
    print(f"Tasks ONLY in 1-unique category: {len(only_one)} (these would STOP firing)")
    if only_one:
        print(f"  {sorted(only_one)}")

if __name__ == "__main__":
    analyze()

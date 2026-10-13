import re
import sys
import os

# For each task: collect numeric expected-value tokens that appear in judge.toml criteria, then check
# whether any appear in instruction.md or tests/task_prompt.txt (the solver-visible files). A hit = leakage.
CORPUS = "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
NUM = re.compile(
    r"\d[\d,]{2,}(?:\.\d+)?"
)  # numbers >= 3 digits (skip trivial 1-2 digit)


def nums_in(path):
    try:
        t = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return set()
    return set(m.group(0).replace(",", "") for m in NUM.finditer(t))


for t in sys.argv[1:]:
    tdir = os.path.join(CORPUS, t)
    tests = os.path.join(tdir, "tests")
    judge_nums = set()
    for root, _, files in os.walk(tests):
        for fn in files:
            if fn == "judge.toml":
                judge_nums |= nums_in(os.path.join(root, fn))
    solver_nums = set()
    for f in [
        os.path.join(tdir, "instruction.md"),
        os.path.join(tests, "task_prompt.txt"),
    ]:
        solver_nums |= nums_in(f)
    leak = judge_nums & solver_nums
    # filter years/common (2021, 2022, dates) to cut noise
    leak = {x for x in leak if x not in {"2021", "2022", "2020", "2023", "1000", "100"}}
    print(
        f"{t}: {len(leak)} judge-value token(s) also in solver-visible text"
        + (f" -> {sorted(leak)[:12]}" if leak else " (clean)")
    )

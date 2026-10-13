#!/usr/bin/env python3
"""bundle.py <short_task_id>

Assemble a shareable folder + zip for one task's audit:
  audit_bundle_<id>/
    README.md
    AUDIT_<id>.docx
    task/            (the task as the pipeline received it)
    qc_results/      (findings, judge transcripts, queue row, extracted artifacts)
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
RUN = HERE / os.environ.get("AUDIT_RUN", "runs/run_10_v2")
CORPUS = HERE / os.environ.get("AUDIT_CORPUS", "corpus_10")
short = sys.argv[1]
A = json.loads((RUN / f"audit_{short}.json").read_text())
ASMT = json.loads((HERE / f"assessments_{short}.json").read_text())

B = HERE / f"audit_bundle_{short}"
if B.exists():
    shutil.rmtree(B)
(B / "qc_results").mkdir(parents=True)

# task as received
shutil.copytree(CORPUS / f"task_{short}", B / "task")
# audit doc
shutil.copy(RUN / f"AUDIT_{short}.docx", B / f"AUDIT_{short}.docx")
# qc results
shutil.copy(RUN / f"audit_{short}.json", B / "qc_results" / "audit_findings.json")
shutil.copy(RUN / f"artifacts_{short}.json", B / "qc_results" / "extracted_artifacts.json")
shutil.copy(RUN / "raw" / f"sample_task_{short}.json", B / "qc_results" / "raw_judge_transcript.json")
review = json.loads((RUN / "batch_review.json").read_text())
sample = next(s for s in review["samples"] if s["sample_id"] == f"task_{short}")
(B / "qc_results" / "batch_review_slice.json").write_text(
    json.dumps({"spec_name": review["spec_name"], "spec_version": review["spec_version"], "sample": sample}, indent=2))
queue = (RUN / "reviewer_queue.csv").read_text().splitlines()
row = [queue[0]] + [ln for ln in queue[1:] if ln.startswith(f"task_{short},")]
(B / "qc_results" / "reviewer_queue_row.csv").write_text("\n".join(row) + "\n")

readme = f"""# QC audit bundle — task_{short}

Everything needed to audit one GDPval task through the QC pipeline: the task as the
pipeline received it, the pipeline's run results, and the audit document.

- Task: `{short}` — {A['sector']} / {A['occupation']}
- Pipeline: `gdpval-assess` v18.5, judges gpt-5.5 + gemini-3.1-pro
- Verdict: **{A['verdict']}**

## Start here

**`AUDIT_{short}.docx`** — the audit. Each flagged gate reads top to bottom: what the
gate evaluates, the inline source text to verify against, both judges' verbatim
responses, an audit assessment, and a line for your own verdict. A sign-off block is at
the end.

## Contents

```
AUDIT_{short}.docx           the audit document (start here)
task/                        the task as the pipeline received it
  instruction.md             the prompt
  environment/               input files
  solution/golden_outputs/   golden deliverables
  tests/verifier.json        the rubric, adapted into the pipeline's schema
  task.toml                  task metadata
qc_results/
  audit_findings.json        all gate findings; each judge's severity, justification, evidence
  batch_review_slice.json    this task's full machine record from the run
  raw_judge_transcript.json  raw LLM transcripts per gate
  reviewer_queue_row.csv     the queue row the run produced (top issues + actions)
  extracted_artifacts.json   text extracted from the files plus the full rubric
```

## One caveat on the rubric

`task/tests/verifier.json` was adapted from GDPval's native rubric (a flat list of
scored criteria) into the pipeline's schema. The criterion text and point weights are
preserved verbatim; the grading-role and per-criterion source-file fields were filled
in by the adapter and carry no GDPval signal. The audit flags any gate whose result
depends on those adapter-filled fields.
"""
(B / "README.md").write_text(readme)

zip_path = HERE / f"audit_bundle_{short}.zip"
if zip_path.exists():
    zip_path.unlink()
subprocess.run(["zip", "-rq", str(zip_path), B.name, "-x", "*.DS_Store"], cwd=HERE, check=True)
size = zip_path.stat().st_size / 1e6
print(f"bundle: {B.relative_to(HERE)}/  +  {zip_path.name} ({size:.1f} MB)")


if __name__ == "__main__":
    pass

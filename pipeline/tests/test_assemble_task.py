"""Safety checks for assemble_task.py's SVC-PC-specific DVC pointer gating.

assemble_task.py is the shared "loose expert pieces -> harbor task" builder
used by both the SVC-PC batch converter (svc_pc_batch_convert.py) and the
EKW harbor-task-intake skill. The full-corpus DVC pointer it can ship
(pipeline/templates/svc_fullcorpus_dvc/) is the SVC-fictional-company
"Cirrus Sleep Full Y1" corpus specifically -- it must only be included for
SVC-PC tasks (--category starting with "SVC", case-insensitive, or the
explicit --dvc-fullcorpus override), never stapled onto an unrelated EKW
task just because it shares this same assembler.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"


def _load_assemble_task():
    sys.path.insert(0, str(TOOLS_DIR))
    spec = importlib.util.spec_from_file_location(
        "assemble_task", TOOLS_DIR / "assemble_task.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["assemble_task"] = module
    spec.loader.exec_module(module)
    return module


def _write_minimal_inputs(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "Journal.csv").write_text("date,amount\n2021-01-01,100\n")

    verifier_path = tmp_path / "verifier.json"
    verifier_path.write_text(
        json.dumps({"verifiers": [{"name": "c1", "metadata": {"weight": 1.0}}]})
    )
    return source_dir, verifier_path


def test_svc_category_gets_dvc_pointer(tmp_path):
    at = _load_assemble_task()
    source_dir, verifier_path = _write_minimal_inputs(tmp_path)
    out_dir = tmp_path / "out"

    for category in ("SVC-PC", "svc-pc", "SVC"):
        dest = at.assemble(
            task_id=f"svc-task-{category}",
            prompt_text="Do the task.",
            source_dir=source_dir,
            solution_dir=None,
            verifier_path=verifier_path,
            out_dir=out_dir,
            category=category,
        )
        assert (dest / "environment" / "data.dvc").is_file(), category
        assert (dest / "environment" / ".dvc" / "config").is_file(), category


def test_non_svc_category_does_not_get_dvc_pointer(tmp_path):
    """EKW tasks (and any other non-SVC category) must never get the
    SVC-specific corpus stapled onto them just because they share this
    assembler with svc_pc_batch_convert.py."""
    at = _load_assemble_task()
    source_dir, verifier_path = _write_minimal_inputs(tmp_path)
    out_dir = tmp_path / "out"

    for category in ("EKW", "gdpval", ""):
        dest = at.assemble(
            task_id=f"non-svc-task-{category or 'blank'}",
            prompt_text="Do the task.",
            source_dir=source_dir,
            solution_dir=None,
            verifier_path=verifier_path,
            out_dir=out_dir,
            category=category,
        )
        assert not (dest / "environment" / "data.dvc").exists(), category
        assert not (dest / "environment" / ".dvc").exists(), category
        # The named source file must still land normally either way.
        assert (dest / "environment" / "data" / "Journal.csv").is_file(), category


def test_dvc_fullcorpus_flag_overrides_non_svc_category(tmp_path):
    """The explicit --dvc-fullcorpus override still works for the rare
    non-SVC-PC task that genuinely needs this specific corpus anyway."""
    at = _load_assemble_task()
    source_dir, verifier_path = _write_minimal_inputs(tmp_path)
    out_dir = tmp_path / "out"

    dest = at.assemble(
        task_id="ekw-task-with-override",
        prompt_text="Do the task.",
        source_dir=source_dir,
        solution_dir=None,
        verifier_path=verifier_path,
        out_dir=out_dir,
        category="EKW",
        dvc_fullcorpus=True,
    )
    assert (dest / "environment" / "data.dvc").is_file()
    assert (dest / "environment" / ".dvc" / "config").is_file()

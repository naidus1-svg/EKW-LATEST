"""Tests for v18 document caching + multimodal prompt construction."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gdpval_qc.finding import JudgeAttempt
from gdpval_qc.llm_client import DocumentBlock, TextBlock
from gdpval_qc.mock_llm import MockLLMClient, RecordedCall, make_attempt_json
from gdpval_qc.v18_judge import (
    build_user_prompt, build_user_prompt_blocks,
    run_one_judge, sample_has_multimodal_content,
    _pdf_to_document_block,
)
from gdpval_qc.v18_loader import FileContent, Sample, TaskCorpusLoader
from gdpval_qc.v18_spec import V18Spec


REPO_ROOT     = Path(__file__).resolve().parent.parent
V18_SPEC_PATH = REPO_ROOT / "specs" / "gdpval_task_quality_v18.md"


@pytest.fixture(scope="session")
def spec() -> V18Spec:
    return V18Spec.from_markdown(V18_SPEC_PATH)


# ── Multimodal detection ───────────────────────────────────────────────────

def _make_sample_with_pdf(pdf_path: Path) -> Sample:
    return Sample(
        task_id="t", task_dir=pdf_path.parent,
        fields={
            "instruction": "Grade this document.",
            "category":    "Test",
            "solution_files": [
                FileContent(name="memo.docx", path=pdf_path, text="dummy text",
                             cached_path=pdf_path, is_pdf=True),
            ],
        },
    )


def _make_sample_text_only() -> Sample:
    return Sample(
        task_id="t", task_dir=Path("/tmp"),
        fields={
            "instruction": "Grade this document.",
            "category":    "Test",
            "solution_files": [
                FileContent(name="memo.txt", path=Path("/tmp/m.txt"), text="content",
                             cached_path=None, is_pdf=False),
            ],
        },
    )


def test_sample_has_multimodal_content_true(spec: V18Spec, tmp_path: Path) -> None:
    # Fake a PDF on disk
    pdf = tmp_path / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    sample = _make_sample_with_pdf(pdf)
    dim = spec.get_dimension("solution_instruction_alignment")
    assert sample_has_multimodal_content(dim, sample) is True


def test_sample_has_multimodal_content_false_text_only(spec: V18Spec) -> None:
    sample = _make_sample_text_only()
    dim = spec.get_dimension("solution_instruction_alignment")
    assert sample_has_multimodal_content(dim, sample) is False


def test_sample_has_multimodal_content_false_when_dim_doesnt_use_files(spec: V18Spec, tmp_path: Path) -> None:
    """Even if the sample has PDFs, a dim that doesn't bind any file field
    shouldn't trigger multimodal."""
    pdf = tmp_path / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    sample = _make_sample_with_pdf(pdf)
    # role_and_deliverable_clarity only binds [instruction]
    dim = spec.get_dimension("role_and_deliverable_clarity")
    assert sample_has_multimodal_content(dim, sample) is False


# ── Block prompt construction ──────────────────────────────────────────────

def test_build_user_prompt_blocks_includes_document_block(spec: V18Spec, tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf_bytes = b"%PDF-1.4 fake content"
    pdf.write_bytes(pdf_bytes)
    sample = _make_sample_with_pdf(pdf)
    dim = spec.get_dimension("solution_instruction_alignment")

    blocks = build_user_prompt_blocks(dim, sample)

    # Must contain at least one DocumentBlock and several TextBlocks
    document_blocks = [b for b in blocks if isinstance(b, DocumentBlock)]
    text_blocks = [b for b in blocks if isinstance(b, TextBlock)]
    assert len(document_blocks) == 1, f"expected 1 DocumentBlock, got {len(document_blocks)}"
    assert len(text_blocks) >= 2, "expected dim metadata text blocks alongside the doc"

    # The document block carries base64-encoded PDF bytes
    db = document_blocks[0]
    assert db.source["type"] == "base64"
    assert db.source["media_type"] == "application/pdf"
    decoded = base64.standard_b64decode(db.source["data"])
    assert decoded == pdf_bytes

    # The dim's name and inputs tag should appear in the prose blocks
    prose = "\n".join(b.text for b in text_blocks)
    assert dim.dimension_name in prose
    assert "<solution_files>" in prose


def test_build_user_prompt_blocks_marks_original_extension_for_docx(
    spec: V18Spec, tmp_path: Path,
) -> None:
    """When a .docx is sent as a transport-PDF, the <file> tag must expose
    the original `.docx` extension AND flag the conversion explicitly so
    the judge doesn't grade format-match on the transport format."""
    pdf = tmp_path / "memo_abc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    docx = tmp_path / "memo.docx"
    docx.write_bytes(b"fake docx bytes")
    sample = Sample(
        task_id="t", task_dir=tmp_path,
        fields={
            "instruction": "Produce a memo as memo.docx",
            "category":    "Test",
            "solution_files": [
                FileContent(name="memo.docx", path=docx, text="extracted",
                             cached_path=pdf, is_pdf=True),
            ],
        },
    )
    dim = spec.get_dimension("solution_format_match")
    blocks = build_user_prompt_blocks(dim, sample)
    prose = "\n".join(b.text for b in blocks if isinstance(b, TextBlock))

    # Original extension MUST be explicit
    assert 'original_extension=".docx"' in prose
    # The transport-PDF flag MUST be present
    assert "pdf-conversion-of-original" in prose
    # We MUST NOT say `format="pdf"` (the previous, confusing rendering)
    assert 'format="pdf"' not in prose


def test_build_user_prompt_blocks_marks_native_pdf_without_conversion_flag(
    spec: V18Spec, tmp_path: Path,
) -> None:
    """A native .pdf file (no conversion) should not carry the
    `sent_to_judge_as` attribute on its `<file>` tag.

    Uses solution_layout_professionalism (rather than solution_format_match)
    so we can substring-check the rendered prose without the dim's own
    documentation prose mentioning 'pdf-conversion-of-original'."""
    import re as _re
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    sample = Sample(
        task_id="t", task_dir=tmp_path,
        fields={
            "instruction": "Produce a report",
            "category":    "Test",
            "solution_files": [
                FileContent(name="report.pdf", path=pdf, text="extracted",
                             cached_path=pdf, is_pdf=True),
            ],
        },
    )
    dim = spec.get_dimension("solution_layout_professionalism")
    blocks = build_user_prompt_blocks(dim, sample)
    prose = "\n".join(b.text for b in blocks if isinstance(b, TextBlock))

    # Find the <file ... /> tag(s) the loader emitted for this sample.
    file_tags = _re.findall(r"<file\s+[^/]+/>", prose)
    assert len(file_tags) >= 1
    tag = file_tags[0]
    assert 'original_extension=".pdf"' in tag
    assert "sent_to_judge_as" not in tag, \
        f"native PDF tag must not carry conversion marker; got {tag!r}"


def test_build_user_prompt_blocks_text_fallback_when_no_pdf(spec: V18Spec) -> None:
    sample = _make_sample_text_only()
    dim = spec.get_dimension("solution_instruction_alignment")
    blocks = build_user_prompt_blocks(dim, sample)
    # No DocumentBlocks, just text
    assert not any(isinstance(b, DocumentBlock) for b in blocks)
    prose = "\n".join(b.text for b in blocks if isinstance(b, TextBlock))
    # The extracted text from the FileContent must appear
    assert "content" in prose


def test_pdf_to_document_block_round_trips_bytes(tmp_path: Path) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.7 \x00\x01\x02 binary stuff")
    db = _pdf_to_document_block(pdf)
    assert db.source["type"] == "base64"
    decoded = base64.standard_b64decode(db.source["data"])
    assert decoded == pdf.read_bytes()


# ── run_one_judge routes to multimodal when applicable ─────────────────────

def test_run_one_judge_sends_multimodal_blocks_when_pdfs_present(
    spec: V18Spec, tmp_path: Path,
) -> None:
    pdf = tmp_path / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    sample = _make_sample_with_pdf(pdf)
    dim = spec.get_dimension("solution_instruction_alignment")

    captured: list[list] = []

    def responder(call: RecordedCall) -> str:
        return make_attempt_json(severity=0)

    client = MockLLMClient(responder=responder)
    # Patch the client's `complete` to capture the message content shape
    orig_complete = client.complete

    def spying_complete(messages, config):
        captured.append([m.content for m in messages])
        return orig_complete(messages, config)

    client.complete = spying_complete  # type: ignore[method-assign]

    attempt = run_one_judge(client, spec, dim, sample, model="m1", multimodal=True)
    assert attempt.error is None
    assert len(captured) == 1
    content = captured[0][0]
    # Multimodal path: content is a list of ContentBlocks
    assert isinstance(content, list)
    assert any(isinstance(b, DocumentBlock) for b in content)


def test_run_one_judge_falls_back_to_text_when_multimodal_disabled(
    spec: V18Spec, tmp_path: Path,
) -> None:
    pdf = tmp_path / "fake.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    sample = _make_sample_with_pdf(pdf)
    dim = spec.get_dimension("solution_instruction_alignment")

    captured: list[list] = []

    def responder(call: RecordedCall) -> str:
        return make_attempt_json(severity=0)

    client = MockLLMClient(responder=responder)
    orig_complete = client.complete

    def spying_complete(messages, config):
        captured.append([m.content for m in messages])
        return orig_complete(messages, config)

    client.complete = spying_complete  # type: ignore[method-assign]

    run_one_judge(client, spec, dim, sample, model="m1", multimodal=False)
    content = captured[0][0]
    # multimodal=False path: content is a str
    assert isinstance(content, str)


# ── TaskCorpusLoader conversion wiring ─────────────────────────────────────

def test_loader_rejects_partial_conversion_config(spec: V18Spec) -> None:
    with pytest.raises(ValueError, match="must be supplied together"):
        TaskCorpusLoader(
            "/tmp",  # type: ignore[arg-type]
            spec,
            converter=object(),  # type: ignore[arg-type]
            cache_dir=None,
        )


def test_loader_attaches_cached_path_via_converter(spec: V18Spec, tmp_path: Path) -> None:
    """When a converter is supplied, FileContent objects carry cached_path
    and is_pdf flags populated from the converter's output."""

    # Synth task with one docx-like file
    td = tmp_path / "task_demo"
    (td / "solution" / "golden_outputs").mkdir(parents=True)
    (td / "environment").mkdir()
    (td / "instruction.md").write_text("Test", encoding="utf-8")
    (td / "task.toml").write_text('[metadata]\ndomain = "Test"\n', encoding="utf-8")
    fake_office = td / "solution" / "golden_outputs" / "memo.docx"
    fake_office.write_bytes(b"PK\x03\x04 fake docx zip header")  # docx is a zip

    root = tmp_path / "root"
    root.mkdir()
    td.rename(root / "task_demo")

    # A converter mock: returns a fake PDF path (it doesn't need to actually exist
    # because the loader just records what the converter returns)
    cache_dir = tmp_path / "cache"
    fake_pdf = cache_dir / "converted" / "memo_abc.pdf"
    fake_pdf.parent.mkdir(parents=True, exist_ok=True)
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    converter = MagicMock()
    converter.convert_for_eval = MagicMock(return_value=(fake_pdf, True))

    loader = TaskCorpusLoader(
        root, spec, converter=converter, cache_dir=cache_dir,
    )
    sample = loader.load_sample("task_demo")
    sol = sample.fields["solution_files"]
    assert len(sol) == 1
    fc = sol[0]
    assert isinstance(fc, FileContent)
    assert fc.cached_path == fake_pdf
    assert fc.is_pdf is True


def test_loader_continues_when_converter_raises(spec: V18Spec, tmp_path: Path) -> None:
    """If the converter raises on one file, the load still succeeds with
    cached_path=None and is_pdf=False — the judge can fall back to text."""

    td = tmp_path / "task_demo"
    (td / "solution" / "golden_outputs").mkdir(parents=True)
    (td / "environment").mkdir()
    (td / "instruction.md").write_text("Test", encoding="utf-8")
    (td / "task.toml").write_text('[metadata]\ndomain = "Test"\n', encoding="utf-8")
    (td / "solution" / "golden_outputs" / "memo.docx").write_bytes(b"fake")

    root = tmp_path / "root"
    root.mkdir()
    td.rename(root / "task_demo")

    cache_dir = tmp_path / "cache"
    converter = MagicMock()
    converter.convert_for_eval = MagicMock(side_effect=RuntimeError("nope"))

    loader = TaskCorpusLoader(
        root, spec, converter=converter, cache_dir=cache_dir,
    )
    sample = loader.load_sample("task_demo")
    fc = sample.fields["solution_files"][0]
    assert fc.cached_path is None
    assert fc.is_pdf is False


# ── DocumentConverter cache reuse ──────────────────────────────────────────

def test_document_converter_cache_hit_on_repeat_call(tmp_path: Path) -> None:
    """The second call against the same source must return the same cached
    path AND report was_fresh=False."""
    from gdpval_qc.converters import DocumentConverter

    # Build a fake plain-text file that DocumentConverter handles by copying
    src = tmp_path / "doc.md"
    src.write_text("hello world", encoding="utf-8")

    cache = tmp_path / "cache"
    conv = DocumentConverter()

    first_path, was_fresh1 = conv.convert_for_eval(src, cache)
    second_path, was_fresh2 = conv.convert_for_eval(src, cache)

    assert first_path == second_path, "cache key must be deterministic"
    assert was_fresh1 is True, "first call should convert"
    assert was_fresh2 is False, "second call should hit cache"
    # Content preserved
    assert first_path.read_text(encoding="utf-8") == "hello world"

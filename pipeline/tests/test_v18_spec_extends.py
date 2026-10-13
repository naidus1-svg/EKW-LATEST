"""Tests for spec composition via `extends` (base spec + front overlay).

Verifies that:
  - an overlay with no relevant delta inherits the base dim/field byte-for-byte
  - field_types/field_bindings merge by key; remove_field_types drops both
  - a `### dim` section in the overlay replaces the base's same-named section
  - remove_dimensions drops a base dimension from the merged spec
  - an overlay-only dimension is appended
  - extends chains (overlay of an overlay) resolve recursively
  - a circular extends chain is rejected with a clear error
  - a spec without `extends` behaves exactly as before (identity path)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from gdpval_qc.v18_spec import V18Spec, SpecValidationError


def _write(path: Path, name: str, content: str) -> Path:
    p = path / name
    p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return p


_BASE = """
    ---
    name: test_base
    version: "18.0"
    models:
      - model: gpt-5.5
    field_types:
      instruction: text
      solution_files: document
    field_bindings:
      solution_files:
        source: directory
        path: solution/golden_outputs
    severity_scale: {0: "ok", 1: "minor", 2: "material", 3: "severe"}
    verdict_tiers: [accept]
    ---
    # body

    ### dim_a

    ```yaml
    dimension_name: "Dim A (base)"
    check_kind: llm
    inputs: [instruction]
    gate:
      role: blocking
      reject_at_severity: 3
    ```

    base prose for dim_a

    ### dim_b

    ```yaml
    dimension_name: "Dim B"
    check_kind: llm
    inputs: [instruction]
    gate:
      role: advisory
      reject_at_severity: 3
    ```

    base prose for dim_b
"""


def test_no_extends_is_unchanged_identity_path(tmp_path: Path) -> None:
    p = _write(tmp_path, "base.md", _BASE)
    spec = V18Spec.from_markdown(p)
    assert {d.name for d in spec.dimensions} == {"dim_a", "dim_b"}
    assert spec.field_bindings[0].path == "solution/golden_outputs"


def test_overlay_overrides_field_bindings_and_dim_section(tmp_path: Path) -> None:
    base = _write(tmp_path, "base.md", _BASE)
    overlay = _write(tmp_path, "overlay.md", """
        ---
        name: test_overlay
        extends: base.md
        field_bindings:
          solution_files:
            source: directory
            path: solution/golden
        ---
        ### dim_a

        ```yaml
        dimension_name: "Dim A (overlay)"
        check_kind: llm
        inputs: [instruction]
        gate:
          role: blocking
          reject_at_severity: 2
        ```

        overlay prose for dim_a
    """)
    spec = V18Spec.from_markdown(overlay)

    # field_bindings: overlay's entry wins for the shared key
    fb = {b.field_name: b for b in spec.field_bindings}
    assert fb["solution_files"].path == "solution/golden"

    # dim_a: overlay's section replaces the base's
    dim_a = spec.get_dimension("dim_a")
    assert dim_a.dimension_name == "Dim A (overlay)"
    assert dim_a.gate.reject_at_severity == 2
    assert "overlay prose" in dim_a.prose

    # dim_b: untouched by the overlay, inherited byte-for-byte
    dim_b = spec.get_dimension("dim_b")
    assert dim_b.dimension_name == "Dim B"
    assert "base prose for dim_b" in dim_b.prose


def test_remove_dimensions_and_new_overlay_dim(tmp_path: Path) -> None:
    base = _write(tmp_path, "base.md", _BASE)
    overlay = _write(tmp_path, "overlay.md", """
        ---
        name: test_overlay
        extends: base.md
        remove_dimensions: [dim_b]
        ---
        ### dim_c

        ```yaml
        dimension_name: "Dim C (overlay-only)"
        check_kind: llm
        inputs: [instruction]
        gate:
          role: advisory
          reject_at_severity: 3
        ```

        front-only dim
    """)
    spec = V18Spec.from_markdown(overlay)
    names = {d.name for d in spec.dimensions}
    assert names == {"dim_a", "dim_c"}  # dim_b removed, dim_a inherited, dim_c added


def test_remove_field_types_drops_type_and_binding(tmp_path: Path) -> None:
    base = _write(tmp_path, "base.md", _BASE)
    overlay = _write(tmp_path, "overlay.md", """
        ---
        name: test_overlay
        extends: base.md
        remove_field_types: [solution_files]
        ---
    """)
    spec = V18Spec.from_markdown(overlay)
    assert "solution_files" not in spec.field_types
    assert not any(b.field_name == "solution_files" for b in spec.field_bindings)


def test_extends_chain_resolves_recursively(tmp_path: Path) -> None:
    base = _write(tmp_path, "base.md", _BASE)
    mid = _write(tmp_path, "mid.md", """
        ---
        name: test_mid
        extends: base.md
        remove_dimensions: [dim_b]
        ---
    """)
    leaf = _write(tmp_path, "leaf.md", """
        ---
        name: test_leaf
        extends: mid.md
        ---
        ### dim_c

        ```yaml
        dimension_name: "Dim C"
        check_kind: llm
        inputs: [instruction]
        gate:
          role: advisory
          reject_at_severity: 3
        ```

        leaf-only dim
    """)
    spec = V18Spec.from_markdown(leaf)
    assert {d.name for d in spec.dimensions} == {"dim_a", "dim_c"}


def test_circular_extends_rejected(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text(textwrap.dedent("""
        ---
        name: a
        extends: b.md
        ---
    """).lstrip("\n"), encoding="utf-8")
    b.write_text(textwrap.dedent("""
        ---
        name: b
        extends: a.md
        ---
    """).lstrip("\n"), encoding="utf-8")
    with pytest.raises(SpecValidationError) as exc:
        V18Spec.from_markdown(a)
    assert "circular" in str(exc.value).lower()


def test_extends_missing_base_file_rejected(tmp_path: Path) -> None:
    overlay = _write(tmp_path, "overlay.md", """
        ---
        name: test_overlay
        extends: does_not_exist.md
        ---
    """)
    with pytest.raises(SpecValidationError) as exc:
        V18Spec.from_markdown(overlay)
    assert "does_not_exist.md" in str(exc.value)

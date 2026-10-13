"""Guard against SDK version drift (PR #445 review).

The adapters use SDK features that older-but-pyproject-allowed versions lack:
  - openai: `reasoning_effort` kwarg on chat.completions.create (>=1.58.0)
  - google-genai: types.HttpOptions / ThinkingConfig / ThinkingLevel (>=1.51.0)

These assert the symbols/versions exist so a clean install can't satisfy
pyproject.toml yet fail at runtime before the default judges run.
"""

from __future__ import annotations

import pytest


def _ver_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for chunk in v.split(".")[:3]:
        num = "".join(c for c in chunk if c.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def test_openai_supports_reasoning_effort() -> None:
    openai = pytest.importorskip("openai")
    assert _ver_tuple(openai.__version__) >= (1, 58, 0), (
        f"openai {openai.__version__} predates reasoning_effort support; "
        "pyproject lower bound must be >=1.58.0"
    )
    # The kwarg must be accepted by the create() signature.
    import inspect
    from openai.resources.chat.completions import Completions
    sig = inspect.signature(Completions.create)
    assert "reasoning_effort" in sig.parameters


def test_google_genai_has_thinking_types() -> None:
    pytest.importorskip("google.genai")
    import importlib.metadata as _md
    ver = _md.version("google-genai")
    assert _ver_tuple(ver) >= (1, 51, 0), (
        f"google-genai {ver} predates the thinking/HttpOptions types used by "
        "gemini_client.py; pyproject lower bound must be >=1.51.0"
    )
    from google.genai import types as _types
    for symbol in ("HttpOptions", "ThinkingConfig", "ThinkingLevel"):
        assert hasattr(_types, symbol), (
            f"google-genai is missing types.{symbol}; "
            "pyproject lower bound must be >=1.51.0"
        )


def test_adapters_import() -> None:
    """Both default-judge adapters import without error under the pinned SDKs."""
    pytest.importorskip("openai")
    pytest.importorskip("google.genai")
    from gdpval_qc.openai_client import OpenAIClientAdapter   # noqa: F401
    from gdpval_qc.gemini_client import GeminiClientAdapter   # noqa: F401

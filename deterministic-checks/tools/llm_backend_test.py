#!/usr/bin/env python3
"""Unit tests for llm_backend.py's HTTP backend error handling. Focused on the
bare-TimeoutError leak found for real on 2026-09-16: a stall during urlopen()'s
response-read phase can raise socket TimeoutError directly, which is NOT a
urllib.error.URLError instance, so it used to skip _call_http_backend's own
except clause entirely and surface to callers as an unlabeled exception
instead of a proper LLMBackendError. No real network call in any test here;
urllib.request.urlopen is monkeypatched to raise each failure mode directly.

Run:
    python deterministic-checks/tools/llm_backend_test.py
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import llm_backend
from llm_backend import LLMBackendError, _call_http_backend

REQUIRED_ENV = {
    "LLM_API_KEY": "sk-test-fake-key-not-real",
    "LLM_API_BASE_URL": "http://198.51.100.1:4000/v1",  # TEST-NET-2, never dialed
    "LLM_API_PROVIDER": "openai",
    "LLM_API_MODEL": "test-model",
}


class _FakeEnv:
    """Context manager: set the 4 required HTTP env vars, restore on exit."""

    def __enter__(self):
        import os

        self._saved = {k: os.environ.get(k) for k in REQUIRED_ENV}
        os.environ.update(REQUIRED_ENV)
        return self

    def __exit__(self, *exc):
        import os

        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _patch_urlopen(monkeypatch_fn):
    """Replace urllib.request.urlopen for the duration of the caller's `with`
    block. Returns a restore callable."""
    original = urllib.request.urlopen
    urllib.request.urlopen = monkeypatch_fn
    return original


def test_bare_timeouterror_is_wrapped_as_llmbackenderror():
    """The real 2026-09-16 bug: urlopen() raising a bare TimeoutError (not
    wrapped in URLError) must still come back as LLMBackendError, not leak
    past this function uncaught."""

    def fake_urlopen(req, timeout=None):
        raise TimeoutError("timed out")

    original = _patch_urlopen(fake_urlopen)
    try:
        with _FakeEnv():
            try:
                _call_http_backend("hello", timeout=5)
                raise AssertionError("expected LLMBackendError, no exception raised")
            except LLMBackendError as exc:
                msg = str(exc)
                assert (
                    "timed out" in msg
                ), f"expected 'timed out' in message, got: {msg}"
                assert (
                    "5" in msg
                ), f"expected the timeout value (5) named in message, got: {msg}"
            except TimeoutError:
                raise AssertionError(
                    "bare TimeoutError leaked past _call_http_backend uncaught "
                    "(this is the exact 2026-09-16 bug - not fixed)"
                )
    finally:
        urllib.request.urlopen = original
    print("  test_bare_timeouterror_is_wrapped_as_llmbackenderror: PASS")


def test_urlerror_still_wrapped():
    """Regression guard: the pre-existing URLError path (e.g. WinError 10060
    connect-phase failure) must still work after adding the TimeoutError
    clause below it."""

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection attempt failed")

    original = _patch_urlopen(fake_urlopen)
    try:
        with _FakeEnv():
            try:
                _call_http_backend("hello", timeout=5)
                raise AssertionError("expected LLMBackendError, no exception raised")
            except LLMBackendError as exc:
                assert "connection attempt failed" in str(exc)
    finally:
        urllib.request.urlopen = original
    print("  test_urlerror_still_wrapped: PASS")


def test_httperror_still_wrapped():
    """Regression guard: the pre-existing HTTPError path (e.g. a real 429 or
    5xx from the gateway) must still work after adding the TimeoutError
    clause below it."""
    import io

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            url="http://198.51.100.1:4000/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b'{"error": "rate limited"}'),
        )

    original = _patch_urlopen(fake_urlopen)
    try:
        with _FakeEnv():
            try:
                _call_http_backend("hello", timeout=5)
                raise AssertionError("expected LLMBackendError, no exception raised")
            except LLMBackendError as exc:
                assert "HTTP 429" in str(
                    exc
                ), f"expected 'HTTP 429' in message, got: {exc}"
                assert "rate limited" in str(exc)
    finally:
        urllib.request.urlopen = original
    print("  test_httperror_still_wrapped: PASS")


def test_call_llm_surfaces_timeout_in_aggregate_message():
    """End-to-end through call_llm() (forced to the HTTP backend): the
    TimeoutError must show up named as 'HTTP backend: ...timed out...' in the
    aggregate 'No LLM backend available' message, the same shape every other
    HTTP failure already produces - not a generic unlabeled exception."""

    def fake_urlopen(req, timeout=None):
        raise TimeoutError("timed out")

    original = _patch_urlopen(fake_urlopen)
    try:
        with _FakeEnv():
            import os

            os.environ["LLM_BACKEND_FORCE"] = "http"
            try:
                try:
                    llm_backend.call_llm("hello", timeout=5)
                    raise AssertionError(
                        "expected LLMBackendError, no exception raised"
                    )
                except LLMBackendError as exc:
                    msg = str(exc)
                    assert "HTTP backend" in msg
                    assert "timed out" in msg
            finally:
                os.environ.pop("LLM_BACKEND_FORCE", None)
    finally:
        urllib.request.urlopen = original
    print("  test_call_llm_surfaces_timeout_in_aggregate_message: PASS")


if __name__ == "__main__":
    tests = [
        test_bare_timeouterror_is_wrapped_as_llmbackenderror,
        test_urlerror_still_wrapped,
        test_httperror_still_wrapped,
        test_call_llm_surfaces_timeout_in_aggregate_message,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  {t.__name__}: FAIL - {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{passed + failed} tests passed")
    sys.exit(1 if failed else 0)

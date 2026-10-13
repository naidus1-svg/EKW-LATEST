"""Regression tests for PR #445 review fixes:

- context_limiter.truncate_if_needed must reserve the request's real output
  budget (config.max_tokens), not a fixed 4096, when deciding fit.
- llm_client must accumulate per-call usage across threads for run-wide cost.
"""

from __future__ import annotations

import threading

import pytest

from gdpval_qc.context_limiter import truncate_if_needed, ContextLimitError, get_context_limit
from gdpval_qc.llm_client import (
    LLMClientConfig, LLMMessage, ModelUsage,
    _store_usage, get_accumulated_usage, reset_accumulated_usage,
)


# A text-only prompt sized so that:
#   estimated + 4096   <= limit   (would fit under the OLD fixed budget)
#   estimated + 32000  >  limit   (does NOT fit once the real budget is reserved)
# gpt-5* context limit is 272_000 tokens; _CHARS_PER_TOKEN is 4.
_MODEL = "gpt-5.5"
_LIMIT = get_context_limit(_MODEL)          # 272_000
_EST_TOKENS = _LIMIT - 22_000               # 250_000 → fits w/ 4096, not w/ 32000
_BIG_TEXT = "x" * (_EST_TOKENS * 4)


def _msgs() -> list[LLMMessage]:
    return [LLMMessage(role="user", content=_BIG_TEXT)]


def test_real_output_budget_is_reserved_and_blocks_overflow() -> None:
    """With max_tokens=32000 the prompt no longer fits, so a text-only payload
    (no PDFs to shrink) raises ContextLimitError instead of being passed through."""
    config = LLMClientConfig(model=_MODEL, max_tokens=32_000)
    with pytest.raises(ContextLimitError):
        truncate_if_needed(_msgs(), config)


def test_small_output_budget_still_fits() -> None:
    """The same prompt fits when only 4096 output tokens are reserved — proving
    the difference above is driven by the threaded max_tokens, not the prompt."""
    config = LLMClientConfig(model=_MODEL, max_tokens=4_096)
    msgs, info = truncate_if_needed(_msgs(), config)
    assert msgs is not None


def test_explicit_response_budget_overrides_config() -> None:
    """An explicit response_token_budget still wins over config.max_tokens."""
    config = LLMClientConfig(model=_MODEL, max_tokens=32_000)
    msgs, info = truncate_if_needed(_msgs(), config, response_token_budget=4_096)
    assert msgs is not None


# ── Cost accumulator across threads (C1) ───────────────────────────────────

def test_accumulated_usage_collects_across_threads() -> None:
    reset_accumulated_usage()

    def worker(model: str) -> None:
        _store_usage([ModelUsage.from_tokens(model, 100, 50)])

    threads = [threading.Thread(target=worker, args=(f"gpt-5.5",)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    usage = get_accumulated_usage()
    assert len(usage) == 8, "every worker-thread call should be recorded"
    # get_last_usage on this (main) thread saw none of the worker calls.
    from gdpval_qc.llm_client import get_last_usage
    assert get_last_usage() == []


def test_reset_accumulated_usage_clears() -> None:
    reset_accumulated_usage()
    _store_usage([ModelUsage.from_tokens("gpt-5.5", 10, 10)])
    assert len(get_accumulated_usage()) == 1
    reset_accumulated_usage()
    assert get_accumulated_usage() == []

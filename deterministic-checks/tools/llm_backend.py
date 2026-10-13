#!/usr/bin/env python3
"""Provider-agnostic single LLM call, so Check A (content audit, see CHECK_META["A"]
in tools/svc_qc_tracker_build.py) and anything else that needs one LLM call can run
for anyone on the QC team, not just whoever has a Claude Code session open.

Two backends, tried in this order, first one actually usable wins:

  1. Claude Code CLI, non-interactive (`claude -p ...`). Free under a Claude Code
     Max plan for whoever runs this from their own logged-in machine. This script
     never sees or handles a credential on this path - auth is whatever `claude`
     is already logged into. If the CLI is present but not logged in (e.g. run
     inside a sandboxed subprocess with no login session), that attempt fails and
     falls through to backend 2.

  2. A generic HTTP call to an OpenAI-compatible or Anthropic-compatible endpoint,
     ONLY if the caller has set these themselves - none of them is ever
     hardcoded, generated, or defaulted to a real value here:

       LLM_API_KEY         required. The caller's own key. Never logged, never
                            written anywhere by this script.
       LLM_API_BASE_URL     required. Provider API root, INCLUDING any version
                            segment the provider expects, e.g.
                            https://api.anthropic.com/v1 (Anthropic) or
                            https://api.openai.com/v1 (OpenAI) or the equivalent
                            root for a self-hosted OpenAI-compatible server.
       LLM_API_PROVIDER     required. "anthropic" or "openai" - selects the
                            request shape (see build_http_request below).
       LLM_API_MODEL        required. The exact model id your provider expects.
                            Not guessed or defaulted, since a wrong guess fails
                            louder than an explicit "you must set this."
       LLM_API_MAX_TOKENS   optional. Defaults to 4096.

     Request shapes sent on this path (both stdlib urllib, no new dependency):

       Anthropic:  POST {LLM_API_BASE_URL}/messages
                   headers: content-type: application/json
                            x-api-key: <LLM_API_KEY>
                            anthropic-version: 2023-06-01
                   body:    {"model": ..., "max_tokens": ..., "messages":
                            [{"role": "user", "content": <prompt>}],
                            "system": <system>}  # system key omitted if unset

       OpenAI:     POST {LLM_API_BASE_URL}/chat/completions
                   headers: content-type: application/json
                            authorization: Bearer <LLM_API_KEY>
                   body:    {"model": ..., "max_tokens": ..., "messages":
                            [{"role": "system", "content": <system>},  # omitted if unset
                             {"role": "user", "content": <prompt>}]}

If neither backend is available, call_llm raises LLMBackendError naming exactly
what to set. It never fails silently and never fabricates a response.

No key is ever stored, generated, or defaulted by this script. Nothing here
makes a real network call unless the caller has already put their own key in
their own environment.

CLI usage:
    python tools/llm_backend.py --prompt "..." [--system "..."]
    python tools/llm_backend.py --prompt "..." --dry-run   # see "Dry run" below

Dry run: pass --dry-run (or call build_http_request directly) to see the exact
HTTP request backend 2 would send - method, url, headers (key redacted), body -
without sending it and without needing a real key. Use this to check the
request shape is right before ever setting a real LLM_API_KEY. This path never
touches the CLI backend.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request


class LLMBackendError(RuntimeError):
    """Raised when no backend is available, or the one tried failed."""


# ---------------------------------------------------------------------------
# Backend 1: Claude Code CLI
# ---------------------------------------------------------------------------


def _version_sort_key(version_dir_name: str):
    parts = version_dir_name.split(".")
    return tuple(int(p) if p.isdigit() else p for p in parts)


def _find_claude_cli() -> str | None:
    """Locate a runnable `claude` binary, or return None.

    Order: an explicit CLAUDE_CODE_BIN override, then the normal PATH lookup
    (how most installs - the official installer, npm global install - put it),
    then, on Windows only, the versioned desktop-app bundle directory that has
    no PATH entry and no stable "current" pointer, so the highest version
    present is used.
    """
    override = os.environ.get("CLAUDE_CODE_BIN")
    if override:
        return override if os.path.isfile(override) else None

    found = shutil.which("claude")
    if found:
        return found

    if sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude-code")
        if os.path.isdir(base):
            candidates = [
                d
                for d in os.listdir(base)
                if os.path.isfile(os.path.join(base, d, "claude.exe"))
            ]
            if candidates:
                candidates.sort(key=_version_sort_key)
                return os.path.join(base, candidates[-1], "claude.exe")

    return None


def _call_claude_cli(
    claude_bin: str, prompt: str, system: str | None = None, timeout: int = 180
) -> str:
    # The prompt goes on stdin, never as an argv element. Windows caps an
    # assembled CreateProcess command line at ~32,767 chars; a prompt past
    # that raised FileNotFoundError [WinError 206] (a misleading name - it's
    # a length limit, not a missing file), silently killing every call whose
    # prompt was long enough, confirmed empirically 2026-09-16 (72/131 errors
    # in one real run). --system-prompt stays on argv since it's a short,
    # fixed per-check string, not variable-length caller content.
    args = [claude_bin, "-p", "--output-format", "json"]
    if system:
        args += ["--system-prompt", system]
    model = os.environ.get("CLAUDE_CODE_MODEL")
    if model:
        args += ["--model", model]

    try:
        proc = subprocess.run(
            args,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except OSError as exc:
        # FileNotFoundError, and also ENOEXEC "Exec format error" while the claude binary is mid auto-update
        # (35-0-0 parked as a "tool bug" on 2026-09-23 from exactly that). An LLMBackendError is infra, not a crash.
        raise LLMBackendError(f"binary not runnable at {claude_bin}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise LLMBackendError(f"timed out after {timeout}s") from exc

    stdout = proc.stdout.strip()
    if not stdout:
        stderr = proc.stderr.strip()[:2000]
        raise LLMBackendError(
            f"produced no output (exit code {proc.returncode}); stderr: {stderr}"
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise LLMBackendError(
            f"output was not valid JSON (exit code {proc.returncode}): {stdout[:2000]}"
        ) from exc

    if data.get("is_error"):
        message = data.get("result", "(no message)")
        raise LLMBackendError(
            f'returned an error: {message}. If this says "Not logged in", run '
            "`claude /login` once in a normal terminal - a fresh subprocess with "
            "no prior login session cannot pick that up, even when the binary "
            "itself runs fine."
        )

    result = data.get("result")
    if not result:
        raise LLMBackendError(f"returned no result text: {stdout[:2000]}")
    return result


# ---------------------------------------------------------------------------
# Backend 2: generic HTTP (OpenAI-compatible or Anthropic-compatible)
# ---------------------------------------------------------------------------

_REQUIRED_HTTP_ENV = (
    "LLM_API_KEY",
    "LLM_API_BASE_URL",
    "LLM_API_PROVIDER",
    "LLM_API_MODEL",
)


def build_http_request(
    prompt: str, system: str | None = None
) -> tuple[str, str, dict, dict]:
    """Build the (method, url, headers, body) backend 2 would send, and nothing else.

    Pure function, no network call. Reads LLM_API_KEY / LLM_API_BASE_URL /
    LLM_API_PROVIDER / LLM_API_MODEL / LLM_API_MAX_TOKENS from the environment
    each time it's called - never cached, never hardcoded, never defaulted to
    a real value. Both the real HTTP call and --dry-run go through this same
    function, so the two can never structurally diverge.
    """
    env = {name: os.environ.get(name) for name in _REQUIRED_HTTP_ENV}
    missing = [name for name, value in env.items() if not value]
    if missing:
        raise LLMBackendError(
            "not configured - missing env var(s): "
            + ", ".join(missing)
            + ". Set LLM_API_KEY (your own key, never this script's), "
            "LLM_API_BASE_URL (provider API root including any version segment, "
            "e.g. https://api.anthropic.com/v1 or https://api.openai.com/v1), "
            'LLM_API_PROVIDER ("anthropic" or "openai"), and LLM_API_MODEL '
            "(the exact model id your provider expects)."
        )

    provider = env["LLM_API_PROVIDER"].strip().lower()
    base_url = env["LLM_API_BASE_URL"].rstrip("/")
    model = env["LLM_API_MODEL"]
    key = env["LLM_API_KEY"]
    max_tokens = int(os.environ.get("LLM_API_MAX_TOKENS") or "4096")

    if provider == "anthropic":
        url = f"{base_url}/messages"
        headers = {
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
    elif provider == "openai":
        url = f"{base_url}/chat/completions"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {key}",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {"model": model, "max_tokens": max_tokens, "messages": messages}
    else:
        raise LLMBackendError(
            f'LLM_API_PROVIDER must be "anthropic" or "openai", got {provider!r}'
        )

    return "POST", url, headers, body


def _mask_headers(headers: dict) -> dict:
    masked = dict(headers)
    for name in ("x-api-key", "authorization"):
        if name in masked:
            value = masked[name]
            masked[name] = (
                (value[:10] + "...<redacted>") if len(value) > 10 else "<redacted>"
            )
    return masked


def _extract_http_text(provider: str, data: dict) -> str:
    provider = provider.strip().lower()
    if provider == "anthropic":
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text:
            raise LLMBackendError(
                f"Anthropic-compatible response had no text content: {json.dumps(data)[:2000]}"
            )
        return text
    if provider == "openai":
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMBackendError(
                f"OpenAI-compatible response had no message content: {json.dumps(data)[:2000]}"
            ) from exc
        # Observed for real against an OpenAI-compatible gateway (2026-09-16): a 200 response
        # with a well-formed choices[0].message.content that is itself an empty string --
        # roughly 7 of 8 real calls in one session. The Anthropic branch above already raises
        # on this shape (`if not text: raise`); this branch silently returned "" instead, so an
        # empty completion looked identical to a real "nothing to report" answer all the way
        # down to parse_llm_response()'s own generic "empty response" message, several layers
        # removed from this actual cause. Raising here instead gives the caller the same signal
        # the Anthropic branch already gives, named for what it is.
        if not text:
            raise LLMBackendError(
                f"OpenAI-compatible response had an empty message.content: {json.dumps(data)[:2000]}"
            )
        return text
    raise LLMBackendError(f"unknown provider {provider!r}")


def _call_http_backend(
    prompt: str, system: str | None = None, timeout: int = 120
) -> str:
    method, url, headers, body = build_http_request(prompt, system)
    provider = os.environ["LLM_API_PROVIDER"]

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise LLMBackendError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMBackendError(f"request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        # Observed for real (2026-09-16): urlopen()'s timeout= argument covers
        # the connect phase reliably (a connect-phase failure surfaces as
        # URLError, caught above), but a stall during the response-read phase
        # (server accepted the connection, then never sent a reply) can raise
        # a bare socket TimeoutError that is NOT a URLError instance, so the
        # except clause above never catches it. Uncaught, that bare exception
        # skipped every caller's own `except LLMBackendError` handling
        # (rubric_overspecification_check.py, golden_groundedness_check.py)
        # and fell all the way through to their generic per-task catch-all
        # wrapper, reporting "unexpected exception in audit_task:
        # TimeoutError('timed out')" instead of a proper, actionable backend
        # error. Converting it here restores the same detailed error path
        # every other failure mode already gets.
        raise LLMBackendError(f"request timed out after {timeout}s: {exc}") from exc

    data = json.loads(raw)
    return _extract_http_text(provider, data)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _call_llm_once(
    prompt: str, system: str | None, timeout_kwargs: dict
) -> tuple[str | None, list[str]]:
    """One pass over both backends. Returns (result_or_None, attempts_log)."""
    forced = os.environ.get("LLM_BACKEND_FORCE", "").strip().lower()
    attempts: list[str] = []

    if forced != "http":
        claude_bin = _find_claude_cli()
        if claude_bin:
            try:
                return (
                    _call_claude_cli(claude_bin, prompt, system, **timeout_kwargs),
                    attempts,
                )
            except LLMBackendError as exc:
                attempts.append(f"Claude Code CLI ({claude_bin}): {exc}")
        else:
            attempts.append(
                "Claude Code CLI: not found (checked $CLAUDE_CODE_BIN, PATH, "
                "and the Windows desktop-app bundle location)"
            )
        if forced == "cli":
            return None, attempts

    have_http_config = all(os.environ.get(name) for name in _REQUIRED_HTTP_ENV)
    if have_http_config:
        try:
            return _call_http_backend(prompt, system, **timeout_kwargs), attempts
        except LLMBackendError as exc:
            attempts.append(f"HTTP backend: {exc}")
    else:
        attempts.append(
            "HTTP backend: not configured (set LLM_API_KEY, LLM_API_BASE_URL, "
            "LLM_API_PROVIDER, LLM_API_MODEL to use it)"
        )
    return None, attempts


def call_llm(prompt: str, system: str | None = None, timeout: int | None = None) -> str:
    """Get one completion from whichever backend is actually usable.

    Tries the Claude Code CLI first (free, no key handling here), then the
    caller-configured HTTP backend. Raises LLMBackendError naming exactly what
    to set if neither works - never returns a fabricated response.

    timeout: optional per-call override in seconds, passed through to
    whichever backend actually runs (_call_claude_cli defaults to 180s,
    _call_http_backend to 120s, when this is left as None). Added so a caller
    with a slower/heavier prompt (a large audit-sized rubric+golden text) can
    ask for more time without every other caller having to know about it.

    Set LLM_BACKEND_FORCE=cli or =http to skip the probe and require one
    specific backend (useful for testing which path is actually being hit).

    Retries the whole two-backend pass once, after a short delay, before
    giving up. Added 2026-09-16: a real run found zero retry anywhere in this
    file, so one hiccup on either backend was terminal for that task. This
    does not help a persistent state (an actual "not logged in" session needs
    `claude /login`, retrying won't fix that), but it gives a genuinely
    transient failure - a busy backend, a momentary connection drop - a
    second chance. Bounded: at most one retry, so worst case is roughly
    double the single-attempt latency, not unbounded.
    """
    forced = os.environ.get("LLM_BACKEND_FORCE", "").strip().lower()
    timeout_kwargs = {} if timeout is None else {"timeout": timeout}

    result, attempts_1 = _call_llm_once(prompt, system, timeout_kwargs)
    if result is not None:
        return result

    time.sleep(2)
    result, attempts_2 = _call_llm_once(prompt, system, timeout_kwargs)
    if result is not None:
        return result

    all_attempts = [f"[attempt 1] {a}" for a in attempts_1] + [
        f"[attempt 2] {a}" for a in attempts_2
    ]

    if forced == "cli":
        raise LLMBackendError(
            "LLM_BACKEND_FORCE=cli but that backend failed twice:\n"
            + "\n".join(f"  - {a}" for a in all_attempts)
        )

    raise LLMBackendError(
        "No LLM backend available after 2 attempts.\n"
        + "\n".join(f"  - {a}" for a in all_attempts)
        + "\n\nTo fix: either log into the Claude Code CLI in a normal terminal "
        "(`claude /login`, or `claude auth status` to check first) so this can "
        "shell out to it for free under your Max plan, or set your own "
        "LLM_API_KEY / LLM_API_BASE_URL / LLM_API_PROVIDER / LLM_API_MODEL to "
        "call a provider directly. This script never stores or invents a key."
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Provider-agnostic single LLM call. Tries the Claude Code CLI first, "
            "then a caller-configured HTTP backend. See this file's module "
            "docstring for the env vars the HTTP backend reads."
        )
    )
    ap.add_argument("--prompt", required=True, help="The prompt to send.")
    ap.add_argument("--system", default=None, help="Optional system prompt.")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the HTTP request the API-key backend would send (key "
            "redacted) and exit, without sending it and without touching the "
            "CLI backend. Requires the same LLM_API_* env vars as the real "
            "call, since the shape depends on the provider."
        ),
    )
    args = ap.parse_args(argv)

    if args.dry_run:
        try:
            method, url, headers, body = build_http_request(args.prompt, args.system)
        except LLMBackendError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "method": method,
                    "url": url,
                    "headers": _mask_headers(headers),
                    "body": body,
                },
                indent=2,
            )
        )
        return 0

    try:
        print(call_llm(args.prompt, args.system))
        return 0
    except LLMBackendError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

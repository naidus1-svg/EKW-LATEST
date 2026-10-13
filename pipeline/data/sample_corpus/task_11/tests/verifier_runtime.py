#!/usr/bin/env python3
"""Hard-cutover v3 Harbor task verifier entrypoint."""

import os
import sys
import logging
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from verifier_lib.runner import (  # noqa: E402
    build_failure_payload,
    run_verifier as _run_verifier,
    write_outputs,
)


TESTS_DIR = Path(os.environ.get("TESTS_DIR", "/tests"))
VERIFIER_DIR = Path(os.environ.get("VERIFIER_DIR", "/logs/verifier"))
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
AGENT_LOGS_DIR = Path(os.environ.get("AGENT_LOGS_DIR", "/logs/agent"))
VERIFIER_JSON = TESTS_DIR / "verifier.json"
MAX_CONTENT_CHARS = int(os.environ.get("VERIFIER_MAX_CONTENT", "90000"))


def configure_logging() -> None:
    """Configures timestamped runtime logging for the verifier process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    for logger_name in ("LiteLLM", "LiteLLM Proxy", "LiteLLM Router"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def main() -> int:
    """Runs the Harbor verifier entrypoint.

    Returns:
        Process exit code. Zero means grading completed and reward artifacts
        were written; non-zero means verifier infrastructure failed.
    """
    configure_logging()
    logger = logging.getLogger(__name__)

    if not VERIFIER_JSON.exists():
        message = f"{VERIFIER_JSON} not found"
        logger.error(message)
        write_outputs(build_failure_payload(message), VERIFIER_DIR)
        return 1
    try:
        payload = _run_verifier(
            VERIFIER_JSON,
            workspace_dir=WORKSPACE_DIR,
            verifier_dir=VERIFIER_DIR,
            agent_logs_dir=AGENT_LOGS_DIR,
            max_content_chars=MAX_CONTENT_CHARS,
        )
    except Exception as exc:
        logger.exception("Verifier failed")
        if not (VERIFIER_DIR / "verifier-report.json").exists():
            write_outputs(build_failure_payload(str(exc)), VERIFIER_DIR)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

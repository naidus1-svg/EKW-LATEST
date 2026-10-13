#!/usr/bin/env python3
"""Check the `python qc.py ...` command lines in the two run sheets against the real qc.py.

    python docs/test_runsheet_commands.py          (or: python -m unittest docs/test_runsheet_commands.py -v)

Stdlib only. It reads docs/QC-RUNBOOK-qc-person.md and docs/QC-RUNBOOK-manager.md and takes every command line that
starts with `python qc.py`: the lines inside code blocks and the inline `code` spans. For each one it runs only
`python qc.py --no-update <subcommand> -h`, which prints help and exits before any command code runs, so the test
never reaches a command that calls a model or touches the network. Then it checks that

  1. the subcommand exists,
  2. every --option on the line is listed in that subcommand's help,
  3. a value given to an option with a fixed list of choices (--tab) is one of the choices, and so is the word
     after `proof` (init or check),
  4. in a code block, the number of plain arguments fits the usage line (inline spans may be partial, so they skip this).

The sheets' own rule for code blocks is checked too: a command that has <placeholders> or [optional parts] is followed
by a line `# Example ...` and one example line with made-up names and no angle or square brackets.

In a command line, <anything> counts as one value and a [bracketed part] may repeat or be left out.
To test against another copy of qc.py (for example one that has an option the sheets mention early):
    QC_PY=C:/path/to/qc.py python docs/test_runsheet_commands.py
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import unittest
import warnings
from pathlib import Path

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
QC = Path(os.environ.get("QC_PY") or ROOT / "qc.py")
SHEETS = [DOCS / "QC-RUNBOOK-qc-person.md", DOCS / "QC-RUNBOOK-manager.md"]

# Options the run sheets mention before qc.py has them: (subcommand, option) -> allowed values.
# `proof --tab` comes with the golden-answer block (branch golden-hold-2026-10-09). Until that is merged, a qc.py
# without the option is accepted for exactly these pairs and the test prints a warning. Delete the entry when it lands;
# AheadOfCode below warns you when it is no longer needed.
AHEAD_OF_CODE = {}

FENCE = re.compile(r"^\s*(```|~~~)")
SPAN = re.compile(r"`([^`\n]+)`")
STARTS = re.compile(r"^python\s+qc\.py(\s|$)")
BRACKETS = re.compile(r"[<>\[\]]")


class Cmd:
    def __init__(
        self, sheet: str, line: int, text: str, fenced: bool, block: int, example: bool
    ):
        self.sheet, self.line, self.text, self.fenced, self.block, self.example = (
            sheet,
            line,
            text,
            fenced,
            block,
            example,
        )

    def where(self) -> str:
        return f"{self.sheet}:{self.line}: {self.text}"


def commands_in(path: Path) -> list[Cmd]:
    """Every `python qc.py ...` command in a sheet, in file order."""
    found: list[Cmd] = []
    in_fence, block, labelled = False, 0, False
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(raw):
            in_fence = not in_fence
            block += in_fence
            labelled = False
            continue
        if in_fence:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                labelled = line.lower().startswith("# example")
                continue
            if STARTS.match(line):
                found.append(Cmd(path.name, n, line, True, block, labelled))
            labelled = False
            continue
        for m in SPAN.finditer(raw):
            span = m.group(1).strip()
            if STARTS.match(span):
                found.append(Cmd(path.name, n, span, False, 0, False))
    return found


class Help:
    """What `python qc.py --no-update <sub> -h` says: its options, its choices and how many plain arguments fit."""

    def __init__(self, text: str):
        head = text.split("\n\n", 1)[0]  # the usage block ends at the first blank line
        usage = " ".join(head.split())
        parts = usage.split(None, 3)  # usage: qc.py <sub> <the rest>
        rest = parts[3] if len(parts) > 3 else ""
        # option -> allowed values (None: any value; empty set: takes no value)
        self.options: dict[str, set[str] | None] = {}
        for name, metavar in re.findall(r"\[(-{1,2}[\w-]+)(?:\s+([^\]\s]+))?\]", rest):
            if not metavar:
                self.options[name] = set()
            elif metavar.startswith("{"):
                self.options[name] = set(metavar.strip("{}").split(","))
            else:
                self.options[name] = None
        positional = re.sub(r"\[-{1,2}[\w-]+(?:\s+[^\]\s]+)?\]", " ", rest)
        required = [
            t for t in re.sub(r"\[[^\]]*\]", " ", positional).split() if t != "..."
        ]
        groups = re.findall(r"\[([^\]]*)\]", positional)
        self.min_args = len(required)
        self.max_args = None if "..." in positional else len(required) + len(groups)
        self.first_choices = (
            set(required[0].strip("{}").split(","))
            if required and required[0].startswith("{")
            else None
        )


_cache: dict[str, Help | None] = {}


def real_help(sub: str) -> Help | None:
    """Help for one subcommand of the real qc.py, or None when qc.py has no such subcommand."""
    if sub not in _cache:
        env = dict(os.environ, NO_COLOR="1", PYTHONIOENCODING="utf-8")
        env.pop("FORCE_COLOR", None)
        done = subprocess.run(
            [sys.executable, str(QC), "--no-update", sub, "-h"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(QC.parent),
            timeout=120,
        )
        _cache[sub] = Help(done.stdout) if done.returncode == 0 else None
    return _cache[sub]


def tokens(text: str) -> tuple[list[str], list[str], bool]:
    """(words outside [brackets], --options found inside [brackets], whether there were [brackets]) of one command line."""
    text = re.sub(r"\s+#.*$", "", text)  # a trailing comment
    text = re.sub(r"<[^<>]*>", "X", text)  # <a placeholder> stands for one value
    inside = re.findall(r"\[([^\]]*)\]", text)
    outside = re.sub(r"\[[^\]]*\]", " ", text)
    words = [w.strip('"') for w in shlex.split(outside, posix=False) if w != "..."]
    optional = [w for part in inside for w in part.split() if w.startswith("--")]
    return words, optional, bool(inside)


def check_command(cmd: Cmd, get_help=real_help) -> tuple[list[str], list[str]]:
    """(problems, notes) for one command line. A note means the line relies on AHEAD_OF_CODE."""
    problems: list[str] = []
    notes: list[str] = []
    words, optional, has_optional = tokens(cmd.text)
    rest = words[2:]
    if rest and rest[0] == "--no-update":
        rest = rest[1:]
    if not rest:
        return ([] if not cmd.fenced else ["no subcommand after python qc.py"]), notes
    sub, args = rest[0], rest[1:]
    info = get_help(sub)
    if info is None:
        return [f"qc.py has no subcommand {sub!r}"], notes

    def known(option: str) -> set[str] | None | bool:
        """The option's allowed values, or False when qc.py does not take it."""
        if option in info.options or option == "--help":
            return info.options.get(option, set())
        if (sub, option) in AHEAD_OF_CODE:
            notes.append(
                f"{sub} {option} is in the sheets before it is in this qc.py (AHEAD_OF_CODE)"
            )
            return AHEAD_OF_CODE[(sub, option)]
        return False

    for option in optional:
        if known(option) is False:
            problems.append(f"{sub} does not take {option}")
    positionals: list[str] = []
    i = 0
    while i < len(args):
        word = args[i]
        i += 1
        if word.startswith("--"):
            name, eq, value = word.partition("=")
            allowed = known(name)
            if allowed is False:
                problems.append(f"{sub} does not take {name}")
                continue
            if allowed != set():  # the option takes a value
                if not eq:
                    value = args[i] if i < len(args) else ""
                    i += 1
                if not value:
                    problems.append(f"{name} needs a value")
                elif allowed and value not in allowed:
                    problems.append(
                        f"{name} {value}: choose one of {', '.join(sorted(allowed))}"
                    )
        elif word.startswith("-") and len(word) > 1:
            if word not in ("-h",):
                problems.append(f"{sub} does not take {word}")
        else:
            positionals.append(word)
    if info.first_choices and positionals and positionals[0] not in info.first_choices:
        problems.append(
            f"{sub} {positionals[0]}: choose one of {', '.join(sorted(info.first_choices))}"
        )
    if cmd.fenced:
        if len(positionals) < info.min_args:
            problems.append(
                f"{sub} needs at least {info.min_args} plain argument(s), the line has {len(positionals)}"
            )
        if (
            not has_optional
            and info.max_args is not None
            and len(positionals) > info.max_args
        ):
            problems.append(
                f"{sub} takes at most {info.max_args} plain argument(s), the line has {len(positionals)}"
            )
    return problems, notes


class RunSheetCommands(unittest.TestCase):
    def test_qc_py_exists(self):
        self.assertTrue(QC.is_file(), f"{QC} not found")

    def test_each_sheet_has_commands(self):
        for sheet in SHEETS:
            with self.subTest(sheet=sheet.name):
                self.assertGreaterEqual(
                    len(commands_in(sheet)), 3, "the extractor found almost no commands"
                )

    def test_commands_match_qc_py_usage(self):
        seen: set[str] = set()
        for sheet in SHEETS:
            for cmd in commands_in(sheet):
                with self.subTest(command=cmd.where()):
                    problems, notes = check_command(cmd)
                    for note in notes:
                        if note not in seen:
                            seen.add(note)
                            warnings.warn(note)
                    self.assertEqual(problems, [], cmd.where())

    def test_example_lines_follow_each_command_with_placeholders(self):
        for sheet in SHEETS:
            cmds = commands_in(sheet)
            for i, cmd in enumerate(cmds):
                if not cmd.fenced:
                    continue
                with self.subTest(command=cmd.where()):
                    if cmd.example:
                        self.assertIsNone(
                            BRACKETS.search(cmd.text),
                            "an example line must have no angle or square brackets",
                        )
                    if BRACKETS.search(cmd.text) and not cmd.example:
                        nxt = cmds[i + 1] if i + 1 < len(cmds) else None
                        ok = (
                            nxt is not None
                            and nxt.fenced
                            and nxt.block == cmd.block
                            and nxt.example
                        )
                        self.assertTrue(
                            ok,
                            "a command with placeholders needs '# Example ...' and an example line under it",
                        )
                        self.assertEqual(
                            tokens(cmd.text)[0][2:3],
                            tokens(nxt.text)[0][2:3],
                            "the example uses another subcommand",
                        )


class AheadOfCode(unittest.TestCase):
    def test_allowance_is_still_needed(self):
        for sub, option in AHEAD_OF_CODE:
            info = real_help(sub)
            if info is not None and option in info.options:
                warnings.warn(
                    f"qc.py {sub} now takes {option}: delete ({sub!r}, {option!r}) from AHEAD_OF_CODE"
                )


READ_HELP = """usage: qc.py read [-h] [--out OUT] [--tab {EKW,SVC,ekw,svc}] [--times TIMES]
                   task_folder

positional arguments:
  task_folder
"""
PROOF_HELP = """usage: qc.py proof [-h] {init,check} task_folder

positional arguments:
  {init,check}
"""
MANAGE_HELP = """usage: qc.py manage [-h] [--out OUT] [--tab {EKW,SVC,ekw,svc}]
                    inputs [inputs ...]

positional arguments:
  inputs
"""
CHECKS_HELP = """usage: qc.py checks [-h] root [stage] [out]

positional arguments:
  root
"""
UPDATE_HELP = "usage: qc.py update [-h]\n\noptions:\n  -h, --help  show this help message and exit\n"
CANNED = {
    "read": Help(READ_HELP),
    "proof": Help(PROOF_HELP),
    "manage": Help(MANAGE_HELP),
    "checks": Help(CHECKS_HELP),
    "update": Help(UPDATE_HELP),
}


class ValidatorSelfTests(unittest.TestCase):
    """The checker can fail: canned help text (copied from qc.py -h), so these need no qc.py at all."""

    def problems(self, text: str, fenced: bool = True) -> list[str]:
        return check_command(Cmd("t.md", 1, text, fenced, 1, False), CANNED.get)[0]

    def test_good_lines_pass(self):
        for text in (
            "python qc.py update",
            "python qc.py read C:/qc/tasks/EKW-123 --out read_EKW-123",
            "python qc.py read <task folder> --out read_<task name> --tab EKW",
            "python qc.py proof check <rev folder>",
            "python qc.py manage <zip> [<zip> ...] --out qc_manage_out",
            "python qc.py manage a.zip b.zip --out qc_manage_out",
            "python qc.py checks C:/qc/tasks",
            "python qc.py read C:/qc/tasks/EKW-123 --out read_EKW-123   # a trailing comment",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.problems(text), [])

    def test_bad_lines_fail(self):
        for text, fragment in (
            ("python qc.py nope a", "no subcommand"),
            ("python qc.py read a --outdir x", "does not take --outdir"),
            ("python qc.py read a --tab FOO", "choose one of"),
            ("python qc.py read a --out", "needs a value"),
            ("python qc.py proof run <rev folder>", "choose one of check, init"),
            ("python qc.py read", "at least 1"),
            ("python qc.py read a b", "at most 1"),
            ("python qc.py update now", "at most 0"),
            ("python qc.py", "no subcommand"),
        ):
            with self.subTest(text=text):
                found = self.problems(text)
                self.assertTrue(any(fragment in p for p in found), found)

    def test_an_inline_span_may_be_partial(self):
        self.assertEqual(self.problems("python qc.py read", fenced=False), [])
        self.assertEqual(self.problems("python qc.py", fenced=False), [])
        self.assertTrue(self.problems("python qc.py read --nope", fenced=False))

    def test_extractor_reads_blocks_and_spans(self):
        tmp = DOCS / "_runsheet_selftest.tmp.md"
        tmp.write_text(
            "Run `python qc.py update` first. Then `qc.py read` alone is only a name.\n\n```\n"
            "python qc.py read <task folder> --out read_<task name>\n# Example (made-up names):\n"
            "python qc.py read C:/qc/tasks/EKW-123 --out read_EKW-123\ngit status\n```\n",
            encoding="utf-8",
        )
        try:
            found = commands_in(tmp)
        finally:
            tmp.unlink()
        self.assertEqual(
            [(c.fenced, c.example) for c in found],
            [(False, False), (True, False), (True, True)],
        )


if __name__ == "__main__":
    unittest.main()

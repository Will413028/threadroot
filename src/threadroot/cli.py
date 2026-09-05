from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import sys

from . import __version__
from .operations import run_adopt, run_doctor, run_init, run_claim
from .paths import resolve_vault, filesystem_error
from .results import CommandResult, ExitCode, Issue, ThreadrootError


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ThreadrootError(ExitCode.USAGE, "usage.invalid", "Invalid arguments; run threadroot --help.")


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="threadroot", allow_abbrev=False)
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    for command in ("init", "adopt", "doctor", "claim"):
        subparser = subparsers.add_parser(command, allow_abbrev=False)
        subparser.add_argument("--vault")
        subparser.add_argument("--json", action="store_true")
        if command in ("init", "adopt", "claim"):
            subparser.add_argument("--apply", action="store_true")
        if command in ("init", "adopt"):
            subparser.add_argument("--set-default", action="store_true")
        if command == "claim":
            subparser.add_argument("--path", required=True)
    return parser


def execute(
    args: argparse.Namespace,
    cwd: Path,
    environ: Mapping[str, str],
    home: Path,
) -> CommandResult:
    command = args.command
    if command not in ("init", "adopt", "doctor", "claim"):
        raise ThreadrootError(ExitCode.USAGE, "usage.invalid", "A command is required.")

    root: Path | None = None
    try:
        root = resolve_vault(args.vault, cwd, environ, home)
        if command == "init":
            return run_init(root, args.apply, args.set_default, environ, home)
        if command == "adopt":
            return run_adopt(root, args.apply, args.set_default, environ, home)
        if command == "claim":
            return run_claim(root, args.path, args.apply)
        return run_doctor(root)
    except (ThreadrootError, OSError) as caught:
        error = caught if isinstance(caught, ThreadrootError) else filesystem_error()
        return CommandResult(
            ok=False,
            command=command,
            applied=False,
            vault=str(root) if root is not None else None,
            issues=(Issue("error", error.code, error.message, error.path),),
            exit_code=error.exit_code,
        )


def render_json(result: CommandResult) -> str:
    return json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def render_human(result: CommandResult) -> str:
    if result.ok:
        if result.command == "doctor":
            state = "checked"
        else:
            state = "applied" if result.applied else "preview"
        summary = f"OK {result.command} {state}"
    else:
        summary = f"ERROR {result.command}"
    if result.vault is not None:
        summary += f" {result.vault}"

    lines = [summary]
    lines.extend(
        f"[{change.status}] {change.action} {change.path}"
        for change in result.changes
    )
    for issue in result.issues:
        suffix = f" ({issue.path})" if issue.path is not None else ""
        lines.append(f"{issue.level.upper()} {issue.code}: {issue.message}{suffix}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command is None and not args.version:
            parser.error("a command is required")
    except ThreadrootError as error:
        print(f"ERROR {error.code}: {error.message}", file=sys.stderr)
        return int(error.exit_code)

    if args.version:
        print(f"threadroot {__version__}")
        return int(ExitCode.OK)

    result = execute(args, Path.cwd(), os.environ, Path.home())
    rendered = render_json(result) if args.json else render_human(result)
    print(rendered, file=sys.stdout if args.json or result.ok else sys.stderr)
    return int(result.exit_code)

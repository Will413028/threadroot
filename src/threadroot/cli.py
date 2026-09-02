from __future__ import annotations

import argparse
import sys

from . import __version__
from .results import ExitCode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="threadroot")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("command", choices=("init", "adopt", "doctor"), nargs="?")
    args = parser.parse_args(argv)
    if args.version:
        print(f"threadroot {__version__}")
        return int(ExitCode.OK)
    if args.command is None:
        parser.print_help(sys.stderr)
        return int(ExitCode.USAGE)
    return int(ExitCode.OK)

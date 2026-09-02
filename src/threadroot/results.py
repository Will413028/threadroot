from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Literal

CommandName = Literal["init", "adopt", "doctor"]
ActionName = Literal["create_directory", "create_file", "write_default_pointer"]
ChangeStatus = Literal["planned", "completed", "unexecuted"]
IssueLevel = Literal["error", "warning", "info"]


class ExitCode(IntEnum):
    OK = 0
    USAGE = 2
    CONFIG = 3
    UNSAFE_PATH = 4
    CONFLICT = 5
    IO_OR_DRIFT = 6


@dataclass(frozen=True)
class Change:
    action: ActionName
    path: str
    status: ChangeStatus


@dataclass(frozen=True)
class Issue:
    level: IssueLevel
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    command: CommandName
    applied: bool
    vault: str | None
    changes: tuple[Change, ...] = ()
    issues: tuple[Issue, ...] = ()
    exit_code: ExitCode = ExitCode.OK

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "command": self.command,
            "applied": self.applied,
            "vault": self.vault,
            "changes": [asdict(change) for change in self.changes],
            "issues": [asdict(issue) for issue in self.issues],
        }


class ThreadrootError(Exception):
    def __init__(
        self,
        exit_code: ExitCode,
        code: str,
        message: str,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code
        self.message = message
        self.path = path

from __future__ import annotations

from collections.abc import Mapping, Sequence

from dataclasses import dataclass
from pathlib import Path
import re


CONTRACT_KEYS = {
    "new-file",
    "claim-failure",
    "claim-verification",
    "partial-state",
    "outside-vault-create",
    "extends",
    "drift",
    "secrets",
    "confirmation-order",
    "confirmation-cadence",
    "local-adapter",
    "write-gate",
    "decision-gate",
    "draft-gate",
    "followup-routing",
    "project-backlink",
    "supersession",
}


@dataclass(frozen=True)
class SkillDocument:
    name: str
    description: str
    body: str


@dataclass(frozen=True)
class EffectiveSkillContract:
    commands: frozenset[str]
    invariants: tuple[tuple[str, str], ...]


def load_skill(name: str) -> SkillDocument:
    path = Path("skills") / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    match = re.fullmatch(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if match is None:
        raise AssertionError(f"{path} must have one YAML frontmatter block")

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise AssertionError(f"invalid frontmatter line in {path}: {line}")
        key = key.strip()
        if key in fields:
            raise AssertionError(f"duplicate frontmatter key in {path}: {key}")
        fields[key] = value.strip().strip('"')

    if set(fields) != {"name", "description"}:
        raise AssertionError(f"{path} frontmatter keys must be name and description")
    if not fields["name"] or not fields["description"]:
        raise AssertionError(f"{path} frontmatter values must not be empty")
    return SkillDocument(fields["name"], fields["description"], match.group(2))


def _contract_fields(path: Path, text: str) -> dict[str, str]:
    matches = re.findall(
        r"<!-- threadroot-contract\n(.*?)\n-->",
        text,
        re.DOTALL,
    )
    if len(matches) != 1:
        raise AssertionError(f"{path} must have one threadroot contract block")

    fields: dict[str, str] = {}
    for line in matches[0].splitlines():
        key, separator, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not separator or not key or not value:
            raise AssertionError(f"invalid contract line in {path}: {line}")
        if key not in CONTRACT_KEYS:
            raise AssertionError(f"unknown contract key in {path}: {key}")
        if key in fields:
            raise AssertionError(f"duplicate contract key in {path}: {key}")
        fields[key] = value
    return fields


def _threadroot_commands(text: str) -> frozenset[str]:
    marker = "threadroot-commands"
    matches = list(
        re.finditer(
            r"<!-- threadroot-commands\n(?P<commands>.*?)\n-->",
            text,
            re.DOTALL,
        )
    )
    if text.count(marker) != 1 or len(matches) != 1:
        raise AssertionError("skill must have exactly one closed command inventory")

    match = matches[0]
    lines = match.group("commands").split("\n")
    if any(not line or line != line.strip() for line in lines):
        raise AssertionError("command inventory entries must be non-empty and exact")
    if any(
        line != "threadroot" and not line.startswith("threadroot ")
        for line in lines
    ):
        raise AssertionError("command inventory entries must be Threadroot commands")
    if len(lines) != len(set(lines)):
        raise AssertionError("command inventory entries must be unique")

    outside_inventory = text[: match.start()] + text[match.end() :]
    lowercase_command = re.compile(
        r"(?<![\w-])(?:threadroot|_+threadroot_+)(?![\w-])"
    )
    if lowercase_command.search(outside_inventory):
        raise AssertionError("lowercase threadroot token outside command inventory")

    return frozenset(lines)


def load_effective_contract(
    path: Path,
    allowed_commands: frozenset[str],
) -> EffectiveSkillContract:
    path = path.resolve()
    text = path.read_text(encoding="utf-8")
    local = _contract_fields(path, text)
    extends = local.pop("extends", None)
    if extends is None:
        raise AssertionError(f"{path} contract must extend a shared contract")
    extends_path = Path(extends)
    if extends_path.is_absolute():
        raise AssertionError(f"{path} shared contract path must be relative")

    skills_root = path.parent.parent.resolve()
    shared_path = (path.parent / extends_path).resolve()
    try:
        shared_path.relative_to(skills_root)
    except ValueError:
        raise AssertionError(f"{path} shared contract escapes skills root") from None

    shared = _contract_fields(
        shared_path,
        shared_path.read_text(encoding="utf-8"),
    )
    if "extends" in shared:
        raise AssertionError(f"{shared_path} must not extend another contract")

    invariants = shared | local
    required = {
        "drift": "stop",
        "secrets": "never-read",
        "new-file": "claim-verify-native-edit",
        "claim-failure": "stop",
        "claim-verification": "same-identity-empty-regular",
        "partial-state": "preserve-and-report",
        "outside-vault-create": "independent-native-exclusive-or-omit"
    }
    for key, value in required.items():
        if invariants.get(key) != value:
            raise AssertionError(
                f"{path} effective contract requires {key}={value}"
            )

    commands = _threadroot_commands(text)
    if commands != allowed_commands:
        raise AssertionError(
            f"{path} command inventory must be exact; "
            f"extra={sorted(commands - allowed_commands)}, "
            f"missing={sorted(allowed_commands - commands)}"
        )

    return EffectiveSkillContract(
        commands=commands,
        invariants=tuple(sorted(invariants.items())),
    )


def _claim_result_pair(event: Mapping[str, object], applied: bool) -> tuple[str, str] | None:
    result = event.get("result")
    if (type(event.get("exit")) is not int or event["exit"] != 0
            or type(result) is not dict
            or set(result) != {"ok", "command", "applied", "vault", "changes", "issues"}):
        return None
    if (result["ok"] is not True or result["applied"] is not applied
            or result["command"] != "claim" or result["issues"] != []
            or type(result["vault"]) is not str or not result["vault"]):
        return None
    changes = result["changes"]
    if type(changes) is not list or len(changes) != 1 or type(changes[0]) is not dict:
        return None
    change = changes[0]
    if (set(change) != {"action", "path", "status"}
            or change["action"] != "create_file"
            or change["status"] != ("completed" if applied else "planned")
            or type(change["path"]) is not str or not change["path"]):
        return None
    return result["vault"], change["path"]


def validate_claim_trace(
    events: Sequence[Mapping[str, object]], *,
    expected_vault: str = "/synthetic/vault",
    expected_path: str = "daily/2042-04-03.md",
) -> tuple[str, ...]:
    state = "preview"
    pair = (expected_vault, expected_path)
    identity: list[int] | None = None
    partial = False
    failure = ("claim.unsafe-continuation",)
    for event in events:
        kind = event.get("kind")
        if kind == "stop":
            if (set(event) != {"kind", "partial"} or state != "stop"
                    or event.get("partial") is not partial):
                return failure
            state = "done"
            continue
        if state in ("stop", "done"):
            return failure
        if state in ("preview", "apply"):
            if kind != state or set(event) != {"kind", "exit", "result"}:
                return failure
            applying = state == "apply"
            if applying:
                result = event.get("result")
                changes = result.get("changes", []) if type(result) is dict else []
                completed = type(changes) is list and any(
                    type(change) is dict and change.get("status") == "completed"
                    for change in changes
                )
                partial = event.get("exit") == 0 or completed
            observed = _claim_result_pair(event, applying)
            if observed != pair:
                state = "stop"
            elif applying:
                state = "verify-first"
            else:
                state = "apply"
        elif state in ("verify-first", "verify-second"):
            if kind != "verify":
                return failure
            observed = event.get("identity")
            valid = (set(event) == {"kind", "identity", "regular", "size"}
                     and type(observed) is list and len(observed) == 2
                     and all(type(value) is int for value in observed)
                     and event.get("regular") is True
                     and type(event.get("size")) is int and event["size"] == 0)
            if not valid or (state == "verify-second" and observed != identity):
                state = "stop"
            elif state == "verify-first":
                identity = list(observed)
                state = "verify-second"
            else:
                state = "edit"
        elif state == "edit":
            if (kind != "native-edit" or set(event) != {"kind", "ok"}
                    or type(event.get("ok")) is not bool):
                return failure
            state = "done" if event["ok"] else "stop"
    return () if state == "done" else failure

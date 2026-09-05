import unittest

from threadroot.results import Change, CommandResult, ExitCode, Issue


class CommandResultTests(unittest.TestCase):
    def test_to_dict_uses_stable_public_shape(self) -> None:
        result = CommandResult(
            ok=False,
            command="doctor",
            applied=False,
            vault="/tmp/example-vault",
            changes=(Change("create_directory", "daily", "planned"),),
            issues=(Issue("error", "config.invalid", "Invalid config", ".second-brain/config.json"),),
            exit_code=ExitCode.CONFIG,
        )

        self.assertEqual(
            result.to_dict(),
            {
                "ok": False,
                "command": "doctor",
                "applied": False,
                "vault": "/tmp/example-vault",
                "changes": [
                    {"action": "create_directory", "path": "daily", "status": "planned"}
                ],
                "issues": [
                    {
                        "level": "error",
                        "code": "config.invalid",
                        "message": "Invalid config",
                        "path": ".second-brain/config.json",
                    }
                ],
            },
        )

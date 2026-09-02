import contextlib
import io
import unittest

from threadroot import __version__
from threadroot.cli import main


class VersionTests(unittest.TestCase):
    def test_version(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), f"threadroot {__version__}\n")

"""Offline behavioral checks; never connect to the cluster."""

import contextlib
import importlib.util
import io
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "scc", Path(__file__).resolve().parents[1] / "scripts" / "scc.py")
scc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scc)


class SCCTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.env_file = Path(temp.name) / ".env"
        self.env_file.write_text(
            "BUPT_SCC_HOST=cluster.example.invalid\nBUPT_SCC_PORT=2222\nBUPT_SCC_USER=test-user\n")
        patcher = patch.object(scc, "ENV_FILE", self.env_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.dict(scc.os.environ, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def command(self, *argv):
        return scc.build_command(scc.parser(scc.load_config()).parse_args(argv))

    def test_endpoint_and_batch_auth(self):
        cmd = self.command("--user", "alice", "info")
        self.assertEqual(cmd[:3], ["ssh", "-p", "2222"])
        self.assertEqual(cmd[-2], "cluster.example.invalid")
        self.assertIn("BatchMode=yes", cmd)
        self.assertIn("alice", cmd)
        self.assertFalse(any("StrictHostKeyChecking" in item for item in cmd))

    def test_interactive_login(self):
        cmd = self.command("login")
        self.assertEqual(cmd[-1], "cluster.example.invalid")
        self.assertIn("-t", cmd)
        self.assertNotIn("BatchMode=yes", cmd)

    def test_remote_exec_preserves_metacharacters(self):
        argv = ["printf", "%s", "a b; $(touch /tmp/unwanted) ' quote"]
        remote = self.command("exec", "--", *argv)[-1]
        self.assertEqual(shlex.split(remote), argv)

    def test_submit_paths_are_literal(self):
        remote = self.command("submit", "/work/a ' job.sbatch", "--workdir", "/work/a $b")[-1]
        self.assertEqual(shlex.split(remote), ["sbatch", "--parsable", "--chdir",
                                              "/work/a $b", "/work/a ' job.sbatch"])

    def test_reject_broad_cancel_and_relative_paths(self):
        for argv in [("cancel", "--all"), ("cancel", "123,456"),
                     ("submit", "relative.sbatch", "--workdir", "/work")]:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    scc.parser().parse_args(argv)
        self.assertEqual(shlex.split(self.command("cancel", "123_2")[-1]),
                         ["scancel", "123_2"])

    def test_dry_run_never_executes(self):
        with patch.object(scc.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(scc.main(["--dry-run", "submit", "/w/a.sbatch", "--workdir", "/w"]), 0)
            run.assert_not_called()

    def test_transport_error_preserved_without_retry(self):
        with patch.object(scc.subprocess, "run", return_value=subprocess.CompletedProcess([], 255)) as run:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(scc.main(["submit", "/w/a.sbatch", "--workdir", "/w"]), 255)
            run.assert_called_once()
            self.assertIn("不要直接重试", err.getvalue())
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_environment_and_cli_precedence(self):
        with patch.dict(scc.os.environ, {"BUPT_SCC_USER": "environment-user"}):
            self.assertIn("environment-user", self.command("info"))
            self.assertIn("cli-user", self.command("--user", "cli-user", "info"))

    def test_config_is_literal_and_does_not_change_environment(self):
        self.env_file.write_text(
            '# comment\n\nBUPT_SCC_IDENTITY="/keys/a $HOME $(whoami) key"\n')
        self.assertEqual(scc.load_config()["BUPT_SCC_IDENTITY"], "/keys/a $HOME $(whoami) key")
        self.assertNotIn("BUPT_SCC_IDENTITY", scc.os.environ)

    def test_invalid_config_does_not_disclose_values(self):
        for line in ['PASSWORD=private-value', 'BUPT_SCC_USER="private-value']:
            self.env_file.write_text(line)
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(scc.main(["info"]), 2)
            self.assertNotIn("private-value", err.getvalue())

    def test_missing_config_never_connects(self):
        self.env_file.unlink()
        with patch.object(scc.subprocess, "run") as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                scc.main(["info"])
            run.assert_not_called()

    def test_invalid_host_and_port_never_execute(self):
        for argv in [("--host", "-oProxyCommand=bad", "info"),
                     ("--host", "user@host", "info"), ("--port", "65536", "info")]:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises((SystemExit, ValueError)):
                    self.command(*argv)


if __name__ == "__main__":
    unittest.main()

"""Offline transport/configuration/Slurm checks; no real cluster connections."""

import contextlib
import importlib.util
import io
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "slurm", ROOT / "skills" / "bupt-slurm-skill" / "scripts" / "slurm.py")
slurm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(slurm)
scc = slurm.scc


class SkillTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.env_file = Path(temp.name) / ".env"
        self.env_file.write_text(
            "BUPT_SCC_HOST=cluster.example.invalid\nBUPT_SCC_PORT=2222\n"
            "BUPT_SCC_USER=test-user\nBUPT_SLURM_COMMENT=test-billing\n")
        for patcher in [patch.object(scc, "ENV_FILE", self.env_file),
                        patch.dict(scc.os.environ, {}, clear=True)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def command(self, module, *argv):
        return module.build_command(module.parser(scc.load_config()).parse_args(argv))

    def test_endpoint_and_batch_auth(self):
        cmd = self.command(scc, "--user", "alice", "exec", "--", "pwd")
        self.assertEqual(cmd[:3], ["ssh", "-p", "2222"])
        self.assertEqual(cmd[-2], "cluster.example.invalid")
        self.assertIn("BatchMode=yes", cmd)
        self.assertIn("alice", cmd)
        self.assertFalse(any("StrictHostKeyChecking" in item for item in cmd))

    def test_interactive_login(self):
        cmd = self.command(scc, "login")
        self.assertEqual(cmd[-1], "cluster.example.invalid")
        self.assertIn("-t", cmd)
        self.assertNotIn("BatchMode=yes", cmd)

    def test_remote_exec_preserves_metacharacters(self):
        argv = ["printf", "%s", "a b; $(touch /tmp/unwanted) ' quote"]
        remote = self.command(scc, "exec", "--", *argv)[-1]
        self.assertEqual(shlex.split(remote), argv)

    def test_submit_injects_billing_and_quotes_paths(self):
        remote = self.command(slurm, "submit", "/work/a ' job.sbatch", "--workdir", "/work/a $b",
                              "--partition", "test-partition")[-1]
        self.assertEqual(shlex.split(remote), ["sbatch", "--parsable", "--comment=test-billing",
                         "--chdir", "/work/a $b", "--partition=test-partition", "/work/a ' job.sbatch"])

    def test_reject_broad_cancel_and_relative_paths(self):
        for argv in [("cancel", "--all"), ("cancel", "123,456"),
                     ("submit", "relative.sbatch", "--workdir", "/work")]:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    slurm.parser().parse_args(argv)
        self.assertEqual(shlex.split(self.command(slurm, "cancel", "123_2")[-1]), ["scancel", "123_2"])

    def test_dry_run_never_executes_and_redacts(self):
        with patch.object(scc.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(slurm.main(["--dry-run", "submit", "/w/a.sbatch", "--workdir", "/w"]), 0)
            run.assert_not_called()
        for value in ["cluster.example.invalid", "2222", "test-user", "test-billing"]:
            self.assertNotIn(value, out.getvalue())
        self.assertIn("--comment=", out.getvalue())

    def test_dry_run_redacts_quoted_billing(self):
        with patch.dict(scc.os.environ, {"BUPT_SLURM_COMMENT": "billing's token"}):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                slurm.main(["--dry-run", "submit", "/w/a.sbatch", "--workdir", "/w"])
            self.assertNotIn("billing", out.getvalue())
            self.assertNotIn("token", out.getvalue())

    def test_transport_error_preserved_without_retry(self):
        with patch.object(scc.subprocess, "run", return_value=subprocess.CompletedProcess([], 255)) as run:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(slurm.main(["submit", "/w/a.sbatch", "--workdir", "/w"]), 255)
            run.assert_called_once()
            self.assertIn("不要直接重试", err.getvalue())
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertIn("--comment=test-billing", run.call_args.args[0][-1])

    def test_environment_and_cli_precedence(self):
        with patch.dict(scc.os.environ, {"BUPT_SCC_USER": "environment-user"}):
            self.assertIn("environment-user", self.command(slurm, "info"))
            self.assertIn("cli-user", self.command(slurm, "--user", "cli-user", "info"))

    def test_config_is_literal_and_does_not_change_environment(self):
        self.env_file.write_text('# comment\n\nBUPT_SCC_IDENTITY="/keys/a $HOME $(whoami) key"\n')
        self.assertEqual(scc.load_config()["BUPT_SCC_IDENTITY"], "/keys/a $HOME $(whoami) key")
        self.assertNotIn("BUPT_SCC_IDENTITY", scc.os.environ)

    def test_invalid_config_does_not_disclose_values(self):
        for line in ['PASSWORD=private-value', 'BUPT_SCC_USER="private-value']:
            self.env_file.write_text(line)
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(slurm.main(["info"]), 2)
            self.assertNotIn("private-value", err.getvalue())

    def test_missing_config_never_connects(self):
        self.env_file.unlink()
        with patch.object(scc.subprocess, "run") as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                slurm.main(["info"])
            run.assert_not_called()

    def test_invalid_host_and_port_never_execute(self):
        for argv in [("--host", "-oProxyCommand=bad", "info"),
                     ("--host", "user@host", "info"), ("--port", "65536", "info")]:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises((SystemExit, ValueError)):
                    self.command(slurm, *argv)

    def test_missing_or_invalid_comment_fails_before_ssh(self):
        for value in ["", "  ", "a\nb", "a\x00b"]:
            config = dict(scc.load_config(), BUPT_SLURM_COMMENT=value)
            with self.subTest(value=value), patch.object(scc, "load_config", return_value=config):
                with patch.object(scc.subprocess, "run") as run, contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        slurm.main(["submit", "/w/a.sbatch", "--workdir", "/w"])
                    run.assert_not_called()

    def test_queries_do_not_require_billing(self):
        with patch.dict(scc.os.environ, {"BUPT_SLURM_COMMENT": ""}):
            self.assertIn("sacct", self.command(slurm, "accounting", "123")[-1])

    def test_file_transfer_options_and_literal_paths(self):
        cmd = self.command(scc, "upload", "a file.sbatch", "/remote/a ' file.sbatch")
        self.assertEqual(cmd[:3], ["scp", "-P", "2222"])
        self.assertIn("BatchMode=yes", cmd)
        self.assertEqual(cmd[-1], "test-user@cluster.example.invalid:/remote/a ' file.sbatch")
        self.assertTrue(Path(cmd[-2]).is_absolute())
        download = self.command(scc, "download", "a file.sbatch", "/remote/a ' file.sbatch")
        self.assertEqual(download[-2:], list(reversed(cmd[-2:])))

    def test_explicit_env_file(self):
        other = self.env_file.parent / "custom.env"
        other.write_text("BUPT_SCC_USER=external-user\n")
        with patch.dict(scc.os.environ, {"BUPT_SCC_ENV_FILE": str(other)}):
            self.assertEqual(scc.load_config()["BUPT_SCC_USER"], "external-user")
            self.assertEqual(scc.load_config(self.env_file)["BUPT_SCC_USER"], "test-user")

    def test_job_filter_preserves_remote_failure(self):
        argv = shlex.split(self.command(slurm, "job", "123")[-1])
        self.assertEqual(argv[:4], ["bash", "-o", "pipefail", "-c"])
        # Use a shell function to emulate the remote scheduler without a cluster.
        result = subprocess.run(argv[:4] + ['scontrol() { return 9; }; ' + argv[4]],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 9)
        result = subprocess.run(argv[:4] + [
            'scontrol() { printf "JobId=123\\n   Comment=test-billing\\n   JobState=COMPLETED\\n"; }; ' + argv[4]],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("test-billing", result.stdout)
        self.assertIn("COMPLETED", result.stdout)

    def test_local_mode_requires_no_ssh_configuration(self):
        self.env_file.write_text("BUPT_SCC_MODE=local\nBUPT_SLURM_COMMENT=test-billing\n")
        self.assertEqual(self.command(slurm, "accounting", "123")[:3], ["sacct", "--jobs", "123"])
        cmd = self.command(slurm, "submit", "/w/a.sbatch", "--workdir", "/w")
        self.assertEqual(cmd, ["sbatch", "--parsable", "--comment=test-billing", "--chdir", "/w", "/w/a.sbatch"])

    def test_local_exec_is_literal_and_preserves_exit_status(self):
        value = "a; $(touch unexpected) ' literal"
        cmd = self.command(scc, "--mode", "local", "exec", "--", sys.executable, "-c",
                           "import sys; print(sys.argv[1]); sys.exit(7)", value)
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), value)
        self.assertEqual(result.returncode, 7)

    def test_local_submit_runs_directly_with_comment(self):
        self.env_file.write_text("BUPT_SCC_MODE=local\nBUPT_SLURM_COMMENT=test-billing\n")
        with patch.object(scc.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(slurm.main(["submit", "/w/a.sbatch", "--workdir", "/w"]), 0)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "sbatch")
        self.assertIn("--comment=test-billing", argv)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_local_missing_comment_and_mode_mistakes_never_execute(self):
        configs = [{"BUPT_SCC_MODE": "local"}, {"BUPT_SCC_MODE": "typo", "BUPT_SLURM_COMMENT": "test"}]
        for config in configs:
            with self.subTest(config=config), patch.object(scc, "load_config", return_value=config):
                with patch.object(scc.subprocess, "run") as run, contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        slurm.main(["submit", "/w/a.sbatch", "--workdir", "/w"])
                    run.assert_not_called()

    def test_local_login_and_transfers_fail_without_side_effects(self):
        for argv in [("login",), ("upload", "a", "/b"), ("download", "a", "/b")]:
            with self.subTest(argv=argv):
                with patch.object(scc.subprocess, "run") as run, contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        scc.main(["--mode", "local", *argv])
                    run.assert_not_called()

    def test_mode_precedence_and_local_dry_run(self):
        with patch.dict(scc.os.environ, {"BUPT_SCC_MODE": "local"}):
            self.assertEqual(self.command(slurm, "accounting", "123")[0], "sacct")
            self.assertEqual(self.command(slurm, "--mode", "ssh", "accounting", "123")[0], "ssh")
            with patch.object(scc.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()) as out:
                slurm.main(["--dry-run", "submit", "/w/a.sbatch", "--workdir", "/w"])
            run.assert_not_called()
            self.assertTrue(out.getvalue().startswith("sbatch "))
            self.assertNotIn("test-billing", out.getvalue())

    def test_local_missing_executable_reports_cluster_environment(self):
        with patch.object(scc.subprocess, "run", side_effect=FileNotFoundError):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(slurm.main(["--mode", "local", "accounting", "123"]), 127)
            self.assertIn("PATH", err.getvalue())
            self.assertNotIn("OpenSSH", err.getvalue())


if __name__ == "__main__":
    unittest.main()

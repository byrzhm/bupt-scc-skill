#!/usr/bin/env python3
"""BUPT Slurm operations with mandatory billing comment from local config."""

import argparse
import importlib.util
from pathlib import Path
import re
import shlex
import sys


TRANSPORT = Path(__file__).resolve().parents[2] / "bupt-scc-skill" / "scripts" / "scc.py"
if not TRANSPORT.is_file():
    raise SystemExit("缺少同级 bupt-scc-skill，请将两个技能一起安装在 skills 目录下。")
SPEC = importlib.util.spec_from_file_location("bupt_scc_transport", TRANSPORT)
scc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scc)


def job_id(value):
    if not re.fullmatch(r"[1-9][0-9]*(?:_[0-9]+)?", value):
        raise argparse.ArgumentTypeError("需要单个作业 ID，例如 12345 或 12345_2")
    return value


def parser(config=None):
    config = {} if config is None else config
    p = argparse.ArgumentParser(description=__doc__)
    scc.add_connection_options(p, config)
    p.set_defaults(billing_comment=config.get("BUPT_SLURM_COMMENT"))
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("info", help="用户、版本和分区摘要")
    sub.add_parser("queue", help="当前用户队列")
    for name, desc in [("job", "作业详情（不输出计费 comment）"),
                       ("accounting", "作业及步骤记账"), ("cancel", "取消单个作业")]:
        cmd = sub.add_parser(name, help=desc)
        cmd.add_argument("job_id", type=job_id)
    cmd = sub.add_parser("submit", help="通过本地配置注入计费 comment 并提交远端脚本")
    cmd.add_argument("script", type=scc.remote_path)
    cmd.add_argument("--workdir", required=True, type=scc.remote_path)
    cmd.add_argument("--partition", default=config.get("BUPT_SLURM_PARTITION"))
    cmd.add_argument("--account")
    cmd.add_argument("--qos")
    return p


def remote_command(args):
    if args.action == "info":
        return 'id -un && sinfo --version && sinfo -o "%P %a %l %D %t"'
    if args.action == "queue":
        return 'squeue --user="$(id -un)" -o "%.18i %.12P %.30j %.8u %.2t %.10M %.6D %R"'
    if args.action == "job":
        # scontrol exposes Comment, so remove that field before output leaves SSH.
        program = f"scontrol show job {args.job_id} | sed '/^[[:space:]]*Comment=/d'"
        return shlex.join(["bash", "-o", "pipefail", "-c", program])
    if args.action == "accounting":
        argv = ["sacct", "--jobs", args.job_id, "--parsable2",
                "--format=JobID,JobName,State,ExitCode,Elapsed,AllocCPUS,MaxRSS"]
    elif args.action == "cancel":
        argv = ["scancel", args.job_id]
    else:
        comment = args.billing_comment
        if not comment or not comment.strip() or any(c in comment for c in "\x00\r\n"):
            raise ValueError("提交前必须在 .env 或进程环境中配置非空 BUPT_SLURM_COMMENT")
        argv = ["sbatch", "--parsable", f"--comment={comment}", "--chdir", args.workdir]
        for name in ("partition", "account", "qos"):
            value = getattr(args, name)
            if value:
                argv.append(f"--{name}={value}")
        argv.append(args.script)
    return shlex.join(argv)


def build_command(args):
    return scc.build_ssh(args, remote_command(args))


def main(argv=None):
    return scc.cli(parser, build_command, argv)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Small SSH/Slurm helper for BUPT SCC; no local shell or automatic retries."""

import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
CONFIG_KEYS = ("BUPT_SCC_HOST", "BUPT_SCC_PORT", "BUPT_SCC_USER", "BUPT_SCC_IDENTITY")


def load_config(path=None):
    """Read literal KEY=value settings; never execute or expand file contents."""
    path = ENV_FILE if path is None else Path(path)
    config = {}
    if path.exists():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or key not in CONFIG_KEYS:
                raise ValueError(f".env 第 {number} 行格式错误或配置键不受支持")
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError(f".env 第 {number} 行引号未闭合")
                value = value[1:-1]
            config[key] = value
    for key in CONFIG_KEYS:
        if key in os.environ:
            config[key] = os.environ[key]
    return config


def job_id(value):
    if not re.fullmatch(r"[1-9][0-9]*(?:_[0-9]+)?", value):
        raise argparse.ArgumentTypeError("需要单个作业 ID，例如 12345 或 12345_2")
    return value


def remote_path(value):
    if not value.startswith("/") or any(c in value for c in "\x00\r\n"):
        raise argparse.ArgumentTypeError("需要无换行的远端绝对路径")
    return value


def parser(config=None):
    config = {} if config is None else config
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=config.get("BUPT_SCC_HOST"), help="SSH 登录节点")
    p.add_argument("--port", default=config.get("BUPT_SCC_PORT"), help="SSH 端口")
    p.add_argument("--user", default=config.get("BUPT_SCC_USER"), help="SSH 用户名")
    p.add_argument("--identity", default=config.get("BUPT_SCC_IDENTITY"), help="已有 SSH 私钥路径")
    p.add_argument("--interactive-auth", action="store_true", help="允许交互认证")
    p.add_argument("--dry-run", action="store_true", help="仅打印命令，不连接")
    sub = p.add_subparsers(dest="action", required=True)
    for name, desc in [("login", "交互登录"), ("info", "用户、版本和分区"),
                       ("queue", "当前用户队列")]:
        sub.add_parser(name, help=desc)
    for name, desc in [("job", "作业详情"), ("accounting", "作业记账"),
                       ("cancel", "取消指定作业")]:
        cmd = sub.add_parser(name, help=desc)
        cmd.add_argument("job_id", type=job_id)
    cmd = sub.add_parser("submit", help="提交远端已有脚本")
    cmd.add_argument("script", type=remote_path)
    cmd.add_argument("--workdir", required=True, type=remote_path)
    cmd = sub.add_parser("exec", help="按参数执行远端命令；用 -- 分隔")
    cmd.add_argument("argv", nargs=argparse.REMAINDER)
    return p


def remote_command(args):
    if args.action == "login":
        return None
    if args.action == "info":
        return 'id -un && sinfo --version && sinfo -o "%P %a %l %D %t"'
    if args.action == "queue":
        return 'squeue --user="$(id -un)" -o "%.18i %.12P %.30j %.8u %.2t %.10M %.6D %R"'
    if args.action == "job":
        argv = ["scontrol", "show", "job", args.job_id]
    elif args.action == "accounting":
        argv = ["sacct", "--jobs", args.job_id, "--parsable2",
                "--format=JobID,JobName,State,ExitCode,Elapsed,AllocCPUS,MaxRSS"]
    elif args.action == "cancel":
        argv = ["scancel", args.job_id]
    elif args.action == "submit":
        argv = ["sbatch", "--parsable", "--chdir", args.workdir, args.script]
    else:
        argv = args.argv
        if argv and argv[0] == "--":
            argv = argv[1:]
        if not argv:
            raise ValueError("exec 需要远端命令")
    return shlex.join(argv)


def build_command(args):
    if not args.host or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]*", args.host):
        raise ValueError("请在 .env 或 --host 中配置有效的 SSH 主机名/IP")
    if not args.port or not re.fullmatch(r"[0-9]+", args.port) or not 1 <= int(args.port) <= 65535:
        raise ValueError("请在 .env 或 --port 中配置有效端口（1–65535）")
    if not args.user:
        raise ValueError("请在 .env 或 --user 中配置集群用户名")
    command = ["ssh", "-p", args.port, "-o", "ConnectTimeout=15",
               "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3"]
    if args.action == "login":
        command.append("-t")
    else:
        command.append("-T")
        if not args.interactive_auth:
            command.extend(["-o", "BatchMode=yes"])
    if args.user:
        if args.user.startswith("-") or any(c.isspace() or c == "\x00" for c in args.user):
            raise ValueError("无效 SSH 用户名")
        command.extend(["-l", args.user])
    if args.identity:
        command.extend(["-i", os.path.expanduser(args.identity)])
    command.append(args.host)
    remote = remote_command(args)
    if remote is not None:
        command.append(remote)
    return command


def main(argv=None):
    try:
        config = load_config()
    except (OSError, UnicodeError, ValueError) as exc:
        # Do not print file contents or OS error paths containing personal data.
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) else ".env 无法读取"
        print(message, file=sys.stderr)
        return 2
    p = parser(config)
    args = p.parse_args(argv)
    try:
        command = build_command(args)
    except ValueError as exc:
        p.error(str(exc))
    if args.dry_run:
        print(shlex.join(command))
        return 0
    try:
        result = subprocess.run(command, check=False)
    except FileNotFoundError:
        print("找不到 ssh，请安装 OpenSSH 客户端。", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        if args.action == "submit":
            print("提交被中断，结果可能不确定；先检查队列与记账记录再决定是否重试。", file=sys.stderr)
        return 130
    if args.action == "submit" and result.returncode != 0:
        print("提交未正常返回；若发生通信错误，先核查是否已受理，不要直接重试。", file=sys.stderr)
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


if __name__ == "__main__":
    sys.exit(main())

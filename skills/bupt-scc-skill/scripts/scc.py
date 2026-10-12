#!/usr/bin/env python3
"""BUPT SCC SSH/file transport and shared literal dotenv configuration."""

import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
CONFIG_KEYS = ("BUPT_SCC_HOST", "BUPT_SCC_PORT", "BUPT_SCC_USER", "BUPT_SCC_IDENTITY",
               "BUPT_SLURM_COMMENT", "BUPT_SLURM_PARTITION")


def load_config(path=None):
    """Read literal KEY=value settings; never execute or expand file contents."""
    path = Path(path or os.environ.get("BUPT_SCC_ENV_FILE") or ENV_FILE).expanduser()
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


def remote_path(value):
    if not value.startswith("/") or any(c in value for c in "\x00\r\n"):
        raise argparse.ArgumentTypeError("需要无换行的远端绝对路径")
    return value


def add_connection_options(p, config=None):
    config = {} if config is None else config
    p.add_argument("--host", default=config.get("BUPT_SCC_HOST"), help="SSH 登录节点")
    p.add_argument("--port", default=config.get("BUPT_SCC_PORT"), help="SSH 端口")
    p.add_argument("--user", default=config.get("BUPT_SCC_USER"), help="SSH 用户名")
    p.add_argument("--identity", default=config.get("BUPT_SCC_IDENTITY"), help="已有 SSH 私钥路径")
    p.add_argument("--interactive-auth", action="store_true", help="允许交互认证")
    p.add_argument("--dry-run", action="store_true", help="仅打印脱敏命令，不连接")


def parser(config=None):
    p = argparse.ArgumentParser(description=__doc__)
    add_connection_options(p, config)
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("login", help="交互登录")
    for name, desc in [("upload", "上传单个文件"), ("download", "下载单个文件")]:
        cmd = sub.add_parser(name, help=desc)
        cmd.add_argument("local", help="本地文件路径")
        cmd.add_argument("remote", type=remote_path, help="远端绝对文件路径")
    cmd = sub.add_parser("exec", help="按参数执行远端命令；用 -- 分隔")
    cmd.add_argument("argv", nargs=argparse.REMAINDER)
    return p


def remote_command(args):
    if args.action == "login":
        return None
    argv = args.argv
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise ValueError("exec 需要远端命令")
    return shlex.join(argv)


def connection_options(args):
    if not args.host or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]*", args.host):
        raise ValueError("请在 .env 或 --host 中配置有效的 SSH 主机名/IP")
    if not args.port or not re.fullmatch(r"[0-9]+", args.port) or not 1 <= int(args.port) <= 65535:
        raise ValueError("请在 .env 或 --port 中配置有效端口（1–65535）")
    if not args.user:
        raise ValueError("请在 .env 或 --user 中配置集群用户名")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", args.user):
        raise ValueError("无效 SSH 用户名")
    command = ["-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30",
               "-o", "ServerAliveCountMax=3"]
    if args.action != "login" and not args.interactive_auth:
        command.extend(["-o", "BatchMode=yes"])
    if args.identity:
        command.extend(["-i", os.path.expanduser(args.identity)])
    return command


def build_ssh(args, remote):
    command = ["ssh", "-p", args.port, *connection_options(args),
               "-t" if args.action == "login" else "-T", "-l", args.user, args.host]
    if remote is not None:
        command.append(remote)
    return command


def build_command(args):
    if args.action not in ("upload", "download"):
        return build_ssh(args, remote_command(args))
    options = connection_options(args)
    local = str(Path(args.local).expanduser().resolve())
    host = f"[{args.host}]" if ":" in args.host else args.host
    remote = f"{args.user}@{host}:{args.remote}"
    paths = [local, remote] if args.action == "upload" else [remote, local]
    return ["scp", "-P", args.port, *options, *paths]


def run_command(args, command, config):
    if args.dry_run:
        # Only redact the display; the executed argv retains the exact values.
        display = list(command)
        private = [args.host, args.port, args.user, args.identity, config.get("BUPT_SLURM_COMMENT")]
        if args.identity:
            private.append(os.path.expanduser(args.identity))
        for value in sorted({v for v in private if v}, key=len, reverse=True):
            quoted = shlex.quote(value)
            variants = {value, quoted}
            if quoted.startswith("'"):
                variants.add(quoted[1:-1])
            for variant in sorted(variants, key=len, reverse=True):
                display = [item.replace(variant, "<redacted>") for item in display]
        print(shlex.join(display))
        return 0
    try:
        result = subprocess.run(command, check=False)
    except FileNotFoundError:
        print("找不到 SSH/SCP 程序，请安装 OpenSSH 客户端。", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        if args.action == "submit":
            print("提交被中断，结果可能不确定；先检查队列与记账记录再决定是否重试。", file=sys.stderr)
        return 130
    if args.action == "submit" and result.returncode != 0:
        print("提交未正常返回；若发生通信错误，先核查是否已受理，不要直接重试。", file=sys.stderr)
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


def cli(parser_factory, command_factory, argv=None):
    try:
        config = load_config()
    except (OSError, UnicodeError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) else ".env 无法读取"
        print(message, file=sys.stderr)
        return 2
    p = parser_factory(config)
    args = p.parse_args(argv)
    try:
        command = command_factory(args)
    except ValueError as exc:
        p.error(str(exc))
    return run_command(args, command, config)


def main(argv=None):
    return cli(parser, build_command, argv)


if __name__ == "__main__":
    sys.exit(main())

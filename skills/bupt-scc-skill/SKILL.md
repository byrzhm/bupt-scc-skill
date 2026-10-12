---
name: bupt-scc-skill
description: 在个人电脑通过 SSH 连接北邮超算，或在集群本机直接执行轻量命令，管理私有配置和文件。适用于 Codex、Claude Code 等 Agent 的集群访问、网络认证排查和文件准备；作业调度使用同级 bupt-slurm-skill。
---

# 北邮超算访问与文件操作

## 配置与目录

本技能提供 `scripts/scc.py`，依赖 Python 3.8+；SSH 模式还需要 OpenSSH。技能使用通用 `SKILL.md` 格式，不依赖某个 Agent 客户端。Codex 和 Claude Code 的安装及调用方式见仓库 [README](../../README.md)。两个技能按同级目录一起使用：

```text
.env                        # 本地私有配置，不上传
.env.example                # 不含私有值的配置示例
skills/
  bupt-scc-skill/
  bupt-slurm-skill/
```

脚本默认读取上述目录根部的 `.env`，与调用时的工作目录无关。若安装到其他位置，通过 `BUPT_SCC_ENV_FILE=/绝对路径/.env` 指向已有配置文件。不要搜索其他项目的 `.env`。配置优先级为命令行参数 > 进程环境 > 文件。

在仓库根目录首次配置，已有文件时不要覆盖：

```bash
cp .env.example .env
chmod 600 .env
```

编辑执行脚本的机器上的 `.env`：`BUPT_SCC_MODE=ssh`（默认）时，必填 `BUPT_SCC_HOST`、`BUPT_SCC_PORT`、`BUPT_SCC_USER`，可选 `BUPT_SCC_IDENTITY` 指向已有私钥；Agent 已在集群上运行时设置 `BUPT_SCC_MODE=local`，不需要 SSH 字段。Slurm 共用此文件中的 `BUPT_SLURM_COMMENT` 和可选 `BUPT_SLURM_PARTITION`，见 [Slurm 技能](../bupt-slurm-skill/SKILL.md)。不保存密码或私钥正文。

配置是每行 `KEY=value`，允许空行、整行注释、包裹值的单/双引号。不支持 `export`、行尾注释、多行值、转义或变量展开。解析器不会执行文件，也不会把变量导出到调用它的 shell。未知键报错，避免配置拼写错误被静默忽略。

`.env` 和 `.env.*` 被 Git 忽略，只提交不含私有值的 `.env.example`。实际地址、账号、计费值、完整 SSH 输出和实测日志均不能写入受跟踪文件。预览命令会脱敏；真实远端输出仍可能包含个人信息，分享前检查。不要使用 `set -x` 回显配置。

## 执行位置

按执行脚本的机器选择模式，不按聊天界面所在机器判断。`ssh` 通过配置的登录节点执行；`local` 直接使用当前操作系统账号和 PATH，在当前机器执行。默认仍为 `ssh`，不根据主机名或是否安装 Slurm 自动切换，以免在错误环境操作。

两种模式都支持 `exec`，单次覆盖使用全局 `--mode local` 或 `--mode ssh`。本机模式不启动嵌套 SSH，不创建额外登录 shell；先在启动 Agent 的终端初始化集群模块环境。安装在集群上并不意味着可以在登录节点直接执行训练，计算仍应通过 Slurm 分配资源。

```bash
python3 scripts/scc.py --mode local exec -- pwd
python3 scripts/scc.py --mode local exec -- bash -lc 'command -v sbatch'
```

## 登录与命令

以下从本技能目录执行，其他位置使用脚本绝对路径：

```bash
python3 scripts/scc.py login
python3 scripts/scc.py --dry-run exec -- pwd
python3 scripts/scc.py exec -- pwd
python3 scripts/scc.py exec -- bash -lc 'command -v sbatch; command -v module'
```

`login` 仅用于 SSH 模式；local 模式会明确报错，因为已经在当前机器上。全局选项 `--mode`、`--host`、`--port`、`--user`、`--identity`、`--dry-run` 放在子命令前。SSH 模式的非交互操作默认使用 `BatchMode=yes`；密码认证可使用交互 `login`，或在有终端时加 `--interactive-auth`。不让用户把密码发到聊天里，不关闭主机密钥验证。首次连接或密钥变化时，核实可信指纹。

`exec` 在 local 模式直接传递参数列表；在 SSH 模式将每个参数正确引用后交给远端 shell。两种模式默认都不解释参数中的管道、变量或重定向。确需这些功能时明确调用 `bash -lc`；不要把不可信文本拼接进 shell 程序。该命令不是权限沙箱。

登录节点只做轻量查询和文件准备。GPU 测试、训练和长时间计算由 [Slurm 技能](../bupt-slurm-skill/SKILL.md) 分配计算节点后执行，不在登录节点直接运行。

## 文件传输

`upload` / `download` 仅适用于 SSH 模式。本机模式的文件已经在集群文件系统中，直接使用现有绝对路径；需要复制时可用 `exec -- cp 源文件 目标文件`，先核实目标，避免覆盖。脚本不会把 upload/download 静默解释为本机复制。

```bash
python3 scripts/scc.py upload ./job.sbatch /remote/project/job.sbatch
python3 scripts/scc.py download ./slurm.out /remote/project/slurm-12345.out
```

两个命令均按“本地文件、远端文件”顺序传参，仅传输单个文件。远端路径必须为绝对路径；先核实实际目录并创建需要的父目录。使用现代 OpenSSH 默认 SFTP 模式的 `scp`，不自动退回旧 SCP 协议。私钥、端口、用户和认证方式与 SSH 一致。

传输可能覆盖目标文件，先检查目的路径，冒烟作业优先使用独立运行目录。不要用整目录上传把 `.env` 或私钥带到集群。

## 排查与汇报

连接失败按路由/校园网或 VPN、端口、认证、主机密钥分类检查，不猜测账号或关闭验证。只进行用户任务所需的远端操作。

说明执行过的命令类型、实际结果和仍未核实的事项；只完成离线准备时，不声称连接成功。作业的提交授权、资源选择、计费和终态判断由 Slurm 技能处理。

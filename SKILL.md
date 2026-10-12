---
name: bupt-scc
description: 使用北邮超算集群，通过 SSH 连接登录节点并使用 Slurm 查询资源、准备和提交作业、检查日志与资源使用、传输文件及排查失败。适用于北邮超算上的计算任务和集群操作。
---

# 北邮超算集群

## 已知配置与边界

- 调度系统：Slurm。登录节点、SSH 端口、用户名和私钥路径仅从本地 `.env` 或用户的运行环境读取，不写入受 Git 跟踪的文件。
- 用户名、认证方式、分区、账户、QoS、GPU 型号、存储目录和软件模块尚未核实。先读取用户提供的配置或查询集群，不编造这些信息。
- 登录节点用于轻量查询、文件操作和作业准备。训练、长时间计算、性能测试等通过 Slurm 分配资源后执行。
- 用户要求准备脚本时只准备；要求提交或取消指定作业时可在该范围内执行，无需重复确认。不要把“使用此技能”视为提交任意任务的授权。
- 不保存密码、私钥或令牌，不关闭 SSH 主机密钥验证。首次连接或主机密钥变化时，应通过可信渠道核对指纹。

## 连接与封装

本技能的 `scripts/scc.py` 仅依赖本地 Python 3.8+ 和 OpenSSH；远端需要可用的 Slurm 命令。下面命令在技能目录执行；在其他目录使用脚本的绝对路径。

```bash
# 首次配置：复制后在本地编辑 .env，填入实际连接信息
cp .env.example .env
chmod 600 .env
python3 scripts/scc.py login
python3 scripts/scc.py info
python3 scripts/scc.py queue
```

脚本固定读取技能根目录的 `.env`，与当前工作目录无关。已有 `.env` 时不要重新复制覆盖。支持 `BUPT_SCC_HOST`、`BUPT_SCC_PORT`、`BUPT_SCC_USER` 和可选的 `BUPT_SCC_IDENTITY`；前三项必填。优先级为命令行参数 > 进程环境变量 > `.env`。`--identity` 指向已有私钥，仍遵循本地 SSH 配置中的代理等设置。全局参数放在子命令前。

`.env` 使用每行 `KEY=value`，允许空行、整行注释和包裹值的单/双引号；不支持 `export`、行尾注释、变量展开、转义或多行值。脚本只解析文本，不执行文件，也不会将配置导出到调用它的 shell。禁止在配置中保存密码或私钥正文。

`.env` 和 `.env.*` 已被 Git 忽略，仅提交不含实际信息的 `.env.example`。不要将配置、命令预览、SSH 输出或包含实际连接信息的测试日志提交到仓库；`--dry-run` 会显示真实连接参数，仅用于本地检查。

```bash
python3 scripts/scc.py --user alice --dry-run info
python3 scripts/scc.py --identity ~/.ssh/id_ed25519 queue
python3 scripts/scc.py --help
```

默认非交互命令使用 `BatchMode=yes`，避免等待密码；仅有密码认证时，使用 `login` 手动登录，或在交互终端使用 `--interactive-auth`。不要让用户把密码发到聊天中。连接失败先区分内网路由、端口、认证和主机密钥问题；是否需要校园网或 VPN 须结合实际网络环境判断。

`exec` 按参数传递远端命令，对每个参数做 shell 引用。管道、变量展开、重定向仅在明确调用远端 shell 时生效。不要把不可信文本拼接到 shell 程序中。封装不是权限沙箱，`exec` 仍须遵守用户授权范围。

```bash
python3 scripts/scc.py exec -- scontrol show partition
python3 scripts/scc.py exec -- bash -lc 'command -v sbatch; command -v module'
```

## 资源发现与作业准备

1. 用 `info` 查看当前远端用户、Slurm 版本和分区摘要；必要时执行 `scontrol show partition` 与 `sinfo -N -o '%N %P %c %m %G %t'`，核实 CPU、内存与 GRES。可见资源不等于该账号有使用权限。
2. 根据任务确定工作目录、输入输出、运行命令、CPU 数、内存、时间和 GPU 需求。分区、账户、QoS 若无法从用户配置和只读查询确定，仅询问当前作业必需的缺失项。
3. 从 [assets/job.sbatch](assets/job.sbatch) 复制并修改作业脚本。模板只运行轻量主机信息作为冒烟检查；实际任务必须替换运行命令并按需修改资源。
4. 核实远端软件环境，再加入 `module load`、Conda 激活或容器命令。不要假设交互登录环境会自动出现在批作业中。
5. `#SBATCH` 指令放在首个可执行语句前，指令中不依赖 shell 变量展开。工作目录必须预先存在；自定义日志路径的父目录也必须在提交前建立，不能等作业启动后创建。

GPU 作业在核实集群配置后再添加相应 GRES 请求，例如 `#SBATCH --gres=gpu:1`，并选用适配的分区；此处不是已核实的北邮 GPU 配置。多节点或 MPI 任务需匹配集群 MPI 环境和 Slurm 启动方式，不直接套用单任务模板。

## 文件传输与提交

先用远端 `pwd` 和用户配置确定真实路径。以下 `/remote/project` 为示意路径，必须替换。传输优先使用 OpenSSH 的 `scp`；其端口参数是大写 `-P`，SSH 使用小写 `-p`。从本地配置读取主机、端口和用户名后构造传输命令，不把真实值写回本文或上传脚本。Python 读取 `.env` 不会让当前 shell 获得同名环境变量。

```bash
python3 scripts/scc.py --dry-run submit /remote/project/job.sbatch --workdir /remote/project
python3 scripts/scc.py submit /remote/project/job.sbatch --workdir /remote/project
```

封装要求脚本与工作目录均为远端绝对路径，使用 `sbatch --parsable` 返回作业 ID，可能带有 `;集群名`。`--dry-run` 仅打印命令，不连接、不验证文件、不表示提交成功。提交前检查最终脚本、资源和输出位置，提交后记录作业 ID、脚本路径、工作目录及资源请求。

**提交连接中断或输出不完整时，不自动重试。** 先通过当前用户队列、作业名称、提交时间、工作目录及可用的记账记录核查是否已受理；仍有歧义就报告不确定性，避免重复消耗资源。

## 跟踪、诊断和取消

```bash
python3 scripts/scc.py queue
python3 scripts/scc.py job 12345
python3 scripts/scc.py accounting 12345
python3 scripts/scc.py exec -- tail -n 100 /remote/project/slurm-12345.out
python3 scripts/scc.py cancel 12345
```

- `queue` 只查询当前远端用户；`job` 查看调度器详情；`accounting` 查看作业及其步骤的状态、退出码、耗时和内存记录。封装支持普通作业 ID 和单个数组任务 ID（如 `12345_2`），不支持批量取消表达式。
- 排队时先查看原因及分区/账户限制，不通过反复重投解决等待。
- 队列中消失不等于成功。结合记账状态、步骤退出码、日志与预期输出判断；记账服务可能未启用或数据延迟，MaxRSS 也可能仅出现在步骤记录中或不可用。
- 失败时区分内存不足、时间上限、环境/依赖、输入路径和程序错误，按证据修改必要参数。重新提交是新操作，应符合用户授权范围。
- 取消前核对目标作业归属及 ID。取消数组父作业会影响整个数组。取消成功后查询状态；不要在未获授权时使用按用户全部取消的命令。
- 下载日志时使用本地配置构造 `scp` 命令，并检查本地目标，避免覆盖用户已有文件。

汇报时说明已执行的操作、作业 ID 和当前可证实状态、日志/输出路径及尚未验证的事项。只完成文件准备时，不声称已经连接或运行成功。

## 维护与参考

本地验证：`python3 -m unittest discover -s tests -v`；这些测试模拟 SSH，不接触集群。
新增集群配置应基于用户确认或实际查询，并注明来源。远端版本和本站策略优先于通用示例。

Slurm 官方文档：[sbatch](https://slurm.schedmd.com/sbatch.html)、[squeue](https://slurm.schedmd.com/squeue.html)、[sacct](https://slurm.schedmd.com/sacct.html)。

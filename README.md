# 北邮超算 Agent Skills

通过自然语言让 Agent 连接北邮超算集群、传输文件、准备和提交 Slurm 作业，并检查运行结果。仓库包含两个配套使用的 skill：

| Skill | 职责 |
| --- | --- |
| [bupt-scc-skill](skills/bupt-scc-skill/SKILL.md) | SSH 登录、连接排查、本地配置、轻量远端命令和单文件上传下载 |
| [bupt-slurm-skill](skills/bupt-slurm-skill/SKILL.md) | 资源查询、sbatch 提交、comment 计费、队列监控、日志分析和作业取消 |

`bupt-slurm-skill` 会调用同级 `bupt-scc-skill` 的连接模块，**请同时安装两个目录，保留目录名称与同级关系**。

## 安装到 Codex

以下命令适用于 macOS、Linux 或 WSL，在运行 Agent 的机器上执行。需要 Python 3.8+、Git，以及支持默认 SFTP 传输模式的现代 OpenSSH 客户端（`ssh` / `scp`）；脚本不依赖第三方 Python 包。该机器还需要能够访问集群网络，必要时连接校园网或 VPN，并具备有效的集群账号与 SSH 认证方式。

### 1. 克隆仓库

在准备存放仓库的目录中执行；已有仓库时直接进入该目录：

```bash
git clone https://github.com/byrzhm/bupt-scc-skill.git
cd bupt-scc-skill
BUPT_SKILL_REPO="$(pwd -P)"
```

### 2. 创建本地配置

在仓库根目录执行，已有 `.env` 时保留原文件：

```bash
if [ ! -e .env ]; then
  (umask 077; cp .env.example .env)
fi
chmod 600 .env
```

用本地编辑器打开 `.env`，填写配置。真实值由集群管理员或账号持有人提供，不放入公开文档、聊天示例或 Git 提交。

| 变量 | 是否必填 | 用途 |
| --- | --- | --- |
| `BUPT_SCC_HOST` | 是 | 登录节点主机名或 IP |
| `BUPT_SCC_PORT` | 是 | SSH 端口 |
| `BUPT_SCC_USER` | 是 | 集群用户名 |
| `BUPT_SCC_IDENTITY` | 否 | 已有 SSH 私钥的本地路径；留空使用 OpenSSH 配置或 agent |
| `BUPT_SLURM_COMMENT` | 提交作业时必填 | 计费标识，由封装自动传给 `sbatch --comment` |
| `BUPT_SLURM_PARTITION` | 否 | 默认分区；应先查询当前资源，提交时可用 `--partition` 覆盖 |

**计费标识必须通过 comment 传递，不能以 `--account` 替代。** 缺少 `BUPT_SLURM_COMMENT` 时，提交封装会在连接前报错；仅登录和查询不要求此项。

文件采用每行 `KEY=value`，支持空行、整行 `#` 注释和包裹值的引号；不支持 `export`、行尾注释、多行值或变量展开。不要写入密码或私钥正文，也不需要用 `source .env` 加载。

### 3. 注册两个 skill

推荐创建指向仓库的符号链接，便于更新，也让脚本继续读取仓库根目录的 `.env`。Codex 支持用户级 `~/.agents/skills`、项目级 `.agents/skills` 以及符号链接；详见 [官方技能文档](https://learn.chatgpt.com/docs/build-skills)。

在仓库根目录执行：

```bash
BUPT_SKILL_REPO="$(pwd -P)"
BUPT_SKILL_DIR="$HOME/.agents/skills"
mkdir -p "$BUPT_SKILL_DIR"

for skill in bupt-scc-skill bupt-slurm-skill; do
  target="$BUPT_SKILL_DIR/$skill"
  if [ -e "$target" ] || [ -L "$target" ]; then
    printf '保留已有路径，请检查是否指向本仓库：%s\n' "$target"
  else
    ln -s "$BUPT_SKILL_REPO/skills/$skill" "$target"
  fi
done
```

如果只在某个项目使用，将 `BUPT_SKILL_DIR` 改成该项目的绝对路径加 `/.agents/skills`。两种方式选一种即可，避免重复注册。不要移动或删除作为链接目标的仓库。

如果选择复制 skill 目录而非使用符号链接，还需让执行脚本的进程获得 `BUPT_SCC_ENV_FILE`，指向已有配置文件，例如：

```bash
export BUPT_SCC_ENV_FILE="/absolute/path/to/bupt-scc-skill/.env"
```

这个变量在进程环境中设置，不写进 `.env`。桌面应用不一定继承终端里的 `export`；也可在 prompt 中要求 Agent 为脚本调用设置该变量，并给出配置文件的本地路径。配置优先级为命令行参数 > 进程环境变量 > `.env`。

### 4. 确认安装

在 Codex CLI / IDE 中通过 `/skills` 或输入 `$` 查找两个 skill；也可直接在 prompt 中写 `$bupt-scc-skill` 或 `$bupt-slurm-skill`。支持 `@` 技能选择器的界面可使用对应选择器。未出现时重启客户端再检查。调用方式参见 [官方技能文档](https://learn.chatgpt.com/docs/build-skills)。

可以先进行不联网的命令预览：

```bash
python3 skills/bupt-scc-skill/scripts/scc.py --dry-run exec -- pwd
```

填写配置后，再进行只读连接检查：

```bash
python3 skills/bupt-slurm-skill/scripts/slurm.py info
```

首次 SSH 连接需通过可信渠道核实主机指纹。非交互命令默认使用 `BatchMode=yes`；如果只有密码认证，可在终端运行 `scc.py login`，或在有交互终端时为命令加 `--interactive-auth`。不要通过关闭主机密钥验证解决连接问题。

## 典型 prompt

以下内容可直接发送给 Agent。将本地文件、远端目录、作业 ID 和资源需求替换为实际值。真实连接信息和计费值已经保存在 `.env`，无需重复写入 prompt。

### 检查连接与集群资源

```text
使用 $bupt-scc-skill 和 $bupt-slurm-skill，从本地 .env 读取配置。
检查能否连接北邮超算，查询 Slurm 版本、当前可用分区、GPU 类型和我的排队作业。
仅执行只读检查，不提交作业，不打印完整配置或计费标识。
```

### 运行一次 nvidia-smi 测试

```text
使用 $bupt-slurm-skill，在北邮超算上提交一次 nvidia-smi 冒烟作业。
先查询可用 GPU 分区，为本次运行创建独立目录，使用仓库中的 nvidia-smi.sbatch。
申请 1 张 GPU，时间上限 2 分钟，从 .env 读取计费 comment。
等待作业结束，检查 stdout、stderr 和记账结果，报告作业 ID、GPU 型号、终态和退出码。
若提交连接中断，先核查是否已经受理，不要直接重复提交。
```

此 prompt 会提交实际作业并按集群规则计费。模板执行的命令是 `srun --ntasks=1 nvidia-smi`；成功应同时具备 GPU 输出、`COMPLETED` 终态和 `0:0` 退出码。

### 准备训练脚本，暂不提交

```text
使用 $bupt-slurm-skill，为本地 ./train.py 准备北邮超算上的单卡训练作业。
运行命令是 python train.py --config configs/demo.yaml，预计需要 4 个 CPU、16G 内存、1 小时。
先核实可用 GPU 分区、共享工作目录和 Python 环境，再生成 sbatch 脚本。
计费值只从 .env 读取；目前只准备脚本并展示资源和脱敏后的提交命令，不上传、不提交。
缺少关键输入时向我询问，不猜测环境名称或远端目录。
```

### 上传并提交已检查的作业

```text
使用 $bupt-scc-skill 和 $bupt-slurm-skill，将本地 ./train.py、./configs/demo.yaml
和 ./train.sbatch 上传到我指定的远端目录 /remote/project/run-001，保留配置文件的相对位置。
先检查目标是否存在，避免覆盖文件，并确认脚本的输入路径和环境有效。
使用 train.sbatch 中已确定的资源提交一次作业，从 .env 注入计费 comment。
提交后报告作业 ID 和日志路径，不上传 .env 或私钥。
```

文件传输封装每次处理一个文件；多个文件由 Agent 分别上传。`/remote/project/run-001` 是示意路径，需要替换。

### 查询排队或运行进度

```text
使用 $bupt-slurm-skill，检查作业 12345 的状态。
如果仍在排队，说明调度器给出的原因；如果运行中，查看最近的日志和已运行时间；
如果已经退出，结合 sacct、步骤退出码和输出文件判断是否成功。
不要自动取消、修改资源或重新提交。
```

### 诊断失败作业

```text
使用 $bupt-slurm-skill，分析失败作业 12345。
检查主作业与各步骤的状态、退出码、stderr 和资源记录，区分内存不足、超时、
软件环境、输入路径或程序错误。给出有证据支持的原因和最小修改建议，暂不重提作业。
```

### 下载结果或取消指定作业

```text
使用 $bupt-scc-skill，将远端 /remote/project/run-001/slurm-12345.out
下载到本地 ./results/slurm-12345.out，先检查本地文件是否已经存在，避免覆盖。
```

```text
使用 $bupt-slurm-skill，核实作业 12345 属于我，然后取消这个作业并检查最终状态。
不要取消我的其他作业。
```

## 手动调用脚本

以下命令从仓库根目录执行，路径、分区名和作业 ID 都是示例。`submit` 会实际提交，`cancel` 会实际取消。

```bash
# 查询资源和队列
python3 skills/bupt-slurm-skill/scripts/slurm.py info
python3 skills/bupt-slurm-skill/scripts/slurm.py queue

# 预览提交：不联网，连接参数和计费 comment 会脱敏
python3 skills/bupt-slurm-skill/scripts/slurm.py --dry-run submit \
  /remote/run/job.sbatch --workdir /remote/run --partition PARTITION

# 提交远端已经存在且检查过的脚本
python3 skills/bupt-slurm-skill/scripts/slurm.py submit \
  /remote/run/job.sbatch --workdir /remote/run --partition PARTITION

# 检查状态与记账，取消指定作业
python3 skills/bupt-slurm-skill/scripts/slurm.py job 12345
python3 skills/bupt-slurm-skill/scripts/slurm.py accounting 12345
python3 skills/bupt-slurm-skill/scripts/slurm.py cancel 12345
```

SSH 和传输示例见 [连接技能](skills/bupt-scc-skill/SKILL.md)，作业规则见 [Slurm 技能](skills/bupt-slurm-skill/SKILL.md)。所有全局参数（如 `--dry-run`、`--identity`）放在子命令之前。

## 配置保护与常见问题

- `.env` / `.env.*` 已加入 `.gitignore`，仅空值 `.env.example` 可提交。不要使用 `git add -f .env`；分享日志前检查其中的账号、路径和 comment。Git 忽略规则不能清除已经发布的历史内容。
- 登录节点只做轻量查询和文件准备，训练和 GPU 测试通过 Slurm 运行。
- 提示缺少连接配置：检查实际 `.env` 位置、必填项和 `BUPT_SCC_ENV_FILE` 是否被执行进程读取。
- 提示缺少计费 comment：在本地填写 `BUPT_SLURM_COMMENT`，不要把真实值写入 sbatch 模板或公开 issue。
- 提示缺少同级 skill：检查两个目录是否同时存在、名称是否正确、符号链接目标是否有效。
- 队列里找不到作业：继续查记账和日志，不能仅凭队列为空判断成功。提交结果不明时先查重，避免重复计费。

## 更新与本地验证

在仓库目录运行 `git pull --ff-only` 更新代码。符号链接安装会使用更新后的文件；本地 `.env` 不受 Git 更新管理。若使用复制安装，需要同步更新两个 skill。

```bash
python3 -m unittest discover -s tests -v
```

测试使用虚构配置并模拟 SSH，不连接集群。真实的 `nvidia-smi` 作业验证需要单独提出提交请求。

Slurm 流程参考 [NVIDIA Megatron-LM 的 mcore-run-on-slurm](https://github.com/NVIDIA/Megatron-LM/blob/main/skills/mcore-run-on-slurm/SKILL.md)，已针对本仓库的连接配置和 comment 计费方式调整。

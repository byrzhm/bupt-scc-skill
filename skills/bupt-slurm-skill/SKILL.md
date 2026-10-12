---
name: bupt-slurm-skill
description: 供 Codex、Claude Code 等 Agent 从本机或经 SSH 在北邮超算上使用 Slurm 发现资源、编写和提交 sbatch 作业、通过私有 comment 配置计费、跟踪日志与退出状态，以及排查 GPU 或分布式训练任务。适用于 sbatch、srun、排队、作业取消和 nvidia-smi 冒烟检查。
---

# 北邮 Slurm 作业

## 连接与计费

依赖同级 [bupt-scc-skill](../bupt-scc-skill/SKILL.md) 的执行方式选择、文件传输和配置解析脚本，两个技能须一起安装；首先阅读其配置部分。`scripts/slurm.py` 共用仓库根目录 `.env`，也支持 `BUPT_SCC_ENV_FILE` 指定外部配置文件。

`BUPT_SCC_MODE=ssh`（默认）从个人电脑连接集群；`BUPT_SCC_MODE=local` 在集群上以当前账号直接执行 `sbatch`、`sacct` 等命令，不需要 SSH 连接字段。命令行 `--mode` 可单次覆盖。两种模式共享相同的计费、作业 ID、错误处理与脱敏规则。不要因本机模式而绕过 Slurm 在登录节点执行计算。

local 模式使用 Agent 进程继承的 PATH 和软件环境。若查询提示找不到 Slurm 命令，应先按集群实际配置初始化模块；不要自动切回 SSH 或安装另一套调度器。

**提交必须设置 `BUPT_SLURM_COMMENT`。** 其值由用户提供，只存入本地 `.env` 或进程环境。封装通过 `sbatch --comment=...` 传递，不硬编码到模板、文档或测试中，不用 `--account` 替代。缺失或空白时在执行前报错。可选 `BUPT_SLURM_PARTITION` 提供默认分区，`submit --partition` 可覆盖。

命令行 comment 优先于作业文件内的指令；模板不应包含真实计费值。不要直接绕过封装提交而漏掉 comment。若任务确需 `salloc` 或独立 `srun` 创建分配，先核实当地规则并从同一配置传递计费信息；作业内的 `srun` 使用已有分配。

用户要求准备时只准备，要求提交时执行其授权范围内的提交；不要把技能触发视为无限制消耗资源的授权。提交失败不自动重试，连接中断时先查是否受理。

## 发现资源与准备

从本技能目录运行，其他位置使用脚本绝对路径：

```bash
python3 scripts/slurm.py info
python3 scripts/slurm.py queue
python3 ../bupt-scc-skill/scripts/scc.py exec -- sinfo -N -o '%N %P %c %m %G %t'
python3 ../bupt-scc-skill/scripts/scc.py exec -- scontrol show partition
```

按当前查询确定 GPU 类型/GRES、可用分区、资源限制和用户权限，不将一次查询结果写成永久默认。仅在确实需要时向用户询问账户、QoS、程序命令或输入位置。

- 代码、数据、日志和检查点应位于分配节点都能访问的目录；本地路径和节点临时目录不能直接当作共享工作目录。
- 明确节点数、任务数、CPU、GPU、内存、时间和输出位置；按实际需求申请。核实模块、虚拟环境或容器再编写初始化步骤，不假设交互登录环境自动继承。
- `#SBATCH` 放在首个可执行语句前，指令中不展开 shell 变量。日志父目录和工作目录必须在提交前存在。
- 普通任务从 [job.sbatch](assets/job.sbatch) 修改；GPU 连通性检查使用 [nvidia-smi.sbatch](assets/nvidia-smi.sbatch)，只申请 1 张 GPU，时间上限 2 分钟。分区通过提交参数指定，计费通过 `.env` 注入。
- 只有涉及 Megatron 或 PyTorch 多节点训练时，阅读 [分布式训练参考](references/distributed-training.md)。不要求简单 GPU 检查安装训练依赖或容器。

## 提交与验证

下面路径仅作示意，先在选定执行模式下查出集群上的真实绝对路径。为每次运行创建独立目录，准备脚本时避免覆盖正在运行作业的文件。SSH 模式先上传；local 模式直接使用集群上已有脚本路径或复制到运行目录，跳过 upload。

```bash
python3 ../bupt-scc-skill/scripts/scc.py upload assets/nvidia-smi.sbatch /remote/run/nvidia-smi.sbatch
python3 scripts/slurm.py --dry-run submit /remote/run/nvidia-smi.sbatch --workdir /remote/run --partition PARTITION
python3 scripts/slurm.py submit /remote/run/nvidia-smi.sbatch --workdir /remote/run --partition PARTITION
```

在集群上可直接运行（路径需替换）：

```bash
python3 scripts/slurm.py --mode local info
python3 scripts/slurm.py --mode local --dry-run submit /shared/run/job.sbatch --workdir /shared/run --partition PARTITION
```

预览只打印脱敏命令，不执行命令、不检查目标文件。`submit` 接受集群上的绝对脚本路径和工作目录，还支持可选 `--account`、`--qos`。读取 `sbatch --parsable` 返回的作业 ID（可能带 `;集群名`），记录脚本、目录、资源与提交时间，但不持久化真实 comment。

若 SSH 中断、返回异常或 ID 不完整，先用名称、时间、工作目录、当前用户队列与记账记录查重。仍不确定就报告不确定性，不重复提交。

## 监控与失败定位

```bash
python3 scripts/slurm.py queue
python3 scripts/slurm.py job 12345
python3 scripts/slurm.py accounting 12345
python3 ../bupt-scc-skill/scripts/scc.py exec -- tail -n 100 /remote/run/slurm-12345.out
python3 ../bupt-scc-skill/scripts/scc.py exec -- tail -n 100 /remote/run/slurm-12345.err
python3 scripts/slurm.py cancel 12345
```

`queue` 只看当前用户；`job` 去掉标准 `scontrol` 输出中的 Comment 行，但剩余内容仍可能含账号和路径。原始 Slurm 查询可能显示 comment，不能作为公开日志上传。`accounting` 包括步骤记录，有助于检查退出码与 MaxRSS。

- 等待时查看原因和限制，使用合理间隔查询，避免高频轮询或反复重投；长时间排队先汇报事实，不扩大资源范围。
- 作业离开队列不等于成功。结合终态、主作业/步骤退出码、stderr 和预期输出判断。记账可能延迟或未启用，MaxRSS 可能只在步骤记录中或不可用。
- `nvidia-smi` 检查以打印 GPU 信息、作业 `COMPLETED` 和退出码 `0:0` 为成功证据；它不等于训练环境通过验证。
- 按内存、时间上限、依赖环境、文件路径或程序错误定位失败。多进程任务先检查各 rank 最早的实际错误，不只追踪后续通信超时。
- 取消前核对归属和 ID。封装只支持普通 ID 和单个数组任务 ID，取消数组父 ID 会影响整个数组。不得擅自按用户批量取消。

结果报告包含作业 ID、终态、退出码、资源和日志位置。测试日志与连接/计费信息只保留在本地私有输出或远端运行目录，不提交 GitHub。

## 来源与本地验证

流程参考 [NVIDIA Megatron-LM 的 mcore-run-on-slurm](https://github.com/NVIDIA/Megatron-LM/blob/main/skills/mcore-run-on-slurm/SKILL.md)，采用共享路径、明确启动环境和结合日志诊断的思路；北邮的 comment 计费要求由用户提供，不来自该参考。

命令语义参见 [sbatch](https://slurm.schedmd.com/sbatch.html)、[squeue](https://slurm.schedmd.com/squeue.html)、[sacct](https://slurm.schedmd.com/sacct.html)。以远端版本和本站规则为准。

仓库根目录运行 `python3 -m unittest discover -s tests -v`，测试使用虚构配置和模拟 SSH，不消耗集群资源。

# 按需阅读：Megatron / PyTorch 分布式训练

参考 [NVIDIA mcore-run-on-slurm](https://github.com/NVIDIA/Megatron-LM/blob/main/skills/mcore-run-on-slurm/SKILL.md)（2026-10-12 阅读）。以下是任务准备要点，不是已验证的北邮训练配置。

- 所有节点须能访问同一份代码、环境、输入和输出目录。先在合适环境准备依赖，避免每个 worker 启动时重复安装。
- 使用每节点一个 Slurm 启动任务，再由训练启动器派生该节点的 GPU workers。总进程数应等于节点数乘每节点 worker 数，后者与可见 GPU 数匹配，避免双重派生。
- 主节点地址从分配节点列表确定，选定可用通信端口。各节点共享地址、端口和总节点数，并通过节点 rank 区分；跨节点组成同一 worker group。
- Megatron 的 uv 环境使用 `uv run python -m torch.distributed.run`，明确传入 `--nnodes`、`--nproc-per-node`、`--node-rank`、`--master-addr`、`--master-port`。普通 PyTorch 项目应使用其已验证的 Python 环境，不盲目强制 uv。
- 不统一设置 `CUDA_DEVICE_MAX_CONNECTIONS`。其值依赖 GPU 代际、TP/CP、FSDP 和通信重叠方案；实际运行前查项目当前要求。
- 容器是可选项。先检查集群支持的容器机制、挂载和 CUDA/NCCL/PyTorch 兼容性，不假设存在 Pyxis 或特定镜像。
- 收集各 rank 的错误，以最早的异常为线索；检查 OOM、并行维度、导入环境及网络。先验收输出，再结合调度状态确认结果。

即便采用训练模板，北邮提交仍须使用本地 `BUPT_SLURM_COMMENT` 注入 `--comment`，不要复制参考中的账户或分区示例作为本站配置。

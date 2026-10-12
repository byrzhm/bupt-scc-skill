#!/bin/bash
#SBATCH --job-name=bupt-smoke
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:05:00
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err

# 根据实际集群要求，在首个可执行语句前加入 partition/account/qos 等指令。
# 此模板依赖提交时指定的工作目录，资源值仅用于轻量冒烟检查。
set -euo pipefail
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"

# 在这里显式初始化经核实的软件环境，然后替换下方冒烟检查命令。
printf 'Job: %s\nWorkdir: %s\n' "$SLURM_JOB_ID" "$PWD"
srun hostname

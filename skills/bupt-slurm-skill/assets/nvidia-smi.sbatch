#!/bin/bash
#SBATCH --job-name=bupt-gpu-smoke
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --gres=gpu:1
#SBATCH --mem=1G
#SBATCH --time=00:02:00
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err

# Partition and billing comment are supplied by slurm.py at submission time.
set -euo pipefail
printf 'Job: %s\nHost: %s\nVisible GPUs: %s\n' \
    "$SLURM_JOB_ID" "$(hostname)" "${CUDA_VISIBLE_DEVICES:-unset}"
srun --ntasks=1 nvidia-smi

#!/bin/sh
# Print "gpu" if Docker containers can use an NVIDIA GPU, otherwise "cpu".
# Override with NEXUS_PROFILE=gpu|cpu.
set -eu

if [ -n "${NEXUS_PROFILE:-}" ]; then
  echo "$NEXUS_PROFILE"
  exit 0
fi

if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  # The host has a GPU; confirm the container runtime can actually expose it.
  if docker run --rm --gpus all --entrypoint nvidia-smi ollama/ollama:0.40.16 -L >/dev/null 2>&1; then
    echo gpu
    exit 0
  fi
fi
echo cpu

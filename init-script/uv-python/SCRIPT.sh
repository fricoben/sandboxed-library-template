#!/usr/bin/env bash
# Description: Install uv (fast Python package manager)

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="/root/.local/bin:$PATH"
fi

# Ensure uv is in PATH for future sessions
if ! grep -q '.local/bin' /root/.bashrc 2>/dev/null; then
  echo 'export PATH="/root/.local/bin:$PATH"' >> /root/.bashrc
fi

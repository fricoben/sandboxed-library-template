#!/usr/bin/env bash
# Description: Install Bun and MCP packages for AI agent tooling

if ! command -v bun >/dev/null 2>&1; then
  curl -fsSL https://bun.sh/install | bash
  export BUN_INSTALL="/root/.bun"
  export PATH="$BUN_INSTALL/bin:$PATH"
fi

# Ensure bun/bunx are available in standard paths (for MCP server resolution)
if [ -f /root/.bun/bin/bun ] && [ ! -f /usr/local/bin/bun ]; then
  ln -sf /root/.bun/bin/bun /usr/local/bin/bun
fi
if [ -f /root/.bun/bin/bunx ] && [ ! -f /usr/local/bin/bunx ]; then
  ln -sf /root/.bun/bin/bunx /usr/local/bin/bunx
fi

# Install Playwright MCP (skip anthropic packages as they don't exist on npm)
if command -v bun >/dev/null 2>&1; then
  bun install --global @playwright/mcp@latest || true
fi

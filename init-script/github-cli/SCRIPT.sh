#!/usr/bin/env bash
# Description: Install GitHub CLI (gh)

if ! command -v gh >/dev/null 2>&1; then
  GH_VERSION=$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest | sed -n 's/.*"tag_name": "v\([^"]*\)".*/\1/p' | head -n1) || true
  if [ -n "$GH_VERSION" ]; then
    curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" -o /tmp/gh.tar.gz
    tar -xzf /tmp/gh.tar.gz -C /tmp
    mv /tmp/gh_${GH_VERSION}_linux_amd64/bin/gh /usr/local/bin/gh
    chmod +x /usr/local/bin/gh
    rm -rf /tmp/gh.tar.gz /tmp/gh_${GH_VERSION}_linux_amd64
  fi
fi

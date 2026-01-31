#!/usr/bin/env bash
# Description: Install Bitwarden Secrets Manager CLI (bws)

if ! command -v bws >/dev/null 2>&1; then
  # Find latest bws-v* release from bitwarden/sdk repo
  BWS_VERSION=$(curl -fsSL https://api.github.com/repos/bitwarden/sdk/releases | grep -o '"tag_name": "bws-v[^"]*"' | head -1 | sed 's/.*bws-v\([^"]*\)".*/\1/') || true
  if [ -n "$BWS_VERSION" ]; then
    curl -fsSL "https://github.com/bitwarden/sdk/releases/download/bws-v${BWS_VERSION}/bws-x86_64-unknown-linux-gnu-${BWS_VERSION}.zip" -o /tmp/bws.zip
    unzip -o /tmp/bws.zip -d /tmp/bws
    mv /tmp/bws/bws /usr/local/bin/bws
    chmod +x /usr/local/bin/bws
    rm -rf /tmp/bws.zip /tmp/bws
  fi
fi

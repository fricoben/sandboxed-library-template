#!/usr/bin/env bash
# Description: SSH key setup from SSH_PRIVATE_KEY_B64 environment variable

mkdir -p /root/.ssh
chmod 700 /root/.ssh

# Add known hosts for common Git providers
for host in github.com gitlab.com bitbucket.org; do
  ssh-keyscan -T 5 "$host" >> /root/.ssh/known_hosts 2>/dev/null || true
done
chmod 600 /root/.ssh/known_hosts 2>/dev/null || true

# Setup SSH key from base64-encoded environment variable
if [ -n "${SSH_PRIVATE_KEY_B64:-}" ]; then
  echo "$SSH_PRIVATE_KEY_B64" | base64 -d > /root/.ssh/id_ed25519
  chmod 600 /root/.ssh/id_ed25519
  ssh-keygen -y -f /root/.ssh/id_ed25519 > /root/.ssh/id_ed25519.pub 2>/dev/null && chmod 644 /root/.ssh/id_ed25519.pub

  if ! grep -q "Host github.com gitlab.com bitbucket.org" /root/.ssh/config 2>/dev/null; then
    cat >> /root/.ssh/config <<'SSHEOF'
Host github.com gitlab.com bitbucket.org
  IdentityFile /root/.ssh/id_ed25519
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
SSHEOF
  fi
  chmod 600 /root/.ssh/config
fi

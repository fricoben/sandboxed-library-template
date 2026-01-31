#!/usr/bin/env bash
# Description: Base logging, retry helper, apt update, and essential system packages

set -euo pipefail

LOG=/var/log/openagent-init.log
exec > >(tee -a "$LOG") 2>&1
trap 'echo "Init failed at line $LINENO: $BASH_COMMAND" >&2' ERR

export DEBIAN_FRONTEND=noninteractive

retry() {
  local n=0
  local max="${RETRY_MAX:-5}"
  local delay="${RETRY_DELAY:-2}"
  until "$@"; do
    n=$((n+1))
    if [ "$n" -ge "$max" ]; then
      return 1
    fi
    sleep "$delay"
  done
}

# Configure apt sources for Ubuntu noble (with security updates)
if command -v apt-get >/dev/null 2>&1; then
  cat > /etc/apt/sources.list <<'EOFAPT'
deb http://archive.ubuntu.com/ubuntu noble main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu noble-updates main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu noble-security main restricted universe multiverse
EOFAPT

  retry apt-get update
  
  # Full system upgrade to resolve dependency issues
  retry apt-get dist-upgrade -y || true
  
  retry apt-get install -y --no-install-recommends \
    ca-certificates curl wget unzip zip git gnupg jq ripgrep \
    iproute2 iptables iputils-ping dnsutils netcat-openbsd procps psmisc lsof fd-find less nano tree \
    busybox openssh-client rsync nodejs npm
fi

# Provide fd command (Debian/Ubuntu package uses fdfind)
if command -v fdfind >/dev/null 2>&1 && ! command -v fd >/dev/null 2>&1; then
  ln -sf "$(command -v fdfind)" /usr/local/bin/fd
fi

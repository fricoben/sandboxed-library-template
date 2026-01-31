#!/usr/bin/env bash
# Description: Network bootstrap scripts for veth/udhcpc container networking

# Link busybox utilities
if command -v busybox >/dev/null 2>&1; then
  ln -sf "$(command -v busybox)" /usr/local/bin/udhcpc
  ln -sf "$(command -v busybox)" /usr/local/bin/udhcpc6
fi

# Create network bootstrap script for veth networking
cat >/usr/local/bin/openagent-network-up <<'NETSCRIPT'
#!/bin/bash
set -e
if ip link show host0 &>/dev/null; then
  ip link set host0 up || true
  busybox udhcpc -i host0 -n -q -f -s /etc/udhcpc/default.script 2>/dev/null || true
fi
NETSCRIPT
chmod +x /usr/local/bin/openagent-network-up

# Create udhcpc script directory and default script
mkdir -p /etc/udhcpc
cat >/etc/udhcpc/default.script <<'DHCP'
#!/bin/sh
case "$1" in
  deconfig) ip addr flush dev "$interface" ;;
  bound|renew) ip addr add "$ip/$mask" dev "$interface"
    [ -n "$router" ] && ip route add default via "$router" dev "$interface" || true ;;
esac
DHCP
chmod +x /etc/udhcpc/default.script

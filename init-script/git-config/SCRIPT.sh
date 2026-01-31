#!/usr/bin/env bash
# Description: Git user configuration and GPG signing setup

# Git configuration
git config --global user.name "Thomas Marchand (agent)"
git config --global user.email "agent@thomas.md"
git config --global init.defaultBranch main

# Setup GPG key for commit signing
if [ -n "${GPG_PRIVATE_KEY_B64:-}" ]; then
  echo "$GPG_PRIVATE_KEY_B64" | base64 -d | gpg --batch --import 2>/dev/null || true
  GPG_KEY_ID=$(gpg --list-secret-keys --with-colons agent@thomas.md 2>/dev/null | awk -F: '/^sec/{print $5; exit}') || true
  if [ -n "$GPG_KEY_ID" ]; then
    git config --global user.signingkey "$GPG_KEY_ID"
    git config --global commit.gpgsign true
    git config --global tag.gpgsign true
    printf '%s:6:\n' "$GPG_KEY_ID" | gpg --import-ownertrust >/dev/null 2>&1 || true
  fi
fi

#!/usr/bin/env python3
"""
Sync OpenAgent library contents to Claude Code and Codex/Opencode configurations.

This script compiles skills, commands, and MCP servers from this repository
to the appropriate config formats for various AI coding tools:

  - Skills → ~/.claude/skills/ and ~/.codex/skills/
  - Commands → ~/.claude/commands/ and ~/.codex/prompts/
  - MCP servers → ~/.claude.json (mcpServers) and ~/.codex/config.toml (mcp_servers)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from uuid import uuid4

from utils import (
    CRYPTO_AVAILABLE,
    MARKER_FILE,
    convert_mcp_to_codex_toml,
    decrypt_directory,
    has_encrypted_tags,
    iter_command_files,
    iter_skill_dirs,
    load_mcp_config,
    load_private_key,
    marker_contents,
    substitute_directory,
    validate_skill,
)

# Global state for encryption
_private_key: bytes | None = None
_encryption_warned: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync library contents to Claude Code and Codex configurations"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show actions without making changes"
    )
    parser.add_argument(
        "--prune", action="store_true", help="Remove managed items not in source"
    )

    # Content type filters
    content_group = parser.add_mutually_exclusive_group()
    content_group.add_argument(
        "--skills-only", action="store_true", help="Only sync skills"
    )
    content_group.add_argument(
        "--commands-only", action="store_true", help="Only sync commands"
    )
    content_group.add_argument(
        "--mcp-only", action="store_true", help="Only sync MCP servers"
    )

    # Target filters
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--claude-only", action="store_true", help="Only sync to Claude Code"
    )
    target_group.add_argument(
        "--codex-only", action="store_true", help="Only sync to Codex/Opencode"
    )

    # Custom directories
    parser.add_argument(
        "--claude-skills-dir",
        default=os.getenv("CLAUDE_SKILLS_DIR", "~/.claude/skills"),
    )
    parser.add_argument(
        "--claude-commands-dir",
        default=os.getenv("CLAUDE_COMMANDS_DIR", "~/.claude/commands"),
    )
    parser.add_argument(
        "--codex-skills-dir", default=os.getenv("CODEX_SKILLS_DIR", "~/.codex/skills")
    )
    parser.add_argument(
        "--codex-prompts-dir",
        default=os.getenv("CODEX_PROMPTS_DIR", "~/.codex/prompts"),
    )

    # Specific items
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Limit to specific item names (repeatable)",
    )

    return parser.parse_args()


def expand_path(path_str: str) -> Path:
    return Path(os.path.expanduser(path_str)).resolve()


# =============================================================================
# Skills Sync
# =============================================================================


def copy_skill(
    src: Path, dest_root: Path, dry_run: bool, env: dict[str, str]
) -> list[str]:
    """Copy skill to destination, decrypting secrets and substituting placeholders."""
    global _encryption_warned
    dest = dest_root / src.name

    if dry_run:
        print(f"  DRY-RUN: {src.name} → {dest}")
        return []

    dest_root.mkdir(parents=True, exist_ok=True)
    tmp = dest_root / f".{src.name}.tmp-{uuid4().hex}"

    if tmp.exists():
        shutil.rmtree(tmp)

    shutil.copytree(src, tmp)

    # Decrypt encrypted content tags
    decrypted, stripped = decrypt_directory(tmp, _private_key)
    if stripped > 0 and not _encryption_warned:
        print("\n  WARNING: Some encrypted values could not be decrypted.")
        print("           Set PRIVATE_KEY in .env or environment to decrypt secrets.")
        _encryption_warned = True

    # Substitute environment variable placeholders
    unresolved = substitute_directory(tmp, env)

    marker_path = tmp / MARKER_FILE
    marker_path.write_text(marker_contents("skill", src.name), encoding="utf-8")

    if dest.exists():
        shutil.rmtree(dest)

    tmp.rename(dest)

    status = f"  COPY: {src.name} → {dest}"
    if decrypted > 0:
        status += f" (decrypted {decrypted} file(s))"
    print(status)
    return unresolved


def prune_skills(dest_root: Path, keep: set[str], dry_run: bool) -> None:
    """Remove managed skills not in the keep set."""
    if not dest_root.exists():
        return
    for child in sorted(dest_root.iterdir()):
        marker = child / MARKER_FILE
        if child.is_dir() and marker.exists() and child.name not in keep:
            if dry_run:
                print(f"  DRY-RUN: prune {child}")
            else:
                shutil.rmtree(child)
                print(f"  PRUNE: {child}")


def sync_skills(args: argparse.Namespace) -> int:
    """Sync skills to Claude Code and Codex."""
    print("=" * 60)
    print("SKILLS")
    print("=" * 60)

    only_set = set()
    for item in args.only:
        only_set.update(name.strip() for name in item.split(",") if name.strip())

    skill_dirs = list(iter_skill_dirs())
    if only_set:
        skill_dirs = [p for p in skill_dirs if p.name in only_set]

    # Validate skills
    all_errors = []
    for skill_dir in skill_dirs:
        _, errors = validate_skill(skill_dir)
        all_errors.extend(errors)

    if all_errors:
        for issue in all_errors:
            print(f"ERROR: {issue.name}: {issue.message}")
        return 1

    if not skill_dirs:
        print("No skills found in skill/")
        if args.prune and not only_set:
            if not args.codex_only:
                prune_skills(expand_path(args.claude_skills_dir), set(), args.dry_run)
            if not args.claude_only:
                prune_skills(expand_path(args.codex_skills_dir), set(), args.dry_run)
        return 0

    print(f"Found {len(skill_dirs)} skill(s): {', '.join(p.name for p in skill_dirs)}")

    env = dict(os.environ)
    all_unresolved: set[str] = set()

    # Sync to Claude Code
    if not args.codex_only:
        claude_dir = expand_path(args.claude_skills_dir)
        print(f"\nSyncing to Claude Code ({claude_dir}):")
        for skill_dir in skill_dirs:
            unresolved = copy_skill(skill_dir, claude_dir, args.dry_run, env)
            all_unresolved.update(unresolved)

    # Sync to Codex
    if not args.claude_only:
        codex_dir = expand_path(args.codex_skills_dir)
        print(f"\nSyncing to Codex ({codex_dir}):")
        for skill_dir in skill_dirs:
            unresolved = copy_skill(skill_dir, codex_dir, args.dry_run, env)
            all_unresolved.update(unresolved)

    if all_unresolved:
        print(
            f"\nWARNING: unresolved placeholders: {', '.join(sorted(all_unresolved))}"
        )

    # Prune
    if args.prune and not only_set:
        keep = {p.name for p in skill_dirs}
        print("\nPruning orphaned skills:")
        if not args.codex_only:
            prune_skills(expand_path(args.claude_skills_dir), keep, args.dry_run)
        if not args.claude_only:
            prune_skills(expand_path(args.codex_skills_dir), keep, args.dry_run)

    return 0


# =============================================================================
# Commands Sync
# =============================================================================


def copy_command(src: Path, dest_dir: Path, dry_run: bool) -> None:
    """Copy a command file to the destination directory, decrypting secrets."""
    global _encryption_warned
    dest = dest_dir / src.name
    marker_path = dest_dir / f".{src.stem}{MARKER_FILE}"

    if dry_run:
        print(f"  DRY-RUN: {src.name} → {dest}")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)

    # Read, decrypt if needed, and write
    content = src.read_text(encoding="utf-8")
    was_decrypted = False

    if has_encrypted_tags(content):
        from utils import decrypt_or_strip_content

        new_content, was_decrypted = decrypt_or_strip_content(content, _private_key)
        if not was_decrypted and not _encryption_warned:
            print("\n  WARNING: Some encrypted values could not be decrypted.")
            print(
                "           Set PRIVATE_KEY in .env or environment to decrypt secrets."
            )
            _encryption_warned = True
        content = new_content

    dest.write_text(content, encoding="utf-8")
    marker_path.write_text(marker_contents("command", src.stem), encoding="utf-8")

    status = f"  COPY: {src.name} → {dest}"
    if was_decrypted:
        status += " (decrypted)"
    print(status)


def prune_commands(dest_dir: Path, keep: set[str], dry_run: bool) -> None:
    """Remove managed commands not in the keep set."""
    if not dest_dir.exists():
        return

    for marker in dest_dir.glob(f".*{MARKER_FILE}"):
        command_name = marker.name[1:].replace(MARKER_FILE, "")
        if command_name not in keep:
            command_file = dest_dir / f"{command_name}.md"
            if dry_run:
                print(f"  DRY-RUN: prune {command_file}")
            else:
                if command_file.exists():
                    command_file.unlink()
                marker.unlink()
                print(f"  PRUNE: {command_file}")


def sync_commands(args: argparse.Namespace) -> int:
    """Sync commands to Claude Code and Codex."""
    print("\n" + "=" * 60)
    print("COMMANDS")
    print("=" * 60)

    only_set = set()
    for item in args.only:
        only_set.update(name.strip() for name in item.split(",") if name.strip())

    command_files = list(iter_command_files())
    if only_set:
        command_files = [f for f in command_files if f.stem in only_set]

    if not command_files:
        print("No commands found in command/")
        if args.prune and not only_set:
            if not args.codex_only:
                prune_commands(
                    expand_path(args.claude_commands_dir), set(), args.dry_run
                )
            if not args.claude_only:
                prune_commands(expand_path(args.codex_prompts_dir), set(), args.dry_run)
        return 0

    print(
        f"Found {len(command_files)} command(s): {', '.join(f.stem for f in command_files)}"
    )

    # Sync to Claude Code
    if not args.codex_only:
        claude_dir = expand_path(args.claude_commands_dir)
        print(f"\nSyncing to Claude Code ({claude_dir}):")
        for cmd_file in command_files:
            copy_command(cmd_file, claude_dir, args.dry_run)

    # Sync to Codex
    if not args.claude_only:
        codex_dir = expand_path(args.codex_prompts_dir)
        print(f"\nSyncing to Codex ({codex_dir}):")
        for cmd_file in command_files:
            copy_command(cmd_file, codex_dir, args.dry_run)

    # Prune
    if args.prune and not only_set:
        keep = {f.stem for f in command_files}
        print("\nPruning orphaned commands:")
        if not args.codex_only:
            prune_commands(expand_path(args.claude_commands_dir), keep, args.dry_run)
        if not args.claude_only:
            prune_commands(expand_path(args.codex_prompts_dir), keep, args.dry_run)

    return 0


# =============================================================================
# MCP Sync
# =============================================================================


def sync_mcp_to_claude(servers: dict, dry_run: bool) -> None:
    """Sync MCP servers to Claude Code's ~/.claude.json."""
    claude_json_path = Path.home() / ".claude.json"

    if claude_json_path.exists():
        config = json.loads(claude_json_path.read_text(encoding="utf-8"))
    else:
        config = {}

    config["mcpServers"] = servers

    if dry_run:
        print(f"  DRY-RUN: would update {claude_json_path}")
        print(f"  Servers: {list(servers.keys())}")
    else:
        if claude_json_path.exists():
            backup_path = claude_json_path.with_suffix(".json.bak")
            shutil.copy2(claude_json_path, backup_path)

        claude_json_path.write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )
        print(f"  UPDATED: {claude_json_path}")
        print(f"  Servers: {list(servers.keys())}")


def sync_mcp_to_codex(servers: dict, dry_run: bool) -> None:
    """Sync MCP servers to Codex's ~/.codex/config.toml."""
    codex_dir = Path.home() / ".codex"
    config_path = codex_dir / "config.toml"

    if not codex_dir.exists():
        if dry_run:
            print(f"  DRY-RUN: would create {codex_dir}")
        else:
            codex_dir.mkdir(parents=True, exist_ok=True)

    existing_content = ""
    if config_path.exists():
        existing_content = config_path.read_text(encoding="utf-8")

    # Remove existing [mcp_servers.*] sections
    cleaned_content = re.sub(
        r"^\[mcp_servers\.[^\]]+\].*?(?=^\[(?!mcp_servers\.)|$(?![\r\n]))",
        "",
        existing_content,
        flags=re.MULTILINE | re.DOTALL,
    )
    cleaned_content = re.sub(r"\n{3,}", "\n\n", cleaned_content.strip())

    mcp_toml = convert_mcp_to_codex_toml(servers)

    if cleaned_content:
        new_content = cleaned_content + "\n\n" + mcp_toml
    else:
        new_content = mcp_toml

    if dry_run:
        print(f"  DRY-RUN: would update {config_path}")
        print(f"  Servers: {list(servers.keys())}")
    else:
        if config_path.exists():
            backup_path = config_path.with_suffix(".toml.bak")
            shutil.copy2(config_path, backup_path)

        config_path.write_text(new_content, encoding="utf-8")
        print(f"  UPDATED: {config_path}")
        print(f"  Servers: {list(servers.keys())}")


def sync_mcp(args: argparse.Namespace) -> int:
    """Sync MCP servers to Claude Code and Codex."""
    print("\n" + "=" * 60)
    print("MCP SERVERS")
    print("=" * 60)

    servers = load_mcp_config()

    if not servers:
        print("No MCP servers found in mcp/servers.json")
        return 0

    print(f"Found {len(servers)} server(s): {', '.join(servers.keys())}")

    if not args.codex_only:
        print(f"\nSyncing to Claude Code:")
        sync_mcp_to_claude(servers, args.dry_run)

    if not args.claude_only:
        print(f"\nSyncing to Codex:")
        sync_mcp_to_codex(servers, args.dry_run)

    return 0


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    global _private_key

    args = parse_args()

    print("OpenAgent Library Sync")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    if args.prune:
        print("Pruning: ENABLED")

    # Load encryption key
    _private_key = load_private_key()
    if _private_key:
        print("Encryption: PRIVATE_KEY loaded")
    elif CRYPTO_AVAILABLE:
        print("Encryption: No PRIVATE_KEY (encrypted values will be stripped)")
    else:
        print("Encryption: cryptography library not installed")

    errors = 0

    # Determine what to sync
    sync_all = not (args.skills_only or args.commands_only or args.mcp_only)

    if sync_all or args.skills_only:
        errors += sync_skills(args)

    if sync_all or args.commands_only:
        errors += sync_commands(args)

    if sync_all or args.mcp_only:
        errors += sync_mcp(args)

    print("\n" + "=" * 60)
    if errors:
        print(f"COMPLETED WITH {errors} ERROR(S)")
    else:
        print("SYNC COMPLETE")
    print("=" * 60)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

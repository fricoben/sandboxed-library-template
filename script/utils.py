#!/usr/bin/env python3
"""Shared utilities for library sync scripts."""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Optional cryptography import - gracefully degrade if not available
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

FRONTMATTER_BOUNDARY = "---"
MARKER_FILE = ".managed-by-openagent-library"

# Environment variable placeholder pattern: ${VAR_NAME}
ENV_PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Encryption constants
KEY_LENGTH = 32  # 256 bits for AES-256
NONCE_LENGTH = 12  # 96 bits for AES-GCM
PRIVATE_KEY_ENV = "PRIVATE_KEY"
ENCRYPTION_VERSION = "1"

# Regex patterns for encrypted tags
VERSIONED_TAG_PATTERN = re.compile(r'<encrypted v="(\d+)">([^<]*)</encrypted>')
ANY_ENCRYPTED_TAG_PATTERN = re.compile(r'<encrypted(?:\s+v="\d+")?>([^<]*)</encrypted>')

# Patterns for detecting leaked secrets
UNSAFE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"ASIA[0-9A-Z]{16}"), "AWS temporary access key id"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "Google API key"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI API key"),
    (re.compile(r"sk-proj-[A-Za-z0-9]{10,}"), "OpenAI project API key"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "GitHub personal access token"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"-----BEGIN PRIVATE KEY-----"), "private key block"),
]

TEXT_EXTENSIONS = {".md", ".txt", ".yaml", ".yml", ".json", ".py", ".sh"}


@dataclass
class ValidationIssue:
    name: str
    message: str


class FrontmatterError(ValueError):
    pass


def repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parents[1]


def skills_root() -> Path:
    return repo_root() / "skill"


def commands_root() -> Path:
    return repo_root() / "command"


def mcp_config_path() -> Path:
    return repo_root() / "mcp" / "servers.json"


def iter_skill_dirs() -> list[Path]:
    """Iterate over all skill directories (those containing SKILL.md)."""
    root = skills_root()
    if not root.exists():
        return []
    return [
        p for p in sorted(root.iterdir()) if p.is_dir() and (p / "SKILL.md").exists()
    ]


def iter_command_files() -> list[Path]:
    """Iterate over all command files (.md files in command/)."""
    root = commands_root()
    if not root.exists():
        return []
    return sorted(
        [
            f
            for f in root.iterdir()
            if f.is_file() and f.suffix == ".md" and not f.name.startswith(".")
        ]
    )


def parse_frontmatter(text: str) -> dict[str, str]:
    """Parse YAML frontmatter from text."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_BOUNDARY:
        raise FrontmatterError("missing frontmatter opening '---'")

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == FRONTMATTER_BOUNDARY:
            end_idx = idx
            break
    if end_idx is None:
        raise FrontmatterError("missing frontmatter closing '---'")

    block = lines[1:end_idx]
    data: dict[str, str] = {}
    i = 0
    while i < len(block):
        line = block[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith(" ") or line.startswith("\t"):
            raise FrontmatterError(f"unexpected indentation at line {i + 2}")
        if ":" not in line:
            raise FrontmatterError(f"invalid frontmatter line: {line}")
        key, rest = line.split(":", 1)
        key = key.strip()
        rest = rest.lstrip()
        if not key:
            raise FrontmatterError("empty key in frontmatter")
        if rest in (">", "|"):
            literal = rest == "|"
            collected: list[str] = []
            i += 1
            while i < len(block):
                next_line = block[i]
                if next_line.startswith(" ") or next_line.startswith("\t"):
                    collected.append(next_line.lstrip())
                    i += 1
                    continue
                break
            value = (
                "\n".join(collected)
                if literal
                else " ".join(l.strip() for l in collected)
            )
            data[key] = value.strip()
            continue
        value = rest.strip()
        if len(value) >= 2:
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
        data[key] = value
        i += 1
    return data


def detect_unsafe_patterns(content: str) -> list[str]:
    """Detect potentially leaked secrets in content."""
    hits = []
    for pattern, label in UNSAFE_PATTERNS:
        if pattern.search(content):
            hits.append(label)
    return hits


def word_count(text: str) -> int:
    """Count words in text."""
    return len(re.findall(r"\b\w+\b", text))


def validate_skill(skill_dir: Path) -> tuple[dict[str, str], list[ValidationIssue]]:
    """Validate a skill directory. Returns (frontmatter, errors)."""
    errors: list[ValidationIssue] = []
    skill_name = skill_dir.name
    skill_file = skill_dir / "SKILL.md"

    if not skill_file.exists():
        errors.append(ValidationIssue(skill_name, "missing SKILL.md"))
        return {}, errors

    content = skill_file.read_text(encoding="utf-8")
    try:
        frontmatter = parse_frontmatter(content)
    except FrontmatterError as exc:
        errors.append(ValidationIssue(skill_name, f"frontmatter error: {exc}"))
        return {}, errors

    name = frontmatter.get("name", "").strip()
    description = frontmatter.get("description", "").strip()

    if not name:
        errors.append(ValidationIssue(skill_name, "frontmatter 'name' is required"))
    elif name != skill_name:
        errors.append(
            ValidationIssue(
                skill_name, f"frontmatter name '{name}' does not match folder"
            )
        )

    if not description:
        errors.append(
            ValidationIssue(skill_name, "frontmatter 'description' is required")
        )

    unsafe = detect_unsafe_patterns(content)
    for label in unsafe:
        errors.append(ValidationIssue(skill_name, f"unsafe pattern detected: {label}"))

    wc = word_count(content)
    if wc > 2500 or len(content) > 15000:
        errors.append(
            ValidationIssue(
                skill_name, "SKILL.md is too long; move details to references/"
            )
        )

    return frontmatter, errors


def git_value(args: list[str]) -> str:
    """Get a value from git."""
    try:
        output = (
            subprocess.check_output(
                ["git"] + args,
                stderr=subprocess.DEVNULL,
                cwd=repo_root(),
            )
            .decode()
            .strip()
        )
        return output if output else "unknown"
    except Exception:
        return "unknown"


def marker_contents(item_type: str, item_name: str) -> str:
    """Generate marker file contents for tracking managed items."""
    repo_url = git_value(["config", "--get", "remote.origin.url"])
    commit = git_value(["rev-parse", "HEAD"])
    timestamp = datetime.now(timezone.utc).isoformat()
    return "\n".join(
        [
            f"repo: {repo_url}",
            f"commit: {commit}",
            f"timestamp_utc: {timestamp}",
            f"{item_type}: {item_name}",
            "",
        ]
    )


def substitute_placeholders(content: str, env: dict[str, str]) -> tuple[str, list[str]]:
    """
    Substitute ${VAR_NAME} placeholders with values from env dict.
    Returns (substituted_content, list_of_unresolved_placeholders).
    """
    unresolved: list[str] = []

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        if var_name in env:
            return env[var_name]
        unresolved.append(var_name)
        return match.group(0)

    result = ENV_PLACEHOLDER_PATTERN.sub(replacer, content)
    return result, unresolved


def substitute_file(file_path: Path, env: dict[str, str]) -> list[str]:
    """Substitute placeholders in a text file. Returns list of unresolved vars."""
    if file_path.suffix.lower() not in TEXT_EXTENSIONS:
        return []
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    new_content, unresolved = substitute_placeholders(content, env)
    if new_content != content:
        file_path.write_text(new_content, encoding="utf-8")
    return unresolved


def substitute_directory(dir_path: Path, env: dict[str, str]) -> list[str]:
    """Recursively substitute placeholders in all text files. Returns unresolved vars."""
    all_unresolved: list[str] = []
    for file_path in dir_path.rglob("*"):
        if file_path.is_file():
            unresolved = substitute_file(file_path, env)
            all_unresolved.extend(unresolved)
    return all_unresolved


def escape_toml_string(value: str) -> str:
    """Escape special characters for TOML double-quoted strings."""
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    value = value.replace("\t", "\\t")
    value = value.replace("\b", "\\b")
    value = value.replace("\f", "\\f")
    return value


def quote_toml_key(key: str) -> str:
    """Quote a TOML key if it contains special characters."""
    if re.match(r"^[A-Za-z0-9_-]+$", key):
        return key
    return f'"{escape_toml_string(key)}"'


def load_mcp_config() -> dict[str, Any]:
    """Load MCP configuration from mcp/servers.json."""
    config_path = mcp_config_path()
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def convert_mcp_to_codex_toml(servers: dict[str, Any]) -> str:
    """Convert MCP servers config to Codex TOML format."""
    lines: list[str] = []

    for name, config in servers.items():
        quoted_name = quote_toml_key(name)
        lines.append(f"[mcp_servers.{quoted_name}]")

        server_type = config.get("type", "stdio")

        if server_type == "http":
            url = escape_toml_string(config.get("url", ""))
            lines.append(f'url = "{url}"')
        else:
            command = escape_toml_string(config.get("command", ""))
            args = config.get("args", [])
            lines.append(f'command = "{command}"')
            if args:
                args_str = json.dumps(args)
                lines.append(f"args = {args_str}")

        env = config.get("env", {})
        if env:
            lines.append("")
            lines.append(f"[mcp_servers.{quoted_name}.env]")
            for key, value in env.items():
                quoted_key = quote_toml_key(key)
                escaped_value = escape_toml_string(str(value))
                lines.append(f'{quoted_key} = "{escaped_value}"')

        lines.append("")

    return "\n".join(lines)


# =============================================================================
# Encryption / Decryption
# =============================================================================


def load_dotenv() -> dict[str, str]:
    """Load environment variables from .env file in repo root."""
    env_file = repo_root() / ".env"
    env_vars: dict[str, str] = {}

    if not env_file.exists():
        return env_vars

    content = env_file.read_text(encoding="utf-8")
    for line in content.splitlines():
        line = line.strip()
        # Skip comments and empty lines
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Remove surrounding quotes
        if len(value) >= 2:
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
        env_vars[key] = value

    return env_vars


def parse_key(key_str: str) -> bytes:
    """Parse a key from hex or base64 format. Returns 32 bytes."""
    trimmed = key_str.strip()

    # Try hex first (64 characters = 32 bytes)
    if len(trimmed) == KEY_LENGTH * 2 and all(
        c in "0123456789abcdefABCDEF" for c in trimmed
    ):
        return bytes.fromhex(trimmed)

    # Try base64
    try:
        decoded = base64.b64decode(trimmed)
        if len(decoded) == KEY_LENGTH:
            return decoded
    except Exception:
        pass

    raise ValueError(
        f"Key must be {KEY_LENGTH} bytes (64 hex chars or base64). Got: {len(trimmed)} chars"
    )


def load_private_key() -> bytes | None:
    """
    Load the private key from environment or .env file.
    Returns None if not available.
    """
    # Check environment variable first
    key_str = os.environ.get(PRIVATE_KEY_ENV, "").strip()

    # Fall back to .env file
    if not key_str:
        dotenv = load_dotenv()
        key_str = dotenv.get(PRIVATE_KEY_ENV, "").strip()

    if not key_str:
        return None

    try:
        return parse_key(key_str)
    except ValueError as e:
        warnings.warn(f"Invalid {PRIVATE_KEY_ENV}: {e}")
        return None


def is_encrypted(value: str) -> bool:
    """Check if a value is an encrypted tag (versioned format)."""
    trimmed = value.strip()
    return trimmed.startswith('<encrypted v="') and trimmed.endswith("</encrypted>")


def has_encrypted_tags(content: str) -> bool:
    """Check if content contains any encrypted tags."""
    return '<encrypted v="' in content


def decrypt_value(key: bytes, encrypted_value: str) -> str:
    """
    Decrypt a single encrypted value.
    Format: <encrypted v="1">BASE64(nonce||ciphertext)</encrypted>
    Returns plaintext or raises an error.
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography library not available for decryption")

    # Parse the tag
    match = VERSIONED_TAG_PATTERN.match(encrypted_value.strip())
    if not match:
        # Not an encrypted value, return as-is
        return encrypted_value

    version = match.group(1)
    payload_b64 = match.group(2)

    if version != ENCRYPTION_VERSION:
        raise ValueError(f"Unsupported encryption version: {version}")

    # Decode base64
    try:
        combined = base64.b64decode(payload_b64)
    except Exception as e:
        raise ValueError(f"Failed to decode encrypted value: {e}")

    if len(combined) < NONCE_LENGTH:
        raise ValueError("Encrypted value too short")

    # Split nonce and ciphertext
    nonce = combined[:NONCE_LENGTH]
    ciphertext = combined[NONCE_LENGTH:]

    # Decrypt
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception:
        raise ValueError("Decryption failed: invalid key or corrupted data")

    return plaintext.decode("utf-8")


def decrypt_content_tags(key: bytes, content: str) -> str:
    """
    Decrypt all <encrypted v="N">...</encrypted> tags in content.
    Returns content with decrypted values (tags stripped).
    """
    if not has_encrypted_tags(content):
        return content

    def replacer(match: re.Match) -> str:
        full_tag = match.group(0)
        try:
            return decrypt_value(key, full_tag)
        except Exception as e:
            warnings.warn(f"Failed to decrypt tag: {e}")
            return full_tag  # Keep encrypted if decryption fails

    return VERSIONED_TAG_PATTERN.sub(replacer, content)


def strip_encrypted_tags(content: str) -> str:
    """
    Strip all <encrypted>...</encrypted> tags, leaving inner values.
    Use this when decryption is not available but tags should be removed.
    """
    return ANY_ENCRYPTED_TAG_PATTERN.sub(r"\1", content)


def decrypt_or_strip_content(content: str, key: bytes | None) -> tuple[str, bool]:
    """
    Decrypt content if key is available, otherwise strip tags.
    Returns (processed_content, was_decrypted).
    """
    if not has_encrypted_tags(content):
        return content, False

    if key is not None and CRYPTO_AVAILABLE:
        try:
            return decrypt_content_tags(key, content), True
        except Exception as e:
            warnings.warn(f"Decryption failed, stripping tags: {e}")

    # No key or decryption failed - strip tags but warn
    return strip_encrypted_tags(content), False


def decrypt_file(file_path: Path, key: bytes | None) -> bool:
    """
    Decrypt encrypted tags in a file in-place.
    Returns True if any decryption was performed.
    """
    if file_path.suffix.lower() not in TEXT_EXTENSIONS:
        return False

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False

    if not has_encrypted_tags(content):
        return False

    new_content, was_decrypted = decrypt_or_strip_content(content, key)
    if new_content != content:
        file_path.write_text(new_content, encoding="utf-8")

    return was_decrypted


def decrypt_directory(dir_path: Path, key: bytes | None) -> tuple[int, int]:
    """
    Recursively decrypt all encrypted tags in text files.
    Returns (decrypted_count, stripped_count).
    """
    decrypted = 0
    stripped = 0

    for file_path in dir_path.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in TEXT_EXTENSIONS:
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        if not has_encrypted_tags(content):
            continue

        new_content, was_decrypted = decrypt_or_strip_content(content, key)
        if new_content != content:
            file_path.write_text(new_content, encoding="utf-8")
            if was_decrypted:
                decrypted += 1
            else:
                stripped += 1

    return decrypted, stripped

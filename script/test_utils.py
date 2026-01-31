#!/usr/bin/env python3
"""Unit tests for sync script utilities."""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

import pytest

from utils import (
    CRYPTO_AVAILABLE,
    convert_mcp_to_codex_toml,
    decrypt_or_strip_content,
    detect_unsafe_patterns,
    escape_toml_string,
    has_encrypted_tags,
    is_encrypted,
    iter_command_files,
    iter_skill_dirs,
    load_dotenv,
    marker_contents,
    parse_frontmatter,
    parse_key,
    quote_toml_key,
    strip_encrypted_tags,
    substitute_placeholders,
    validate_skill,
    word_count,
    FrontmatterError,
)

# Import decryption only if crypto is available
if CRYPTO_AVAILABLE:
    from utils import decrypt_value, decrypt_content_tags


class TestParseFrontmatter:
    def test_basic_frontmatter(self):
        text = """---
name: test-skill
description: A test skill
---

Content here
"""
        result = parse_frontmatter(text)
        assert result["name"] == "test-skill"
        assert result["description"] == "A test skill"

    def test_quoted_values(self):
        text = """---
name: "quoted-name"
description: 'single quoted'
---
"""
        result = parse_frontmatter(text)
        assert result["name"] == "quoted-name"
        assert result["description"] == "single quoted"

    def test_missing_opening_boundary(self):
        text = """name: test
---
"""
        with pytest.raises(FrontmatterError, match="missing frontmatter opening"):
            parse_frontmatter(text)

    def test_missing_closing_boundary(self):
        text = """---
name: test
"""
        with pytest.raises(FrontmatterError, match="missing frontmatter closing"):
            parse_frontmatter(text)

    def test_multiline_literal(self):
        text = """---
name: test
description: |
  Line 1
  Line 2
---
"""
        result = parse_frontmatter(text)
        assert result["name"] == "test"
        assert "Line 1" in result["description"]
        assert "Line 2" in result["description"]

    def test_multiline_folded(self):
        text = """---
name: test
description: >
  Part 1
  Part 2
---
"""
        result = parse_frontmatter(text)
        assert result["description"] == "Part 1 Part 2"


class TestValidateSkill:
    def test_valid_skill(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: my-skill
description: A test skill for testing
---

Instructions here.
""")
        frontmatter, errors = validate_skill(skill_dir)
        assert frontmatter["name"] == "my-skill"
        assert len(errors) == 0

    def test_missing_skill_md(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        _, errors = validate_skill(skill_dir)
        assert len(errors) == 1
        assert "missing SKILL.md" in errors[0].message

    def test_missing_name(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
description: A test skill
---
""")
        _, errors = validate_skill(skill_dir)
        assert any("'name' is required" in e.message for e in errors)

    def test_name_mismatch(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: wrong-name
description: A test skill
---
""")
        _, errors = validate_skill(skill_dir)
        assert any("does not match folder" in e.message for e in errors)

    def test_missing_description(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: my-skill
---
""")
        _, errors = validate_skill(skill_dir)
        assert any("'description' is required" in e.message for e in errors)


class TestDetectUnsafePatterns:
    def test_aws_key(self):
        content = "key = AKIAIOSFODNN7EXAMPLE"
        hits = detect_unsafe_patterns(content)
        assert "AWS access key id" in hits

    def test_openai_key(self):
        content = "OPENAI_API_KEY=sk-proj-abcdefghij1234567890"
        hits = detect_unsafe_patterns(content)
        assert any("OpenAI" in h for h in hits)

    def test_github_token(self):
        content = "token: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        hits = detect_unsafe_patterns(content)
        assert "GitHub personal access token" in hits

    def test_clean_content(self):
        content = "This is safe content with no secrets."
        hits = detect_unsafe_patterns(content)
        assert len(hits) == 0


class TestSubstitutePlaceholders:
    def test_basic_substitution(self):
        content = "Hello ${NAME}!"
        env = {"NAME": "World"}
        result, unresolved = substitute_placeholders(content, env)
        assert result == "Hello World!"
        assert len(unresolved) == 0

    def test_multiple_substitutions(self):
        content = "${GREETING} ${NAME}!"
        env = {"GREETING": "Hello", "NAME": "World"}
        result, unresolved = substitute_placeholders(content, env)
        assert result == "Hello World!"

    def test_unresolved_placeholder(self):
        content = "Hello ${UNKNOWN}!"
        env = {}
        result, unresolved = substitute_placeholders(content, env)
        assert result == "Hello ${UNKNOWN}!"
        assert "UNKNOWN" in unresolved

    def test_mixed_resolved_unresolved(self):
        content = "${KNOWN} and ${UNKNOWN}"
        env = {"KNOWN": "yes"}
        result, unresolved = substitute_placeholders(content, env)
        assert result == "yes and ${UNKNOWN}"
        assert "UNKNOWN" in unresolved


class TestWordCount:
    def test_simple_sentence(self):
        assert word_count("Hello world") == 2

    def test_with_punctuation(self):
        assert word_count("Hello, world!") == 2

    def test_multiline(self):
        assert word_count("Line one\nLine two") == 4


class TestTomlHelpers:
    def test_escape_toml_string(self):
        assert escape_toml_string('hello"world') == 'hello\\"world'
        assert escape_toml_string("line\nbreak") == "line\\nbreak"
        assert escape_toml_string("back\\slash") == "back\\\\slash"

    def test_quote_toml_key_bare(self):
        assert quote_toml_key("simple-key") == "simple-key"
        assert quote_toml_key("key_123") == "key_123"

    def test_quote_toml_key_special(self):
        assert quote_toml_key("key.with.dots") == '"key.with.dots"'
        assert quote_toml_key("key with spaces") == '"key with spaces"'


class TestConvertMcpToCodexToml:
    def test_stdio_server(self):
        servers = {
            "my-server": {
                "command": "npx",
                "args": ["-y", "my-mcp-server"],
            }
        }
        result = convert_mcp_to_codex_toml(servers)
        assert "[mcp_servers.my-server]" in result
        assert 'command = "npx"' in result
        assert 'args = ["-y", "my-mcp-server"]' in result

    def test_http_server(self):
        servers = {
            "remote": {
                "type": "http",
                "url": "https://api.example.com",
            }
        }
        result = convert_mcp_to_codex_toml(servers)
        assert "[mcp_servers.remote]" in result
        assert 'url = "https://api.example.com"' in result

    def test_server_with_env(self):
        servers = {
            "with-env": {
                "command": "node",
                "args": ["server.js"],
                "env": {"API_KEY": "secret"},
            }
        }
        result = convert_mcp_to_codex_toml(servers)
        assert "[mcp_servers.with-env.env]" in result
        assert 'API_KEY = "secret"' in result


class TestMarkerContents:
    def test_marker_format(self):
        result = marker_contents("skill", "test-skill")
        assert "repo:" in result
        assert "commit:" in result
        assert "timestamp_utc:" in result
        assert "skill: test-skill" in result


class TestIterators:
    def test_iter_skill_dirs_empty(self, tmp_path, monkeypatch):
        # Patch skills_root to return tmp_path
        import utils
        monkeypatch.setattr(utils, "skills_root", lambda: tmp_path)
        result = list(iter_skill_dirs())
        assert result == []

    def test_iter_skill_dirs_with_skills(self, tmp_path, monkeypatch):
        import utils
        monkeypatch.setattr(utils, "skills_root", lambda: tmp_path)

        # Create a valid skill directory
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\n")

        # Create a non-skill directory (no SKILL.md)
        (tmp_path / "not-a-skill").mkdir()

        result = list(iter_skill_dirs())
        assert len(result) == 1
        assert result[0].name == "my-skill"

    def test_iter_command_files_empty(self, tmp_path, monkeypatch):
        import utils
        monkeypatch.setattr(utils, "commands_root", lambda: tmp_path)
        result = list(iter_command_files())
        assert result == []

    def test_iter_command_files_with_commands(self, tmp_path, monkeypatch):
        import utils

        monkeypatch.setattr(utils, "commands_root", lambda: tmp_path)

        (tmp_path / "cmd1.md").write_text("# Command 1")
        (tmp_path / "cmd2.md").write_text("# Command 2")
        (tmp_path / ".hidden.md").write_text("# Hidden")
        (tmp_path / "not-markdown.txt").write_text("Not a command")

        result = list(iter_command_files())
        assert len(result) == 2
        assert {f.name for f in result} == {"cmd1.md", "cmd2.md"}


# =============================================================================
# Encryption Tests
# =============================================================================


class TestParseKey:
    def test_parse_hex_key(self):
        # 32 bytes = 64 hex chars
        hex_key = "00" * 32
        key = parse_key(hex_key)
        assert len(key) == 32
        assert key == bytes(32)

    def test_parse_hex_key_mixed_case(self):
        hex_key = "aAbBcCdDeEfF" + "00" * 26
        key = parse_key(hex_key)
        assert len(key) == 32

    def test_parse_base64_key(self):
        # 32 bytes in base64
        raw_key = bytes(range(32))
        b64_key = base64.b64encode(raw_key).decode()
        key = parse_key(b64_key)
        assert key == raw_key

    def test_parse_key_invalid_length(self):
        with pytest.raises(ValueError, match="must be 32 bytes"):
            parse_key("abc")

    def test_parse_key_invalid_hex(self):
        # 64 chars but not valid hex
        with pytest.raises(ValueError):
            parse_key("zz" * 32)


class TestIsEncrypted:
    def test_versioned_tag(self):
        assert is_encrypted('<encrypted v="1">abc123</encrypted>')
        assert is_encrypted('  <encrypted v="1">abc123</encrypted>  ')

    def test_plaintext(self):
        assert not is_encrypted("plaintext")
        assert not is_encrypted("")

    def test_unversioned_tag(self):
        # Unversioned tags are not considered "encrypted" (storage format)
        assert not is_encrypted("<encrypted>plaintext</encrypted>")

    def test_malformed_tag(self):
        assert not is_encrypted('<encrypted v="1">no closing tag')
        assert not is_encrypted('no opening tag</encrypted>')


class TestHasEncryptedTags:
    def test_with_versioned_tag(self):
        content = 'Key: <encrypted v="1">ciphertext</encrypted>'
        assert has_encrypted_tags(content)

    def test_without_tags(self):
        content = "No encrypted content here"
        assert not has_encrypted_tags(content)

    def test_empty(self):
        assert not has_encrypted_tags("")


class TestStripEncryptedTags:
    def test_strip_versioned_tag(self):
        content = 'Key: <encrypted v="1">secret-value</encrypted>'
        result = strip_encrypted_tags(content)
        assert result == "Key: secret-value"

    def test_strip_unversioned_tag(self):
        content = "Key: <encrypted>secret-value</encrypted>"
        result = strip_encrypted_tags(content)
        assert result == "Key: secret-value"

    def test_strip_multiple_tags(self):
        content = """
API_KEY=<encrypted v="1">key1</encrypted>
SECRET=<encrypted>key2</encrypted>
"""
        result = strip_encrypted_tags(content)
        assert "key1" in result
        assert "key2" in result
        assert "<encrypted" not in result

    def test_no_tags(self):
        content = "Plain content"
        result = strip_encrypted_tags(content)
        assert result == content


class TestDecryptOrStripContent:
    def test_no_encrypted_tags(self):
        content = "Plain content without tags"
        result, was_decrypted = decrypt_or_strip_content(content, None)
        assert result == content
        assert not was_decrypted

    def test_strip_when_no_key(self):
        content = 'Key: <encrypted v="1">ciphertext</encrypted>'
        result, was_decrypted = decrypt_or_strip_content(content, None)
        assert result == "Key: ciphertext"
        assert not was_decrypted


class TestLoadDotenv:
    def test_load_simple_env(self, tmp_path, monkeypatch):
        import utils

        monkeypatch.setattr(utils, "repo_root", lambda: tmp_path)

        env_file = tmp_path / ".env"
        env_file.write_text(
            """
# Comment
KEY1=value1
KEY2="quoted value"
KEY3='single quoted'
EMPTY=
"""
        )

        result = load_dotenv()
        assert result["KEY1"] == "value1"
        assert result["KEY2"] == "quoted value"
        assert result["KEY3"] == "single quoted"
        assert result["EMPTY"] == ""

    def test_load_missing_env(self, tmp_path, monkeypatch):
        import utils

        monkeypatch.setattr(utils, "repo_root", lambda: tmp_path)
        # No .env file
        result = load_dotenv()
        assert result == {}


# Only test actual decryption if cryptography is available
@pytest.mark.skipif(not CRYPTO_AVAILABLE, reason="cryptography not installed")
class TestDecryption:
    @pytest.fixture
    def test_key(self):
        """Generate a test key (32 bytes)."""
        return bytes(range(32))

    @pytest.fixture
    def encrypt_value(self, test_key):
        """Helper to encrypt a value for testing."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        def _encrypt(plaintext: str) -> str:
            nonce = os.urandom(12)
            aesgcm = AESGCM(test_key)
            ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
            combined = nonce + ciphertext
            encoded = base64.b64encode(combined).decode()
            return f'<encrypted v="1">{encoded}</encrypted>'

        return _encrypt

    def test_decrypt_value(self, test_key, encrypt_value):
        encrypted = encrypt_value("my-secret")
        result = decrypt_value(test_key, encrypted)
        assert result == "my-secret"

    def test_decrypt_value_passthrough_plaintext(self, test_key):
        result = decrypt_value(test_key, "plaintext")
        assert result == "plaintext"

    def test_decrypt_value_wrong_key(self, encrypt_value):
        encrypted = encrypt_value("secret")
        wrong_key = bytes(reversed(range(32)))
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_value(wrong_key, encrypted)

    def test_decrypt_content_tags(self, test_key, encrypt_value):
        encrypted_key = encrypt_value("api-key-12345")
        content = f"API_KEY={encrypted_key}\nOTHER=value"

        result = decrypt_content_tags(test_key, content)
        assert "api-key-12345" in result
        assert "<encrypted" not in result

    def test_decrypt_multiple_tags(self, test_key, encrypt_value):
        enc1 = encrypt_value("secret1")
        enc2 = encrypt_value("secret2")
        content = f"KEY1={enc1}\nKEY2={enc2}"

        result = decrypt_content_tags(test_key, content)
        assert "secret1" in result
        assert "secret2" in result

    def test_decrypt_or_strip_with_key(self, test_key, encrypt_value):
        encrypted = encrypt_value("decrypted-value")
        content = f"Key: {encrypted}"

        result, was_decrypted = decrypt_or_strip_content(content, test_key)
        assert "decrypted-value" in result
        assert was_decrypted

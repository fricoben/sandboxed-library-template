# Sandboxed Library

Configuration library for
[sandboxed.sh](https://github.com/Th0rgal/sandboxed.sh) workspaces.

## Structure

- `skill/` — AI agent skills (instructions + references)
- `command/` — Slash commands
- `mcp/` — MCP server configurations
- `init-script/` — Workspace initialization scripts
- `workspace-template/` — Workspace templates

## Secrets

Workspace templates can contain encrypted secrets using the `<encrypted>` tag:

```json
{
  "env_vars": {
    "API_KEY": "<encrypted v=\"1\">base64-encrypted-data...</encrypted>"
  }
}
```

These secrets are automatically decrypted at workspace startup using the `nv`
encryption key set in your `.env` file. The decrypted values are injected as
environment variables.

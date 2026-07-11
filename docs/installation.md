# Installation

BranchForge can run in two modes:

1. **Agent-native mode**: Codex or Claude performs the reasoning and subagent work. BranchForge skills define the workflow, while MCP tools persist state, evidence, artifacts, and dossiers.
2. **Headless provider mode**: the Python search kernel calls configured model APIs directly.

Agent-native mode is recommended for normal use.

## Requirements

- Python 3.11+
- Git
- Codex, Claude Code, Claude Desktop, or another MCP-capable host

## Install For Agent Hosts

Clone the repository:

```bash
git clone https://github.com/elijahbutler/branchforge.git
cd branchforge
```

Install for both Codex and Claude:

```bash
./scripts/install-agent.sh --all --force
```

Or install for one host:

```bash
./scripts/install-agent.sh --codex --force
./scripts/install-agent.sh --claude --force
```

The installer:

1. Creates `.venv` in the checkout.
2. Installs `branchforge[mcp]`.
3. Installs the BranchForge skill suite.
4. Registers the MCP server using the absolute `.venv/bin/branchforge` path.

Restart the agent host or open a new task after installation.

## Verify Installation

Run the non-mutating doctor:

```bash
branchforge doctor --host local
branchforge doctor --host codex
branchforge doctor --host claude
branchforge doctor --host claude-desktop
```

Codex:

```bash
codex mcp get branchforge
```

Claude Code:

```bash
claude mcp get branchforge
```

Claude Desktop on macOS:

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
print(json.loads(p.read_text())["mcpServers"]["branchforge"])
PY
```

The configured command should end with:

```text
.venv/bin/branchforge mcp
```

## Claude Desktop Notes

Claude Desktop exposes different capabilities depending on where the conversation runs:

| Desktop surface | BranchForge availability |
|---|---|
| **Code tab, Local session** | `/branchforge` skill plus all MCP tools |
| **Code tab, Remote session** | Local skills/plugins and local MCP servers are unavailable |
| **Regular Chat or Cowork** | BranchForge MCP tools and its MCP prompt; Claude Code slash-skills are not supported |

After installation, completely quit Claude Desktop with `Cmd+Q` and reopen it. In the Code tab, select **Local** before starting a session.

## Manual Skill Install

If you only want the skill files:

```bash
./scripts/install-skill.sh --codex --force
./scripts/install-skill.sh --claude --force
```

The MCP server is still required for the full durable BranchForge workflow.

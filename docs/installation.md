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

The installer registers every requested host it finds and skips the rest, so `--all` works with only one of Codex and Claude installed. It can be rerun without `--force`; use `--force` only to replace a skill of the same name that came from elsewhere.

Restart the agent host or open a new task after installation.

## Let BranchForge Run Check Commands

By default BranchForge records check results that the agent reports. To have it run checks itself, list the commands you allow in a JSON file outside the project:

```json
{
  "projects": ["/Users/you/code/my-project"],
  "checks": {
    "unit": {"command": ["pytest", "-q"]},
    "types": {"command": ["mypy", "src"], "kind": "static_analysis"}
  }
}
```

Then point the MCP server at it:

```bash
claude mcp remove branchforge -s user
claude mcp add -s user branchforge -e BRANCHFORGE_CHECKS_FILE="$HOME/.config/branchforge/checks.json" -- "$PWD/.venv/bin/branchforge" mcp
```

`projects` lists the project directories where these checks may run. An agent can reference the checks by name and cannot supply or change a command, and it cannot use them in a project you did not list. BranchForge refuses a checks file inside a listed project. Commands run without a shell, with your user's permissions, in the project directory or one of its git worktrees. A test runner still executes the code the agent wrote, so allow only commands you would let the agent run.

## Install As A Claude Code Plugin

The repository is also a Claude Code plugin marketplace. The plugin starts the server with `uvx` from the plugin directory, so it needs [uv](https://docs.astral.sh/uv/) on PATH and nothing else:

```bash
claude plugin marketplace add elijahbutler/branchforge
claude plugin install branchforge@branchforge
```

The Codex plugin under `plugins/branchforge` expects a `branchforge` command on PATH.

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

The CLI lives in the checkout's `.venv`. Run it as `.venv/bin/branchforge`, or add that directory to PATH.

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

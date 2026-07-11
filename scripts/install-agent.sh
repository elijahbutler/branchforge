#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 [--codex|--claude|--all] [--force]"
}

platform="all"
force="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --codex) platform="codex" ;;
    --claude) platform="claude" ;;
    --all) platform="all" ;;
    --force) force="true" ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="$repo_root/.venv"

if [[ ! -x "$venv/bin/python" ]]; then
  python3 -m venv "$venv"
fi
"$venv/bin/python" -m pip install -e "$repo_root[mcp]"

skill_args=("--$platform")
if [[ "$force" == "true" ]]; then
  skill_args+=("--force")
fi
"$repo_root/scripts/install-skill.sh" "${skill_args[@]}"

server="$venv/bin/branchforge"

install_codex() {
  command -v codex >/dev/null || { echo "codex is not installed" >&2; return 1; }
  codex mcp remove branchforge >/dev/null 2>&1 || true
  codex mcp add branchforge -- "$server" mcp
  echo "Registered BranchForge MCP with Codex"
}

install_claude() {
  command -v claude >/dev/null || { echo "claude is not installed" >&2; return 1; }
  claude mcp remove branchforge -s user >/dev/null 2>&1 || true
  claude mcp add -s user branchforge -- "$server" mcp
  echo "Registered BranchForge MCP with Claude Code"
}

case "$platform" in
  codex) install_codex ;;
  claude) install_claude ;;
  all)
    install_codex
    install_claude
    ;;
esac

echo "Restart the agent host, then invoke BranchForge."

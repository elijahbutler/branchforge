#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 [--codex|--claude|--all] [--copy] [--force]"
}

platform="all"
mode="link"
force="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --codex) platform="codex" ;;
    --claude) platform="claude" ;;
    --all) platform="all" ;;
    --copy) mode="copy" ;;
    --force) force="true" ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="$repo_root/skills/branching-deliberation"

install_one() {
  local target_root="$1"
  local target="$target_root/branching-deliberation"
  mkdir -p "$target_root"
  if [[ -e "$target" || -L "$target" ]]; then
    if [[ "$force" != "true" ]]; then
      echo "Refusing to replace existing skill: $target" >&2
      echo "Re-run with --force if replacement is intended." >&2
      return 1
    fi
    rm -rf "$target"
  fi
  if [[ "$mode" == "copy" ]]; then
    cp -R "$source_dir" "$target"
  else
    ln -s "$source_dir" "$target"
  fi
  echo "Installed $target"
}

case "$platform" in
  codex) install_one "$HOME/.agents/skills" ;;
  claude) install_one "$HOME/.claude/skills" ;;
  all)
    install_one "$HOME/.agents/skills"
    install_one "$HOME/.claude/skills"
    ;;
esac

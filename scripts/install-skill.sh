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

install_suite() {
  local target_root="$1"
  mkdir -p "$target_root"
  local source_dir target
  for source_dir in "$repo_root"/skills/branchforge "$repo_root"/skills/branchforge-* "$repo_root"/skills/branching-deliberation; do
    [[ -d "$source_dir" ]] || continue
    target="$target_root/$(basename "$source_dir")"
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
  done
}

case "$platform" in
  codex) install_suite "$HOME/.agents/skills" ;;
  claude) install_suite "$HOME/.claude/skills" ;;
  all)
    install_suite "$HOME/.agents/skills"
    install_suite "$HOME/.claude/skills"
    ;;
esac

#!/usr/bin/env python3
"""Safely register BranchForge with Claude Desktop without replacing other servers."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def default_config() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA is not set")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    raise RuntimeError("Claude Desktop is supported on macOS and Windows")


def install(server: Path, config: Path) -> bool:
    server = server.expanduser().resolve()
    if not server.is_file():
        raise FileNotFoundError(f"BranchForge executable not found: {server}")

    if config.exists():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid Claude Desktop JSON at {config}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Claude Desktop configuration must be a JSON object: {config}")
    else:
        data = {}

    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"mcpServers must be a JSON object: {config}")
    desired = {"command": str(server), "args": ["mcp"]}
    if servers.get("branchforge") == desired:
        return False

    config.parent.mkdir(parents=True, exist_ok=True)
    if config.exists():
        shutil.copy2(config, config.with_name(f"{config.name}.branchforge.bak"))
    servers["branchforge"] = desired

    descriptor, temporary = tempfile.mkstemp(
        dir=config.parent, prefix=f".{config.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, config)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("server", type=Path)
    parser.add_argument("--config", type=Path, default=None, help="Override config path for testing")
    args = parser.parse_args()
    config = (args.config or default_config()).expanduser().resolve()
    changed = install(args.server, config)
    action = "Registered" if changed else "Already registered"
    print(f"{action} BranchForge MCP in Claude Desktop: {config}")


if __name__ == "__main__":
    main()

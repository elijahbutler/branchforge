from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any


HOSTS = {"local", "codex", "claude", "claude-desktop"}


def _check(name: str, status: str, detail: str, action: str | None = None) -> dict[str, str]:
    result = {"name": name, "status": status, "detail": detail}
    if action:
        result["action"] = action
    return result


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def run_doctor(host: str = "local", *, home: str | Path | None = None) -> dict[str, Any]:
    if host not in HOSTS:
        raise ValueError(f"host must be one of: {', '.join(sorted(HOSTS))}")

    checks: list[dict[str, str]] = []
    version = sys.version_info
    if version >= (3, 11):
        checks.append(_check(
            "python_version",
            "ok",
            f"{version.major}.{version.minor}.{version.micro}",
        ))
    else:
        checks.append(_check(
            "python_version",
            "error",
            f"{version.major}.{version.minor}.{version.micro}",
            "Install Python 3.11 or newer.",
        ))

    branchforge_available = _module_available("branchforge")
    checks.append(_check(
        "branchforge_import",
        "ok" if branchforge_available else "error",
        "branchforge package is importable" if branchforge_available else "branchforge package is not importable",
        None if branchforge_available else "Install BranchForge in this environment.",
    ))

    mcp_available = _module_available("mcp")
    checks.append(_check(
        "mcp_extra",
        "ok" if mcp_available else "warn",
        "mcp package is importable" if mcp_available else "mcp package is not installed",
        None if mcp_available else "Install the MCP extra with: pip install 'branchforge[mcp]'.",
    ))
    if mcp_available:
        try:
            from .mcp_server import build_server

            build_server()
            checks.append(_check("mcp_server", "ok", "MCP server can be constructed."))
        except Exception as exc:  # pragma: no cover - defensive diagnostic path
            checks.append(_check(
                "mcp_server",
                "error",
                f"MCP server construction failed: {exc}",
                "Reinstall BranchForge with the MCP extra and rerun doctor.",
            ))

    if host in {"codex", "claude"}:
        binary = shutil.which(host)
        checks.append(_check(
            f"{host}_cli",
            "ok" if binary else "error",
            binary or f"{host} CLI was not found on PATH",
            None if binary else f"Install {host} or choose a different host.",
        ))

    if host == "claude-desktop":
        root = Path(home) if home else Path.home()
        config = root / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if not config.exists():
            checks.append(_check(
                "claude_desktop_config",
                "error",
                f"Config file not found: {config}",
                "Run scripts/install-agent.sh --claude --force or install the Desktop connector.",
            ))
        else:
            try:
                data = json.loads(config.read_text())
                server = data.get("mcpServers", {}).get("branchforge")
                if server:
                    checks.append(_check("claude_desktop_config", "ok", "BranchForge MCP server is configured."))
                else:
                    checks.append(_check(
                        "claude_desktop_config",
                        "error",
                        "Claude Desktop config does not include a branchforge MCP server.",
                        "Run scripts/install-agent.sh --claude --force.",
                    ))
            except json.JSONDecodeError as exc:
                checks.append(_check(
                    "claude_desktop_config",
                    "error",
                    f"Claude Desktop config is not valid JSON: {exc}",
                    "Fix the JSON file, then rerun the installer.",
                ))

    return {
        "host": host,
        "ok": not any(check["status"] == "error" for check in checks),
        "checks": checks,
    }

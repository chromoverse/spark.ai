"""SecuritySandbox — command classification for shell execution."""
from __future__ import annotations

import re

ALLOWED_PREFIXES = frozenset({
    "git", "npm", "npx", "pip", "python", "node", "py",
    "dir", "ls", "cat", "type", "echo", "mkdir", "cd",
    "code", "start", "explorer", "notepad",
    "curl", "wget", "tar", "unzip",
    "docker", "docker-compose",
    "dotnet", "cargo", "go", "rustc",
    "where", "which", "whoami", "hostname",
    "tree", "find", "grep", "head", "tail",
    "powershell", "pwsh", "cmd",
    "set", "env", "printenv",
})

BLOCKED_PATTERNS = [
    re.compile(r"rm\s+(-rf|--force)\s+[/\\]", re.IGNORECASE),
    re.compile(r"del\s+/s\s+/q", re.IGNORECASE),
    re.compile(r"format\s+[a-z]:", re.IGNORECASE),
    re.compile(r"reg\s+(delete|add)", re.IGNORECASE),
    re.compile(r"net\s+user", re.IGNORECASE),
    re.compile(r"(shutdown|restart)\s", re.IGNORECASE),
    re.compile(r"taskkill\s+/f\s+/im\s+\*", re.IGNORECASE),
    re.compile(r"mkfs\.", re.IGNORECASE),
    re.compile(r"dd\s+if=", re.IGNORECASE),
]


class SecuritySandbox:
    """Classifies commands as allowed, blocked, or requires_approval."""

    def validate(self, command: str) -> tuple[bool, str]:
        """Returns (allowed, reason). reason='requires_approval' means ask user."""
        cmd = command.strip()
        if not cmd:
            return False, "Empty command"

        # Check blocked patterns first
        for pattern in BLOCKED_PATTERNS:
            if pattern.search(cmd):
                return False, f"Blocked: dangerous pattern detected"

        # Check whitelist
        first_token = cmd.split()[0].lower().rstrip(".exe")
        if first_token in ALLOWED_PREFIXES:
            return True, "whitelisted"

        return False, "requires_approval"

"""Turn `git log` output into file authorship. Git is optional."""

from __future__ import annotations

import subprocess
from pathlib import Path


def collect_authorship(root: Path, limit: int = 300) -> dict[str, dict[str, dict[str, str | int]]]:
    """Map a repo-relative path to {email: {name, email, count}}."""
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "log",
                f"-n{limit}",
                "--pretty=format:---%an|%ae",
                "--name-only",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if completed.returncode != 0:
        return {}
    return parse_git_log(completed.stdout)


def parse_git_log(text: str) -> dict[str, dict[str, dict[str, str | int]]]:
    authorship: dict[str, dict[str, dict[str, str | int]]] = {}
    name = ""
    email = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("---"):
            payload = line[3:]
            if "|" in payload:
                name, email = payload.split("|", 1)
            else:
                name, email = payload, payload
            name = name.strip() or "Unknown"
            email = email.strip().lower() or name.lower()
            continue
        if not email:
            continue
        path = line.replace("\\", "/")
        bucket = authorship.setdefault(path, {})
        current = bucket.get(email)
        if current is None:
            bucket[email] = {"name": name, "email": email, "count": 1}
        else:
            current["count"] = int(current["count"]) + 1
    return authorship

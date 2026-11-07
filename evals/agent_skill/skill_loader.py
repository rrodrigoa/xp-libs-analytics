"""Read the actual product skill and documented references; never duplicate it."""

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load_skill() -> tuple[str, str]:
    paths = [
        REPO / "skills/generic-analytics/SKILL.md",
        REPO / "skills/generic-analytics/references/query-language.md",
        REPO / "skills/generic-analytics/references/errors.md",
        REPO / "docs/query-language.md",
        REPO / "docs/string-matching.md",
        REPO / "skills/generic-analytics/references/string-matching.md",
        REPO / "docs/yaml-security.md",
        REPO / "examples/README.md",
    ]
    paths += sorted((REPO / "examples/queries").glob("*.yaml"))
    blocks = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError("Empty skill reference")
        blocks.append(f"\n--- {path.relative_to(REPO).as_posix()} ---\n{text}")
    content = "".join(blocks)
    return content, hashlib.sha256(content.encode()).hexdigest()

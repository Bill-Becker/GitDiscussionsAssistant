"""Loads editable AI guidance (guidance/system.md) and skills (guidance/skills/*.md) for the worker.

Skill file format (Markdown with a simple front-matter block):

    ---
    name: Troubleshooting errors
    keywords: error, fail, exception, "stack trace"
    always: false
    ---
    Instructions for the model when this skill applies...

A skill is included when any keyword appears in the discussion title or body (case-insensitive,
whole-word/phrase match) or when `always: true`. Files starting with "_" are ignored (templates).
Files are re-read for every job, so edits take effect without restarting the worker.

Preview what the model would receive:
    docker compose exec worker python guidance.py "Title" "Body text"
"""
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("guidance")

GUIDANCE_DIR = Path(os.getenv("GUIDANCE_DIR", Path(__file__).parent / "guidance"))
MAX_SKILLS = int(os.getenv("GUIDANCE_MAX_SKILLS", "3"))

DEFAULT_SYSTEM = (
    "You help the REopt team draft concise, polite replies to GitHub Discussions. "
    "Provide: 1) a 1-2 sentence summary, 2) a suggested 2-3 sentence public reply, "
    "3) 2-4 recommended next actions for the REopt team. Respond in plain text."
)


@dataclass
class Skill:
    name: str
    instructions: str
    keywords: List[str] = field(default_factory=list)
    always: bool = False
    source: str = ""

    def score(self, text: str) -> int:
        """Number of distinct keywords found in text (whole word/phrase, case-insensitive)."""
        return sum(
            1 for k in self.keywords
            if re.search(r"(?<!\w)" + re.escape(k.lower()) + r"(?!\w)", text)
        )


def _read(path: Path) -> str:
    """Read a guidance file, dropping <!-- author notes --> so they are not sent to the model."""
    return re.sub(r"<!--.*?-->\s*", "", path.read_text(encoding="utf-8"), flags=re.S)


def _parse(path: Path) -> Skill:
    raw = _read(path)
    meta, body = {}, raw
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
    keywords = [k.strip().strip("\"'") for k in meta.get("keywords", "").split(",") if k.strip()]
    return Skill(
        name=meta.get("name") or path.stem,
        instructions=body.strip(),
        keywords=keywords,
        always=meta.get("always", "").lower() in ("true", "yes", "1"),
        source=path.name,
    )


def load_skills(directory: Optional[Path] = None) -> List[Skill]:
    d = (directory or GUIDANCE_DIR) / "skills"
    skills = []
    for path in sorted(d.glob("*.md")) if d.is_dir() else []:
        if path.name.startswith("_"):
            continue
        try:
            skills.append(_parse(path))
        except Exception:
            log.exception("Could not load skill %s", path)
    return skills


def select_skills(title: str, body: str, skills: List[Skill], limit: int = MAX_SKILLS) -> List[Skill]:
    """Always-on skills, plus the best keyword matches (up to `limit`)."""
    text = f"{title}\n{body}".lower()
    always = [s for s in skills if s.always]
    scored = sorted(
        ((s.score(text), s) for s in skills if not s.always),
        key=lambda pair: -pair[0],
    )
    return always + [s for score, s in scored if score > 0][:limit]


def load_system(directory: Optional[Path] = None) -> str:
    path = (directory or GUIDANCE_DIR) / "system.md"
    try:
        return _read(path).strip()
    except FileNotFoundError:
        log.warning("%s not found; using built-in default guidance", path)
        return DEFAULT_SYSTEM


def build_system_prompt(title: str, body: str, directory: Optional[Path] = None):
    """Return (system_prompt, applied_skill_names)."""
    chosen = select_skills(title, body, load_skills(directory))
    parts = [load_system(directory)]
    for s in chosen:
        parts.append(f"## Skill: {s.name}\n\n{s.instructions}")
    return "\n\n".join(parts), [s.name for s in chosen]


if __name__ == "__main__":
    t = sys.argv[1] if len(sys.argv) > 1 else ""
    b = sys.argv[2] if len(sys.argv) > 2 else ""
    prompt, names = build_system_prompt(t, b)
    print(f"Skills applied: {', '.join(names) or 'none'}\n{'=' * 60}\n{prompt}")

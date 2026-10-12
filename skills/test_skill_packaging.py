"""Every skill directory is uploadable as a custom skill (docs/managed-agents-notes.md 2c): SKILL.md
at its root with valid frontmatter, the folder named after the skill, no caches or other junk,
and within the size limits. This file sits in skills/, outside every skill directory, so it is
never uploaded.

Run: cd backend && uv run pytest ../skills -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).resolve().parent
SKILLS = ("booking-links", "travel-research-rules", "trip-tracker-schema")
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# What `ant` skips when it uploads a skill directory (notes 2c, "Rules and limits").
ANT_SKIPPED_DIRS = {"__pycache__", ".venv", "node_modules", "dist", "build"}
UPLOADED_SUFFIXES = {".md", ".py", ".json"}
TEST_FILE = re.compile(r"^(test_.*|conftest)\.py$")


def frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{path} must start with YAML frontmatter between --- lines"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict)
    return data


def uploaded_files(skill_dir: Path) -> list[Path]:
    """The files an upload would carry: everything except what `ant` skips (dotfiles, caches,
    symlinks) and the tests, which a bootstrap upload should leave out too."""
    files: list[Path] = []
    for path in sorted(skill_dir.rglob("*")):
        relative = path.relative_to(skill_dir)
        if any(part.startswith(".") or part in ANT_SKIPPED_DIRS for part in relative.parts):
            continue
        if path.is_symlink() or not path.is_file() or TEST_FILE.match(path.name):
            continue
        files.append(path)
    return files


def test_the_three_skills_exist() -> None:
    present = sorted(p.name for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file())
    assert present == sorted(SKILLS)


@pytest.mark.parametrize("skill", SKILLS)
def test_frontmatter(skill: str) -> None:
    data = frontmatter(SKILLS_DIR / skill / "SKILL.md")
    assert set(data) == {"name", "description"}
    name, description = data["name"], data["description"]
    assert name == skill  # the upload folder must match the name
    assert isinstance(name, str)
    assert NAME.match(name)
    assert len(name) <= 64
    assert "anthropic" not in name
    assert "claude" not in name
    assert isinstance(description, str)
    assert 0 < len(description) <= 1024
    assert "<" not in description  # no XML tags
    assert ">" not in description


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_directory_is_clean_and_small(skill: str) -> None:
    skill_dir = SKILLS_DIR / skill
    junk = [
        str(path.relative_to(skill_dir))
        for path in skill_dir.rglob("*")
        if path.name in {"__pycache__", ".pytest_cache", ".DS_Store"} or path.suffix == ".pyc"
    ]
    assert junk == [], f"caches inside {skill}/ would be uploaded by files_from_dir: {junk}"
    files = uploaded_files(skill_dir)
    assert files
    assert {path.suffix for path in files} <= UPLOADED_SUFFIXES
    total = sum(path.stat().st_size for path in files)
    assert total < 1_000_000  # far below the 30 MB limit: skills are read into the context


SUPPORT_FILES = {
    "booking-links": ("build_link.py", "templates.json"),
    "travel-research-rules": ("write_result.py", "geocode.py"),
    "trip-tracker-schema": ("example.json",),
}


CORE_MAX_CHARS = 6_500
"""A SKILL.md is read whole by every agent that uses the skill and re-read by every later model
request (about 4 characters per token): the core stays under roughly 1,600 tokens, and the
detail lives in references/ files read on demand (docs/managed-agents-notes.md, "Cost levers")."""


def reference_files(skill_dir: Path) -> list[Path]:
    return sorted((skill_dir / "references").glob("*.md"))


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_md_names_only_files_that_exist(skill: str) -> None:
    skill_dir = SKILLS_DIR / skill
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    # A support file is named by the core or by one of its references.
    named_in = text + "".join(p.read_text(encoding="utf-8") for p in reference_files(skill_dir))
    for name in SUPPORT_FILES[skill]:
        assert (skill_dir / name).is_file(), name
        assert f"`{name}`" in named_in or f"<skill_dir>/{name}" in named_in, name
    for name in re.findall(r"<skill_dir>/([\w./<>-]+)", text):
        if "<" in name:  # <skill_dir>/schemas/<agent>.json: a family of generated files
            assert (skill_dir / name.split("<")[0]).is_dir(), name
            continue
        assert (skill_dir / name).is_file(), name


@pytest.mark.parametrize("skill", SKILLS)
def test_core_is_short_and_points_at_every_reference(skill: str) -> None:
    skill_dir = SKILLS_DIR / skill
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert len(text) <= CORE_MAX_CHARS, f"{skill}/SKILL.md has {len(text)} characters"
    references = reference_files(skill_dir)
    assert references, f"{skill} has no references/: the detail belongs there"
    for path in references:
        assert f"<skill_dir>/references/{path.name}" in text, (
            f"{skill}/SKILL.md must say when to read references/{path.name}"
        )
    for name in re.findall(r"<skill_dir>/references/([\w.-]+)", text):
        assert (skill_dir / "references" / name).is_file(), name

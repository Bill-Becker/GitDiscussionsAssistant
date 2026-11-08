from pathlib import Path

import guidance


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_dir(tmp_path: Path) -> Path:
    write(tmp_path / "system.md", "BASE <!-- note for authors -->guidance")
    write(tmp_path / "skills" / "errors.md",
          "---\nname: Errors\nkeywords: error, \"stack trace\"\n---\n<!-- hidden -->Ask for the trace.")
    write(tmp_path / "skills" / "battery.md",
          "---\nname: Battery\nkeywords: battery, storage\n---\nBattery tips.")
    write(tmp_path / "skills" / "always.md", "---\nname: Always\nalways: true\n---\nAlways on.")
    write(tmp_path / "skills" / "_template.md", "---\nname: Template\nalways: true\n---\nIgnored.")
    return tmp_path


def test_keyword_selection_and_always(tmp_path):
    prompt, names = guidance.build_system_prompt("Battery storage sizing", "", make_dir(tmp_path))
    assert names == ["Always", "Battery"]
    assert prompt.startswith("BASE guidance")
    assert "Battery tips." in prompt and "Template" not in prompt


def test_whole_word_and_phrase_match(tmp_path):
    d = make_dir(tmp_path)
    _, names = guidance.build_system_prompt("", "terror", d)  # "error" inside a word: no match
    assert "Errors" not in names
    prompt, names = guidance.build_system_prompt("", "Here is my Stack Trace", d)
    assert "Errors" in names
    assert "hidden" not in prompt and "note for authors" not in prompt


def test_best_matches_first_and_limit(tmp_path):
    skills = guidance.load_skills(make_dir(tmp_path))
    chosen = guidance.select_skills("battery storage error", "", skills, limit=1)
    assert [s.name for s in chosen] == ["Always", "Battery"]  # battery scores 2, errors 1


def test_missing_dir_uses_default(tmp_path):
    prompt, names = guidance.build_system_prompt("x", "y", tmp_path / "missing")
    assert prompt == guidance.DEFAULT_SYSTEM and names == []


def test_shipped_guidance_loads():
    prompt, names = guidance.build_system_prompt("Run failed", "I get an error", None)
    assert "Troubleshooting errors" in names
    assert "SUGGESTED REPLY" in prompt

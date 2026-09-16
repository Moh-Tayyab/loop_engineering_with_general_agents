"""Config-invariant tests for the maker-checker loop (Concept 11).

These tests assert the loop guardrails hold in the config files so the split is
enforced by code, not just by intention:

- the checker is a read-only subagent: cannot edit, cannot run bash, cannot spawn
  subagents, and uses a different model than the maker;
- the maker may spawn subagents (task allowed) but is bounded by a steps limit;
- subagent nesting is capped globally (subagent_depth=1) and the task permission
  defaults to deny for every agent that does not explicitly allow it.

The frontmatter parser below handles the indentation shape used in this repo
(top-level scalars and nested maps such as `permission:` and `permission.task:`).
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / ".opencode" / "opencode.json"
AGENT_DIR = REPO / ".opencode" / "agent"


def _scalar(raw: str):
    raw = raw.strip().strip('"').strip("'")
    if raw in ("true", "false"):
        return raw == "true"
    if raw.isdigit():
        return int(raw)
    if raw.startswith("[") and raw.endswith("]"):
        return [i.strip().strip('"').strip("'") for i in raw[1:-1].split(",") if i.strip()]
    return raw


def _strip_jsonc_comments(text: str) -> str:
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _load_jsonc(path: Path) -> dict:
    return json.loads(_strip_jsonc_comments(path.read_text()))


def _parse_frontmatter(path: Path) -> dict:
    text = path.read_text()
    fm = text.split("---", 2)[1]
    root = {}
    stack = []

    def parent(depth):
        while stack and stack[-1][0] >= depth:
            stack.pop()
        return stack[-1][1] if stack else root

    for line in fm.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        key, _, val = line.strip().partition(":")
        key = key.strip().strip('"').strip("'")
        val = val.strip()
        container = parent(indent)
        if val:
            container[key] = _scalar(val)
        else:
            child = {}
            container[key] = child
            stack.append((indent, child))
    return root


def test_checker_is_read_only_subagent():
    checker = _parse_frontmatter(AGENT_DIR / "checker.md")
    assert checker["mode"] == "subagent"
    assert checker["steps"] == 30
    assert checker["permission"]["edit"] == "deny"
    assert checker["permission"]["bash"] == "deny"
    assert checker["permission"]["task"] == "deny"
    assert checker["permission"]["webfetch"] == "deny"
    assert checker["permission"]["websearch"] == "deny"


def test_checker_has_no_bash_escape_hatch():
    checker = _parse_frontmatter(AGENT_DIR / "checker.md")
    assert checker["permission"]["bash"] == "deny"


def test_checker_never_self_approves_or_edits():
    checker = _parse_frontmatter(AGENT_DIR / "checker.md")
    text = (AGENT_DIR / "checker.md").read_text().lower()
    assert checker["permission"]["edit"] == "deny"
    assert "you do not make changes" in text
    assert "rubber-stamp" in text


def test_maker_may_spawn_only_checker_and_is_bounded():
    maker = _parse_frontmatter(AGENT_DIR / "maker.md")
    assert maker["mode"] == "all"
    assert maker["steps"] == 60
    assert maker["permission"]["edit"] == "allow"
    assert maker["permission"]["bash"] == "allow"
    task = maker["permission"]["task"]
    assert task == {"*": "deny", "checker": "allow"}


def test_maker_and_checker_use_distinct_models():
    checker = _parse_frontmatter(AGENT_DIR / "checker.md")
    maker = _parse_frontmatter(AGENT_DIR / "maker.md")
    assert checker["model"] != maker["model"]


def test_global_nesting_guard_and_default_deny():
    cfg = _load_jsonc(CONFIG)
    assert cfg["subagent_depth"] == 1
    assert cfg["permission"]["task"] == "deny"
    assert cfg["agent"]["build"]["permission"]["task"] == "allow"


def test_only_build_and_maker_may_spawn():
    cfg = _load_jsonc(CONFIG)
    config_spawnable = {name for name, a in cfg.get("agent", {}).items()
                        if (a.get("permission", {}).get("task") == "allow")}
    assert config_spawnable == {"build"}
    file_spawnable = []
    for f in sorted(AGENT_DIR.glob("*.md")):
        fm = _parse_frontmatter(f)
        t = fm.get("permission", {}).get("task")
        if t == "allow" or (isinstance(t, dict) and "allow" in t.values()):
            file_spawnable.append(f.stem)
    assert file_spawnable == ["maker"]


def test_spawn_allow_tied_to_real_agents():
    maker = _parse_frontmatter(AGENT_DIR / "maker.md")
    assert maker["permission"]["task"]["checker"] == "allow"


def test_checker_prompt_declares_verdict_contract():
    text = (AGENT_DIR / "checker.md").read_text()
    assert "APPROVED" in text
    assert "CHANGES REQUESTED" in text


def test_maker_prompt_forbids_self_approval():
    text = (AGENT_DIR / "maker.md").read_text().lower()
    assert "never" in text and "own work" in text


def test_both_agents_exist_and_are_not_the_same_file():
    assert (AGENT_DIR / "maker.md").is_file()
    assert (AGENT_DIR / "checker.md").is_file()


def test_verify_loop_state_skill_is_valid():
    skill_dir = REPO / ".opencode" / "skills" / "verify-loop-state"
    skill = skill_dir / "SKILL.md"
    assert skill.is_file()
    fm = _parse_frontmatter(skill)
    assert fm["name"] == skill_dir.name
    assert fm["description"]
    assert set(fm["allowed-tools"]) >= {"read", "grep", "edit"}


def test_every_skill_frontmatter_is_wellformed():
    skills = REPO / ".opencode" / "skills"
    assert skills.is_dir()
    for d in sorted(p for p in skills.iterdir() if p.is_dir()):
        skill = d / "SKILL.md"
        assert skill.is_file(), f"missing {skill}"
        fm = _parse_frontmatter(skill)
        assert fm.get("name") == d.name, f"{d.name}: name mismatch"
        assert fm.get("description"), f"{d.name}: missing description"


def test_spine_sections_in_rules_file():
    loops = [REPO / "video_generation_loop" / "AGENTS.md",
             REPO / "job_fetching_loop" / "AGENTS.md"]
    for rules in loops:
        text = rules.read_text()
        assert "Spine — State Between Runs" in text
        assert "Lessons Learned" in text
        assert text.index("Spine — State Between Runs") < text.index("Lessons Learned")


def test_no_root_rules_files():
    assert not (REPO / "STATE.md").exists()
    assert not (REPO / "AGENTS.md").exists()


def test_verify_skill_has_improvement_hook():
    skill = (REPO / ".opencode" / "skills" / "verify-loop-state" / "SKILL.md").read_text()
    assert "Improvement hook" in skill
    assert "Do NOT edit `AGENTS.md` yourself" in skill

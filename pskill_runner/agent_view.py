"""The agent screens of the viewer: the agents list, one agent's text and users, and saving its text.

A pskill agent is one Markdown file `.pskill/agents/<name>.md` (SPEC.md section 6.3). The viewer only
changes an agent file that exists, so a name can never point outside the agents folder.
"""

from pathlib import Path
from typing import Any

from pskill_runner.project import Project
from pskill_runner.skill_editor import write_text_atomic
from pskill_runner.skill_loader import load_catalog
from pskill_runner.skill_model import ParallelBlock, SkillCatalog
from pskill_runner.validator import agent_names_used

AGENT_FILE_SUFFIX = ".md"


class AgentEditError(Exception):
    """A change to an agent file that the viewer refuses. `problems` has the same shape as EditError's."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def agent_names(project: Project) -> list[str]:
    """Every agent of the project, in name order."""
    if not project.agents_folder.is_dir():
        return []
    return sorted(path.stem for path in project.agents_folder.glob(f"*{AGENT_FILE_SUFFIX}") if path.is_file())


def agents_overview(project: Project) -> dict[str, Any]:
    """One row per agent: its name, its first line, and the skills that use it."""
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    rows = []
    for name in agent_names(project):
        text = agent_file(project, name).read_text(encoding="utf-8")
        used_by = [user["skill"] for user in agent_users(catalog, name)]
        rows.append({"name": name, "summary": first_line(text), "used_by": used_by})
    return {"agents": rows}


def agent_detail(project: Project, name: str) -> dict[str, Any] | None:
    """Everything the agent screen shows, or None when no agent has this name."""
    if name not in agent_names(project):
        return None
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    return {
        "name": name,
        "file": f".pskill/agents/{name}{AGENT_FILE_SUFFIX}",
        "text": agent_file(project, name).read_text(encoding="utf-8"),
        "used_by": agent_users(catalog, name),
    }


def save_agent(project: Project, name: str, text: str) -> None:
    """Replace the text of an existing agent file. A CRLF file stays CRLF."""
    if name not in agent_names(project):
        raise AgentEditError([f"There is no agent {name!r} in .pskill/agents/."])
    write_text_atomic(agent_file(project, name), text)


def agent_file(project: Project, name: str) -> Path:
    return project.agents_folder / f"{name}{AGENT_FILE_SUFFIX}"


def agent_users(catalog: SkillCatalog, name: str) -> list[dict[str, Any]]:
    """The skills, and their parallel blocks, that name this agent in a way that `pskill validate` can see.

    An agent name computed from run data (a list that a script returns) is known only during a run.
    """
    users = []
    for skill_id, skill in sorted(catalog.skills.items()):
        blocks = [
            block.id
            for block in skill.blocks.values()
            if isinstance(block, ParallelBlock) and name in agent_names_used(block)
        ]
        if blocks:
            users.append({"skill": skill_id, "blocks": blocks})
    return users


def first_line(text: str) -> str:
    """The first line with text, without a Markdown heading mark."""
    for line in text.splitlines():
        if line.strip():
            return line.strip().lstrip("#").strip()
    return ""

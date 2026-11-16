"""The logic of the harness hooks (SPEC.md section 9.2), independent of any harness format.

- Stop: while a run of this session has an open block, keep the agent working, at most
  `stop_hook_max_blocks` times in a row. Then pause the run and allow the stop, so a stuck agent never
  loops forever. When that pause has `on_pause` steps, the hook blocks that stop once more, with the
  pause packet. Another session in the same checkout stops freely. A worktree run (SPEC.md 7.8) holds the
  session that owns it from the checkout too, though its record lives in its worktree. While a `pskill wait`
  runs, and the harness wakes the agent after a background command (Claude Code), allow the stop with no
  message and no count.
- Session start: refresh stale skill stubs. It lists no runs: a run of another live session would invite
  the new session to take it over. `pskill runs --open` lists them.
- Git block (Claude Code only): refuse a git command that changes the repository when a `pskill-read`
  subagent runs it. Best effort: it reads the command text only.
"""

import re
import shlex

from pskill_runner.adapters import adapter_for
from pskill_runner.engine import list_runs, register_stop_attempt, unshown_pause_packet
from pskill_runner.packets import key_option
from pskill_runner.project import Project
from pskill_runner.run_records import RunInfo
from pskill_runner.run_store import utc_now
from pskill_runner.run_waits import is_waiting
from pskill_runner.skill_loader import load_catalog
from pskill_runner.stubs import RUNNER, StubError, sync_stubs
from pskill_runner.worktrees import worktree_projects


def stop_hook_reason(project: Project, harness: str, session_id: str | None = None) -> str | None:
    """Why the agent must not stop yet, or None to allow the stop.

    A run holds only the session that owns it. A run with no owner, or a hook with no session id, holds
    every session of the harness, as before 0.9.0.
    """
    held = held_runs(project, harness, session_id)
    if not held:
        return None
    run_project, info = held[0]
    run_id = info["run_id"]
    # Only a harness that wakes the agent after a background command gets the wait: elsewhere nothing would
    # wake the agent, so the run would stay active and idle instead of pausing.
    can_wait = adapter_for(harness).wakes_after_background_command
    if can_wait and is_waiting(info, utc_now()):
        return None
    if not register_stop_attempt(run_project, run_id):
        return give_up_reason(run_project, run_id)
    folder = (
        ""
        if run_project is project
        else f"It works in the folder `{run_project.root.as_posix()}`: run these commands from that folder. "
    )
    run = f"{run_id}{key_option(info.get('key'))}"
    reason = (
        f"pskill run {run_id} has an open block. {folder}Continue it: run `{RUNNER} current {run}` and follow "
        f"the packet. If the user asked to stop, run `{RUNNER} pause {run}` instead."
    )
    if not can_wait:
        return reason
    return (
        f"{reason}\n"
        f'If you wait on background work, run `{RUNNER} wait {run_id} --reason "<what you wait on>"` in the '
        "background, then end your turn."
    )


def held_runs(project: Project, harness: str, session_id: str | None) -> list[tuple[Project, RunInfo]]:
    """The active runs of the harness that hold the session, each with the project that holds it, newest first.

    A run in a worktree of this checkout holds only the session that owns it: an unowned run there belongs to
    no session of the checkout, and other sessions share it.
    """
    runs = [(project, info) for info in list_runs(project) if holds_session(info, session_id)]
    for tree_project in worktree_projects(project):
        runs += [
            (tree_project, info)
            for info in list_runs(tree_project)
            if session_id is not None and info.get("session_id") == session_id
        ]
    active = [(owner, info) for owner, info in runs if info["harness"] == harness and info["status"] == "active"]
    return sorted(active, key=lambda pair: pair[1]["updated_at"], reverse=True)


def give_up_reason(project: Project, run_id: str) -> str | None:
    """The stop that paused the run passes, unless the pause has steps: then it is blocked once more, with them.

    The run is paused now, so the next stop passes and nothing loops. This also covers a run whose waits used up
    `max_wait_minutes`: its stops count again, and the same pause follows.
    """
    packet = unshown_pause_packet(project, run_id)
    if packet is None:
        return None
    return (
        f"pskill run {run_id} is paused: the agent ended its turn with an open block, several times. Do its pause "
        f"steps now, then end your turn.\n\n{packet}"
    )


def holds_session(info: RunInfo, session_id: str | None) -> bool:
    owner = info.get("session_id")
    return session_id is None or owner is None or owner == session_id


def session_start_text(project: Project) -> str:
    """The context for a new session. An empty text means that nothing needs attention."""
    lines = stub_refresh_lines(project)
    return "\n".join(lines) + "\n" if lines else ""


def stub_refresh_lines(project: Project) -> list[str]:
    catalog = load_catalog(project.skills_folder, project.agents_folder)
    skill_folders = [folder for folder in sorted(project.skills_folder.glob("*")) if (folder / "skill.yaml").is_file()]
    broken = [folder.name for folder in skill_folders if folder.name not in catalog.skills]
    lines = [
        f"pskill: the skill {name!r} does not load, so its stub was not refreshed. Run `{RUNNER} validate {name}`."
        for name in broken
    ]
    try:
        changes = sync_stubs(project, catalog, check_only=False, protected_names=set(broken))
    except StubError as error:
        return [*lines, f"pskill: {error}"]
    if changes:
        names = ", ".join(sorted({change.skill for change in changes}))
        lines.append(f"pskill: updated {len(changes)} stubs ({names}).")
    return lines


READ_AGENT_TYPE = "pskill-read"
BLOCKED_GIT_SUBCOMMANDS = frozenset(
    {"commit", "push", "checkout", "switch", "reset", "branch", "merge", "rebase", "tag"}
)
# The git options before the subcommand that take the next word as their value.
GIT_OPTIONS_WITH_VALUE = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--attr-source"}
)
# The characters of the tokens that end one shell command and start another (newline and backtick too).
SEPARATOR_CHARACTERS = frozenset(";&|()\n`")
# The words that can stand before a command in a compound command: `git` after them is still a git call.
LEADING_RESERVED_WORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "{", "!", "time"})
# What follows `<<` that opens a heredoc: an optional `-`, then its delimiter word (parts may be quoted).
HEREDOC_START = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*((?:'[^']*'|\"[^\"]*\"|\\.|[^\s;&|()<>'\"\\])+)")
GIT_BLOCK_REASON = (
    "A read-only task must not change the repository: `git {subcommand}` is refused. "
    "Do not retry it. Submit your answer if you have it, then end your turn."
)


def git_block_reason(hook_input: dict[str, object]) -> str | None:
    """Why this Bash call is refused, or None to allow it.

    Only a call inside a `pskill-read` subagent can be refused: the main agent has no `agent_id`. An input
    that has an unknown shape, or a command that cannot be split into words, is allowed.
    """
    if not hook_input.get("agent_id") or hook_input.get("agent_type") != READ_AGENT_TYPE:
        return None
    tool_input = hook_input.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return None
    for subcommand in git_subcommands(command):
        if subcommand in BLOCKED_GIT_SUBCOMMANDS:
            return GIT_BLOCK_REASON.format(subcommand=subcommand)
    return None


def git_subcommands(command: str) -> list[str]:
    """The git subcommand of each `git` call in a shell command line, in order."""
    try:
        words = split_shell_words(remove_inert_text(command))
    except ValueError:  # an unclosed quote
        return []
    return [sub for sub in (git_subcommand(call) for call in split_calls(words)) if sub is not None]


def remove_inert_text(command: str) -> str:
    """The command without the text that bash never runs as a command, written so that shlex reads it as bash does.

    It drops the heredoc bodies, the comments (from an unquoted `#` at a word start to the end of its line),
    and each backslash-newline outside single quotes, as bash does. Quotes may span lines. A `$'...'` string
    keeps its escaped quotes out of the text, and a `$(...)` inside double quotes is cut out of them: its text
    is checked as a command of its own, after the rest. A heredoc never starts inside `((...))` arithmetic,
    where `<<` is a shift, nor with a delimiter of only digits.
    """
    kept: list[str] = []
    quote = ""
    heredocs: list[tuple[str, bool]] = []  # the pending (delimiter, tabs stripped) of the current line
    substitutions: list[str] = []
    arithmetic_depth = 0
    position = 0
    while position < len(command):
        char = command[position]
        if char == "\\" and quote != "'":
            pair = command[position : position + 2]
            if pair == "\\'" and quote == "$'":
                kept.append("_")
            elif pair[1:] != "\n":
                kept.append(pair)
            position += 2
            continue
        position += 1
        if quote:
            if char == quote[-1]:
                quote = ""
            elif quote == '"' and char == "(" and kept[-1:] == ["$"]:
                end = end_of_substitution(command, position)
                kept[-1] = "_"
                substitutions.append(command[position : end - 1])
                position = end
                continue
        elif char in "'\"":
            quote = "$'" if char == "'" and kept[-1:] == ["$"] else char
        elif char == "#" and is_word_start(kept):
            line_end = command.find("\n", position)
            position = len(command) if line_end == -1 else line_end
            continue
        elif char == "(":
            if arithmetic_depth:
                arithmetic_depth += 1
            elif kept[-1:] == ["("]:
                arithmetic_depth = 2
        elif char == ")" and arithmetic_depth:
            arithmetic_depth -= 1
        elif char == "<" and not arithmetic_depth:
            match = HEREDOC_START.match(command, position - 1)
            if match and not match.group(2).isdigit():
                heredocs.append((split_shell_words(match.group(2))[0], match.group(1) == "-"))
                kept.append(match.group(0))
                position = match.end()
                continue
        elif char == "\n" and heredocs:
            position = end_of_heredoc_bodies(command, position, heredocs)
            heredocs = []
        kept.append(char)
    kept.extend("\n" + remove_inert_text(inner) for inner in substitutions)
    return "".join(kept)


def end_of_substitution(command: str, position: int) -> int:
    """The position after the `)` that closes a `$(` whose text starts at `position`. Quotes inside nest."""
    depth = 1
    while position < len(command):
        char = command[position]
        if char == "\\":
            position += 2
            continue
        position += 1
        if char in "'\"":
            position = end_of_quote(command, position, char)
        elif char == "$" and command[position : position + 1] == "'":
            position = end_of_quote(command, position + 1, "$'")
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return position
    return position


def end_of_quote(command: str, position: int, quote: str) -> int:
    """The position after the quote that closes the one (`'`, `$'`, or `"`) opened just before `position`."""
    while position < len(command):
        char = command[position]
        if char == "\\" and quote != "'":
            position += 2
            continue
        position += 1
        if char == quote[-1]:
            return position
        if quote == '"' and char == "$" and command[position : position + 1] == "(":
            position = end_of_substitution(command, position + 1)
    return position


def is_word_start(kept: list[str]) -> bool:
    return not kept or kept[-1] in " \t\r" or kept[-1] in SEPARATOR_CHARACTERS


def end_of_heredoc_bodies(command: str, position: int, heredocs: list[tuple[str, bool]]) -> int:
    """The position after the bodies that start at `position`, each one up to the line that is its delimiter."""
    lines = command[position:].split("\n")
    used = 0
    for delimiter, tabs_stripped in heredocs:
        while used < len(lines):
            line = lines[used].lstrip("\t") if tabs_stripped else lines[used]
            used += 1
            if line == delimiter:
                break
    return position + sum(len(line) + 1 for line in lines[:used])


def split_shell_words(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n`")
    lexer.commenters = ""  # bash starts a comment only at a word start, and its words are plain words here
    lexer.whitespace = " \t\r"  # no newline: it is a separator, and a quoted one stays inside its word
    lexer.whitespace_split = True
    return list(lexer)


def split_calls(words: list[str]) -> list[list[str]]:
    """Cut the words at the shell separators: any token made only of separator characters, such as `&&\\n`."""
    calls: list[list[str]] = [[]]
    for word in words:
        if set(word) <= SEPARATOR_CHARACTERS:
            calls.append([])
        else:
            calls[-1].append(word)
    return calls


def git_subcommand(call: list[str]) -> str | None:
    """The subcommand of one call that starts with `git`, after its options. None for another program."""
    start = 0
    while start < len(call) and call[start] in LEADING_RESERVED_WORDS:
        start += 1
    if start == len(call) or call[start] != "git":
        return None
    position = start + 1
    while position < len(call) and call[position].startswith("-"):
        position += 2 if call[position] in GIT_OPTIONS_WITH_VALUE else 1
    return call[position] if position < len(call) else None

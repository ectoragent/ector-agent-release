#!/usr/bin/env python3
"""
Memory Tool Module - Persistent Curated Memory

Provides bounded, file-backed memory that persists across sessions. Two stores:
  - MEMORY.md: agent's personal notes and observations (environment facts, project
    conventions, tool quirks, things learned)
  - USER.md: what the agent knows about the user (preferences, communication style,
    expectations, workflow habits)

Both are injected into the system prompt as a frozen snapshot at session start.
Mid-session writes update files on disk immediately (durable) but do NOT change
the system prompt -- this preserves the prefix cache for the entire session.
The snapshot refreshes on the next session start.

Entry delimiter: § (section sign). Entries can be multiline.
Character limits (not tokens) because char counts are model-independent.

Design:
- Single `memory` tool with action parameter: add, replace, remove, read
- replace/remove use short unique substring matching (not full text or IDs)
- Behavioral guidance lives in the tool schema description
- Frozen snapshot pattern: system prompt is stable, tool responses show live state
"""

import json
import logging
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from ector_constants import get_ector_home
from typing import Dict, Any, List, Optional, Tuple
from openai import AsyncOpenAI

# fcntl is Unix-only; on Windows use msvcrt for file locking
msvcrt = None
try:
    import fcntl
except ImportError:
    fcntl = None
    try:
        import msvcrt
    except ImportError:
        pass

logger = logging.getLogger(__name__)

# Where memory files live — resolved dynamically so profile overrides
# (ECTOR_HOME env var changes) are always respected.  The old module-level
# constant was cached at import time and could go stale if a profile switch
# happened after the first import.
def get_memory_dir() -> Path:
    """Return the profile-scoped memories directory."""
    return get_ector_home() / "memories"

ENTRY_DELIMITER = "\n§\n"
SESSION_DELTA_MAX_CHARS = 2000

# Entries that tell the agent to load a skill by name (skill_view / "Skill `…`").
# When that skill is deleted, these entries keep steering the model toward a
# 404 — scrub them from MEMORY.md / USER.md on delete and on session load.
_SKILL_VIEW_NAME_RE = re.compile(
    r"""skill_view\s*\(\s*name\s*=\s*['\"]([^'\"]+)['\"]""",
    re.IGNORECASE,
)
_SKILL_LABEL_RE = re.compile(
    r"""(?:^|[\s(])Skill\s+`([A-Za-z0-9][A-Za-z0-9._-]*)`""",
    re.IGNORECASE,
)


def _skill_names_referenced_in_entry(entry: str) -> set[str]:
    """Return skill names an entry explicitly recommends loading."""
    names: set[str] = set()
    for match in _SKILL_VIEW_NAME_RE.finditer(entry):
        name = (match.group(1) or "").strip()
        if name:
            names.add(name)
    for match in _SKILL_LABEL_RE.finditer(entry):
        name = (match.group(1) or "").strip()
        if name:
            names.add(name)
    return names


def _entry_references_skill(entry: str, skill_name: str) -> bool:
    target = (skill_name or "").strip().casefold()
    if not target:
        return False
    return any(name.casefold() == target for name in _skill_names_referenced_in_entry(entry))


def _known_skill_names() -> set[str]:
    """Directory + frontmatter names currently present on disk (local/ext/builtin)."""
    names: set[str] = set()
    try:
        from agent.skill_utils import get_all_skills_dirs, iter_skill_index_files, parse_frontmatter
    except Exception:
        return names

    for skills_dir in get_all_skills_dirs():
        if not skills_dir.exists():
            continue
        for skill_md in iter_skill_index_files(skills_dir, "SKILL.md"):
            names.add(skill_md.parent.name)
            try:
                raw = skill_md.read_text(encoding="utf-8")
                frontmatter, _ = parse_frontmatter(raw)
                fm_name = frontmatter.get("name")
                if isinstance(fm_name, str) and fm_name.strip():
                    names.add(fm_name.strip())
            except Exception:
                continue
    return names


def _read_memory_entries_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not raw:
        return []
    return [e.strip() for e in raw.split(ENTRY_DELIMITER) if e.strip()]


def _write_memory_entries_file(path: Path, entries: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not entries:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(ENTRY_DELIMITER.join(entries) + "\n", encoding="utf-8")


def scrub_skill_name_from_memory(skill_name: str) -> dict[str, int]:
    """Remove MEMORY.md / USER.md entries that recommend a deleted skill.

    Called after skill_manage delete / cloud uninstall so the next session
    does not keep instructing skill_view on a missing name.
    """
    name = (skill_name or "").strip()
    if not name:
        return {"memory": 0, "user": 0}

    removed = {"memory": 0, "user": 0}
    mem_dir = get_memory_dir()
    for target, filename in (("memory", "MEMORY.md"), ("user", "USER.md")):
        path = mem_dir / filename
        entries = _read_memory_entries_file(path)
        if not entries:
            continue
        kept = [e for e in entries if not _entry_references_skill(e, name)]
        dropped = len(entries) - len(kept)
        if dropped:
            _write_memory_entries_file(path, kept)
            removed[target] = dropped
            logger.info(
                "Removed %d %s memory entr%s referencing deleted skill '%s'",
                dropped,
                target,
                "y" if dropped == 1 else "ies",
                name,
            )
    return removed


def scrub_stale_skill_references_from_memory() -> dict[str, int]:
    """Drop memory entries that recommend skills no longer on disk.

    Runs at session load so orphaned refs (manual rm, cloud prune, rename)
    cannot keep steering skill_view toward 404s.
    """
    known = {n.casefold() for n in _known_skill_names()}
    removed = {"memory": 0, "user": 0}
    if not known:
        # No skills indexed at all — don't wipe every Skill `…` mention;
        # only clear when we can positively say a name is gone.
        return removed

    mem_dir = get_memory_dir()
    for target, filename in (("memory", "MEMORY.md"), ("user", "USER.md")):
        path = mem_dir / filename
        entries = _read_memory_entries_file(path)
        if not entries:
            continue
        kept: list[str] = []
        dropped = 0
        for entry in entries:
            refs = _skill_names_referenced_in_entry(entry)
            if refs and any(ref.casefold() not in known for ref in refs):
                dropped += 1
                continue
            kept.append(entry)
        if dropped:
            _write_memory_entries_file(path, kept)
            removed[target] = dropped
            logger.info(
                "Removed %d stale skill reference(s) from %s memory",
                dropped,
                target,
            )
    return removed


# ---------------------------------------------------------------------------
# Memory content scanning — lightweight check for injection/exfiltration
# in content that gets injected into the system prompt.
# ---------------------------------------------------------------------------

_MEMORY_THREAT_PATTERNS = [
    # Prompt injection
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'you\s+are\s+now\s+', "role_hijack"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'disregard\s+(your|all|any)\s+(instructions|rules|guidelines)', "disregard_rules"),
    (r'act\s+as\s+(if|though)\s+you\s+(have\s+no|don\'t\s+have)\s+(restrictions|limits|rules)', "bypass_restrictions"),
    # Exfiltration via curl/wget with secrets
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_curl"),
    (r'wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_wget"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)', "read_secrets"),
    # Persistence via shell rc
    (r'authorized_keys', "ssh_backdoor"),
    (r'\$HOME/\.ssh|\~/\.ssh', "ssh_access"),
    (r'\$HOME/\.ector/\.env|\~/\.ector/\.env', "ector_env"),
]

# Subset of invisible chars for injection detection
_INVISIBLE_CHARS = {
    '\u200b', '\u200c', '\u200d', '\u2060', '\ufeff',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
}


def _scan_memory_content(content: str) -> Optional[str]:
    """Scan memory content for injection/exfil patterns. Returns error string if blocked."""
    # Check invisible unicode
    for char in _INVISIBLE_CHARS:
        if char in content:
            return f"Blocked: content contains invisible unicode character U+{ord(char):04X} (possible injection)."

    # Check threat patterns
    for pattern, pid in _MEMORY_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return f"Blocked: content matches threat pattern '{pid}'. Memory entries are injected into the system prompt and must not contain injection or exfiltration payloads."

    return None


class MemoryStore:
    """
    Bounded curated memory with file persistence. One instance per AIAgent.

    Maintains two parallel states:
      - _system_prompt_snapshot: frozen at load time, used for system prompt injection.
        Never mutated mid-session. Keeps prefix cache stable.
      - memory_entries / user_entries: live state, mutated by tool calls, persisted to disk.
        Tool responses always reflect this live state.
    """

    def __init__(self, memory_char_limit: int = 10000, user_char_limit: int = 10000):
        self.memory_entries: List[str] = []
        self.user_entries: List[str] = []
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        # Frozen snapshot for system prompt -- set once at load_from_disk()
        self._system_prompt_snapshot: Dict[str, str] = {"memory": "", "user": ""}
        # Entry texts at load time — used to dedupe session delta vs snapshot
        self._snapshot_entry_texts: Dict[str, set[str]] = {"memory": set(), "user": set()}
        # Writes this session (add/replace) for optional ephemeral injection
        self._session_writes: List[Dict[str, str]] = []

    def load_from_disk(self):
        """Load entries from MEMORY.md and USER.md, capture system prompt snapshot."""
        mem_dir = get_memory_dir()
        mem_dir.mkdir(parents=True, exist_ok=True)

        # Drop entries that still push skill_view for skills that were deleted
        # (cloud prune, rename, manual rm) before freezing the prompt snapshot.
        try:
            scrub_stale_skill_references_from_memory()
        except Exception:
            logger.debug("stale skill memory scrub failed", exc_info=True)

        self.memory_entries = self._read_file(mem_dir / "MEMORY.md")
        self.user_entries = self._read_file(mem_dir / "USER.md")

        # Deduplicate entries (preserves order, keeps first occurrence)
        self.memory_entries = list(dict.fromkeys(self.memory_entries))
        self.user_entries = list(dict.fromkeys(self.user_entries))

        # Capture frozen snapshot for system prompt injection
        self._system_prompt_snapshot = {
            "memory": self._render_block("memory", self.memory_entries),
            "user": self._render_block("user", self.user_entries),
        }
        self._snapshot_entry_texts = {
            "memory": set(self.memory_entries),
            "user": set(self.user_entries),
        }
        self._session_writes = []

    def _record_session_write(self, target: str, content: str, action: str) -> None:
        """Track successful add/replace for optional session delta injection."""
        text = (content or "").strip()
        if not text or target not in ("memory", "user"):
            return
        self._session_writes.append({"target": target, "content": text, "action": action})

    def format_session_delta_block(self, max_chars: int = SESSION_DELTA_MAX_CHARS) -> str:
        """Return plain-text delta of session writes not already in the load snapshot."""
        if not self._session_writes:
            return ""

        seen_keys: set[tuple[str, str]] = set()
        lines: List[str] = []
        used = 0

        for item in self._session_writes:
            target = item.get("target", "")
            content = item.get("content", "").strip()
            if not content or target not in ("memory", "user"):
                continue
            if content in self._snapshot_entry_texts.get(target, set()):
                continue
            key = (target, content)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            label = "USER notes" if target == "user" else "MEMORY notes"
            line = f"[{label}] {content}"
            extra = len(line) + (1 if lines else 0)
            if used + extra > max_chars:
                break
            lines.append(line)
            used += extra

        if not lines:
            return ""

        header = (
            "[Session memory delta — written this session; "
            "not yet in the cached system prompt snapshot.]"
        )
        return header + "\n" + "\n".join(lines)

    @staticmethod
    @contextmanager
    def _file_lock(path: Path):
        """Acquire an exclusive file lock for read-modify-write safety.

        Uses a separate .lock file so the memory file itself can still be
        atomically replaced via os.replace().
        """
        lock_path = path.with_suffix(path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        if fcntl is None and msvcrt is None:
            yield
            return

        if msvcrt and (not lock_path.exists() or lock_path.stat().st_size == 0):
            lock_path.write_text(" ", encoding="utf-8")

        fd = open(lock_path, "r+" if msvcrt else "a+")
        try:
            if fcntl:
                fcntl.flock(fd, fcntl.LOCK_EX)
            else:
                fd.seek(0)
                msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            if fcntl:
                fcntl.flock(fd, fcntl.LOCK_UN)
            elif msvcrt:
                try:
                    fd.seek(0)
                    msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
                except (OSError, IOError):
                    pass
            fd.close()

    @staticmethod
    def _path_for(target: str) -> Path:
        mem_dir = get_memory_dir()
        if target == "user":
            return mem_dir / "USER.md"
        return mem_dir / "MEMORY.md"

    def _reload_target(self, target: str):
        """Re-read entries from disk into in-memory state.

        Called under file lock to get the latest state before mutating.
        """
        fresh = self._read_file(self._path_for(target))
        fresh = list(dict.fromkeys(fresh))  # deduplicate
        self._set_entries(target, fresh)

    def save_to_disk(self, target: str):
        """Persist entries to the appropriate file. Called after every mutation."""
        get_memory_dir().mkdir(parents=True, exist_ok=True)
        self._write_file(self._path_for(target), self._entries_for(target))

    def _entries_for(self, target: str) -> List[str]:
        if target == "user":
            return self.user_entries
        return self.memory_entries

    def _set_entries(self, target: str, entries: List[str]):
        if target == "user":
            self.user_entries = entries
        else:
            self.memory_entries = entries

    def _char_count(self, target: str) -> int:
        entries = self._entries_for(target)
        if not entries:
            return 0
        return len(ENTRY_DELIMITER.join(entries))

    def _char_limit(self, target: str) -> int:
        if target == "user":
            return self.user_char_limit
        return self.memory_char_limit

    async def add(self, target: str, content: str) -> Dict[str, Any]:
        """Append a new entry. Returns error if it would exceed the char limit."""
        content = content.strip()
        if not content:
            return {"success": False, "error": "Content cannot be empty."}

        if target == "user":
            try:
                from agent.onboarding import user_memory_blocks_assistant_alias_name

                _alias_err = user_memory_blocks_assistant_alias_name(content)
                if _alias_err:
                    return {"success": False, "error": _alias_err}
            except Exception:
                pass

        # Scan for injection/exfiltration before accepting
        scan_error = _scan_memory_content(content)
        if scan_error:
            return {"success": False, "error": scan_error}

        with self._file_lock(self._path_for(target)):
            # Re-read from disk under lock to pick up writes from other sessions
            self._reload_target(target)

            entries = self._entries_for(target)
            limit = self._char_limit(target)

            # Reject exact duplicates
            if content in entries:
                return self._success_response(target, "Entry already exists (no duplicate added).")

            # Calculate what the new total would be
            new_entries = entries + [content]
            new_total = len(ENTRY_DELIMITER.join(new_entries))

            if new_total > limit:
                # Autonomous behavior: instead of failing, try to summarize/compress
                logger.info("Memory for '%s' is full (%d/%d). Attempting autonomous optimization...", target, new_total, limit)
                success, optimized_entries = await self._auto_optimize(target, entries + [content])
                
                if success:
                    self._set_entries(target, optimized_entries)
                    self.save_to_disk(target)
                    self._record_session_write(target, content, "add")
                    return self._success_response(target, "Entry added (memory was automatically optimized to fit).")
                
                # If optimization failed or didn't save enough space, then we fall back to error
                current = self._char_count(target)
                return {
                    "success": False,
                    "error": (
                        f"Memory at {current:,}/{limit:,} chars. "
                        f"Autonomous optimization could not free enough space. "
                        f"Please manually remove or merge old entries."
                    ),
                    "current_entries": entries,
                    "usage": f"{current:,}/{limit:,}",
                }

            entries.append(content)
            self._set_entries(target, entries)
            self.save_to_disk(target)
            self._record_session_write(target, content, "add")

        return self._success_response(target, "Entry added.")

    def replace(self, target: str, old_text: str, new_content: str) -> Dict[str, Any]:
        """Find entry containing old_text substring, replace it with new_content."""
        old_text = old_text.strip()
        new_content = new_content.strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}
        if not new_content:
            return {"success": False, "error": "new_content cannot be empty. Use 'remove' to delete entries."}

        if target == "user":
            try:
                from agent.onboarding import user_memory_blocks_assistant_alias_name

                _alias_err = user_memory_blocks_assistant_alias_name(new_content)
                if _alias_err:
                    return {"success": False, "error": _alias_err}
            except Exception:
                pass

        # Scan replacement content for injection/exfiltration
        scan_error = _scan_memory_content(new_content)
        if scan_error:
            return {"success": False, "error": scan_error}

        with self._file_lock(self._path_for(target)):
            self._reload_target(target)

            entries = self._entries_for(target)
            matches = [(i, e) for i, e in enumerate(entries) if old_text in e]

            if not matches:
                return {"success": False, "error": f"No entry matched '{old_text}'."}

            if len(matches) > 1:
                # If all matches are identical (exact duplicates), operate on the first one
                unique_texts = set(e for _, e in matches)
                if len(unique_texts) > 1:
                    previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                    return {
                        "success": False,
                        "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                        "matches": previews,
                    }
                # All identical -- safe to replace just the first

            idx = matches[0][0]
            limit = self._char_limit(target)

            # Check that replacement doesn't blow the budget
            test_entries = entries.copy()
            test_entries[idx] = new_content
            new_total = len(ENTRY_DELIMITER.join(test_entries))

            if new_total > limit:
                return {
                    "success": False,
                    "error": (
                        f"Replacement would put memory at {new_total:,}/{limit:,} chars. "
                        f"Shorten the new content or remove other entries first."
                    ),
                }

            entries[idx] = new_content
            self._set_entries(target, entries)
            self.save_to_disk(target)
            self._record_session_write(target, new_content, "replace")

        return self._success_response(target, "Entry replaced.")

    def remove(self, target: str, old_text: str) -> Dict[str, Any]:
        """Remove the entry containing old_text substring."""
        old_text = old_text.strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}

        with self._file_lock(self._path_for(target)):
            self._reload_target(target)

            entries = self._entries_for(target)
            matches = [(i, e) for i, e in enumerate(entries) if old_text in e]

            if not matches:
                return {"success": False, "error": f"No entry matched '{old_text}'."}

            if len(matches) > 1:
                # If all matches are identical (exact duplicates), remove the first one
                unique_texts = set(e for _, e in matches)
                if len(unique_texts) > 1:
                    previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                    return {
                        "success": False,
                        "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                        "matches": previews,
                    }
                # All identical -- safe to remove just the first

            idx = matches[0][0]
            entries.pop(idx)
            self._set_entries(target, entries)
            self.save_to_disk(target)

        return self._success_response(target, "Entry removed.")

    def format_for_system_prompt(self, target: str) -> Optional[str]:
        """
        Return the frozen snapshot for system prompt injection.

        This returns the state captured at load_from_disk() time, NOT the live
        state. Mid-session writes do not affect this. This keeps the system
        prompt stable across all turns, preserving the prefix cache.

        Returns None if the snapshot is empty (no entries at load time).
        """
        block = self._system_prompt_snapshot.get(target, "")
        return block if block else None

    async def _auto_optimize(self, target: str, all_entries: List[str]) -> Tuple[bool, List[str]]:
        """Use LLM to compress memory entries when the limit is exceeded."""
        try:
            # Resolve credentials
            try:
                from ector_cli.config import load_config
                from ector_cli.runtime_provider import resolve_runtime_provider
                cfg = load_config()
                
                # Get primary model/provider
                model = cfg.get("model", "")
                if isinstance(model, dict):
                    model = model.get("default") or model.get("model") or ""
                
                # Resolve API key
                provider = os.getenv("ECTOR_INFERENCE_PROVIDER")
                runtime = resolve_runtime_provider(requested=provider)
                api_key = runtime.get("api_key")
                base_url = runtime.get("base_url") or "https://openrouter.ai/api/v1"
                
                if not api_key or not model:
                    return False, []
            except Exception as e:
                logger.debug("Failed to resolve LLM credentials for memory optimization: %s", e)
                return False, []

            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            
            limit = self._char_limit(target)
            content_to_optimize = ENTRY_DELIMITER.join(all_entries)
            
            system_prompt = (
                "You are a memory optimization assistant for Ector, an AI assistant. "
                "The user's memory store is full. Your task is to rewrite the provided memory entries "
                "to be more concise, remove duplicates, and merge related facts, while preserving ALL "
                "essential information, preferences, and corrections.\n\n"
                f"TARGET STORE: {target}\n"
                f"MAXIMUM CHARACTERS: {limit}\n\n"
                "RULES:\n"
                "1. Keep entries factual and brief.\n"
                "2. Merge entries that talk about the same topic.\n"
                "3. Remove outdated or corrected information (keep the latest version).\n"
                "4. Maintain the delimiter ' " + ENTRY_DELIMITER + " ' between entries.\n"
                "5. Output ONLY the optimized entries, nothing else."
            )
            
            user_prompt = f"Current entries to optimize (exceeding {limit} chars):\n\n{content_to_optimize}"
            
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            
            optimized_text = (response.choices[0].message.content or "").strip()
            new_entries = [e.strip() for e in optimized_text.split(ENTRY_DELIMITER) if e.strip()]
            
            # Final check: did it actually work?
            if len(ENTRY_DELIMITER.join(new_entries)) <= limit:
                return True, new_entries
                
            return False, []
        except Exception as e:
            logger.error("Autonomous memory optimization failed: %s", e)
            return False, []

    # -- Internal helpers --

    def _success_response(self, target: str, message: str = None) -> Dict[str, Any]:
        entries = self._entries_for(target)
        current = self._char_count(target)
        limit = self._char_limit(target)
        pct = min(100, int((current / limit) * 100)) if limit > 0 else 0

        resp = {
            "success": True,
            "target": target,
            "entries": entries,
            "usage": f"{pct}% — {current:,}/{limit:,} chars",
            "entry_count": len(entries),
        }
        if message:
            resp["message"] = message
        return resp

    def _render_block(self, target: str, entries: List[str]) -> str:
        """Render a system prompt block with header and usage indicator."""
        if not entries:
            return ""

        limit = self._char_limit(target)
        content = ENTRY_DELIMITER.join(entries)
        current = len(content)
        pct = min(100, int((current / limit) * 100)) if limit > 0 else 0

        if target == "user":
            header = (
                f"USER NOTES (agent-curated; ector.cc profile is authoritative "
                f"for name/personality/behavior) [{pct}% — {current:,}/{limit:,} chars]"
            )
        else:
            header = f"MEMORY (your personal notes) [{pct}% — {current:,}/{limit:,} chars]"

        separator = "═" * 46
        return f"{separator}\n{header}\n{separator}\n{content}"

    @staticmethod
    def _read_file(path: Path) -> List[str]:
        """Read a memory file and split into entries.

        No file locking needed: _write_file uses atomic rename, so readers
        always see either the previous complete file or the new complete file.
        """
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, IOError):
            return []

        if not raw.strip():
            return []

        # Use ENTRY_DELIMITER for consistency with _write_file. Splitting by "§"
        # alone would incorrectly split entries that contain "§" in their content.
        entries = [e.strip() for e in raw.split(ENTRY_DELIMITER)]
        return [e for e in entries if e]

    @staticmethod
    def _write_file(path: Path, entries: List[str]):
        """Write entries to a memory file using atomic temp-file + rename.

        Previous implementation used open("w") + flock, but "w" truncates the
        file *before* the lock is acquired, creating a race window where
        concurrent readers see an empty file. Atomic rename avoids this:
        readers always see either the old complete file or the new one.
        """
        content = ENTRY_DELIMITER.join(entries) if entries else ""
        try:
            # Write to temp file in same directory (same filesystem for atomic rename)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), suffix=".tmp", prefix=".mem_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, str(path))  # Atomic on same filesystem
            except BaseException:
                # Clean up temp file on any failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except (OSError, IOError) as e:
            raise RuntimeError(f"Failed to write memory file {path}: {e}")


async def memory_tool(
    action: str,
    target: str = "memory",
    content: str = None,
    old_text: str = None,
    store: Optional[MemoryStore] = None,
) -> str:
    """
    Single entry point for the memory tool. Dispatches to MemoryStore methods.

    Returns JSON string with results.
    """
    if store is None:
        return tool_error("Memory is not available. It may be disabled in config or this environment.", success=False)

    if target not in ("memory", "user"):
        return tool_error(f"Invalid target '{target}'. Use 'memory' or 'user'.", success=False)

    if action == "add":
        if not content:
            return tool_error("Content is required for 'add' action.", success=False)
        result = await store.add(target, content)

    elif action == "replace":
        if not old_text:
            return tool_error("old_text is required for 'replace' action.", success=False)
        if not content:
            return tool_error("content is required for 'replace' action.", success=False)
        result = store.replace(target, old_text, content)

    elif action == "remove":
        if not old_text:
            return tool_error("old_text is required for 'remove' action.", success=False)
        result = store.remove(target, old_text)

    else:
        return tool_error(f"Unknown action '{action}'. Use: add, replace, remove", success=False)

    return json.dumps(result, ensure_ascii=False)


def check_memory_requirements() -> bool:
    """Memory tool has no external requirements -- always available."""
    return True


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

MEMORY_SCHEMA = {
    "name": "memory",
    "description": (
        "Save durable information to persistent memory that survives across sessions. "
        "Memory is injected into future turns, so keep it compact and focused on facts "
        "that will still matter later.\n\n"
        "WHEN TO SAVE (do this proactively, don't wait to be asked):\n"
        "- User corrects you or says 'remember this' / 'don't do that again'\n"
        "- User shares a preference, habit, or personal detail (name, role, timezone, coding style)\n"
        "- You discover something about the environment (OS, installed tools, project structure)\n"
        "- You learn a convention, API quirk, or workflow specific to this user's setup\n"
        "- You identify a stable fact that will be useful again in future sessions\n\n"
        "PRIORITY: User preferences and corrections > environment facts > procedural knowledge. "
        "The most valuable memory prevents the user from having to repeat themselves.\n\n"
        "Do NOT save task progress, session outcomes, completed-work logs, or temporary TODO "
        "state to memory; use session_search to recall those from past transcripts.\n"
        "If you've discovered a new way to do something, solved a problem that could be "
        "necessary later, save it as a skill with the skill tool.\n\n"
        "TWO TARGETS:\n"
        "- 'user': who the user is -- name, role, preferences, communication style, pet peeves\n"
        "- 'memory': your notes -- environment facts, project conventions, tool quirks, lessons learned\n\n"
        "ACTIONS: add (new entry), replace (update existing -- old_text identifies it), "
        "remove (delete -- old_text identifies it).\n\n"
        "SKIP: trivial/obvious info, things easily re-discovered, raw data dumps, and temporary task state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove"],
                "description": "The action to perform."
            },
            "target": {
                "type": "string",
                "enum": ["memory", "user"],
                "description": "Which memory store: 'memory' for personal notes, 'user' for user profile."
            },
            "content": {
                "type": "string",
                "description": "The entry content. Required for 'add' and 'replace'."
            },
            "old_text": {
                "type": "string",
                "description": "Short unique substring identifying the entry to replace or remove."
            },
        },
        "required": ["action", "target"],
    },
}


# --- Registry ---
from tools.registry import registry, tool_error

registry.register(
    name="memory",
    toolset="memory",
    schema=MEMORY_SCHEMA,
    handler=lambda args, **kw: memory_tool(
        action=args.get("action", ""),
        target=args.get("target", "memory"),
        content=args.get("content"),
        old_text=args.get("old_text"),
        store=kw.get("store")),
    check_fn=check_memory_requirements,
    emoji="🧠",
)





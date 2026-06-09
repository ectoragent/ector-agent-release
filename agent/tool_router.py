"""Semantic / keyword tool routing for the agent loop.

Filters the OpenAI-format ``tools`` list sent to the LLM on each iteration
while keeping the full tool pool available for dispatch (expand-on-miss).

Routing is cache-safe: only the per-request ``tools`` parameter changes;
the cached system prompt is untouched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

from ector_constants import get_ector_home

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)

_DEFAULT_PIN_TOOLS = frozenset({
    "todo",
    "memory",
    "session_search",
    "wiser",
    "skills_list",
    "skill_view",
    "skill_manage",
    "delegate_task",
})

_DEFAULT_PIN_TOOLSETS = frozenset({"skills", "delegation", "planning"})

# Weak refs to live AIAgent instances — MCP tool-list refresh rebuilds their routers.
_ROUTING_AGENT_REFS: List[weakref.ref] = []


def register_routing_agent(agent: Any) -> None:
    """Register an agent instance for MCP-driven tool-index refresh."""
    ref = weakref.ref(agent)
    if ref not in _ROUTING_AGENT_REFS:
        _ROUTING_AGENT_REFS.append(ref)


def notify_registry_tools_changed() -> None:
    """Notify live agents that the tool registry changed (e.g. MCP list_changed)."""
    live: List[weakref.ref] = []
    for ref in _ROUTING_AGENT_REFS:
        agent = ref()
        if agent is None:
            continue
        live.append(ref)
        try:
            agent._reload_tools_for_routing()
        except Exception:
            logger.exception("tool routing registry refresh failed")
    _ROUTING_AGENT_REFS[:] = live


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


@dataclass
class ToolRoutingConfig:
    enabled: bool = True
    mode: str = "hybrid"  # keyword | hybrid | embedding
    max_tools: int = 24
    bm25_candidates: int = 48
    pin_tools: Set[str] = field(default_factory=lambda: set(_DEFAULT_PIN_TOOLS))
    pin_toolsets: Set[str] = field(default_factory=lambda: set(_DEFAULT_PIN_TOOLSETS))
    expand_on_miss: bool = True
    rerank_each_iteration: bool = True
    min_score: float = 0.0
    min_pool_size: int = 15

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "ToolRoutingConfig":
        if not isinstance(raw, dict):
            return cls()
        pin_tools = raw.get("pin_tools")
        pin_toolsets = raw.get("pin_toolsets")
        return cls(
            enabled=bool(raw.get("enabled", True)),
            mode=str(raw.get("mode", "hybrid")).strip().lower() or "hybrid",
            max_tools=max(1, int(raw.get("max_tools", 24))),
            bm25_candidates=max(1, int(raw.get("bm25_candidates", 48))),
            pin_tools=set(pin_tools) if isinstance(pin_tools, list) else set(_DEFAULT_PIN_TOOLS),
            pin_toolsets=set(pin_toolsets) if isinstance(pin_toolsets, list) else set(_DEFAULT_PIN_TOOLSETS),
            expand_on_miss=bool(raw.get("expand_on_miss", True)),
            rerank_each_iteration=bool(raw.get("rerank_each_iteration", True)),
            min_score=float(raw.get("min_score", 0.0)),
            min_pool_size=max(1, int(raw.get("min_pool_size", 15))),
        )


@dataclass
class RoutingContext:
    """Per-iteration routing inputs."""

    turn_query: str = ""
    iteration_query: str = ""
    turn_embedding: Optional[List[float]] = None
    expanded: Set[str] = field(default_factory=set)
    used_this_turn: Set[str] = field(default_factory=set)


@dataclass(frozen=True)
class RoutingSelection:
    """Result of a routing pass — used for logging."""

    visible: int
    total: int
    mode: str


@dataclass
class _ToolDoc:
    name: str
    toolset: str
    text: str
    tokens: List[str]
    schema_hash: str
    tool_def: Dict[str, Any]


class _BM25Index:
    """Minimal BM25 over pre-tokenized documents."""

    def __init__(self, docs: Sequence[_ToolDoc], *, k1: float = 1.5, b: float = 0.75):
        self._docs = list(docs)
        self._k1 = k1
        self._b = b
        self._avgdl = 0.0
        self._doc_len: List[int] = []
        self._doc_tf: List[Dict[str, int]] = []
        self._df: Dict[str, int] = {}
        self._N = len(self._docs)
        if not self._docs:
            return
        for doc in self._docs:
            tf: Dict[str, int] = {}
            for tok in doc.tokens:
                tf[tok] = tf.get(tok, 0) + 1
            self._doc_tf.append(tf)
            length = len(doc.tokens) or 1
            self._doc_len.append(length)
            self._avgdl += length
            for tok in tf:
                self._df[tok] = self._df.get(tok, 0) + 1
        self._avgdl /= max(self._N, 1)

    def rank(self, query: str, *, top_k: int) -> List[tuple[str, float]]:
        if not self._docs or top_k <= 0:
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return [(doc.name, 0.0) for doc in self._docs[:top_k]]
        scores: List[tuple[str, float]] = []
        for idx, doc in enumerate(self._docs):
            scores.append((doc.name, self._score(q_tokens, idx)))
        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:top_k]

    def _score(self, q_tokens: List[str], doc_idx: int) -> float:
        tf = self._doc_tf[doc_idx]
        dl = self._doc_len[doc_idx]
        total = 0.0
        for term in q_tokens:
            if term not in tf:
                continue
            df = self._df.get(term, 0)
            idf = math.log(1 + (self._N - df + 0.5) / (df + 0.5))
            freq = tf[term]
            denom = freq + self._k1 * (1 - self._b + self._b * dl / self._avgdl)
            total += idf * (freq * (self._k1 + 1)) / (denom or 1.0)
        return total


def _schema_hash(tool_def: Dict[str, Any]) -> str:
    fn = tool_def.get("function") or {}
    payload = json.dumps(fn, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _build_doc_text(name: str, description: str, toolset: str) -> str:
    parts = [name.replace("_", " "), name, description or ""]
    if toolset:
        parts.append(f"toolset {toolset}")
    return "\n".join(p for p in parts if p)


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class ToolRouter:
    """Rank and filter tool schemas for each LLM API call."""

    def __init__(
        self,
        tools: List[Dict[str, Any]],
        *,
        config: ToolRoutingConfig,
        toolset_resolver: Optional[Callable[[str], Optional[str]]] = None,
        toolset_expander: Optional[Callable[[str], Set[str]]] = None,
    ):
        self.config = config
        self._toolset_resolver = toolset_resolver or (lambda _name: None)
        self._toolset_expander = toolset_expander or (lambda _ts: set())
        self._docs: List[_ToolDoc] = []
        self._by_name: Dict[str, _ToolDoc] = {}
        self._pinned_names: Set[str] = set()
        self._bm25: Optional[_BM25Index] = None
        self._embeddings: Dict[str, List[float]] = {}
        self._embeddings_loaded = False
        self._stats_expansions = 0
        self.last_selection: Optional[RoutingSelection] = None
        self.rebuild(tools)

    @classmethod
    def from_tools(
        cls,
        tools: List[Dict[str, Any]],
        *,
        config: Optional[Dict[str, Any]] = None,
        toolset_resolver: Optional[Callable[[str], Optional[str]]] = None,
        toolset_expander: Optional[Callable[[str], Set[str]]] = None,
    ) -> "ToolRouter":
        return cls(
            tools,
            config=ToolRoutingConfig.from_dict(config),
            toolset_resolver=toolset_resolver,
            toolset_expander=toolset_expander,
        )

    @property
    def all_tool_names(self) -> Set[str]:
        return set(self._by_name)

    @property
    def stats_expansions(self) -> int:
        return self._stats_expansions

    def rebuild(self, tools: List[Dict[str, Any]]) -> None:
        docs: List[_ToolDoc] = []
        by_name: Dict[str, _ToolDoc] = {}
        for tool_def in tools or []:
            if not isinstance(tool_def, dict):
                continue
            fn = tool_def.get("function") or {}
            name = fn.get("name")
            if not name:
                continue
            toolset = self._toolset_resolver(name) or ""
            description = str(fn.get("description") or "")
            text = _build_doc_text(name, description, toolset)
            doc = _ToolDoc(
                name=name,
                toolset=toolset,
                text=text,
                tokens=_tokenize(text),
                schema_hash=_schema_hash(tool_def),
                tool_def=tool_def,
            )
            docs.append(doc)
            by_name[name] = doc
        self._docs = docs
        self._by_name = by_name
        self._bm25 = _BM25Index(docs)
        self._pinned_names = self._compute_pinned_names()
        self._embeddings = {}
        self._embeddings_loaded = False
        self._load_embeddings_from_cache()

    def _compute_pinned_names(self) -> Set[str]:
        pinned = {n for n in self.config.pin_tools if n in self._by_name}
        for ts in self.config.pin_toolsets:
            for name in self._toolset_expander(ts):
                if name in self._by_name:
                    pinned.add(name)
        return pinned

    def should_route(self) -> bool:
        if not self.config.enabled:
            return False
        return len(self._by_name) > self.config.min_pool_size

    def expand_tool(self, name: str) -> bool:
        if name in self._by_name:
            self._stats_expansions += 1
            return True
        return False

    def rank(self, query: str, *, k: Optional[int] = None) -> List[str]:
        if not query.strip() or self._bm25 is None:
            return list(self._by_name)
        limit = k or self.config.bm25_candidates
        ranked = self._bm25.rank(query, top_k=limit)
        if self.config.min_score > 0:
            ranked = [(name, score) for name, score in ranked if score >= self.config.min_score]
        return [name for name, _score in ranked]

    def _embedding_rerank(
        self,
        candidates: List[str],
        *,
        query_embedding: Optional[List[float]],
        k: int,
    ) -> List[str]:
        if not query_embedding or not candidates:
            return candidates[:k]
        scored: List[tuple[str, float]] = []
        for name in candidates:
            emb = self._embeddings.get(name)
            score = _cosine_similarity(query_embedding, emb) if emb else 0.0
            scored.append((name, score))
        if self.config.min_score > 0:
            scored = [(n, s) for n, s in scored if s >= self.config.min_score]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [name for name, _ in scored[:k]]

    def select_for_context(
        self,
        tools: List[Dict[str, Any]],
        context: Optional[RoutingContext],
    ) -> List[Dict[str, Any]]:
        total = len(tools or [])
        if not self.should_route():
            self.last_selection = None
            return list(tools or [])

        ctx = context or RoutingContext()
        query = (ctx.iteration_query or ctx.turn_query or "").strip()
        if not self.config.rerank_each_iteration:
            query = (ctx.turn_query or query).strip()

        selected_names: Set[str] = set(self._pinned_names)
        selected_names.update(ctx.expanded)
        selected_names.update(ctx.used_this_turn)

        mode = self.config.mode
        use_embedding = mode in ("hybrid", "embedding")

        if query:
            if use_embedding and ctx.turn_embedding:
                self._ensure_embeddings()
            if use_embedding and ctx.turn_embedding and mode == "embedding":
                ranked = self._embedding_rerank(
                    list(self._by_name),
                    query_embedding=ctx.turn_embedding,
                    k=self.config.max_tools,
                )
            elif use_embedding and ctx.turn_embedding and mode == "hybrid":
                ranked = self._embedding_rerank(
                    self.rank(query, k=self.config.bm25_candidates),
                    query_embedding=ctx.turn_embedding,
                    k=self.config.max_tools,
                )
            else:
                ranked = self.rank(query, k=self.config.max_tools)

            for name in ranked:
                if name in self._by_name:
                    selected_names.add(name)
                if len(selected_names) >= self.config.max_tools:
                    break

        visible = [
            t for t in (tools or [])
            if (t.get("function") or {}).get("name") in selected_names
        ]
        if not visible:
            self.last_selection = None
            return list(tools or [])

        self.last_selection = RoutingSelection(
            visible=len(visible),
            total=total,
            mode=mode,
        )
        return visible

    def prepare_turn_embedding(self, turn_query: str) -> Optional[List[float]]:
        if not self.should_route():
            return None
        if self.config.mode not in ("hybrid", "embedding"):
            return None
        if not turn_query.strip():
            return None
        try:
            from agent.auxiliary_client import embed_text
            return embed_text(turn_query, task="embedding")
        except Exception as exc:
            logger.debug("Turn embedding failed, falling back to keyword routing: %s", exc)
            return None

    def _embeddings_cache_path(self) -> Path:
        return get_ector_home() / "cache" / "tool_embeddings.json"

    def _load_embeddings_from_cache(self) -> None:
        """Load cached tool embeddings (no network). Called on rebuild."""
        self._embeddings = {}
        if self.config.mode not in ("hybrid", "embedding") or not self._docs:
            return

        try:
            from agent.auxiliary_client import get_embedding_model_name
        except Exception:
            return

        model_name = get_embedding_model_name("embedding")
        cache_path = self._embeddings_cache_path()
        if not cache_path.is_file():
            return

        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return

        if cached.get("model") != model_name:
            return

        cache_tools = cached.get("tools")
        if not isinstance(cache_tools, dict):
            return

        for doc in self._docs:
            entry = cache_tools.get(doc.name)
            if (
                isinstance(entry, dict)
                and entry.get("hash") == doc.schema_hash
                and isinstance(entry.get("embedding"), list)
            ):
                self._embeddings[doc.name] = [float(x) for x in entry["embedding"]]

    def _ensure_embeddings(self) -> None:
        """Fill missing tool embeddings via API (lazy, once per rebuild)."""
        if self._embeddings_loaded:
            return
        self._embeddings_loaded = True
        if self.config.mode not in ("hybrid", "embedding") or not self._docs:
            return

        missing = [doc for doc in self._docs if doc.name not in self._embeddings]
        if not missing:
            return

        try:
            from agent.auxiliary_client import embed_text, get_embedding_model_name
        except Exception:
            return

        model_name = get_embedding_model_name("embedding")
        cache_path = self._embeddings_cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        cached: Dict[str, Any] = {}
        cache_tools: Dict[str, Any] = {}
        if cache_path.is_file():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("model") == model_name:
                    raw_tools = cached.get("tools")
                    if isinstance(raw_tools, dict):
                        cache_tools = dict(raw_tools)
            except Exception:
                pass

        updated = False
        for doc in missing:
            try:
                vec = embed_text(doc.text, task="embedding")
            except Exception as exc:
                logger.debug("Embedding tool %s failed: %s", doc.name, exc)
                continue
            if not vec:
                continue
            self._embeddings[doc.name] = vec
            cache_tools[doc.name] = {"hash": doc.schema_hash, "embedding": vec}
            updated = True

        if updated:
            payload = {"version": 1, "model": model_name, "tools": cache_tools}
            try:
                tmp = cache_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(payload), encoding="utf-8")
                tmp.replace(cache_path)
            except Exception as exc:
                logger.debug("Failed to write tool embedding cache: %s", exc)

    def purge_stale_cache_entries(self) -> None:
        """Remove cache entries for tools no longer in the index."""
        if not self._embeddings_cache_path().is_file():
            return
        try:
            from agent.auxiliary_client import get_embedding_model_name
            cached = json.loads(self._embeddings_cache_path().read_text(encoding="utf-8"))
            if cached.get("model") != get_embedding_model_name("embedding"):
                return
            tools = cached.get("tools")
            if not isinstance(tools, dict):
                return
            live = set(self._by_name)
            pruned = {k: v for k, v in tools.items() if k in live}
            if len(pruned) != len(tools):
                cached["tools"] = pruned
                tmp = self._embeddings_cache_path().with_suffix(".tmp")
                tmp.write_text(json.dumps(cached), encoding="utf-8")
                tmp.replace(self._embeddings_cache_path())
        except Exception:
            pass


def build_iteration_query(
    turn_query: str,
    messages: Iterable[Dict[str, Any]],
    *,
    tail_messages: int = 4,
) -> str:
    """Compose a lexical query from the user turn plus recent assistant/tool text."""
    parts: List[str] = []
    if turn_query.strip():
        parts.append(turn_query.strip())

    tail: List[str] = []
    for msg in messages or []:
        role = msg.get("role")
        if role not in ("assistant", "tool"):
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            tail.append(content.strip()[:800])
        elif role == "assistant" and msg.get("tool_calls"):
            for tc in msg.get("tool_calls") or []:
                fn = (tc.get("function") if isinstance(tc, dict) else getattr(tc, "function", None)) or {}
                if isinstance(fn, dict) and fn.get("name"):
                    tail.append(str(fn["name"]))

    if tail:
        parts.extend(tail[-tail_messages:])
    return "\n".join(parts).strip()

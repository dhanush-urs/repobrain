"""
flow_service.py — Execution Flow Map inference engine.

Infers likely execution paths through a repository using static heuristics:
  - Dependency edges (import/from_import/call)
  - Symbol table (function/class definitions)
  - File naming conventions (route/service/repository/util/model/worker)
  - Route decorator patterns (FastAPI, Flask, Express, etc.)

All logic is generic — no repo-specific hardcoding.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.dependency_edge import DependencyEdge
from app.db.models.file import File
from app.db.models.symbol import Symbol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File role classifier — generic naming heuristics
# ---------------------------------------------------------------------------

_ROLE_PATTERNS: list[tuple[str, list[str]]] = [
    ("route_handler",  ["route", "router", "routes", "controller", "handler", "endpoint", "view", "api"]),
    ("service",        ["service", "services", "usecase", "use_case", "business", "logic", "manager"]),
    ("repository",     ["repo", "repository", "dao", "store", "storage", "crud", "db", "database", "query"]),
    ("model",          ["model", "models", "schema", "schemas", "entity", "entities", "orm"]),
    ("util",           ["util", "utils", "helper", "helpers", "common", "shared", "lib", "libs"]),
    ("config",         ["config", "settings", "configuration", "env", "constants"]),
    ("middleware",     ["middleware", "interceptor", "guard", "auth", "authentication", "authorization"]),
    ("worker",         ["worker", "task", "job", "queue", "celery", "background", "async"]),
    ("client",         ["client", "external", "api_client", "http", "request", "fetch"]),
    ("test",           ["test", "tests", "spec", "specs", "__test__", "fixture"]),
]

# Role ordering for flow path scoring (earlier = more likely to be upstream)
_ROLE_ORDER = {
    "route_handler": 0,
    "middleware":    1,
    "service":       2,
    "repository":    3,
    "model":         4,
    "client":        5,
    "worker":        6,
    "util":          7,
    "config":        8,
    "test":          9,
    "unknown":       10,
}


def _classify_file_role(path: str, file_kind: str | None = None) -> str:
    """Classify a file's architectural role from its path and kind."""
    path_lower = path.lower()
    parts = path_lower.replace("\\", "/").split("/")
    basename = parts[-1].rsplit(".", 1)[0] if "." in parts[-1] else parts[-1]

    # Check each part of the path against role patterns
    for role, keywords in _ROLE_PATTERNS:
        for part in parts + [basename]:
            for kw in keywords:
                if kw == part or part.startswith(kw + "_") or part.endswith("_" + kw):
                    return role
                if kw in part and len(kw) >= 4:
                    return role

    if file_kind in ("test",):
        return "test"
    if file_kind in ("config",):
        return "config"

    return "unknown"


# ---------------------------------------------------------------------------
# Route pattern detector — generic multi-framework support
# ---------------------------------------------------------------------------

# Patterns for common route decorators across frameworks
_ROUTE_PATTERNS = [
    # FastAPI / Flask / Starlette
    re.compile(r'@(?:app|router|blueprint|api)\.(get|post|put|delete|patch|options|head)\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE),
    # Express.js
    re.compile(r'(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE),
    # Django urls.py path()
    re.compile(r'path\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE),
    # Generic route annotation
    re.compile(r'@Route\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE),
]


def _find_route_in_file(content: str, route_query: str) -> tuple[bool, str | None]:
    """
    Check if a file contains a route matching the query.
    Returns (found, handler_symbol_name).
    """
    if not content:
        return False, None

    route_q = route_query.strip().lower().rstrip("/")

    for pat in _ROUTE_PATTERNS:
        for m in pat.finditer(content):
            groups = m.groups()
            # groups may be (method, path) or (path,) depending on pattern
            route_path = groups[-1].lower().rstrip("/")
            if route_path == route_q or route_path.endswith(route_q) or route_q.endswith(route_path):
                # Try to find the function name after the decorator
                after = content[m.end():]
                fn_match = re.search(r"(?:async\s+)?(?:def|function)\s+(\w+)", after[:200])
                handler = fn_match.group(1) if fn_match else None
                return True, handler

    return False, None


# ---------------------------------------------------------------------------
# Topology builder — shared across all modes
# ---------------------------------------------------------------------------

class RepoTopology:
    """
    Lightweight in-memory topology built from DB data.
    Shared across flow inference modes.
    """

    def __init__(self, db: Session, repository_id: str):
        self.db = db
        self.repository_id = repository_id
        self._files: dict[str, dict] = {}          # file_id → file_info
        self._path_to_id: dict[str, str] = {}      # path → file_id
        self._symbols: dict[str, list[dict]] = {}  # name_lower → [symbol_info]
        self._outgoing: dict[str, list[dict]] = defaultdict(list)  # file_id → [edge]
        self._incoming: dict[str, list[dict]] = defaultdict(list)  # file_id → [edge]
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return

        # Load files — do NOT load File.content (can be megabytes per file)
        # Content is fetched lazily only when needed (e.g. route detection)
        file_rows = list(self.db.execute(
            select(File.id, File.path, File.language, File.file_kind,
                   File.line_count, File.is_test, File.is_generated, File.is_vendor)
            .where(File.repository_id == self.repository_id)
        ).all())

        for fid, path, lang, kind, lc, is_test, is_gen, is_vendor in file_rows:
            role = _classify_file_role(path, kind)
            self._files[fid] = {
                "id": fid, "path": path, "language": lang,
                "file_kind": kind or "source", "line_count": lc or 0,
                "content": None,  # loaded lazily via _load_content()
                "role": role,
                "is_test": bool(is_test), "is_generated": bool(is_gen), "is_vendor": bool(is_vendor),
                "name": path.split("/")[-1],
            }
            self._path_to_id[path.lower()] = fid
            # Also index by basename
            basename = path.split("/")[-1].lower()
            if basename not in self._path_to_id:
                self._path_to_id[basename] = fid

        # Load symbols
        sym_rows = list(self.db.execute(
            select(Symbol.id, Symbol.name, Symbol.symbol_type, Symbol.file_id,
                   Symbol.start_line, Symbol.end_line, Symbol.signature)
            .where(Symbol.repository_id == self.repository_id)
        ).all())

        for sid, name, stype, file_id, sl, el, sig in sym_rows:
            key = name.lower()
            self._symbols.setdefault(key, []).append({
                "id": sid, "name": name, "type": stype,
                "file_id": file_id, "start_line": sl, "end_line": el,
                "signature": sig,
            })

        # Load edges
        edge_rows = list(self.db.execute(
            select(DependencyEdge.id, DependencyEdge.source_file_id,
                   DependencyEdge.target_file_id, DependencyEdge.edge_type,
                   DependencyEdge.target_ref, DependencyEdge.source_ref)
            .where(
                DependencyEdge.repository_id == self.repository_id,
                DependencyEdge.source_file_id.isnot(None),
            )
        ).all())

        for eid, src, tgt, etype, tref, sref in edge_rows:
            edge = {"id": eid, "source": src, "target": tgt,
                    "type": etype, "target_ref": tref, "source_ref": sref}
            self._outgoing[src].append(edge)
            if tgt:
                self._incoming[tgt].append(edge)

        self._loaded = True

    def _load_content(self, file_id: str) -> str:
        """Lazily fetch file content for a single file (only when needed)."""
        fi = self._files.get(file_id)
        if fi is None:
            return ""
        if fi["content"] is not None:
            return fi["content"]
        try:
            row = self.db.execute(
                select(File.content).where(File.id == file_id)
            ).scalar_one_or_none()
            fi["content"] = row or ""
        except Exception:
            fi["content"] = ""
        return fi["content"]

    def file_by_path(self, path_query: str) -> dict | None:
        """Find a file by path (exact, case-insensitive, or basename)."""
        q = path_query.lower().strip()
        fid = self._path_to_id.get(q)
        if not fid:
            # Try suffix match
            for p, fid2 in self._path_to_id.items():
                if p.endswith("/" + q) or q.endswith("/" + p):
                    fid = fid2
                    break
        return self._files.get(fid) if fid else None

    def symbols_by_name(self, name: str) -> list[dict]:
        return self._symbols.get(name.lower(), [])

    def outgoing(self, file_id: str) -> list[dict]:
        return self._outgoing.get(file_id, [])

    def incoming(self, file_id: str) -> list[dict]:
        return self._incoming.get(file_id, [])

    def file_info(self, file_id: str) -> dict | None:
        return self._files.get(file_id)

    def all_files(self) -> list[dict]:
        return list(self._files.values())


# ---------------------------------------------------------------------------
# Flow path builder
# ---------------------------------------------------------------------------

def _node_type_label(role: str) -> str:
    labels = {
        "route_handler": "route_handler",
        "service":       "service",
        "repository":    "repository",
        "model":         "model",
        "util":          "utility",
        "config":        "config",
        "middleware":    "middleware",
        "worker":        "worker",
        "client":        "external_client",
        "test":          "test",
        "unknown":       "module",
    }
    return labels.get(role, "module")


def _build_flow_node(file_info: dict, symbol: str | None = None,
                     changed: bool = False, impacted: bool = False) -> dict:
    role = file_info.get("role", "unknown")
    return {
        "id": f"fn_{file_info['id']}",
        "file_id": file_info["id"],  # expose for deep-linking
        "label": file_info["name"],
        "type": _node_type_label(role),
        "path": file_info["path"],
        "symbol": symbol,
        "role": role,
        "language": file_info.get("language"),
        "line_count": file_info.get("line_count", 0),
        "changed": changed,
        "impacted": impacted,
    }


def _build_flow_edge(src_id: str, tgt_id: str, etype: str = "calls") -> dict:
    return {
        "source": f"fn_{src_id}",
        "target": f"fn_{tgt_id}",
        "type": etype,
    }


def _score_path(nodes: list[dict]) -> float:
    """Score a flow path based on role ordering and diversity."""
    if not nodes:
        return 0.0

    score = 0.5  # base

    # Bonus for having diverse roles
    roles = [n.get("role", "unknown") for n in nodes]
    unique_roles = set(roles)
    score += min(len(unique_roles) * 0.08, 0.3)

    # Bonus for following natural role order
    role_positions = [_ROLE_ORDER.get(r, 10) for r in roles]
    ordered = all(role_positions[i] <= role_positions[i + 1] for i in range(len(role_positions) - 1))
    if ordered:
        score += 0.15

    # Bonus for having a route handler at start
    if roles and roles[0] == "route_handler":
        score += 0.1

    # Bonus for having a repository/db at end
    if roles and roles[-1] in ("repository", "model"):
        score += 0.08

    # Penalty for test files
    if any(n.get("role") == "test" for n in nodes):
        score -= 0.2

    return round(min(score, 0.99), 2)


def _bfs_downstream(
    topo: RepoTopology,
    start_file_id: str,
    max_depth: int = 4,
    max_nodes: int = 8,
    exclude_roles: set[str] | None = None,
) -> list[dict]:
    """BFS downstream from a file through outgoing dependency edges."""
    exclude_roles = exclude_roles or {"test", "config"}
    visited: dict[str, int] = {start_file_id: 0}
    queue: deque[tuple[str, int]] = deque([(start_file_id, 0)])
    path_nodes: list[dict] = []

    while queue and len(path_nodes) < max_nodes:
        fid, depth = queue.popleft()
        fi = topo.file_info(fid)
        if not fi:
            continue
        if fi.get("role") not in exclude_roles:
            path_nodes.append(fi)

        if depth >= max_depth:
            continue

        for edge in topo.outgoing(fid):
            tgt = edge.get("target")
            if not tgt or tgt in visited:
                continue
            tgt_fi = topo.file_info(tgt)
            if not tgt_fi:
                continue
            if tgt_fi.get("is_test") or tgt_fi.get("is_generated") or tgt_fi.get("is_vendor"):
                continue
            visited[tgt] = depth + 1
            queue.append((tgt, depth + 1))

    return path_nodes


def _bfs_upstream(
    topo: RepoTopology,
    start_file_id: str,
    max_depth: int = 3,
    max_nodes: int = 6,
) -> list[dict]:
    """BFS upstream from a file through incoming dependency edges."""
    visited: dict[str, int] = {start_file_id: 0}
    queue: deque[tuple[str, int]] = deque([(start_file_id, 0)])
    path_nodes: list[dict] = []

    while queue and len(path_nodes) < max_nodes:
        fid, depth = queue.popleft()
        fi = topo.file_info(fid)
        if fi:
            path_nodes.append(fi)
        if depth >= max_depth:
            continue
        for edge in topo.incoming(fid):
            src = edge.get("source")
            if not src or src in visited:
                continue
            src_fi = topo.file_info(src)
            if not src_fi or src_fi.get("is_test"):
                continue
            visited[src] = depth + 1
            queue.append((src, depth + 1))

    return list(reversed(path_nodes))  # upstream first


# ---------------------------------------------------------------------------
# Mode implementations
# ---------------------------------------------------------------------------

def _flow_route(topo: RepoTopology, query: str, depth: int) -> dict:
    """Find route handler and trace downstream flow."""
    route_q = query.strip()
    if not route_q.startswith("/"):
        route_q = "/" + route_q

    # Search all files for a matching route decorator
    candidates: list[tuple[dict, str | None, float]] = []  # (file_info, handler_name, confidence)

    for fi in topo.all_files():
        if fi.get("is_test") or fi.get("is_generated") or fi.get("is_vendor"):
            continue
        content = topo._load_content(fi["id"])
        found, handler = _find_route_in_file(content, route_q)
        if found:
            candidates.append((fi, handler, 0.9))
        elif fi.get("role") == "route_handler":
            # Weaker match: file is a route handler and path appears in content
            if route_q.lower().replace("/", "") in content.lower():
                candidates.append((fi, None, 0.5))

    if not candidates:
        return _empty_flow("route", query, f"No route matching '{route_q}' found in indexed files.")

    paths = []
    for fi, handler, conf in candidates[:2]:
        downstream = _bfs_downstream(topo, fi["id"], max_depth=depth, max_nodes=6)
        if not downstream:
            downstream = [fi]

        nodes = [_build_flow_node(n, symbol=handler if n["id"] == fi["id"] else None)
                 for n in downstream]
        edges = [_build_flow_edge(downstream[i]["id"], downstream[i + 1]["id"], "calls")
                 for i in range(len(downstream) - 1)]

        score = _score_path(nodes) * conf
        explanation = f"Route '{route_q}' → {' → '.join(n['label'] for n in nodes[:4])}"

        paths.append({
            "id": f"path_{len(paths) + 1}",
            "score": round(score, 2),
            "explanation": explanation,
            "nodes": nodes,
            "edges": edges,
        })

    paths.sort(key=lambda p: -p["score"])
    return _wrap_result("route", query, paths, notes=["Static heuristic inference from route decorators and dependency edges."])


def _flow_file(topo: RepoTopology, query: str, depth: int) -> dict:
    """Show upstream + downstream flow for a given file."""
    fi = topo.file_by_path(query)
    if not fi:
        return _empty_flow("file", query, f"File '{query}' not found in indexed repository.")

    upstream = _bfs_upstream(topo, fi["id"], max_depth=min(depth, 3), max_nodes=4)
    downstream = _bfs_downstream(topo, fi["id"], max_depth=depth, max_nodes=5)

    # Combine: upstream → target → downstream (deduplicated)
    seen: set[str] = set()
    all_nodes_info: list[dict] = []
    for n in upstream + [fi] + downstream:
        if n["id"] not in seen:
            seen.add(n["id"])
            all_nodes_info.append(n)

    nodes = [_build_flow_node(n) for n in all_nodes_info]
    edges = []
    node_ids = {n["id"] for n in all_nodes_info}

    for n in all_nodes_info:
        for edge in topo.outgoing(n["id"]):
            tgt = edge.get("target")
            if tgt and tgt in node_ids and tgt != n["id"]:
                edges.append(_build_flow_edge(n["id"], tgt, edge.get("type", "depends_on")))

    score = _score_path(nodes)
    explanation = f"Flow through {fi['name']}: {len(upstream)} upstream, {len(downstream)} downstream files."

    path = {
        "id": "path_1",
        "score": score,
        "explanation": explanation,
        "nodes": nodes,
        "edges": edges,
    }
    return _wrap_result("file", query, [path],
                        notes=[f"File role: {fi.get('role', 'unknown')}. Showing upstream + downstream dependency chain."])


def _flow_function(topo: RepoTopology, query: str, depth: int) -> dict:
    """Find a function/symbol and trace its cross-file call path."""
    sym_name = query.strip()
    matches = topo.symbols_by_name(sym_name)

    if not matches:
        # Try partial match
        q_lower = sym_name.lower()
        for key, syms in topo._symbols.items():
            if q_lower in key or key in q_lower:
                matches.extend(syms)
        if not matches:
            return _empty_flow("function", query, f"Symbol '{sym_name}' not found in indexed repository.")

    # Deduplicate by file_id, prefer exact name match
    seen_files: set[str] = set()
    best_matches: list[dict] = []
    for sym in sorted(matches, key=lambda s: (s["name"].lower() != sym_name.lower(), len(s["name"]))):
        if sym["file_id"] not in seen_files:
            seen_files.add(sym["file_id"])
            best_matches.append(sym)
        if len(best_matches) >= 3:
            break

    paths = []
    for sym in best_matches:
        fi = topo.file_info(sym["file_id"])
        if not fi:
            continue

        downstream = _bfs_downstream(topo, fi["id"], max_depth=depth, max_nodes=6)
        if not downstream:
            downstream = [fi]

        nodes = [_build_flow_node(n, symbol=sym["name"] if n["id"] == fi["id"] else None)
                 for n in downstream]
        edges = [_build_flow_edge(downstream[i]["id"], downstream[i + 1]["id"], "calls")
                 for i in range(len(downstream) - 1)]

        score = _score_path(nodes)
        explanation = f"Function '{sym['name']}' in {fi['name']} → {' → '.join(n['label'] for n in nodes[1:4])}"

        paths.append({
            "id": f"path_{len(paths) + 1}",
            "score": round(score, 2),
            "explanation": explanation,
            "nodes": nodes,
            "edges": edges,
        })

    paths.sort(key=lambda p: -p["score"])
    notes = [f"Found {len(matches)} symbol match(es) for '{sym_name}'."]
    if len(matches) > 3:
        notes.append(f"Showing top 3 candidates. {len(matches) - 3} additional matches not shown.")
    return _wrap_result("function", query, paths, notes=notes)


# ---------------------------------------------------------------------------
# Entrypoint detection — generic heuristics, no repo-specific hardcoding
# ---------------------------------------------------------------------------

# Generic entrypoint filename stems (language-agnostic)
# Ordered by confidence: exact match scores higher than prefix/suffix match
_ENTRYPOINT_STEMS: list[tuple[str, float]] = [
    # Python
    ("app",        0.90),
    ("main",       0.88),
    ("server",     0.85),
    ("manage",     0.80),   # Django manage.py
    ("wsgi",       0.75),
    ("asgi",       0.75),
    ("run",        0.70),
    ("start",      0.65),
    ("bootstrap",  0.60),
    ("init",       0.55),
    # JS/TS
    ("index",      0.85),
    ("server",     0.85),
    ("app",        0.90),
    ("main",       0.88),
    ("entry",      0.80),
    # Go
    ("main",       0.88),
    # Generic
    ("cli",        0.60),
    ("launcher",   0.55),
]

# Entrypoint directory hints — files in these dirs score higher
_ENTRYPOINT_DIR_BOOST: dict[str, float] = {
    "src":  0.10,
    "app":  0.05,
    "cmd":  0.15,   # Go convention
    "bin":  0.10,
}

# Roles that are NOT entrypoints (penalize)
_NON_ENTRYPOINT_ROLES = {"test", "config", "model", "util"}


def _score_entrypoint(fi: dict, outgoing_count: int) -> float:
    """
    Score a file as a likely application entrypoint.
    Returns a float in [0, 1]. Higher = more likely entrypoint.
    Generic — no repo-specific logic.
    """
    path = fi.get("path", "")
    path_lower = path.lower().replace("\\", "/")
    parts = path_lower.split("/")
    basename = parts[-1]
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename

    # Skip non-source files
    if fi.get("is_test") or fi.get("is_generated") or fi.get("is_vendor"):
        return 0.0

    # Skip roles that are never entrypoints
    role = fi.get("role", "unknown")
    if role in _NON_ENTRYPOINT_ROLES:
        return 0.0

    score = 0.0

    # 1. Stem match
    for ep_stem, ep_score in _ENTRYPOINT_STEMS:
        if stem == ep_stem:
            score = max(score, ep_score)
            break
        if stem.startswith(ep_stem + "_") or stem.endswith("_" + ep_stem):
            score = max(score, ep_score * 0.85)

    # 2. Depth bonus — shallower files are more likely entrypoints
    depth = len(parts) - 1  # 0 = root level
    if depth == 0:
        score += 0.15
    elif depth == 1:
        score += 0.08
    elif depth >= 4:
        score -= 0.10

    # 3. Directory hint
    for dir_part, boost in _ENTRYPOINT_DIR_BOOST.items():
        if dir_part in parts[:-1]:
            score += boost
            break

    # 4. Outgoing edges — entrypoints import many things
    if outgoing_count >= 5:
        score += 0.12
    elif outgoing_count >= 3:
        score += 0.07
    elif outgoing_count >= 1:
        score += 0.03
    elif outgoing_count == 0 and score > 0:
        # Named like an entrypoint but no imports — lower confidence
        score -= 0.10

    # 5. Role bonus — route_handler files are often near entrypoints
    if role == "route_handler":
        score += 0.05

    return round(min(max(score, 0.0), 1.0), 3)


def _detect_entrypoints(topo: RepoTopology) -> list[tuple[dict, float]]:
    """
    Detect likely application entrypoints from the topology.
    Returns a list of (file_info, confidence_score) sorted by score descending.
    Never raises.
    """
    # Count outgoing edges per file
    outgoing_counts: dict[str, int] = {}
    for fi in topo.all_files():
        outgoing_counts[fi["id"]] = len(topo.outgoing(fi["id"]))

    candidates: list[tuple[dict, float]] = []
    for fi in topo.all_files():
        score = _score_entrypoint(fi, outgoing_counts.get(fi["id"], 0))
        if score > 0.3:  # minimum threshold
            candidates.append((fi, score))

    candidates.sort(key=lambda x: -x[1])
    return candidates[:5]  # top 5 candidates


# ---------------------------------------------------------------------------
# Primary app flow — auto-inferred, no user input required
# ---------------------------------------------------------------------------

def _flow_primary(topo: RepoTopology, hint: str, depth: int) -> dict:
    """
    Infer the primary application flow automatically.

    Strategy:
    1. Detect likely entrypoints using generic heuristics.
    2. If hint is provided, prefer the matching entrypoint.
    3. From the best entrypoint, BFS downstream through dependency edges.
    4. Build a layered flow: entrypoint → routes → services → repositories → models.
    5. Score and return with entrypoint candidates for the UI selector.
    """
    # Detect entrypoints
    candidates = _detect_entrypoints(topo)

    if not candidates:
        # No entrypoint found — fall back to the highest-outgoing-degree file
        all_files = [
            fi for fi in topo.all_files()
            if not fi.get("is_test") and not fi.get("is_generated") and not fi.get("is_vendor")
        ]
        if not all_files:
            return _empty_flow("primary", "", "No indexed source files found.")

        best = max(all_files, key=lambda fi: len(topo.outgoing(fi["id"])))
        candidates = [(best, 0.35)]

    # If hint provided, try to match it
    selected_fi, selected_conf = candidates[0]
    if hint:
        for fi, conf in candidates:
            if hint.lower() in fi["path"].lower() or fi["path"].lower().endswith(hint.lower()):
                selected_fi, selected_conf = fi, conf
                break

    # BFS downstream from entrypoint — build layered flow
    downstream = _bfs_downstream(
        topo, selected_fi["id"],
        max_depth=depth,
        max_nodes=8,
        exclude_roles={"test"},  # keep config in primary flow
    )

    if not downstream:
        downstream = [selected_fi]

    # Deduplicate and ensure entrypoint is first
    seen: set[str] = set()
    ordered: list[dict] = []
    for fi in downstream:
        if fi["id"] not in seen:
            seen.add(fi["id"])
            ordered.append(fi)

    # Build nodes and edges
    nodes = [_build_flow_node(n) for n in ordered]
    edges = []

    # Primary edges: sequential chain
    for i in range(len(ordered) - 1):
        edges.append(_build_flow_edge(ordered[i]["id"], ordered[i + 1]["id"], "calls"))

    # Also add any direct dependency edges between non-adjacent nodes
    node_id_set = {n["id"] for n in ordered}
    seen_edge_pairs: set[tuple[str, str]] = {
        (ordered[i]["id"], ordered[i + 1]["id"]) for i in range(len(ordered) - 1)
    }
    for fi in ordered:
        for edge in topo.outgoing(fi["id"]):
            tgt = edge.get("target")
            if tgt and tgt in node_id_set and tgt != fi["id"]:
                pair = (fi["id"], tgt)
                if pair not in seen_edge_pairs:
                    seen_edge_pairs.add(pair)
                    edges.append(_build_flow_edge(fi["id"], tgt, edge.get("type", "depends_on")))

    score = _score_path(nodes) * selected_conf
    role_chain = " → ".join(
        dict.fromkeys(  # deduplicate preserving order
            _node_type_label(n.get("role", "unknown")) for n in ordered
        )
    )
    explanation = (
        f"Primary flow from {selected_fi['name']} "
        f"({role_chain}). "
        f"Entrypoint confidence: {int(selected_conf * 100)}%."
    )

    path = {
        "id": "path_1",
        "score": round(score, 2),
        "explanation": explanation,
        "nodes": nodes,
        "edges": edges,
    }

    # Build entrypoint candidates list for UI selector
    entrypoint_candidates = [
        {
            "path": fi["path"],
            "name": fi["name"],
            "confidence": conf,
            "role": fi.get("role", "unknown"),
            "language": fi.get("language"),
        }
        for fi, conf in candidates[:5]
    ]

    notes = [
        f"Auto-detected entrypoint: {selected_fi['path']} ({int(selected_conf * 100)}% confidence).",
    ]
    if len(candidates) > 1:
        others = [fi["name"] for fi, _ in candidates[1:3]]
        notes.append(f"Other candidates: {', '.join(others)}.")

    result = _wrap_result("primary", selected_fi["path"], [path], notes=notes)
    result["entrypoint_candidates"] = entrypoint_candidates
    result["selected_entrypoint"] = selected_fi["path"]
    return result


def _flow_impact(topo: RepoTopology, changed_paths: list[str], depth: int) -> dict:
    """Show workflows affected by changed files."""
    changed_ids: set[str] = set()
    not_found: list[str] = []

    for cp in changed_paths:
        fi = topo.file_by_path(cp)
        if fi:
            changed_ids.add(fi["id"])
        else:
            not_found.append(cp)

    if not changed_ids:
        return _empty_flow("impact", ",".join(changed_paths),
                           f"None of the changed files found in indexed repository: {', '.join(not_found[:3])}")

    # BFS: find all files impacted by the changed set
    reverse_adj: dict[str, set[str]] = defaultdict(set)
    for fi in topo.all_files():
        for edge in topo.outgoing(fi["id"]):
            tgt = edge.get("target")
            if tgt:
                reverse_adj[tgt].add(fi["id"])

    impacted_ids: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(fid, 0) for fid in changed_ids])
    visited: set[str] = set(changed_ids)

    while queue:
        fid, d = queue.popleft()
        if d >= depth:
            continue
        for dep in reverse_adj.get(fid, set()):
            if dep not in visited:
                visited.add(dep)
                impacted_ids.add(dep)
                queue.append((dep, d + 1))

    # Build a combined path: changed files + top impacted
    all_relevant = list(changed_ids) + [fid for fid in impacted_ids if fid not in changed_ids]
    all_relevant = all_relevant[:12]

    nodes = []
    for fid in all_relevant:
        fi = topo.file_info(fid)
        if fi:
            nodes.append(_build_flow_node(fi,
                                          changed=fid in changed_ids,
                                          impacted=fid in impacted_ids and fid not in changed_ids))

    edges = []
    node_id_set = {n["path"] for n in nodes}
    seen_edges: set[tuple[str, str]] = set()
    for fid in all_relevant:
        for edge in topo.outgoing(fid):
            tgt = edge.get("target")
            if tgt and tgt in {n["id"].replace("fn_", "") for n in nodes}:
                key = (fid, tgt)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(_build_flow_edge(fid, tgt, "impacts"))

    score = 0.75 if impacted_ids else 0.5
    explanation = (
        f"{len(changed_ids)} changed file(s) → "
        f"{len(impacted_ids)} impacted file(s) via dependency graph."
    )

    path = {
        "id": "path_1",
        "score": score,
        "explanation": explanation,
        "nodes": nodes,
        "edges": edges,
    }

    notes = [f"Changed: {', '.join(changed_paths[:3])}"]
    if not_found:
        notes.append(f"Not found in index: {', '.join(not_found[:3])}")
    if not impacted_ids:
        notes.append("No downstream dependents found. Graph may be sparse — re-index to improve.")

    return _wrap_result("impact", ",".join(changed_paths), [path], notes=notes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_flow(mode: str, query: str, reason: str) -> dict:
    return {
        "mode": mode,
        "query": query,
        "summary": {
            "entrypoint": query,
            "estimated_confidence": 0.0,
            "path_count": 0,
            "notes": [reason],
        },
        "paths": [],
    }


def _wrap_result(mode: str, query: str, paths: list[dict], notes: list[str] | None = None) -> dict:
    top_score = max((p["score"] for p in paths), default=0.0)
    return {
        "mode": mode,
        "query": query,
        "summary": {
            "entrypoint": query,
            "estimated_confidence": top_score,
            "path_count": len(paths),
            "notes": notes or [],
        },
        "paths": paths[:3],  # cap at 3 paths
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

class FlowService:
    def __init__(self, db: Session):
        self.db = db

    def get_flow(
        self,
        repository_id: str,
        mode: str,
        query: str = "",
        changed: str = "",
        depth: int = 4,
    ) -> dict:
        """
        Main entry point for flow inference.
        Never raises — always returns a valid dict.
        """
        try:
            topo = RepoTopology(self.db, repository_id)
            topo.load()

            if not topo.all_files():
                return _empty_flow(mode, query or changed, "Repository has no indexed files.")

            depth = max(1, min(depth, 6))

            if mode == "route":
                return _flow_route(topo, query, depth)
            elif mode == "file":
                return _flow_file(topo, query, depth)
            elif mode == "function":
                return _flow_function(topo, query, depth)
            elif mode == "impact":
                changed_paths = [p.strip() for p in changed.split(",") if p.strip()]
                if not changed_paths:
                    return _empty_flow("impact", changed, "No changed file paths provided.")
                return _flow_impact(topo, changed_paths, depth)
            elif mode == "primary":
                return _flow_primary(topo, query, depth)
            else:
                return _empty_flow(mode, query, f"Unknown mode: {mode}")

        except Exception as e:
            logger.error(f"FlowService.get_flow failed: {e}", exc_info=True)
            return _empty_flow(mode, query or changed, f"Internal error: {type(e).__name__}")

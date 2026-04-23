from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from collections import defaultdict
from typing import Optional

from app.api.deps import get_db
from app.db.models.dependency_edge import DependencyEdge
from app.db.models.file import File
from app.services.graph_service import compute_inferred_edges
from app.services.job_service import JobService
from app.services.repository_service import RepositoryService

router = APIRouter(tags=["graph"])

_GRAPH_UNAVAILABLE = (
    "Graph service is unavailable in this environment "
    "(neo4j package not installed or neo4j server unreachable). "
    "Non-graph features continue to work normally."
)

# Sparsity threshold: if resolved_edges / files < this, run fallback inference
_SPARSITY_THRESHOLD = 0.15


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cluster_id_from_path(path: str, depth: int = 2) -> str:
    """Derive a stable cluster ID from a file path by taking the first `depth` segments."""
    parts = path.split("/")
    if len(parts) <= 1:
        return "root"
    return "/".join(parts[:depth])


def _risk_color(risk_score: float) -> str:
    if risk_score >= 70:
        return "high"
    if risk_score >= 40:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Multi-mode graph endpoint  GET /repos/{repo_id}/graph
# ---------------------------------------------------------------------------

@router.get("/repos/{repo_id}/graph")
def get_repo_knowledge_graph(
    repo_id: str,
    view: str = Query(default="clusters", regex="^(clusters|files|hotspots|impact)$"),
    changed: Optional[str] = Query(default=None, description="Comma-separated changed file paths for impact mode"),
    max_nodes: int = Query(default=80, ge=1, le=300),
    edge_types: str = Query(default="import,from_import,call,require,export"),
    db: Session = Depends(get_db),
):
    """
    Multi-mode repository knowledge graph.

    Modes:
    - clusters  (default): folder-based cluster nodes with aggregated edges
    - files:    individual file nodes with dependency edges
    - hotspots: same as files but nodes carry risk_score for color mapping
    - impact:   same as files but marks changed + impacted nodes
    """
    repository_service = RepositoryService(db)
    repo = repository_service.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    requested_types = [t.strip() for t in edge_types.split(",") if t.strip()]

    # ── Load all files ───────────────────────────────────────────────────────
    all_files = list(db.execute(
        select(
            File.id, File.path, File.language, File.file_kind,
            File.line_count, File.is_generated, File.is_vendor, File.is_test,
        ).where(File.repository_id == repo_id)
    ).all())

    if not all_files:
        return _empty_graph(repo_id, view)

    file_map = {row[0]: row for row in all_files}  # id → row

    # ── Load resolved edges ──────────────────────────────────────────────────
    raw_edges = list(db.execute(
        select(
            DependencyEdge.source_file_id,
            DependencyEdge.target_file_id,
            DependencyEdge.edge_type,
        ).where(
            DependencyEdge.repository_id == repo_id,
            DependencyEdge.target_file_id.isnot(None),
            DependencyEdge.source_file_id.isnot(None),
            DependencyEdge.edge_type.in_(requested_types),
        )
    ).all())

    # ── Fallback: infer edges when graph is sparse ───────────────────────────
    # If resolved edge density is below threshold, derive additional inferred
    # edges from import statements, imports_list field, and naming heuristics.
    # Inferred edges are marked with edge_type="inferred" or "inferred_naming"
    # and are never persisted to the database.
    inferred_edges: list[tuple[str, str, str]] = []
    try:
        inferred_edges = compute_inferred_edges(
            db=db,
            repository_id=repo_id,
            resolved_edges=[(s, t, e) for s, t, e in raw_edges],
            all_files=all_files,
            sparsity_threshold=_SPARSITY_THRESHOLD,
        )
    except Exception:
        pass  # always degrade gracefully

    # Merge: resolved edges first, then inferred (deduplication by (src, tgt))
    all_edges = list(raw_edges)
    if inferred_edges:
        resolved_pairs = {(s, t) for s, t, _ in raw_edges}
        for s, t, e in inferred_edges:
            if (s, t) not in resolved_pairs and s in {r[0] for r in all_files} and t in {r[0] for r in all_files}:
                all_edges.append((s, t, e))
                resolved_pairs.add((s, t))

    # ── Load risk scores (for hotspot + impact modes) ────────────────────────
    risk_map: dict[str, float] = {}
    if view in ("hotspots", "impact"):
        try:
            from app.services.risk_service import RiskService
            rs = RiskService(db)
            for item in rs.get_hotspots(repo_id, limit=10000):
                risk_map[item["file_id"]] = item["risk_score"]
        except Exception:
            pass  # degrade gracefully

    # ── Parse changed files for impact mode ──────────────────────────────────
    changed_paths: set[str] = set()
    impacted_ids: set[str] = set()
    if view == "impact" and changed:
        changed_paths = {p.strip() for p in changed.split(",") if p.strip()}
        # Map paths to file IDs
        path_to_id = {row[1]: row[0] for row in all_files}
        changed_ids: set[str] = set()
        for cp in changed_paths:
            fid = path_to_id.get(cp)
            if fid:
                changed_ids.add(fid)
        # BFS 1-hop impact
        reverse_adj: dict[str, set[str]] = defaultdict(set)
        for src, tgt, _ in all_edges:
            if src != tgt:
                reverse_adj[tgt].add(src)
        for cid in changed_ids:
            for dep in reverse_adj.get(cid, set()):
                impacted_ids.add(dep)
        impacted_ids -= changed_ids  # don't double-mark

    # ── Dispatch to view builder ─────────────────────────────────────────────
    n_resolved = len(raw_edges)
    n_inferred = len(inferred_edges)

    if view == "clusters":
        return _build_cluster_graph(repo_id, all_files, all_edges, max_nodes, n_resolved, n_inferred)
    else:
        return _build_file_graph(
            repo_id, view, all_files, file_map, all_edges,
            risk_map, changed_paths, impacted_ids, max_nodes, n_resolved, n_inferred,
        )


def _empty_graph(repo_id: str, view: str) -> dict:
    return {
        "view": view,
        "repo_id": repo_id,
        "nodes": [],
        "edges": [],
        "legend": _legend(view),
        "total_files": 0,
        "total_resolved_edges": 0,
        "truncated": False,
    }


def _legend(view: str) -> dict:
    if view == "hotspots":
        return {"red": "high risk (≥70)", "orange": "medium risk (40–70)", "green": "low risk (<40)"}
    if view == "impact":
        return {"red": "directly changed", "orange": "impacted (1-hop)", "blue": "unaffected"}
    return {"indigo": "source", "amber": "test", "emerald": "config", "slate": "generated/vendor"}


# ---------------------------------------------------------------------------
# Cluster view builder
# ---------------------------------------------------------------------------

def _build_cluster_graph(
    repo_id: str,
    all_files: list,
    raw_edges: list,
    max_nodes: int,
    n_resolved: int = 0,
    n_inferred: int = 0,
) -> dict:
    """
    Aggregate files into folder-based clusters.
    Cluster ID = first 2 path segments (e.g. "app/services").
    Edges = aggregated inter-cluster dependency counts.
    Inferred edges are included and marked in edge metadata.
    """
    # Build set of inferred edge types for metadata tagging
    _INFERRED_TYPES = {"inferred", "inferred_naming"}

    # Map file_id → cluster_id
    file_to_cluster: dict[str, str] = {}
    cluster_files: dict[str, list] = defaultdict(list)

    for fid, path, lang, kind, lc, is_gen, is_vendor, is_test in all_files:
        cid = _cluster_id_from_path(path, depth=2)
        file_to_cluster[fid] = cid
        cluster_files[cid].append({
            "id": fid, "path": path, "language": lang,
            "file_kind": kind, "line_count": lc or 0,
            "is_generated": bool(is_gen), "is_vendor": bool(is_vendor), "is_test": bool(is_test),
        })

    # Aggregate edges between clusters
    # Track whether any edge in a cluster pair is resolved vs inferred
    cluster_edge_agg: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "resolved": 0, "inferred": 0}
    )
    for src_fid, tgt_fid, etype in raw_edges:
        src_c = file_to_cluster.get(src_fid)
        tgt_c = file_to_cluster.get(tgt_fid)
        if src_c and tgt_c and src_c != tgt_c:
            agg = cluster_edge_agg[(src_c, tgt_c)]
            agg["count"] += 1
            if etype in _INFERRED_TYPES:
                agg["inferred"] += 1
            else:
                agg["resolved"] += 1

    # Compute cluster degree
    cluster_degree: dict[str, int] = defaultdict(int)
    for (sc, tc), agg in cluster_edge_agg.items():
        cluster_degree[sc] += agg["count"]
        cluster_degree[tc] += agg["count"]

    # Select top clusters by degree + file count
    all_cluster_ids = list(cluster_files.keys())
    if len(all_cluster_ids) > max_nodes:
        all_cluster_ids = sorted(
            all_cluster_ids,
            key=lambda c: -(cluster_degree.get(c, 0) + len(cluster_files[c]))
        )[:max_nodes]
    cluster_set = set(all_cluster_ids)

    # Build nodes
    nodes = []
    for cid in all_cluster_ids:
        files_in = cluster_files[cid]
        file_count = len(files_in)
        # Infer dominant language
        langs = [f["language"] for f in files_in if f["language"]]
        dominant_lang = max(set(langs), key=langs.count) if langs else None
        # Infer kind
        kinds = [f["file_kind"] for f in files_in if f["file_kind"]]
        dominant_kind = max(set(kinds), key=kinds.count) if kinds else "source"

        nodes.append({
            "id": cid,
            "type": "cluster",
            "label": cid.split("/")[-1] or cid,
            "path": cid,
            "cluster_id": None,
            "risk_score": 0.0,
            "size": file_count,
            "degree": cluster_degree.get(cid, 0),
            "language": dominant_lang,
            "file_kind": dominant_kind,
            "meta": {
                "file_count": file_count,
                "changed": False,
                "impacted": False,
            },
        })

    # Build edges
    edges = []
    edge_idx = 0
    for (sc, tc), agg in cluster_edge_agg.items():
        if sc in cluster_set and tc in cluster_set:
            is_inferred_only = agg["resolved"] == 0 and agg["inferred"] > 0
            edges.append({
                "id": f"ce_{edge_idx}",
                "source": sc,
                "target": tc,
                "type": "inferred" if is_inferred_only else "depends_on",
                "edge_type": "inferred" if is_inferred_only else "depends_on",
                "weight": agg["count"],
                "count": agg["count"],
                "meta": {
                    "resolved_count": agg["resolved"],
                    "inferred_count": agg["inferred"],
                    "is_inferred": is_inferred_only,
                },
            })
            edge_idx += 1

    total_files = len(all_files)

    return {
        "view": "clusters",
        "repo_id": repo_id,
        "nodes": nodes,
        "edges": edges,
        "legend": _legend("clusters"),
        "total_files": total_files,
        "total_resolved_edges": n_resolved,
        "total_inferred_edges": n_inferred,
        "truncated": len(cluster_set) < len(cluster_files),
    }


# ---------------------------------------------------------------------------
# File / hotspot / impact view builder
# ---------------------------------------------------------------------------

def _build_file_graph(
    repo_id: str,
    view: str,
    all_files: list,
    file_map: dict,
    raw_edges: list,
    risk_map: dict[str, float],
    changed_paths: set[str],
    impacted_ids: set[str],
    max_nodes: int,
    n_resolved: int = 0,
    n_inferred: int = 0,
) -> dict:
    """Build a file-level graph for files/hotspots/impact views.

    For sparse graphs: prioritizes connected files over isolated ones.
    Inferred edges are tagged in metadata so the UI can style them differently.
    """
    _INFERRED_TYPES = {"inferred", "inferred_naming"}

    # Aggregate edges — track resolved vs inferred per (src, tgt) pair
    edge_agg: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "types": set(), "resolved": 0, "inferred": 0}
    )
    for src, tgt, etype in raw_edges:
        if src != tgt:
            agg = edge_agg[(src, tgt)]
            agg["count"] += 1
            agg["types"].add(etype)
            if etype in _INFERRED_TYPES:
                agg["inferred"] += 1
            else:
                agg["resolved"] += 1

    # Compute degree (all edges, resolved + inferred)
    degree: dict[str, int] = defaultdict(int)
    for (src, tgt), agg in edge_agg.items():
        degree[src] += agg["count"]
        degree[tgt] += agg["count"]

    # For impact mode: always include changed + impacted files
    path_to_id = {row[1]: row[0] for row in all_files}
    changed_ids = {path_to_id[p] for p in changed_paths if p in path_to_id}
    priority_ids = changed_ids | impacted_ids

    # Select file IDs — prefer connected files over isolated ones
    all_ids = set(degree.keys())  # files with at least one edge

    # Also include isolated files up to budget (for completeness)
    all_file_ids = {row[0] for row in all_files}
    isolated_ids = all_file_ids - all_ids

    if view == "impact" and priority_ids:
        # Ensure changed/impacted are included
        remaining_connected = sorted(all_ids - priority_ids, key=lambda fid: -degree.get(fid, 0))
        selected_ids = priority_ids | set(remaining_connected[:max(0, max_nodes - len(priority_ids))])
    elif len(all_ids) >= max_nodes:
        # Enough connected files — use top by degree
        selected_ids = set(sorted(all_ids, key=lambda fid: -degree.get(fid, 0))[:max_nodes])
    else:
        # Fill remaining budget with isolated files (sorted by path for stability)
        budget_left = max_nodes - len(all_ids)
        selected_ids = all_ids | set(
            sorted(isolated_ids, key=lambda fid: file_map.get(fid, ("", ""))[1])[:budget_left]
        )

    if not selected_ids:
        return _empty_graph(repo_id, view)

    # Build nodes
    nodes = []
    for fid in selected_ids:
        row = file_map.get(fid)
        if not row:
            continue
        fid_, path, lang, kind, lc, is_gen, is_vendor, is_test = row
        parts = path.split("/")
        name = parts[-1]
        folder = "/".join(parts[:-1]) if len(parts) > 1 else ""
        risk_score = risk_map.get(fid_, 0.0)
        is_changed = fid_ in changed_ids
        is_impacted = fid_ in impacted_ids

        nodes.append({
            "id": fid_,
            "type": "file",
            "label": name,
            "path": path,
            "name": name,
            "folder": folder,
            "cluster_id": _cluster_id_from_path(path),
            "risk_score": round(risk_score, 2),
            "size": 1,
            "degree": degree.get(fid_, 0),
            "language": lang,
            "file_kind": kind or "source",
            "line_count": lc or 0,
            "is_generated": bool(is_gen),
            "is_vendor": bool(is_vendor),
            "is_test": bool(is_test),
            "meta": {
                "file_count": 1,
                "changed": is_changed,
                "impacted": is_impacted,
            },
        })

    # Build edges — include resolved and inferred, tag each
    edges = []
    edge_type_counts: dict[str, int] = defaultdict(int)
    for (src, tgt), agg in edge_agg.items():
        if src in selected_ids and tgt in selected_ids:
            # Pick the primary edge type (prefer resolved over inferred)
            resolved_types = [t for t in agg["types"] if t not in _INFERRED_TYPES]
            inferred_types = [t for t in agg["types"] if t in _INFERRED_TYPES]
            primary_type = resolved_types[0] if resolved_types else (inferred_types[0] if inferred_types else "depends_on")
            is_inferred = agg["resolved"] == 0

            edges.append({
                "id": f"{src}_{tgt}_{primary_type}",
                "source": src,
                "target": tgt,
                "type": primary_type,
                "edge_type": primary_type,
                "weight": agg["count"],
                "count": agg["count"],
                "meta": {
                    "is_inferred": is_inferred,
                    "resolved_count": agg["resolved"],
                    "inferred_count": agg["inferred"],
                    "all_types": list(agg["types"]),
                },
            })
            edge_type_counts[primary_type] += 1

    return {
        "view": view,
        "repo_id": repo_id,
        "nodes": nodes,
        "edges": edges,
        "legend": _legend(view),
        "edge_type_counts": dict(edge_type_counts),
        "total_files": len(all_files),
        "total_resolved_edges": n_resolved,
        "total_inferred_edges": n_inferred,
        "truncated": len(selected_ids) < len(all_file_ids),
    }


# ---------------------------------------------------------------------------
# SQL-backed graph data endpoint (legacy — kept for RepoGraphCanvas)
# ---------------------------------------------------------------------------

@router.get("/repos/{repo_id}/graph/data")
def get_repo_graph_data(
    repo_id: str,
    edge_types: str = Query(default="import,from_import,call,require,export"),
    max_nodes: int = Query(default=120, ge=1, le=500),
    min_degree: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Return a bounded file-relationship graph for the repository.

    Only includes edges where target_file_id is resolved (local file-to-file).
    Aggregates multiple edges between the same source/target into one edge with a count.
    Bounds the graph to max_nodes by selecting the highest-degree files.
    """
    repository_service = RepositoryService(db)
    repo = repository_service.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    requested_types = [t.strip() for t in edge_types.split(",") if t.strip()]

    # ── Fetch all resolved edges for this repo ───────────────────────────────
    raw_edges = list(db.execute(
        select(
            DependencyEdge.source_file_id,
            DependencyEdge.target_file_id,
            DependencyEdge.edge_type,
        ).where(
            DependencyEdge.repository_id == repo_id,
            DependencyEdge.target_file_id.isnot(None),
            DependencyEdge.source_file_id.isnot(None),
            DependencyEdge.edge_type.in_(requested_types),
        )
    ).all())

    # ── Aggregate edges: (src, tgt, type) → count ───────────────────────────
    edge_agg: dict[tuple[str, str, str], int] = defaultdict(int)
    for src, tgt, etype in raw_edges:
        if src != tgt:  # skip self-loops
            edge_agg[(src, tgt, etype)] += 1

    # ── Compute degree per file ──────────────────────────────────────────────
    degree: dict[str, int] = defaultdict(int)
    for (src, tgt, _), cnt in edge_agg.items():
        degree[src] += cnt
        degree[tgt] += cnt

    # ── Collect all file IDs involved ────────────────────────────────────────
    all_file_ids: set[str] = set()
    for src, tgt, _ in edge_agg:
        all_file_ids.add(src)
        all_file_ids.add(tgt)

    # ── Apply min_degree filter ──────────────────────────────────────────────
    if min_degree > 0:
        all_file_ids = {fid for fid in all_file_ids if degree.get(fid, 0) >= min_degree}

    # ── Bound to max_nodes by highest degree ─────────────────────────────────
    if len(all_file_ids) > max_nodes:
        all_file_ids = set(
            sorted(all_file_ids, key=lambda fid: -degree.get(fid, 0))[:max_nodes]
        )

    if not all_file_ids:
        return {
            "nodes": [],
            "edges": [],
            "total_files": 0,
            "total_resolved_edges": 0,
            "edge_type_counts": {},
            "truncated": False,
        }

    # ── Fetch file metadata ──────────────────────────────────────────────────
    file_rows = list(db.execute(
        select(
            File.id,
            File.path,
            File.language,
            File.file_kind,
            File.line_count,
            File.is_generated,
            File.is_vendor,
            File.is_test,
        ).where(
            File.repository_id == repo_id,
            File.id.in_(list(all_file_ids)),
        )
    ).all())

    file_map = {row[0]: row for row in file_rows}

    # ── Build nodes ──────────────────────────────────────────────────────────
    nodes = []
    for fid in all_file_ids:
        row = file_map.get(fid)
        if not row:
            continue
        fid_, path, lang, kind, line_count, is_gen, is_vendor, is_test = row
        # Derive display name and folder
        parts = path.split("/")
        name = parts[-1]
        folder = "/".join(parts[:-1]) if len(parts) > 1 else ""

        nodes.append({
            "id": fid_,
            "path": path,
            "name": name,
            "folder": folder,
            "language": lang,
            "file_kind": kind or "source",
            "line_count": line_count or 0,
            "is_generated": bool(is_gen),
            "is_vendor": bool(is_vendor),
            "is_test": bool(is_test),
            "degree": degree.get(fid_, 0),
        })

    # ── Build edges (only between included nodes) ────────────────────────────
    edges = []
    edge_type_counts: dict[str, int] = defaultdict(int)
    for (src, tgt, etype), cnt in edge_agg.items():
        if src in all_file_ids and tgt in all_file_ids:
            edges.append({
                "id": f"{src}_{tgt}_{etype}",
                "source": src,
                "target": tgt,
                "edge_type": etype,
                "count": cnt,
            })
            edge_type_counts[etype] += 1

    # ── Total counts for context ─────────────────────────────────────────────
    total_files = db.scalar(
        select(func.count(File.id)).where(File.repository_id == repo_id)
    ) or 0
    total_resolved = db.scalar(
        select(func.count(DependencyEdge.id)).where(
            DependencyEdge.repository_id == repo_id,
            DependencyEdge.target_file_id.isnot(None),
        )
    ) or 0

    return {
        "nodes": nodes,
        "edges": edges,
        "total_files": total_files,
        "total_resolved_edges": total_resolved,
        "edge_type_counts": dict(edge_type_counts),
        "truncated": len(all_file_ids) < len(degree),
    }


# ---------------------------------------------------------------------------
# Legacy Neo4j endpoints (kept for backward compat, return 503 gracefully)
# ---------------------------------------------------------------------------

@router.post("/repos/{repo_id}/graph/sync", status_code=status.HTTP_202_ACCEPTED)
def trigger_graph_sync(
    repo_id: str,
    db: Session = Depends(get_db),
):
    repository_service = RepositoryService(db)
    repository = repository_service.get_repository(repo_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")

    job_service = JobService(db)
    try:
        from app.workers.tasks_graph import sync_repository_graph
        job = job_service.create_job(
            repository_id=repo_id,
            job_type="sync_repository_graph",
            status="queued",
            message="Graph sync queued",
        )
        task = sync_repository_graph.delay(repo_id, job.id)
        job_service.update_task_id(job.id, task.id)
    except (RuntimeError, ImportError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_GRAPH_UNAVAILABLE,
        )

    return {
        "message": "Graph sync started",
        "repository_id": repo_id,
        "job_id": job.id,
        "task_id": task.id,
    }


@router.get("/repos/{repo_id}/graph/summary")
def get_graph_summary(
    repo_id: str,
    db: Session = Depends(get_db),
):
    repository_service = RepositoryService(db)
    repository = repository_service.get_repository(repo_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        from app.graph.graph_service import GraphService as Neo4jGraphService
        graph_service = Neo4jGraphService(db)
        summary = graph_service.get_repository_graph_summary(repo_id)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_GRAPH_UNAVAILABLE,
        )

    return summary

from __future__ import annotations

import logging
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.file import File
from app.schemas.repository import RepoCreateRequest, RepoListResponse, RepoResponse
from app.services.job_service import JobService
from app.services.repository_service import RepositoryService
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def _dispatch_repo_indexing(repo_id: str, job_id: str):
    """Background task to dispatch Celery worker without blocking the HTTP response."""
    db = SessionLocal()
    try:
        from app.workers.tasks_ingest import index_repository
        from app.workers.celery_app import dispatch_task
        task = dispatch_task(index_repository, repo_id, job_id)
        
        job_service = JobService(db)
        job_service.update_task_id(job_id, task.id)
    except Exception as e:
        logger.warning(f"Could not enqueue indexing task: {e}")
    finally:
        db.close()


def _get_languages_used(db: Session, repo_id: str) -> list[str]:
    """Return languages used in the repository, sorted by file count descending.
    Only counts files with a non-null, non-empty language field.
    Result is deterministic and entirely data-driven from indexed files.
    """
    rows = db.execute(
        select(File.language).where(
            File.repository_id == repo_id,
            File.language.isnot(None),
            File.language != "",
        )
    ).scalars().all()
    counts = Counter(lang.strip() for lang in rows if lang and lang.strip())
    # Return sorted by count desc, alphabetical for ties
    return [lang for lang, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


router = APIRouter(prefix="/repos", tags=["repos"])


@router.post("", response_model=RepoResponse, status_code=status.HTTP_201_CREATED)
def create_repo(payload: RepoCreateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    repository_service = RepositoryService(db)
    job_service = JobService(db)

    try:
        repo = repository_service.create_repository(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Failed to persist repository")
        raise HTTPException(status_code=500, detail={"message": "Failed to create repository", "error": str(e)})

    # Trigger initial indexing task
    try:
        job = job_service.create_job(
            repository_id=repo.id,
            job_type="index_repository",
            status="queued",
            message="Repository indexing queued",
        )
        background_tasks.add_task(_dispatch_repo_indexing, repo.id, job.id)
    except Exception as e:
        logger.warning(f"Could not enqueue indexing task: {e}")

    return repo


@router.get("", response_model=RepoListResponse)
def get_repos(db: Session = Depends(get_db)):
    repository_service = RepositoryService(db)
    repos = repository_service.list_repositories()
    
    items = []
    for repo in repos:
        full_name = getattr(repo, "full_name", "") or ""
        owner = full_name.split("/")[0] if "/" in full_name else "unknown"
        items.append(RepoResponse(
            id=repo.id,
            repo_url=repo.repo_url,
            name=repo.name,
            owner=owner,
            default_branch=repo.default_branch or "main",
            local_path=getattr(repo, "local_path", None),
            status=repo.status,
            primary_language=getattr(repo, "primary_language", "unknown"),
            framework=getattr(repo, "detected_frameworks", "none"),
            languages_used=_get_languages_used(db, repo.id),
            created_at=repo.created_at,
        ))
        
    return RepoListResponse(items=items, total=len(items))


@router.get("/{repo_id}", response_model=RepoResponse)
def get_repo(repo_id: str, db: Session = Depends(get_db)):
    repository_service = RepositoryService(db)
    repo = repository_service.get_repository(repo_id)

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    full_name = getattr(repo, "full_name", "") or ""
    owner = full_name.split("/")[0] if "/" in full_name else "unknown"
    return RepoResponse(
        id=repo.id,
        repo_url=repo.repo_url,
        name=repo.name,
        owner=owner,
        default_branch=repo.default_branch or "main",
        local_path=getattr(repo, "local_path", None),
        status=repo.status,
        primary_language=getattr(repo, "primary_language", "unknown"),
        framework=getattr(repo, "detected_frameworks", "none"),
        languages_used=_get_languages_used(db, repo_id),
        created_at=repo.created_at,
    )


@router.post("/{repo_id}/parse", status_code=status.HTTP_202_ACCEPTED)
def parse_repo(repo_id: str, db: Session = Depends(get_db)):
    repository_service = RepositoryService(db)
    # FIX: job_service was used but never instantiated — was `name 'job_service' is not defined`
    job_service = JobService(db)

    repo = repository_service.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        from app.workers.tasks_parse import parse_repository_semantics
        from app.workers.celery_app import dispatch_task

        # Create job FIRST before setting status, so job record exists even if dispatch fails
        job = job_service.create_job(
            repository_id=repo_id,
            job_type="parse_repository_semantics",
            status="queued",
            message="Semantic parsing queued",
        )

        repo.status = "parsing"
        db.commit()

        task = dispatch_task(parse_repository_semantics, repo_id, job.id)
        job_service.update_task_id(job.id, task.id)

        return {
            "job_id": job.id,
            "task_id": str(task.id),
            "repo_id": repo_id,
            "status": "queued",
            "message": "Repository parse job triggered.",
        }
    except Exception as e:
        logger.error(f"Could not enqueue parse task: {e}", exc_info=True)
        # Try to recover status if job creation failed
        try:
            repo.status = "failed"
            db.commit()
        except Exception:
            pass
        raise HTTPException(status_code=503, detail=f"Task broker unavailable: {e}")


# ---------------------------------------------------------------------------
# Canonical file intelligence endpoint
# ---------------------------------------------------------------------------
# Returns per-file intelligence metadata: role, importance, connectivity,
# symbol counts, and graph signals. Used by Files, Search, Overview, Graph.
# All logic is generic — no repo-specific hardcoding.
# ---------------------------------------------------------------------------

_ROLE_PRIORITY: dict[str, int] = {
    "entrypoint": 0, "route": 1, "service": 2, "repository": 3,
    "model": 4, "schema": 4, "frontend": 5, "api_client": 5,
    "config": 6, "integration": 6, "middleware": 7, "worker": 7,
    "utility": 8, "test": 9, "unknown": 10,
}

_SEMANTIC_EDGE_TYPES = frozenset({
    "route_to_service", "service_to_model", "uses_symbol", "inferred_api",
})


def _classify_file_role_server(
    path: str,
    file_kind: str,
    is_test: bool,
    is_generated: bool,
    is_vendor: bool,
    inbound: int,
    outbound: int,
    symbol_count: int,
    semantic_edges: int,
) -> tuple[str, float]:
    """
    Classify a file's architectural role using server-side evidence.
    Returns (role, confidence) where confidence is 0.0–1.0.
    Generic — no repo-specific hardcoding.
    """
    p = path.lower().replace("\\", "/")
    parts = p.split("/")
    stem = parts[-1].rsplit(".", 1)[0] if "." in parts[-1] else parts[-1]
    ext = "." + parts[-1].rsplit(".", 1)[1] if "." in parts[-1] else ""

    # Hard overrides from flags
    if is_test or any(t in p for t in ("/test/", "/tests/", "/spec/", "/specs/")):
        return "test", 0.95
    if is_generated or is_vendor:
        return "unknown", 0.5

    # Entrypoint: shallow path + canonical stem + high outgoing
    _EP_STEMS = {"app", "main", "server", "index", "manage", "wsgi", "asgi", "run", "start", "bootstrap"}
    if stem in _EP_STEMS and len(parts) <= 3 and outbound >= 2:
        conf = 0.9 + min(0.09, outbound * 0.01)
        return "entrypoint", round(min(conf, 0.99), 2)

    # Path-based role detection (ordered by specificity)
    _PATH_ROLES: list[tuple[str, str, float]] = [
        # (pattern, role, base_confidence)
        (r"/(route|routes|router|controller|controllers|handler|handlers|endpoint|endpoints|view|views|api)/", "route", 0.88),
        (r"/(service|services|usecase|use_case|manager|business)/", "service", 0.88),
        (r"/(repo|repository|repositories|dao|store|crud|database|db)/", "repository", 0.85),
        (r"/(schema|schemas)/", "schema", 0.87),
        (r"/(model|models|entity|entities|orm)/", "model", 0.85),
        (r"/(frontend|client|ui|web|pages|components|views|scripts|static)/", "frontend", 0.82),
        (r"/(config|settings|configuration|env|constants)/", "config", 0.85),
        (r"/(middleware|interceptor|guard)/", "middleware", 0.85),
        (r"/(worker|task|job|queue|celery|background)/", "worker", 0.85),
        (r"/(integration|integrations|external|third_party)/", "integration", 0.82),
        (r"/(util|utils|helper|helpers|common|shared|lib|libs)/", "utility", 0.80),
    ]

    import re as _re
    for pattern, role, base_conf in _PATH_ROLES:
        if _re.search(pattern, p):
            # Boost confidence with semantic evidence
            conf = base_conf
            if semantic_edges > 0:
                conf = min(conf + 0.05, 0.97)
            if symbol_count > 3:
                conf = min(conf + 0.02, 0.97)
            return role, round(conf, 2)

    # Stem-based fallback
    _STEM_ROLES: list[tuple[set[str], str, float]] = [
        ({"app", "main", "server", "index", "manage", "wsgi", "asgi"}, "entrypoint", 0.75),
        ({"route", "router", "routes", "controller", "handler", "endpoint", "view"}, "route", 0.78),
        ({"service", "services", "usecase", "manager"}, "service", 0.78),
        ({"repo", "repository", "dao", "store", "crud"}, "repository", 0.75),
        ({"schema", "schemas"}, "schema", 0.78),
        ({"model", "models", "entity"}, "model", 0.75),
        ({"config", "settings", "configuration", "constants"}, "config", 0.78),
        ({"util", "utils", "helper", "helpers", "common", "shared"}, "utility", 0.72),
    ]
    for stems, role, base_conf in _STEM_ROLES:
        if stem in stems or any(stem.endswith("_" + s) or stem.startswith(s + "_") for s in stems):
            return role, base_conf

    # Frontend by extension
    if ext in (".jsx", ".tsx", ".vue", ".svelte"):
        return "frontend", 0.80

    # Fallback: use connectivity signals
    if inbound >= 5 and outbound >= 3:
        return "service", 0.55  # high connectivity = likely service
    if outbound >= 5 and inbound <= 1:
        return "entrypoint", 0.50  # high outgoing, low incoming = likely entry

    return "unknown", 0.40


@router.get("/{repo_id}/intelligence")
def get_repo_file_intelligence(
    repo_id: str,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """
    Return canonical per-file intelligence metadata for a repository.

    Provides: role, role_confidence, importance_score, connectivity signals,
    symbol counts, semantic edge counts, and graph centrality.

    Used by: Files, Search, Overview, Knowledge Graph, Execution Map.
    All logic is generic — no repo-specific hardcoding.
    Degrades gracefully when graph/symbol data is sparse.
    """
    from sqlalchemy import func as _func
    from app.db.models.dependency_edge import DependencyEdge
    from app.db.models.symbol import Symbol

    repository_service = RepositoryService(db)
    repo = repository_service.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        # ── Load files ────────────────────────────────────────────────────────
        file_rows = list(db.execute(
            select(
                File.id, File.path, File.language, File.file_kind,
                File.line_count, File.is_test, File.is_generated, File.is_vendor,
            ).where(File.repository_id == repo_id)
        ).all())

        if not file_rows:
            return {"repository_id": repo_id, "files": [], "total": 0}

        file_ids = [r[0] for r in file_rows]

        # ── Aggregate edge counts ─────────────────────────────────────────────
        inbound_counts: dict[str, int] = {}
        outbound_counts: dict[str, int] = {}
        semantic_counts: dict[str, int] = {}

        try:
            out_rows = db.execute(
                select(DependencyEdge.source_file_id, _func.count(DependencyEdge.id))
                .where(
                    DependencyEdge.repository_id == repo_id,
                    DependencyEdge.source_file_id.in_(file_ids),
                    DependencyEdge.target_file_id.isnot(None),
                )
                .group_by(DependencyEdge.source_file_id)
            ).all()
            outbound_counts = {r[0]: r[1] for r in out_rows}

            in_rows = db.execute(
                select(DependencyEdge.target_file_id, _func.count(DependencyEdge.id))
                .where(
                    DependencyEdge.repository_id == repo_id,
                    DependencyEdge.target_file_id.in_(file_ids),
                    DependencyEdge.source_file_id.isnot(None),
                )
                .group_by(DependencyEdge.target_file_id)
            ).all()
            inbound_counts = {r[0]: r[1] for r in in_rows}

            sem_rows = db.execute(
                select(DependencyEdge.source_file_id, _func.count(DependencyEdge.id))
                .where(
                    DependencyEdge.repository_id == repo_id,
                    DependencyEdge.source_file_id.in_(file_ids),
                    DependencyEdge.edge_type.in_(list(_SEMANTIC_EDGE_TYPES)),
                )
                .group_by(DependencyEdge.source_file_id)
            ).all()
            semantic_counts = {r[0]: r[1] for r in sem_rows}
        except Exception:
            pass  # degrade gracefully

        # ── Aggregate symbol counts ───────────────────────────────────────────
        symbol_counts: dict[str, int] = {}
        try:
            sym_rows = db.execute(
                select(Symbol.file_id, _func.count(Symbol.id))
                .where(Symbol.repository_id == repo_id)
                .group_by(Symbol.file_id)
            ).all()
            symbol_counts = {r[0]: r[1] for r in sym_rows}
        except Exception:
            pass

        # ── Build intelligence records ────────────────────────────────────────
        records = []
        for fid, path, lang, kind, lc, is_test, is_gen, is_vendor in file_rows:
            inbound = inbound_counts.get(fid, 0)
            outbound = outbound_counts.get(fid, 0)
            semantic = semantic_counts.get(fid, 0)
            sym_count = symbol_counts.get(fid, 0)

            role, role_conf = _classify_file_role_server(
                path=path,
                file_kind=kind or "source",
                is_test=bool(is_test),
                is_generated=bool(is_gen),
                is_vendor=bool(is_vendor),
                inbound=inbound,
                outbound=outbound,
                symbol_count=sym_count,
                semantic_edges=semantic,
            )

            # Importance score: weighted combination of connectivity + role priority
            role_pri = _ROLE_PRIORITY.get(role, 10)
            importance = (
                inbound * 4.0
                + outbound * 2.0
                + semantic * 6.0
                + sym_count * 0.5
                + max(0, (10 - role_pri) * 3.0)
            )
            importance = round(min(importance, 100.0), 1)

            records.append({
                "file_id": fid,
                "path": path,
                "name": path.split("/")[-1],
                "language": lang,
                "file_kind": kind or "source",
                "line_count": lc or 0,
                "role": role,
                "role_confidence": role_conf,
                "importance_score": importance,
                "inbound_edge_count": inbound,
                "outbound_edge_count": outbound,
                "semantic_edge_count": semantic,
                "symbol_count": sym_count,
                "is_entrypoint": role == "entrypoint",
                "is_frontend": role in ("frontend", "api_client"),
                "is_generated": bool(is_gen),
                "is_vendor": bool(is_vendor),
                "is_test": bool(is_test),
            })

        # Sort by importance descending
        records.sort(key=lambda r: -r["importance_score"])

        # Cap at limit
        return {
            "repository_id": repo_id,
            "files": records[:limit],
            "total": len(records),
        }

    except Exception as e:
        logger.error(f"get_repo_file_intelligence failed: {e}", exc_info=True)
        return {"repository_id": repo_id, "files": [], "total": 0, "error": str(e)}


@router.get("/{repo_id}/archetype")
def get_repository_archetype(
    repo_id: str,
    db: Session = Depends(get_db),
):
    """
    Detect repository archetype(s) using Universal Analysis Engine.
    
    Returns multi-label classification with confidence scoring:
    - backend_api, fullstack_web, frontend_app, java_desktop_gui, cli_tool, etc.
    - Evidence-backed scoring from paths, imports, frameworks, UI toolkits
    - Graceful degradation for sparse repositories
    
    Used by: Overview, Ask Repo, Knowledge Graph, Execution Map, PR Impact
    """
    repository_service = RepositoryService(db)
    repo = repository_service.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        from app.services.archetype_service import ArchetypeService
        
        archetype_svc = ArchetypeService(db)
        result = archetype_svc.detect_archetypes(repo_id)
        
        return {
            "repository_id": repo_id,
            **result
        }
        
    except Exception as e:
        logger.error(f"get_repository_archetype failed: {e}", exc_info=True)
        return {
            "repository_id": repo_id,
            "archetypes": [{"name": "generic_codebase", "score": 1.0, "confidence": "low", "evidence": ["Analysis failed"]}],
            "primary_archetype": "generic_codebase",
            "all_signals": {},
            "analysis_quality": "low",
            "error": str(e)
        }


@router.get("/{repo_id}/entrypoints")
def get_repository_entrypoints(
    repo_id: str,
    archetype: str = "generic_codebase",
    db: Session = Depends(get_db),
):
    """
    Detect repository entrypoints using archetype-aware logic.
    
    Returns multi-candidate results with confidence scoring:
    - Primary entrypoint (highest confidence)
    - Candidate entrypoints (alternatives)
    - Archetype-specific detection (Java main(), CLI __main__, web app.py, etc.)
    - Penalizes helper/config/db files
    
    Used by: Overview, Execution Map, Ask Repo
    """
    repository_service = RepositoryService(db)
    repo = repository_service.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        from app.services.entrypoint_service import EntrypointService
        
        entrypoint_svc = EntrypointService(db)
        result = entrypoint_svc.detect_entrypoints(repo_id, archetype=archetype)
        
        return {
            "repository_id": repo_id,
            "archetype": archetype,
            **result
        }
        
    except Exception as e:
        logger.error(f"get_repository_entrypoints failed: {e}", exc_info=True)
        return {
            "repository_id": repo_id,
            "archetype": archetype,
            "primary_entrypoint": None,
            "candidate_entrypoints": [],
            "analysis_quality": "low",
            "error": str(e)
        }


@router.get("/{repo_id}/file-roles")
def get_repository_file_roles(
    repo_id: str,
    archetype: str = "generic_codebase",
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """
    Classify all files by semantic role using Universal Analysis Engine.
    
    Returns per-file role classification:
    - entrypoint, route, service, model, ui_screen, component, config, etc.
    - Confidence scoring and evidence reasons
    - Archetype-aware classification (Java GUI screens, CLI commands, etc.)
    
    Used by: Files page, Search enrichment, Ask Repo context
    """
    repository_service = RepositoryService(db)
    repo = repository_service.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        from app.services.file_role_service import FileRoleService
        
        file_role_svc = FileRoleService(db)
        file_roles = file_role_svc.classify_file_roles(repo_id, archetype=archetype, limit=limit)
        
        # Convert to list format for API response
        results = []
        for file_id, role_data in file_roles.items():
            results.append({
                "file_id": file_id,
                **role_data
            })
        
        # Sort by confidence descending, then by role priority
        role_priority = {
            "entrypoint": 10, "route": 9, "handler": 8, "service": 7, "model": 6,
            "ui_screen": 8, "component": 7, "config": 5, "utility": 4, "unknown": 0
        }
        results.sort(key=lambda x: (-role_priority.get(x["role"], 0), -len(x.get("reasons", []))))
        
        return {
            "repository_id": repo_id,
            "archetype": archetype,
            "file_roles": results[:limit],
            "total": len(results),
        }
        
    except Exception as e:
        logger.error(f"get_repository_file_roles failed: {e}", exc_info=True)
        return {
            "repository_id": repo_id,
            "archetype": archetype,
            "file_roles": [],
            "total": 0,
            "error": str(e)
        }


@router.get("/{repo_id}/graph-health")
def get_repository_graph_health(
    repo_id: str,
    db: Session = Depends(get_db),
):
    """
    Assess dependency graph health and sparsity for a repository.
    
    Returns graph quality metrics:
    - Total files vs total edges
    - Edges per file ratio
    - Sparse graph detection
    - Edge type breakdown
    - Quality assessment and recommendations
    
    Used by: Knowledge Graph, Overview, PR Impact graceful degradation
    """
    repository_service = RepositoryService(db)
    repo = repository_service.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        from app.services.graph_service import GraphService
        
        graph_svc = GraphService(db)
        health_data = graph_svc.get_graph_health(repo_id)
        
        return {
            "repository_id": repo_id,
            **health_data
        }
        
    except Exception as e:
        logger.error(f"get_repository_graph_health failed: {e}", exc_info=True)
        return {
            "repository_id": repo_id,
            "total_files": 0,
            "total_edges": 0,
            "edges_per_file": 0.0,
            "is_sparse": True,
            "edge_types": {},
            "quality": "low",
            "recommendations": ["Graph health check failed"],
            "error": str(e)
        }

@router.get("/{repo_id}/analysis-snapshot")
def get_analysis_snapshot(
    repo_id: str,
    db: Session = Depends(get_db),
):
    """
    Get canonical universal analysis snapshot for repository.
    
    Single source of truth consumed by all product surfaces:
    - Overview, Ask Repo, Knowledge Graph, Execution Map
    - PR Impact, Search, Files pages
    
    Returns comprehensive intelligence with graceful degradation:
    - Repository archetypes with evidence
    - Multi-language analysis results
    - Entrypoint detection with confidence
    - File role classification summary
    - 3-layer graph intelligence
    - Execution flow strategy
    - Quality metrics and limitations
    
    Architecture: GitHub-grade universal platform, not one-repo demo.
    """
    repository_service = RepositoryService(db)
    repo = repository_service.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        from app.services.universal_analysis_service import UniversalAnalysisService
        
        analysis_svc = UniversalAnalysisService(db)
        snapshot = analysis_svc.get_analysis_snapshot(repo_id)
        
        return snapshot
        
    except Exception as e:
        logger.error(f"get_analysis_snapshot failed: {e}", exc_info=True)
        return {
            "repository_id": repo_id,
            "timestamp": "error",
            "version": "10.0",
            "error": str(e),
            "overall_confidence": "low",
            "weak_repo_mode": True,
            "limitations": ["Analysis snapshot generation failed"],
        }
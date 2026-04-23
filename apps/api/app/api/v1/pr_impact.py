from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.pr_impact import PRImpactRequest, PRImpactResponse
from app.services.pr_impact_service import PRImpactService
from app.services.repository_service import RepositoryService

router = APIRouter(tags=["pr-impact"])


def _run_analysis(repo_id: str, payload: PRImpactRequest, db: Session) -> PRImpactResponse:
    """Shared handler used by both endpoint paths."""
    if not payload.diff and not payload.changed_files:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of: 'diff' (unified diff text) or 'changed_files' (list of paths).",
        )

    repository_service = RepositoryService(db)
    repository = repository_service.get_repository(repo_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")

    impact_service = PRImpactService(db)
    result = impact_service.analyze_impact(
        repository_id=repo_id,
        changed_files=payload.changed_files,
        diff=payload.diff,
        notes=payload.notes,
        max_depth=payload.max_depth,
    )
    return PRImpactResponse(**result)


@router.post("/repos/{repo_id}/impact", response_model=PRImpactResponse)
def analyze_repository_pr_impact(
    repo_id: str,
    payload: PRImpactRequest,
    db: Session = Depends(get_db),
):
    """
    Graph-aware PR impact analysis (primary endpoint).
    Accepts a raw unified diff and/or explicit changed file paths.
    Returns Gemini-synthesized summary (primary) or deterministic fallback.
    """
    return _run_analysis(repo_id, payload, db)


@router.post("/repos/{repo_id}/impact/analyze", response_model=PRImpactResponse)
def analyze_repository_pr_impact_v2(
    repo_id: str,
    payload: PRImpactRequest,
    db: Session = Depends(get_db),
):
    """
    Graph-aware PR impact analysis (alternate path for spec compliance).
    Identical behavior to POST /repos/{repo_id}/impact.
    """
    return _run_analysis(repo_id, payload, db)

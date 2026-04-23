from pydantic import BaseModel, Field
from typing import Any


class PRImpactRequest(BaseModel):
    # Accept either a raw unified diff OR an explicit file list (or both)
    diff: str | None = Field(default=None, description="Raw unified diff / patch text")
    changed_files: list[str] = Field(default_factory=list, description="Explicit list of changed file paths")
    notes: str | None = Field(default=None, description="Optional PR description or context")
    max_depth: int = Field(default=3, ge=1, le=8)


class ImpactedFileItem(BaseModel):
    file_id: str
    path: str
    language: str | None = None
    depth: int
    inbound_dependencies: int
    outbound_dependencies: int
    risk_score: float
    impact_score: float
    impact_level: str = "low"
    reasons: list[str] = Field(default_factory=list)
    edge_types: list[str] = Field(default_factory=list)
    is_directly_changed: bool = False
    categories: list[str] = Field(default_factory=list)
    primary_category: str = "module"
    symbol_hits: list[str] = Field(default_factory=list)
    why_now: str = ""


class ReviewerSuggestion(BaseModel):
    reviewer_hint: str
    reason: str
    why_now: str = ""


class FlowPathSummary(BaseModel):
    summary: str = ""
    score: float = 0.0
    nodes: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# New enriched response sections
# ---------------------------------------------------------------------------

class InputExtraction(BaseModel):
    """Section A — what was extracted from the input."""
    changed_files: list[str] = Field(default_factory=list)
    changed_symbols: list[str] = Field(default_factory=list)
    added_lines: int = 0
    removed_lines: int = 0
    analysis_source: str = "file_list"  # "diff" | "file_list" | "diff+file_list"


class BlastRadius(BaseModel):
    """Section B — scope of impact."""
    direct_dependents_count: int = 0
    upstream_dependencies_count: int = 0
    total_blast_radius_count: int = 0
    impacted_modules: list[str] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    """Section C — risk classification with reasons."""
    overall_risk_level: str = "low"
    overall_risk_score: float = 0.0
    risk_reasons: list[str] = Field(default_factory=list)


class AffectedFlow(BaseModel):
    """Section D — execution paths touched by this PR."""
    flow_name: str
    confidence: float = 0.0
    summary: str = ""
    path_nodes: list[str] = Field(default_factory=list)
    why_relevant: str = ""


class ReviewPriority(BaseModel):
    """Section E — ordered review checklist."""
    file_id: str | None = None
    path: str
    reason: str
    priority_score: float = 0.0
    primary_category: str = "module"


class PossibleRegression(BaseModel):
    """Section F — heuristic regression warnings."""
    description: str
    affected_area: str = ""
    confidence: str = "possible"  # "possible" | "likely"


class EvidenceSignal(BaseModel):
    """Section G — why RepoBrain concluded what it did."""
    signal: str
    file_path: str = ""
    detail: str = ""


class PRImpactResponse(BaseModel):
    # ── Original fields (preserved for backward compat) ──────────────────────
    repository_id: str
    changed_files: list[str]
    changed_symbols: list[str] = Field(default_factory=list)
    impacted_count: int
    risk_level: str
    total_impact_score: float
    summary: str
    mode: str = "fallback"
    impacted_files: list[ImpactedFileItem]
    reviewer_suggestions: list[ReviewerSuggestion]
    flow_paths: list[FlowPathSummary] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    # ── New enriched sections ─────────────────────────────────────────────────
    input_extraction: InputExtraction = Field(default_factory=InputExtraction)
    blast_radius: BlastRadius = Field(default_factory=BlastRadius)
    risk_assessment: RiskAssessment = Field(default_factory=RiskAssessment)
    affected_flows: list[AffectedFlow] = Field(default_factory=list)
    review_priorities: list[ReviewPriority] = Field(default_factory=list)
    possible_regressions: list[PossibleRegression] = Field(default_factory=list)
    evidence: list[EvidenceSignal] = Field(default_factory=list)
    executive_summary: str = ""
    partial_failure: bool = False
    partial_failure_reasons: list[str] = Field(default_factory=list)

"""
pr_impact_service.py — Graph-aware PR impact analysis with Gemini synthesis.

Pipeline:
  1. Parse diff / changed_files input → normalized changed file list + changed symbols
  2. Map changed paths to indexed repo files
  3. Graph expansion: BFS through dependency edges (inbound = blast radius)
  4. Score impacted files using graph + symbol + category signals
  5. Classify impact categories per file
  6. Build smart review order
  7. Retrieve evidence snippets for top impacted files
  8. Gemini synthesis (PRIMARY) → deterministic fallback (SECONDARY)

All logic is generic — no repo-specific hardcoding.
"""
from __future__ import annotations

import logging
import re
from collections import deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.dependency_edge import DependencyEdge
from app.db.models.file import File
from app.scoring.impact_scoring import (
    classify_impact_level,
    compute_file_impact_score,
    compute_total_impact_score,
)
from app.services.risk_service import RiskService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Diff parser — generic unified diff support
# ---------------------------------------------------------------------------

def _parse_diff(diff_text: str) -> list[str]:
    """
    Extract changed file paths from a unified diff.
    Handles:  diff --git a/... b/...  and  --- a/...  /  +++ b/...
    Returns a deduplicated list of file paths (b-side / new paths preferred).
    """
    paths: list[str] = []
    seen: set[str] = set()

    def _add(p: str) -> None:
        p = p.strip()
        for prefix in ("b/", "a/"):
            if p.startswith(prefix):
                p = p[len(prefix):]
                break
        if p and p not in seen and p != "/dev/null":
            seen.add(p)
            paths.append(p)

    for line in diff_text.splitlines():
        m = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
        if m:
            _add(m.group(2))
            continue
        m2 = re.match(r"^\+\+\+ (.+)$", line)
        if m2:
            _add(m2.group(1))
            continue
        m3 = re.match(r"^--- (.+)$", line)
        if m3:
            _add(m3.group(1))

    return paths


# ---------------------------------------------------------------------------
# Changed symbol extraction — generic, best-effort
# ---------------------------------------------------------------------------

# Generic patterns for symbol definitions across languages
_SYMBOL_PATTERNS = [
    # Python / JS / TS function defs
    re.compile(r"^[+-]\s*(?:async\s+)?(?:def|function)\s+(\w+)\s*\(", re.MULTILINE),
    # Python class
    re.compile(r"^[+-]\s*class\s+(\w+)\s*[:(]", re.MULTILINE),
    # JS/TS arrow function / const assignment
    re.compile(r"^[+-]\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(", re.MULTILINE),
    # JS/TS export function
    re.compile(r"^[+-]\s*export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE),
    # Decorator-based route handlers (generic @verb pattern)
    re.compile(r"^[+-]\s*@\w+\.\w+\s*\(['\"]([^'\"]+)['\"]", re.MULTILINE),
    # Assignment / config key (ALL_CAPS env-like)
    re.compile(r"^[+-]\s*([A-Z][A-Z0-9_]{2,})\s*=", re.MULTILINE),
    # Method definitions (indented def)
    re.compile(r"^[+-]\s{4,}(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE),
]

_TRIVIAL_SYMBOLS = {
    "if", "for", "while", "with", "try", "return", "raise", "pass",
    "import", "from", "class", "def", "async", "await", "yield",
    "true", "false", "null", "none", "undefined",
}


def _extract_changed_symbols(diff_text: str) -> list[str]:
    """
    Extract likely changed symbol names from a unified diff.
    Best-effort — never fails. Returns deduplicated list.
    """
    if not diff_text:
        return []

    symbols: list[str] = []
    seen: set[str] = set()

    for pat in _SYMBOL_PATTERNS:
        for m in pat.finditer(diff_text):
            sym = m.group(1).strip()
            if sym and len(sym) >= 2 and sym.lower() not in _TRIVIAL_SYMBOLS:
                if sym not in seen:
                    seen.add(sym)
                    symbols.append(sym)

    return symbols[:20]  # cap to avoid noise



# ---------------------------------------------------------------------------
# Diff change-type classifier — generic, language-agnostic
# ---------------------------------------------------------------------------
# Classifies what KIND of change a diff represents, enabling realistic
# severity calibration. Low-signal changes get penalized; high-signal
# changes (route/schema/auth/public API) get boosted.
# ---------------------------------------------------------------------------

# Patterns for low-severity change detection
_WHITESPACE_ONLY_RE = re.compile(r"^[+-]\s*$", re.MULTILINE)
_COMMENT_LINE_RE = re.compile(r"^[+-]\s*(?:#|//|/\*|\*|\"\"\"|\'\'\').*$", re.MULTILINE)
_IMPORT_LINE_RE = re.compile(r"^[+-]\s*(?:import|from\s+\S+\s+import|require\s*\(|#include)", re.MULTILINE)
_LOGGING_LINE_RE = re.compile(r"^[+-]\s*(?:logger\.|logging\.|console\.|print\s*\(|log\s*\()", re.MULTILINE)
_DOCSTRING_RE = re.compile(r'^[+-]\s*(?:"""|\'\'\').*?(?:"""|\'\'\')$', re.MULTILINE | re.DOTALL)

# Patterns for high-severity change detection
_ROUTE_DECORATOR_RE = re.compile(
    r"^[+-]\s*@(?:app|router|blueprint|api)\.(get|post|put|delete|patch|options|head)\s*\(",
    re.MULTILINE | re.IGNORECASE,
)
_ROUTE_PATH_RE = re.compile(
    r"^[+-]\s*(?:path|re_path|url)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE | re.IGNORECASE,
)
_PUBLIC_FUNC_RE = re.compile(
    r"^[+-]\s*(?:async\s+)?def\s+(?!_)(\w+)\s*\(",
    re.MULTILINE,
)
_PUBLIC_CLASS_RE = re.compile(
    r"^[+-]\s*class\s+(\w+)\s*[:(]",
    re.MULTILINE,
)
_SCHEMA_FIELD_RE = re.compile(
    r"^[+-]\s*\w+\s*[:=]\s*(?:Field|Column|models\.|db\.Column|Mapped\[)",
    re.MULTILINE,
)
_AUTH_PATTERN_RE = re.compile(
    r"^[+-].*(?:password|token|secret|auth|permission|role|credential|jwt|oauth|session)",
    re.MULTILINE | re.IGNORECASE,
)
_CONFIG_PATTERN_RE = re.compile(
    r"^[+-]\s*[A-Z][A-Z0-9_]{2,}\s*=",
    re.MULTILINE,
)


def _classify_diff_change_types(diff: str | None, changed_paths: list[str]) -> dict:
    """
    Classify the change types present in a diff.

    Returns a dict with:
    - change_types: list of detected change type strings
    - severity_modifier: float (-1.0 to +1.0) to adjust base risk score
    - is_trivial: bool — true if all changes are low-signal
    - explanation: human-readable summary of what was detected

    Never raises — returns safe defaults on failure.
    """
    result = {
        "change_types": [],
        "severity_modifier": 0.0,
        "is_trivial": False,
        "explanation": "",
    }

    if not diff:
        # File-list only — classify by path patterns
        change_types = []
        for path in changed_paths:
            p = path.lower()
            if any(t in p for t in ("test", "spec", "fixture", "mock")):
                change_types.append("test_only")
            elif any(t in p for t in ("readme", "changelog", "docs", ".md", ".rst", ".txt")):
                change_types.append("docs_only")
        if change_types and all(ct in ("test_only", "docs_only") for ct in change_types):
            result["change_types"] = list(set(change_types))
            result["severity_modifier"] = -0.3
            result["is_trivial"] = True
            result["explanation"] = "Only test/documentation files changed."
        return result

    try:
        # Extract only the changed lines (+ and - lines, not context)
        changed_lines = [l for l in diff.splitlines() if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
        changed_text = "\n".join(changed_lines)

        if not changed_text.strip():
            result["is_trivial"] = True
            result["explanation"] = "No meaningful content changes detected."
            return result

        change_types: list[str] = []
        severity_mod = 0.0

        # ── Low-severity signals ──────────────────────────────────────────────
        non_ws_lines = [l for l in changed_lines if l[1:].strip()]
        ws_only = len(non_ws_lines) == 0
        if ws_only:
            change_types.append("whitespace_only")
            severity_mod -= 0.5

        comment_lines = len(_COMMENT_LINE_RE.findall(changed_text))
        import_lines = len(_IMPORT_LINE_RE.findall(changed_text))
        logging_lines = len(_LOGGING_LINE_RE.findall(changed_text))
        total_changed = max(1, len(non_ws_lines))

        if comment_lines / total_changed >= 0.8:
            change_types.append("comment_only")
            severity_mod -= 0.4
        elif comment_lines / total_changed >= 0.5:
            change_types.append("mostly_comments")
            severity_mod -= 0.2

        if import_lines > 0 and import_lines / total_changed >= 0.7:
            change_types.append("import_only")
            severity_mod -= 0.25

        if logging_lines > 0 and logging_lines / total_changed >= 0.6:
            change_types.append("logging_only")
            severity_mod -= 0.2

        # ── High-severity signals ─────────────────────────────────────────────
        route_decorators = _ROUTE_DECORATOR_RE.findall(changed_text)
        if route_decorators:
            change_types.append("route_signature_change")
            severity_mod += 0.35

        route_paths = _ROUTE_PATH_RE.findall(changed_text)
        if route_paths:
            change_types.append("route_path_change")
            severity_mod += 0.30

        public_funcs = _PUBLIC_FUNC_RE.findall(changed_text)
        if public_funcs:
            change_types.append("public_function_signature_change")
            severity_mod += 0.20

        public_classes = _PUBLIC_CLASS_RE.findall(changed_text)
        if public_classes:
            change_types.append("public_class_change")
            severity_mod += 0.15

        schema_fields = _SCHEMA_FIELD_RE.findall(changed_text)
        if schema_fields:
            change_types.append("schema_change")
            severity_mod += 0.30

        auth_patterns = _AUTH_PATTERN_RE.findall(changed_text)
        if auth_patterns:
            change_types.append("auth_security_change")
            severity_mod += 0.40

        config_constants = _CONFIG_PATTERN_RE.findall(changed_text)
        if config_constants:
            change_types.append("config_runtime_change")
            severity_mod += 0.25

        # ── Path-based signals ────────────────────────────────────────────────
        for path in changed_paths:
            p = path.lower()
            if any(t in p for t in ("test", "spec", "fixture", "mock")):
                if "test_only" not in change_types:
                    change_types.append("test_only")
                    severity_mod -= 0.20

        # ── Determine if trivial ──────────────────────────────────────────────
        low_signal = {"whitespace_only", "comment_only", "mostly_comments", "import_only", "logging_only", "test_only", "docs_only"}
        high_signal = {"route_signature_change", "route_path_change", "schema_change", "auth_security_change", "public_function_signature_change"}
        has_high = bool(set(change_types) & high_signal)
        all_low = bool(change_types) and not has_high and all(ct in low_signal for ct in change_types)
        is_trivial = all_low and not has_high

        # Build explanation
        if not change_types:
            change_types.append("generic_logic_change")
            explanation = "General code changes detected."
        elif is_trivial:
            explanation = f"Low-signal changes: {', '.join(change_types)}."
        elif has_high:
            high_found = [ct for ct in change_types if ct in high_signal]
            explanation = f"High-impact changes detected: {', '.join(high_found)}."
        else:
            explanation = f"Mixed changes: {', '.join(change_types[:3])}."

        result["change_types"] = list(dict.fromkeys(change_types))  # deduplicate preserving order
        result["severity_modifier"] = round(max(-0.6, min(0.6, severity_mod)), 2)
        result["is_trivial"] = is_trivial
        result["explanation"] = explanation

    except Exception as e:
        logger.debug(f"_classify_diff_change_types failed: {e}")

    return result


# ---------------------------------------------------------------------------
# Impact category classifier — generic file role heuristics
# ---------------------------------------------------------------------------

_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("api_contract",        ["route", "router", "routes", "controller", "handler", "endpoint", "view", "api", "rest", "graphql"]),
    ("business_logic",      ["service", "services", "usecase", "use_case", "business", "logic", "manager", "workflow"]),
    ("data_model",          ["model", "models", "schema", "schemas", "entity", "entities", "dto", "type", "interface", "struct"]),
    ("persistence",         ["repo", "repository", "dao", "store", "storage", "crud", "db", "database", "query", "migration", "orm"]),
    ("auth_security",       ["auth", "authentication", "authorization", "permission", "security", "token", "jwt", "oauth", "guard", "middleware"]),
    ("config",              ["config", "settings", "configuration", "env", "constants", "secrets", "credentials"]),
    ("external_integration",["client", "external", "api_client", "http", "request", "fetch", "sdk", "webhook", "integration"]),
    ("ui_rendering",        ["component", "page", "view", "template", "render", "layout", "widget", "screen"]),
    ("test_only",           ["test", "tests", "spec", "specs", "__test__", "fixture", "mock", "stub"]),
    ("infrastructure",      ["docker", "compose", "deploy", "infra", "ci", "cd", "pipeline", "worker", "celery", "queue", "job"]),
    ("utility_shared",      ["util", "utils", "helper", "helpers", "common", "shared", "lib", "libs", "base"]),
]

_CATEGORY_PRIORITY = {
    "api_contract":         1,
    "auth_security":        2,
    "business_logic":       3,
    "data_model":           4,
    "persistence":          5,
    "external_integration": 6,
    "config":               7,
    "infrastructure":       8,
    "utility_shared":       9,
    "ui_rendering":         10,
    "test_only":            11,
}

# Category → score boost applied during ranking
_CATEGORY_BOOST: dict[str, float] = {
    "api_contract":         12.0,
    "auth_security":        14.0,
    "data_model":           10.0,
    "business_logic":       8.0,
    "persistence":          8.0,
    "external_integration": 7.0,
    "config":               6.0,
    "utility_shared":       5.0,
    "infrastructure":       4.0,
    "ui_rendering":         3.0,
    "test_only":            -8.0,  # penalty
}


def _classify_file_categories(path: str, file_kind: str | None = None) -> tuple[list[str], str]:
    """
    Classify a file into one or more impact categories.
    Returns (categories[], primary_category).
    """
    path_lower = path.lower().replace("\\", "/")
    parts = path_lower.split("/")
    basename = parts[-1].rsplit(".", 1)[0] if "." in parts[-1] else parts[-1]

    matched: list[str] = []
    for category, keywords in _CATEGORY_PATTERNS:
        for part in parts + [basename]:
            for kw in keywords:
                if kw == part or part.startswith(kw + "_") or part.endswith("_" + kw) or (len(kw) >= 4 and kw in part):
                    if category not in matched:
                        matched.append(category)
                    break

    if not matched:
        if file_kind in ("test",):
            matched = ["test_only"]
        elif file_kind in ("config",):
            matched = ["config"]
        else:
            matched = ["utility_shared"]

    # Primary = highest priority (lowest number)
    primary = min(matched, key=lambda c: _CATEGORY_PRIORITY.get(c, 99))
    return matched, primary


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------

def _normalize_path(path: str, path_to_file: dict[str, File]) -> File | None:
    """Map a changed path to an indexed File using multiple strategies."""
    if path in path_to_file:
        return path_to_file[path]
    for indexed_path, f in path_to_file.items():
        if indexed_path.endswith("/" + path) or path.endswith("/" + indexed_path):
            return f
    basename = path.split("/")[-1]
    matches = [f for p, f in path_to_file.items() if p.split("/")[-1] == basename]
    if len(matches) == 1:
        return matches[0]
    return None


# ---------------------------------------------------------------------------
# Gemini prompt builder — upgraded
# ---------------------------------------------------------------------------

def _build_impact_prompt(
    changed_files: list[str],
    impacted_files: list[dict],
    evidence: list[dict],
    notes: str | None,
    flow_paths: list[dict] | None = None,
    changed_symbols: list[str] | None = None,
) -> tuple[str, str]:
    """Build upgraded system + user prompts for Gemini PR impact synthesis."""
    system = (
        "You are a senior software engineer reviewing a pull request for a teammate.\n"
        "You have been given structured impact analysis data derived from the repository's "
        "dependency graph, symbol table, and execution flow analysis.\n\n"
        "Your job: write a concise, grounded, developer-facing impact summary.\n\n"
        "Rules:\n"
        "1. Write in plain natural prose. No section headers, no bold text, no bullet spam.\n"
        "2. Explain what changed, which layers are affected, and why the blast radius exists.\n"
        "3. Tell the reviewer what to inspect first and what kinds of regressions to test.\n"
        "4. Be specific — name the files and relationships from the evidence.\n"
        "5. Keep it under 6 sentences for simple changes, up to 10 for complex ones.\n"
        "6. Never fabricate file names, symbols, or relationships not in the evidence.\n"
        "7. Do not output 'Summary:', 'Analysis:', 'Confidence:', 'Impact:', or similar labels.\n"
        "8. Sound like a senior reviewer, not a template engine.\n"
    )

    changed_str = "\n".join(f"  - {f}" for f in changed_files[:20])

    sym_str = ""
    if changed_symbols:
        sym_str = f"\nCHANGED SYMBOLS: {', '.join(changed_symbols[:12])}"

    top_impacted = impacted_files[:8]
    impacted_str = "\n".join(
        f"  - {f['path']} [{f.get('primary_category', 'module')}] "
        f"(score={f['impact_score']:.1f}, {f.get('impact_level','?')} impact, "
        f"reasons: {', '.join(f.get('reasons', [])[:2])})"
        for f in top_impacted
    )

    review_str = ""
    review_order = impacted_files[:5]  # top 5 by smart order
    if review_order:
        review_str = "\nSUGGESTED REVIEW ORDER:\n" + "\n".join(
            f"  {i+1}. {f['path']} — {f.get('why_now', f.get('reasons', [''])[0] if f.get('reasons') else '')}"
            for i, f in enumerate(review_order)
        )

    ev_str = ""
    if evidence:
        ev_parts = []
        for ev in evidence[:3]:
            snip = (ev.get("snippet") or "")[:180].replace("\n", " ")
            ev_parts.append(f"  [{ev['path']}]: {snip}")
        ev_str = "\nKEY CODE CONTEXT:\n" + "\n".join(ev_parts)

    flow_str = ""
    if flow_paths:
        fp_parts = [f"  - {fp['summary']}" for fp in flow_paths[:2] if fp.get("summary")]
        if fp_parts:
            flow_str = "\nEXECUTION PATHS AFFECTED:\n" + "\n".join(fp_parts)

    notes_str = f"\nPR CONTEXT:\n{notes}" if notes else ""

    user = (
        f"CHANGED FILES ({len(changed_files)}):\n{changed_str}"
        f"{sym_str}\n\n"
        f"TOP IMPACTED FILES ({len(top_impacted)}):\n{impacted_str}"
        f"{review_str}"
        f"{ev_str}"
        f"{flow_str}"
        f"{notes_str}\n\n"
        "Write a concise, grounded impact summary for the developer reviewing this PR. "
        "Explain what changed, what is likely to break, and what to review first."
    )

    return system, user


# ---------------------------------------------------------------------------
# Evidence retrieval
# ---------------------------------------------------------------------------

def _retrieve_evidence(
    db: Session,
    repository_id: str,
    file_ids: list[str],
    max_per_file: int = 1,
) -> list[dict]:
    """Fetch short content windows for the top impacted files."""
    evidence = []
    for fid in file_ids[:6]:
        try:
            f = db.get(File, fid)
            if not f or not f.content:
                continue
            lines = f.content.splitlines()
            meaningful = [
                l for l in lines[:60]
                if l.strip() and not l.strip().startswith("#")
                and not l.strip().startswith("//") and len(l.strip()) > 3
            ][:15]
            if meaningful:
                evidence.append({
                    "file_id": fid,
                    "path": f.path,
                    "snippet": "\n".join(meaningful),
                })
        except Exception:
            pass
    return evidence


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class PRImpactService:
    def __init__(self, db: Session):
        self.db = db
        self.risk_service = RiskService(db)

    def analyze_impact(
        self,
        repository_id: str,
        changed_files: list[str],
        diff: str | None = None,
        notes: str | None = None,
        max_depth: int = 3,
    ) -> dict:
        pipeline_notes: list[str] = []

        # ── Step 1: normalize input + extract changed symbols ────────────────
        all_changed: list[str] = list(changed_files)
        changed_symbols: list[str] = []

        if diff:
            diff_paths = _parse_diff(diff)
            if diff_paths:
                seen = set(all_changed)
                for p in diff_paths:
                    if p not in seen:
                        all_changed.append(p)
                        seen.add(p)
            else:
                pipeline_notes.append("Diff was provided but no file paths could be extracted.")
            # Extract changed symbols from diff hunks (best-effort)
            try:
                changed_symbols = _extract_changed_symbols(diff)
            except Exception:
                pass  # never fail on symbol extraction

        # ── Step 1b: classify change types for severity calibration ──────────
        change_classification = _classify_diff_change_types(diff, all_changed)
        change_types = change_classification.get("change_types", [])
        severity_modifier = change_classification.get("severity_modifier", 0.0)
        is_trivial_change = change_classification.get("is_trivial", False)
        change_explanation = change_classification.get("explanation", "")

        if not all_changed:
            return {
                "repository_id": repository_id,
                "changed_files": [],
                "impacted_count": 0,
                "risk_level": "low",
                "total_impact_score": 0.0,
                "summary": "No changed files provided. Supply a diff or a list of file paths.",
                "mode": "error",
                "impacted_files": [],
                "reviewer_suggestions": [],
                "notes": pipeline_notes,
                "score_explanation": "No files to analyze; provide changed file paths or diff.",
            }

        # ── Step 2: load repo files (no content — not needed for impact scoring) ──
        file_rows = list(self.db.execute(
            select(
                File.id, File.path, File.language, File.file_kind,
                File.line_count, File.is_test, File.is_generated, File.is_vendor,
            ).where(File.repository_id == repository_id)
        ).all())

        if not file_rows:
            return self._empty_response(repository_id, all_changed, pipeline_notes)

        # Build lightweight file objects (no content field)
        class _FileProxy:
            __slots__ = ("id", "path", "language", "file_kind", "line_count",
                         "is_test", "is_generated", "is_vendor")
            def __init__(self, row: tuple) -> None:
                (self.id, self.path, self.language, self.file_kind,
                 self.line_count, self.is_test, self.is_generated, self.is_vendor) = row

        all_files = [_FileProxy(row) for row in file_rows]
        path_to_file: dict[str, _FileProxy] = {f.path: f for f in all_files}
        file_map: dict[str, _FileProxy] = {f.id: f for f in all_files}

        # ── Step 3: map changed paths to indexed files ───────────────────────
        changed_file_records: list[File] = []
        unmatched: list[str] = []
        for p in all_changed:
            f = _normalize_path(p, path_to_file)
            if f:
                changed_file_records.append(f)
            else:
                unmatched.append(p)

        if unmatched:
            pipeline_notes.append(
                f"{len(unmatched)} changed path(s) not found in indexed files: "
                + ", ".join(unmatched[:5])
                + ("..." if len(unmatched) > 5 else "")
            )

        if not changed_file_records:
            return {
                "repository_id": repository_id,
                "changed_files": all_changed,
                "impacted_count": 0,
                "risk_level": "low",
                "total_impact_score": 0.0,
                "summary": (
                    "None of the provided changed files were found in the indexed repository. "
                    "Ensure the repository has been indexed and the file paths match."
                ),
                "mode": "fallback",
                "impacted_files": [],
                "reviewer_suggestions": [],
                "notes": pipeline_notes,
                "score_explanation": "Changed files not found in indexed repository; unable to analyze impact.",
            }

        # ── Step 4: load dependency edges ────────────────────────────────────
        file_ids = [f.id for f in all_files]

        edges = list(
            self.db.scalars(
                select(DependencyEdge).where(
                    DependencyEdge.repository_id == repository_id,
                    DependencyEdge.source_file_id.in_(file_ids),
                    DependencyEdge.target_file_id.in_(file_ids),
                )
            ).all()
        )

        # Build adjacency maps
        # source imports/calls target → changing target impacts source (reverse)
        reverse_adj: dict[str, set[str]] = {}   # target → set of sources that depend on it
        forward_adj: dict[str, set[str]] = {}   # source → set of targets it depends on
        edge_type_map: dict[tuple[str, str], list[str]] = {}  # (src, tgt) → edge types

        for edge in edges:
            if not edge.source_file_id or not edge.target_file_id:
                continue
            reverse_adj.setdefault(edge.target_file_id, set()).add(edge.source_file_id)
            forward_adj.setdefault(edge.source_file_id, set()).add(edge.target_file_id)
            key = (edge.source_file_id, edge.target_file_id)
            edge_type_map.setdefault(key, [])
            if edge.edge_type not in edge_type_map[key]:
                edge_type_map[key].append(edge.edge_type)

        # ── Inferred edge fallback (sparse graph) ────────────────────────────
        # If no resolved edges exist, use the same inferred edge layer that
        # powers Knowledge Graph and Execution Map. This keeps PR Impact
        # consistent with the rest of the product.
        _used_inferred_edges = False
        if not edges:
            try:
                from app.services.graph_service import compute_inferred_edges
                all_file_rows = list(self.db.execute(
                    select(
                        File.id, File.path, File.language, File.file_kind,
                        File.line_count, File.is_generated, File.is_vendor, File.is_test,
                    ).where(File.repository_id == repository_id)
                ).all())
                inferred = compute_inferred_edges(
                    db=self.db,
                    repository_id=repository_id,
                    resolved_edges=[],
                    all_files=all_file_rows,
                    sparsity_threshold=1.0,  # always run when no resolved edges
                    max_inferred=300,
                )
                if inferred:
                    file_id_set = set(file_ids)
                    for src, tgt, etype in inferred:
                        if src not in file_id_set or tgt not in file_id_set:
                            continue
                        reverse_adj.setdefault(tgt, set()).add(src)
                        forward_adj.setdefault(src, set()).add(tgt)
                        key = (src, tgt)
                        edge_type_map.setdefault(key, [])
                        if etype not in edge_type_map[key]:
                            edge_type_map[key].append(etype)
                    _used_inferred_edges = bool(inferred)
            except Exception:
                pass  # always degrade gracefully

        if not edges and not _used_inferred_edges:
            pipeline_notes.append(
                "No resolved dependency edges found. Graph expansion unavailable. "
                "Re-index the repository to populate file relationships."
            )
        elif _used_inferred_edges:
            pipeline_notes.append(
                "Used inferred dependency relationships due to sparse persisted graph. "
                "Impact expansion confidence is lower than with persisted dependency edges."
            )

        inbound_counts = {fid: len(reverse_adj.get(fid, set())) for fid in file_map}
        outbound_counts = {fid: len(forward_adj.get(fid, set())) for fid in file_map}

        # ── Step 5: BFS graph expansion ──────────────────────────────────────
        risk_map = self.risk_service.get_file_risk_map(repository_id)

        visited_depth: dict[str, int] = {}
        visited_reasons: dict[str, list[str]] = {}
        visited_edge_types: dict[str, set[str]] = {}
        queue: deque[tuple[str, int, str]] = deque()

        changed_ids = {f.id for f in changed_file_records}

        for f in changed_file_records:
            visited_depth[f.id] = 0
            visited_reasons[f.id] = ["directly changed"]
            visited_edge_types[f.id] = set()
            queue.append((f.id, 0, "direct"))

        while queue:
            current_id, depth, _ = queue.popleft()
            if depth >= max_depth:
                continue

            # Inbound: files that import/call current_id (blast radius)
            for dependent_id in reverse_adj.get(current_id, set()):
                next_depth = depth + 1
                if dependent_id not in visited_depth or next_depth < visited_depth[dependent_id]:
                    visited_depth[dependent_id] = next_depth
                    etypes = edge_type_map.get((dependent_id, current_id), ["import"])
                    reason = _reason_from_edge(etypes, current_id, file_map, direction="inbound")
                    visited_reasons[dependent_id] = [reason]
                    visited_edge_types[dependent_id] = set(etypes)
                    queue.append((dependent_id, next_depth, "inbound"))

            # Outbound (depth 1 only): files that current_id depends on
            if depth == 0:
                for dep_id in forward_adj.get(current_id, set()):
                    if dep_id not in visited_depth:
                        visited_depth[dep_id] = 1
                        etypes = edge_type_map.get((current_id, dep_id), ["import"])
                        reason = _reason_from_edge(etypes, current_id, file_map, direction="outbound")
                        visited_reasons[dep_id] = [reason]
                        visited_edge_types[dep_id] = set(etypes)
                        queue.append((dep_id, 1, "outbound"))

        # ── Step 6: score impacted files with category + symbol boosts ──────
        impacted_files: list[dict] = []

        # Build symbol lookup set for fast matching
        changed_sym_lower = {s.lower() for s in changed_symbols}

        for file_id, depth in visited_depth.items():
            f = file_map.get(file_id)
            if not f:
                continue
            file_risk = risk_map.get(file_id, {})
            risk_score = float(file_risk.get("risk_score", 0.0))
            inbound = inbound_counts.get(file_id, 0)
            outbound = outbound_counts.get(file_id, 0)

            impact_score = compute_file_impact_score(
                depth=depth,
                inbound_dependencies=inbound,
                outbound_dependencies=outbound,
                risk_score=risk_score,
            )

            # Boost directly changed files
            if file_id in changed_ids:
                impact_score = max(impact_score, 50.0)

            # ── Category classification ──────────────────────────────────────
            categories, primary_category = _classify_file_categories(f.path, f.file_kind)

            # ── Category-based score boost ───────────────────────────────────
            cat_boost = _CATEGORY_BOOST.get(primary_category, 0.0)
            impact_score = max(0.0, impact_score + cat_boost)

            # ── Symbol hit boost ─────────────────────────────────────────────
            symbol_hits: list[str] = []
            if changed_sym_lower and f.content:
                content_lower = f.content.lower()
                for sym in changed_sym_lower:
                    if len(sym) >= 3 and sym in content_lower:
                        symbol_hits.append(sym)
                if symbol_hits:
                    # Strong boost: file references changed symbols
                    sym_boost = min(len(symbol_hits) * 6.0, 20.0)
                    impact_score += sym_boost
                    if "references changed symbol" not in (visited_reasons.get(file_id) or []):
                        visited_reasons.setdefault(file_id, []).append(
                            f"references changed symbol: {', '.join(symbol_hits[:2])}"
                        )

            # ── Shared core boost: high-inbound utility files ────────────────
            if primary_category == "utility_shared" and inbound >= 5:
                impact_score += 5.0

            # ── Test-only penalty ────────────────────────────────────────────
            if f.is_test or primary_category == "test_only":
                if file_id not in changed_ids:
                    impact_score = max(0.0, impact_score - 10.0)

            impact_level = classify_impact_level(impact_score)
            reasons = visited_reasons.get(file_id, [])
            etypes = list(visited_edge_types.get(file_id, set()))
            etypes_set = visited_edge_types.get(file_id, set())
            is_direct = file_id in changed_ids

            # Reason tag and evidence strength from edge types
            reason_tag = _reason_tag_from_edge_types(etypes_set, is_direct)
            evidence_strength = _evidence_strength_from_edge_types(etypes_set) if not is_direct else "high"

            impacted_files.append({
                "file_id": file_id,
                "path": f.path,
                "language": f.language,
                "depth": depth,
                "inbound_dependencies": inbound,
                "outbound_dependencies": outbound,
                "risk_score": round(risk_score, 2),
                "impact_score": round(impact_score, 2),
                "impact_level": impact_level,
                "reasons": reasons,
                "edge_types": etypes,
                "is_directly_changed": is_direct,
                "categories": categories,
                "primary_category": primary_category,
                "symbol_hits": symbol_hits[:5],
                "reason_tag": reason_tag,
                "evidence_strength": evidence_strength,
            })

        impacted_files.sort(key=lambda x: (-x["impact_score"], x["depth"]))

        total_impact_score = compute_total_impact_score([f["impact_score"] for f in impacted_files])

        # Apply severity modifier from change-type classification
        # Trivial changes (whitespace/comment/import-only) get capped
        if is_trivial_change and total_impact_score > 40.0:
            total_impact_score = min(total_impact_score, 40.0)
            pipeline_notes.append(f"Score capped: {change_explanation}")
        elif severity_modifier != 0.0:
            # Apply modifier proportionally (not additively) to avoid inflation
            adjusted = total_impact_score * (1.0 + severity_modifier)
            total_impact_score = round(max(0.0, min(100.0, adjusted)), 2)

        risk_level = classify_impact_level(total_impact_score)

        # ── Step 6b: build smart review order ────────────────────────────────
        # Order by: directly changed first, then by category priority, then score
        def _review_sort_key(f: dict) -> tuple:
            is_direct = 0 if f.get("is_directly_changed") else 1
            cat_pri = _CATEGORY_PRIORITY.get(f.get("primary_category", "utility_shared"), 99)
            return (is_direct, cat_pri, -f["impact_score"])

        review_ordered = sorted(impacted_files, key=_review_sort_key)

        # Annotate each file with why_now
        for f in review_ordered:
            cat = f.get("primary_category", "module")
            if f.get("is_directly_changed"):
                f["why_now"] = "directly changed — inspect all modifications"
            elif cat == "api_contract":
                f["why_now"] = "public API boundary — contract changes propagate to callers"
            elif cat == "auth_security":
                f["why_now"] = "auth/security layer — regressions here are high severity"
            elif cat == "data_model":
                f["why_now"] = "data model/schema — shape changes affect all consumers"
            elif cat == "business_logic":
                f["why_now"] = "core business logic — verify behavior is preserved"
            elif cat == "persistence":
                f["why_now"] = "data access layer — check queries and transactions"
            elif cat == "external_integration":
                f["why_now"] = "external integration — verify API contracts and error handling"
            elif cat == "config":
                f["why_now"] = "configuration — changes affect runtime behavior broadly"
            elif f.get("symbol_hits"):
                f["why_now"] = f"references changed symbol: {', '.join(f['symbol_hits'][:2])}"
            else:
                reasons = f.get("reasons", [])
                f["why_now"] = reasons[0] if reasons else "impacted via dependency graph"

        # ── Step 7: retrieve evidence ─────────────────────────────────────────
        top_ids = [f["file_id"] for f in impacted_files[:6]]
        evidence = _retrieve_evidence(self.db, repository_id, top_ids)

        # ── Step 7b: enrich with FlowService impact paths ─────────────────────
        flow_paths: list[dict] = []
        try:
            from app.services.flow_service import FlowService
            flow_svc = FlowService(self.db)
            changed_csv = ",".join(all_changed[:10])
            flow_result = flow_svc.get_flow(
                repository_id=repository_id,
                mode="impact",
                changed=changed_csv,
                depth=min(max_depth, 3),
            )
            for path in (flow_result.get("paths") or [])[:3]:
                flow_paths.append({
                    "summary": path.get("explanation", ""),
                    "score": path.get("score", 0.0),
                    "nodes": [
                        {"path": n.get("path", ""), "type": n.get("type", ""), "label": n.get("label", "")}
                        for n in (path.get("nodes") or [])[:6]
                    ],
                })
        except Exception as _flow_err:
            logger.debug(f"FlowService enrichment skipped: {_flow_err}")

        # ── Step 8: Gemini synthesis (PRIMARY) ────────────────────────────────
        summary = ""
        mode = "fallback"

        try:
            from app.llm.providers import get_chat_provider
            provider = get_chat_provider()
            if provider is not None:
                system_prompt, user_prompt = _build_impact_prompt(
                    changed_files=all_changed,
                    impacted_files=review_ordered,  # use smart order for Gemini context
                    evidence=evidence,
                    flow_paths=flow_paths,
                    notes=notes,
                    changed_symbols=changed_symbols,
                )
                raw = (provider.answer(system_prompt, user_prompt) or "").strip()
                if raw:
                    # Strip any leaked markdown bold
                    summary = raw.replace("**", "")
                    mode = "gemini_synthesized"
        except Exception as e:
            logger.warning(f"Gemini synthesis failed for PR impact: {e}")

        # ── Step 9: deterministic fallback ────────────────────────────────────
        if not summary:
            summary = _build_fallback_summary(
                changed_files=all_changed,
                impacted_files=review_ordered,
                total_impact_score=total_impact_score,
                risk_level=risk_level,
                has_graph=bool(edges) or _used_inferred_edges,
                used_inferred=_used_inferred_edges,
                flow_paths=flow_paths,
                changed_symbols=changed_symbols,
            )
            mode = "fallback"

        reviewer_suggestions = _suggest_review_order(review_ordered)

        # ── Enrichment: build new structured sections ─────────────────────────
        enriched = _build_enriched_sections(
            repository_id=repository_id,
            all_changed=all_changed,
            changed_symbols=changed_symbols,
            diff=diff,
            impacted_files=impacted_files,
            review_ordered=review_ordered,
            flow_paths=flow_paths,
            risk_level=risk_level,
            total_impact_score=total_impact_score,
            edges=edges,
            file_map=file_map,
            inbound_counts=inbound_counts,
            outbound_counts=outbound_counts,
            changed_ids=changed_ids,
            pipeline_notes=pipeline_notes,
            used_inferred_edges=_used_inferred_edges,
        )
        # executive_summary mirrors the main summary
        enriched["executive_summary"] = summary

        # Build score explanation from real scoring components
        score_explanation_parts: list[str] = []
        if change_explanation:
            score_explanation_parts.append(change_explanation)
        if is_trivial_change:
            score_explanation_parts.append("Score reduced: low-signal change type.")
        if enriched.get("risk_assessment", {}).get("risk_reasons"):
            top_reason = enriched["risk_assessment"]["risk_reasons"][0]
            score_explanation_parts.append(f"Risk elevated: {top_reason}")
        if not edges:
            score_explanation_parts.append("Confidence limited: no dependency graph available.")
        
        # Ensure score_explanation is always non-empty for successful responses
        if score_explanation_parts:
            enriched["score_explanation"] = " ".join(score_explanation_parts[:3])
        else:
            # Fallback explanation when no specific scoring components are available
            if is_trivial_change:
                enriched["score_explanation"] = "Low-signal change detected (e.g. whitespace/comments/import-only), score capped."
            elif len(all_changed) == 1 and any(ext in all_changed[0].lower() for ext in ['.md', '.txt', '.rst']):
                enriched["score_explanation"] = "Documentation-only change detected, minimal impact expected."
            elif not edges and len(all_changed) <= 2:
                enriched["score_explanation"] = "Limited evidence: sparse dependency graph, score based on changed file type and direct references."
            else:
                enriched["score_explanation"] = "Score based on graph expansion and category analysis."
        enriched["change_types"] = change_types
        enriched["is_trivial_change"] = is_trivial_change

        # Final safety net: ensure score_explanation is always present in successful responses
        if "score_explanation" not in enriched or not enriched["score_explanation"] or not enriched["score_explanation"].strip():
            enriched["score_explanation"] = "Score based on direct file changes and dependency graph expansion."

        return {
            "repository_id": repository_id,
            "changed_files": all_changed,
            "changed_symbols": changed_symbols,
            "impacted_count": len(impacted_files),
            "risk_level": risk_level,
            "total_impact_score": total_impact_score,
            "summary": summary,
            "mode": mode,
            "impacted_files": impacted_files[:50],
            "reviewer_suggestions": reviewer_suggestions,
            "flow_paths": flow_paths,
            "notes": pipeline_notes,
            # New enriched sections
            **enriched,
        }

    def _empty_response(self, repository_id: str, changed_files: list[str], notes: list[str]) -> dict:
        return {
            "repository_id": repository_id,
            "changed_files": changed_files,
            "impacted_count": 0,
            "risk_level": "low",
            "total_impact_score": 0.0,
            "summary": "Repository has no indexed files. Index the repository first.",
            "mode": "fallback",
            "impacted_files": [],
            "reviewer_suggestions": [],
            "notes": notes,
            "score_explanation": "Repository has no indexed files; unable to perform impact analysis.",
            # New enriched sections — empty defaults
            "input_extraction": {"changed_files": changed_files, "changed_symbols": [], "added_lines": 0, "removed_lines": 0, "analysis_source": "file_list"},
            "blast_radius": {"direct_dependents_count": 0, "upstream_dependencies_count": 0, "total_blast_radius_count": 0, "impacted_modules": []},
            "risk_assessment": {"overall_risk_level": "low", "overall_risk_score": 0.0, "risk_reasons": []},
            "affected_flows": [],
            "review_priorities": [],
            "possible_regressions": [],
            "evidence": [],
            "executive_summary": "",
            "partial_failure": False,
            "partial_failure_reasons": [],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reason_from_edge(
    edge_types: list[str],
    related_file_id: str,
    file_map: dict[str, File],
    direction: str,
) -> str:
    related = file_map.get(related_file_id)
    related_name = related.path.split("/")[-1] if related else "changed file"
    primary = edge_types[0] if edge_types else "import"

    # Semantic edge types get descriptive reasons
    if "route_to_service" in edge_types:
        if direction == "inbound":
            return f"route handler calls this service (via {related_name})"
        return f"this route calls service {related_name}"
    if "service_to_model" in edge_types:
        if direction == "inbound":
            return f"service uses this model/schema (via {related_name})"
        return f"this service uses model {related_name}"
    if "uses_symbol" in edge_types:
        if direction == "inbound":
            return f"uses changed symbol from {related_name}"
        return f"symbol used in {related_name}"
    if "inferred_api" in edge_types:
        if direction == "inbound":
            return f"frontend calls this backend route (via {related_name})"
        return f"this frontend calls backend {related_name}"

    if direction == "inbound":
        if primary in ("import", "from_import", "require"):
            return f"imports {related_name}"
        if primary == "call":
            return f"calls symbol from {related_name}"
        return f"depends on {related_name}"
    else:
        if primary in ("import", "from_import", "require"):
            return f"imported by {related_name}"
        if primary == "call":
            return f"called by {related_name}"
        return f"dependency of {related_name}"


def _evidence_strength_from_edge_types(edge_types: set[str]) -> str:
    """Return evidence strength based on edge types present."""
    if any(et in edge_types for et in ("route_to_service", "service_to_model", "uses_symbol")):
        return "high"
    if any(et in edge_types for et in ("import", "from_import", "call", "require")):
        return "medium"
    if any(et in edge_types for et in ("inferred_api", "inferred", "inferred_naming")):
        return "low"
    return "medium"


def _reason_tag_from_edge_types(edge_types: set[str], is_directly_changed: bool) -> str:
    """Return a reason tag for the impacted file."""
    if is_directly_changed:
        return "direct_change"
    if "route_to_service" in edge_types:
        return "route_calls_changed_service"
    if "service_to_model" in edge_types:
        return "service_uses_changed_model"
    if "uses_symbol" in edge_types:
        return "changed_symbol_used_here"
    if "inferred_api" in edge_types:
        return "frontend_calls_changed_route"
    if any(et in edge_types for et in ("import", "from_import", "require")):
        return "imports_changed_code"
    if any(et in edge_types for et in ("inferred", "inferred_naming")):
        return "same_execution_path"
    return "semantic_reference_only"


def _build_fallback_summary(
    changed_files: list[str],
    impacted_files: list[dict],
    total_impact_score: float,
    risk_level: str,
    has_graph: bool,
    used_inferred: bool = False,
    flow_paths: list[dict] | None = None,
    changed_symbols: list[str] | None = None,
) -> str:
    n_changed = len(changed_files)
    indirect = [f for f in impacted_files if not f.get("is_directly_changed")]
    directly = [f for f in impacted_files if f.get("is_directly_changed")]

    parts: list[str] = []

    # What changed
    changed_names = [p.split("/")[-1] for p in changed_files[:3]]
    sym_str = ""
    if changed_symbols:
        sym_str = f", modifying {', '.join(changed_symbols[:3])}"
    parts.append(f"This PR modifies {n_changed} file(s) ({', '.join(changed_names)}){sym_str}.")

    # Which layers are affected
    if indirect:
        # Group by category
        cat_groups: dict[str, list[str]] = {}
        for f in indirect[:8]:
            cat = f.get("primary_category", "module")
            cat_groups.setdefault(cat, []).append(f["path"].split("/")[-1])

        top_cats = sorted(cat_groups.items(), key=lambda x: _CATEGORY_PRIORITY.get(x[0], 99))[:3]
        layer_desc = "; ".join(
            f"{cat.replace('_', ' ')} ({', '.join(names[:2])})"
            for cat, names in top_cats
        )
        parts.append(
            f"Graph analysis found {len(indirect)} potentially affected file(s) "
            f"across: {layer_desc}."
        )
    elif not has_graph:
        parts.append(
            "No resolved dependency edges are available — graph expansion was skipped. "
            "Re-index the repository to enable relationship-aware impact analysis."
        )
    elif used_inferred:
        parts.append(
            "Impact expansion used inferred file relationships; "
            "confidence is lower than with persisted dependency edges."
        )

    # Risk level
    parts.append(f"Overall impact is classified as {risk_level} (score {total_impact_score:.1f}/100).")

    # What to review first
    top_review = next((f for f in impacted_files if not f.get("is_directly_changed")), None)
    if top_review:
        why = top_review.get("why_now", top_review.get("reasons", [""])[0] if top_review.get("reasons") else "")
        parts.append(
            f"Start your review with {top_review['path'].split('/')[-1]} "
            f"({top_review.get('primary_category', 'module').replace('_', ' ')}) — {why}."
        )

    # Flow path hint
    if flow_paths:
        top_fp = next((fp for fp in flow_paths if fp.get("summary")), None)
        if top_fp:
            parts.append(f"Likely execution path affected: {top_fp['summary']}")

    return " ".join(parts)


def _suggest_review_order(impacted_files: list[dict]) -> list[dict]:
    """Return top files to review, with a plain-language reason and why_now."""
    suggestions = []
    seen: set[str] = set()

    for f in impacted_files[:8]:
        path = f["path"]
        if path in seen:
            continue
        seen.add(path)
        why_now = f.get("why_now", "")
        reasons = f.get("reasons", [])
        reason = why_now or (reasons[0] if reasons else "high impact score")
        suggestions.append({
            "reviewer_hint": path.split("/")[-1],
            "reason": f"{path} — {reason}",
            "why_now": why_now,
        })

    return suggestions


# ---------------------------------------------------------------------------
# Enrichment builder — produces the new structured sections
# All logic is generic; no repo-specific hardcoding.
# Never raises — returns safe defaults on any subsystem failure.
# ---------------------------------------------------------------------------

# Generic role → regression hint mapping
_ROLE_REGRESSION_HINTS: dict[str, tuple[str, str]] = {
    "route_handler":  ("route handlers may fail downstream", "api_layer"),
    "service":        ("business logic behavior may change", "service_layer"),
    "repository":     ("database queries or persistence may be affected", "data_layer"),
    "model":          ("data model shape changes may affect all consumers", "data_model"),
    "middleware":     ("request/response middleware may behave differently", "middleware"),
    "config":         ("configuration mismatch across environments is possible", "config"),
    "worker":         ("background job or task processing may be affected", "workers"),
    "client":         ("external API integration behavior may change", "external"),
    "util":           ("shared utility changes may have broad side effects", "utilities"),
    "unknown":        ("downstream behavior may be affected", "general"),
}

# Generic category → risk reason
_CAT_RISK_REASONS: dict[str, str] = {
    "api_contract":         "touches public API contract — callers may break",
    "auth_security":        "touches auth/security layer — regressions are high severity",
    "data_model":           "touches data model/schema — shape changes affect all consumers",
    "business_logic":       "touches core business logic — verify behavior is preserved",
    "persistence":          "touches data access layer — check queries and transactions",
    "external_integration": "touches external integration — verify API contracts",
    "config":               "touches configuration — changes affect runtime behavior broadly",
    "infrastructure":       "touches infrastructure/deployment — environment impact possible",
    "utility_shared":       "touches shared utility — broad side effects possible",
}

# Entrypoint-like file name stems (generic)
_ENTRYPOINT_STEMS = frozenset({
    "app", "main", "server", "index", "manage", "wsgi", "asgi",
    "run", "start", "bootstrap", "entry", "cli",
})


def _is_entrypoint_path(path: str) -> bool:
    basename = path.split("/")[-1]
    stem = basename.rsplit(".", 1)[0].lower() if "." in basename else basename.lower()
    return stem in _ENTRYPOINT_STEMS


def _count_diff_lines(diff: str | None) -> tuple[int, int]:
    """Count added/removed lines from a unified diff."""
    if not diff:
        return 0, 0
    added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    return added, removed


def _build_enriched_sections(
    repository_id: str,
    all_changed: list[str],
    changed_symbols: list[str],
    diff: str | None,
    impacted_files: list[dict],
    review_ordered: list[dict],
    flow_paths: list[dict],
    risk_level: str,
    total_impact_score: float,
    edges: list,
    file_map: dict,
    inbound_counts: dict[str, int],
    outbound_counts: dict[str, int],
    changed_ids: set[str],
    pipeline_notes: list[str],
    used_inferred_edges: bool = False,
) -> dict:
    """
    Build the 8 new enriched sections from existing pipeline data.
    Never raises — each section degrades gracefully.
    """
    partial_failures: list[str] = []

    # ── Section A: Input Extraction ───────────────────────────────────────────
    try:
        added_lines, removed_lines = _count_diff_lines(diff)
        if diff and all_changed:
            analysis_source = "diff+file_list"
        elif diff:
            analysis_source = "diff"
        else:
            analysis_source = "file_list"

        input_extraction = {
            "changed_files": all_changed,
            "changed_symbols": changed_symbols,
            "added_lines": added_lines,
            "removed_lines": removed_lines,
            "analysis_source": analysis_source,
        }
    except Exception as e:
        logger.debug(f"input_extraction failed: {e}")
        input_extraction = {"changed_files": all_changed, "changed_symbols": [], "added_lines": 0, "removed_lines": 0, "analysis_source": "file_list"}
        partial_failures.append("input_extraction")

    # ── Section B: Blast Radius ───────────────────────────────────────────────
    try:
        indirect = [f for f in impacted_files if not f.get("is_directly_changed")]
        direct_dependents = [f for f in indirect if f.get("depth", 99) == 1]
        upstream_deps = [f for f in impacted_files if f.get("is_directly_changed")]

        # Impacted modules = unique top-level path segments of impacted files
        module_set: set[str] = set()
        for f in impacted_files:
            parts = f["path"].split("/")
            if len(parts) >= 2:
                module_set.add(parts[0] if len(parts) == 2 else "/".join(parts[:2]))
        impacted_modules = sorted(module_set)[:8]

        blast_radius = {
            "direct_dependents_count": len(direct_dependents),
            "upstream_dependencies_count": len(upstream_deps),
            "total_blast_radius_count": len(impacted_files),
            "impacted_modules": impacted_modules,
        }
    except Exception as e:
        logger.debug(f"blast_radius failed: {e}")
        blast_radius = {"direct_dependents_count": 0, "upstream_dependencies_count": 0, "total_blast_radius_count": 0, "impacted_modules": []}
        partial_failures.append("blast_radius")

    # ── Section C: Risk Assessment ────────────────────────────────────────────
    try:
        risk_reasons: list[str] = []

        # Collect categories from changed + high-impact files
        all_cats: set[str] = set()
        for f in impacted_files[:12]:
            cat = f.get("primary_category", "")
            if cat:
                all_cats.add(cat)

        for cat in all_cats:
            reason = _CAT_RISK_REASONS.get(cat)
            if reason:
                risk_reasons.append(reason)

        # Entrypoint check
        for path in all_changed:
            if _is_entrypoint_path(path):
                risk_reasons.append(f"touches likely application entrypoint ({path.split('/')[-1]})")
                break

        # High centrality check — files with many inbound dependencies
        high_centrality = [
            f for f in impacted_files
            if f.get("inbound_dependencies", 0) >= 5
        ]
        if high_centrality:
            risk_reasons.append(
                f"affects {len(high_centrality)} high-centrality file(s) with many dependents"
            )

        # Blast radius size signal
        indirect_count = len([f for f in impacted_files if not f.get("is_directly_changed")])
        if indirect_count >= 10:
            risk_reasons.append(f"large blast radius: {indirect_count} indirectly impacted files")
        elif indirect_count >= 5:
            risk_reasons.append(f"moderate blast radius: {indirect_count} indirectly impacted files")

        # Changed symbols signal
        if changed_symbols:
            risk_reasons.append(
                f"modifies {len(changed_symbols)} symbol(s): {', '.join(changed_symbols[:3])}"
            )

        # Docs/test only → lower risk signal
        all_cats_changed = set()
        for path in all_changed:
            p_lower = path.lower()
            if any(t in p_lower for t in ("test", "spec", "docs", "readme", "changelog", "generated")):
                all_cats_changed.add("docs_or_test")
            else:
                all_cats_changed.add("source")
        if all_cats_changed == {"docs_or_test"}:
            risk_reasons = ["only touches docs/tests/generated files — lower structural risk"]

        # Sparse graph confidence penalty — be honest when evidence is weak
        if not edges and not used_inferred_edges:
            risk_reasons.append(
                "no dependency graph available — impact may be underestimated; "
                "re-index to enable relationship-aware analysis"
            )
            # Reduce score when graph is missing — don't claim high confidence
            adjusted_score = min(total_impact_score, 60.0)
        elif used_inferred_edges:
            risk_reasons.append(
                "used inferred dependency relationships — confidence is lower than persisted edges"
            )
            adjusted_score = total_impact_score * 0.90  # slight confidence penalty for inferred
        else:
            # Confidence scales with graph density
            n_files = len(file_map) if file_map else 1
            n_edges = len(edges)
            density = n_edges / max(n_files, 1)
            if density < 0.5:
                risk_reasons.append(
                    f"sparse dependency graph ({n_edges} edges / {n_files} files) — "
                    "confidence is partial"
                )
                adjusted_score = total_impact_score * 0.85  # slight confidence penalty
            else:
                adjusted_score = total_impact_score

        risk_assessment = {
            "overall_risk_level": risk_level,
            "overall_risk_score": round(adjusted_score, 1),
            "risk_reasons": risk_reasons[:7],
        }
    except Exception as e:
        logger.debug(f"risk_assessment failed: {e}")
        risk_assessment = {"overall_risk_level": risk_level, "overall_risk_score": round(total_impact_score, 1), "risk_reasons": []}
        partial_failures.append("risk_assessment")

    # ── Section D: Affected Flows ─────────────────────────────────────────────
    try:
        affected_flows: list[dict] = []
        seen_flow_names: set[str] = set()

        # Use existing flow_paths from FlowService
        for fp in flow_paths[:3]:
            summary = fp.get("summary", "")
            nodes = fp.get("nodes", [])
            node_labels = [n.get("label", n.get("path", "")) for n in nodes[:5]]

            # Infer a human-readable flow name from node types
            node_types = [n.get("type", "") for n in nodes[:3]]
            if "route_handler" in node_types:
                flow_name = "Route Request Flow"
            elif any("worker" in t or "job" in t for t in node_types):
                flow_name = "Background Job Flow"
            elif any("middleware" in t for t in node_types):
                flow_name = "Middleware Flow"
            else:
                flow_name = "Execution Flow"

            # Deduplicate by name
            if flow_name in seen_flow_names:
                flow_name = f"{flow_name} {len(seen_flow_names) + 1}"
            seen_flow_names.add(flow_name)

            # Why relevant: which changed file appears in this flow
            why_relevant = ""
            for path in all_changed[:3]:
                basename = path.split("/")[-1]
                if any(basename in (n.get("label", "") or n.get("path", "")) for n in nodes):
                    why_relevant = f"changed file {basename} appears in this flow"
                    break
            if not why_relevant and summary:
                why_relevant = "flow passes through impacted files"

            affected_flows.append({
                "flow_name": flow_name,
                "confidence": round(fp.get("score", 0.5), 2),
                "summary": summary,
                "path_nodes": node_labels,
                "why_relevant": why_relevant,
            })

        # If no flow_paths, infer flows from role classification of changed files
        if not affected_flows:
            roles_present: set[str] = set()
            for f in impacted_files[:10]:
                # Use file_map to get role via path classification
                fid = f.get("file_id", "")
                proxy = file_map.get(fid)
                if proxy:
                    path = proxy.path if hasattr(proxy, "path") else f.get("path", "")
                    from app.services.flow_service import _classify_file_role
                    role = _classify_file_role(path)
                    roles_present.add(role)

            if "route_handler" in roles_present or "service" in roles_present:
                affected_flows.append({
                    "flow_name": "Route Request Flow",
                    "confidence": 0.55,
                    "summary": "Changes touch route/service layer — request handling flows may be affected.",
                    "path_nodes": [],
                    "why_relevant": "changed files include route or service layer components",
                })
            if "repository" in roles_present or "model" in roles_present:
                affected_flows.append({
                    "flow_name": "Data Access Flow",
                    "confidence": 0.50,
                    "summary": "Changes touch data/persistence layer — database flows may be affected.",
                    "path_nodes": [],
                    "why_relevant": "changed files include repository or model components",
                })
            if any(_is_entrypoint_path(p) for p in all_changed):
                affected_flows.append({
                    "flow_name": "Application Startup Flow",
                    "confidence": 0.70,
                    "summary": "Changes touch the application entrypoint — startup/bootstrap flow may be affected.",
                    "path_nodes": [],
                    "why_relevant": "changed file is a likely application entrypoint",
                })

    except Exception as e:
        logger.debug(f"affected_flows failed: {e}")
        affected_flows = []
        partial_failures.append("affected_flows")

    # ── Section E: Review Priorities ─────────────────────────────────────────
    try:
        review_priorities: list[dict] = []
        seen_paths: set[str] = set()

        for f in review_ordered[:8]:
            path = f.get("path", "")
            if path in seen_paths:
                continue
            seen_paths.add(path)

            fid = f.get("file_id")
            reason = f.get("why_now") or (f.get("reasons", [""])[0] if f.get("reasons") else "high impact score")
            priority_score = f.get("impact_score", 0.0)
            cat = f.get("primary_category", "module")

            review_priorities.append({
                "file_id": fid,
                "path": path,
                "reason": reason,
                "priority_score": round(priority_score, 1),
                "primary_category": cat,
            })

    except Exception as e:
        logger.debug(f"review_priorities failed: {e}")
        review_priorities = []
        partial_failures.append("review_priorities")

    # ── Section F: Possible Regressions ──────────────────────────────────────
    try:
        possible_regressions: list[dict] = []
        seen_areas: set[str] = set()

        # From role classification of impacted files
        for f in impacted_files[:15]:
            fid = f.get("file_id", "")
            proxy = file_map.get(fid)
            if not proxy:
                continue
            path = proxy.path if hasattr(proxy, "path") else f.get("path", "")
            from app.services.flow_service import _classify_file_role
            role = _classify_file_role(path)
            hint, area = _ROLE_REGRESSION_HINTS.get(role, _ROLE_REGRESSION_HINTS["unknown"])
            if area not in seen_areas:
                seen_areas.add(area)
                confidence = "likely" if f.get("impact_score", 0) >= 30 else "possible"
                possible_regressions.append({
                    "description": hint,
                    "affected_area": area,
                    "confidence": confidence,
                })

        # Entrypoint regression
        for path in all_changed:
            if _is_entrypoint_path(path) and "startup" not in seen_areas:
                seen_areas.add("startup")
                possible_regressions.insert(0, {
                    "description": "application startup may fail if entrypoint initialization changes",
                    "affected_area": "startup",
                    "confidence": "likely",
                })
                break

        possible_regressions = possible_regressions[:6]

    except Exception as e:
        logger.debug(f"possible_regressions failed: {e}")
        possible_regressions = []
        partial_failures.append("possible_regressions")

    # ── Section G: Evidence Signals ───────────────────────────────────────────
    try:
        evidence: list[dict] = []

        for f in impacted_files[:6]:
            fid = f.get("file_id", "")
            path = f.get("path", "")
            inbound = f.get("inbound_dependencies", 0)
            cat = f.get("primary_category", "module")
            reasons = f.get("reasons", [])
            sym_hits = f.get("symbol_hits", [])

            if f.get("is_directly_changed"):
                evidence.append({"signal": "directly changed in this PR", "file_path": path, "detail": ""})
            if inbound >= 5:
                evidence.append({"signal": f"high graph centrality — imported by {inbound} files", "file_path": path, "detail": ""})
            if sym_hits:
                evidence.append({"signal": f"references changed symbol: {', '.join(sym_hits[:2])}", "file_path": path, "detail": ""})
            if cat in ("auth_security", "api_contract", "data_model"):
                evidence.append({"signal": f"classified as {cat.replace('_', ' ')} — high-priority layer", "file_path": path, "detail": ""})
            if reasons:
                evidence.append({"signal": reasons[0], "file_path": path, "detail": ""})

        # Entrypoint evidence
        for path in all_changed:
            if _is_entrypoint_path(path):
                evidence.insert(0, {"signal": "file classified as application entrypoint", "file_path": path, "detail": ""})
                break

        # Graph evidence
        if not edges and not used_inferred_edges:
            evidence.append({"signal": "no resolved dependency edges — graph expansion unavailable", "file_path": "", "detail": "re-index to enable relationship-aware analysis"})
        elif used_inferred_edges:
            evidence.append({"signal": "used inferred dependency relationships for impact expansion", "file_path": "", "detail": "confidence lower than persisted dependency edges"})

        # Deduplicate signals
        seen_sigs: set[str] = set()
        deduped_evidence: list[dict] = []
        for ev in evidence:
            key = ev["signal"][:60]
            if key not in seen_sigs:
                seen_sigs.add(key)
                deduped_evidence.append(ev)

        evidence = deduped_evidence[:8]

    except Exception as e:
        logger.debug(f"evidence failed: {e}")
        evidence = []
        partial_failures.append("evidence")

    # ── Section H: Executive Summary ─────────────────────────────────────────
    # Use the existing Gemini-synthesized or deterministic summary as executive_summary
    # (it's already computed upstream — we just expose it in the new field too)
    executive_summary = ""  # will be filled by caller from result["summary"]

    # ── Section I: Impact Confidence + Evidence Breakdown ────────────────────
    try:
        # Count edge types used across all impacted files
        all_etypes: list[str] = []
        for f in impacted_files:
            all_etypes.extend(f.get("edge_types", []))

        _EXACT_TYPES = {"route_to_service", "service_to_model", "uses_symbol", "import", "from_import", "call", "require"}
        _INFERRED_TYPES = {"inferred", "inferred_naming", "inferred_api"}
        _FLOW_TYPES = {"route_to_service", "service_to_model"}
        _SYMBOL_TYPES = {"uses_symbol", "call"}

        exact_count = sum(1 for et in all_etypes if et in _EXACT_TYPES)
        inferred_count = sum(1 for et in all_etypes if et in _INFERRED_TYPES)
        flow_count = sum(1 for et in all_etypes if et in _FLOW_TYPES)
        symbol_count = sum(1 for et in all_etypes if et in _SYMBOL_TYPES)
        semantic_only = sum(1 for f in impacted_files if f.get("reason_tag") == "semantic_reference_only")

        total_evidence = exact_count + inferred_count + flow_count + symbol_count
        if total_evidence == 0:
            impact_confidence = "low"
        elif exact_count + flow_count + symbol_count >= total_evidence * 0.6:
            impact_confidence = "high"
        elif exact_count + flow_count + symbol_count >= total_evidence * 0.3:
            impact_confidence = "medium"
        else:
            impact_confidence = "low"

        # Downgrade if graph is sparse
        if not edges:
            impact_confidence = "low"
        elif impact_confidence == "high" and semantic_only > len(impacted_files) * 0.5:
            impact_confidence = "medium"

        evidence_breakdown = {
            "exact_edges_used": exact_count,
            "inferred_edges_used": inferred_count,
            "flow_links_used": flow_count,
            "symbol_links_used": symbol_count,
            "semantic_only_hits": semantic_only,
            "total_impacted": len(impacted_files),
        }
    except Exception as e:
        logger.debug(f"impact_confidence failed: {e}")
        impact_confidence = "low"
        evidence_breakdown = {}
        partial_failures.append("impact_confidence")

    return {
        "input_extraction": input_extraction,
        "blast_radius": blast_radius,
        "risk_assessment": risk_assessment,
        "affected_flows": affected_flows,
        "review_priorities": review_priorities,
        "possible_regressions": possible_regressions,
        "evidence": evidence,
        "executive_summary": executive_summary,
        "impact_confidence": impact_confidence,
        "evidence_breakdown": evidence_breakdown,
        "partial_failure": len(partial_failures) > 0,
        "partial_failure_reasons": partial_failures,
    }

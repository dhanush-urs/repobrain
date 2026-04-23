"""
graph_service.py — dependency graph resolution and query helpers.

Resolution strategy (generic, no repo-specific logic):
  1. Build a comprehensive lookup index from all indexed file paths.
  2. For each unresolved edge, try multiple generic resolution strategies
     in order of confidence, stopping at the first high-confidence match.
  3. For call edges, consult the Symbol table to find the defining file.
  4. Only persist target_file_id when confidence is HIGH — never guess.

Fallback inference (for sparse graphs):
  When resolved edge density is below a threshold, derive additional
  inferred file-to-file edges from:
    - imports_list / exports_list stored on File rows
    - raw import statement scanning from file content
    - path/module similarity heuristics
    - route → service → repository naming patterns
  Inferred edges are marked with edge_type="inferred" and never persisted.

All heuristics are language-agnostic and work across arbitrary repositories.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models.dependency_edge import DependencyEdge
from app.db.models.file import File
from app.db.models.symbol import Symbol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic file-path index builder
# ---------------------------------------------------------------------------

def _build_path_index(files: list) -> dict[str, str]:
    """
    Build a comprehensive lookup index: normalized_key → file_id.

    Covers all generic resolution patterns:
    - Exact path:           "app/utils.py"          → id
    - Module dot notation:  "app.utils"              → id  (Python-style)
    - Extensionless path:   "app/utils"              → id  (JS/TS-style)
    - Basename only:        "utils"                  → id  (last resort, low confidence)
    - Index file:           "app/utils/index"        → id  (JS index.ts/index.js)
    - Relative-like:        "./utils" "../lib/utils" → id  (stripped)

    Keys are lowercased for case-insensitive matching.
    Values are file IDs.
    When multiple files map to the same key, the shorter path wins
    (shorter = more central / less nested).
    """
    # Source code extensions we care about for resolution
    _CODE_EXTS = {
        ".py", ".js", ".ts", ".tsx", ".jsx",
        ".go", ".rs", ".java", ".rb", ".php",
        ".cs", ".cpp", ".c", ".h", ".swift", ".kt",
        ".vue", ".svelte", ".mjs", ".cjs",
    }

    index: dict[str, str] = {}

    def _set(key: str, fid: str, path: str) -> None:
        """Set key only if not already set, or if new path is shorter (more central)."""
        key = key.lower().strip()
        if not key or len(key) < 2:
            return
        if key not in index:
            index[key] = fid
        else:
            # Prefer shorter path (less nested = more likely to be the canonical definition)
            existing_path = next(
                (f.path for f in files if f.id == index[key]), ""
            )
            if len(path) < len(existing_path):
                index[key] = fid

    for f in files:
        fid = f.id
        path = f.path  # e.g. "app/utils.py" or "src/lib/auth/index.ts"

        # 1. Exact path
        _set(path, fid, path)

        ext = ""
        base_no_ext = path
        if "." in path.split("/")[-1]:
            base_no_ext = path.rsplit(".", 1)[0]
            ext = "." + path.rsplit(".", 1)[1].lower()

        if ext not in _CODE_EXTS:
            continue  # skip non-code files for resolution

        # 2. Extensionless path: "app/utils.py" → "app/utils"
        _set(base_no_ext, fid, path)

        # 3. Module dot notation: "app/utils.py" → "app.utils"
        dot_mod = base_no_ext.replace("/", ".")
        _set(dot_mod, fid, path)

        # 4. Basename without extension: "utils"
        basename = base_no_ext.split("/")[-1]
        if len(basename) >= 3:
            _set(basename, fid, path)

        # 5. Index file shorthand: "app/utils/index.ts" → "app/utils"
        if basename in ("index", "mod", "main", "__init__"):
            parent = "/".join(base_no_ext.split("/")[:-1])
            if parent:
                _set(parent, fid, path)
                _set(parent.replace("/", "."), fid, path)

        # 6. Partial module paths (for deeply nested modules):
        #    "app/api/v1/routes/auth.py" → also index "api.v1.routes.auth", "routes.auth", "auth"
        parts = base_no_ext.split("/")
        for start in range(1, len(parts)):
            sub = ".".join(parts[start:])
            if len(sub) >= 3:
                _set(sub, fid, path)
            sub_path = "/".join(parts[start:])
            if len(sub_path) >= 3:
                _set(sub_path, fid, path)

    return index


# ---------------------------------------------------------------------------
# Generic import/from_import resolution
# ---------------------------------------------------------------------------

def _resolve_import_ref(
    target_ref: str,
    source_ref: str | None,
    path_index: dict[str, str],
    source_file_path: str | None = None,
) -> str | None:
    """
    Resolve an import or from_import edge to a file_id.

    target_ref examples:
      - "os"                          → stdlib, no local match → None
      - "app.utils"                   → try path_index["app.utils"]
      - "fastapi.FastAPI"             → try "fastapi" (strip symbol suffix)
      - "api.auth.router"             → try "api.auth.router", "api/auth/router", "api.auth"
      - "./utils"                     → strip "./" → "utils"
      - "../lib/auth"                 → strip "../" → "lib/auth"

    source_ref (for from_import) is the module part:
      - "from api.auth import router" → source_ref="api.auth", target_ref="api.auth.router"
      - "from .utils import helper"   → source_ref=".utils", target_ref=".utils.helper"

    Returns file_id if resolved with high confidence, else None.
    """
    if not target_ref and not source_ref:
        return None

    candidates: list[str] = []

    # Normalize: strip leading ./ and ../
    def _strip_relative(s: str) -> str:
        s = re.sub(r"^\.{1,2}/", "", s)
        s = re.sub(r"\.\./", "", s)
        return s

    tr = (target_ref or "").strip()
    sr = (source_ref or "").strip()

    # ── Strategy 0: source_ref FIRST for from_import ─────────────────────────
    # source_ref is the module path (e.g. "app.utils") — this is the most
    # reliable resolution target. Try it before target_ref.
    if sr:
        candidates.append(sr)
        # Handle relative imports: ".utils" → resolve relative to source file dir
        if sr.startswith("."):
            stripped = _strip_relative(sr)
            candidates.append(stripped)
            # Also try bare basename: ".utils" → "utils"
            bare = sr.lstrip(".")
            if bare:
                candidates.append(bare)
                candidates.append(bare.split("/")[-1].split(".")[-1])

    # ── Strategy 1: try target_ref directly ──────────────────────────────────
    if tr:
        candidates.append(tr)

    # ── Strategy 2: strip the last component (symbol name) from dotted target_ref
    # e.g. "fastapi.FastAPI" → "fastapi", "api.auth.router" → "api.auth"
    if tr and "." in tr:
        parts = tr.split(".")
        for i in range(len(parts) - 1, 0, -1):
            candidates.append(".".join(parts[:i]))

    # ── Strategy 3: relative path normalization for target_ref ───────────────
    if tr.startswith("."):
        stripped = _strip_relative(tr)
        candidates.append(stripped)
        bare = tr.lstrip(".")
        if bare:
            candidates.append(bare)
            candidates.append(bare.split("/")[-1].split(".")[-1])

    # ── Strategy 4: path-style variants of dot-notation ──────────────────────
    for c in list(candidates):
        if c and "." in c and "/" not in c and not c.startswith("."):
            candidates.append(c.replace(".", "/"))

    # Try each candidate in order — first hit wins
    seen: set[str] = set()
    for c in candidates:
        c_lower = c.lower().strip()
        if not c_lower or len(c_lower) < 2 or c_lower in seen:
            continue
        seen.add(c_lower)
        if c_lower in path_index:
            return path_index[c_lower]

    return None


# ---------------------------------------------------------------------------
# Generic call edge resolution
# ---------------------------------------------------------------------------

def _resolve_call_ref(
    target_ref: str,
    source_file_id: str,
    symbol_index: dict[str, list[tuple[str, str]]],  # name → [(file_id, file_path)]
    path_index: dict[str, str],
    import_map: dict[str, set[str]],  # source_file_id → set of resolved target_file_ids
) -> str | None:
    """
    Resolve a call edge to the file that most likely defines the called symbol.

    Strategy (conservative — high precision over high recall):
    1. Look up symbol name in symbol_index.
    2. If exactly one match → high confidence → return it.
    3. If multiple matches → prefer files that the source file imports.
    4. If still ambiguous → prefer shorter paths (more central definitions).
    5. If no symbol match → return None (do not guess).

    Never resolves to the source file itself (a file doesn't call itself).
    """
    if not target_ref or not symbol_index:
        return None

    name_lower = target_ref.lower().strip()
    if not name_lower or len(name_lower) < 2:
        return None

    # Skip very common generic names that would produce false positives
    _SKIP_NAMES = {
        "print", "len", "str", "int", "float", "list", "dict", "set", "tuple",
        "bool", "type", "range", "enumerate", "zip", "map", "filter", "sorted",
        "open", "super", "self", "cls", "true", "false", "null", "none",
        "undefined", "console", "document", "window", "object", "array",
        "error", "exception", "return", "yield", "raise", "throw",
        "if", "for", "while", "with", "try", "catch", "finally",
        "new", "delete", "typeof", "instanceof",
    }
    if name_lower in _SKIP_NAMES:
        return None

    matches = symbol_index.get(name_lower, [])
    if not matches:
        return None

    # Filter out the source file itself
    matches = [(fid, fp) for fid, fp in matches if fid != source_file_id]
    if not matches:
        return None

    # Exactly one match → high confidence
    if len(matches) == 1:
        return matches[0][0]

    # Multiple matches → prefer files that the source file imports
    imported_fids = import_map.get(source_file_id, set())
    imported_matches = [(fid, fp) for fid, fp in matches if fid in imported_fids]
    if len(imported_matches) == 1:
        return imported_matches[0][0]
    if imported_matches:
        # Among imported matches, prefer shorter path
        return min(imported_matches, key=lambda x: len(x[1]))[0]

    # No import relationship — prefer shorter path (more central definition)
    # Only do this if there are ≤3 candidates to avoid false positives
    if len(matches) <= 3:
        return min(matches, key=lambda x: len(x[1]))[0]

    # Too ambiguous — do not resolve
    return None


# ---------------------------------------------------------------------------
# Fallback inferred edge inference
# ---------------------------------------------------------------------------

# Patterns for extracting import targets from source content
# Language-agnostic — covers Python, JS/TS, Go, Ruby, PHP, Java, etc.
_IMPORT_PATTERNS = [
    # Python: from X import Y  /  from .X import Y  /  from ..X import Y
    re.compile(r"^\s*from\s+([\w\.]+)\s+import\s+", re.MULTILINE),
    # Python: import X  /  import X as Y
    re.compile(r"^\s*import\s+([\w\.]+)(?:\s+as\s+\w+)?\s*$", re.MULTILINE),
    # JS/TS: import ... from 'X'  /  import ... from "X"
    re.compile(r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]\s*;?\s*$""", re.MULTILINE),
    # JS/TS: require('X')  /  require("X")
    re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    # JS/TS: export ... from 'X'
    re.compile(r"""^\s*export\s+.*?from\s+['"]([^'"]+)['"]\s*;?\s*$""", re.MULTILINE),
    # Go: import "X"  /  import ( "X" )
    re.compile(r"""["']([\w/\.\-]+)["']\s*$""", re.MULTILINE),
    # Ruby: require 'X'  /  require_relative 'X'
    re.compile(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]\s*$""", re.MULTILINE),
]

# Known stdlib / third-party prefixes to skip (avoid false positives)
# These are generic top-level names that are never local files
_STDLIB_PREFIXES = frozenset({
    "os", "sys", "re", "io", "json", "math", "time", "datetime", "pathlib",
    "typing", "collections", "itertools", "functools", "operator", "copy",
    "abc", "enum", "dataclasses", "contextlib", "logging", "warnings",
    "threading", "multiprocessing", "subprocess", "socket", "http", "urllib",
    "email", "html", "xml", "csv", "sqlite3", "hashlib", "hmac", "secrets",
    "base64", "struct", "array", "queue", "heapq", "bisect", "weakref",
    "gc", "inspect", "ast", "dis", "traceback", "pprint", "textwrap",
    # Common third-party packages (never local)
    "fastapi", "flask", "django", "starlette", "uvicorn", "gunicorn",
    "sqlalchemy", "alembic", "pydantic", "celery", "redis", "aioredis",
    "requests", "httpx", "aiohttp", "boto3", "botocore", "google",
    "numpy", "pandas", "scipy", "sklearn", "torch", "tensorflow",
    "pytest", "unittest", "mock", "faker",
    "react", "vue", "angular", "next", "nuxt", "express", "koa", "hapi",
    "lodash", "axios", "fetch", "moment", "dayjs", "uuid", "dotenv",
    "webpack", "vite", "rollup", "babel", "typescript",
    "fmt", "log", "net", "http", "io", "os", "path", "strings", "strconv",
    "encoding", "errors", "context", "sync", "atomic", "runtime",
})


def _extract_import_targets(content: str) -> list[str]:
    """
    Extract import target strings from file content using generic patterns.
    Returns a deduplicated list of raw import targets (not yet resolved to file IDs).
    Never raises.
    """
    if not content:
        return []

    targets: list[str] = []
    seen: set[str] = set()

    for pat in _IMPORT_PATTERNS:
        try:
            for m in pat.finditer(content):
                raw = m.group(1).strip()
                if not raw or len(raw) < 2:
                    continue
                # Skip stdlib/third-party top-level names
                top = raw.split(".")[0].split("/")[0].lower()
                if top in _STDLIB_PREFIXES:
                    continue
                # Skip absolute URLs, node builtins, etc.
                if raw.startswith(("http", "node:", "@types/", "~")):
                    continue
                if raw not in seen:
                    seen.add(raw)
                    targets.append(raw)
        except Exception:
            pass

    return targets


def _infer_edges_from_content(
    files_with_content: list[tuple],  # (id, path, content)
    path_index: dict[str, str],
    existing_edges: set[tuple[str, str]],  # (src_id, tgt_id) already resolved
) -> list[tuple[str, str, str]]:
    """
    Infer file-to-file edges by scanning import statements in file content.

    Returns list of (source_file_id, target_file_id, "inferred") tuples.
    Only returns edges not already in existing_edges.
    Never raises.
    """
    inferred: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set(existing_edges)

    for fid, path, content in files_with_content:
        if not content:
            continue
        targets = _extract_import_targets(content)
        for raw_target in targets:
            resolved = _resolve_import_ref(raw_target, None, path_index)
            if resolved and resolved != fid:
                key = (fid, resolved)
                if key not in seen:
                    seen.add(key)
                    inferred.append((fid, resolved, "inferred"))

    return inferred


def _infer_edges_from_imports_list(
    files_with_imports: list[tuple],  # (id, path, imports_list)
    path_index: dict[str, str],
    existing_edges: set[tuple[str, str]],
) -> list[tuple[str, str, str]]:
    """
    Infer edges from the pre-stored imports_list field on File rows.
    imports_list is a newline or comma-separated list of import targets stored
    during parsing — faster than scanning raw content.

    Returns list of (source_file_id, target_file_id, "inferred") tuples.
    """
    inferred: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set(existing_edges)

    for fid, path, imports_list in files_with_imports:
        if not imports_list:
            continue
        # Split on newlines, commas, or semicolons
        raw_targets = re.split(r"[\n,;]+", imports_list)
        for raw in raw_targets:
            raw = raw.strip()
            if not raw or len(raw) < 2:
                continue
            top = raw.split(".")[0].split("/")[0].lower()
            if top in _STDLIB_PREFIXES:
                continue
            resolved = _resolve_import_ref(raw, None, path_index)
            if resolved and resolved != fid:
                key = (fid, resolved)
                if key not in seen:
                    seen.add(key)
                    inferred.append((fid, resolved, "inferred"))

    return inferred


def _infer_edges_from_naming(
    files: list,  # File rows with id, path, file_kind
    existing_edges: set[tuple[str, str]],
) -> list[tuple[str, str, str]]:
    """
    Infer edges from architectural naming heuristics.

    Generic patterns (no repo-specific names):
    - route/controller → service with matching name stem
    - service → repository/dao with matching name stem
    - service → model with matching name stem
    - test file → source file with matching name stem

    Example: "user_routes.py" → "user_service.py" → "user_repository.py"

    Only infers when there is a clear naming match — never guesses randomly.
    """
    inferred: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set(existing_edges)

    # Role keyword sets — used for classification and stem extraction
    _ROLE_KEYWORDS: dict[str, list[str]] = {
        "route":      ["routes", "route", "router", "controller", "controllers",
                       "handler", "handlers", "endpoint", "endpoints", "view", "views", "api"],
        "service":    ["services", "service", "usecase", "use_case", "manager", "business"],
        "repository": ["repositories", "repository", "repo", "dao", "store", "crud",
                       "database", "db", "query"],
        "model":      ["models", "model", "schema", "schemas", "entity", "entities", "orm"],
        "test":       ["tests", "test", "spec", "specs"],
    }

    # Downstream role for each upstream role
    _DOWNSTREAM: dict[str, tuple[str, ...]] = {
        "route":   ("service", "repository", "model"),
        "service": ("repository", "model"),
        "test":    ("route", "service", "repository", "model"),
    }

    def _classify_and_stem(stem: str) -> tuple[str | None, str]:
        """
        Return (role, entity_stem) for a file stem like 'user_service' or 'UserController'.
        Strips the role keyword to get the entity stem.
        Returns (None, '') if no role keyword found.
        """
        stem_lower = stem.lower()
        for role, keywords in _ROLE_KEYWORDS.items():
            for kw in sorted(keywords, key=len, reverse=True):  # longest first
                # Match as a whole word segment (surrounded by _ or at boundary)
                # e.g. "user_service" → strip "_service" → "user"
                # e.g. "UserService"  → strip "Service"  → "User"
                # e.g. "user_routes"  → strip "_routes"  → "user"
                patterns = [
                    f"_{kw}$",       # suffix: user_service → user
                    f"^{kw}_",       # prefix: service_user → user
                    f"{kw}s?$",      # camelCase suffix: UserService → User
                    f"^{kw}s?",      # camelCase prefix: ServiceUser → User
                ]
                for pat in patterns:
                    cleaned = re.sub(pat, "", stem_lower, flags=re.IGNORECASE).strip("_- ")
                    if cleaned and cleaned != stem_lower and len(cleaned) >= 2:
                        return role, cleaned
        return None, ""

    # Build stem → role → [(file_id, path)]
    from collections import defaultdict
    stem_role_map: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for f in files:
        fid = f.id if hasattr(f, "id") else f[0]
        path = f.path if hasattr(f, "path") else f[1]
        basename = path.split("/")[-1]
        stem = basename.rsplit(".", 1)[0] if "." in basename else basename

        role, entity_stem = _classify_and_stem(stem)
        if role and entity_stem:
            stem_role_map[entity_stem][role].append((fid, path))

    # Connect upstream → downstream by entity stem
    for entity_stem, role_files in stem_role_map.items():
        for upstream_role, downstream_roles in _DOWNSTREAM.items():
            upstream_files = role_files.get(upstream_role, [])
            for downstream_role in downstream_roles:
                downstream_files = role_files.get(downstream_role, [])
                for src_fid, src_path in upstream_files:
                    for tgt_fid, tgt_path in downstream_files:
                        if src_fid == tgt_fid:
                            continue
                        key = (src_fid, tgt_fid)
                        if key not in seen:
                            seen.add(key)
                            inferred.append((src_fid, tgt_fid, "inferred_naming"))

    return inferred


def compute_inferred_edges(
    db: Session,
    repository_id: str,
    resolved_edges: list[tuple[str, str, str]],  # (src, tgt, etype)
    all_files: list,  # lightweight file rows (id, path, ...)
    sparsity_threshold: float = 0.15,
    max_inferred: int = 500,
) -> list[tuple[str, str, str]]:
    """
    Compute inferred edges when resolved edge density is below the threshold.

    Sparsity check: if (resolved_edges / files) < threshold, run inference.

    Inference pipeline (in order of confidence):
    1. imports_list field (pre-stored, fast)
    2. Content scan (slower, only for source files without imports_list)
    3. Naming heuristics (architectural patterns)

    Returns list of (source_file_id, target_file_id, edge_type) tuples.
    Never raises — returns [] on any failure.
    """
    try:
        n_files = len(all_files)
        n_resolved = len(resolved_edges)

        if n_files == 0:
            return []

        density = n_resolved / n_files
        if density >= sparsity_threshold:
            # Graph is dense enough — no inference needed
            logger.debug(
                "compute_inferred_edges: density=%.2f >= threshold=%.2f, skipping inference",
                density, sparsity_threshold,
            )
            return []

        logger.info(
            "compute_inferred_edges: density=%.2f < threshold=%.2f, running inference for repo %s",
            density, sparsity_threshold, repository_id,
        )

        # Build path index from all_files
        # all_files rows: (id, path, language, file_kind, line_count, is_gen, is_vendor, is_test)
        class _FProxy:
            __slots__ = ("id", "path")
            def __init__(self, row): self.id = row[0]; self.path = row[1]

        file_proxies = [_FProxy(r) for r in all_files]
        path_index = _build_path_index(file_proxies)

        # Build existing edge set for deduplication
        existing: set[tuple[str, str]] = {(s, t) for s, t, _ in resolved_edges if s and t}

        inferred: list[tuple[str, str, str]] = []

        # ── Step 1: imports_list field ────────────────────────────────────────
        try:
            import_rows = list(db.execute(
                select(File.id, File.path, File.imports_list).where(
                    File.repository_id == repository_id,
                    File.imports_list.isnot(None),
                    File.is_generated.is_(False),
                    File.is_vendor.is_(False),
                )
            ).all())
            if import_rows:
                step1 = _infer_edges_from_imports_list(import_rows, path_index, existing)
                inferred.extend(step1)
                logger.debug("compute_inferred_edges: step1 (imports_list) → %d edges", len(step1))
        except Exception as e:
            logger.debug("imports_list inference failed: %s", e)

        # Update existing set with step1 results
        existing.update((s, t) for s, t, _ in inferred)

        # ── Step 2: content scan (only for files without imports_list) ────────
        # Limit to source files to avoid scanning large binary/doc files
        _SOURCE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rb", ".php",
                        ".java", ".cs", ".rs", ".vue", ".svelte", ".mjs", ".cjs"}
        try:
            # Only scan files that didn't have imports_list
            files_with_imports_list = {r[0] for r in import_rows} if import_rows else set()
            content_rows = list(db.execute(
                select(File.id, File.path, File.content).where(
                    File.repository_id == repository_id,
                    File.is_generated.is_(False),
                    File.is_vendor.is_(False),
                    File.content.isnot(None),
                )
            ).all())
            # Filter to source files not already covered by imports_list
            content_rows = [
                r for r in content_rows
                if r[0] not in files_with_imports_list
                and any(r[1].lower().endswith(ext) for ext in _SOURCE_EXTS)
            ]
            if content_rows:
                step2 = _infer_edges_from_content(content_rows, path_index, existing)
                inferred.extend(step2)
                logger.debug("compute_inferred_edges: step2 (content scan) → %d edges", len(step2))
        except Exception as e:
            logger.debug("content scan inference failed: %s", e)

        existing.update((s, t) for s, t, _ in inferred)

        # ── Step 3: naming heuristics ─────────────────────────────────────────
        try:
            step3 = _infer_edges_from_naming(file_proxies, existing)
            inferred.extend(step3)
            logger.debug("compute_inferred_edges: step3 (naming) → %d edges", len(step3))
        except Exception as e:
            logger.debug("naming inference failed: %s", e)

        # Cap total inferred edges
        result = inferred[:max_inferred]
        logger.info(
            "compute_inferred_edges: total inferred=%d (capped at %d) for repo %s",
            len(result), max_inferred, repository_id,
        )
        return result

    except Exception as e:
        logger.warning("compute_inferred_edges failed (graceful): %s", e)
        return []


# ---------------------------------------------------------------------------
# Generic file-path index builder
# ---------------------------------------------------------------------------

def _build_path_index(files: list) -> dict[str, str]:
    """
    Build a comprehensive lookup index: normalized_key → file_id.

    Covers all generic resolution patterns:
    - Exact path:           "app/utils.py"          → id
    - Module dot notation:  "app.utils"              → id  (Python-style)
    - Extensionless path:   "app/utils"              → id  (JS/TS-style)
    - Basename only:        "utils"                  → id  (last resort, low confidence)
    - Index file:           "app/utils/index"        → id  (JS index.ts/index.js)
    - Relative-like:        "./utils" "../lib/utils" → id  (stripped)

    Keys are lowercased for case-insensitive matching.
    Values are file IDs.
    When multiple files map to the same key, the shorter path wins
    (shorter = more central / less nested).
    """
    # Source code extensions we care about for resolution
    _CODE_EXTS = {
        ".py", ".js", ".ts", ".tsx", ".jsx",
        ".go", ".rs", ".java", ".rb", ".php",
        ".cs", ".cpp", ".c", ".h", ".swift", ".kt",
        ".vue", ".svelte", ".mjs", ".cjs",
    }

    index: dict[str, str] = {}

    def _set(key: str, fid: str, path: str) -> None:
        """Set key only if not already set, or if new path is shorter (more central)."""
        key = key.lower().strip()
        if not key or len(key) < 2:
            return
        if key not in index:
            index[key] = fid
        else:
            # Prefer shorter path (less nested = more likely to be the canonical definition)
            existing_path = next(
                (f.path for f in files if f.id == index[key]), ""
            )
            if len(path) < len(existing_path):
                index[key] = fid

    for f in files:
        fid = f.id
        path = f.path  # e.g. "app/utils.py" or "src/lib/auth/index.ts"

        # 1. Exact path
        _set(path, fid, path)

        ext = ""
        base_no_ext = path
        if "." in path.split("/")[-1]:
            base_no_ext = path.rsplit(".", 1)[0]
            ext = "." + path.rsplit(".", 1)[1].lower()

        if ext not in _CODE_EXTS:
            continue  # skip non-code files for resolution

        # 2. Extensionless path: "app/utils.py" → "app/utils"
        _set(base_no_ext, fid, path)

        # 3. Module dot notation: "app/utils.py" → "app.utils"
        dot_mod = base_no_ext.replace("/", ".")
        _set(dot_mod, fid, path)

        # 4. Basename without extension: "utils"
        basename = base_no_ext.split("/")[-1]
        if len(basename) >= 3:
            _set(basename, fid, path)

        # 5. Index file shorthand: "app/utils/index.ts" → "app/utils"
        if basename in ("index", "mod", "main", "__init__"):
            parent = "/".join(base_no_ext.split("/")[:-1])
            if parent:
                _set(parent, fid, path)
                _set(parent.replace("/", "."), fid, path)

        # 6. Partial module paths (for deeply nested modules):
        #    "app/api/v1/routes/auth.py" → also index "api.v1.routes.auth", "routes.auth", "auth"
        parts = base_no_ext.split("/")
        for start in range(1, len(parts)):
            sub = ".".join(parts[start:])
            if len(sub) >= 3:
                _set(sub, fid, path)
            sub_path = "/".join(parts[start:])
            if len(sub_path) >= 3:
                _set(sub_path, fid, path)

    return index


# ---------------------------------------------------------------------------
# Main resolution entry point
# ---------------------------------------------------------------------------

class GraphService:
    def __init__(self, db: Session):
        self.db = db

    def resolve_repository_dependencies(self, repository_id: str) -> int:
        """
        Resolve unresolved DependencyEdge rows to concrete target_file_id values.

        Runs after parsing. Builds comprehensive in-memory indexes then applies
        generic resolution heuristics per edge type.

        Returns the number of newly resolved edges.
        """
        # Fetch all unresolved edges for this repo
        edges = list(self.db.scalars(
            select(DependencyEdge).where(
                DependencyEdge.repository_id == repository_id,
                DependencyEdge.target_file_id.is_(None),
            )
        ).all())

        if not edges:
            return 0

        # ── Build indexes ────────────────────────────────────────────────────

        # 1. File path index
        files = list(self.db.scalars(
            select(File).where(File.repository_id == repository_id)
        ).all())
        path_index = _build_path_index(files)

        # 2. Symbol index: name_lower → [(file_id, file_path)]
        symbols = list(self.db.execute(
            select(Symbol.name, Symbol.file_id, File.path)
            .join(File, File.id == Symbol.file_id)
            .where(Symbol.repository_id == repository_id)
        ).all())
        symbol_index: dict[str, list[tuple[str, str]]] = {}
        for sym_name, sym_file_id, sym_file_path in symbols:
            key = sym_name.lower().strip()
            if key and len(key) >= 2:
                symbol_index.setdefault(key, []).append((sym_file_id, sym_file_path))

        # 3. Import map: source_file_id → set of resolved target_file_ids
        #    (built from edges we resolve in this pass — import/from_import first)
        import_map: dict[str, set[str]] = {}

        # ── Pass 1: resolve import and from_import edges ─────────────────────
        resolved_count = 0
        # Build file_id → path map for relative import resolution
        file_id_to_path: dict[str, str] = {f.id: f.path for f in files}

        for edge in edges:
            if edge.edge_type not in ("import", "from_import", "require"):
                continue
            source_path = file_id_to_path.get(edge.source_file_id or "", "")
            target_id = _resolve_import_ref(
                edge.target_ref or "",
                edge.source_ref,
                path_index,
                source_file_path=source_path,
            )
            if target_id and target_id != edge.source_file_id:
                edge.target_file_id = target_id
                resolved_count += 1
                # Update import map for call resolution
                if edge.source_file_id:
                    import_map.setdefault(edge.source_file_id, set()).add(target_id)

        # Flush import resolutions before call resolution
        try:
            self.db.flush()
        except Exception as e:
            logger.warning(f"flush after import resolution failed: {e}")
            self.db.rollback()

        # Also populate import_map from already-resolved edges in DB
        try:
            existing_resolved = list(self.db.execute(
                select(DependencyEdge.source_file_id, DependencyEdge.target_file_id)
                .where(
                    DependencyEdge.repository_id == repository_id,
                    DependencyEdge.edge_type.in_(["import", "from_import", "require"]),
                    DependencyEdge.target_file_id.isnot(None),
                    DependencyEdge.source_file_id.isnot(None),
                )
            ).all())
            for src_fid, tgt_fid in existing_resolved:
                import_map.setdefault(src_fid, set()).add(tgt_fid)
        except Exception as e:
            logger.warning(f"import_map population failed: {e}")

        # ── Pass 2: resolve call edges using symbol index + import map ────────
        for edge in edges:
            if edge.edge_type != "call" or edge.target_file_id is not None:
                continue
            target_id = _resolve_call_ref(
                edge.target_ref or "",
                edge.source_file_id or "",
                symbol_index,
                path_index,
                import_map,
            )
            if target_id and target_id != edge.source_file_id:
                edge.target_file_id = target_id
                resolved_count += 1

        # ── Commit all resolutions ────────────────────────────────────────────
        try:
            self.db.commit()
        except Exception as e:
            logger.error(f"resolve_repository_dependencies commit failed: {e}")
            self.db.rollback()
            return 0

        # ── Deduplication pass: remove duplicate (src, tgt, type) edges ──────
        # After resolution, multiple unresolved edges may have resolved to the
        # same (source, target, type) triple. Keep only one per triple.
        try:
            from sqlalchemy import text as _sql_text
            # Find all resolved edges for this repo
            resolved_edges = list(self.db.execute(
                select(
                    DependencyEdge.id,
                    DependencyEdge.source_file_id,
                    DependencyEdge.target_file_id,
                    DependencyEdge.edge_type,
                ).where(
                    DependencyEdge.repository_id == repository_id,
                    DependencyEdge.source_file_id.isnot(None),
                    DependencyEdge.target_file_id.isnot(None),
                )
            ).all())

            # Group by (src, tgt, type) — keep first, delete rest
            seen_triples: set[tuple[str, str, str]] = set()
            ids_to_delete: list[str] = []
            for eid, src, tgt, etype in resolved_edges:
                triple = (src, tgt, etype)
                if triple in seen_triples:
                    ids_to_delete.append(eid)
                else:
                    seen_triples.add(triple)

            if ids_to_delete:
                from sqlalchemy import delete as _delete
                # Delete in batches of 500
                for i in range(0, len(ids_to_delete), 500):
                    batch = ids_to_delete[i:i+500]
                    self.db.execute(
                        _delete(DependencyEdge).where(DependencyEdge.id.in_(batch))
                    )
                self.db.commit()
                logger.info(
                    f"resolve_repository_dependencies: removed {len(ids_to_delete)} duplicate edges "
                    f"for repo {repository_id}"
                )
        except Exception as dedup_err:
            logger.warning(f"deduplication pass failed (non-fatal): {dedup_err}")
            self.db.rollback()

        logger.info(
            f"resolve_repository_dependencies: resolved {resolved_count} edges "
            f"for repo {repository_id}"
        )
        return resolved_count

    def get_incoming_dependencies(self, file_id: str) -> list[DependencyEdge]:
        """Find all files that depend on this file."""
        return list(self.db.scalars(
            select(DependencyEdge).where(DependencyEdge.target_file_id == file_id)
        ).all())

    def get_outgoing_dependencies(self, file_id: str) -> list[DependencyEdge]:
        """Find all files this file depends on."""
        return list(self.db.scalars(
            select(DependencyEdge).where(DependencyEdge.source_file_id == file_id)
        ).all())

    def get_symbol_usage(self, repository_id: str, symbol_name: str) -> list[DependencyEdge]:
        """Find where a symbol (function/class name) is called."""
        return list(self.db.scalars(
            select(DependencyEdge).where(
                DependencyEdge.repository_id == repository_id,
                DependencyEdge.edge_type == "call",
                DependencyEdge.target_ref == symbol_name,
            )
        ).all())

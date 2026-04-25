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
    # Java/Kotlin/Scala: import X.Y.Z;  /  import X.Y.*;
    re.compile(r"^\s*import\s+([\w\.]+(?:\.\*)?)\s*;", re.MULTILINE),
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

# Java/JVM stdlib package prefixes — never local files
_JVM_STDLIB_PREFIXES = frozenset({
    "java", "javax", "jakarta", "android", "kotlin", "scala", "groovy",
    "org.w3c", "org.xml", "org.ietf", "org.omg",
    "sun", "jdk", "com.sun", "com.oracle",
})

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
                top = raw.split(".")[0].split("/")[0].lower()
                # Skip Python/JS/Go stdlib/third-party top-level names
                if top in _STDLIB_PREFIXES:
                    continue
                # Skip JVM stdlib packages (java.*, javax.*, etc.)
                if top in _JVM_STDLIB_PREFIXES:
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


# Pattern for Java/C#/C++ constructor instantiation: new ClassName(...)
# Captures class names that start with uppercase (PascalCase) — local classes
_CONSTRUCTOR_PATTERN = re.compile(r"\bnew\s+([A-Z][A-Za-z0-9_]*)\s*\(", re.MULTILINE)

# Java/C# JVM stdlib class name prefixes to skip
_JVM_STDLIB_CLASSES = frozenset({
    "String", "Integer", "Long", "Double", "Float", "Boolean", "Byte", "Short", "Character",
    "Object", "Class", "Thread", "Runnable", "Exception", "RuntimeException", "Error",
    "StringBuilder", "StringBuffer", "ArrayList", "LinkedList", "HashMap", "HashSet",
    "TreeMap", "TreeSet", "LinkedHashMap", "LinkedHashSet", "Arrays", "Collections",
    "Math", "System", "Runtime", "Process", "ProcessBuilder",
    "File", "Path", "Paths", "Files", "InputStream", "OutputStream", "Reader", "Writer",
    "BufferedReader", "BufferedWriter", "FileReader", "FileWriter", "PrintWriter",
    "Scanner", "Random", "Date", "Calendar", "LocalDate", "LocalTime", "LocalDateTime",
    "BigDecimal", "BigInteger", "Optional", "Stream", "List", "Map", "Set",
    # Swing/AWT (JVM GUI stdlib)
    "JFrame", "JPanel", "JButton", "JLabel", "JTextField", "JPasswordField",
    "JTextArea", "JScrollPane", "JTable", "JList", "JComboBox", "JCheckBox",
    "JRadioButton", "JMenuBar", "JMenu", "JMenuItem", "JToolBar", "JDialog",
    "JOptionPane", "JFileChooser", "JColorChooser", "JTabbedPane", "JSplitPane",
    "JProgressBar", "JSlider", "JSpinner", "JTree", "JPopupMenu",
    "BorderLayout", "FlowLayout", "GridLayout", "GridBagLayout", "BoxLayout",
    "Color", "Font", "Dimension", "Point", "Rectangle", "ImageIcon",
    "ActionEvent", "MouseEvent", "KeyEvent", "WindowEvent", "ItemEvent",
    # JDBC
    "Connection", "Statement", "PreparedStatement", "ResultSet", "DriverManager",
    # Common test/util
    "Exception", "IllegalArgumentException", "NullPointerException",
    "IllegalStateException", "UnsupportedOperationException",
})


def _extract_constructor_targets(content: str) -> list[str]:
    """
    Extract class names from constructor instantiations (new ClassName(...)).
    Only returns PascalCase names that are likely local application classes.
    Never raises.
    """
    if not content:
        return []

    targets: list[str] = []
    seen: set[str] = set()

    try:
        for m in _CONSTRUCTOR_PATTERN.finditer(content):
            name = m.group(1).strip()
            if not name or len(name) < 2:
                continue
            # Skip known JVM stdlib class names
            if name in _JVM_STDLIB_CLASSES:
                continue
            # Skip names that look like constants (ALL_CAPS)
            if name.isupper():
                continue
            if name not in seen:
                seen.add(name)
                targets.append(name)
    except Exception:
        pass

    return targets


def _infer_edges_from_content(
    files_with_content: list[tuple],  # (id, path, content)
    path_index: dict[str, str],
    existing_edges: set[tuple[str, str]],  # (src_id, tgt_id) already resolved
) -> list[tuple[str, str, str]]:
    """
    Infer file-to-file edges by scanning import statements and constructor
    instantiations in file content.

    Returns list of (source_file_id, target_file_id, "inferred") tuples.
    Only returns edges not already in existing_edges.
    Never raises.
    """
    inferred: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set(existing_edges)

    for fid, path, content in files_with_content:
        if not content:
            continue

        # Step A: import-based edges
        targets = _extract_import_targets(content)
        for raw_target in targets:
            resolved = _resolve_import_ref(raw_target, None, path_index)
            if resolved and resolved != fid:
                key = (fid, resolved)
                if key not in seen:
                    seen.add(key)
                    inferred.append((fid, resolved, "inferred"))

        # Step B: constructor instantiation edges (new ClassName(...))
        # Useful for Java/C#/C++ where local classes are instantiated without imports
        ctor_targets = _extract_constructor_targets(content)
        for class_name in ctor_targets:
            resolved = _resolve_import_ref(class_name, None, path_index)
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

        # ── Archetype-aware edge enrichment ──────────────────────────────────
        # After basic resolution, add archetype-specific semantic edges
        try:
            from app.services.archetype_service import ArchetypeService
            
            archetype_svc = ArchetypeService(self.db)
            archetype_data = archetype_svc.detect_archetypes(repository_id)
            primary_archetype = archetype_data.get("primary_archetype", "generic_codebase")
            
            # Add archetype-specific edges
            archetype_counts = enrich_archetype_specific_edges(
                self.db, repository_id, primary_archetype
            )
            
            # Add general semantic edges (existing logic)
            semantic_counts = enrich_repository_edges(self.db, repository_id)
            
            logger.info(
                f"resolve_repository_dependencies: resolved {resolved_count} basic edges, "
                f"added {sum(archetype_counts.values())} archetype edges ({primary_archetype}), "
                f"added {sum(semantic_counts.values())} semantic edges for repo {repository_id}"
            )
            
        except Exception as enrich_err:
            logger.warning(f"edge enrichment failed (non-fatal): {enrich_err}")

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

    def get_graph_health(self, repository_id: str) -> dict:
        """
        Assess graph health and sparsity for a repository.
        
        Returns:
        {
            "total_files": int,
            "total_edges": int,
            "edges_per_file": float,
            "is_sparse": bool,
            "edge_types": dict[str, int],
            "quality": "high" | "medium" | "low",
            "recommendations": list[str]
        }
        """
        try:
            # Count files
            total_files = self.db.scalar(
                select(func.count(File.id)).where(
                    File.repository_id == repository_id,
                    File.is_generated.is_(False),
                    File.is_vendor.is_(False),
                )
            ) or 0

            # Count edges by type
            edge_rows = list(self.db.execute(
                select(DependencyEdge.edge_type, func.count(DependencyEdge.id))
                .where(
                    DependencyEdge.repository_id == repository_id,
                    DependencyEdge.source_file_id.isnot(None),
                    DependencyEdge.target_file_id.isnot(None),
                )
                .group_by(DependencyEdge.edge_type)
            ).all())

            edge_types = {etype: count for etype, count in edge_rows}
            total_edges = sum(edge_types.values())

            # Calculate metrics
            edges_per_file = total_edges / max(total_files, 1)
            is_sparse = total_edges < max(3, total_files * 0.1)  # Less than 3 edges or 10% of files

            # Determine quality
            if total_edges >= total_files * 0.5 and edges_per_file >= 2.0:
                quality = "high"
            elif total_edges >= 3 and edges_per_file >= 0.5:
                quality = "medium"
            else:
                quality = "low"

            # Generate recommendations
            recommendations = []
            if is_sparse:
                recommendations.append("Graph is sparse — consider re-indexing with updated parsers")
            if total_files > 10 and total_edges == 0:
                recommendations.append("No relationships detected — check if repository uses supported languages/frameworks")
            if edge_types.get("import", 0) == 0 and total_files > 5:
                recommendations.append("No import relationships found — may need language-specific parser updates")

            return {
                "total_files": total_files,
                "total_edges": total_edges,
                "edges_per_file": round(edges_per_file, 2),
                "is_sparse": is_sparse,
                "edge_types": edge_types,
                "quality": quality,
                "recommendations": recommendations,
            }

        except Exception as e:
            logger.error(f"get_graph_health failed for repo {repository_id}: {e}")
            return {
                "total_files": 0,
                "total_edges": 0,
                "edges_per_file": 0.0,
                "is_sparse": True,
                "edge_types": {},
                "quality": "low",
                "recommendations": ["Graph health check failed"],
            }


# ---------------------------------------------------------------------------
# Semantic edge enrichment — derives higher-level typed edges
# ---------------------------------------------------------------------------
# Runs AFTER resolve_repository_dependencies.
# Uses already-resolved import/call edges + symbol table + file roles to
# produce route_to_service, service_to_model, uses_symbol, and inferred_api edges.
# All logic is generic — no repo-specific hardcoding.
# ---------------------------------------------------------------------------

# File role classification (mirrors flow_service._classify_file_role)
_ROLE_KEYWORDS_ENRICH: dict[str, list[str]] = {
    "route":      ["route", "router", "routes", "controller", "handler", "endpoint", "view", "api"],
    "service":    ["service", "services", "usecase", "use_case", "manager", "business"],
    "model":      ["model", "models", "schema", "schemas", "entity", "entities", "orm", "dto"],
    "repository": ["repo", "repository", "dao", "store", "crud", "db", "database", "query"],
    "frontend":   ["frontend", "client", "ui", "web", "pages", "components", "views", "scripts"],
    "config":     ["config", "settings", "configuration", "env", "constants"],
}

# Integration / external service keywords
_INTEGRATION_KEYWORDS = frozenset({
    "firebase", "supabase", "openai", "anthropic", "gemini", "stripe",
    "twilio", "sendgrid", "aws", "s3", "dynamodb", "redis", "celery",
    "elasticsearch", "mongo", "postgres", "mysql", "sqlite",
    "sqlalchemy", "alembic", "prisma", "mongoose",
})

# Frontend API call patterns
_FRONTEND_FETCH_PATTERNS = [
    # fetch('/path', ...) or fetch("path", ...)
    re.compile(r"""fetch\s*\(\s*['"`]([^'"`\s]+)['"`]"""),
    # axios.get/post/put/delete/patch('/path')
    re.compile(r"""axios\s*\.\s*(?:get|post|put|delete|patch|request)\s*\(\s*['"`]([^'"`\s]+)['"`]""", re.IGNORECASE),
    # api.get/post/... patterns (common API client wrappers)
    re.compile(r"""(?:api|client|http)\s*\.\s*(?:get|post|put|delete|patch)\s*\(\s*['"`]([^'"`\s]+)['"`]""", re.IGNORECASE),
    # Template literal: fetch(`/api/${...}`) — extract static prefix
    re.compile(r"""fetch\s*\(\s*`([^`$\s]+)"""),
]

# Backend route decorator patterns
_BACKEND_ROUTE_PATTERNS = [
    # FastAPI / Flask / Starlette: @app.get("/path") or @router.post("/path")
    re.compile(r"""@(?:app|router|blueprint|api)\s*\.\s*(?:get|post|put|delete|patch|options|head)\s*\(\s*['"]([^'"]+)['"]""", re.IGNORECASE),
    # Express: app.get('/path', ...) or router.post('/path', ...)
    re.compile(r"""(?:app|router)\s*\.\s*(?:get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""", re.IGNORECASE),
    # Django: path('route', ...) or re_path(r'route', ...)
    re.compile(r"""(?:path|re_path)\s*\(\s*r?['"]([^'"]+)['"]""", re.IGNORECASE),
]


def _classify_file_role_enrich(path: str) -> str:
    """Classify a file's role from its path. Returns role string or 'unknown'."""
    path_lower = path.lower().replace("\\", "/")
    parts = path_lower.split("/")
    basename = parts[-1].rsplit(".", 1)[0] if "." in parts[-1] else parts[-1]

    for role, keywords in _ROLE_KEYWORDS_ENRICH.items():
        for part in parts + [basename]:
            for kw in keywords:
                if kw == part or part.startswith(kw + "_") or part.endswith("_" + kw):
                    return role
                if kw in part and len(kw) >= 4:
                    return role
    return "unknown"


def _normalize_route_path(path: str) -> str:
    """Normalize a route path for matching: lowercase, strip trailing slash, ensure leading slash."""
    path = path.strip().lower()
    if not path.startswith("/"):
        path = "/" + path
    path = path.rstrip("/")
    # Replace dynamic segments: /users/{id} → /users/:param, /users/:id → /users/:param
    path = re.sub(r"\{[^}]+\}", ":param", path)
    path = re.sub(r":[a-zA-Z_][a-zA-Z0-9_]*", ":param", path)
    path = re.sub(r"\$\{[^}]+\}", ":param", path)
    return path


def _paths_match(frontend_path: str, backend_path: str) -> float:
    """
    Return a confidence score [0, 1] for how well two route paths match.
    0 = no match, 1 = exact match.
    """
    fp = _normalize_route_path(frontend_path)
    bp = _normalize_route_path(backend_path)

    if fp == bp:
        return 1.0

    # Exact match after normalization
    if fp.rstrip("/") == bp.rstrip("/"):
        return 0.95

    # One is a prefix of the other (e.g. /api/chat matches /api/chat/{id})
    if fp.startswith(bp) or bp.startswith(fp):
        return 0.75

    # Segment similarity: count matching segments
    fp_parts = [p for p in fp.split("/") if p]
    bp_parts = [p for p in bp.split("/") if p]
    if not fp_parts or not bp_parts:
        return 0.0

    # Must have same number of segments for a reasonable match
    if len(fp_parts) != len(bp_parts):
        return 0.0

    matching = sum(
        1 for a, b in zip(fp_parts, bp_parts)
        if a == b or a == ":param" or b == ":param"
    )
    score = matching / len(fp_parts)
    return round(score * 0.65, 2) if score >= 0.8 else 0.0  # only return if 80%+ segments match


def enrich_repository_edges(db: Session, repository_id: str) -> dict:
    """
    Derive higher-level semantic edges from already-resolved import/call edges.

    Produces:
    - route_to_service: route file → service file (via call/import edges)
    - service_to_model: service file → model/schema file (via import edges)
    - uses_symbol: file → defining file (via exact symbol resolution)
    - inferred_api: frontend file → backend route file (via URL matching)

    Returns a dict with counts of each edge type added.
    Never raises — returns partial results on failure.
    """
    counts: dict[str, int] = {
        "route_to_service": 0,
        "service_to_model": 0,
        "uses_symbol": 0,
        "inferred_api": 0,
        "skipped_duplicates": 0,
    }

    try:
        # ── Load all files with their roles ──────────────────────────────────
        file_rows = list(db.execute(
            select(File.id, File.path, File.language, File.file_kind, File.content)
            .where(
                File.repository_id == repository_id,
                File.is_generated.is_(False),
                File.is_vendor.is_(False),
            )
        ).all())

        if not file_rows:
            return counts

        file_map: dict[str, dict] = {}
        for fid, path, lang, kind, content in file_rows:
            role = _classify_file_role_enrich(path)
            file_map[fid] = {
                "id": fid, "path": path, "language": lang,
                "file_kind": kind, "content": content or "",
                "role": role,
            }

        # ── Load already-resolved edges ───────────────────────────────────────
        resolved_edges = list(db.execute(
            select(
                DependencyEdge.source_file_id,
                DependencyEdge.target_file_id,
                DependencyEdge.edge_type,
                DependencyEdge.target_ref,
                DependencyEdge.source_ref,
            ).where(
                DependencyEdge.repository_id == repository_id,
                DependencyEdge.source_file_id.isnot(None),
                DependencyEdge.target_file_id.isnot(None),
            )
        ).all())

        # Build adjacency: source_file_id → set of target_file_ids
        outgoing: dict[str, set[str]] = defaultdict(set)
        for src, tgt, etype, tref, sref in resolved_edges:
            outgoing[src].add(tgt)

        # Build existing edge set for deduplication
        existing_triples: set[tuple[str, str, str]] = {
            (src, tgt, etype) for src, tgt, etype, _, _ in resolved_edges
        }

        # ── Load symbol table ─────────────────────────────────────────────────
        symbol_rows = list(db.execute(
            select(Symbol.name, Symbol.file_id, Symbol.symbol_type)
            .join(File, File.id == Symbol.file_id)
            .where(Symbol.repository_id == repository_id)
        ).all())

        # symbol_name_lower → [(file_id, symbol_type)]
        symbol_index: dict[str, list[tuple[str, str]]] = {}
        for sym_name, sym_file_id, sym_type in symbol_rows:
            key = sym_name.lower().strip()
            if key and len(key) >= 2:
                symbol_index.setdefault(key, []).append((sym_file_id, sym_type))

        new_edges: list[dict] = []

        def _add_edge(src: str, tgt: str, etype: str, confidence: float,
                      target_ref: str | None = None, source_ref: str | None = None) -> bool:
            """Add edge if not duplicate. Returns True if added."""
            if src == tgt:
                return False
            triple = (src, tgt, etype)
            if triple in existing_triples:
                counts["skipped_duplicates"] += 1
                return False
            existing_triples.add(triple)
            new_edges.append({
                "repository_id": repository_id,
                "source_file_id": src,
                "target_file_id": tgt,
                "edge_type": etype,
                "source_ref": source_ref,
                "target_ref": target_ref,
            })
            return True

        # ── 1. route_to_service edges ─────────────────────────────────────────
        # Route files that import/call service files
        route_files = {fid: fi for fid, fi in file_map.items() if fi["role"] == "route"}
        service_files = {fid: fi for fid, fi in file_map.items() if fi["role"] == "service"}

        for route_fid, route_fi in route_files.items():
            for tgt_fid in outgoing.get(route_fid, set()):
                if tgt_fid in service_files:
                    added = _add_edge(
                        route_fid, tgt_fid, "route_to_service",
                        confidence=0.9,
                        source_ref=route_fi["path"].split("/")[-1],
                        target_ref=service_files[tgt_fid]["path"].split("/")[-1],
                    )
                    if added:
                        counts["route_to_service"] += 1

        # ── 2. service_to_model edges ─────────────────────────────────────────
        # Service files that import/call model/schema files
        model_files = {fid: fi for fid, fi in file_map.items() if fi["role"] == "model"}

        for svc_fid, svc_fi in service_files.items():
            for tgt_fid in outgoing.get(svc_fid, set()):
                if tgt_fid in model_files:
                    added = _add_edge(
                        svc_fid, tgt_fid, "service_to_model",
                        confidence=0.9,
                        source_ref=svc_fi["path"].split("/")[-1],
                        target_ref=model_files[tgt_fid]["path"].split("/")[-1],
                    )
                    if added:
                        counts["service_to_model"] += 1

        # Also check route → model directly (some routes use models directly)
        for route_fid, route_fi in route_files.items():
            for tgt_fid in outgoing.get(route_fid, set()):
                if tgt_fid in model_files:
                    added = _add_edge(
                        route_fid, tgt_fid, "service_to_model",
                        confidence=0.8,
                        source_ref=route_fi["path"].split("/")[-1],
                        target_ref=model_files[tgt_fid]["path"].split("/")[-1],
                    )
                    if added:
                        counts["service_to_model"] += 1

        # ── 3. uses_symbol edges ──────────────────────────────────────────────
        # For each resolved call edge, if the target symbol is in the symbol table,
        # create a uses_symbol edge with higher semantic meaning
        for src, tgt, etype, tref, sref in resolved_edges:
            if etype != "call" or not tref:
                continue
            sym_matches = symbol_index.get(tref.lower(), [])
            if not sym_matches:
                continue
            # Only create uses_symbol if the target file matches the resolved edge target
            for sym_fid, sym_type in sym_matches:
                if sym_fid == tgt and sym_fid != src:
                    added = _add_edge(
                        src, tgt, "uses_symbol",
                        confidence=1.0,
                        source_ref=sref,
                        target_ref=tref,
                    )
                    if added:
                        counts["uses_symbol"] += 1
                    break

        # ── 4. inferred_api edges (frontend → backend) ────────────────────────
        # Parse frontend files for fetch/axios calls, match against backend routes
        frontend_files = [
            fi for fi in file_map.values()
            if fi["role"] == "frontend"
            or any(fi["path"].lower().endswith(ext) for ext in (".js", ".ts", ".jsx", ".tsx"))
            and not any(kw in fi["path"].lower() for kw in ("node_modules", "dist/", ".next/", "build/"))
        ]

        # Build backend route index: normalized_path → (file_id, handler_symbol)
        backend_routes: list[tuple[str, str, str | None]] = []  # (norm_path, file_id, handler)
        for fid, fi in file_map.items():
            if fi["role"] not in ("route", "unknown"):
                continue
            content = fi["content"]
            if not content:
                continue
            for pat in _BACKEND_ROUTE_PATTERNS:
                for m in pat.finditer(content):
                    route_path = m.group(1).strip()
                    if route_path and len(route_path) >= 1:
                        norm = _normalize_route_path(route_path)
                        backend_routes.append((norm, fid, route_path))

        if frontend_files and backend_routes:
            for fe_fi in frontend_files:
                content = fe_fi["content"]
                if not content:
                    continue
                # Extract frontend API calls
                for pat in _FRONTEND_FETCH_PATTERNS:
                    for m in pat.finditer(content):
                        fe_path = m.group(1).strip()
                        if not fe_path or len(fe_path) < 2:
                            continue
                        # Skip non-path strings
                        if fe_path.startswith(("http://", "https://", "ws://", "wss://")):
                            # Strip host to get path
                            try:
                                from urllib.parse import urlparse
                                parsed = urlparse(fe_path)
                                fe_path = parsed.path or fe_path
                            except Exception:
                                continue

                        # Match against backend routes
                        best_conf = 0.0
                        best_backend_fid = None
                        best_route = None

                        for norm_backend, be_fid, orig_route in backend_routes:
                            if be_fid == fe_fi["id"]:
                                continue
                            conf = _paths_match(fe_path, norm_backend)
                            if conf > best_conf:
                                best_conf = conf
                                best_backend_fid = be_fid
                                best_route = orig_route

                        if best_backend_fid and best_conf >= 0.65:
                            added = _add_edge(
                                fe_fi["id"], best_backend_fid, "inferred_api",
                                confidence=best_conf,
                                source_ref=fe_path,
                                target_ref=best_route,
                            )
                            if added:
                                counts["inferred_api"] += 1

        # ── 5. HTML asset edges (html_loads_script, html_loads_style) ─────────
        # Detect <script src="..."> and <link rel="stylesheet" href="..."> in HTML files
        _SCRIPT_SRC_RE = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
        _LINK_CSS_RE = re.compile(r'<link[^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
        _LINK_REL_RE = re.compile(r'rel=["\']stylesheet["\']', re.IGNORECASE)

        html_files = [fi for fi in file_map.values() if fi["path"].lower().endswith((".html", ".htm"))]
        path_index_local = {fi["path"].lower(): fi["id"] for fi in file_map.values()}

        for html_fi in html_files:
            content = html_fi.get("content") or ""
            if not content:
                continue
            # script src edges
            for m in _SCRIPT_SRC_RE.finditer(content):
                src = m.group(1).strip().lstrip("./")
                # Try to resolve to an indexed file
                for candidate_path, candidate_fid in path_index_local.items():
                    if candidate_path.endswith(src.lower()) or src.lower() in candidate_path:
                        if candidate_fid != html_fi["id"]:
                            added = _add_edge(html_fi["id"], candidate_fid, "html_loads_script",
                                              confidence=0.9, source_ref=html_fi["path"].split("/")[-1], target_ref=src)
                            if added:
                                counts.setdefault("html_loads_script", 0)
                                counts["html_loads_script"] += 1
                            break
            # link stylesheet edges
            for m in _LINK_CSS_RE.finditer(content):
                # Only if rel="stylesheet" is present nearby
                tag_start = max(0, m.start() - 50)
                tag_context = content[tag_start:m.end() + 50]
                if not _LINK_REL_RE.search(tag_context):
                    continue
                href = m.group(1).strip().lstrip("./")
                for candidate_path, candidate_fid in path_index_local.items():
                    if candidate_path.endswith(href.lower()) or href.lower() in candidate_path:
                        if candidate_fid != html_fi["id"]:
                            added = _add_edge(html_fi["id"], candidate_fid, "html_loads_style",
                                              confidence=0.9, source_ref=html_fi["path"].split("/")[-1], target_ref=href)
                            if added:
                                counts.setdefault("html_loads_style", 0)
                                counts["html_loads_style"] += 1
                            break

        # ── 6. Data / config file edges ───────────────────────────────────────
        # Detect open("..."), Path(...).read_text(), json.load, yaml.safe_load,
        # dotenv loading, os.getenv mapped to known config files
        _DATA_READ_PATTERNS = [
            re.compile(r"""open\s*\(\s*['"]([^'"]+\.(json|csv|txt|yaml|yml|toml|xml|sql))['"]\s*""", re.IGNORECASE),
            re.compile(r"""Path\s*\(\s*['"]([^'"]+\.(json|csv|txt|yaml|yml|toml|xml))['"]\s*\)""", re.IGNORECASE),
            re.compile(r"""load_dotenv\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.IGNORECASE),
            re.compile(r"""dotenv_values\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.IGNORECASE),
        ]
        _CONFIG_FILE_EXTS = {".env", ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf"}
        _DATA_FILE_EXTS = {".json", ".csv", ".txt", ".xml", ".sql", ".db", ".sqlite"}

        # Build index of data/config files
        data_config_files: dict[str, str] = {}  # basename_lower → file_id
        for fi in file_map.values():
            p = fi["path"].lower()
            ext = "." + p.rsplit(".", 1)[-1] if "." in p.split("/")[-1] else ""
            basename = p.split("/")[-1]
            if ext in _CONFIG_FILE_EXTS or ext in _DATA_FILE_EXTS or basename.startswith(".env"):
                data_config_files[basename] = fi["id"]
                data_config_files[p] = fi["id"]

        if data_config_files:
            for fid, fi in file_map.items():
                if fi.get("is_test") or fi.get("is_generated") or fi.get("is_vendor"):
                    continue
                content = fi.get("content") or ""
                if not content:
                    continue
                role = fi.get("role", "unknown")
                for pat in _DATA_READ_PATTERNS:
                    for m in pat.finditer(content):
                        ref_path = m.group(1).strip()
                        ref_basename = ref_path.split("/")[-1].lower()
                        target_fid = data_config_files.get(ref_basename) or data_config_files.get(ref_path.lower())
                        if target_fid and target_fid != fid:
                            # Determine edge type from role and file type
                            ref_ext = "." + ref_basename.rsplit(".", 1)[-1] if "." in ref_basename else ""
                            if ref_ext in _CONFIG_FILE_EXTS or ref_basename.startswith(".env"):
                                etype = "service_reads_config" if role == "service" else "route_reads_config"
                            else:
                                etype = "service_reads_data" if role == "service" else "route_reads_data"
                            added = _add_edge(fid, target_fid, etype, confidence=0.85,
                                              source_ref=fi["path"].split("/")[-1], target_ref=ref_path)
                            if added:
                                counts.setdefault(etype, 0)
                                counts[etype] += 1

        # ── 7. Response / return edges ────────────────────────────────────────
        # Add reverse semantic edges to show data flows back:
        # service_returns_to_route, route_responds_to_frontend
        # These are derived from existing route_to_service and inferred_api edges.
        # Mark as inferred (confidence 0.7) since they are semantic inverses.
        try:
            # For each route_to_service edge, add service_returns_to_route (reverse semantic)
            for src, tgt, etype, tref, sref in resolved_edges:
                if etype == "route_to_service":
                    # service returns data back to route
                    added = _add_edge(tgt, src, "service_returns_to_route", confidence=0.7,
                                      source_ref=tref, target_ref=sref)
                    if added:
                        counts.setdefault("service_returns_to_route", 0)
                        counts["service_returns_to_route"] += 1

            # For each inferred_api edge (frontend → route), add route_responds_to_frontend
            for src, tgt, etype, tref, sref in resolved_edges:
                if etype == "inferred_api":
                    added = _add_edge(tgt, src, "route_responds_to_frontend", confidence=0.7,
                                      source_ref=sref, target_ref=tref)
                    if added:
                        counts.setdefault("route_responds_to_frontend", 0)
                        counts["route_responds_to_frontend"] += 1
        except Exception as _resp_err:
            logger.debug(f"response edge inference failed: {_resp_err}")

        # ── Persist new edges ─────────────────────────────────────────────────
        if new_edges:
            try:
                for edge_data in new_edges:
                    edge = DependencyEdge(
                        repository_id=edge_data["repository_id"],
                        source_file_id=edge_data["source_file_id"],
                        target_file_id=edge_data["target_file_id"],
                        edge_type=edge_data["edge_type"],
                        source_ref=edge_data.get("source_ref"),
                        target_ref=edge_data.get("target_ref"),
                    )
                    db.add(edge)
                db.commit()
                logger.info(
                    f"enrich_repository_edges: added {len(new_edges)} semantic edges "
                    f"for repo {repository_id}: {counts}"
                )
            except Exception as e:
                logger.error(f"enrich_repository_edges commit failed: {e}")
                db.rollback()
                return counts

    except Exception as e:
        logger.error(f"enrich_repository_edges failed: {e}", exc_info=True)

    return counts



def enrich_archetype_specific_edges(
    db: Session,
    repository_id: str,
    archetype: str = "generic_codebase"
) -> dict:
    """
    Add archetype-specific semantic edges based on repository type.
    
    Supports:
    - java_desktop_gui: GUI navigation, action listeners, screen-to-DB edges
    - frontend_app: Component tree, router-to-page, asset loading (enhanced)
    - cli_tool: Command dispatch, parser-to-handler
    - library_sdk: Public API to implementation
    - ml_ai_project: Pipeline stage edges
    
    Returns counts of edges added per type.
    Never raises — returns partial results on failure.
    """
    counts: dict[str, int] = {
        "gui_navigation": 0,
        "gui_action": 0,
        "gui_db_access": 0,
        "component_tree": 0,
        "router_page": 0,
        "cli_command": 0,
        "public_api": 0,
        "pipeline_stage": 0,
        "skipped_duplicates": 0,
    }

    try:
        # Load all files
        file_rows = list(db.execute(
            select(File.id, File.path, File.language, File.content, File.is_test)
            .where(
                File.repository_id == repository_id,
                File.is_generated.is_(False),
                File.is_vendor.is_(False),
                File.is_test.is_(False),
            )
        ).all())

        if not file_rows:
            return counts

        file_map: dict[str, dict] = {}
        for fid, path, lang, content, is_test in file_rows:
            file_map[fid] = {
                "id": fid,
                "path": path,
                "language": lang,
                "content": content or "",
            }

        # Build existing edge set for deduplication
        existing_edges = set(db.execute(
            select(DependencyEdge.source_file_id, DependencyEdge.target_file_id, DependencyEdge.edge_type)
            .where(
                DependencyEdge.repository_id == repository_id,
                DependencyEdge.source_file_id.isnot(None),
                DependencyEdge.target_file_id.isnot(None),
            )
        ).all())

        existing_triples = {(src, tgt, etype) for src, tgt, etype in existing_edges}

        new_edges: list[dict] = []

        def _add_edge(src: str, tgt: str, etype: str, source_ref: str | None = None, target_ref: str | None = None) -> bool:
            """Add edge if not duplicate. Returns True if added."""
            if src == tgt:
                return False
            triple = (src, tgt, etype)
            if triple in existing_triples:
                counts["skipped_duplicates"] += 1
                return False
            existing_triples.add(triple)
            new_edges.append({
                "repository_id": repository_id,
                "source_file_id": src,
                "target_file_id": tgt,
                "edge_type": etype,
                "source_ref": source_ref,
                "target_ref": target_ref,
            })
            return True

        # Branch by archetype
        if archetype == "java_desktop_gui":
            counts.update(_extract_java_gui_edges(file_map, _add_edge))

        elif archetype == "frontend_app":
            counts.update(_extract_frontend_edges(file_map, _add_edge))

        elif archetype == "cli_tool":
            counts.update(_extract_cli_edges(file_map, _add_edge))

        elif archetype == "library_sdk":
            counts.update(_extract_library_edges(file_map, _add_edge))

        elif archetype == "ml_ai_project":
            counts.update(_extract_ml_pipeline_edges(file_map, _add_edge))

        # Persist new edges
        if new_edges:
            try:
                for edge_data in new_edges:
                    edge = DependencyEdge(
                        repository_id=edge_data["repository_id"],
                        source_file_id=edge_data["source_file_id"],
                        target_file_id=edge_data["target_file_id"],
                        edge_type=edge_data["edge_type"],
                        source_ref=edge_data.get("source_ref"),
                        target_ref=edge_data.get("target_ref"),
                    )
                    db.add(edge)
                db.commit()
                logger.info(
                    f"enrich_archetype_specific_edges ({archetype}): added {len(new_edges)} edges "
                    f"for repo {repository_id}: {counts}"
                )
            except Exception as e:
                logger.error(f"enrich_archetype_specific_edges commit failed: {e}")
                db.rollback()

    except Exception as e:
        logger.error(f"enrich_archetype_specific_edges failed: {e}", exc_info=True)

    return counts


def _extract_java_gui_edges(file_map: dict, add_edge) -> dict:
    """Extract Java Swing/AWT GUI navigation and interaction edges."""
    counts = {"gui_navigation": 0, "gui_action": 0, "gui_db_access": 0}

    # Build class name index: ClassName → file_id
    class_index: dict[str, str] = {}
    for fid, fi in file_map.items():
        if not fi["path"].endswith(".java"):
            continue
        # Extract class name from path (e.g., "Login.java" → "Login")
        basename = fi["path"].split("/")[-1]
        if basename.endswith(".java"):
            class_name = basename[:-5]  # Remove ".java"
            class_index[class_name.lower()] = fid

    # Patterns for GUI navigation
    _NEW_SCREEN_RE = re.compile(r'new\s+([A-Z][a-zA-Z0-9_]*)\s*\(', re.MULTILINE)
    _SETVISIBLE_RE = re.compile(r'([a-zA-Z][a-zA-Z0-9_]*)\s*\.\s*setVisible\s*\(\s*true\s*\)', re.MULTILINE)

    # Patterns for DB access
    _DB_KEYWORDS = ["mysql", "database", "connection", "query", "statement", "resultset", "jdbc"]

    for fid, fi in file_map.items():
        if not fi["path"].endswith(".java"):
            continue

        content = fi["content"]
        if not content:
            continue

        # 1. GUI navigation edges: new SomeScreen() → SomeScreen file
        for m in _NEW_SCREEN_RE.finditer(content):
            target_class = m.group(1)
            target_fid = class_index.get(target_class.lower())
            if target_fid and target_fid != fid:
                if add_edge(fid, target_fid, "gui_navigation", source_ref=fi["path"].split("/")[-1], target_ref=target_class):
                    counts["gui_navigation"] += 1

        # 2. GUI action edges: someScreen.setVisible(true) → someScreen file
        for m in _SETVISIBLE_RE.finditer(content):
            var_name = m.group(1)
            # Try to infer class from variable name (e.g., "loginScreen" → "Login")
            # This is heuristic — capitalize first letter
            inferred_class = var_name[0].upper() + var_name[1:] if var_name else ""
            # Remove common suffixes
            for suffix in ["Screen", "Frame", "Window", "Dialog", "Panel"]:
                if inferred_class.endswith(suffix):
                    inferred_class = inferred_class[:-len(suffix)]
                    break
            target_fid = class_index.get(inferred_class.lower())
            if target_fid and target_fid != fid:
                if add_edge(fid, target_fid, "gui_action", source_ref=fi["path"].split("/")[-1], target_ref=inferred_class):
                    counts["gui_action"] += 1

        # 3. GUI-to-DB edges: screen files calling DB helpers
        content_lower = content.lower()
        if any(kw in content_lower for kw in _DB_KEYWORDS):
            # Find DB helper files
            for target_fid, target_fi in file_map.items():
                if target_fid == fid:
                    continue
                target_path_lower = target_fi["path"].lower()
                if any(kw in target_path_lower for kw in _DB_KEYWORDS):
                    # Check if this screen references the DB helper class
                    target_class = target_fi["path"].split("/")[-1].replace(".java", "")
                    if target_class.lower() in content_lower:
                        if add_edge(fid, target_fid, "gui_db_access", source_ref=fi["path"].split("/")[-1], target_ref=target_class):
                            counts["gui_db_access"] += 1

    return counts


def _extract_frontend_edges(file_map: dict, add_edge) -> dict:
    """Extract frontend component tree and router edges."""
    counts = {"component_tree": 0, "router_page": 0}

    # Component import pattern: import SomeComponent from './SomeComponent'
    _COMPONENT_IMPORT_RE = re.compile(
        r'import\s+(?:\{[^}]+\}|[A-Z][a-zA-Z0-9_]*)\s+from\s+["\']([^"\']+)["\']',
        re.MULTILINE
    )

    # Router pattern: <Route path="..." component={SomeComponent} />
    _ROUTE_COMPONENT_RE = re.compile(
        r'<Route[^>]+component=\{([A-Z][a-zA-Z0-9_]*)\}',
        re.MULTILINE
    )

    # Build component index: component name → file_id
    component_index: dict[str, str] = {}
    for fid, fi in file_map.items():
        if fi["path"].endswith((".tsx", ".jsx", ".ts", ".js", ".vue", ".svelte")):
            basename = fi["path"].split("/")[-1]
            # Extract component name (e.g., "Button.tsx" → "Button")
            comp_name = basename.rsplit(".", 1)[0]
            if comp_name and comp_name[0].isupper():
                component_index[comp_name.lower()] = fid

    for fid, fi in file_map.items():
        if not fi["path"].endswith((".tsx", ".jsx", ".ts", ".js", ".vue")):
            continue

        content = fi["content"]
        if not content:
            continue

        # 1. Component tree edges: parent imports child
        for m in _COMPONENT_IMPORT_RE.finditer(content):
            import_path = m.group(1)
            # Try to resolve to a component file
            for comp_name, comp_fid in component_index.items():
                if comp_name in import_path.lower() and comp_fid != fid:
                    if add_edge(fid, comp_fid, "component_tree", source_ref=fi["path"].split("/")[-1], target_ref=comp_name):
                        counts["component_tree"] += 1
                    break

        # 2. Router-to-page edges
        for m in _ROUTE_COMPONENT_RE.finditer(content):
            comp_name = m.group(1)
            comp_fid = component_index.get(comp_name.lower())
            if comp_fid and comp_fid != fid:
                if add_edge(fid, comp_fid, "router_page", source_ref=fi["path"].split("/")[-1], target_ref=comp_name):
                    counts["router_page"] += 1

    return counts


def _extract_cli_edges(file_map: dict, add_edge) -> dict:
    """Extract CLI command dispatch edges."""
    counts = {"cli_command": 0}

    # CLI command pattern: @click.command() or @typer.command()
    _CLI_COMMAND_RE = re.compile(
        r'@(?:click|typer)\.command\s*\(\s*["\']?([a-zA-Z0-9_-]+)?["\']?\s*\)',
        re.MULTILINE
    )

    # Function definition pattern
    _FUNC_DEF_RE = re.compile(r'def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', re.MULTILINE)

    # Build function index: function name → file_id
    func_index: dict[str, str] = {}
    for fid, fi in file_map.items():
        if not fi["path"].endswith(".py"):
            continue
        content = fi["content"]
        if not content:
            continue
        for m in _FUNC_DEF_RE.finditer(content):
            func_name = m.group(1)
            func_index[func_name.lower()] = fid

    # Find CLI entry files (main, cli, __main__)
    cli_entry_files = [
        fid for fid, fi in file_map.items()
        if any(kw in fi["path"].lower() for kw in ("__main__", "cli.py", "main.py", "cmd.py"))
    ]

    for entry_fid in cli_entry_files:
        entry_fi = file_map[entry_fid]
        content = entry_fi["content"]
        if not content:
            continue

        # Find command decorators and link to handler functions
        for m in _CLI_COMMAND_RE.finditer(content):
            # Find the function defined right after this decorator
            func_match = _FUNC_DEF_RE.search(content, m.end())
            if func_match:
                func_name = func_match.group(1)
                # Check if this function is defined in another file
                target_fid = func_index.get(func_name.lower())
                if target_fid and target_fid != entry_fid:
                    if add_edge(entry_fid, target_fid, "cli_command", source_ref=entry_fi["path"].split("/")[-1], target_ref=func_name):
                        counts["cli_command"] += 1

    return counts


def _extract_library_edges(file_map: dict, add_edge) -> dict:
    """Extract library public API to implementation edges."""
    counts = {"public_api": 0}

    # Find __init__.py or index.js/ts files (public API entry points)
    api_files = [
        fid for fid, fi in file_map.items()
        if fi["path"].endswith(("__init__.py", "index.js", "index.ts", "mod.rs", "lib.rs"))
    ]

    # Export pattern: from .module import Something
    _EXPORT_RE = re.compile(
        r'from\s+\.([a-zA-Z0-9_]+)\s+import\s+([a-zA-Z0-9_,\s]+)',
        re.MULTILINE
    )

    for api_fid in api_files:
        api_fi = file_map[api_fid]
        content = api_fi["content"]
        if not content:
            continue

        # Find exports and link to implementation files
        for m in _EXPORT_RE.finditer(content):
            module_name = m.group(1)
            # Try to find the implementation file
            for target_fid, target_fi in file_map.items():
                if target_fid == api_fid:
                    continue
                if module_name.lower() in target_fi["path"].lower():
                    if add_edge(api_fid, target_fid, "public_api", source_ref=api_fi["path"].split("/")[-1], target_ref=module_name):
                        counts["public_api"] += 1
                    break

    return counts


def _extract_ml_pipeline_edges(file_map: dict, add_edge) -> dict:
    """Extract ML/data pipeline stage edges."""
    counts = {"pipeline_stage": 0}

    # ML stage keywords
    _STAGE_KEYWORDS = {
        "load": ["load", "loader", "dataset", "data"],
        "preprocess": ["preprocess", "transform", "clean", "prepare"],
        "train": ["train", "fit", "model"],
        "inference": ["inference", "predict", "infer", "evaluate"],
        "output": ["output", "save", "export", "postprocess"],
    }

    # Build stage index: stage → [file_ids]
    stage_index: dict[str, list[str]] = {stage: [] for stage in _STAGE_KEYWORDS}

    for fid, fi in file_map.items():
        if not fi["path"].endswith((".py", ".ipynb")):
            continue
        path_lower = fi["path"].lower()
        for stage, keywords in _STAGE_KEYWORDS.items():
            if any(kw in path_lower for kw in keywords):
                stage_index[stage].append(fid)

    # Create pipeline edges: load → preprocess → train → inference → output
    pipeline_order = ["load", "preprocess", "train", "inference", "output"]
    for i in range(len(pipeline_order) - 1):
        src_stage = pipeline_order[i]
        tgt_stage = pipeline_order[i + 1]
        for src_fid in stage_index[src_stage]:
            for tgt_fid in stage_index[tgt_stage]:
                if src_fid != tgt_fid:
                    src_fi = file_map[src_fid]
                    tgt_fi = file_map[tgt_fid]
                    if add_edge(src_fid, tgt_fid, "pipeline_stage", source_ref=src_fi["path"].split("/")[-1], target_ref=tgt_fi["path"].split("/")[-1]):
                        counts["pipeline_stage"] += 1

    return counts

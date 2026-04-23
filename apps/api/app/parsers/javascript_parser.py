import re
from pathlib import Path


IMPORT_RE = re.compile(
    r"""^\s*import\s+(?:.+?\s+from\s+)?['"]([^'"]+)['"]\s*;?""",
    re.MULTILINE,
)

REQUIRE_RE = re.compile(
    r"""require\(\s*['"]([^'"]+)['"]\s*\)"""
)

CLASS_RE = re.compile(
    r"""^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)""",
    re.MULTILINE,
)

FUNCTION_RE = re.compile(
    r"""^\s*(?:export\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(""",
    re.MULTILINE,
)

ARROW_FUNCTION_RE = re.compile(
    r"""^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>""",
    re.MULTILINE,
)

# Named import extraction: import { Foo, Bar } from './module'
NAMED_IMPORT_RE = re.compile(
    r"""import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# Default import: import Foo from './module'
DEFAULT_IMPORT_RE = re.compile(
    r"""import\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)


class JavaScriptParser:
    language = "JavaScript/TypeScript"

    SUPPORTED_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def parse(self, file_path: Path) -> dict:
        try:
            source = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return {
                "symbols": [],
                "dependencies": [],
                "error": f"Failed to read file: {exc}",
            }

        symbols = []
        dependencies = []
        # Track imported names for call deduplication
        imported_names: set[str] = set()
        import_targets: list[str] = []

        # ── Imports ──────────────────────────────────────────────────────────
        for match in IMPORT_RE.finditer(source):
            target = match.group(1)
            dependencies.append(
                {
                    "edge_type": "import",
                    "source_ref": None,
                    "target_ref": target,
                }
            )
            import_targets.append(target)

        for match in REQUIRE_RE.finditer(source):
            target = match.group(1)
            dependencies.append(
                {
                    "edge_type": "require",
                    "source_ref": None,
                    "target_ref": target,
                }
            )
            import_targets.append(target)

        # Track named imports for call resolution
        for match in NAMED_IMPORT_RE.finditer(source):
            names_str = match.group(1)
            for name in re.split(r"[,\s]+", names_str):
                name = name.strip()
                if name and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                    imported_names.add(name)

        for match in DEFAULT_IMPORT_RE.finditer(source):
            imported_names.add(match.group(1))

        # ── Symbols ──────────────────────────────────────────────────────────
        for match in CLASS_RE.finditer(source):
            name = match.group(1)
            line_no = self._line_number_from_index(source, match.start())
            symbols.append(
                {
                    "name": name,
                    "symbol_type": "class",
                    "signature": f"class {name}",
                    "start_line": line_no,
                    "end_line": line_no,
                }
            )

        for match in FUNCTION_RE.finditer(source):
            name = match.group(1)
            line_no = self._line_number_from_index(source, match.start())
            symbols.append(
                {
                    "name": name,
                    "symbol_type": "function",
                    "signature": f"function {name}(...)",
                    "start_line": line_no,
                    "end_line": line_no,
                }
            )

        for match in ARROW_FUNCTION_RE.finditer(source):
            name = match.group(1)
            line_no = self._line_number_from_index(source, match.start())
            symbols.append(
                {
                    "name": name,
                    "symbol_type": "arrow_function",
                    "signature": f"const {name} = (...) =>",
                    "start_line": line_no,
                    "end_line": line_no,
                }
            )

        # ── Exports ──────────────────────────────────────────────────────────
        EXPORT_RE = re.compile(r"export\s+(?:const|let|var|function|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
        for match in EXPORT_RE.finditer(source):
            dependencies.append({
                "edge_type": "export",
                "source_ref": match.group(1),
                "target_ref": None,
            })

        # ── Call detection — only for imported names (reduces noise dramatically) ──
        # Instead of matching every `word(`, only track calls to names we know
        # were imported. This keeps call edges meaningful and resolvable.
        if imported_names:
            # Build a pattern that only matches imported names
            # Cap at 50 names to avoid regex explosion
            names_to_track = list(imported_names)[:50]
            call_pattern = re.compile(
                r"\b(" + "|".join(re.escape(n) for n in names_to_track) + r")\s*\("
            )
            seen_calls: set[str] = set()
            for match in call_pattern.finditer(source):
                name = match.group(1)
                if name not in seen_calls:
                    seen_calls.add(name)
                    dependencies.append({
                        "edge_type": "call",
                        "source_ref": None,
                        "target_ref": name,
                    })

        # Deduplicate import targets for imports_list
        unique_targets = list(dict.fromkeys(import_targets))

        return {
            "symbols": symbols,
            "dependencies": dependencies,
            "imports_list": "\n".join(unique_targets[:200]),
            "error": None,
        }

    def _line_number_from_index(self, source: str, index: int) -> int:
        return source.count("\n", 0, index) + 1

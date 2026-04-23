import ast
import re
from pathlib import Path


class PythonParser:
    language = "Python"

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".py"

    def parse(self, file_path: Path) -> dict:
        try:
            source = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return {
                "symbols": [],
                "dependencies": [],
                "error": f"Failed to read file: {exc}",
            }

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return {
                "symbols": [],
                "dependencies": [],
                "error": f"Python syntax error: {exc}",
            }

        symbols = []
        dependencies = []
        # Track imports for call resolution (module alias → module name)
        import_aliases: dict[str, str] = {}
        # Track which names are imported (for call deduplication)
        imported_names: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                symbols.append(
                    {
                        "name": node.name,
                        "symbol_type": "function",
                        "signature": self._build_function_signature(node),
                        "start_line": getattr(node, "lineno", 0),
                        "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
                    }
                )

            elif isinstance(node, ast.AsyncFunctionDef):
                symbols.append(
                    {
                        "name": node.name,
                        "symbol_type": "async_function",
                        "signature": self._build_function_signature(node, async_fn=True),
                        "start_line": getattr(node, "lineno", 0),
                        "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
                        "summary": ast.get_docstring(node),
                    }
                )

            elif isinstance(node, ast.ClassDef):
                symbols.append(
                    {
                        "name": node.name,
                        "symbol_type": "class",
                        "signature": self._build_class_signature(node),
                        "start_line": getattr(node, "lineno", 0),
                        "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
                        "summary": ast.get_docstring(node),
                    }
                )

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    asname = alias.asname or module.split(".")[0]
                    import_aliases[asname] = module
                    imported_names.add(asname)
                    dependencies.append(
                        {
                            "edge_type": "import",
                            # source_ref = None for bare imports
                            "source_ref": None,
                            # target_ref = the module name (e.g. "os", "app.utils")
                            "target_ref": module,
                        }
                    )

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                level = node.level  # 0 = absolute, 1 = relative (.), 2 = (..)
                # Encode relative level in source_ref so resolver can handle it
                # e.g. level=1, module="utils" → source_ref=".utils"
                # e.g. level=2, module="core" → source_ref="..core"
                if level > 0:
                    relative_prefix = "." * level
                    effective_module = f"{relative_prefix}{module_name}" if module_name else relative_prefix
                else:
                    effective_module = module_name

                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
                    dependencies.append(
                        {
                            "edge_type": "from_import",
                            # source_ref = the module being imported FROM (most useful for resolution)
                            "source_ref": effective_module or None,
                            # target_ref = module.symbol (for symbol-level resolution)
                            "target_ref": f"{effective_module}.{alias.name}" if effective_module else alias.name,
                        }
                    )

            elif isinstance(node, ast.Call):
                # Only emit call edges for names that are likely imported symbols
                # (not builtins, not local variables). This dramatically reduces noise.
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                    # Only track calls to names that were imported or look like class instantiation
                    if name in imported_names or (name and name[0].isupper()):
                        dependencies.append(
                            {
                                "edge_type": "call",
                                "source_ref": None,
                                "target_ref": name,
                            }
                        )
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    obj = node.func.value.id
                    method = node.func.attr
                    # Only track calls on imported module aliases
                    if obj in import_aliases:
                        dependencies.append(
                            {
                                "edge_type": "call",
                                "source_ref": obj,
                                "target_ref": method,
                            }
                        )

        # Populate imports_list for fast fallback inference
        # This is a newline-separated list of import targets (module paths)
        import_targets = list(dict.fromkeys(
            dep["source_ref"] or dep["target_ref"]
            for dep in dependencies
            if dep["edge_type"] in ("import", "from_import")
            and (dep["source_ref"] or dep["target_ref"])
        ))

        return {
            "symbols": symbols,
            "dependencies": dependencies,
            "imports_list": "\n".join(import_targets[:200]),
            "error": None,
        }

    def _build_function_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef, async_fn: bool = False) -> str:
        arg_names = [arg.arg for arg in node.args.args]
        prefix = "async def" if async_fn else "def"
        return f"{prefix} {node.name}({', '.join(arg_names)})"

    def _build_class_signature(self, node: ast.ClassDef) -> str:
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)

        if bases:
            return f"class {node.name}({', '.join(bases)})"
        return f"class {node.name}"

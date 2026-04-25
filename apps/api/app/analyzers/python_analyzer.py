"""
Python Analyzer - RepoBrain 10.0

Analyzes Python files for:
- Imports (import, from import)
- Functions, classes, methods
- Framework detection (FastAPI, Flask, Django, Click, etc.)
- Entrypoint detection (__main__, main())
- Route detection (@app.route, etc.)
"""

import re
from typing import List, Dict, Any
from .base_analyzer import BaseAnalyzer, AnalysisResult


class PythonAnalyzer(BaseAnalyzer):
    """Python language analyzer with framework-aware detection."""
    
    def get_language(self) -> str:
        return "python"
    
    def can_analyze(self, file_path: str, content: str) -> bool:
        return file_path.endswith('.py') or content.startswith('#!')
    
    def analyze(self, file_id: str, file_path: str, content: str) -> AnalysisResult:
        result = AnalysisResult(
            file_id=file_id,
            path=file_path,
            language="python",
            analyzer_confidence=0.9  # High confidence for Python
        )
        
        try:
            # Extract imports
            result.imports = self._extract_python_imports(content)
            
            # Extract functions and classes
            result.functions = self._extract_python_functions(content)
            result.classes = self._extract_python_classes(content)
            
            # Detect entrypoint hints
            result.entrypoint_hints = self._detect_entrypoint_hints(content)
            
            # Detect routes
            result.route_hints = self._extract_route_hints(content)
            
            # Detect UI hints (for desktop apps)
            result.ui_hints = self._detect_ui_hints(content, result.imports)
            
            # Detect config hints
            result.config_hints = self._extract_config_hints(content)
            
            # Extract file references
            result.file_references = self.extract_string_literals(content)
            
            # Detect framework and integration signals
            result.framework_signals = self.detect_framework_signals(content, result.imports)
            result.integration_signals = self.detect_integration_signals(content, result.imports)
            
            # Extract symbol names
            result.symbol_names = self._extract_symbol_names(result.functions, result.classes)
            
            # Extract selective comments
            result.comments = self._extract_useful_comments(content)
            
        except Exception as e:
            result.limitations.append(f"Python analysis failed: {str(e)}")
            result.analyzer_confidence = 0.3
        
        return result
    
    def _extract_python_imports(self, content: str) -> List[str]:
        """Extract Python imports and from-imports."""
        imports = []
        
        # Standard imports: import module
        import_pattern = r'^import\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)'
        imports.extend(re.findall(import_pattern, content, re.MULTILINE))
        
        # From imports: from module import ...
        from_pattern = r'^from\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s+import'
        imports.extend(re.findall(from_pattern, content, re.MULTILINE))
        
        # Relative imports: from .module import ...
        rel_pattern = r'^from\s+\.+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s+import'
        imports.extend(re.findall(rel_pattern, content, re.MULTILINE))
        
        return list(set(imports))  # Deduplicate
    
    def _extract_python_functions(self, content: str) -> List[Dict[str, Any]]:
        """Extract Python function definitions."""
        pattern = r'^(\s*)def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\):'
        functions = []
        
        for match in re.finditer(pattern, content, re.MULTILINE):
            indent, name, params = match.groups()
            functions.append({
                "name": name,
                "params": [p.strip().split('=')[0].strip() for p in params.split(',') if p.strip()],
                "line": content[:match.start()].count('\n') + 1,
                "indent_level": len(indent),
                "signature": match.group(0).strip(),
            })
        
        return functions
    
    def _extract_python_classes(self, content: str) -> List[Dict[str, Any]]:
        """Extract Python class definitions."""
        pattern = r'^(\s*)class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\([^)]*\))?:'
        classes = []
        
        for match in re.finditer(pattern, content, re.MULTILINE):
            indent, name = match.groups()
            
            # Extract methods for this class (basic heuristic)
            class_start = match.end()
            methods = []
            method_pattern = r'^\s{4,}def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\('
            
            # Look for methods after class definition
            remaining_content = content[class_start:]
            for method_match in re.finditer(method_pattern, remaining_content, re.MULTILINE):
                method_line = class_start + method_match.start()
                if content[:method_line].count('\n') - content[:match.start()].count('\n') < 100:  # Reasonable proximity
                    methods.append(method_match.group(1))
            
            classes.append({
                "name": name,
                "methods": methods[:10],  # Limit to first 10 methods
                "line": content[:match.start()].count('\n') + 1,
                "indent_level": len(indent),
                "signature": match.group(0).strip(),
            })
        
        return classes
    
    def _detect_entrypoint_hints(self, content: str) -> List[str]:
        """Detect Python entrypoint patterns."""
        hints = []
        
        # __main__ guard
        if re.search(r'if\s+__name__\s*==\s*["\']__main__["\']', content):
            hints.append("main_guard")
        
        # main() function
        if re.search(r'def\s+main\s*\(', content):
            hints.append("main_function")
        
        # CLI framework decorators
        if re.search(r'@(?:click|typer)\.command', content):
            hints.append("cli_command")
        
        # Web framework app creation
        if re.search(r'(?:FastAPI|Flask|app)\s*\(', content):
            hints.append("web_app_bootstrap")
        
        # Django management
        if 'manage.py' in content or 'django.core.management' in content:
            hints.append("django_management")
        
        return hints
    
    def _extract_route_hints(self, content: str) -> List[str]:
        """Extract HTTP route definitions."""
        routes = []
        
        # FastAPI/Flask style routes
        route_patterns = [
            r'@app\.(?:get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
            r'@router\.(?:get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
            r'@blueprint\.route\s*\(\s*["\']([^"\']+)["\']',
        ]
        
        for pattern in route_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            routes.extend(matches)
        
        return list(set(routes))[:20]  # Limit to 20 routes
    
    def _detect_ui_hints(self, content: str, imports: List[str]) -> List[str]:
        """Detect UI toolkit usage."""
        hints = []
        content_lower = content.lower()
        
        # Desktop UI toolkits
        ui_toolkits = {
            "tkinter": ["tkinter", "tk.", "ttk.", "messagebox"],
            "pyqt": ["pyqt", "qwidget", "qapplication", "qmainwindow"],
            "kivy": ["kivy", "app.run", "widget"],
            "pygame": ["pygame", "pygame.init", "display.set_mode"],
        }
        
        for toolkit, indicators in ui_toolkits.items():
            if any(ind in content_lower for ind in indicators) or \
               any(toolkit in imp.lower() for imp in imports):
                hints.append(toolkit)
        
        return hints
    
    def _extract_config_hints(self, content: str) -> List[str]:
        """Extract configuration variable references."""
        config_vars = []
        
        # Environment variable patterns
        env_patterns = [
            r'os\.getenv\s*\(\s*["\']([A-Z_][A-Z0-9_]*)["\']',
            r'os\.environ\s*\[\s*["\']([A-Z_][A-Z0-9_]*)["\']',
            r'getenv\s*\(\s*["\']([A-Z_][A-Z0-9_]*)["\']',
        ]
        
        for pattern in env_patterns:
            matches = re.findall(pattern, content)
            config_vars.extend(matches)
        
        return list(set(config_vars))[:10]  # Limit to 10 config vars
    
    def _extract_symbol_names(self, functions: List[Dict], classes: List[Dict]) -> List[str]:
        """Extract all symbol names for search/reference."""
        symbols = []
        
        # Function names
        symbols.extend([f["name"] for f in functions])
        
        # Class names
        symbols.extend([c["name"] for c in classes])
        
        # Method names
        for cls in classes:
            symbols.extend(cls.get("methods", []))
        
        return list(set(symbols))
    
    def _extract_useful_comments(self, content: str) -> List[str]:
        """Extract useful comments and docstrings."""
        comments = []
        
        # Docstrings (triple quotes)
        docstring_pattern = r'"""([^"]{10,200})"""'
        docstrings = re.findall(docstring_pattern, content, re.DOTALL)
        for doc in docstrings:
            clean_doc = ' '.join(doc.strip().split())
            if len(clean_doc) > 20:  # Only meaningful docstrings
                comments.append(clean_doc[:200])  # Truncate
        
        # TODO/FIXME comments
        todo_pattern = r'#\s*(TODO|FIXME|NOTE|HACK):\s*(.{10,100})'
        todos = re.findall(todo_pattern, content, re.IGNORECASE)
        for tag, text in todos:
            comments.append(f"{tag}: {text.strip()}")
        
        return comments[:5]  # Limit to 5 useful comments
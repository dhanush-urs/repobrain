"""
JavaScript/TypeScript Analyzer - RepoBrain 10.0

Analyzes JavaScript and TypeScript files for:
- Import/export statements (ES6, CommonJS, TypeScript)
- Function and class definitions
- React/Vue/Angular component patterns
- Node.js framework detection (Express, Nest, etc.)
- Frontend framework patterns
- API calls and routing patterns
"""

import re
import json
import logging
from typing import Dict, List, Any
from .base_analyzer import BaseAnalyzer, AnalysisResult

logger = logging.getLogger(__name__)


class JavaScriptAnalyzer(BaseAnalyzer):
    """Analyzer for JavaScript and TypeScript files."""
    
    def get_language(self) -> str:
        return "javascript"
    
    def can_analyze(self, file_path: str, content: str) -> bool:
        """Check if this is a JavaScript/TypeScript file."""
        path_lower = file_path.lower()
        return (path_lower.endswith(('.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs')) or
                'javascript' in content[:200].lower() or
                'typescript' in content[:200].lower())
    
    def analyze(self, file_id: str, file_path: str, content: str) -> AnalysisResult:
        """Analyze JavaScript/TypeScript file content."""
        result = AnalysisResult(
            file_id=file_id,
            path=file_path,
            language="javascript"
        )
        
        try:
            # Extract imports and requires
            result.imports = self._extract_imports(content)
            result.requires = self._extract_requires(content)
            
            # Extract exports
            result.exports = self._extract_exports(content)
            
            # Extract functions and classes
            result.functions = self._extract_functions(content)
            result.classes = self._extract_classes(content)
            
            # Extract entrypoint hints
            result.entrypoint_hints = self._detect_entrypoint_hints(content, file_path)
            
            # Extract framework patterns
            result.route_hints = self._extract_route_hints(content)
            result.ui_hints = self._extract_ui_hints(content)
            result.config_hints = self._extract_config_hints(content)
            
            # Extract references
            result.file_references = self.extract_string_literals(content)
            result.call_hints = self._extract_call_hints(content)
            
            # Detect frameworks and integrations
            all_imports = result.imports + result.requires
            result.framework_signals = self.detect_framework_signals(content, all_imports)
            result.integration_signals = self.detect_integration_signals(content, all_imports)
            
            # Extract symbol names
            result.symbol_names = self._extract_symbol_names(content)
            
            # Set confidence based on analysis success
            result.analyzer_confidence = self._calculate_confidence(result)
            
        except Exception as e:
            logger.error(f"JavaScript analysis failed for {file_path}: {e}")
            result.limitations.append(f"Analysis failed: {str(e)}")
            result.analyzer_confidence = 0.1
        
        return result
    
    def _extract_imports(self, content: str) -> List[str]:
        """Extract ES6 import statements."""
        imports = []
        
        # ES6 imports: import ... from 'module'
        import_patterns = [
            r'import\s+.*?\s+from\s+["\']([^"\']+)["\']',
            r'import\s+["\']([^"\']+)["\']',
            r'import\s*\(\s*["\']([^"\']+)["\']\s*\)',  # Dynamic imports
        ]
        
        for pattern in import_patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            imports.extend(matches)
        
        return list(set(imports))
    
    def _extract_requires(self, content: str) -> List[str]:
        """Extract CommonJS require statements."""
        requires = []
        
        # CommonJS requires: require('module')
        require_patterns = [
            r'require\s*\(\s*["\']([^"\']+)["\']\s*\)',
        ]
        
        for pattern in require_patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            requires.extend(matches)
        
        return list(set(requires))
    
    def _extract_exports(self, content: str) -> List[str]:
        """Extract export statements."""
        exports = []
        
        # Export patterns
        export_patterns = [
            r'export\s+(?:default\s+)?(?:class|function|const|let|var)\s+(\w+)',
            r'export\s+\{\s*([^}]+)\s*\}',
            r'module\.exports\s*=\s*(\w+)',
            r'exports\.(\w+)',
        ]
        
        for pattern in export_patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            for match in matches:
                if isinstance(match, str):
                    if ',' in match:  # Handle export { a, b, c }
                        exports.extend([name.strip() for name in match.split(',')])
                    else:
                        exports.append(match.strip())
        
        return list(set(exports))
    
    def _extract_functions(self, content: str) -> List[Dict[str, Any]]:
        """Extract function definitions."""
        functions = []
        
        # Function patterns
        function_patterns = [
            r'function\s+(\w+)\s*\([^)]*\)',
            r'const\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>',
            r'let\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>',
            r'var\s+(\w+)\s*=\s*(?:async\s+)?function',
            r'(\w+)\s*:\s*(?:async\s+)?function\s*\([^)]*\)',  # Object methods
            r'async\s+function\s+(\w+)\s*\([^)]*\)',
        ]
        
        for pattern in function_patterns:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                functions.append({
                    "name": match.group(1),
                    "line": content[:match.start()].count('\n') + 1,
                    "signature": match.group(0).strip(),
                })
        
        return functions
    
    def _extract_classes(self, content: str) -> List[Dict[str, Any]]:
        """Extract class definitions."""
        classes = []
        
        # Class patterns
        class_patterns = [
            r'class\s+(\w+)(?:\s+extends\s+\w+)?',
            r'(\w+)\s*=\s*class(?:\s+extends\s+\w+)?',
        ]
        
        for pattern in class_patterns:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                classes.append({
                    "name": match.group(1),
                    "line": content[:match.start()].count('\n') + 1,
                    "signature": match.group(0).strip(),
                })
        
        return classes
    
    def _detect_entrypoint_hints(self, content: str, file_path: str) -> List[str]:
        """Detect entrypoint patterns."""
        hints = []
        
        # File name patterns
        path_lower = file_path.lower()
        if any(name in path_lower for name in ['index', 'main', 'app', 'server']):
            hints.append("entry_file_name")
        
        # Content patterns
        if 'app.listen(' in content or 'server.listen(' in content:
            hints.append("web_server_bootstrap")
        
        if 'express()' in content or 'new Express' in content:
            hints.append("express_app")
        
        if 'ReactDOM.render' in content or 'createRoot(' in content:
            hints.append("react_entry")
        
        if 'new Vue(' in content or 'createApp(' in content:
            hints.append("vue_entry")
        
        if 'angular.bootstrap' in content or 'platformBrowserDynamic' in content:
            hints.append("angular_entry")
        
        if 'if (require.main === module)' in content:
            hints.append("node_main_check")
        
        return hints
    
    def _extract_route_hints(self, content: str) -> List[str]:
        """Extract API route patterns."""
        routes = []
        
        # Express/Fastify route patterns
        route_patterns = [
            r'app\.(?:get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
            r'router\.(?:get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
            r'@(?:Get|Post|Put|Delete|Patch)\s*\(\s*["\']([^"\']+)["\']',  # NestJS decorators
        ]
        
        for pattern in route_patterns:
            matches = re.findall(pattern, content, re.MULTILINE | re.IGNORECASE)
            routes.extend(matches)
        
        return list(set(routes))
    
    def _extract_ui_hints(self, content: str) -> List[str]:
        """Extract UI framework patterns."""
        ui_hints = []
        
        # React patterns
        if any(pattern in content for pattern in ['React.Component', 'useState', 'useEffect', 'JSX.Element']):
            ui_hints.append("react_component")
        
        # Vue patterns
        if any(pattern in content for pattern in ['Vue.component', 'v-if', 'v-for', 'setup()']):
            ui_hints.append("vue_component")
        
        # Angular patterns
        if any(pattern in content for pattern in ['@Component', 'ngOnInit', 'Injectable']):
            ui_hints.append("angular_component")
        
        # DOM manipulation
        if any(pattern in content for pattern in ['document.getElementById', 'querySelector', 'addEventListener']):
            ui_hints.append("dom_manipulation")
        
        return ui_hints
    
    def _extract_config_hints(self, content: str) -> List[str]:
        """Extract configuration patterns."""
        config_hints = []
        
        # Environment variables
        if 'process.env' in content:
            config_hints.append("env_variables")
        
        # Config files
        if any(pattern in content for pattern in ['config.json', 'settings.js', '.env']):
            config_hints.append("config_files")
        
        # Database config
        if any(pattern in content for pattern in ['DATABASE_URL', 'DB_HOST', 'MONGO_URI']):
            config_hints.append("database_config")
        
        return config_hints
    
    def _extract_call_hints(self, content: str) -> List[str]:
        """Extract function call patterns."""
        calls = []
        
        # Function call patterns (best effort)
        call_patterns = [
            r'(\w+)\s*\(',
            r'\.(\w+)\s*\(',
        ]
        
        for pattern in call_patterns:
            matches = re.findall(pattern, content)
            calls.extend([match for match in matches if len(match) > 2])
        
        return list(set(calls))[:50]  # Limit to prevent explosion
    
    def _extract_symbol_names(self, content: str) -> List[str]:
        """Extract all identifier names."""
        # Simple identifier extraction
        identifiers = re.findall(r'\b[a-zA-Z_$][a-zA-Z0-9_$]*\b', content)
        
        # Filter out common keywords
        keywords = {
            'const', 'let', 'var', 'function', 'class', 'if', 'else', 'for', 'while',
            'return', 'import', 'export', 'from', 'default', 'async', 'await',
            'true', 'false', 'null', 'undefined', 'this', 'new', 'typeof'
        }
        
        filtered = [name for name in identifiers if name not in keywords and len(name) > 2]
        return list(set(filtered))[:100]  # Limit to top 100
    
    def _calculate_confidence(self, result: AnalysisResult) -> float:
        """Calculate analysis confidence based on extracted data."""
        confidence = 0.0
        
        # Base confidence for successful parsing
        confidence += 0.3
        
        # Boost for imports/exports
        if result.imports or result.requires:
            confidence += 0.2
        if result.exports:
            confidence += 0.1
        
        # Boost for code structure
        if result.functions:
            confidence += 0.2
        if result.classes:
            confidence += 0.1
        
        # Boost for framework detection
        if result.framework_signals:
            confidence += 0.1
        if result.entrypoint_hints:
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    def detect_framework_signals(self, content: str, imports: List[str]) -> List[str]:
        """Detect JavaScript framework usage."""
        signals = []
        content_lower = content.lower()
        
        # Frontend frameworks
        if any(fw in ' '.join(imports).lower() for fw in ['react', 'react-dom']):
            signals.append("react")
        elif any(fw in ' '.join(imports).lower() for fw in ['vue', '@vue']):
            signals.append("vue")
        elif any(fw in ' '.join(imports).lower() for fw in ['@angular', 'angular']):
            signals.append("angular")
        elif any(fw in ' '.join(imports).lower() for fw in ['svelte', 'sveltekit']):
            signals.append("svelte")
        
        # Backend frameworks
        if any(fw in ' '.join(imports).lower() for fw in ['express', 'fastify', 'koa']):
            signals.append("node_web_framework")
        elif any(fw in ' '.join(imports).lower() for fw in ['@nestjs', 'nest']):
            signals.append("nestjs")
        elif any(fw in ' '.join(imports).lower() for fw in ['next', 'nuxt']):
            signals.append("fullstack_framework")
        
        # Testing frameworks
        if any(fw in ' '.join(imports).lower() for fw in ['jest', 'mocha', 'chai', 'cypress']):
            signals.append("testing_framework")
        
        # Build tools
        if any(fw in ' '.join(imports).lower() for fw in ['webpack', 'vite', 'rollup', 'parcel']):
            signals.append("build_tool")
        
        return signals
    
    def detect_integration_signals(self, content: str, imports: List[str]) -> List[str]:
        """Detect third-party service integrations."""
        signals = []
        content_lower = content.lower()
        all_text = content_lower + ' '.join(imports).lower()
        
        # Cloud services
        if any(svc in all_text for svc in ['aws-sdk', 'firebase', 'supabase']):
            signals.append("cloud_service")
        
        # Payment services
        if any(svc in all_text for svc in ['stripe', 'paypal', 'braintree']):
            signals.append("payment_service")
        
        # AI/ML services
        if any(svc in all_text for svc in ['openai', 'anthropic', 'langchain']):
            signals.append("llm_service")
        
        # Database
        if any(db in all_text for db in ['mongoose', 'prisma', 'typeorm', 'sequelize']):
            signals.append("database_orm")
        
        return signals
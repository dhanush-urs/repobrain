"""
Java Analyzer - RepoBrain 10.0

Analyzes Java files for:
- Imports (import statements)
- Classes, methods, interfaces
- Framework detection (Spring, Swing, JavaFX)
- Entrypoint detection (main method)
- UI patterns (JFrame, ActionListener, etc.)
"""

import re
from typing import List, Dict, Any
from .base_analyzer import BaseAnalyzer, AnalysisResult


class JavaAnalyzer(BaseAnalyzer):
    """Java language analyzer with GUI and enterprise framework detection."""
    
    def get_language(self) -> str:
        return "java"
    
    def can_analyze(self, file_path: str, content: str) -> bool:
        return file_path.endswith('.java')
    
    def analyze(self, file_id: str, file_path: str, content: str) -> AnalysisResult:
        result = AnalysisResult(
            file_id=file_id,
            path=file_path,
            language="java",
            analyzer_confidence=0.85  # High confidence for Java
        )
        
        try:
            # Extract imports
            result.imports = self._extract_java_imports(content)
            
            # Extract classes and methods
            result.classes = self._extract_java_classes(content)
            result.methods = self._extract_java_methods(content)
            
            # Detect entrypoint hints
            result.entrypoint_hints = self._detect_entrypoint_hints(content)
            
            # Detect UI hints (Swing, JavaFX)
            result.ui_hints = self._detect_ui_hints(content, result.imports)
            
            # Detect route hints (Spring)
            result.route_hints = self._extract_route_hints(content)
            
            # Detect config hints
            result.config_hints = self._extract_config_hints(content)
            
            # Extract file references
            result.file_references = self.extract_string_literals(content)
            
            # Detect framework and integration signals
            result.framework_signals = self._detect_java_frameworks(content, result.imports)
            result.integration_signals = self.detect_integration_signals(content, result.imports)
            
            # Extract symbol names
            result.symbol_names = self._extract_symbol_names(result.classes, result.methods)
            
            # Extract useful comments
            result.comments = self._extract_useful_comments(content)
            
        except Exception as e:
            result.limitations.append(f"Java analysis failed: {str(e)}")
            result.analyzer_confidence = 0.4
        
        return result
    
    def _extract_java_imports(self, content: str) -> List[str]:
        """Extract Java import statements."""
        imports = []
        
        # Standard imports: import package.Class;
        import_pattern = r'import\s+(?:static\s+)?([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*(?:\.\*)?)\s*;'
        matches = re.findall(import_pattern, content)
        imports.extend(matches)
        
        return list(set(imports))
    
    def _extract_java_classes(self, content: str) -> List[Dict[str, Any]]:
        """Extract Java class definitions."""
        classes = []
        
        # Class pattern: public class ClassName extends/implements ...
        class_pattern = r'(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?class\s+([A-Z][a-zA-Z0-9_]*)'
        
        for match in re.finditer(class_pattern, content):
            class_name = match.group(1)
            
            # Extract methods for this class
            methods = self._extract_class_methods(content, match.start(), class_name)
            
            classes.append({
                "name": class_name,
                "methods": methods,
                "line": content[:match.start()].count('\n') + 1,
                "signature": match.group(0).strip(),
                "type": "class"
            })
        
        # Interface pattern
        interface_pattern = r'(?:public\s+|private\s+|protected\s+)?interface\s+([A-Z][a-zA-Z0-9_]*)'
        
        for match in re.finditer(interface_pattern, content):
            interface_name = match.group(1)
            
            classes.append({
                "name": interface_name,
                "methods": [],
                "line": content[:match.start()].count('\n') + 1,
                "signature": match.group(0).strip(),
                "type": "interface"
            })
        
        return classes
    
    def _extract_java_methods(self, content: str) -> List[Dict[str, Any]]:
        """Extract Java method definitions."""
        methods = []
        
        # Method pattern: public/private returnType methodName(params)
        method_pattern = r'(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:[a-zA-Z_][a-zA-Z0-9_<>\[\]]*\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*(?:throws\s+[^{]+)?\s*\{'
        
        for match in re.finditer(method_pattern, content):
            method_name = match.group(1)
            
            # Skip constructors (same name as class)
            if method_name[0].isupper():
                continue
                
            methods.append({
                "name": method_name,
                "line": content[:match.start()].count('\n') + 1,
                "signature": match.group(0).strip().rstrip('{'),
            })
        
        return methods
    
    def _extract_class_methods(self, content: str, class_start: int, class_name: str) -> List[str]:
        """Extract method names for a specific class."""
        methods = []
        
        # Look for methods after class definition (simple heuristic)
        remaining_content = content[class_start:]
        method_pattern = r'(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:[a-zA-Z_][a-zA-Z0-9_<>\[\]]*\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*\{'
        
        for match in re.finditer(method_pattern, remaining_content):
            method_name = match.group(1)
            
            # Skip if it's the class constructor
            if method_name == class_name:
                continue
                
            # Stop if we've gone too far (next class)
            if match.start() > 5000:  # Reasonable class size limit
                break
                
            methods.append(method_name)
        
        return methods[:15]  # Limit to 15 methods per class
    
    def _detect_entrypoint_hints(self, content: str) -> List[str]:
        """Detect Java entrypoint patterns."""
        hints = []
        
        # Main method
        if re.search(r'public\s+static\s+void\s+main\s*\(\s*String\s*\[\s*\]\s*\w*\s*\)', content):
            hints.append("main_method")
        
        # Spring Boot application
        if re.search(r'@SpringBootApplication', content):
            hints.append("spring_boot_app")
        
        # JavaFX Application
        if re.search(r'extends\s+Application', content) and 'javafx' in content.lower():
            hints.append("javafx_app")
        
        # Swing application (JFrame)
        if re.search(r'extends\s+JFrame', content):
            hints.append("swing_app")
        
        return hints
    
    def _detect_ui_hints(self, content: str, imports: List[str]) -> List[str]:
        """Detect Java UI toolkit usage."""
        hints = []
        content_lower = content.lower()
        
        # Swing components
        swing_patterns = [
            "JFrame", "JPanel", "JButton", "JLabel", "JTextField", "JTable",
            "ActionListener", "actionPerformed", "WindowAdapter", "MouseListener"
        ]
        
        if any(pattern.lower() in content_lower for pattern in swing_patterns) or \
           any("swing" in imp.lower() for imp in imports):
            hints.append("swing")
        
        # AWT components
        awt_patterns = ["Frame", "Panel", "Button", "Label", "TextField", "Canvas"]
        
        if any(pattern.lower() in content_lower for pattern in awt_patterns) or \
           any("java.awt" in imp for imp in imports):
            hints.append("awt")
        
        # JavaFX components
        javafx_patterns = ["Stage", "Scene", "Button", "Label", "TextField", "VBox", "HBox"]
        
        if any(pattern.lower() in content_lower for pattern in javafx_patterns) or \
           any("javafx" in imp.lower() for imp in imports):
            hints.append("javafx")
        
        return hints
    
    def _extract_route_hints(self, content: str) -> List[str]:
        """Extract Spring REST endpoints."""
        routes = []
        
        # Spring REST annotations
        route_patterns = [
            r'@(?:Get|Post|Put|Delete|Patch)Mapping\s*\(\s*["\']([^"\']+)["\']',
            r'@RequestMapping\s*\([^)]*value\s*=\s*["\']([^"\']+)["\']',
        ]
        
        for pattern in route_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            routes.extend(matches)
        
        return list(set(routes))[:15]  # Limit to 15 routes
    
    def _extract_config_hints(self, content: str) -> List[str]:
        """Extract configuration property references."""
        config_vars = []
        
        # Spring @Value annotations
        value_pattern = r'@Value\s*\(\s*["\']([^"\']+)["\']'
        matches = re.findall(value_pattern, content)
        config_vars.extend(matches)
        
        # Properties file references
        prop_pattern = r'getProperty\s*\(\s*["\']([^"\']+)["\']'
        matches = re.findall(prop_pattern, content)
        config_vars.extend(matches)
        
        return list(set(config_vars))[:10]
    
    def _detect_java_frameworks(self, content: str, imports: List[str]) -> List[str]:
        """Detect Java framework usage."""
        frameworks = []
        content_lower = content.lower()
        
        # Spring Framework
        spring_indicators = ["@RestController", "@Service", "@Repository", "@Component", "@Autowired"]
        if any(ind in content for ind in spring_indicators) or \
           any("springframework" in imp for imp in imports):
            frameworks.append("spring")
        
        # Spring Boot
        if "@SpringBootApplication" in content or \
           any("spring.boot" in imp for imp in imports):
            frameworks.append("spring_boot")
        
        # Hibernate/JPA
        jpa_indicators = ["@Entity", "@Table", "@Id", "@GeneratedValue"]
        if any(ind in content for ind in jpa_indicators) or \
           any("hibernate" in imp.lower() or "javax.persistence" in imp for imp in imports):
            frameworks.append("jpa_hibernate")
        
        # Android
        if any("android" in imp.lower() for imp in imports) or \
           "Activity" in content or "Fragment" in content:
            frameworks.append("android")
        
        return frameworks
    
    def _extract_symbol_names(self, classes: List[Dict], methods: List[Dict]) -> List[str]:
        """Extract all symbol names."""
        symbols = []
        
        # Class names
        symbols.extend([c["name"] for c in classes])
        
        # Method names
        symbols.extend([m["name"] for m in methods])
        
        # Class methods
        for cls in classes:
            symbols.extend(cls.get("methods", []))
        
        return list(set(symbols))
    
    def _extract_useful_comments(self, content: str) -> List[str]:
        """Extract useful Javadoc and comments."""
        comments = []
        
        # Javadoc comments
        javadoc_pattern = r'/\*\*([^*]+(?:\*(?!/)[^*]*)*)\*/'
        javadocs = re.findall(javadoc_pattern, content, re.DOTALL)
        for doc in javadocs:
            clean_doc = ' '.join(doc.strip().replace('*', '').split())
            if len(clean_doc) > 20:
                comments.append(clean_doc[:200])
        
        # TODO/FIXME comments
        todo_pattern = r'//\s*(TODO|FIXME|NOTE|HACK):\s*(.{10,100})'
        todos = re.findall(todo_pattern, content, re.IGNORECASE)
        for tag, text in todos:
            comments.append(f"{tag}: {text.strip()}")
        
        return comments[:5]
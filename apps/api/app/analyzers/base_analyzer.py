"""
Base Analyzer - Universal Language Analysis Interface

Defines common schema and interface for all language analyzers.
Ensures consistent output across Python, Java, JavaScript, etc.
"""

import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class AnalysisResult:
    """Normalized analysis result schema used by all language analyzers."""
    
    # File metadata
    file_id: str
    path: str
    language: str
    
    # Imports/Dependencies
    imports: List[str] = None  # ["fastapi", "react", "java.awt"]
    includes: List[str] = None  # C/C++ includes
    requires: List[str] = None  # Node.js requires
    
    # Exports/Public API
    exports: List[str] = None  # Public symbols exported
    public_symbols: List[str] = None  # Classes, functions exposed
    
    # Code Structure
    classes: List[Dict[str, Any]] = None  # [{"name": "Login", "methods": [...]}]
    functions: List[Dict[str, Any]] = None  # [{"name": "main", "params": [...]}]
    methods: List[Dict[str, Any]] = None  # Class methods
    
    # Entrypoint Hints
    entrypoint_hints: List[str] = None  # ["main_method", "cli_entry", "web_bootstrap"]
    
    # Framework/Pattern Hints
    route_hints: List[str] = None  # ["/api/users", "/login"]
    ui_hints: List[str] = None  # ["JFrame", "React.Component", "ActionListener"]
    config_hints: List[str] = None  # ["DATABASE_URL", "API_KEY"]
    
    # References
    file_references: List[str] = None  # String literals that look like file paths
    call_hints: List[str] = None  # Function/method calls (best effort)
    
    # Framework Signals
    framework_signals: List[str] = None  # ["fastapi", "spring_boot", "react"]
    integration_signals: List[str] = None  # ["stripe", "openai", "firebase"]
    
    # Metadata
    symbol_names: List[str] = None  # All identifiers found
    comments: List[str] = None  # Selective comments/docstrings
    analyzer_confidence: float = 0.0  # 0.0-1.0
    limitations: List[str] = None  # What this analyzer couldn't detect
    
    def __post_init__(self):
        """Initialize empty lists for None fields."""
        for field_name, field_type in self.__annotations__.items():
            if getattr(self, field_name) is None and hasattr(field_type, '__origin__') and field_type.__origin__ is list:
                setattr(self, field_name, [])


class BaseAnalyzer(ABC):
    """Base class for all language analyzers."""
    
    def __init__(self):
        self.language = self.get_language()
        self.confidence = 0.0
        
    @abstractmethod
    def get_language(self) -> str:
        """Return the language this analyzer handles."""
        pass
    
    @abstractmethod
    def can_analyze(self, file_path: str, content: str) -> bool:
        """Check if this analyzer can handle the given file."""
        pass
    
    @abstractmethod
    def analyze(self, file_id: str, file_path: str, content: str) -> AnalysisResult:
        """Analyze file content and return normalized result."""
        pass
    
    def extract_imports_basic(self, content: str, patterns: List[str]) -> List[str]:
        """Extract imports using regex patterns (fallback for complex parsing)."""
        imports = []
        for pattern in patterns:
            matches = re.findall(pattern, content, re.MULTILINE | re.IGNORECASE)
            imports.extend(matches)
        return list(set(imports))  # Deduplicate
    
    def extract_functions_basic(self, content: str, pattern: str) -> List[Dict[str, Any]]:
        """Extract function definitions using regex."""
        functions = []
        matches = re.finditer(pattern, content, re.MULTILINE)
        for match in matches:
            functions.append({
                "name": match.group(1),
                "line": content[:match.start()].count('\n') + 1,
                "signature": match.group(0).strip(),
            })
        return functions
    
    def extract_classes_basic(self, content: str, pattern: str) -> List[Dict[str, Any]]:
        """Extract class definitions using regex."""
        classes = []
        matches = re.finditer(pattern, content, re.MULTILINE)
        for match in matches:
            classes.append({
                "name": match.group(1),
                "line": content[:match.start()].count('\n') + 1,
                "signature": match.group(0).strip(),
            })
        return classes
    
    def extract_string_literals(self, content: str) -> List[str]:
        """Extract string literals that might be file references."""
        # Match quoted strings that look like paths
        pattern = r'["\']([^"\']*(?:\.(?:py|js|ts|java|html|css|json|yaml|toml|xml|sql|md)|/[^"\']*)+)["\']'
        matches = re.findall(pattern, content)
        return [m for m in matches if len(m) > 2 and ('/' in m or '.' in m)]
    
    def detect_framework_signals(self, content: str, imports: List[str]) -> List[str]:
        """Detect framework usage from imports and content."""
        signals = []
        content_lower = content.lower()
        
        # Web frameworks
        web_frameworks = {
            "fastapi": ["fastapi", "@app.", "FastAPI"],
            "flask": ["flask", "@app.route", "Flask"],
            "django": ["django", "models.Model", "HttpResponse"],
            "express": ["express", "app.get", "app.post"],
            "spring": ["@RestController", "@RequestMapping", "SpringApplication"],
        }
        
        for framework, indicators in web_frameworks.items():
            if any(ind.lower() in content_lower for ind in indicators) or \
               any(framework in imp.lower() for imp in imports):
                signals.append(framework)
        
        # Frontend frameworks
        frontend_frameworks = {
            "react": ["react", "React.Component", "useState", "useEffect"],
            "vue": ["vue", "Vue.component", "v-if", "v-for"],
            "angular": ["angular", "@Component", "ngOnInit"],
        }
        
        for framework, indicators in frontend_frameworks.items():
            if any(ind.lower() in content_lower for ind in indicators) or \
               any(framework in imp.lower() for imp in imports):
                signals.append(framework)
        
        return signals
    
    def detect_integration_signals(self, content: str, imports: List[str]) -> List[str]:
        """Detect third-party service integrations."""
        signals = []
        content_lower = content.lower()
        
        integrations = {
            "openai": ["openai", "gpt-", "chatgpt"],
            "stripe": ["stripe", "sk_", "pk_"],
            "firebase": ["firebase", "firestore", "firebase_admin"],
            "aws": ["boto3", "aws-sdk", "s3", "dynamodb"],
            "database": ["mysql", "postgres", "mongodb", "redis", "sqlite"],
        }
        
        for integration, indicators in integrations.items():
            if any(ind in content_lower for ind in indicators) or \
               any(any(ind in imp.lower() for ind in indicators) for imp in imports):
                signals.append(integration)
        
        return signals
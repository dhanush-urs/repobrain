"""
Analyzer Registry - RepoBrain 10.0

Central registry for all language analyzers.
Provides unified interface for multi-language analysis.
"""

import logging
from typing import Dict, List, Optional
from .base_analyzer import BaseAnalyzer, AnalysisResult
from .python_analyzer import PythonAnalyzer
from .java_analyzer import JavaAnalyzer
from .javascript_analyzer import JavaScriptAnalyzer
from .html_analyzer import HTMLAnalyzer

logger = logging.getLogger(__name__)


class AnalyzerRegistry:
    """Central registry for all language analyzers."""
    
    def __init__(self):
        self.analyzers: Dict[str, BaseAnalyzer] = {}
        self._register_default_analyzers()
    
    def _register_default_analyzers(self):
        """Register all built-in analyzers."""
        analyzers = [
            PythonAnalyzer(),
            JavaAnalyzer(),
            JavaScriptAnalyzer(),
            HTMLAnalyzer(),
            # TODO: Add more analyzers
            # GoAnalyzer(),
            # RustAnalyzer(),
            # ConfigAnalyzer(),
        ]
        
        for analyzer in analyzers:
            self.register_analyzer(analyzer)
    
    def register_analyzer(self, analyzer: BaseAnalyzer):
        """Register a new analyzer."""
        self.analyzers[analyzer.get_language()] = analyzer
        logger.info(f"Registered analyzer for {analyzer.get_language()}")
    
    def get_analyzer(self, language: str) -> Optional[BaseAnalyzer]:
        """Get analyzer for specific language."""
        return self.analyzers.get(language.lower())
    
    def analyze_file(self, file_id: str, file_path: str, content: str, language: str = None) -> Optional[AnalysisResult]:
        """Analyze a file using appropriate analyzer."""
        
        # Try specific language analyzer first
        if language:
            analyzer = self.get_analyzer(language)
            if analyzer and analyzer.can_analyze(file_path, content):
                try:
                    return analyzer.analyze(file_id, file_path, content)
                except Exception as e:
                    logger.error(f"Analysis failed with {language} analyzer: {e}")
        
        # Try all analyzers to find a match
        for analyzer in self.analyzers.values():
            if analyzer.can_analyze(file_path, content):
                try:
                    return analyzer.analyze(file_id, file_path, content)
                except Exception as e:
                    logger.error(f"Analysis failed with {analyzer.get_language()} analyzer: {e}")
                    continue
        
        # No analyzer found
        logger.debug(f"No analyzer found for {file_path}")
        return None
    
    def get_supported_languages(self) -> List[str]:
        """Get list of supported languages."""
        return list(self.analyzers.keys())
    
    def analyze_repository_files(self, files: List[Dict]) -> Dict[str, AnalysisResult]:
        """Analyze multiple files from a repository."""
        results = {}
        
        for file_data in files:
            file_id = file_data.get("id")
            file_path = file_data.get("path", "")
            content = file_data.get("content", "")
            language = file_data.get("language")
            
            if not file_id or not content:
                continue
            
            result = self.analyze_file(file_id, file_path, content, language)
            if result:
                results[file_id] = result
        
        return results


# Global registry instance
_registry = None

def get_analyzer_registry() -> AnalyzerRegistry:
    """Get global analyzer registry instance."""
    global _registry
    if _registry is None:
        _registry = AnalyzerRegistry()
    return _registry
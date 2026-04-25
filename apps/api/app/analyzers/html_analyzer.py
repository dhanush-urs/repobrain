"""
HTML/CSS Analyzer - RepoBrain 10.0

Analyzes HTML and CSS files for:
- Script and stylesheet references
- Asset loading patterns
- Component structure
- Framework detection (Bootstrap, Tailwind, etc.)
- Static site patterns
"""

import re
import logging
from typing import Dict, List, Any
from .base_analyzer import BaseAnalyzer, AnalysisResult

logger = logging.getLogger(__name__)


class HTMLAnalyzer(BaseAnalyzer):
    """Analyzer for HTML and CSS files."""
    
    def get_language(self) -> str:
        return "html"
    
    def can_analyze(self, file_path: str, content: str) -> bool:
        """Check if this is an HTML or CSS file."""
        path_lower = file_path.lower()
        return (path_lower.endswith(('.html', '.htm', '.css', '.scss', '.sass', '.less')) or
                content.strip().startswith(('<!DOCTYPE', '<html', '<head', '<body')) or
                'text/html' in content[:200])
    
    def analyze(self, file_id: str, file_path: str, content: str) -> AnalysisResult:
        """Analyze HTML/CSS file content."""
        result = AnalysisResult(
            file_id=file_id,
            path=file_path,
            language="html"
        )
        
        try:
            if file_path.lower().endswith(('.html', '.htm')):
                self._analyze_html(content, result)
            elif file_path.lower().endswith(('.css', '.scss', '.sass', '.less')):
                self._analyze_css(content, result)
            
            # Extract file references
            result.file_references = self._extract_file_references(content)
            
            # Detect frameworks
            result.framework_signals = self._detect_frameworks(content)
            result.integration_signals = self._detect_integrations(content)
            
            # Set confidence
            result.analyzer_confidence = self._calculate_confidence(result)
            
        except Exception as e:
            logger.error(f"HTML/CSS analysis failed for {file_path}: {e}")
            result.limitations.append(f"Analysis failed: {str(e)}")
            result.analyzer_confidence = 0.1
        
        return result
    
    def _analyze_html(self, content: str, result: AnalysisResult):
        """Analyze HTML-specific patterns."""
        # Extract script references
        script_refs = re.findall(r'<script[^>]*src=["\']([^"\']+)["\']', content, re.IGNORECASE)
        result.includes = script_refs
        
        # Extract stylesheet references
        css_refs = re.findall(r'<link[^>]*href=["\']([^"\']+\.css[^"\']*)["\']', content, re.IGNORECASE)
        result.file_references.extend(css_refs)
        
        # Extract entrypoint hints
        result.entrypoint_hints = self._detect_html_entrypoint_hints(content)
        
        # Extract UI hints
        result.ui_hints = self._extract_html_ui_hints(content)
        
        # Extract route hints (for SPAs)
        result.route_hints = self._extract_html_route_hints(content)
    
    def _analyze_css(self, content: str, result: AnalysisResult):
        """Analyze CSS-specific patterns."""
        # Extract @import statements
        import_refs = re.findall(r'@import\s+["\']([^"\']+)["\']', content, re.IGNORECASE)
        result.includes = import_refs
        
        # Extract URL references
        url_refs = re.findall(r'url\(["\']?([^"\')\s]+)["\']?\)', content, re.IGNORECASE)
        result.file_references.extend(url_refs)
        
        # Extract UI hints
        result.ui_hints = self._extract_css_ui_hints(content)
    
    def _detect_html_entrypoint_hints(self, content: str) -> List[str]:
        """Detect HTML entrypoint patterns."""
        hints = []
        
        # Main page indicators
        if '<title>' in content.lower():
            hints.append("html_page")
        
        # SPA indicators
        if any(pattern in content for pattern in ['<div id="root"', '<div id="app"', 'ng-app']):
            hints.append("spa_entry")
        
        # Landing page indicators
        if any(pattern in content.lower() for pattern in ['index.html', 'home', 'landing']):
            hints.append("landing_page")
        
        return hints
    
    def _extract_html_ui_hints(self, content: str) -> List[str]:
        """Extract HTML UI patterns."""
        ui_hints = []
        
        # Framework-specific patterns
        if any(pattern in content for pattern in ['ng-', 'angular', '[ngFor]', '(click)']):
            ui_hints.append("angular_template")
        
        if any(pattern in content for pattern in ['v-', 'vue', '{{', '}}']):
            ui_hints.append("vue_template")
        
        if any(pattern in content for pattern in ['{%', '{{', 'django', 'jinja']):
            ui_hints.append("template_engine")
        
        # Component patterns
        if re.search(r'<[a-z]+-[a-z-]+', content):  # Custom elements
            ui_hints.append("web_components")
        
        # Form patterns
        if '<form' in content.lower():
            ui_hints.append("form_interface")
        
        return ui_hints
    
    def _extract_html_route_hints(self, content: str) -> List[str]:
        """Extract routing patterns from HTML."""
        routes = []
        
        # Extract href patterns that look like routes
        href_patterns = re.findall(r'href=["\']([^"\']+)["\']', content, re.IGNORECASE)
        for href in href_patterns:
            if href.startswith(('/', '#/')) and not href.startswith(('http', 'mailto', 'tel')):
                routes.append(href)
        
        return routes
    
    def _extract_css_ui_hints(self, content: str) -> List[str]:
        """Extract CSS UI patterns."""
        ui_hints = []
        
        # Grid/Flexbox layouts
        if any(pattern in content for pattern in ['display: grid', 'display: flex', 'grid-template']):
            ui_hints.append("modern_layout")
        
        # Responsive design
        if '@media' in content:
            ui_hints.append("responsive_design")
        
        # Animation patterns
        if any(pattern in content for pattern in ['@keyframes', 'animation:', 'transition:']):
            ui_hints.append("animations")
        
        # Component styling
        if any(pattern in content for pattern in ['.component', '.widget', '.card']):
            ui_hints.append("component_styles")
        
        return ui_hints
    
    def _extract_file_references(self, content: str) -> List[str]:
        """Extract file references from HTML/CSS."""
        references = []
        
        # HTML file references
        html_patterns = [
            r'src=["\']([^"\']+)["\']',
            r'href=["\']([^"\']+)["\']',
            r'action=["\']([^"\']+)["\']',
        ]
        
        # CSS file references
        css_patterns = [
            r'url\(["\']?([^"\')\s]+)["\']?\)',
            r'@import\s+["\']([^"\']+)["\']',
        ]
        
        all_patterns = html_patterns + css_patterns
        
        for pattern in all_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                # Filter out external URLs and data URIs
                if not match.startswith(('http', 'https', 'data:', 'mailto:', 'tel:')):
                    references.append(match)
        
        return list(set(references))
    
    def _detect_frameworks(self, content: str) -> List[str]:
        """Detect CSS/HTML frameworks."""
        frameworks = []
        content_lower = content.lower()
        
        # CSS frameworks
        if any(fw in content_lower for fw in ['bootstrap', 'btn-primary', 'container-fluid']):
            frameworks.append("bootstrap")
        
        if any(fw in content_lower for fw in ['tailwind', 'tw-', 'bg-blue', 'text-center']):
            frameworks.append("tailwind")
        
        if any(fw in content_lower for fw in ['bulma', 'is-primary', 'column']):
            frameworks.append("bulma")
        
        if any(fw in content_lower for fw in ['foundation', 'grid-x', 'cell']):
            frameworks.append("foundation")
        
        # UI libraries
        if any(lib in content_lower for lib in ['material-ui', 'mui', 'mdc-']):
            frameworks.append("material_ui")
        
        if any(lib in content_lower for fw in ['ant-design', 'antd', 'ant-btn']):
            frameworks.append("ant_design")
        
        # Template engines
        if any(engine in content for engine in ['{%', '{{', '<%', '<#']):
            frameworks.append("template_engine")
        
        return frameworks
    
    def _detect_integrations(self, content: str) -> List[str]:
        """Detect third-party integrations."""
        integrations = []
        content_lower = content.lower()
        
        # Analytics
        if any(analytics in content_lower for analytics in ['google-analytics', 'gtag', 'ga(']):
            integrations.append("analytics")
        
        # Maps
        if any(maps in content_lower for maps in ['google-maps', 'mapbox', 'leaflet']):
            integrations.append("maps")
        
        # Social
        if any(social in content_lower for social in ['facebook', 'twitter', 'linkedin']):
            integrations.append("social_media")
        
        # Payment
        if any(payment in content_lower for payment in ['stripe', 'paypal', 'square']):
            integrations.append("payment")
        
        # CDN
        if any(cdn in content_lower for cdn in ['cdn.jsdelivr', 'unpkg', 'cdnjs']):
            integrations.append("cdn")
        
        return integrations
    
    def _calculate_confidence(self, result: AnalysisResult) -> float:
        """Calculate analysis confidence."""
        confidence = 0.0
        
        # Base confidence for successful parsing
        confidence += 0.4
        
        # Boost for file references
        if result.file_references:
            confidence += 0.2
        
        # Boost for includes (scripts/stylesheets)
        if result.includes:
            confidence += 0.2
        
        # Boost for UI patterns
        if result.ui_hints:
            confidence += 0.1
        
        # Boost for framework detection
        if result.framework_signals:
            confidence += 0.1
        
        return min(confidence, 1.0)
"""RAG (Retrieval-Augmented Generation) service for Ask Repo.

Robust fallback chain:
  A. Semantic search (vector embeddings)    -- used if embeddings exist
  B. Hybrid search (keyword + file content) -- used when embeddings are missing
  C. File-level keyword search              -- last resort before no_context
  D. no_context                             -- only if repository has zero indexed content
"""
from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models.embedding_chunk import EmbeddingChunk
from app.db.models.file import File
from app.db.models.symbol import Symbol
from app.llm.prompt_builder import build_system_prompt, build_user_prompt, build_repo_overview_prompt, build_flow_question_prompt
from app.llm.providers import get_chat_provider
from app.services.embedding_service import EmbeddingService
from app.services.graph_service import GraphService
import re

logger = logging.getLogger(__name__)

class QueryIntent:
    REPO_SUMMARY = "repo_summary"
    ARCHITECTURE_EXPLANATION = "architecture_explanation"
    FLOW_QUESTION = "flow_question"          # how does X work, startup flow, request flow
    FILE_LOOKUP = "file_lookup"
    SYMBOL_LOOKUP = "symbol_lookup"
    DEPENDENCY_TRACE = "dependency_trace"
    LINE_IMPACT = "line_impact"
    LINE_CHANGE_IMPACT = "line_change_impact"
    FILE_IMPACT = "file_impact"
    CODE_SNIPPET_IMPACT = "code_snippet_impact"
    DEPENDENCY_IMPACT = "dependency_impact"      # deleting from manifest/config
    CONFIG_IMPACT = "config_impact"              # deleting from env/infra config
    ROUTE_FEATURE_IMPACT = "route_feature_impact"  # "delete the login route"
    SEMANTIC_QA = "semantic_qa"


class QueryMode:
    GENERAL = "general"
    CODE = "code"
    IMPACT = "impact"


class QueryClassifier:
    @staticmethod
    def classify(question: str) -> dict:
        """Classify query intent. Never raises — always returns a safe default."""
        try:
            return QueryClassifier._classify_body(question)
        except Exception as _classify_exc:
            logger.error(f"QueryClassifier.classify crashed: {_classify_exc}", exc_info=True)
            return {"intent": QueryIntent.SEMANTIC_QA, "mode": QueryMode.GENERAL}

    @staticmethod
    def _clean_snippet(text: str) -> str:
        """Strip trailing noise words that aren't part of the actual code."""
        if not text:
            return ""
        # Multi-pass strip for noise tokens at the end of the query
        text = text.strip().strip("`'\"")
        
        # Aggressive multi-pass removal of terminal "noise" words
        # We handle "at line X", "on line X", "line X", etc.
        noise_patterns = [
            r"\s+(?:line|lines|statement|statements|code|snippet|word|context|from this repo|in this codebase|in the code|marker|segment)\.?\s*$",
            r"(?:the\s+)?(?:line|lines|statement|statements|code|snippet|word|context)\s+(?:of|in|from)\s+.*$",
            r"\s+at\s+line\s+\d+\.?\s*$",
            r"\s+on\s+line\s+\d+\.?\s*$",
            r"\s+line\s+\d+\.?\s*$",
        ]
        
        changed = True
        while changed:
            original = text
            for pat in noise_patterns:
                text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()
            changed = (text != original)
            
        return text

    @staticmethod
    def _classify_body(question: str) -> dict:
        q = question.lower()
        raw = question  # preserve original casing for snippet extraction

        # ---- PRIORITY -1: Repo-wide summary / overview questions — catch FIRST
        # These must never fall through to generic semantic fallback.
        # Detection uses both exact phrases AND keyword-based semantic signals.
        _REPO_SUMMARY_PHRASES = [
            "what does this repo do", "what does this project do",
            "what does the repo do", "what does the project do",
            "summarize this repo", "summarize this project",
            "summarize the repo", "summarize the project",
            "explain this repo", "explain this project",
            "explain the repo", "explain the project",
            "what is this repo", "what is this project",
            "what is this codebase", "what is this code",
            "what is this app", "what is this application",
            "overview of this repo", "overview of the repo",
            "overview of this project", "give me an overview",
            "how does this repo work", "how does the repo work",
            "how does this project work", "how does the project work",
            "what is this for", "what is this used for",
            "what does this do", "what is this",
            "describe this repo", "describe this project",
            "describe the codebase", "tell me about this repo",
            "tell me about this project", "what is the purpose",
            "project summary", "repo summary", "codebase overview",
            "what am i looking at", "what is the architecture", "how is this structured",
        ]
        # Keyword-based semantic signals for repo-level questions
        # Catches: "what framework is used", "where does the app start", "what stack is this"
        _REPO_SCOPE_WORDS = {
            "repo", "repository", "project", "codebase", "app", "application",
            "this code", "this system", "this service", "this backend", "this frontend",
        }
        _REPO_INTENT_WORDS = {
            "what framework", "what stack", "what language", "what tech",
            "what database", "what does it use", "what is used",
            "where does it start", "where does the app start", "where does this start",
            "how is it built", "how is this built", "how does it work",
            "what is the main", "what is the entry", "what is the purpose",
            "what does it do", "what does this do",
            "explain the", "describe the", "summarize the",
            "give me a summary", "give an overview", "high level",
            "high-level", "big picture", "overall structure",
        }
        _is_repo_scope = any(w in q for w in _REPO_SCOPE_WORDS)
        _is_repo_intent = any(phrase in q for phrase in _REPO_INTENT_WORDS)
        _has_arch_words = any(a in q for a in [
            "architecture", "structure", "design", "organized", "flow",
            "layers", "modules", "components", "services", "how it works",
        ])

        if any(phrase in q for phrase in _REPO_SUMMARY_PHRASES) or (_is_repo_intent and not any(
            # Exclude code-specific questions that happen to mention the repo
            tok in q for tok in ("line ", "function ", "def ", "class ", "import ", "delete ", "remove ")
        )):
            # Distinguish architecture from general summary
            if _has_arch_words:
                return {"intent": QueryIntent.ARCHITECTURE_EXPLANATION, "mode": QueryMode.GENERAL}
            return {"intent": QueryIntent.REPO_SUMMARY, "mode": QueryMode.GENERAL}

        # ---- PRIORITY -0.5: line/snippet explanation questions
        # Examples:
        #  - what does load_dotenv('.env') do
        #  - what does cred_path = os.getenv(...) do
        if any(x in q for x in ["what does", "explain this line", "explain this code"]):
            explain_match = re.search(
                r"(?:what does|explain(?: this line| this code)?)(.+?)(?:\s+do)?\s*$",
                raw,
                re.IGNORECASE | re.DOTALL,
            )
            candidate = explain_match.group(1).strip(" `\"'") if explain_match else ""
            if candidate and any(tok in candidate for tok in ("=", "(", ")", ".", ":", "[", "]")):
                return {
                    "intent": QueryIntent.SEMANTIC_QA,
                    "mode": QueryMode.CODE,
                    "snippet": QueryClassifier._clean_snippet(candidate),
                }

        # ---- PRIORITY 0: Explicit Code Statement Impact — catch before dependency regex
        # Detect quoted snippets or patterns like "delete import ... from ..."
        _CODE_SNIPPET_PAT = re.compile(
            r"(?:delete|remove|change|replace|impact of)\s+"
            r"(?:the\s+line\s+)?(?:[`'\"\u2018\u2019])?(.{5,})(?:[`'\"\u2018\u2019])?",
            re.IGNORECASE
        )
        snippet_match = _CODE_SNIPPET_PAT.search(raw)
        if snippet_match:
            snippet_raw = snippet_match.group(1)
            # Loosen detection: CSS often has { but no }, partial tags might have < but no >
            # Common code punctuation/keywords or typical CSS/HTML indicators
            _CODE_INDICATORS = (
                "import", "require", "function", "def ", "class ", "return ", "if ", "var ", "let ", "const ",
                "{", "}", "<", ">", ";", "=>", " : ", " = ", ".#", "()"
            )
            
            _is_likely_code_or_markup = (
                any(k in snippet_raw.lower() for k in _CODE_INDICATORS) or
                # CSS selector /.classname / #idname / tagname {
                re.search(r"^[a-z0-9_\-\.#][a-z0-9_\-]*\s*\{", snippet_raw.lower()) or
                # HTML tag <tag / </tag
                re.search(r"<\/?[a-z1-6]+", snippet_raw.lower()) or
                # Generic selector starting with . or #
                re.search(r"^[\.#][a-z0-9_\-]", snippet_raw.lower())
            )
            
            if _is_likely_code_or_markup:
                snippet = QueryClassifier._clean_snippet(snippet_raw)
                return {
                    "intent": QueryIntent.LINE_IMPACT,
                    "mode": QueryMode.IMPACT,
                    "snippet": snippet,
                }

        # ---- PRIORITY 0a: Dependency / Manifest impact
        # "what happens if I delete flask from requirements.txt"
        # "what will happen if I remove sqlalchemy"  (implies dependency)
        _MANIFEST_FILES = {
            "requirements.txt", "requirements-dev.txt", "pyproject.toml",
            "pipfile", "package.json", "yarn.lock", "pnpm-lock.yaml",
            "package-lock.json", "go.mod", "cargo.toml", "pipfile.lock",
        }
        _MANIFEST_PAT = re.compile(
            r"(?:delete|remove|uninstall|drop|comment out)\s+"
            r"(?:the\s+)?(?:[`'\"\u2018\u2019]?)([a-zA-Z0-9_\-\.\[\]]+)"
            r"(?:[`'\"\u2018\u2019]?)"
            r"(?:\s+from\s+([a-zA-Z0-9/_\.\-]+))?",
            re.IGNORECASE,
        )
        manifest_match = _MANIFEST_PAT.search(raw)
        # Explicitly mentioned manifest file?
        mentions_manifest = any(m in q for m in [
            "requirements", "pyproject", "package.json", "pipfile",
            "go.mod", "cargo.toml", "pnpm-lock", "yarn.lock",
            "package-lock", "dockerfile", "docker-compose", "compose",
        ])
        # OR: the pattern looks like a package name delete without JSX/code markers
        _looks_like_package = (
            manifest_match and
            "<" not in raw and "(" not in raw and
            any(x in q for x in ["dependency", "package", "library", "module", "install",
                                   "pip install", "npm install", "requirements", "import"])
        )

        if mentions_manifest or _looks_like_package:
            pkg = manifest_match.group(1).strip() if manifest_match else ""
            manifest_file = manifest_match.group(2).strip() if (manifest_match and manifest_match.group(2)) else ""
            return {
                "intent": QueryIntent.DEPENDENCY_IMPACT,
                "mode": QueryMode.IMPACT,
                "package": pkg,
                "manifest_file": manifest_file,
                "snippet": pkg,
            }

        # ---- PRIORITY 0b: Config / Infra impact
        # "what happens if I delete [env var / dockerfile instruction / compose service]"
        _CONFIG_FILES = {
            ".env", "dockerfile", "docker-compose", "compose.yml",
            ".github", "nginx.conf", "config.yaml", "config.toml",
            "settings.py", "config.py",
        }
        mentions_config = any(c in q for c in [
            ".env", "dockerfile", "docker-compose", "compose", "nginx",
            "env var", "environment variable", "config file",
        ])
        if mentions_config and any(x in q for x in ["delete", "remove", "change", "comment"]):
            return {
                "intent": QueryIntent.CONFIG_IMPACT,
                "mode": QueryMode.IMPACT,
                "snippet": raw,
            }

        # ---- PRIORITY 0c: Natural-language route/feature impact
        # "what happens if I delete the login route"
        # "what will happen if I remove the checkout page"
        _FEATURE_NOUNS = [
            "route", "page", "endpoint", "view", "controller", "handler",
            "template", "component", "api", "auth", "login", "logout",
            "dashboard", "admin", "shop", "cart", "checkout", "search",
            "profile", "settings", "register", "signup", "user", "product",
            "order", "payment", "upload", "download", "webhook", "middleware",
            "worker", "job", "task", "service", "model", "schema",
        ]
        _has_feature_delete = any(x in q for x in ["delete the", "remove the", "what if i delete", "what happens if i remove"])
        if _has_feature_delete and any(fn in q for fn in _FEATURE_NOUNS):
            # Extract the feature noun phrase
            feature_match = re.search(
                r"(?:delete|remove)\s+the\s+([a-zA-Z0-9_\-\s]+?)(?:\s+(?:route|page|endpoint|view|component|api|handler))?(?:\s*\?|$)",
                raw,
                re.IGNORECASE,
            )
            feature_phrase = feature_match.group(1).strip() if feature_match else q
            return {
                "intent": QueryIntent.ROUTE_FEATURE_IMPACT,
                "mode": QueryMode.IMPACT,
                "feature": feature_phrase,
                "snippet": feature_phrase,
            }

        # Catches: "rename heading to h", "change heading to h",
        # "what'll happen if I change JLabel heading = ... heading to h"
        # Pattern: look for "X to Y" where X and Y are identifiers, and a change/rename verb nearby
        _RENAME_PAT = re.compile(
            r"(?:rename|change|renames?)\s+"
            r"(?:[^\n]*?)?"           # optional pasted code in between
            r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b"   # symbol name (old)
            r"\s+to\s+"
            r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b",  # new name
            re.IGNORECASE | re.DOTALL,
        )
        rename_match = _RENAME_PAT.search(raw)
        if rename_match:
            symbol_name = rename_match.group(1).strip()
            new_name = rename_match.group(2).strip()
            # Skip if this looks like a file-path rename (has dots/slashes)
            if "." not in symbol_name and "/" not in symbol_name:
                # Extract the pasted code snippet if present (text before the "X to Y" at the end)
                # Look for multiline content suggesting a pasted declaration
                lines_in_query = raw.strip().splitlines()
                code_snippet = None
                for line in lines_in_query:
                    l = line.strip()
                    # A line that looks like actual code (has = or (); or starts with a type keyword)
                    if ("=" in l or l.endswith(";") or l.endswith("{") or
                            any(k in l for k in ["new ", "import ", "public ", "private ",
                                                  "protected ", "static ", "final ", "class ",
                                                  "void ", "int ", "String ", "bool "])):
                        code_snippet = l
                        break  # take first code-looking line as the declaration to resolve
                return {
                    "intent": QueryIntent.LINE_CHANGE_IMPACT,
                    "operation": "rename",
                    "symbol_name": symbol_name,
                    "new_name": new_name,
                    "old_text": code_snippet or symbol_name,  # used by LineResolver
                    "new_text": new_name,
                    "file": "",
                }

        # ---- PRIORITY 1: line N in file + change/replace question
        # e.g. "replace X with Y in app/main.py" or "change line 5 in ..."
        change_file_line = re.search(
            r"(?:replace|change|modify)\s+(?:line\s+(\d+)\s+in\s+)?([a-zA-Z0-9\/\._\-]+)",
            q,
        )
        # replace `X` with `Y` in file  (backtick/quote conflict avoided via compiled pattern)
        _REPLACE_PAT = re.compile(
            r"replace\s+[`'\"\u2018\u2019]?(.+?)[`'\"\u2018\u2019]?"
            r"\s+with\s+[`'\"\u2018\u2019]?(.+?)[`'\"\u2018\u2019]?"
            r"(?:\s+in\s+([a-zA-Z0-9/._\-]+))?",
            re.IGNORECASE,
        )
        replace_match = _REPLACE_PAT.search(raw)
        if replace_match:
            return {
                "intent": QueryIntent.LINE_CHANGE_IMPACT,
                "old_text": replace_match.group(1).strip(),
                "new_text": replace_match.group(2).strip(),
                "file": replace_match.group(3) or "",
            }

        # ---- PRIORITY 2: explicit line number + file path (delete/change)
        line_num_match = re.search(
            r"(?:delete|remove|change|modify)?\s*line\s+(\d+)\s+in\s+([a-zA-Z0-9\/\._\-]+)",
            q,
        )
        if line_num_match:
            return {
                "intent": QueryIntent.LINE_IMPACT,
                "line": int(line_num_match.group(1)),
                "file": line_num_match.group(2),
                "snippet": None,
                "operation": "delete" if any(x in q for x in ["delete", "remove"]) else "change",
            }

        # FIX: snippet_in_file was used before being defined -> NameError
        _SNIPPET_IN_FILE_PAT = re.compile(
            r"(?:delete|remove|change)\s+[`\'\"\u2018\u2019]([^`\'\"\u2018\u2019\n]+)[`\'\"\u2018\u2019]"
            r"\s+in\s+([a-zA-Z0-9/._\-]+)",
            re.IGNORECASE,
        )
        snippet_in_file = _SNIPPET_IN_FILE_PAT.search(raw)
        if snippet_in_file:
            return {
                "intent": QueryIntent.LINE_IMPACT,
                "snippet": snippet_in_file.group(1).strip(),
                "file": snippet_in_file.group(2).strip(),
                "line": None,
                "operation": "delete" if "delete" in q else "change",
            }

        # ---- NEW PRIORITY: Catch deep code snippet without a file path ----
        # e.g. "what happens if I delete from logging.config import fileConfig"
        _LEXICAL_IMPACT_PAT = re.compile(
            r"(?:delete|remove|change|replace)\s+[`'\"\u2018\u2019]?((?:from |import |def |class |public |private )[a-zA-Z0-9_\. ,\*]+)[`'\"\u2018\u2019]?",
            re.IGNORECASE
        )
        lexical_impact_match = _LEXICAL_IMPACT_PAT.search(raw)
        if lexical_impact_match:
            _lexical_snippet = QueryClassifier._clean_snippet(lexical_impact_match.group(1))
            return {
                "intent": QueryIntent.CODE_SNIPPET_IMPACT,
                "snippet": _lexical_snippet,
                "mode": QueryMode.IMPACT,
            }

        # ---- PRIORITY 4: "delete/remove this line" with pasted code (no file)
        if any(m in q for m in ["delete this line", "remove this line", "change this line"]):
            snippet = re.sub(
                r"what\s+(?:will\s+)?(?:happen|happens|breaks)\s+if\s+i\s+(?:delete|remove|change)\s+this\s+line\??",
                "",
                raw,
                flags=re.IGNORECASE,
            ).strip(" ?'\"\n")
            return {
                "intent": QueryIntent.CODE_SNIPPET_IMPACT,
                "snippet": snippet,
                "file": "",
            }

        # ---- PRIORITY 5: "what happens if I delete <code-like string> in file"
        # Catch: "what happens if I delete `from app.routes import auth` in ..."
        # delete/remove <snippet> in <file> (backtick/quote conflict avoided via compiled pattern)
        _LOOSE_SNIPPET_PAT = re.compile(
            r"(?:delete|remove)\s+[`'\"\u2018\u2019]?([a-zA-Z_].+?)[`'\"\u2018\u2019]?"
            r"\s+in\s+([a-zA-Z0-9/._\-]+)",
            re.IGNORECASE,
        )
        loose_snippet_in_file = _LOOSE_SNIPPET_PAT.search(raw)
        if loose_snippet_in_file:
            return {
                "intent": QueryIntent.LINE_IMPACT,
                "snippet": loose_snippet_in_file.group(1).strip(),
                "file": loose_snippet_in_file.group(2).strip(),
                "line": None,
                "operation": "delete",
            }

        # ---- PRIORITY 9: JSX/HTML element deletion (tag-like content)
        # e.g. what will happen if I delete <p className="mt-1 text-sm text-slate-400"> line
        _JSX_TAG_PAT = re.compile(
            r"(?:delete|remove|change)\s+(?:the\s+)?(<[^>\n]{1,200}>(?:[^<\n]*</[^>]+>)?)",
            re.IGNORECASE,
        )
        jsx_match = _JSX_TAG_PAT.search(raw)
        if jsx_match:
            return {
                "intent": QueryIntent.CODE_SNIPPET_IMPACT,
                "snippet": jsx_match.group(1).strip(),
                "mode": QueryMode.IMPACT,
            }

        # ---- PRIORITY 9b: Catch-all for any delete/remove query
        # Last chance before keyword fallback — extract best available snippet.
        # Catches: "what will happen if I delete <p className=...> line" (unquoted)
        _has_delete = any(x in q for x in ["delete", "remove", "happen if", "what if i", "what breaks"])
        if _has_delete:
            snippet_extract = re.search(
                r"(?:delete|remove)\s+(?:the\s+)?(?:line\s+)?(.{3,}?)\s*(?:line\s*)?(?:\?|$)",
                raw,
                re.IGNORECASE | re.DOTALL,
            )
            extracted = QueryClassifier._clean_snippet(snippet_extract.group(1)) if snippet_extract else ""
            return {
                "intent": QueryIntent.CODE_SNIPPET_IMPACT,
                "snippet": extracted or question,
                "mode": QueryMode.IMPACT,
            }

        # ---- PRIORITY 10: Final Fallback Classification ----
        res = {}
        # 1. IMPACT Detection (Expanding keywords)
        # Note: "move" is excluded here to avoid catching "how does data move through the app"
        impact_keywords = {
            "delete", "remove", "change", "what breaks", "impact", "blast radius", 
            "happen if", "what if", "regression", "side effect", "risk", "breaking",
            "consequences", "modify", "rename",
        }
        # "move" only counts as impact when combined with explicit change/delete context
        _has_move_impact = "move" in q and any(x in q for x in ["file", "function", "class", "symbol", "this"])
        if any(x in q for x in impact_keywords) or _has_move_impact:
            res["mode"] = QueryMode.IMPACT
            if any(x in q for x in ["usages", "who calls", "refs", "depend", "caller", "callee"]):
                res["intent"] = QueryIntent.DEPENDENCY_TRACE
            else:
                res["intent"] = QueryIntent.CODE_SNIPPET_IMPACT
        
        # 2. FLOW / ARCHITECTURE Questions — catch "how does X work" patterns
        # Examples: "how does login work", "how does request flow", "what is the startup flow"
        elif any(x in q for x in ["how does", "how do", "flow of", "flow for", "startup flow", "request flow", "auth flow", "login flow", "data flow", "data move", "move through"]):
            # Distinguish from code-level "how does this line work"
            if not any(tok in q for tok in ["this line", "this code", "this snippet", "this function"]):
                res["mode"] = QueryMode.GENERAL
                res["intent"] = QueryIntent.FLOW_QUESTION
        
        # 3. CODE Detection — FIX: corrected operator precedence (was broken `or`/`and` chain)
        elif (
            any(c in question for c in {"(", ")", "{", "}", "import ", "from ", "[]", "=>", "->"})
            or (
                any(x in q for x in ["where is", "implemented", "how does", "logic of", "logic behind", "flow of"])
                and any(c in question for c in {".", "/", "_", ":"})
            )
            or any(x in q for x in ["where is", "where is this", "where is that", "used", "usage of", "references of", "called", "who calls", "explain this line", "what does this line",
                                     "which files import", "which files use", "files that import", "files that use"])
        ):
            res["mode"] = QueryMode.CODE
            if any(x in q for x in ["where is", "used", "usage of", "references of", "called", "who calls",
                                     "which files import", "which files use", "files that import", "files that use"]):
                res["intent"] = QueryIntent.SYMBOL_LOOKUP
            else:
                res["intent"] = QueryIntent.SEMANTIC_QA
            
        # 4. GENERAL Mode (Repo-wide summary or architectural overview)
        elif any(x in q for x in ["architecture", "purpose", "stack", "summary", "overview", "high level", "structure", "boilerplate"]) or              any(phrase in q for phrase in _REPO_SUMMARY_PHRASES):
            res["mode"] = QueryMode.GENERAL
            res["intent"] = QueryIntent.REPO_SUMMARY
            
        # 5. Fallback (Semantic QA)
        else:
            res["mode"] = QueryMode.GENERAL
            res["intent"] = QueryIntent.SEMANTIC_QA

        return res


# ---------------------------------------------------------------------------
# Line Type Detector — classifies what a single code line does
# ---------------------------------------------------------------------------

class LineTypeDetector:
    # Ordered patterns — first match wins
    _PATTERNS = [
        ("import",          re.compile(r"^\s*(import |from .+ import )", re.IGNORECASE)),
        ("router_include",  re.compile(r"include_router", re.IGNORECASE)),
        ("middleware_reg",  re.compile(r"add_middleware", re.IGNORECASE)),
        ("db_init",         re.compile(r"(create_engine|sessionmaker|Base\.metadata\.create_all)", re.IGNORECASE)),
        ("decorator",       re.compile(r"^\s*@")),
        ("function_def",    re.compile(r"^\s*(async\s+)?(def|function)\s+\w+")),
        ("class_def",       re.compile(r"^\s*class \w+")),
        ("route_def",       re.compile(r"@(app|router)\.(get|post|put|delete|patch|options|head)\(", re.IGNORECASE)),
        # JS/TS specific heuristics
        ("dom_selection",   re.compile(r"(getElementById|querySelector|querySelectorAll|getElementsByClassName)\(")),
        ("event_listener",  re.compile(r"addEventListener\(")),
        ("local_storage",   re.compile(r"(localStorage|sessionStorage)\.")),
        ("react_hook",      re.compile(r"(useState|useEffect|useContext|useReducer|useCallback|useMemo)\(")),
        ("api_call",        re.compile(r"(fetch|axios\.(get|post|put|delete))\(")),
        ("return_stmt",     re.compile(r"^\s*return ")),
        # JS arrow functions and function expressions (must come before variable_init)
        ("function_signature", re.compile(
            r"^\s*(export\s+)?(default\s+)?(async\s+)?"
            r"(function\s+\w+|const\s+\w+\s*=\s*(async\s+)?\(|"
            r"let\s+\w+\s*=\s*(async\s+)?(\(|function)|"
            r"var\s+\w+\s*=\s*(async\s+)?function|"
            r"const\s+\w+\s*=\s*(async\s+)?function)"
        )),
        ("variable_init",   re.compile(r"^\s*(const|let|var)\s+\w+\s*=")),
        ("assignment",      re.compile(r"^\s*[\w\.]+\s*=")),
        ("function_call",   re.compile(r"^\s*[a-zA-Z_][\w.]*\s*\(")),
        ("env_lookup",      re.compile(r"(os\.environ|os\.getenv|config\.get|settings\.|process\.env)", re.IGNORECASE)),
        ("exception",       re.compile(r"^\s*(try:|except |raise |finally:|catch\s*\()")),
        ("log_stmt",        re.compile(r"console\.(log|error|warn|info)")),
        ("html_markup",     re.compile(r"<[a-zA-Z1-6]+.*?>")),
        ("config_property", re.compile(r"""^\s*[\w\-'"]+\s*:\s*(?:[^<\s][^,\n]*)?,?$""")),
    ]

    @classmethod
    def detect(cls, line_text: str) -> str:
        for name, pat in cls._PATTERNS:
            if pat.search(line_text):
                return name
        return "other"


# ---------------------------------------------------------------------------
# Line Resolver — resolves file path + line number / snippet to exact context
# ---------------------------------------------------------------------------

class LineResolver:
    def __init__(self, db: Session):
        self.db = db

    def resolve(
        self,
        repository_id: str,
        file_hint: str = "",
        line_no: int | None = None,
        snippet: str | None = None,
        context_radius: int = 8,
    ) -> dict | None:
        """
        Returns a resolution dict or None if nothing found.
        Fields: file_path, file_id, line_no, line_text,
                context_before, context_after, enclosing_symbol, line_type, found
        """
        file_record = None

        if file_hint:
            # Try exact path first, then ilike
            file_record = self.db.scalar(
                select(File).where(
                    File.repository_id == repository_id,
                    File.path.ilike(f"%{file_hint}%"),
                )
            )

        resolved_line_no: int | None = line_no

        if file_record and snippet and resolved_line_no is None:
            # Resolve snippet to exact line within this file
            resolved_line_no = self._find_snippet_line(file_record.content or "", snippet)

        elif not file_record and snippet:
            # Global search: find the snippet across all files
            # Over-fetch and prioritize source code files over docs/assets
            _SOURCE_EXTS_LR = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp",
                               ".h", ".go", ".rs", ".rb", ".php", ".cs", ".swift", ".kt",
                               ".html", ".htm", ".css", ".scss", ".vue", ".svelte"}
            raw_candidates = list(self.db.scalars(
                select(File).where(
                    File.repository_id == repository_id,
                    File.content.ilike(f"%{snippet[:120]}%"),
                ).limit(15)
            ).all())
            # Sort: source files first, then by path length (shorter = more central)
            def _lr_sort(f):
                ext = "." + f.path.rsplit(".", 1)[-1].lower() if "." in f.path else ""
                return (0 if ext in _SOURCE_EXTS_LR else 1, len(f.path))
            candidates = sorted(raw_candidates, key=_lr_sort)
            # Pick the best candidate that actually contains the snippet on a line
            for cand in candidates:
                ln = self._find_snippet_line(cand.content or "", snippet)
                if ln is not None:
                    file_record = cand
                    resolved_line_no = ln
                    break

        if file_record is None or resolved_line_no is None:
            return {
                "found": False,
                "file_hint": file_hint,
                "snippet_searched": snippet or "",
            }

        content = file_record.content or ""
        lines = content.splitlines()
        idx = resolved_line_no - 1  # 0-indexed
        line_text = lines[idx] if 0 <= idx < len(lines) else ""

        before_start = max(0, idx - context_radius)
        after_end = min(len(lines), idx + context_radius + 1)

        context_before = "\n".join(
            f"{before_start + i + 1}: {l}" for i, l in enumerate(lines[before_start:idx])
        )
        context_after = "\n".join(
            f"{idx + i + 2}: {l}" for i, l in enumerate(lines[idx + 1:after_end])
        )

        # Enclosing symbol lookup
        symbol = self.db.scalars(
            select(Symbol).where(
                Symbol.file_id == file_record.id,
                Symbol.start_line <= resolved_line_no,
                Symbol.end_line >= resolved_line_no,
            )
        ).first()
        enclosing = f"{symbol.name} ({symbol.symbol_type})" if symbol else "module-level"

        line_type = LineTypeDetector.detect(line_text)

        # Local JS/TS dataflow heuristics
        heuristics = {}
        if path_str := file_record.path.lower():
            if path_str.endswith(".js") or path_str.endswith(".ts") or path_str.endswith(".jsx") or path_str.endswith(".tsx"):
                idx = resolved_line_no - 1
                after_lines = lines[idx+1:idx+40]
                
                # Check what variable is created here
                import re as _re
                m_var = _re.search(r"(?:const|let|var)\s+([\w]+)\s*=", line_text)
                if m_var:
                    var_name = m_var.group(1)
                    # How is it used next?
                    used_in_if = any(_re.search(rf"if\s*\([^)]*{var_name}", l) for l in after_lines)
                    reassigned = any(_re.search(rf"^\s*{var_name}\s*=", l) for l in after_lines)
                    used_in_dom = any(_re.search(rf"(appendChild|innerHTML|innerText).*?{var_name}", l) for l in after_lines)
                    used_in_return = any(_re.search(rf"return\s+.*{var_name}", l) for l in after_lines)
                    is_used = used_in_if or reassigned or used_in_dom or used_in_return or any(var_name in l for l in after_lines)
                    
                    heuristics["var_name"] = var_name
                    heuristics["reassigned"] = reassigned
                    heuristics["used_in_dom"] = used_in_dom
                    heuristics["used_in_if"] = used_in_if
                    heuristics["used_in_return"] = used_in_return
                    heuristics["is_used"] = is_used

                # Event listener flow
                if "addEventListener" in line_text:
                    m_ev = _re.search(r"addEventListener\(['\"](.*?)['\"].*?(?:=>|function)", line_text)
                    if m_ev:
                        heuristics["event_type"] = m_ev.group(1)

                # Config property extraction
                m_conf = _re.search(r"^\s*([\w\-\'\"]+)\s*:\s*([^\s].*?)(?:,|;|$)", line_text)
                if m_conf and "{" not in m_conf.group(1):
                    prop_name = m_conf.group(1).strip("'\"").strip()
                    prop_val = m_conf.group(2).strip()
                    
                    if line_type == "config_property" or len(prop_name) > 0:
                        heuristics["config_prop"] = prop_name
                        heuristics["config_val"] = prop_val
                        
                        context = " ".join(lines[max(0, resolved_line_no - 15) : min(len(lines), resolved_line_no + 15)])
                        if _re.search(r"new\s+[A-Z]\w+\s*\(", context):
                            heuristics["config_context"] = "class initialization"
                        elif "options" in context.lower():
                            heuristics["config_context"] = "options block"
                        elif "config" in context.lower():
                            heuristics["config_context"] = "config block"
                        else:
                            heuristics["config_context"] = "object literal"

        return {
            "found": True,
            "file_id": str(file_record.id),
            "file_path": file_record.path,
            "file_record": file_record,
            "line_no": resolved_line_no,
            "line_text": line_text,
            "context_before": context_before,
            "context_after": context_after,
            "enclosing_symbol": enclosing,
            "line_type": line_type,
            "symbol_record": symbol,
            "js_heuristics": heuristics,
        }

    def _normalize_code(self, code: str) -> str:
        """Normalizes code for structural comparison (whitespace/quotes/semicolons)."""
        if not code:
            return ""
        # 1. Normalize quotes
        code = code.replace("'", '"')
        # 2. Normalize whitespace
        code = " ".join(code.split())
        # 3. Strip trailing semicolon
        code = code.rstrip(";")
        return code.lower()

    def _find_snippet_line(self, content: str, snippet: str) -> int | None:
        """Finds the best matching line for a snippet using structural comparison."""
        target = self._normalize_code(snippet)
        if not target:
            return None

        lines = content.splitlines()
        for i, line in enumerate(lines):
            # Try direct match first
            if target in self._normalize_code(line):
                return i + 1
        
        # Fallback: if snippet is multiline, try matching first line
        first_line = snippet.splitlines()[0] if "\n" in snippet else None
        if first_line:
            target_first = self._normalize_code(first_line)
            for i, line in enumerate(lines):
                if target_first in self._normalize_code(line):
                    return i + 1

        return None


# ---------------------------------------------------------------------------
# Deterministic fallback explanation engine
# ---------------------------------------------------------------------------
# Produces query-aware, plain-English answers from retrieved evidence when
# the LLM is unavailable.  All logic is generic — no repo-specific strings.

import re as _re_explain


def _classify_line(line: str) -> str:
    """Return a short label for what kind of code line this is."""
    s = line.strip()
    if _re_explain.match(r"^\s*(from\s+\S+\s+import|import\s+)", s):
        return "import"
    if _re_explain.search(r"\bos\.getenv\b|\bprocess\.env\b|\bos\.environ\b|\bconfig\.get\b|\bsettings\.", s):
        return "env_lookup"
    if _re_explain.match(r"^\s*(async\s+)?def\s+\w+|^\s*(export\s+)?(async\s+)?function\s+\w+", s):
        return "function_def"
    if _re_explain.match(r"^\s*class\s+\w+", s):
        return "class_def"
    if _re_explain.search(r"\.(get|post|put|delete|patch)\s*\(|@(app|router)\.(get|post|put|delete|patch)", s):
        return "route_def"
    if _re_explain.search(r"\baddEventListener\b|\bon\w+\s*=\s*function|\bon\w+\s*=\s*\(", s):
        return "event_listener"
    if _re_explain.match(r"^\s*[\w\.]+\s*=\s*.+", s) and "==" not in s:
        return "assignment"
    if _re_explain.search(r"\w+\s*\(", s):
        return "function_call"
    return "other"


def _explain_line(line: str, file_path: str, context_lines: list[str]) -> str:
    """
    Produce a plain-English explanation of a single code line using its
    type and surrounding context.  Generic — no repo-specific knowledge.
    Plain text only — no markdown bold, no backtick-heavy formatting.
    """
    kind = _classify_line(line)
    s = line.strip()
    fp = file_path or "unknown file"

    if kind == "import":
        m = _re_explain.match(r"from\s+(\S+)\s+import\s+(.+)", s)
        if m:
            module, symbols = m.group(1), m.group(2).strip()
            symbols_clean = symbols.rstrip(",").strip()
            return (
                f"This line imports {symbols_clean} from the {module} package, "
                f"making it available for use in {fp}. "
                f"If this line is removed, any reference to {symbols_clean} in this file "
                f"will raise a NameError or ImportError at runtime."
            )
        m2 = _re_explain.match(r"import\s+(\S+)", s)
        if m2:
            module = m2.group(1)
            return (
                f"This line imports the {module} module into {fp}. "
                f"Removing it will cause a NameError wherever {module} is referenced in this file."
            )

    if kind == "env_lookup":
        m = _re_explain.search(
            r"(\w+)\s*=\s*(?:os\.getenv|os\.environ\.get|process\.env(?:\[|\.))\s*\(?\s*['\"]([^'\"]+)['\"]"
            r"(?:\s*,\s*['\"]?([^'\")\n]+)['\"]?)?",
            s,
        )
        if m:
            var_name = m.group(1)
            env_key = m.group(2)
            default = (m.group(3) or "").strip().strip("'\"") if m.group(3) else None

            ctx_text = " ".join(context_lines).lower()
            usage_hint = ""
            if any(w in ctx_text for w in ("credential", "cred", "service_account", "firebase", "auth")):
                usage_hint = " This appears to be a credentials or authentication path."
            elif any(w in ctx_text for w in ("database", "db_url", "postgres", "mongo", "redis")):
                usage_hint = " This appears to be a database connection string."
            elif any(w in ctx_text for w in ("secret", "token", "api_key", "apikey")):
                usage_hint = " This appears to be a secret key or API token."
            elif any(w in ctx_text for w in ("port", "host", "url", "endpoint")):
                usage_hint = " This appears to be a service address or port."

            default_clause = (
                f" If the variable is not set, it falls back to \"{default}\"."
                if default else
                " If the variable is not set, it returns None."
            )

            return (
                f"{var_name} is assigned by reading the {env_key} environment variable "
                f"from the process environment.{default_clause}{usage_hint} "
                f"This pattern keeps configuration out of source code — the actual value "
                f"is supplied at runtime via environment variables or a .env file."
            )

    if kind == "function_def":
        m = _re_explain.search(r"def\s+(\w+)\s*\(([^)]*)\)", s)
        if m:
            fname, params = m.group(1), m.group(2).strip()
            param_list = [p.strip().split(":")[0].split("=")[0].strip()
                          for p in params.split(",") if p.strip() and p.strip() != "self"]
            param_str = f" It accepts {len(param_list)} parameter(s): {', '.join(param_list)}." if param_list else ""
            return (
                f"{fname} is a function defined in {fp}.{param_str} "
                f"Based on the surrounding context, it is called when this functionality "
                f"is needed by the application."
            )

    if kind == "function_call":
        m = _re_explain.match(r"(\w[\w\.]*)\s*\(([^)]*)\)", s)
        if m:
            fname = m.group(1)
            args_raw = m.group(2).strip()
            args_display = args_raw[:80] if args_raw else ""

            fname_l = fname.lower().replace("_", "")
            if any(w in fname_l for w in ("loaddotenv", "dotenv", "loadenv")):
                arg_note = f" with argument \"{args_display}\"" if args_display else ""
                return (
                    f"{fname}() loads environment variables from a .env file "
                    f"into the process environment{arg_note}. "
                    f"After this call, values defined in the .env file become accessible via "
                    f"os.getenv() or os.environ. This is a standard pattern for keeping "
                    f"secrets and configuration out of source code."
                )
            if any(w in fname_l for w in ("connect", "init", "initialize", "setup", "start", "boot")):
                return (
                    f"{fname}() initializes or connects a service or component in {fp}. "
                    f"This call sets up a dependency that later code relies on. "
                    f"Removing it may cause None references or connection errors downstream."
                )
            if any(w in fname_l for w in ("register", "add", "append", "include", "mount")):
                return (
                    f"{fname}() registers or adds a component to a collection or framework in {fp}. "
                    f"Removing this call will cause the registered component to be absent at runtime."
                )
            if any(w in fname_l for w in ("log", "print", "debug", "warn", "error", "info")):
                return (
                    f"{fname}() emits a log or diagnostic message in {fp}. "
                    f"This is a non-critical observability call — removing it "
                    f"has no functional impact on the application."
                )
            return (
                f"{fname}() is called in {fp}. "
                f"Based on the surrounding context, this call is part of the application's "
                f"initialization or processing flow. The exact behavior depends on the "
                f"implementation of {fname}."
            )

    if kind == "assignment":
        m = _re_explain.match(r"(\w[\w\.]*)\s*=\s*(.+)", s)
        if m:
            lhs, rhs = m.group(1).strip(), m.group(2).strip()
            return (
                f"{lhs} is assigned the value of {rhs} in {fp}. "
                f"Based on the surrounding context, this value is used later in the same "
                f"scope or passed to other functions."
            )

    # Generic fallback
    ctx_preview = [l.strip() for l in context_lines if l.strip() and l.strip() != s][:3]
    ctx_str = "\n".join(ctx_preview)
    return (
        f"In {fp}, this line performs a {kind} operation."
        + (f" Surrounding context:\n{ctx_str}" if ctx_str else "")
    )


def _explain_impact(line: str, file_path: str, context_lines: list[str]) -> str:
    """
    Explain the runtime impact of deleting or changing a line.
    Generic — infers impact from line type and surrounding context.
    Plain text only — no markdown bold or section headers.
    """
    kind = _classify_line(line)
    s = line.strip()
    fp = file_path or "unknown file"

    if kind == "import":
        m = _re_explain.match(r"from\s+(\S+)\s+import\s+(.+)", s)
        if m:
            module, symbols = m.group(1), m.group(2).strip()
            symbols_clean = symbols.rstrip(",").strip()
            # Determine if used at module load time
            ctx_text = " ".join(context_lines).lower()
            startup_risk = any(sym.strip().lower() in ctx_text
                               for sym in symbols_clean.split(","))
            startup_note = (
                " If it is referenced at module load time — for example in a class definition "
                "or a top-level call — the file will fail to import immediately."
                if startup_risk else
                " If it is only used inside functions, the failure will surface at the point "
                "those functions are called, not at startup."
            )
            return (
                f"Removing this line means {symbols_clean} will no longer be available in {fp}. "
                f"Any code in this file that references {symbols_clean} will raise a NameError "
                f"at the point of first use.{startup_note} "
                f"It is safe to remove only if {symbols_clean} is not referenced anywhere else in this file."
            )
        # bare import
        m2 = _re_explain.match(r"import\s+(\S+)", s)
        if m2:
            module = m2.group(1)
            return (
                f"Removing this line means the {module} module will no longer be available in {fp}. "
                f"Any reference to {module} in this file will raise a NameError at runtime. "
                f"It is safe to remove only if {module} is not used anywhere else in this file."
            )

    if kind == "env_lookup":
        m = _re_explain.search(
            r"(\w+)\s*=\s*(?:os\.getenv|os\.environ\.get|process\.env(?:\[|\.))\s*\(?\s*['\"]([^'\"]+)['\"]"
            r"(?:\s*,\s*['\"]?([^'\")\n]+)['\"]?)?",
            s,
        )
        var_name = m.group(1) if m else "this variable"
        env_key = m.group(2) if m else "the environment variable"
        default = (m.group(3) or "").strip().strip("'\"") if (m and m.group(3)) else None

        ctx_text = " ".join(context_lines).lower()
        usage_hints: list[str] = []
        if any(w in ctx_text for w in ("credential", "cred", "service_account", "firebase", "auth", "certificate")):
            usage_hints.append("authentication or credentials initialization will fail")
        if any(w in ctx_text for w in ("database", "db_url", "postgres", "mongo", "redis", "connect")):
            usage_hints.append("database connection setup will fail")
        if any(w in ctx_text for w in ("client", "init", "initialize", "sdk", "admin")):
            usage_hints.append("SDK or client initialization will fail")
        if not usage_hints:
            usage_hints.append(f"any code that uses {var_name} will receive None or raise an error")

        impact_str = "; ".join(usage_hints)
        default_note = (
            f" Currently it falls back to \"{default}\" when the variable is absent."
            if default else
            f" Currently it returns None when the variable is absent."
        )

        return (
            f"Removing this line means {var_name} will no longer be assigned from the "
            f"{env_key} environment variable.{default_note} "
            f"As a result, {impact_str}. "
            f"The failure will surface at the point where {var_name} is first used after this line, "
            f"typically as a TypeError or ValueError if the value is passed to a function "
            f"that requires a non-None argument."
        )

    if kind == "function_def":
        m = _re_explain.search(r"def\s+(\w+)", s)
        fname = m.group(1) if m else "this function"
        ctx_text = " ".join(context_lines).lower()
        startup_note = (
            " If it is called during application startup or module import, "
            "the application may fail to start."
            if any(w in ctx_text for w in ("startup", "init", "app", "main", "start"))
            else ""
        )
        return (
            f"Removing the definition of {fname} from {fp} will cause a NameError or "
            f"AttributeError wherever {fname} is called.{startup_note}"
        )

    if kind == "route_def":
        return (
            f"Removing this line from {fp} removes a route or endpoint registration. "
            f"Requests to this endpoint will return a 404 Not Found, and any client "
            f"code or frontend that calls this route will stop working."
        )

    if kind == "assignment":
        m = _re_explain.match(r"(\w[\w\.]*)\s*=\s*(.+)", s)
        var_name = m.group(1) if m else "this variable"
        return (
            f"Removing this line means {var_name} will not be assigned in {fp}. "
            f"Any subsequent use of {var_name} in this scope will raise a NameError "
            f"or produce unexpected None behavior."
        )

    # Generic
    return (
        f"Removing this line from {fp} eliminates a {kind} operation. "
        f"The behavior controlled by this line will no longer execute. "
        f"Depending on how critical this operation is, the application may fail silently, "
        f"raise an exception, or produce incorrect output."
    )


def _extract_target_line_and_context(
    context_chunks: list[dict],
    question: str = "",
) -> tuple[str, str, list[str]]:
    """
    From the retrieved evidence, extract the single most relevant target line,
    its file path, and a list of surrounding context lines.

    Strategy: score every content line by how many question tokens it contains,
    pick the highest-scoring line as the target.  Falls back to the first
    non-trivial content line if no token match is found.
    """
    _STOPWORDS = {"what", "does", "this", "that", "repo", "file", "line", "code",
                  "the", "and", "for", "with", "from", "into", "how", "why",
                  "when", "where", "which", "will", "would", "should", "could",
                  "have", "been", "being", "about", "delete", "remove", "happen",
                  "found", "matching", "snippet"}
    q_tokens = [
        t.lower().strip("'\"`.,()")
        for t in question.split()
        if len(t) >= 3 and t.lower().strip("'\"`.(),") not in _STOPWORDS
    ]

    best_line = ""
    best_file = ""
    best_context: list[str] = []
    best_score = -1

    for chunk in context_chunks:
        snip = (chunk.get("snippet") or "").strip()
        fp = chunk.get("file_path") or ""
        if not snip:
            continue
        lines = snip.splitlines()
        # Strip header lines like "Found matching snippet at line N:"
        content_lines = [
            l for l in lines
            if not _re_explain.match(r"^Found matching snippet|^Snippet is inside symbol", l)
        ]
        if not content_lines:
            continue

        for i, line in enumerate(content_lines):
            stripped = line.strip()
            if not stripped or len(stripped) < 4:
                continue
            # Skip pure comment lines and docstrings
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            if stripped.startswith('"""') or stripped.startswith("'''"):
                continue

            score = sum(1 for t in q_tokens if t in stripped.lower())
            if score > best_score:
                best_score = score
                best_line = stripped
                best_file = fp
                best_context = [
                    l.strip() for l in content_lines
                    if l.strip() and l.strip() != stripped
                ][:6]

    # If no token match, fall back to first non-trivial content line
    if not best_line:
        for chunk in context_chunks:
            snip = (chunk.get("snippet") or "").strip()
            fp = chunk.get("file_path") or ""
            lines = snip.splitlines()
            content_lines = [
                l for l in lines
                if not _re_explain.match(r"^Found matching snippet|^Snippet is inside symbol", l)
            ]
            for line in content_lines:
                stripped = line.strip()
                if (stripped and len(stripped) > 5
                        and not stripped.startswith("#")
                        and not stripped.startswith("//")
                        and not stripped.startswith('"""')
                        and not stripped.startswith("'''")):
                    best_line = stripped
                    best_file = fp
                    best_context = [
                        l.strip() for l in content_lines
                        if l.strip() and l.strip() != stripped
                    ][:6]
                    break
            if best_line:
                break

    return best_line, best_file, best_context


# ---------------------------------------------------------------------------
# Symbol Extraction  (A) — structured, generic, pattern-based only
# ---------------------------------------------------------------------------

def _extract_query_symbols(question: str) -> dict:
    """
    Lightweight, deterministic symbol extraction from a user query.

    Returns a structured dict with:
        raw_query            – original question unchanged
        normalized_query     – lowercased, stripped
        extracted_symbols    – list of distinct code symbols found
        likely_primary_symbol – single best symbol to anchor retrieval
        query_type_hint      – one of: repo_summary / code_explain /
                               impact / symbol_lookup / usage_lookup
        possible_files       – filenames / extensions detected
        possible_imports     – full import phrases detected
        possible_env_vars    – ALL_CAPS or os.getenv("X") keys
        route_candidates     – /api/... style paths
        bare_identifiers     – snake_case / camelCase / PascalCase names
    """
    raw = question
    q = question.lower().strip()

    symbols: list[str] = []
    possible_files: list[str] = []
    possible_imports: list[str] = []
    possible_env_vars: list[str] = []
    route_candidates: list[str] = []

    # 1. Full import statements  e.g. "from uuid import uuid4"
    for m in re.finditer(
        r"from\s+([\w\.]+)\s+import\s+([\w\s,\*]+?)(?=\s+(?:do|does|did|will|would|should|could|is|are|was|were|has|have|had|be|been|being|in|on|at|to|for|of|and|or|not|if|then|else|what|how|why|where|when|which|that|this|it|he|she|they|we|you|I)\b|$)",
        question,
        re.IGNORECASE,
    ):
        module = m.group(1).strip()
        names = [n.strip() for n in m.group(2).split(",") if n.strip()]
        full_import = f"from {module} import {', '.join(names)}"
        symbols.append(full_import)
        possible_imports.append(full_import)
        symbols.extend(names)
        if module:
            symbols.append(module)

    # 2. Bare import  e.g. "import os"
    for m in re.finditer(r"\bimport\s+([\w\.]+)", question, re.IGNORECASE):
        sym = m.group(1).strip()
        full_import = f"import {sym}"
        symbols.append(full_import)
        possible_imports.append(full_import)
        symbols.append(sym)

    # 3. Function / method calls  e.g. load_dotenv(".env")  os.getenv(...)
    for m in re.finditer(r"([\w][\w\.]*)\s*\(", question):
        sym = m.group(1).strip()
        if len(sym) >= 3 and sym.lower() not in {
            "def", "class", "if", "for", "while", "with", "not", "and", "or",
            "return", "print", "len", "str", "int", "list", "dict", "set",
        }:
            symbols.append(sym)
            if "." in sym:
                symbols.append(sym.rsplit(".", 1)[-1])

    # 4. Assignment LHS  e.g. "cred_path = os.getenv(...)"
    for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*=", question):
        sym = m.group(1).strip()
        if len(sym) >= 3:
            symbols.append(sym)

    # 5. CamelCase / PascalCase identifiers  e.g. BaseModel, FirebaseAdmin
    for m in re.finditer(r"\b([A-Z][a-zA-Z0-9]{2,})\b", question):
        symbols.append(m.group(1))

    # 6. snake_case identifiers
    for m in re.finditer(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+){1,})\b", question):
        sym = m.group(1)
        if len(sym) >= 4:
            symbols.append(sym)

    # 7. Quoted file names  e.g. ".env"  "firebase-service-account.json"
    for m in re.finditer(r'["\']([^"\']{2,60})["\']', question):
        candidate = m.group(1).strip()
        if "." in candidate or "/" in candidate:
            symbols.append(candidate)
            possible_files.append(candidate)

    # 8. Unquoted filenames with extensions  e.g. app.py  config.ts
    for m in re.finditer(r"\b([\w\-]+\.(py|js|ts|tsx|jsx|go|rs|java|rb|php|cs|cpp|c|h|json|yaml|yml|toml|env|md|txt|html|css|scss))\b", question, re.IGNORECASE):
        possible_files.append(m.group(1))
        symbols.append(m.group(1))

    # 9. ALL_CAPS env var names  e.g. DATABASE_URL, API_KEY
    for m in re.finditer(r"\b([A-Z][A-Z0-9_]{2,})\b", question):
        possible_env_vars.append(m.group(1))
        symbols.append(m.group(1))

    # 10. os.getenv("KEY") / process.env.KEY patterns
    for m in re.finditer(r'(?:os\.getenv|os\.environ\.get|process\.env(?:\[|\.))\s*\(?\s*["\']([^"\']+)["\']', question, re.IGNORECASE):
        possible_env_vars.append(m.group(1))
        symbols.append(m.group(1))

    # 11. Route-like paths  e.g. /api/users  /auth/login
    for m in re.finditer(r"(/(?:api|auth|v\d+|admin|user|login|logout|register|health|webhook)[/\w\-]*)", question, re.IGNORECASE):
        route_candidates.append(m.group(1))
        symbols.append(m.group(1))

    # Deduplicate preserving order, drop trivial tokens
    _TRIVIAL = {
        "the", "this", "that", "what", "does", "will", "happen", "delete",
        "remove", "import", "from", "use", "used", "where", "how", "why",
        "repo", "file", "line", "code", "function", "class", "method",
    }
    seen_syms: set[str] = set()
    clean_symbols: list[str] = []
    for s in symbols:
        key = s.lower().strip()
        if key and key not in seen_syms and key not in _TRIVIAL and len(key) >= 2:
            seen_syms.add(key)
            clean_symbols.append(s)

    # Deduplicate structured lists
    possible_files = list(dict.fromkeys(possible_files))
    possible_imports = list(dict.fromkeys(possible_imports))
    possible_env_vars = list(dict.fromkeys(possible_env_vars))
    route_candidates = list(dict.fromkeys(route_candidates))

    # Pick the single best primary symbol
    primary = ""
    for s in clean_symbols:
        if s.startswith("from ") or s.startswith("import "):
            primary = s
            break
    if not primary:
        for s in clean_symbols:
            if re.match(r"^[A-Z][a-zA-Z0-9]{2,}$", s):
                primary = s
                break
    if not primary:
        for s in clean_symbols:
            if "_" in s and len(s) >= 4:
                primary = s
                break
    if not primary and clean_symbols:
        primary = clean_symbols[0]

    # Determine query_type_hint
    _REPO_SUMMARY_WORDS = {
        "repo", "project", "codebase", "overview", "summarize", "architecture",
        "structure", "purpose", "what is this", "what does this",
    }
    _IMPACT_WORDS = {"delete", "remove", "happen", "break", "impact", "change", "replace"}
    _USAGE_WORDS = {"where is", "who calls", "used", "usage", "references", "callers"}

    if any(w in q for w in _REPO_SUMMARY_WORDS) and not clean_symbols:
        type_hint = "repo_summary"
    elif any(w in q for w in _IMPACT_WORDS):
        type_hint = "impact"
    elif any(w in q for w in _USAGE_WORDS):
        type_hint = "usage_lookup"
    elif clean_symbols and any(
        w in q for w in ("where is", "find", "locate", "defined", "definition")
    ):
        type_hint = "symbol_lookup"
    elif clean_symbols:
        type_hint = "code_explain"
    else:
        type_hint = "repo_summary"

    return {
        "raw_query": raw,
        "normalized_query": q,
        "extracted_symbols": clean_symbols,
        "likely_primary_symbol": primary,
        "query_type_hint": type_hint,
        # Structured fields for advanced retrieval
        "possible_files": possible_files,
        "possible_imports": possible_imports,
        "possible_env_vars": possible_env_vars,
        "route_candidates": route_candidates,
        "bare_identifiers": [
            s for s in clean_symbols
            if not (s.startswith("from ") or s.startswith("import ") or "/" in s)
            and len(s) >= 3
        ],
    }


# ---------------------------------------------------------------------------
# Query Rewriting  (B) — structural variants per intent
# ---------------------------------------------------------------------------

def _build_retrieval_queries(question: str, sym_info: dict, intent: str) -> list[str]:
    """
    Build 3–6 retrieval probe strings from the original question + extracted symbols.

    Strategy per intent:
    - CODE_EXPLAIN / SEMANTIC_QA: original + symbol-only + "definition of X" + "usage of X"
    - IMPACT / DELETE: original + "references to X" + "imports of X" + "where is X used"
    - REPO_SUMMARY: original + "README" + "main entrypoint" + "requirements"
    - SYMBOL_LOOKUP: original + "def X" + "class X" + "X =" + "X usage"
    - FILE_LOOKUP: original + exact filename + "import from X"

    Rules:
    - Always include the original question as the first probe.
    - Keep probes short and high-signal; never duplicate the original.
    - Cap at 6 probes total.
    """
    probes: list[str] = [question]
    seen: set[str] = {question.lower().strip()}

    def _add(probe: str) -> None:
        key = probe.lower().strip()
        if key and key not in seen and len(probe) >= 2:
            seen.add(key)
            probes.append(probe)

    primary = sym_info.get("likely_primary_symbol", "")
    symbols = sym_info.get("extracted_symbols", [])
    bare = sym_info.get("bare_identifiers", [])
    possible_files = sym_info.get("possible_files", [])
    possible_imports = sym_info.get("possible_imports", [])
    route_candidates = sym_info.get("route_candidates", [])
    type_hint = sym_info.get("query_type_hint", "")

    # Extract the leaf name from a full import statement
    def _leaf(sym: str) -> str:
        if sym.startswith("from ") or sym.startswith("import "):
            m = re.search(r"import\s+([\w]+)", sym, re.IGNORECASE)
            return m.group(1) if m else sym
        return sym

    primary_leaf = _leaf(primary) if primary else ""

    # ── Intent-specific probe generation ────────────────────────────────────

    if intent in (QueryIntent.REPO_SUMMARY, QueryIntent.ARCHITECTURE_EXPLANATION) or type_hint == "repo_summary":
        _add("README")
        _add("main entrypoint")
        _add("requirements dependencies")
        _add("project structure overview")

    elif intent in (QueryIntent.FLOW_QUESTION,):
        # Flow questions: pull route/service/entrypoint files + flow-relevant symbols
        _add("route handler")
        _add("service layer")
        _add("entrypoint startup")
        if primary_leaf:
            _add(primary_leaf)
            _add(f"def {primary_leaf}")
        for sym in bare[:2]:
            if sym != primary_leaf:
                _add(sym)

    elif intent in (QueryIntent.SYMBOL_LOOKUP,) or type_hint in ("symbol_lookup", "usage_lookup"):
        if primary_leaf:
            _add(primary_leaf)
            _add(f"def {primary_leaf}")
            _add(f"class {primary_leaf}")
            _add(f"{primary_leaf} =")
            _add(f"{primary_leaf} usage")
        for sym in bare[:2]:
            if sym != primary_leaf:
                _add(sym)

    elif intent in (QueryIntent.LINE_IMPACT, QueryIntent.CODE_SNIPPET_IMPACT,
                    QueryIntent.DEPENDENCY_IMPACT, QueryIntent.LINE_CHANGE_IMPACT,
                    QueryIntent.ROUTE_FEATURE_IMPACT) or type_hint == "impact":
        if primary_leaf:
            _add(primary_leaf)
            _add(f"references to {primary_leaf}")
            _add(f"import {primary_leaf}")
            _add(f"where is {primary_leaf} used")
        elif primary and (primary.startswith("from ") or primary.startswith("import ")):
            _add(primary)
            _add(primary_leaf)
        for sym in bare[:2]:
            if sym != primary_leaf:
                _add(sym)
        for route in route_candidates[:1]:
            _add(route)

    else:
        # CODE_EXPLAIN / SEMANTIC_QA — default
        if primary:
            if primary.startswith("from ") or primary.startswith("import "):
                _add(primary)
                if primary_leaf:
                    _add(primary_leaf)
                    _add(f"definition of {primary_leaf}")
            else:
                _add(primary)
                _add(f"definition of {primary}")
                _add(f"{primary} usage")
        for sym in bare[:2]:
            if sym != primary and sym != primary_leaf:
                _add(sym)

    # ── File-specific probes ─────────────────────────────────────────────────
    for f in possible_files[:1]:
        _add(f)

    # ── Import-specific probes ───────────────────────────────────────────────
    for imp in possible_imports[:1]:
        if imp not in probes:
            _add(imp)

    # Cap at 6 probes
    return probes[:6]


# ---------------------------------------------------------------------------
# Intent-aware file boosting  (C)
# ---------------------------------------------------------------------------

_LOW_VALUE_PATH_FRAGMENTS = frozenset({
    "test_", "_test.", "spec.", ".spec.", "mock", "__mock",
    "debug", "scratch", "tmp", "temp", "experimental",
    "generated", "dist/", "/dist", "build/", "/build",
    ".lock", ".log", ".csv", "node_modules", "__pycache__",
    ".pyc", ".min.js", ".map", ".next/",
})

_SUMMARY_BOOST_PATHS = frozenset({
    "readme", "main.py", "app.py", "server.py", "index.js", "index.ts",
    "main.ts", "main.js", "requirements.txt", "package.json",
    "pyproject.toml", "dockerfile", "docker-compose", "compose.yml",
    "compose.yaml", ".env", "settings.py", "config.py",
})

_SUMMARY_BOOST_TYPES = frozenset({
    "config_manifest", "repo_intelligence", "documentation",
})


def _looks_low_value_file(file_path: str) -> bool:
    """Return True if the file path looks like a test/debug/generated artifact."""
    pl = file_path.lower()
    return any(frag in pl for frag in _LOW_VALUE_PATH_FRAGMENTS)


def _count_symbol_occurrences(snippet: str, symbol: str) -> int:
    """Count how many times a symbol appears in a snippet (case-sensitive word boundary)."""
    if not symbol or not snippet:
        return 0
    try:
        return len(re.findall(re.escape(symbol), snippet))
    except re.error:
        return snippet.count(symbol)


def _apply_intent_boosts(
    evidence: list[dict],
    intent: str,
    mode: str,
    sym_info: dict,
) -> list[dict]:
    """
    Apply a deterministic boost/penalty layer on top of existing scores.

    Boosts are kept modest (max ±0.35) so semantic ranking still dominates.
    Modifies items in-place and returns the list sorted by updated score.
    """
    primary = sym_info.get("likely_primary_symbol", "")
    symbols = sym_info.get("extracted_symbols", [])
    # Bare leaf names only (no full import lines) for occurrence counting
    bare_symbols = [
        s for s in symbols
        if not (s.startswith("from ") or s.startswith("import "))
        and len(s) >= 3
    ]

    is_summary_intent = intent in (
        QueryIntent.REPO_SUMMARY, QueryIntent.ARCHITECTURE_EXPLANATION
    )
    is_code_intent = mode in (QueryMode.CODE, QueryMode.IMPACT) or intent in (
        QueryIntent.SEMANTIC_QA, QueryIntent.SYMBOL_LOOKUP,
        QueryIntent.LINE_IMPACT, QueryIntent.CODE_SNIPPET_IMPACT,
        QueryIntent.DEPENDENCY_IMPACT, QueryIntent.LINE_CHANGE_IMPACT,
    )

    for item in evidence:
        fp = (item.get("file_path") or "").lower()
        mt = item.get("match_type", "")
        snippet = item.get("snippet") or item.get("chunk_text") or ""
        adj = 0.0

        # ── Universal penalty: low-value files ──────────────────────────────
        if _looks_low_value_file(fp):
            adj -= 0.20

        # ── Repo-summary intent boosts ───────────────────────────────────────
        if is_summary_intent:
            if any(sig in fp for sig in _SUMMARY_BOOST_PATHS):
                adj += 0.30
            if mt in _SUMMARY_BOOST_TYPES:
                adj += 0.25
            if "router" in fp or "routes" in fp:
                adj += 0.15

        # ── Code / symbol / impact intent boosts ────────────────────────────
        if is_code_intent and bare_symbols:
            # Boost files that contain the primary symbol in a definition context
            for sym in bare_symbols[:3]:
                occ = _count_symbol_occurrences(snippet, sym)
                if occ >= 3:
                    adj += 0.25
                elif occ == 2:
                    adj += 0.15
                elif occ == 1:
                    adj += 0.08

            # Extra boost if the symbol appears in a def/class/import line
            for sym in bare_symbols[:3]:
                if re.search(
                    rf"(?:def|class|import|from|const|let|var|function)\s+.*{re.escape(sym)}",
                    snippet,
                    re.IGNORECASE,
                ):
                    adj += 0.15
                    break

        # ── Penalize test/debug files for non-test intents ──────────────────
        if is_code_intent:
            if any(frag in fp for frag in ("test_", "_test.", "spec.", ".spec.")):
                adj -= 0.15
            if any(frag in fp for frag in ("debug", "scratch", "tmp", "experimental")):
                adj -= 0.20

        item["score"] = min(1.0, max(0.0, item.get("score", 0.5) + adj))

    return sorted(evidence, key=lambda x: x.get("score", 0.0), reverse=True)


# ---------------------------------------------------------------------------
# Advanced Reranking  (D) — structural line-type signals
# ---------------------------------------------------------------------------

# Structural line patterns for intent-aware boosting
_IMPORT_LINE_PAT = re.compile(r"^\s*(from\s+\S+\s+import|import\s+)", re.IGNORECASE)
_DEF_LINE_PAT = re.compile(r"^\s*(async\s+)?(def|function|class)\s+\w+", re.IGNORECASE)
_ASSIGN_LINE_PAT = re.compile(r"^\s*[\w\.]+\s*=\s*", re.IGNORECASE)
_ENV_LINE_PAT = re.compile(r"(os\.getenv|os\.environ|process\.env|config\.get|settings\.)", re.IGNORECASE)
_ROUTE_LINE_PAT = re.compile(r"@(app|router|blueprint)\.(get|post|put|delete|patch|options|head)\(|app\.(use|get|post|put|delete)\(", re.IGNORECASE)
_CALL_LINE_PAT = re.compile(r"\w[\w\.]*\s*\(", re.IGNORECASE)
_EXPORT_LINE_PAT = re.compile(r"^\s*(export\s+(default\s+)?|module\.exports\s*=)", re.IGNORECASE)

# File categories for intent-aware scoring
_SOURCE_EXTS_ADV = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".swift", ".kt",
})
_NOISE_EXTS_ADV = frozenset({
    ".lock", ".log", ".csv", ".min.js", ".map", ".pyc",
})
_NOISE_PATH_FRAGS_ADV = frozenset({
    "node_modules", "__pycache__", ".next/", "dist/", "build/",
    "vendor/", "coverage/", ".min.", "generated",
})


def _structural_line_score(snippet: str, intent: str, bare_symbols: list[str]) -> float:
    """
    Score a snippet based on structural line-type signals relevant to the intent.
    Returns a boost in [0.0, 0.40].
    """
    if not snippet:
        return 0.0

    lines = snippet.splitlines()
    boost = 0.0
    matched_structural = False

    for line in lines:
        s = line.strip()
        if not s or len(s) < 4:
            continue

        # Symbol presence in this line
        sym_in_line = any(sym in s for sym in bare_symbols) if bare_symbols else False

        # Intent-specific structural signals
        if intent in ("line_impact", "code_snippet_impact", "line_change_impact",
                      "dependency_impact"):
            # For impact questions: boost import lines, def lines, assignment lines
            if _IMPORT_LINE_PAT.match(s) and sym_in_line:
                boost += 0.20
                matched_structural = True
            elif _DEF_LINE_PAT.match(s) and sym_in_line:
                boost += 0.15
                matched_structural = True
            elif _ASSIGN_LINE_PAT.match(s) and sym_in_line:
                boost += 0.12
                matched_structural = True
            elif _CALL_LINE_PAT.search(s) and sym_in_line:
                boost += 0.08

        elif intent in ("semantic_qa",) or intent == "":
            # For "what does X do": boost def/class lines and import lines
            if _DEF_LINE_PAT.match(s) and sym_in_line:
                boost += 0.18
                matched_structural = True
            elif _IMPORT_LINE_PAT.match(s) and sym_in_line:
                boost += 0.15
                matched_structural = True
            elif _ENV_LINE_PAT.search(s) and sym_in_line:
                boost += 0.12
                matched_structural = True

        elif intent in ("symbol_lookup",):
            # For "where is X used": boost call sites and assignments
            if _CALL_LINE_PAT.search(s) and sym_in_line:
                boost += 0.15
                matched_structural = True
            elif _ASSIGN_LINE_PAT.match(s) and sym_in_line:
                boost += 0.12
                matched_structural = True
            elif _DEF_LINE_PAT.match(s) and sym_in_line:
                boost += 0.10

        elif intent in ("route_feature_impact",):
            # For route questions: boost route decorator lines
            if _ROUTE_LINE_PAT.search(s):
                boost += 0.20
                matched_structural = True
            elif _DEF_LINE_PAT.match(s) and sym_in_line:
                boost += 0.10

    # Cap structural boost
    return min(0.40, boost)


def _rerank_evidence_advanced(
    evidence: list[dict],
    question: str,
    intent: str,
    mode: str,
    sym_info: dict,
) -> list[dict]:
    """
    Advanced deterministic reranker combining:
    1. Existing semantic score (preserved as base)
    2. Exact symbol match score (symbol in snippet / file path)
    3. Structural line-type relevance (import/def/assign/call/route per intent)
    4. File category relevance (source boost, noise penalty)
    5. Query-origin boost (exact match hits preferred)
    6. Line density / signal quality (penalize blank/comment-heavy chunks)
    7. Diversity control (cap contribution from same file)

    All signals are generic — no repo-specific strings.
    """
    if not evidence:
        return []

    bare_symbols = sym_info.get("bare_identifiers", [])
    primary = sym_info.get("likely_primary_symbol", "")
    primary_leaf = primary
    if primary and (primary.startswith("from ") or primary.startswith("import ")):
        m = re.search(r"import\s+([\w]+)", primary, re.IGNORECASE)
        primary_leaf = m.group(1) if m else primary

    is_summary = intent in (QueryIntent.REPO_SUMMARY, QueryIntent.ARCHITECTURE_EXPLANATION)
    is_impact = intent in (
        QueryIntent.LINE_IMPACT, QueryIntent.CODE_SNIPPET_IMPACT,
        QueryIntent.DEPENDENCY_IMPACT, QueryIntent.LINE_CHANGE_IMPACT,
        QueryIntent.ROUTE_FEATURE_IMPACT, QueryIntent.CONFIG_IMPACT,
    )
    is_code = mode in (QueryMode.CODE, QueryMode.IMPACT) or intent in (
        QueryIntent.SEMANTIC_QA, QueryIntent.SYMBOL_LOOKUP,
    )

    # Track per-file contribution for diversity control
    file_contribution: dict[str, int] = {}

    for item in evidence:
        fp = (item.get("file_path") or "").lower()
        snippet = (item.get("snippet") or item.get("chunk_text") or "")
        mt = item.get("match_type", "")
        base_score = item.get("score", 0.5)
        adj = 0.0

        # ── 1. File category signals ─────────────────────────────────────────
        ext = "." + fp.rsplit(".", 1)[-1] if "." in fp else ""
        is_source = ext in _SOURCE_EXTS_ADV
        is_noise_ext = ext in _NOISE_EXTS_ADV
        is_noise_path = any(frag in fp for frag in _NOISE_PATH_FRAGS_ADV)
        is_test = any(frag in fp for frag in ("test_", "_test.", "spec.", ".spec.", "/tests/", "/test/"))

        if is_noise_ext or is_noise_path:
            adj -= 0.25
        elif is_source and not is_summary:
            adj += 0.15
        if is_test and not is_summary:
            adj -= 0.12

        # ── 2. Summary intent: boost manifest/readme/entrypoint ──────────────
        if is_summary:
            if mt in ("repo_intelligence", "repo_metadata", "structure_census"):
                adj += 0.35
            elif mt in ("readme", "documentation"):
                adj += 0.25
            elif mt in ("manifest", "config_manifest", "entrypoint"):
                adj += 0.20
            elif mt in ("route_file",):
                adj += 0.10
            # Penalize raw code chunks for summary questions
            elif is_source and mt not in ("repo_intelligence", "entrypoint"):
                adj -= 0.05

        # ── 3. Exact symbol match in snippet / file path ─────────────────────
        if bare_symbols and not is_summary:
            sym_score = 0.0
            for sym in bare_symbols[:4]:
                if len(sym) < 3:
                    continue
                # Symbol in file path
                if sym.lower() in fp:
                    sym_score += 0.08
                # Symbol occurrences in snippet
                try:
                    occ = len(re.findall(re.escape(sym), snippet))
                except re.error:
                    occ = snippet.count(sym)
                if occ >= 3:
                    sym_score += 0.20
                elif occ == 2:
                    sym_score += 0.12
                elif occ == 1:
                    sym_score += 0.06
            adj += min(0.35, sym_score)

        # ── 4. Structural line-type relevance ────────────────────────────────
        if not is_summary and bare_symbols:
            struct_boost = _structural_line_score(snippet, intent, bare_symbols)
            adj += struct_boost

        # ── 5. Query-origin boost (exact/token matches preferred) ────────────
        if mt in ("exact", "token_match", "exact_match", "snippet_match", "impact_target"):
            adj += 0.12
        elif mt in ("semantic",) and is_code:
            # Slight penalty for pure semantic hits on code questions
            adj -= 0.05

        # ── 6. Line density / signal quality ────────────────────────────────
        if snippet:
            lines = snippet.splitlines()
            total = len(lines)
            if total > 0:
                meaningful = sum(
                    1 for l in lines
                    if l.strip() and not l.strip().startswith("#")
                    and not l.strip().startswith("//") and len(l.strip()) > 3
                )
                density = meaningful / total
                if density < 0.3:
                    adj -= 0.10  # mostly blank/comment
                elif density > 0.7:
                    adj += 0.05  # dense, high-signal

        # ── 7. Diversity control: penalize 3rd+ chunk from same file ─────────
        file_key = fp or "unknown"
        file_contribution[file_key] = file_contribution.get(file_key, 0) + 1
        if file_contribution[file_key] >= 3:
            adj -= 0.15
        elif file_contribution[file_key] == 2:
            adj -= 0.05

        item["score"] = min(1.0, max(0.0, base_score + adj))

    return sorted(evidence, key=lambda x: x.get("score", 0.0), reverse=True)


# ---------------------------------------------------------------------------
# Evidence Compression  (E) — focused, high-signal windows for LLM
# ---------------------------------------------------------------------------

def _compress_evidence_for_answer(
    question: str,
    intent: str,
    sym_info: dict,
    candidates: list[dict],
    max_blocks: int = 5,
    max_chars_per_block: int = 400,
    max_total_chars: int = 2000,
) -> list[dict]:
    """
    Compress retrieved evidence into focused, high-signal blocks before LLM synthesis.

    Per-block compression:
    - Strip blank lines and comment-only lines.
    - Extract the smallest meaningful window (±3-5 lines) around the best matching line.
    - Keep symbol-bearing lines (imports, defs, assignments, calls, routes).
    - Merge overlapping windows from the same file.
    - Enforce per-block and global char budgets.

    Returns a new list of compressed evidence dicts (same schema, smaller snippets).
    """
    if not candidates:
        return []

    bare_symbols = sym_info.get("bare_identifiers", [])
    primary_leaf = ""
    primary = sym_info.get("likely_primary_symbol", "")
    if primary:
        m = re.search(r"import\s+([\w]+)", primary, re.IGNORECASE)
        primary_leaf = m.group(1) if m else (primary if not primary.startswith(("from ", "import ")) else "")

    all_symbols = list(dict.fromkeys(
        ([primary_leaf] if primary_leaf else []) + bare_symbols
    ))

    _SYMBOL_INDICATORS = (
        "import ", "from ", "def ", "class ", "async def ",
        "function ", "const ", "let ", "var ", "export ",
        "return ", "raise ", "@", "->", "=>", "route",
    )

    def _score_line(line: str) -> float:
        """Score a single line for relevance."""
        s = line.strip()
        if not s or len(s) < 4:
            return 0.0
        score = 0.0
        # Symbol presence
        for sym in all_symbols[:4]:
            if sym and sym in s:
                score += 0.5
        # Structural indicator
        if any(tok in s for tok in _SYMBOL_INDICATORS):
            score += 0.3
        # Not a comment
        if not s.startswith("#") and not s.startswith("//") and not s.startswith("*"):
            score += 0.1
        return score

    def _compress_snippet(raw_snippet: str, window_radius: int = 4) -> str:
        """Extract the best window from a raw snippet."""
        if not raw_snippet:
            return ""

        lines = raw_snippet.splitlines()

        # Strip retrieval-injected header lines
        import re as _re_c
        lines = [
            l for l in lines
            if not _re_c.match(
                r"^(Found matching snippet|Snippet is inside symbol|FILE:|TARGET LINE|"
                r"ENCLOSING|Context before|Context after|---|\[FILE\]|\[REPO\]|"
                r"REPO INTELLIGENCE|REPOSITORY METADATA|FILE STRUCTURE CENSUS|"
                r"PROJECT MANIFEST|ENTRYPOINT CODE|ROUTE/API FILE|DATA MODEL|"
                r"DATA SAMPLE|README CONTENT|DEPENDENCY MANIFEST|PACKAGE USAGE|"
                r"FEATURE MATCH)",
                l.strip(),
                _re_c.IGNORECASE,
            )
        ]

        # Filter noise lines
        clean_lines = [
            (i, l) for i, l in enumerate(lines)
            if l.strip()
            and not l.strip().startswith("#")
            and not l.strip().startswith("//")
            and not l.strip().startswith("/*")
            and not l.strip().startswith("*")
            and len(l.strip()) > 3
        ]

        if not clean_lines:
            return ""

        # If short enough, return as-is
        if len(clean_lines) <= window_radius * 2 + 1:
            return "\n".join(l for _, l in clean_lines)

        # Find the best center line (highest relevance score)
        scored = [(i, l, _score_line(l)) for i, l in clean_lines]
        best_idx, best_line, best_score = max(scored, key=lambda x: x[2])

        # Extract window around best line
        window_start = max(0, best_idx - window_radius)
        window_end = min(len(lines), best_idx + window_radius + 1)
        window_lines = [
            l for l in lines[window_start:window_end]
            if l.strip() and len(l.strip()) > 2
        ]

        return "\n".join(window_lines)

    # Process candidates
    compressed: list[dict] = []
    total_chars = 0
    seen_files: dict[str, list[str]] = {}  # file_path -> list of compressed snippets

    for item in candidates:
        if len(compressed) >= max_blocks:
            break
        if total_chars >= max_total_chars:
            break

        fp = item.get("file_path") or "unknown"
        mt = item.get("match_type", "")

        # For summary/intelligence chunks, use a lighter compression
        is_meta = mt in ("repo_intelligence", "repo_metadata", "structure_census",
                         "readme", "documentation", "manifest", "config_manifest")
        if is_meta:
            raw = (item.get("snippet") or "").strip()
            # Just strip blank lines and cap
            meta_lines = [l for l in raw.splitlines() if l.strip() and len(l.strip()) > 3][:20]
            compressed_text = "\n".join(meta_lines)
        else:
            raw = (item.get("snippet") or item.get("chunk_text") or "").strip()
            compressed_text = _compress_snippet(raw, window_radius=4)

        if not compressed_text:
            continue

        # Cap per block
        if len(compressed_text) > max_chars_per_block:
            compressed_text = compressed_text[:max_chars_per_block] + "\n..."

        # Merge with existing content from same file (avoid near-duplicate blocks)
        if fp in seen_files:
            # Check if this compressed text is substantially different
            existing = " ".join(seen_files[fp])
            overlap = sum(1 for line in compressed_text.splitlines()
                         if line.strip() and line.strip() in existing)
            total_lines = len([l for l in compressed_text.splitlines() if l.strip()])
            if total_lines > 0 and overlap / total_lines > 0.7:
                continue  # Too similar to existing block from same file — skip

        seen_files.setdefault(fp, []).append(compressed_text)

        new_item = dict(item)
        new_item["snippet"] = compressed_text
        compressed.append(new_item)
        total_chars += len(compressed_text)

    return compressed


# ---------------------------------------------------------------------------
# Answer Shaping  (F) — post-process LLM and fallback answers
# ---------------------------------------------------------------------------

def _shape_final_answer(answer: str, intent: str) -> str:
    """
    Normalize the final answer:
    - Strip markdown bold (**text**) and raw section labels.
    - Remove robotic meta-labels.
    - Collapse excessive blank lines.
    - Preserve code identifiers in backticks if already present.
    - Keep answer proportional to intent.
    """
    import re as _re_shape
    if not answer:
        return ""

    text = answer

    # Strip markdown bold
    text = text.replace("**", "")

    # Strip known robotic section labels (case-insensitive, whole line)
    _LABEL_PATTERNS = [
        r"^direct answer\s*:?\s*$",
        r"^evidence\s*:?\s*$",
        r"^detailed explanation\s*:?\s*$",
        r"^likely impact\s*/?\s*risks?\s*:?\s*$",
        r"^confidence\s*:?\s*(high|medium|low)?\s*$",
        r"^summary\s*:?\s*$",
        r"^analysis\s*:?\s*$",
        r"^immediate effect\s*:?\s*$",
        r"^startup impact\s*:?\s*$",
        r"^runtime impact\s*:?\s*$",
        r"^impact analysis\s*$",
        r"^matched line\s*:?\s*$",
        r"^what this line does\s*:?\s*$",
        r"^likely impact if deleted\s*:?\s*$",
        r"^severity\s*:?\s*$",
        r"^={3,}\s*$",
        r"^\[(?:HIGH|MEDIUM|LOW|INFO|WARN|ERROR)\]\s*$",
    ]
    lines = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        is_label = any(
            _re_shape.match(pat, stripped, _re_shape.IGNORECASE)
            for pat in _LABEL_PATTERNS
        )
        if not is_label:
            lines.append(raw_line)

    text = "\n".join(lines)

    # Collapse 3+ blank lines to 2
    text = _re_shape.sub(r"\n{3,}", "\n\n", text)

    # Strip leading/trailing whitespace
    text = text.strip()

    return text


# ---------------------------------------------------------------------------
# Graph-Aware Retrieval  (G) — file-relationship expansion using DB edges
# ---------------------------------------------------------------------------
# Uses the existing DependencyEdge table (import/from_import/call/export edges)
# and Symbol table to expand retrieval beyond isolated chunk search.
#
# Design principles:
# - Lightweight: builds a per-query in-memory adjacency map from DB, not a
#   full graph object. Bounded queries, no O(N²) scans.
# - Generic: all patterns are language-agnostic. No repo-specific logic.
# - Additive: if graph data is absent, falls back to base retrieval silently.
# - Cached per (repo_id, question) within a single request — no cross-request
#   state (stateless service).
# ---------------------------------------------------------------------------

# Edge type weights for graph-aware reranking
_EDGE_WEIGHT: dict[str, float] = {
    "import":       0.90,   # direct import dependency — strong signal
    "from_import":  0.90,   # from X import Y — strong signal
    "call":         0.75,   # function/method call — medium-strong
    "export":       0.70,   # export declaration
    "require":      0.85,   # CommonJS require — strong
    "reference":    0.60,   # generic reference
    "config":       0.55,   # shared config/env key reference
}

# Intent → preferred edge types for expansion
_INTENT_PREFERRED_EDGES: dict[str, tuple[str, ...]] = {
    QueryIntent.LINE_IMPACT:          ("import", "from_import", "call", "require"),
    QueryIntent.CODE_SNIPPET_IMPACT:  ("import", "from_import", "call", "require"),
    QueryIntent.DEPENDENCY_IMPACT:    ("import", "from_import", "require"),
    QueryIntent.LINE_CHANGE_IMPACT:   ("call", "import", "from_import"),
    QueryIntent.ROUTE_FEATURE_IMPACT: ("call", "import", "from_import"),
    QueryIntent.SYMBOL_LOOKUP:        ("call", "import", "from_import", "export"),
    QueryIntent.SEMANTIC_QA:          ("import", "from_import", "call"),
    QueryIntent.FLOW_QUESTION:        ("import", "from_import", "call"),  # trace execution chain
    QueryIntent.REPO_SUMMARY:         (),   # no expansion for summary — use context pack
    QueryIntent.ARCHITECTURE_EXPLANATION: ("import", "from_import"),  # light expansion for arch
}


def _build_file_adjacency(
    db: Session,
    repository_id: str,
    seed_file_ids: list[str],
    bare_symbols: list[str],
    intent: str,
    max_neighbors: int = 6,
) -> dict[str, list[dict]]:
    """
    Build a lightweight adjacency map for the seed files.

    Returns:
        {file_id: [{"neighbor_file_id": str, "edge_type": str, "target_ref": str,
                    "direction": "outgoing"|"incoming", "weight": float}]}

    Strategy:
    - Fetch outgoing edges (files this seed imports/calls)
    - Fetch incoming edges (files that import/call this seed)
    - Filter by preferred edge types for the current intent
    - Bound to max_neighbors per seed to avoid explosion
    """
    if not seed_file_ids:
        return {}

    preferred = _INTENT_PREFERRED_EDGES.get(intent, ("import", "from_import", "call"))
    if not preferred:
        return {}

    from app.db.models.dependency_edge import DependencyEdge

    adjacency: dict[str, list[dict]] = {fid: [] for fid in seed_file_ids}

    try:
        # ── Outgoing edges: what do the seed files import/call? ──────────────
        out_rows = db.execute(
            select(
                DependencyEdge.source_file_id,
                DependencyEdge.target_file_id,
                DependencyEdge.edge_type,
                DependencyEdge.target_ref,
            ).where(
                DependencyEdge.repository_id == repository_id,
                DependencyEdge.source_file_id.in_(seed_file_ids),
                DependencyEdge.edge_type.in_(list(preferred)),
            ).limit(max_neighbors * len(seed_file_ids) * 2)
        ).all()

        for source_fid, target_fid, etype, tref in out_rows:
            if source_fid not in adjacency:
                continue
            weight = _EDGE_WEIGHT.get(etype, 0.5)
            # Symbol relevance boost
            if bare_symbols and tref:
                tref_lower = tref.lower()
                if any(sym.lower() in tref_lower or tref_lower in sym.lower()
                       for sym in bare_symbols[:4]):
                    weight = min(1.0, weight + 0.15)
            adjacency[source_fid].append({
                "neighbor_file_id": target_fid,
                "edge_type": etype,
                "target_ref": tref or "",
                "direction": "outgoing",
                "weight": weight,
            })

        # ── Incoming edges: what files import/call the seed files? ───────────
        if intent in (QueryIntent.LINE_IMPACT, QueryIntent.CODE_SNIPPET_IMPACT,
                      QueryIntent.SYMBOL_LOOKUP, QueryIntent.LINE_CHANGE_IMPACT,
                      QueryIntent.ROUTE_FEATURE_IMPACT):
            in_rows = db.execute(
                select(
                    DependencyEdge.source_file_id,
                    DependencyEdge.target_file_id,
                    DependencyEdge.edge_type,
                    DependencyEdge.target_ref,
                ).where(
                    DependencyEdge.repository_id == repository_id,
                    DependencyEdge.target_file_id.in_(seed_file_ids),
                    DependencyEdge.edge_type.in_(list(preferred)),
                ).limit(max_neighbors * len(seed_file_ids))
            ).all()

            for source_fid, target_fid, etype, tref in in_rows:
                if target_fid not in adjacency:
                    continue
                weight = _EDGE_WEIGHT.get(etype, 0.5) * 0.85
                adjacency[target_fid].append({
                    "neighbor_file_id": source_fid,
                    "edge_type": etype,
                    "target_ref": tref or "",
                    "direction": "incoming",
                    "weight": weight,
                })

    except Exception as e:
        logger.warning(f"_build_file_adjacency failed: {e}")

    # Cap neighbors per seed
    for fid in adjacency:
        adjacency[fid] = sorted(adjacency[fid], key=lambda x: -x["weight"])[:max_neighbors]

    return adjacency


def _resolve_neighbor_file_ids(
    db: Session,
    repository_id: str,
    adjacency: dict[str, list[dict]],
    bare_symbols: list[str],
) -> dict[str, str]:
    """
    Resolve unresolved neighbor_file_id=None entries by matching target_ref
    against file paths and symbol names in the DB.

    Returns: {target_ref: file_id} mapping for resolved refs.
    """
    unresolved_refs: set[str] = set()
    for neighbors in adjacency.values():
        for n in neighbors:
            if n["neighbor_file_id"] is None and n["target_ref"]:
                unresolved_refs.add(n["target_ref"])

    if not unresolved_refs:
        return {}

    resolved: dict[str, str] = {}

    try:
        # Strategy 1: match target_ref against file paths
        # target_ref like "app.utils" → "app/utils.py" or "app/utils/index.ts"
        all_files = db.execute(
            select(File.id, File.path).where(File.repository_id == repository_id)
        ).all()

        path_map: dict[str, str] = {}  # normalized_key → file_id
        for fid, fpath in all_files:
            path_map[fpath.lower()] = fid
            # Module-style: app/utils.py → app.utils
            if "." in fpath:
                base = fpath.rsplit(".", 1)[0]
                path_map[base.lower().replace("/", ".")] = fid
                path_map[base.lower()] = fid
            # Basename: app/utils.py → utils
            basename = fpath.split("/")[-1].rsplit(".", 1)[0].lower()
            if len(basename) >= 3:
                path_map.setdefault(basename, fid)

        for ref in unresolved_refs:
            ref_lower = ref.lower()
            # Try exact path match
            if ref_lower in path_map:
                resolved[ref] = path_map[ref_lower]
                continue
            # Try module-style match (e.g. "fastapi.FastAPI" → try "fastapi")
            parts = ref_lower.split(".")
            for i in range(len(parts), 0, -1):
                candidate = ".".join(parts[:i])
                if candidate in path_map:
                    resolved[ref] = path_map[candidate]
                    break

        # Strategy 2: match target_ref against symbol names
        if bare_symbols:
            sym_refs = [r for r in unresolved_refs if r not in resolved]
            if sym_refs:
                for sym_ref in sym_refs[:10]:
                    sym_row = db.scalar(
                        select(Symbol).where(
                            Symbol.repository_id == repository_id,
                            Symbol.name == sym_ref,
                        ).limit(1)
                    )
                    if sym_row:
                        resolved[sym_ref] = sym_row.file_id

    except Exception as e:
        logger.warning(f"_resolve_neighbor_file_ids failed: {e}")

    return resolved


def _fetch_neighbor_evidence(
    db: Session,
    repository_id: str,
    neighbor_file_ids: list[str],
    bare_symbols: list[str],
    intent: str,
    max_per_neighbor: int = 2,
) -> list[dict]:
    """
    Fetch evidence chunks for neighbor files.
    Prefers chunks that contain the query symbols.
    Falls back to the file's top content window.
    """
    if not neighbor_file_ids:
        return []

    results: list[dict] = []
    seen_fids: set[str] = set()

    for fid in neighbor_file_ids[:8]:  # hard cap
        if fid in seen_fids:
            continue
        seen_fids.add(fid)

        try:
            file_rec = db.get(File, fid)
            if not file_rec or not file_rec.content:
                continue

            content = file_rec.content
            lines = content.splitlines()

            # Find the best window: lines containing query symbols
            best_start = 0
            best_score = 0
            window_size = 15

            for i, line in enumerate(lines):
                line_lower = line.lower()
                score = sum(1 for sym in bare_symbols[:4] if sym.lower() in line_lower)
                if score > best_score:
                    best_score = score
                    best_start = max(0, i - 3)

            window_end = min(len(lines), best_start + window_size)
            snippet_lines = lines[best_start:window_end]

            # Filter noise
            clean_lines = [
                l for l in snippet_lines
                if l.strip() and len(l.strip()) > 3
                and not l.strip().startswith("#")
                and not l.strip().startswith("//")
            ]

            if not clean_lines:
                continue

            snippet = "\n".join(clean_lines[:12])

            results.append({
                "file_id": fid,
                "file_path": file_rec.path,
                "start_line": best_start + 1,
                "end_line": window_end,
                "snippet": snippet,
                "match_type": "graph_neighbor",
                "score": 0.65,  # base score for graph-expanded evidence
                "_graph_expanded": True,
            })

        except Exception as e:
            logger.debug(f"neighbor evidence fetch failed for {fid}: {e}")

    return results


def _build_context_chain(
    db: Session,
    repository_id: str,
    seed_candidates: list[dict],
    adjacency: dict[str, list[dict]],
    ref_resolution: dict[str, str],
    bare_symbols: list[str],
    intent: str,
    max_chain_length: int = 3,
) -> list[dict]:
    """
    Build a small reasoning chain from seed evidence:
    - import line → definition file → usage file
    - function call → function definition → dependent caller
    - env lookup → initialization code → downstream usage
    - route registration → handler definition

    Returns a list of chain evidence dicts (graph_neighbor match_type).
    Chain length is bounded to max_chain_length.
    """
    if not seed_candidates or not adjacency:
        return []

    chain: list[dict] = []
    seen_fids: set[str] = set(
        item.get("file_id") or "" for item in seed_candidates if item.get("file_id")
    )

    # Collect all neighbor file IDs from adjacency, prioritized by weight
    neighbor_candidates: list[tuple[float, str, str, str]] = []  # (weight, fid, edge_type, direction)

    for seed in seed_candidates[:3]:  # expand from top 3 seeds only
        seed_fid = seed.get("file_id") or ""
        if not seed_fid or seed_fid not in adjacency:
            continue

        for neighbor in adjacency[seed_fid]:
            n_fid = neighbor["neighbor_file_id"]
            # Resolve if needed
            if n_fid is None:
                n_fid = ref_resolution.get(neighbor["target_ref"])
            if not n_fid or n_fid in seen_fids:
                continue

            neighbor_candidates.append((
                neighbor["weight"],
                n_fid,
                neighbor["edge_type"],
                neighbor["direction"],
            ))

    # Sort by weight, deduplicate
    seen_chain_fids: set[str] = set()
    sorted_neighbors = sorted(neighbor_candidates, key=lambda x: -x[0])

    for weight, n_fid, etype, direction in sorted_neighbors:
        if len(chain) >= max_chain_length:
            break
        if n_fid in seen_chain_fids or n_fid in seen_fids:
            continue
        seen_chain_fids.add(n_fid)

        # Fetch evidence for this neighbor
        neighbor_ev = _fetch_neighbor_evidence(
            db, repository_id, [n_fid], bare_symbols, intent, max_per_neighbor=1
        )
        for ev in neighbor_ev:
            ev["score"] = weight * 0.85  # scale by edge weight
            ev["_chain_edge_type"] = etype
            ev["_chain_direction"] = direction
            chain.append(ev)

    return chain


def _expand_with_graph(
    db: Session,
    repository_id: str,
    base_candidates: list[dict],
    sym_info: dict,
    intent: str,
    max_expansion: int = 4,
) -> list[dict]:
    """
    Main graph expansion entry point.

    Takes the top base retrieval candidates, expands to graph neighbors,
    builds a context chain, and returns the combined evidence list.

    Gracefully returns base_candidates unchanged if graph data is unavailable.
    """
    # Skip graph expansion for pure summary intent — use context pack instead
    # Architecture and flow questions benefit from graph expansion
    if intent in (QueryIntent.REPO_SUMMARY,):
        return base_candidates

    bare_symbols = sym_info.get("bare_identifiers", [])

    # Use top 3 seeds for expansion
    seeds = [c for c in base_candidates[:5] if c.get("file_id")]
    if not seeds:
        return base_candidates

    seed_file_ids = list(dict.fromkeys(s["file_id"] for s in seeds if s.get("file_id")))
    if not seed_file_ids:
        return base_candidates

    try:
        # Step 1: Build adjacency map for seed files
        adjacency = _build_file_adjacency(
            db, repository_id, seed_file_ids, bare_symbols, intent,
            max_neighbors=5,
        )

        # Step 2: Resolve unresolved neighbor file IDs
        ref_resolution = _resolve_neighbor_file_ids(db, repository_id, adjacency, bare_symbols)

        # Step 3: Build context chain (highest-quality expansion)
        chain = _build_context_chain(
            db, repository_id, seeds, adjacency, ref_resolution,
            bare_symbols, intent, max_chain_length=max_expansion,
        )

        if not chain:
            return base_candidates

        # Step 4: Merge chain into base candidates
        # Chain evidence goes after base candidates (base takes priority)
        existing_fids = {c.get("file_id") for c in base_candidates if c.get("file_id")}
        new_chain = [c for c in chain if c.get("file_id") not in existing_fids]

        logger.debug(
            "graph_expand: seeds=%d chain=%d new=%d intent=%s",
            len(seed_file_ids), len(chain), len(new_chain), intent,
        )

        return base_candidates + new_chain[:max_expansion]

    except Exception as e:
        logger.warning(f"_expand_with_graph failed (graceful fallback): {e}")
        return base_candidates


def _rerank_with_graph_distance(
    candidates: list[dict],
    seed_file_ids: list[str],
    adjacency: dict[str, list[dict]],
    ref_resolution: dict[str, str],
    intent: str,
) -> list[dict]:
    """
    Apply graph-distance scoring on top of existing scores.

    Signals:
    - Direct seed: no penalty (already ranked by base reranker)
    - Direct graph neighbor (hop=1): small boost based on edge weight
    - Graph-expanded (hop=1, chain): moderate boost
    - Unrelated (no graph connection): no change

    Keeps boosts modest (max +0.15) so base reranker still dominates.
    """
    if not adjacency:
        return candidates

    # Build a set of (file_id → max_edge_weight) for direct neighbors
    neighbor_weights: dict[str, float] = {}
    for seed_fid, neighbors in adjacency.items():
        for n in neighbors:
            n_fid = n["neighbor_file_id"]
            if n_fid is None:
                n_fid = ref_resolution.get(n["target_ref"])
            if n_fid:
                w = n["weight"]
                neighbor_weights[n_fid] = max(neighbor_weights.get(n_fid, 0.0), w)

    seed_set = set(seed_file_ids)

    for item in candidates:
        fid = item.get("file_id") or ""
        adj = 0.0

        if fid in seed_set:
            # Direct seed — already well-ranked, tiny boost for being a seed
            adj += 0.05
        elif fid in neighbor_weights:
            # Direct graph neighbor — boost proportional to edge weight
            edge_w = neighbor_weights[fid]
            adj += edge_w * 0.12  # max ~0.11 for weight=0.9
        elif item.get("_graph_expanded"):
            # Graph-expanded but not a direct neighbor — small boost
            adj += 0.04

        item["score"] = min(1.0, max(0.0, item.get("score", 0.5) + adj))

    return sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)


def _explain_from_evidence(
    question: str,
    intent: str,
    context_chunks: list[dict],
    db,
    repository_id: str,
) -> str:
    """
    Query-aware deterministic explanation engine.
    Dispatches to the appropriate explanation strategy based on intent.
    Never returns a raw snippet echo.
    """
    target_line, file_path, context_lines = _extract_target_line_and_context(context_chunks, question)

    # If we have no target line at all, do a direct DB search for key tokens
    if not target_line:
        _STOPWORDS = {"what", "does", "this", "that", "repo", "file", "line", "code",
                      "the", "and", "for", "with", "from", "into", "how", "why",
                      "when", "where", "which", "will", "would", "should", "could",
                      "have", "been", "being", "about", "delete", "remove", "happen"}
        q_tokens = [
            t.lower().strip("'\"`.,()")
            for t in question.split()
            if len(t) >= 4 and t.lower().strip("'\"`.(),") not in _STOPWORDS
        ]
        from app.db.models.file import File as _File
        from sqlalchemy import select as _sel
        for tok in q_tokens[:3]:
            try:
                hits = list(db.scalars(
                    _sel(_File).where(
                        _File.repository_id == repository_id,
                        _File.content.ilike(f"%{tok}%"),
                    ).limit(3)
                ).all())
                for h in hits:
                    for raw_line in (h.content or "").splitlines():
                        if tok in raw_line.lower() and len(raw_line.strip()) > 5:
                            target_line = raw_line.strip()
                            file_path = h.path
                            # Grab a few surrounding lines for context
                            all_lines = (h.content or "").splitlines()
                            idx = next(
                                (i for i, l in enumerate(all_lines) if raw_line.strip() in l),
                                0,
                            )
                            context_lines = [
                                l.strip() for l in all_lines[max(0, idx - 3): idx + 4]
                                if l.strip() and l.strip() != target_line
                            ]
                            break
                    if target_line:
                        break
            except Exception:
                pass
            if target_line:
                break

    if not target_line:
        # Absolute last resort: return the top snippet cleaned up
        if context_chunks:
            first = context_chunks[0]
            fp = first.get("file_path") or "the repository"
            snip_lines = [
                l.strip() for l in (first.get("snippet") or "").splitlines()
                if l.strip() and not _re_explain.match(r"^Found matching snippet", l)
                and len(l.strip()) > 5
            ][:6]
            return (
                f"The most relevant context found is in `{fp}`:\n\n"
                + "\n".join(snip_lines)[:400]
            )
        return "I couldn't find enough relevant indexed context to answer that confidently."

    # Dispatch by intent
    is_impact = intent in (
        "line_impact", "line_change_impact", "code_snippet_impact",
        "dependency_impact", "route_feature_impact", "config_impact",
        "file_impact",
    )

    if is_impact:
        return _explain_impact(target_line, file_path, context_lines)
    else:
        return _explain_line(target_line, file_path, context_lines)


class RAGService:
    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = EmbeddingService(db)
        self.graph_service = GraphService(db)

    def _build_flow_context(
        self,
        repository_id: str,
        question: str,
        sym_info: dict,
    ) -> list[dict]:
        """
        Build context for flow/architecture questions.

        Combines:
        1. Route/controller files (entry points for request flows)
        2. Service files (business logic layer)
        3. Entrypoint files (startup flow)
        4. FlowService primary flow if available
        5. Hybrid search for the specific topic (login, auth, startup, etc.)

        Never raises — returns empty list on failure.
        """
        results: list[dict] = []
        seen_ids: set[str] = set()

        def _add_item(item: dict) -> None:
            uid = item.get("file_id") or item.get("file_path") or ""
            if uid and uid not in seen_ids:
                seen_ids.add(uid)
                results.append(item)

        try:
            # 1. Try FlowService for primary flow context
            try:
                from app.services.flow_service import FlowService
                flow_svc = FlowService(self.db)
                # Extract the most relevant query term for flow lookup
                bare = sym_info.get("bare_identifiers", [])
                flow_query = bare[0] if bare else question.split()[-1] if question else ""
                if flow_query:
                    flow_result = flow_svc.get_flow(
                        repository_id=repository_id,
                        mode="primary",
                        query=flow_query,
                        depth=3,
                    )
                    for path in (flow_result.get("paths") or [])[:2]:
                        for node in (path.get("nodes") or [])[:5]:
                            node_path = node.get("path", "")
                            node_fid = node.get("file_id")
                            if node_path and node_fid:
                                # Fetch file content for this node
                                try:
                                    f = self.db.get(File, node_fid)
                                    if f and f.content:
                                        _add_item({
                                            "file_id": node_fid,
                                            "file_path": node_path,
                                            "snippet": (f.content or "")[:1500],
                                            "match_type": "flow_node",
                                            "score": 0.90,
                                        })
                                except Exception:
                                    pass
            except Exception as _flow_err:
                logger.debug("flow context fetch failed: %s", _flow_err)

            # 2. Route/controller files
            route_files = list(self.db.scalars(
                select(File).where(
                    File.repository_id == repository_id,
                    or_(
                        File.path.ilike("%route%"),
                        File.path.ilike("%router%"),
                        File.path.ilike("%controller%"),
                        File.path.ilike("%handler%"),
                        File.path.ilike("%/api/%"),
                        File.path.ilike("%/views.py"),
                    ),
                    File.is_test.is_(False),
                    File.is_generated.is_(False),
                ).limit(6)
            ).all())
            route_files.sort(key=lambda f: -(f.line_count or 0))
            for rf in route_files[:3]:
                _add_item({
                    "file_id": str(rf.id),
                    "file_path": rf.path,
                    "snippet": (rf.content or "")[:1500],
                    "match_type": "route_file",
                    "score": 0.85,
                })

            # 3. Service files
            service_files = list(self.db.scalars(
                select(File).where(
                    File.repository_id == repository_id,
                    or_(
                        File.path.ilike("%service%"),
                        File.path.ilike("%usecase%"),
                        File.path.ilike("%manager%"),
                    ),
                    File.is_test.is_(False),
                    File.is_generated.is_(False),
                ).limit(5)
            ).all())
            service_files.sort(key=lambda f: -(f.line_count or 0))
            for sf in service_files[:2]:
                _add_item({
                    "file_id": str(sf.id),
                    "file_path": sf.path,
                    "snippet": (sf.content or "")[:1200],
                    "match_type": "service_file",
                    "score": 0.80,
                })

            # 4. Entrypoint files
            _EP_PATTERNS = [
                "%/main.py", "%/app.py", "%/server.py", "%/manage.py",
                "%/index.js", "%/index.ts", "%/main.js", "%/main.ts",
            ]
            ep_clauses = [File.path.ilike(p) for p in _EP_PATTERNS]
            entrypoints = list(self.db.scalars(
                select(File).where(
                    File.repository_id == repository_id,
                    or_(*ep_clauses),
                ).limit(3)
            ).all())
            entrypoints.sort(key=lambda f: len(f.path))
            for ep in entrypoints[:2]:
                _add_item({
                    "file_id": str(ep.id),
                    "file_path": ep.path,
                    "snippet": (ep.content or "")[:1500],
                    "match_type": "entrypoint",
                    "score": 0.88,
                })

        except Exception as e:
            logger.debug("_build_flow_context failed: %s", e)

        return results

    def _synthesize_flow_context(
        self,
        repository_id: str,
        context_pack: list[dict],
        question: str,
    ) -> str:
        """
        Build a plain-text flow summary from route/service/entrypoint context.
        Used as top context for flow questions and as fallback answer.
        Never raises.
        """
        try:
            import re as _re_flow
            sections: list[str] = []

            # Entrypoint
            entry = next((c for c in context_pack if c.get("match_type") == "entrypoint"), None)
            if entry:
                lines = [
                    l.strip() for l in (entry.get("snippet") or "").splitlines()
                    if l.strip() and not l.strip().startswith("#") and len(l.strip()) > 5
                ][:15]
                if lines:
                    sections.append(f"ENTRYPOINT ({entry.get('file_path')}):\n" + "\n".join(lines))

            # Routes
            route_items = [c for c in context_pack if c.get("match_type") in ("route_file", "flow_node")]
            if route_items:
                route_lines: list[str] = []
                for ri in route_items[:3]:
                    snip = ri.get("snippet") or ""
                    for line in snip.splitlines():
                        s = line.strip()
                        if _re_flow.search(
                            r"@(app|router|blueprint|api)\.(get|post|put|delete|patch|options|head)\s*\(|"
                            r"(app|router)\.(get|post|put|delete|patch)\s*\(|"
                            r"async\s+def\s+\w+|def\s+\w+",
                            s, _re_flow.IGNORECASE
                        ):
                            route_lines.append(s[:120])
                if route_lines:
                    sections.append("ROUTES / HANDLERS:\n" + "\n".join(route_lines[:12]))

            # Services
            svc_items = [c for c in context_pack if c.get("match_type") == "service_file"]
            if svc_items:
                svc_names = [(c.get("file_path") or "").split("/")[-1] for c in svc_items[:4]]
                sections.append(f"SERVICE LAYER: {', '.join(svc_names)}")

            if not sections:
                return ""

            return "\n\n---\n\n".join(sections)[:3000]

        except Exception as e:
            logger.debug("_synthesize_flow_context failed: %s", e)
            return ""

    def _build_repo_context_pack(self, repository_id: str) -> list[dict]:
        """
        Build a ranked context pack for repo-level questions.

        Priority order (highest score first):
          1. Pre-computed repo_intelligence chunk (if available)
          2. README / documentation files
          3. Entrypoint files (app.py, main.py, server.py, index.js, src/main.*, manage.py, etc.)
          4. Top route/controller files (routes, controllers, handlers, views, api)
          5. Top service files (services, usecases, managers)
          6. Framework/config files (requirements.txt, package.json, pyproject.toml,
             Dockerfile, docker-compose, next.config, vite.config, etc.)
          7. Data model files (models, schemas, entities)

        requirements.txt / package.json alone are NEVER the top result — they are
        supplementary context, not the primary answer source.
        """
        results: list[dict] = []

        # ── 1. Pre-computed repo intelligence (highest priority) ─────────────
        intel_chunk = self.db.scalar(
            select(EmbeddingChunk).where(
                EmbeddingChunk.repository_id == repository_id,
                EmbeddingChunk.chunk_type == "repo_intelligence",
            ).limit(1)
        )
        if intel_chunk:
            results.append({
                "file_path": "repository_intelligence",
                "snippet": (intel_chunk.content or "")[:3000],
                "match_type": "repo_intelligence",
                "score": 1.0,
            })

        # ── 2. README / documentation ────────────────────────────────────────
        readmes = list(self.db.scalars(
            select(File).where(
                File.repository_id == repository_id,
                or_(
                    File.path.ilike("%README.md"),
                    File.path.ilike("%README.rst"),
                    File.path.ilike("%README.txt"),
                    File.path.ilike("%README"),
                    File.path.ilike("%readme.md"),
                ),
            ).limit(3)
        ).all())
        # Sort: shorter path = more root-level = more authoritative
        readmes.sort(key=lambda f: len(f.path))
        for r in readmes[:2]:
            results.append({
                "file_id": str(r.id),
                "file_path": r.path,
                "snippet": (r.content or "")[:3000],
                "match_type": "readme",
                "score": 0.97,
            })

        # ── 3. Entrypoint files ───────────────────────────────────────────────
        # Generic heuristics — no repo-specific names
        _ENTRYPOINT_PATTERNS = [
            "%/main.py", "%/app.py", "%/server.py", "%/manage.py",
            "%/wsgi.py", "%/asgi.py", "%/run.py", "%/start.py",
            "%/index.js", "%/index.ts", "%/main.js", "%/main.ts",
            "%/src/main.py", "%/src/app.py", "%/src/index.js", "%/src/index.ts",
            "%/src/main.js", "%/src/main.ts", "%/src/server.js", "%/src/server.ts",
            "%/cmd/main.go", "%/main.go",
        ]
        entrypoint_clauses = [File.path.ilike(p) for p in _ENTRYPOINT_PATTERNS]
        entrypoints = list(self.db.scalars(
            select(File).where(
                File.repository_id == repository_id,
                or_(*entrypoint_clauses),
            ).limit(6)
        ).all())
        # Prefer shorter paths (root-level entrypoints over nested ones)
        entrypoints.sort(key=lambda f: len(f.path))
        for e in entrypoints[:3]:
            results.append({
                "file_id": str(e.id),
                "file_path": e.path,
                "snippet": (e.content or "")[:2500],
                "match_type": "entrypoint",
                "score": 0.93,
            })

        # ── 4. Route / controller / API files ────────────────────────────────
        route_files = list(self.db.scalars(
            select(File).where(
                File.repository_id == repository_id,
                or_(
                    File.path.ilike("%route%"),
                    File.path.ilike("%router%"),
                    File.path.ilike("%controller%"),
                    File.path.ilike("%handler%"),
                    File.path.ilike("%endpoint%"),
                    File.path.ilike("%/api/%"),
                    File.path.ilike("%/views.py"),
                    File.path.ilike("%/urls.py"),
                ),
                File.is_test.is_(False),
                File.is_generated.is_(False),
            ).limit(10)
        ).all())
        # Sort by line count descending — larger route files are more informative
        route_files.sort(key=lambda f: -(f.line_count or 0))
        for rf in route_files[:3]:
            results.append({
                "file_id": str(rf.id),
                "file_path": rf.path,
                "snippet": (rf.content or "")[:2000],
                "match_type": "route_file",
                "score": 0.88,
            })

        # ── 5. Service / business logic files ────────────────────────────────
        service_files = list(self.db.scalars(
            select(File).where(
                File.repository_id == repository_id,
                or_(
                    File.path.ilike("%service%"),
                    File.path.ilike("%usecase%"),
                    File.path.ilike("%use_case%"),
                    File.path.ilike("%manager%"),
                    File.path.ilike("%business%"),
                ),
                File.is_test.is_(False),
                File.is_generated.is_(False),
            ).limit(8)
        ).all())
        service_files.sort(key=lambda f: -(f.line_count or 0))
        for sf in service_files[:2]:
            results.append({
                "file_id": str(sf.id),
                "file_path": sf.path,
                "snippet": (sf.content or "")[:1500],
                "match_type": "service_file",
                "score": 0.82,
            })

        # ── 6. Framework / config / build files ──────────────────────────────
        config_files = list(self.db.scalars(
            select(File).where(
                File.repository_id == repository_id,
                or_(
                    File.path.ilike("%requirements.txt"),
                    File.path.ilike("%requirements-%.txt"),
                    File.path.ilike("%pyproject.toml"),
                    File.path.ilike("%package.json"),
                    File.path.ilike("%Dockerfile"),
                    File.path.ilike("%docker-compose%"),
                    File.path.ilike("%next.config%"),
                    File.path.ilike("%vite.config%"),
                    File.path.ilike("%webpack.config%"),
                    File.path.ilike("%tsconfig.json"),
                    File.path.ilike("%setup.py"),
                    File.path.ilike("%setup.cfg"),
                    File.path.ilike("%go.mod"),
                    File.path.ilike("%Cargo.toml"),
                    File.path.ilike("%pom.xml"),
                    File.path.ilike("%build.gradle%"),
                ),
            ).limit(8)
        ).all())
        # Sort: shorter path = root-level config = more authoritative
        config_files.sort(key=lambda f: len(f.path))
        for cf in config_files[:4]:
            results.append({
                "file_id": str(cf.id),
                "file_path": cf.path,
                "snippet": (cf.content or "")[:1200],
                "match_type": "config_manifest",
                "score": 0.78,
            })

        # ── 7. Data model / schema files ─────────────────────────────────────
        model_files = list(self.db.scalars(
            select(File).where(
                File.repository_id == repository_id,
                or_(
                    File.path.ilike("%/models.py"),
                    File.path.ilike("%/model.py"),
                    File.path.ilike("%/schema.py"),
                    File.path.ilike("%/schemas.py"),
                    File.path.ilike("%/entities%"),
                    File.path.ilike("%/models/%"),
                ),
                File.is_test.is_(False),
                File.is_generated.is_(False),
            ).limit(5)
        ).all())
        model_files.sort(key=lambda f: -(f.line_count or 0))
        for mf in model_files[:2]:
            results.append({
                "file_id": str(mf.id),
                "file_path": mf.path,
                "snippet": (mf.content or "")[:1200],
                "match_type": "data_model",
                "score": 0.72,
            })

        # Deduplicate by file_id, preserve order (highest score first)
        seen_ids: set[str] = set()
        deduped: list[dict] = []
        for item in results:
            uid = item.get("file_id") or item.get("file_path") or ""
            if uid and uid not in seen_ids:
                seen_ids.add(uid)
                deduped.append(item)

        return deduped

    def _synthesize_repo_overview(
        self,
        repository_id: str,
        context_pack: list[dict],
        intent: str,
    ) -> str:
        """
        Build a structured internal repo overview from the context pack.

        Extracts signals from README, entrypoints, config files, and route/service files
        to produce a structured summary:
          - primary purpose
          - framework / stack
          - likely entrypoint
          - major modules / capabilities
          - auth / db / external integrations
          - deployment / runtime hints

        This summary is prepended as top context for the LLM prompt, ensuring
        the answer is grounded in repo-level understanding rather than random snippets.

        Returns a plain-text structured overview string.
        Never raises — returns empty string on failure.
        """
        try:
            import re as _re_ov

            sections: list[str] = []

            # ── README: extract first meaningful paragraph ────────────────────
            readme_item = next(
                (c for c in context_pack if c.get("match_type") == "readme"),
                None,
            )
            if readme_item:
                readme_text = (readme_item.get("snippet") or "").strip()
                # Extract first non-header, non-badge paragraph
                paragraphs = [
                    p.strip() for p in _re_ov.split(r"\n{2,}", readme_text)
                    if p.strip()
                    and not p.strip().startswith("#")
                    and not p.strip().startswith("[![")
                    and not p.strip().startswith("---")
                    and len(p.strip()) > 40
                ]
                if paragraphs:
                    sections.append(f"README DESCRIPTION:\n{paragraphs[0][:600]}")

            # ── Config files: detect framework / stack ────────────────────────
            stack_signals: list[str] = []
            for item in context_pack:
                mt = item.get("match_type", "")
                fp = (item.get("file_path") or "").lower()
                snippet = (item.get("snippet") or "")

                if mt == "config_manifest" or "requirements" in fp or "package.json" in fp or "pyproject" in fp:
                    # Extract dependency names (first 20 lines of manifest)
                    dep_lines = [
                        l.strip() for l in snippet.splitlines()[:30]
                        if l.strip()
                        and not l.strip().startswith("#")
                        and not l.strip().startswith("//")
                        and len(l.strip()) > 2
                    ][:15]
                    if dep_lines:
                        stack_signals.append(f"DEPENDENCIES ({fp}):\n" + "\n".join(dep_lines))

            if stack_signals:
                sections.append("\n\n".join(stack_signals[:2]))

            # ── Entrypoint: extract top-level structure ───────────────────────
            entry_item = next(
                (c for c in context_pack if c.get("match_type") == "entrypoint"),
                None,
            )
            if entry_item:
                entry_text = (entry_item.get("snippet") or "").strip()
                # Extract meaningful lines: imports, app creation, route registration
                entry_lines = [
                    l.strip() for l in entry_text.splitlines()
                    if l.strip()
                    and not l.strip().startswith("#")
                    and not l.strip().startswith("//")
                    and len(l.strip()) > 5
                ][:20]
                if entry_lines:
                    sections.append(
                        f"ENTRYPOINT ({entry_item.get('file_path')}):\n"
                        + "\n".join(entry_lines)
                    )

            # ── Route files: list top-level routes / capabilities ─────────────
            route_items = [c for c in context_pack if c.get("match_type") == "route_file"]
            if route_items:
                route_lines: list[str] = []
                for ri in route_items[:2]:
                    snip = (ri.get("snippet") or "")
                    # Extract route decorator lines
                    for line in snip.splitlines():
                        s = line.strip()
                        if _re_ov.search(
                            r"@(app|router|blueprint|api)\.(get|post|put|delete|patch|options|head)\s*\(",
                            s, _re_ov.IGNORECASE
                        ) or _re_ov.search(
                            r"(app|router)\.(get|post|put|delete|patch)\s*\(",
                            s, _re_ov.IGNORECASE
                        ) or _re_ov.search(r"path\s*\(", s, _re_ov.IGNORECASE):
                            route_lines.append(s[:120])
                if route_lines:
                    sections.append(
                        f"ROUTES / API ENDPOINTS (sample):\n"
                        + "\n".join(route_lines[:10])
                    )

            # ── Service files: list service names ─────────────────────────────
            service_items = [c for c in context_pack if c.get("match_type") == "service_file"]
            if service_items:
                svc_names = [
                    (c.get("file_path") or "").split("/")[-1]
                    for c in service_items[:4]
                ]
                if svc_names:
                    sections.append(f"SERVICE MODULES: {', '.join(svc_names)}")

            # ── Pre-computed intelligence ─────────────────────────────────────
            intel_item = next(
                (c for c in context_pack if c.get("match_type") == "repo_intelligence"),
                None,
            )
            if intel_item:
                intel_text = (intel_item.get("snippet") or "").strip()
                if intel_text:
                    sections.insert(0, f"REPO INTELLIGENCE:\n{intel_text[:1500]}")

            if not sections:
                return ""

            overview = "\n\n---\n\n".join(sections)
            return overview[:4000]  # hard cap

        except Exception as _ov_err:
            logger.debug(f"_synthesize_repo_overview failed (graceful): {_ov_err}")
            return ""

    def _rank_evidence(self, evidence: list[dict], mode: str, intent: str) -> list[dict]:
        """
        Heuristic ranking (Phase 5). Prioritizes code for code-queries,
        manifests for architecture, etc.
        """
        if not evidence:
            return []

        # Source code extensions
        _SOURCE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".rb", ".cpp", ".c", ".h"}
        
        for item in evidence:
            score_adj = 0.0
            fp = item.get("file_path", "").lower()
            mt = item.get("match_type", "")
            
            # 1. Extension Boost
            ext = "." + fp.rsplit(".", 1)[-1] if "." in fp else ""
            if ext in _SOURCE_EXTS:
                score_adj += 0.2
            elif fp.endswith(".csv") or fp.endswith(".json") or fp.endswith(".md"):
                score_adj -= 0.1

            # 2. Intent-specific Boost
            if mode == QueryMode.IMPACT:
                if ext in _SOURCE_EXTS: score_adj += 0.3
                if mt == "config_manifest": score_adj += 0.1
                if fp.endswith(".csv"): score_adj -= 0.4  # Heavily penalize CSVs for code impact
            
            if intent in (QueryIntent.REPO_SUMMARY, QueryIntent.ARCHITECTURE_EXPLANATION):
                if mt in ("config_manifest", "repo_intelligence", "documentation"):
                    score_adj += 0.4
                if "router" in fp or "main" in fp:
                    score_adj += 0.3

            item["score"] = min(1.0, item.get("score", 0.5) + score_adj)

        # Sort by score descending
        return sorted(evidence, key=lambda x: x.get("score", 0), reverse=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ask_repo(self, repository_id: str, question: str, top_k: int = 8) -> dict:
        from app.db.models.repository import Repository
        from app.llm.prompt_builder import build_system_prompt, build_user_prompt, build_repo_overview_prompt, build_flow_question_prompt

        clean_question = (question or "").strip()
        if not clean_question:
            return {"answer": "Question cannot be empty.", "citations": [], "mode": "error", "query": clean_question}

        repo = self.db.get(Repository, repository_id)
        if not repo:
            return {"answer": "Repository not found.", "citations": [], "mode": "error", "query": clean_question}

        # ── Step 1: classify intent ──────────────────────────────────────────
        classification = QueryClassifier.classify(clean_question)
        intent = classification.get("intent", QueryIntent.SEMANTIC_QA)
        mode = classification.get("mode", QueryMode.GENERAL)

        # ── Step 2: extract symbols + build retrieval probes (A + B) ────────
        sym_info = _extract_query_symbols(clean_question)
        retrieval_probes = _build_retrieval_queries(clean_question, sym_info, intent)
        logger.debug(
            "ask_repo symbols=%s probes=%s intent=%s",
            sym_info["extracted_symbols"],
            retrieval_probes,
            intent,
        )

        # ── Step 3: retrieve evidence using multiple probes ──────────────────
        snippet = (classification.get("snippet") or "").strip()
        all_retrieved: list[dict] = []
        seen_ids: set[str] = set()

        def _merge(items: list[dict]) -> None:
            for item in items:
                uid = item.get("chunk_id") or f"{item.get('file_path')}:{item.get('start_line')}"
                if uid not in seen_ids:
                    seen_ids.add(uid)
                    all_retrieved.append(item)

        try:
            if intent in (QueryIntent.REPO_SUMMARY, QueryIntent.ARCHITECTURE_EXPLANATION):
                _merge(self._build_repo_context_pack(repository_id) or [])
            elif intent in (QueryIntent.FLOW_QUESTION,):
                # Flow questions: combine repo context pack (routes/services/entrypoints)
                # with hybrid search for the specific flow topic
                _merge(self._build_flow_context(repository_id, clean_question, sym_info) or [])
                if not all_retrieved:
                    _merge(self.embedding_service.hybrid_search(repository_id, clean_question, top_k=top_k) or [])
            else:
                # Primary probe: snippet-based or hybrid search
                if snippet:
                    _merge(self._retrieve_code_snippet(repository_id, snippet) or [])
                if not all_retrieved:
                    _merge(
                        self.embedding_service.hybrid_search(
                            repository_id, clean_question, top_k=top_k
                        ) or []
                    )
                if not all_retrieved:
                    _merge(self._keyword_file_search(repository_id, clean_question, top_k=top_k) or [])

                # Additional probes from query rewriting (skip the first probe = original question)
                for probe in retrieval_probes[1:]:
                    if len(all_retrieved) >= top_k * 3:
                        break
                    try:
                        probe_results = (
                            self._retrieve_code_snippet(repository_id, probe) or []
                            if any(
                                tok in probe
                                for tok in ("import ", "def ", "class ", "=", "(", ".")
                            )
                            else self.embedding_service.hybrid_search(
                                repository_id, probe, top_k=max(3, top_k // 2)
                            ) or []
                        )
                        _merge(probe_results)
                    except Exception as probe_err:
                        logger.debug("probe retrieval failed for %r: %s", probe, probe_err)

        except Exception as retrieval_err:
            logger.error("Ask Repo retrieval failed: %s", retrieval_err, exc_info=True)
            _merge(self._keyword_file_search(repository_id, clean_question, top_k=top_k) or [])

        if not all_retrieved:
            return {
                "answer": "I couldn't find enough relevant indexed context to answer that confidently. Try asking about a specific file, function, or line.",
                "citations": [],
                "mode": "no_context",
                "query": clean_question,
            }

        # ── Step 3b: graph expansion from top base candidates ───────────────
        # Expand retrieval using file-relationship graph (import/call edges).
        # Gracefully skips if graph data is unavailable or intent is summary.
        if all_retrieved and intent not in (QueryIntent.REPO_SUMMARY, QueryIntent.ARCHITECTURE_EXPLANATION):
            try:
                all_retrieved = _expand_with_graph(
                    self.db, repository_id, all_retrieved, sym_info, intent,
                    max_expansion=4,
                )
            except Exception as _graph_err:
                logger.debug("graph expansion skipped: %s", _graph_err)

        # ── Step 4: advanced rerank (replaces old rank + boost) ────────────
        ranked = _rerank_evidence_advanced(all_retrieved, clean_question, intent, mode, sym_info)

        # ── Step 4b: graph-distance reranking on top of advanced rerank ─────
        # Apply graph-distance signals to further refine ordering.
        if intent not in (QueryIntent.REPO_SUMMARY,):
            try:
                seed_file_ids = list(dict.fromkeys(
                    c.get("file_id") for c in all_retrieved[:5] if c.get("file_id")
                ))
                if seed_file_ids:
                    adjacency = _build_file_adjacency(
                        self.db, repository_id, seed_file_ids,
                        sym_info.get("bare_identifiers", []), intent, max_neighbors=5,
                    )
                    ref_resolution = _resolve_neighbor_file_ids(
                        self.db, repository_id, adjacency,
                        sym_info.get("bare_identifiers", []),
                    )
                    ranked = _rerank_with_graph_distance(
                        ranked, seed_file_ids, adjacency, ref_resolution, intent
                    )
            except Exception as _graph_rank_err:
                logger.debug("graph reranking skipped: %s", _graph_rank_err)

        # ── Step 5: deduplicate, cap at top_k ───────────────────────────────
        seen_dedup: set[str] = set()
        deduped: list[dict] = []
        for item in ranked:
            uid = item.get("chunk_id") or f"{item.get('file_path')}:{item.get('start_line')}"
            if uid in seen_dedup:
                continue
            seen_dedup.add(uid)
            deduped.append(item)
            if len(deduped) >= top_k:
                break

        # ── Step 6: compress evidence for LLM synthesis ─────────────────────
        # Compress into focused, high-signal windows before sending to LLM.
        # Code/symbol/flow questions get larger windows; summary gets more blocks.
        is_code_or_symbol = intent in (
            QueryIntent.SEMANTIC_QA, QueryIntent.SYMBOL_LOOKUP,
            QueryIntent.DEPENDENCY_TRACE, QueryIntent.FLOW_QUESTION,
        )
        llm_max_chars = 3000 if is_code_or_symbol else 2000
        llm_max_block = 600 if is_code_or_symbol else 400

        llm_chunks = _compress_evidence_for_answer(
            clean_question, intent, sym_info, deduped,
            max_blocks=6, max_chars_per_block=llm_max_block, max_total_chars=llm_max_chars,
        )
        if not llm_chunks:
            llm_chunks = deduped[:6]

        # Broader evidence for fallback (slightly less compressed)
        context_chunks = _compress_evidence_for_answer(
            clean_question, intent, sym_info, deduped,
            max_blocks=10, max_chars_per_block=700, max_total_chars=5000,
        )
        if not context_chunks:
            context_chunks = deduped[:8]

        # Build fallback context string
        context_blocks: list[str] = []
        total_chars = 0
        _MAX_FALLBACK_CHARS = 6000
        for item in context_chunks:
            file_path = item.get("file_path", "unknown")
            start_line = item.get("start_line") or 0
            end_line = item.get("end_line") or start_line
            snippet_text = (item.get("snippet") or item.get("chunk_text") or "").strip()
            if len(snippet_text) > 600:
                snippet_text = snippet_text[:600] + " ..."
            block = f"[{file_path}:{start_line}-{end_line}]\n{snippet_text}"
            if total_chars + len(block) > _MAX_FALLBACK_CHARS:
                break
            context_blocks.append(block)
            total_chars += len(block)

        provider = get_chat_provider()
        if provider is not None:
            try:
                system_prompt = build_system_prompt(intent=intent)
                # For repo-level questions: synthesize a structured overview first,
                # then inject it as top context so Gemini answers from repo understanding
                # rather than random snippet retrieval.
                if intent in (QueryIntent.REPO_SUMMARY, QueryIntent.ARCHITECTURE_EXPLANATION):
                    repo_overview = self._synthesize_repo_overview(
                        repository_id, deduped, intent
                    )
                    user_prompt = build_repo_overview_prompt(
                        clean_question, llm_chunks, repo_overview, intent
                    )
                elif intent in (QueryIntent.FLOW_QUESTION,):
                    # Flow questions: inject flow summary as top context
                    flow_summary = self._synthesize_flow_context(
                        repository_id, deduped, clean_question
                    )
                    user_prompt = build_flow_question_prompt(
                        clean_question, llm_chunks, flow_summary, intent
                    )
                else:
                    user_prompt = build_user_prompt(clean_question, llm_chunks, intent=intent)
                llm_answer = (provider.answer(system_prompt, user_prompt) or "").strip()
                if llm_answer:
                    shaped = _shape_final_answer(llm_answer, intent)
                    return {
                        "answer": shaped or llm_answer,
                        "citations": self._build_citations(llm_chunks),
                        "mode": "gemini_synthesized",
                        "llm_model": provider.model_name,
                        "query": clean_question,
                    }
            except Exception as llm_err:
                logger.error("Gemini synthesis failed: %s", llm_err, exc_info=True)

        fallback_context = "\n\n".join(context_blocks).strip()
        if not fallback_context:
            fallback_answer = "I couldn't find enough relevant indexed context to answer that confidently. Try asking about a specific file, function, or line."
            fallback_mode = "no_context"
        else:
            # For repo summary questions, use the synthesized overview as fallback
            if intent in ("repo_summary", "architecture_explanation"):
                repo_overview = self._synthesize_repo_overview(
                    repository_id, deduped, intent
                )
                if repo_overview:
                    fallback_answer = repo_overview
                else:
                    # Last resort: pull first meaningful lines from top chunks
                    parts: list[str] = []
                    for c in context_chunks[:4]:
                        mt = c.get("match_type", "")
                        fp = c.get("file_path") or ""
                        snip_lines = [
                            l.strip() for l in (c.get("snippet") or "").splitlines()
                            if l.strip() and not l.strip().startswith("#")
                            and not l.strip().startswith("[![") and len(l.strip()) > 5
                        ][:5]
                        if snip_lines:
                            parts.append(f"[{fp}]:\n" + "\n".join(snip_lines))
                    fallback_answer = "\n\n".join(parts)[:1200] if parts else (
                        "I couldn't find enough indexed context to summarize this repository. "
                        "Make sure the repository has been parsed and indexed."
                    )
                fallback_mode = "fallback"
            elif intent in ("flow_question",):
                # Flow fallback: synthesize from route/service/entrypoint context
                flow_summary = self._synthesize_flow_context(
                    repository_id, context_chunks, clean_question
                )
                if flow_summary:
                    fallback_answer = flow_summary
                else:
                    fallback_answer = _explain_from_evidence(
                        clean_question, intent, context_chunks, self.db, repository_id
                    )
                fallback_mode = "fallback"
            else:
                # All other intents: use the query-aware explanation engine
                fallback_answer = _explain_from_evidence(
                    clean_question, intent, context_chunks, self.db, repository_id
                )
                fallback_mode = "fallback"

        return {
            "answer": _shape_final_answer(fallback_answer, intent),
            "citations": self._build_citations(context_chunks),
            "mode": fallback_mode,
            "llm_model": None,
            "query": clean_question,
        }



    @staticmethod
    def _line_meta_fields(line_metadata: dict) -> dict:
        """Extracts serializable fields from line_metadata."""
        if not line_metadata:
            return {}
        return {
            "resolved_file": line_metadata.get("file_path"),
            "resolved_line_number": line_metadata.get("line_no"),
            "matched_line": line_metadata.get("line_text"),
            "enclosing_scope": line_metadata.get("enclosing_symbol"),
            "line_type": line_metadata.get("line_type"),
            "rename_analysis": line_metadata.get("rename_analysis"),
        }

    @staticmethod
    def _sanitize_answer(text: str) -> str:
        """
        Relaxes sanitization to allow standard markdown headers and formatting
        for professional UI rendering while stripping excessively long blocks.
        """
        import re as _re
        # Remove fenced code block delimiters (```lang ... ```) - the UI should handle them
        # but the user requested "small code snippets", so we keep them if they are small.
        # Actually, let's keep headers and bolding.
        
        # Collapse quadruple+ blank lines
        text = _re.sub(r"\n{4,}", "\n\n\n", text)
        return text.strip()

    @staticmethod
    def _postprocess_answer(text: str, intent: str) -> str:
        import re as _re
        if not text:
            return ""

        lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                lines.append("")
                continue

            lowered = line.lower()
            if lowered in {
                "direct answer", "evidence", "detailed explanation",
                "likely impact / risks", "confidence",
            }:
                continue
            if lowered.startswith("### "):
                header = lowered.replace("### ", "").strip()
                if header in {"direct answer", "evidence", "detailed explanation", "likely impact / risks", "confidence"}:
                    continue
            if lowered.startswith("confidence:") or lowered.startswith("evidence:") or lowered.startswith("evidence from:"):
                continue
            if lowered in {
                "impact analysis",
                "matched line:",
                "what this line does:",
                "likely impact if deleted:",
                "severity:",
                "dependency impact analysis",
                "route / feature impact analysis",
                "config / infrastructure impact analysis",
            }:
                continue
            if set(line) == {"="}:
                continue
            if lowered.startswith("retrieved directly relevant repository files"):
                continue
            if lowered == "key files:":
                continue
            if lowered.startswith("key files and their roles"):
                continue
            if _re.match(r"^\[[A-Z_]+\]\s+", line):
                continue
            if _re.match(r"^[-*]\s*`?[\w./\-\[\]]+\.[A-Za-z0-9]+`?$", line):
                continue
            if line.startswith("-") and "/" in line and ("`" in line or ".py" in line or ".ts" in line or ".js" in line):
                continue
            if _re.match(r"^[\w./\-\[\]]+\.[A-Za-z0-9]+$", line):
                continue
            if _re.match(r"^[\w./\-\[\]]+\.[A-Za-z0-9]+\s+\(line\s+\d+\)$", line, flags=_re.IGNORECASE):
                continue
            if _re.match(r"^\[[A-Z\-]+\]$", line):
                continue

            clean = line.replace("`", "")
            clean = clean.replace("**", "")
            lines.append(clean)

        out = "\n".join(lines)
        out = _re.sub(r"\n{3,}", "\n\n", out).strip()
        return out

    def _calculate_confidence(self, mode: str, retrieved: list[dict], line_meta: dict) -> str:
        """Honest confidence scoring based on mode-specific evidence requirements."""
        if not retrieved:
            return "low"
            
        top_score = max(r.get("score", 0.0) for r in retrieved)
        
        if mode == QueryMode.GENERAL:
            # High = README or Repository Metadata present
            has_strong = any(r.get("match_type") in ("readme", "repo_metadata", "manifest") for r in retrieved)
            if has_strong and len(retrieved) >= 2:
                return "high"
            return "medium"
            
        elif mode == QueryMode.CODE:
            # High = Exact match with score 1.0
            if any(r.get("match_type") in ("exact", "exact_match", "exact_match_ci") and r.get("score") >= 0.95 for r in retrieved):
                return "high"
            if top_score >= 0.8:
                return "medium"
            return "low"
            
        elif mode == QueryMode.IMPACT:
            # High = Resolved line + dependency evidence
            has_resolved = bool(line_meta.get("found"))
            has_graph = any(r.get("chunk_type") == "dependency" for r in retrieved)
            if has_resolved and has_graph:
                return "high"
            if has_resolved or has_graph:
                return "medium"
            if top_score >= 0.8:
                return "medium"
            return "low"
            found = line_meta.get("found", False)
            has_deps = any(r.get("match_type") == "impact_dependency" for r in retrieved)
            if found and has_deps:
                return "high"
            if found or has_deps:
                return "medium"
            return "low"
            
        return "medium"


    def _retrieve_project_summary(self, repository) -> list[dict]:
        """
        Generalized, hierarchy-enforced repo-intelligence evidence gathering.
        Priority: RepoIntelligence > Stored Metadata > README/Docs > Manifests > Entrypoints.
        """
        _NOISE_PATTERNS = [
            ".gitignore", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
            "node_modules", "dist/", ".next/", "build/", "coverage/", "vendor/",
            "__pycache__", ".pyc", ".min.js", ".map", ".lock",
        ]

        def _is_noisy(path: str) -> bool:
            p = path.lower()
            return any(n in p for n in _NOISE_PATTERNS)

        results: list[dict] = []

        try:
            from app.db.models.repo_intelligence import RepoIntelligence
            intel_record = self.db.scalar(select(RepoIntelligence).where(RepoIntelligence.repository_id == repository.id))
            if intel_record:
                results.append({
                    "file_path": "REPO_INTELLIGENCE",
                    "snippet": (
                        f"REPO INTELLIGENCE ARTIFACT:\n"
                        f"Frameworks: {intel_record.frameworks}\n"
                        f"Build Tools: {intel_record.build_tools}\n"
                        f"Summary: {intel_record.repo_summary_text}\n"
                        f"Architecture: {intel_record.architecture_summary_text}\n"
                        f"Backend: {intel_record.backend_summary}\n"
                        f"Frontend: {intel_record.frontend_summary}\n"
                        f"Database: {intel_record.db_summary}\n"
                        f"Modules:\n{intel_record.module_map_text}\n"
                    ),
                    "score": 1.0,
                    "match_type": "repo_intelligence",
                })
        except Exception as e:
            logger.warning(f"Error fetching RepoIntelligence: {e}")

        # ── Tier 1: All stored repository metadata (normalized)
        meta_parts = []
        if getattr(repository, "name", None):
            meta_parts.append(f"Name: {repository.name}")
        if getattr(repository, "primary_language", None):
            meta_parts.append(f"Primary Language: {repository.primary_language}")
        # detected_languages is a comma-separated string or may be empty
        _det_langs = getattr(repository, "detected_languages", None) or ""
        if _det_langs and _det_langs.strip():
            meta_parts.append(f"Detected Languages: {_det_langs}")
        # detected_frameworks is a comma-separated string
        _det_fw = getattr(repository, "detected_frameworks", None) or ""
        if _det_fw and _det_fw.strip():
            meta_parts.append(f"Frameworks / Tools: {_det_fw}")
        # Legacy framework field (may or may not exist)
        _legacy_fw = getattr(repository, "framework", None)
        if _legacy_fw and _legacy_fw not in (_det_fw or ""):
            meta_parts.append(f"Framework: {_legacy_fw}")

        _total_files = getattr(repository, "total_files", None) or 0
        _total_syms = getattr(repository, "total_symbols", None) or 0
        if _total_files:
            meta_parts.append(f"Total Files Indexed: {_total_files}")
        if _total_syms:
            meta_parts.append(f"Total Symbols: {_total_syms}")
        if repository.status:
            meta_parts.append(f"Intelligence Status: {repository.status}")
        if getattr(repository, "summary", None):
            meta_parts.append(f"Repository Summary: {repository.summary}")

        # Always emit metadata block (even if sparse) so summary builder sees it
        results.append({
            "file_path": "REPO_METADATA",
            "snippet": "REPOSITORY METADATA:\n" + "\n".join(meta_parts) if meta_parts else "REPOSITORY METADATA: (no metadata stored yet)",
            "score": 1.0,
            "match_type": "repo_metadata",
        })

        # ── Tier 1b: File-type census from DB (fast aggregate)
        try:
            from sqlalchemy import func as sqlfunc, distinct
            from app.db.models.file import File as FileModel
            # Count files and gather extensions
            all_files = list(self.db.scalars(
                select(FileModel.path).where(
                    FileModel.repository_id == repository.id,
                    FileModel.content.is_not(None),
                )
            ).all())
            total_indexed = len(all_files)
            # Extension breakdown
            ext_counts: dict = {}
            for fp in all_files:
                ext = fp.rsplit(".", 1)[-1].lower() if "." in fp else "other"
                if len(ext) <= 6:
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1
            top_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:6]
            ext_str = ", ".join(f".{e} ({c})" for e, c in top_exts)
            # Find routes/pages/models/templates
            route_files = [p for p in all_files if any(x in p.lower() for x in ["route","router","api/v","controller","handler","view","page","endpoint"])]
            model_files = [p for p in all_files if any(x in p.lower() for x in ["/model","schema","entity","orm","db/"])]
            census_parts = [
                f"Total files indexed: {total_indexed}",
                f"File types: {ext_str or 'various'}",
                f"Detected routes/API files ({len(route_files)}): {', '.join(route_files[:5]) or 'none detected'}",
                f"Detected model/DB files ({len(model_files)}): {', '.join(model_files[:5]) or 'none detected'}",
            ]
            results.append({
                "file_path": "FILE_STRUCTURE_CENSUS",
                "snippet": "FILE STRUCTURE CENSUS:\n" + "\n".join(census_parts),
                "score": 0.99,
                "match_type": "structure_census",
            })
        except Exception as _census_err:
            logger.warning(f"file census failed: {_census_err}")

        # ── Tier 2: README and documentation (Top 5)
        readme_files = list(self.db.scalars(
            select(File).where(
                File.repository_id == repository.id,
                or_(
                    File.path.ilike("README%"),
                    File.path.ilike("%/README%"),
                    File.path.ilike("docs/index%"),
                    File.path.ilike("docs/README%"),
                )
            ).limit(5)
        ).all())
        for f in readme_files:
            if not _is_noisy(f.path):
                results.append({
                    "file_id": str(f.id),
                    "file_path": f.path,
                    "snippet": f"README CONTENT ({f.path}):\n{(f.content or '')[:3000]}",
                    "score": 0.98,
                    "match_type": "readme",
                })

        # ── Tier 3: Primary Manifests (Dependency Evidence)
        manifest_files = list(self.db.scalars(
            select(File).where(
                File.repository_id == repository.id,
                or_(
                    File.path == "package.json",
                    File.path == "requirements.txt",
                    File.path == "pyproject.toml",
                    File.path == "go.mod",
                    File.path == "pom.xml",
                    File.path == "build.gradle",
                    File.path == "Cargo.toml",
                    File.path == "Pipfile",
                    # Nested monorepo manifests
                    File.path.ilike("%/requirements.txt"),
                    File.path.ilike("%/pyproject.toml"),
                    File.path.ilike("%/package.json"),
                    File.path.ilike("%requirements-dev.txt"),
                )
            ).limit(8)
        ).all())
        for f in manifest_files:
            results.append({
                "file_id": str(f.id),
                "file_path": f.path,
                "snippet": f"PROJECT MANIFEST ({f.path}):\n{(f.content or '')[:2000]}",
                "score": 0.95,
                "match_type": "manifest",
            })

        # ── Tier 4: App Entrypoints / Bootstrap files
        entrypoint_files = list(self.db.scalars(
            select(File).where(
                File.repository_id == repository.id,
                or_(
                    File.path.ilike("main.py"),
                    File.path.ilike("app.py"),
                    File.path.ilike("index.js"),
                    File.path.ilike("index.html"),
                    File.path.ilike("index.ejs"),
                    File.path.ilike("server.js"),
                    File.path.ilike("manage.py"),
                    File.path.ilike("App.tsx"),
                    File.path.ilike("main.tsx"),
                    File.path.ilike("next.config.js"),
                )
            ).limit(10)
        ).all())
        for f in entrypoint_files:
            if not _is_noisy(f.path):
                results.append({
                    "file_id": str(f.id),
                    "file_path": f.path,
                    "snippet": f"ENTRYPOINT CODE ({f.path}):\n{(f.content or '')[:1500]}",
                    "score": 0.92,
                    "match_type": "entrypoint",
                })

        # ── Tier 5: Route / API / Page files (surface user-facing features)
        try:
            route_like = list(self.db.scalars(
                select(File).where(
                    File.repository_id == repository.id,
                    or_(
                        File.path.ilike("%/routes%"),
                        File.path.ilike("%/router%"),
                        File.path.ilike("%/api/v%"),
                        File.path.ilike("%/pages/%"),
                        File.path.ilike("%/views/%"),
                        File.path.ilike("%/controllers/%"),
                        File.path.ilike("%/handlers/%"),
                    )
                ).limit(6)
            ).all())
            for f in route_like:
                if not _is_noisy(f.path):
                    results.append({
                        "file_id": str(f.id),
                        "file_path": f.path,
                        "snippet": f"ROUTE/API FILE ({f.path}):\n{(f.content or '')[:800]}",
                        "score": 0.88,
                        "match_type": "route_file",
                    })
        except Exception as _route_err:
            logger.warning(f"route file fetch failed: {_route_err}")

        # ── Tier 6: Model/Schema/DB files (surface data layer)
        try:
            model_like = list(self.db.scalars(
                select(File).where(
                    File.repository_id == repository.id,
                    or_(
                        File.path.ilike("%/models/%"),
                        File.path.ilike("%/schemas/%"),
                        File.path.ilike("%/db/models%"),
                        File.path.ilike("%/entities/%"),
                        File.path.ilike("%/orm/%"),
                    )
                ).limit(6)
            ).all())
            for f in model_like:
                if not _is_noisy(f.path):
                    results.append({
                        "file_id": str(f.id),
                        "file_path": f.path,
                        "snippet": f"DATA MODEL ({f.path}):\n{(f.content or '')[:600]}",
                        "score": 0.85,
                        "match_type": "model_file",
                    })
        except Exception as _model_err:
            logger.warning(f"model file fetch failed: {_model_err}")

        # ── Tier 7: CSV/Data file samples (for data-driven projects)
        try:
            data_files = list(self.db.scalars(
                select(File).where(
                    File.repository_id == repository.id,
                    or_(
                        File.path.ilike("%.csv"),
                        File.path.ilike("%.tsv"),
                        File.path.ilike("%.json"),
                    )
                ).limit(3)
            ).all())
            for f in data_files:
                if not _is_noisy(f.path) and f.content:
                    lines = f.content.splitlines()
                    sample = "\n".join(lines[:10])
                    results.append({
                        "file_id": str(f.id),
                        "file_path": f.path,
                        "snippet": f"DATA SAMPLE ({f.path}):\n{sample}",
                        "score": 0.82,
                        "match_type": "data_sample",
                    })
        except Exception as _data_err:
            logger.warning(f"data file fetch failed: {_data_err}")

        return results


    # ------------------------------------------------------------------
    # Dependency / Config impact retrieval
    # ------------------------------------------------------------------

    def _retrieve_dependency_impact(
        self,
        repository_id: str,
        package: str,
        manifest_file: str = "",
    ) -> list[dict]:
        """
        Gathers evidence for dependency deletion impact:
          - The manifest file(s) containing the package
          - Source files importing or using the package
          - Any config/bootstrap files referencing it
        """
        results: list[dict] = []
        if not package:
            return results

        # Normalize: "flask[async]" -> "flask", "python-dotenv" -> "dotenv"
        pkg_norm = re.sub(r"[\[\]<>=!~].*", "", package).strip()
        pkg_import = pkg_norm.replace("-", "_").lower()

        _MANIFEST_PATTERNS = [
            "requirements.txt", "requirements-dev.txt", "pyproject.toml",
            "pipfile", "package.json", "pnpm-lock.yaml", "yarn.lock",
            "package-lock.json", "go.mod", "cargo.toml",
        ]

        # ── Find manifest files that mention this package
        try:
            manifest_files = list(self.db.scalars(
                select(File).where(
                    File.repository_id == repository_id,
                    or_(*[File.path.ilike(f"%{m}") for m in _MANIFEST_PATTERNS]),
                    File.content.ilike(f"%{pkg_norm}%"),
                ).limit(4)
            ).all())
            for mf in manifest_files:
                # Find the line with the package
                lines = (mf.content or "").splitlines()
                matched_line, line_no = "", 0
                for i, l in enumerate(lines):
                    if pkg_norm.lower() in l.lower():
                        matched_line = l.strip()
                        line_no = i + 1
                        break
                results.append({
                    "file_id": str(mf.id),
                    "file_path": mf.path,
                    "start_line": max(1, line_no - 2),
                    "end_line": line_no + 2,
                    "snippet": (
                        f"DEPENDENCY MANIFEST: {mf.path}\n"
                        f"Package declaration (line {line_no}): {matched_line}\n"
                        f"Context: {chr(10).join(lines[max(0,line_no-3):line_no+3])}"
                    ),
                    "score": 1.0,
                    "match_type": "dependency_manifest",
                })
        except Exception as e:
            logger.warning(f"dependency manifest search failed: {e}")

        # ── Find source files importing / using this package
        try:
            _import_terms = [pkg_import, pkg_norm, pkg_import.replace("_", "-")]
            import_files = []
            for term in _import_terms:
                if len(term) < 3:
                    continue
                hits = list(self.db.scalars(
                    select(File).where(
                        File.repository_id == repository_id,
                        or_(
                            File.content.ilike(f"%import {term}%"),
                            File.content.ilike(f"%from {term}%"),
                            File.content.ilike(f"%require('{term}%"),
                            File.content.ilike(f"%require(\"{term}%"),
                        )
                    ).limit(6)
                ).all())
                import_files.extend(hits)
                if import_files:
                    break

            # Deduplicate
            seen = set()
            for sf in import_files:
                if sf.id in seen:
                    continue
                seen.add(sf.id)
                lines = (sf.content or "").splitlines()
                import_lines = [
                    (i+1, l.strip()) for i, l in enumerate(lines)
                    if pkg_import in l.lower() or pkg_norm in l.lower()
                ][:5]
                usage_text = "\n".join(f"  line {n}: {l}" for n, l in import_lines)
                results.append({
                    "file_id": str(sf.id),
                    "file_path": sf.path,
                    "start_line": import_lines[0][0] if import_lines else 1,
                    "end_line": import_lines[-1][0] if import_lines else 10,
                    "snippet": (
                        f"PACKAGE USAGE IN: {sf.path}\n"
                        f"Import/usage lines:\n{usage_text}"
                    ),
                    "score": 0.92,
                    "match_type": "dependency_usage",
                })
        except Exception as e:
            logger.warning(f"dependency usage search failed: {e}")

        return results

    def _retrieve_route_feature_impact(
        self,
        repository_id: str,
        feature: str,
    ) -> list[dict]:
        """Best-effort mapping of a natural-language feature noun to route/handler/page files."""
        results: list[dict] = []
        if not feature:
            return results

        search_terms = feature.lower().split()[:3]  # e.g. ["login", "route"]
        seen: set = set()

        for term in search_terms:
            if len(term) < 3:
                continue
            try:
                hits = list(self.db.scalars(
                    select(File).where(
                        File.repository_id == repository_id,
                        or_(
                            File.path.ilike(f"%{term}%"),
                            File.content.ilike(f"%{term}%"),
                        )
                    ).limit(4)
                ).all())
                for h in hits:
                    if h.id in seen:
                        continue
                    seen.add(h.id)
                    # Find the most relevant line
                    lines = (h.content or "").splitlines()
                    best_line, best_no = "", 0
                    for i, l in enumerate(lines):
                        if term in l.lower():
                            best_line = l.strip()
                            best_no = i + 1
                            break
                    results.append({
                        "file_id": str(h.id),
                        "file_path": h.path,
                        "start_line": max(1, best_no - 3),
                        "end_line": best_no + 5,
                        "snippet": (
                            f"FEATURE MATCH: {h.path}\n"
                            f"Best matching line ({best_no}): {best_line}\n"
                            f"Context:\n{chr(10).join(lines[max(0,best_no-3):best_no+5])}"
                        ),
                        "score": 0.85,
                        "match_type": "route_feature_match",
                    })
            except Exception as e:
                logger.warning(f"route feature search failed for {term!r}: {e}")

        return results[:8]


    def _retrieve_code_snippet(self, repository_id: str, snippet: str, is_explicit_impact: bool = False) -> list[dict]:
        """Lexical search for a code snippet across all indexed files.

        Progressive fallback strategy:
          1. Full snippet ilike match
          2. Last significant token (e.g., function/symbol name) ilike match
          3. Any keyword from the snippet (first 4 non-trivial words) -- DISABLED for explicit impact
        Filters noisy lock/generated files and prioritizes source code.
        """
        # ── Helpers ──────────────────────────────────────────────────────────
        _NOISE_PATHS = (
            "lock.yaml", "lock.json", "-lock.", "pnpm-lock", "yarn.lock",
            "package-lock", "node_modules", ".next", "dist/", "build/",
            "__pycache__", ".pyc", ".min.js", ".map",
            # Note: specific filenames like test_prompt.py / test_gemini.py are already
            # caught by the generic "test_" prefix pattern above — no repo-specific names needed.
        )
        # Source code extensions to prioritize
        _SOURCE_EXTS = {
            ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", 
            ".go", ".rs", ".rb", ".php", ".cs", ".swift", ".kt", ".m", ".scala"
        }

        def _is_noisy(path: str) -> bool:
            pl = path.lower()
            return any(n in pl for n in _NOISE_PATHS)

        def _search_term(term: str, limit: int = 5) -> list:
            # Over-fetch but prioritize source extensions in the result sort
            candidates = list(self.db.scalars(
                select(File).where(
                    File.repository_id == repository_id,
                    File.content.ilike(f"%{term}%"),
                ).limit(limit * 5)
            ).all())
            
            # Sort: Priority 1 = Source files, Priority 2 = others
            def sort_key(f):
                ext = "." + f.path.rsplit(".", 1)[-1].lower() if "." in f.path else ""
                is_source = 1 if ext in _SOURCE_EXTS else 0
                return (-is_source, f.path)
            
            return sorted(candidates, key=sort_key)

        def _filter(files: list) -> list:
            return [f for f in files if not _is_noisy(f.path)]

        # ── Term preparation ──────────────────────────────────────────────────
        term = snippet.strip()
        if not term:
            return []
        if len(term) > 200:
            term = term[:200]

        # ── Search tier 1: full snippet ───────────────────────────────────────
        files = _filter(_search_term(term))

        # ── Search tier 2: last significant identifier ────────────────────────
        if not files:
            # Extract the rightmost identifier-like token (e.g., "get_settings" from import)
            tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", term)
            # Filter trivial tokens
            stopwords = {"from", "import", "class", "def", "public", "private", "async", "export", "return", "the", "and"}
            meaningful = [t for t in tokens if t.lower() not in stopwords]
            if meaningful:
                # Try longest meaningful token first
                for token in sorted(meaningful, key=len, reverse=True)[:3]:
                    files = _filter(_search_term(token))
                    if files:
                        logger.debug(f"snippet search tier 2 hit: token={token!r}")
                        break

        # ── Search tier 3: any word in snippet (DISABLED for explicit impact) ──
        if not files and not is_explicit_impact:
            words = [w.strip(".,;:()[]{}") for w in term.split() if len(w) >= 4]
            for w in words[:4]:
                files = _filter(_search_term(w))
                if files:
                    logger.debug(f"snippet search tier 3 hit: word={w!r}")
                    break
        
        results = []
        for file in files:
            # Find exact line number to provide context
            content = file.content or ""
            lines = content.splitlines()
            line_no = 1
            for i, line in enumerate(lines):
                if term.lower() in line.lower():
                    line_no = i + 1
                    break
                    
            start_line = max(1, line_no - 5)
            end_line = line_no + 5
            context = "\n".join(lines[start_line - 1:end_line])
            
            results.append({
                "file_id": str(file.id),
                "file_path": file.path,
                "start_line": start_line,
                "end_line": end_line,
                "snippet": f"Found matching snippet at line {line_no}:\n{context}",
                "match_type": "snippet_match",
                "score": 1.0,
            })
            
            # Use self._retrieve_line_impact conditionally to fetch dependents if possible
            # Just fetch the symbol
            symbol = self.db.scalars(
                select(Symbol).where(
                    Symbol.file_id == file.id,
                    Symbol.start_line <= line_no,
                    Symbol.end_line >= line_no
                )
            ).first()
            
            if symbol:
                results.append({
                    "file_id": None,
                    "file_path": file.path,
                    "snippet": f"Snippet is inside symbol: {symbol.name}. Summary: {symbol.summary or 'N/A'}",
                    "match_type": "impact_symbol",
                    "score": 0.95,
                })
        
        return results

    def _retrieve_line_impact_v2(
        self,
        repository_id: str,
        classification: dict,
        question: str,
    ) -> tuple[list[dict], dict]:
        """
        Full true line-level impact retrieval.
        Returns (evidence_list, line_metadata_dict).
        """
        resolver = LineResolver(self.db)
        # For LINE_CHANGE_IMPACT, use old_text as snippet if no explicit snippet given
        effective_snippet = classification.get("snippet") or classification.get("old_text") or None
        res = resolver.resolve(
            repository_id=repository_id,
            file_hint=classification.get("file", ""),
            line_no=classification.get("line"),
            snippet=effective_snippet,
        )

        if not res or not res.get("found"):
            # --- Rename fallback: even if full snippet not found, try finding the symbol by name ---
            symbol_name = classification.get("symbol_name")
            if symbol_name and classification.get("operation") == "rename":
                # Try to find any file containing the symbol
                candidates = list(self.db.scalars(
                    select(File).where(
                        File.repository_id == repository_id,
                        File.content.ilike(f"% {symbol_name} %"),
                    ).limit(3)
                ).all())
                # Try via Symbol table too
                sym_candidates = list(self.db.scalars(
                    select(Symbol).where(
                        Symbol.repository_id == repository_id,
                        Symbol.name == symbol_name,
                    ).limit(3)
                ).all())
                if sym_candidates:
                    # Prefer symbol table result
                    sym = sym_candidates[0]
                    file_rec = self.db.get(File, sym.file_id)
                    if file_rec:
                        refs = self._scan_same_file_references(
                            file_rec.content or "", symbol_name, sym.start_line
                        )
                        lang = self._infer_language(file_rec.path)
                        rename_analysis = {
                            "symbol_name": symbol_name,
                            "new_name": classification.get("new_name", classification.get("new_text", "")),
                            "declaration_line": sym.start_line,
                            "same_file_references": refs,
                            "declaration_only_rename_breaks": len(refs) > 0,
                            "full_rename_safe": True,
                            "language": lang,
                            "error_if_partial": (
                                f"error: cannot find symbol: {symbol_name}"
                                if lang == "java" else
                                f"NameError: name '{symbol_name}' is not defined"
                            ),
                        }
                        meta = {
                            "found": True,
                            "file_path": file_rec.path,
                            "line_no": sym.start_line,
                            "line_text": (file_rec.content or "").splitlines()[sym.start_line - 1]
                                if sym.start_line <= len((file_rec.content or "").splitlines()) else "",
                            "line_type": "assignment",
                            "enclosing_symbol": f"{sym.name} ({sym.symbol_type})",
                            "rename_analysis": rename_analysis,
                        }
                        ev = [{
                            "file_id": str(file_rec.id),
                            "file_path": file_rec.path,
                            "start_line": max(1, sym.start_line - 5),
                            "end_line": sym.start_line + 5,
                            "snippet": (
                                f"FILE: {file_rec.path}\n"
                                f"SYMBOL '{symbol_name}' declared at line {sym.start_line} "
                                f"(type={sym.symbol_type})\n"
                                f"SAME-FILE REFERENCES AFTER DECLARATION ({len(refs)}):\n"
                                + "\n".join(f"  line {r['line_no']}: {r['line_text']}" for r in refs)
                            ),
                            "match_type": "rename_analysis",
                            "score": 1.0,
                        }]
                        return ev, meta
                elif candidates:
                    file_rec = candidates[0]
                    # Find the declaration line for symbol_name
                    decl_line = LineResolver._find_snippet_line(
                        file_rec.content or "", symbol_name
                    )
                    if decl_line:
                        refs = self._scan_same_file_references(
                            file_rec.content or "", symbol_name, decl_line
                        )
                        lang = self._infer_language(file_rec.path)
                        rename_analysis = {
                            "symbol_name": symbol_name,
                            "new_name": classification.get("new_name", classification.get("new_text", "")),
                            "declaration_line": decl_line,
                            "same_file_references": refs,
                            "declaration_only_rename_breaks": len(refs) > 0,
                            "full_rename_safe": True,
                            "language": lang,
                            "error_if_partial": (
                                f"error: cannot find symbol: {symbol_name}"
                                if lang == "java" else
                                f"NameError: name '{symbol_name}' is not defined"
                            ),
                        }
                        decl_text = (file_rec.content or "").splitlines()[decl_line - 1] \
                            if decl_line <= len((file_rec.content or "").splitlines()) else ""
                        meta = {
                            "found": True,
                            "file_path": file_rec.path,
                            "line_no": decl_line,
                            "line_text": decl_text,
                            "line_type": "assignment",
                            "enclosing_symbol": "unknown",
                            "rename_analysis": rename_analysis,
                        }
                        ev = [{
                            "file_id": str(file_rec.id),
                            "file_path": file_rec.path,
                            "start_line": max(1, decl_line - 5),
                            "end_line": decl_line + 5,
                            "snippet": (
                                f"FILE: {file_rec.path}\n"
                                f"DECLARATION of '{symbol_name}' found at line {decl_line}: {decl_text}\n"
                                f"SAME-FILE REFERENCES AFTER DECLARATION ({len(refs)}):\n"
                                + "\n".join(f"  line {r['line_no']}: {r['line_text']}" for r in refs)
                            ),
                            "match_type": "rename_analysis",
                            "score": 1.0,
                        }]
                        return ev, meta

            # No resolution at all — return empty evidence
            return [], {"found": False, "file_hint": classification.get("file", "")}

        file_record = res["file_record"]
        line_no = res["line_no"]
        line_text = res["line_text"]
        line_type = res["line_type"]
        enclosing = res["enclosing_symbol"]
        symbol = res.get("symbol_record")

        # ── Rename analysis (for rename/change operations)
        rename_analysis: dict | None = None
        if classification.get("operation") == "rename":
            symbol_name = classification.get("symbol_name", "")
            new_name = classification.get("new_name", classification.get("new_text", ""))
            if symbol_name:
                refs = self._scan_same_file_references(
                    file_record.content or "", symbol_name, line_no
                )
                lang = self._infer_language(file_record.path)
                rename_analysis = {
                    "symbol_name": symbol_name,
                    "new_name": new_name,
                    "declaration_line": line_no,
                    "same_file_references": refs,
                    "declaration_only_rename_breaks": len(refs) > 0,
                    "full_rename_safe": True,
                    "language": lang,
                    "error_if_partial": (
                        f"error: cannot find symbol: {symbol_name}"
                        if lang == "java" else
                        f"NameError: name '{symbol_name}' is not defined"
                    ),
                }
                # Add a dedicated rename evidence block
                rename_ev_text = (
                    f"RENAME ANALYSIS for symbol '{symbol_name}' -> '{new_name}'\n"
                    f"Declaration at line {line_no}: {line_text}\n"
                    f"Same-file references after declaration ({len(refs)}):\n"
                    + ("\n".join(f"  line {r['line_no']}: {r['line_text']}" for r in refs)
                       if refs else "  (none found — rename may be safe)")
                )

        # ── Evidence block 1: exact line + broad context
        context_snippet = (
            f"FILE: {res['file_path']}\n"
            f"TARGET LINE {line_no}: {line_text}\n"
            f"ENCLOSING SCOPE: {enclosing}\n"
            f"LINE TYPE: {line_type}\n\n"
            f"--- Context before ---\n{res['context_before']}\n"
            f"--- Target line ---\n{line_no}: {line_text}\n"
            f"--- Context after ---\n{res['context_after']}"
        )
        if rename_analysis:
            refs = rename_analysis.get("same_file_references", [])
            context_snippet += (
                f"\n\n--- RENAME ANALYSIS ---\n"
                f"Symbol '{rename_analysis['symbol_name']}' declared at line {rename_analysis['declaration_line']}\n"
                f"References to '{rename_analysis['symbol_name']}' after declaration ({len(refs)}):\n"
                + ("\n".join(f"  line {r['line_no']}: {r['line_text']}" for r in refs)
                   if refs else "  (none found in this file)")
            )

        evidence = [{
            "file_id": res["file_id"],
            "file_path": res["file_path"],
            "start_line": max(1, line_no - 8),
            "end_line": line_no + 8,
            "snippet": context_snippet,
            "match_type": "impact_target",
            "score": 1.0,
        }]

        # ── Evidence block 2: enclosing symbol details
        if symbol:
            evidence.append({
                "file_path": res["file_path"],
                "snippet": (
                    f"ENCLOSING SYMBOL: {symbol.name} (type={symbol.symbol_type})\n"
                    f"Summary: {symbol.summary or 'N/A'}\n"
                    f"Lines: {symbol.start_line}–{symbol.end_line}"
                ),
                "match_type": "impact_symbol",
                "score": 0.95,
            })

            # ── Evidence block 3: caller / usage graph
            try:
                callers = self.graph_service.get_symbol_usage(repository_id, symbol.name)
                for c in callers[:5]:
                    caller_file = self.db.get(File, c.source_file_id)
                    fp = caller_file.path if caller_file else f"file_id={c.source_file_id}"
                    evidence.append({
                        "file_id": str(c.source_file_id) if c.source_file_id else None,
                        "file_path": fp,
                        "snippet": f"Symbol '{symbol.name}' is used in {fp} via {c.edge_type}",
                        "match_type": "impact_dependency",
                        "score": 0.85,
                    })
            except Exception as e:
                logger.warning(f"graph symbol_usage failed: {e}")

        # ── Evidence block 4: file importers (dependency graph)
        try:
            importers = self.graph_service.get_incoming_dependencies(file_record.id)
            for imp in importers[:5]:
                src_file = self.db.get(File, imp.source_file_id)
                if src_file:
                    evidence.append({
                        "file_id": str(src_file.id),
                        "file_path": src_file.path,
                        "snippet": f"File '{res['file_path']}' is imported/used by '{src_file.path}'",
                        "match_type": "impact_dependency",
                        "score": 0.80,
                    })
        except Exception as e:
            logger.warning(f"graph incoming_dependencies failed: {e}")

        # ── Evidence block 5: for change-impact, check if replacement symbol exists
        intent = classification.get("intent")
        if intent == QueryIntent.LINE_CHANGE_IMPACT and classification.get("operation") != "rename":
            new_text = classification.get("new_text", "")
            if new_text:
                new_sym = self.db.scalars(
                    select(Symbol).where(
                        Symbol.repository_id == repository_id,
                        Symbol.name.ilike(f"%{new_text.split('.')[-1]}%"),
                    ).limit(3)
                ).all()
                if new_sym:
                    for ns in new_sym:
                        evidence.append({
                            "file_path": "replacement_symbol_found",
                            "snippet": (
                                f"REPLACEMENT CHECK: '{new_text}' matches symbol '{ns.name}' "
                                f"({ns.symbol_type}) in repo. Replacement may be valid."
                            ),
                            "match_type": "replacement_found",
                            "score": 0.9,
                        })
                else:
                    evidence.append({
                        "file_path": "replacement_symbol_not_found",
                        "snippet": (
                            f"REPLACEMENT CHECK: '{new_text}' NOT found as any symbol in the repository. "
                            f"Replacing would likely cause NameError / AttributeError at runtime."
                        ),
                        "match_type": "replacement_missing",
                        "score": 0.9,
                    })

        # Clean up non-serializable fields before returning metadata
        line_metadata = {k: v for k, v in res.items() if k not in ("file_record", "symbol_record")}
        if rename_analysis:
            line_metadata["rename_analysis"] = rename_analysis
        return evidence, line_metadata

    @staticmethod
    def _scan_same_file_references(content: str, symbol_name: str, declaration_line: int) -> list[dict]:
        """
        Scans a file for all references to `symbol_name` after the declaration line.
        Uses word-boundary matching to avoid false positives (e.g. 'heading' vs 'headingLabel').
        Returns a list of {line_no, line_text} dicts.
        """
        import re as _re
        pattern = _re.compile(r"\b" + _re.escape(symbol_name) + r"\b")
        results = []
        for i, line in enumerate(content.splitlines(), start=1):
            if i <= declaration_line:
                continue  # skip declaration line and anything before it
            if pattern.search(line):
                stripped = line.strip()
                # Skip blank lines, comment-only lines
                if stripped and not stripped.startswith("//") and not stripped.startswith("#"):
                    results.append({"line_no": i, "line_text": stripped})
        return results

    @staticmethod
    def _infer_language(file_path: str) -> str:
        """Infers programming language from file extension."""
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        return {
            "java": "java", "py": "python", "js": "javascript",
            "ts": "typescript", "jsx": "javascript", "tsx": "typescript",
            "cs": "csharp", "cpp": "cpp", "c": "c", "go": "go",
            "rb": "ruby", "php": "php", "kt": "kotlin", "rs": "rust",
        }.get(ext, "unknown")

    # (Legacy stub kept for backward compat - now unused)
    def _retrieve_line_impact(self, repository_id: str, file_path_sub: str, line_no: int) -> list[dict]:
        evidence, _ = self._retrieve_line_impact_v2(
            repository_id,
            {"file": file_path_sub, "line": line_no, "snippet": None, "intent": QueryIntent.LINE_IMPACT},
            f"line {line_no} in {file_path_sub}",
        )
        return evidence



    def _retrieve_file_impact(self, repository_id: str, file_path_sub: str) -> list[dict]:
        file_record = self.db.scalar(
            select(File).where(File.repository_id == repository_id, File.path.ilike(f"%{file_path_sub}%"))
        )
        if not file_record:
            return []

        results = [{
            "file_id": file_record.id,
            "file_path": file_record.path,
            "snippet": f"FILE IMPACT TARGET: {file_record.path}. Summary: {file_record.summary or 'N/A'}",
            "score": 1.0,
            "match_type": "impact_target"
        }]

        # Who imports this file?
        importers = self.graph_service.get_incoming_dependencies(file_record.id)
        for imp in importers[:8]:
            # Load the source file path
            src_file = self.db.get(File, imp.source_file_id)
            if src_file:
                results.append({
                    "file_id": src_file.id,
                    "file_path": src_file.path,
                    "snippet": f"This file is imported/used by {src_file.path}",
                    "score": 0.9,
                    "match_type": "impact_dependency"
                })
        
        return results

    def _retrieve_dependency_trace(self, repository_id: str, target_sub: str) -> list[dict]:
        # Similar to file impact but broader
        return self._retrieve_file_impact(repository_id, target_sub)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _keyword_file_search(
        self, repository_id: str, question: str, top_k: int = 8
    ) -> list[dict]:
        """
        Final fallback: keyword search directly over File.content and EmbeddingChunk.content.
        Works even if embeddings have never been run.
        """
        tokens = [
            t.strip("?.,!:;'\"`").lower()
            for t in question.split()
            if len(t) >= 3
        ]
        # Remove trivial stop words
        stop = {"the", "is", "are", "what", "how", "does", "did", "was", "for", "can", "this", "that", "and", "not"}
        tokens = [t for t in tokens if t not in stop]
        if not tokens:
            tokens = question.lower().split()[:3]

        results: list[dict] = []

        # Search EmbeddingChunk.content (exists post-embed)
        try:
            conds = [EmbeddingChunk.content.ilike(f"%{t}%") for t in tokens[:4]]
            rows = list(
                self.db.execute(
                    select(EmbeddingChunk, File.path)
                    .outerjoin(File, File.id == EmbeddingChunk.file_id)
                    .where(
                        EmbeddingChunk.repository_id == repository_id,
                        or_(*conds),
                    )
                    .limit(top_k)
                ).all()
            )
            for chunk_row, file_path in rows:
                results.append(
                    {
                        "chunk_id": chunk_row.id,
                        "file_id": chunk_row.file_id,
                        "file_path": file_path,
                        "score": 0.6,
                        "chunk_type": chunk_row.chunk_type,
                        "start_line": chunk_row.start_line,
                        "end_line": chunk_row.end_line,
                        "snippet": chunk_row.content[:1000],
                        "match_type": "keyword",
                    }
                )
        except Exception as e:
            logger.warning(f"chunk keyword search failed: {e}")

        # Search File.content directly (works right after parse / ingest)
        try:
            fconds = [File.content.ilike(f"%{t}%") for t in tokens[:4]]
            file_rows = list(
                self.db.scalars(
                    select(File).where(
                        File.repository_id == repository_id,
                        File.content.is_not(None),
                        or_(*fconds),
                    ).limit(top_k)
                ).all()
            )
            for f in file_rows:
                results.append(
                    {
                        "chunk_id": f"filecontent:{f.id}",
                        "file_id": f.id,
                        "file_path": f.path,
                        "score": 0.55,
                        "chunk_type": "file_content",
                        "start_line": 1,
                        "end_line": min((f.line_count or 1), 200),
                        "snippet": (f.content or "")[:1000],
                        "match_type": "file_keyword",
                    }
                )
        except Exception as e:
            logger.warning(f"file content keyword search failed: {e}")

        # If no keyword hits, return top files from this repo as last resort
        if not results:
            try:
                fallback_files = list(
                    self.db.scalars(
                        select(File).where(
                            File.repository_id == repository_id,
                            File.content.is_not(None),
                        ).limit(5)
                    ).all()
                )
                for f in fallback_files:
                    results.append(
                        {
                            "chunk_id": f"file:{f.id}",
                            "file_id": f.id,
                            "file_path": f.path,
                            "score": 0.3,
                            "chunk_type": "file_content",
                            "start_line": 1,
                            "end_line": min((f.line_count or 1), 200),
                            "snippet": (f.content or "")[:1000],
                            "match_type": "fallback",
                        }
                    )
            except Exception as e:
                logger.warning(f"fallback file fetch failed: {e}")

        return results[:top_k]

    def _build_citations(self, evidence: list[dict], max_citations: int = 5) -> list[dict]:
        """Build a deduplicated, score-filtered citation list for UI display."""
        seen_files: set[str] = set()
        citations = []
        # Sort by score desc so highest-quality evidence surfaces first
        sorted_ev = sorted(evidence, key=lambda x: x.get("score", 0), reverse=True)
        for item in sorted_ev:
            score = item.get("score", 0)
            fp = item.get("file_path") or ""
            # Skip very low-confidence items and synthetic/internal paths
            if score < 0.55:
                continue
            if fp in ("replacement_symbol_found", "replacement_symbol_not_found", "repository_intelligence"):
                continue
            citations.append({
                "file_id": item.get("file_id"),
                "file_path": fp,
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
                "matched_lines": item.get("matched_lines", []),
                "chunk_id": item.get("chunk_id") or f"{fp}:{item.get('start_line')}",
                "match_type": item.get("match_type", "semantic"),
            })
            if len(citations) >= max_citations:
                break
        return citations

    @staticmethod
    def _extract_symbol_from_question(question: str) -> str:
        patterns = [
            r"where is\s+([A-Za-z_][\w]*)\s+(?:used|defined|implemented|called)",
            r"usage of\s+([A-Za-z_][\w]*)",
            r"references of\s+([A-Za-z_][\w]*)",
            r"who calls\s+([A-Za-z_][\w]*)",
            r"where is\s+([A-Za-z_][\w]*)",
        ]
        for pat in patterns:
            m = re.search(pat, question, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    def _deterministic_answer(
        self, question: str, evidence: list[dict], intent: str = "general",
        line_metadata: dict | None = None, repository_id: str | None = None,
    ) -> tuple[str, str, list[str]]:
        """Build a non-LLM answer grounded in evidence. Returns plain text with no markdown symbols."""
        notes: list[str] = ["Deterministic answer generated directly from structural retrieval."]

        if not evidence:
            return (
                "The requested snippet or context was not found in the repository.\n\n"
                "Running in deterministic fallback mode (LLM unavailable). "
                "Ensure the code exists in the indexed repository, or enable Gemini for richer reasoning.",
                "low",
                ["No retrieval evidence."],
            )

        if intent in (QueryIntent.SYMBOL_LOOKUP, "symbol_lookup"):
            symbol = self._extract_symbol_from_question(question) or "the requested symbol"
            top = evidence[:8]
            locations = []
            for e in top:
                fp = e.get("file_path")
                if not fp:
                    continue
                sl = e.get("start_line")
                snippet = (e.get("snippet") or "").strip().splitlines()
                preview = " ".join(s.strip() for s in snippet[:1] if s.strip())[:140]
                if sl:
                    locations.append(f"{fp}:{sl} — {preview}" if preview else f"{fp}:{sl}")
                else:
                    locations.append(f"{fp} — {preview}" if preview else fp)
            unique_locations = list(dict.fromkeys(locations))[:5]
            location_text = "; ".join(unique_locations) if unique_locations else "No concrete usage location was extracted."
            answer = (
                f"{symbol} is used in multiple repository locations. "
                f"The strongest indexed matches are: {location_text}. "
                "These matches indicate where the symbol is declared or referenced in active code paths."
            )
            confidence = "high" if len(unique_locations) >= 2 else "medium"
            return answer, confidence, notes

        # -- Rename / variable change impact — structured plain-text analysis
        ra = (line_metadata or {}).get("rename_analysis")
        if ra and intent in ("line_change_impact", "line_impact"):
            symbol_name = ra.get("symbol_name", "")
            new_name = ra.get("new_name", "")
            decl_line = ra.get("declaration_line", "?")
            refs = ra.get("same_file_references", [])
            lang = ra.get("language", "unknown")
            error_msg = ra.get("error_if_partial", f"cannot find symbol: {symbol_name}")
            file_path = (line_metadata or {}).get("file_path", "unknown")
            confidence = "high" if refs is not None else "medium"

            sections: list[str] = []
            sections.append(f"Operation: rename '{symbol_name}' to '{new_name}'")
            sections.append(f"Resolved File: {file_path}")
            sections.append(f"Declaration Line: {decl_line}")
            sections.append(f"Language: {lang}")
            sections.append("")

            if refs:
                sections.append(
                    f"CASE A — Declaration-only rename (BREAKS):\n"
                    f"If you rename only the declaration on line {decl_line} but leave "
                    f"references unchanged, the compiler will report:\n"
                    f"  {error_msg}\n"
                    f"\nLines that still reference '{symbol_name}' ({len(refs)} found):"
                )
                for r in refs:
                    sections.append(f"  Line {r['line_no']}: {r['line_text']}")
                sections.append("")
                sections.append(
                    f"CASE B — Full consistent rename (SAFE):\n"
                    f"If you rename '{symbol_name}' to '{new_name}' on ALL {len(refs) + 1} lines "
                    f"(declaration + {len(refs)} references), this is a safe refactor with "
                    f"no functional or behavioral change."
                )
            else:
                sections.append(
                    f"No references to '{symbol_name}' found after line {decl_line} in this file.\n"
                    f"Renaming only the declaration appears safe — no same-file references break.\n"
                    f"Check cross-file usages if this symbol is public/exported."
                )

            sections.append("")
            sections.append(f"Confidence: {confidence.upper()}")

            key_files = list(dict.fromkeys(
                e.get("file_path", "unknown") for e in evidence if e.get("file_path")
            ))
            sections.append(f"Evidence from: {', '.join(key_files[:3])}")

            return "\n".join(sections), confidence, notes

        # -- DEPENDENCY_IMPACT — structured dependency deletion analysis
        if intent in (QueryIntent.DEPENDENCY_IMPACT, "dependency_impact"):
            pkg = (line_metadata or {}).get("package", "") or question
            top = evidence[:10]
            confidence = "high" if len(top) >= 3 else "medium"

            manifest_hits = [e for e in top if e.get("match_type") == "dependency_manifest"]
            usage_hits = [e for e in top if e.get("match_type") == "dependency_usage"]

            parts = ["Dependency Impact Analysis", "=" * 40, f"Package: {pkg}", ""]
            if manifest_hits:
                parts.append(f"Declared in {len(manifest_hits)} manifest(s):")
                for mh in manifest_hits:
                    parts.append(f"  - {mh.get('file_path')}")
                parts.append("")
            if usage_hits:
                parts.append(f"Used in {len(usage_hits)} source file(s):")
                for uh in usage_hits:
                    parts.append(f"  - {uh.get('file_path')}")
                parts.append("")

            parts.append("Impact Breakdown:")
            parts.append("  FRESH INSTALL / CI / DOCKER REBUILD:")
            if manifest_hits:
                parts.append(f"    Removing from manifest will cause `pip/npm install` to skip {pkg}.")
                parts.append("    On next environment rebuild, the package will not be installed.")
                parts.append("    Any import of this package will fail with ModuleNotFoundError / ImportError.")
            else:
                parts.append(f"    Package {pkg!r} not found in any manifest — may already be transitive dep.")
            parts.append("")
            parts.append("  ALREADY-RUNNING ENVIRONMENT:")
            parts.append("    Currently running processes are NOT affected immediately.")
            parts.append("    Impact occurs only on restart in a fresh environment without the package.")
            parts.append("")
            if usage_hits:
                parts.append(f"  STARTUP / RUNTIME RISK: HIGH")
                parts.append(f"    {len(usage_hits)} file(s) import this package. On restart in a cleaned environment,")
                parts.append(f"    they will fail at import time → service will not start.")
            else:
                parts.append("  STARTUP / RUNTIME RISK: LOW")
                parts.append("    No direct import usage found — package may be a dev/build-only dependency.")
            parts.append("")
            parts.append(f"Confidence: {confidence.upper()}")
            parts.append(f"Evidence: {len(top)} blocks (manifests + usage files)")
            return "\n".join(parts), confidence, ["Dependency impact analysis from manifest and usage evidence."]

        # -- ROUTE_FEATURE_IMPACT — natural-language route/feature deletion
        if intent in (QueryIntent.ROUTE_FEATURE_IMPACT, "route_feature_impact"):
            feature = (line_metadata or {}).get("feature", "") or question
            top = evidence[:8]
            confidence = "medium" if top else "low"
            key_files = list(dict.fromkeys(e.get("file_path","") for e in top if e.get("file_path")))

            parts = ["Route / Feature Impact Analysis", "=" * 40, f"Feature: {feature}", ""]
            if key_files:
                parts.append(f"Best-match files found ({len(key_files)}):")
                for fp in key_files[:5]:
                    e_for_file = next((e for e in top if e.get("file_path") == fp), {})
                    sl = e_for_file.get("start_line", "")
                    parts.append(f"  - {fp}" + (f" (around line {sl})" if sl else ""))
                parts.append("")
                parts.append("Likely Impact:")
                parts.append(f"  Deleting the '{feature}' feature/route will remove the associated")
                parts.append(f"  handler(s), UI page(s), or API endpoint(s) listed above.")
                parts.append("  Any client code or navigation that references this route will break.")
                parts.append("  Check for: links/hrefs, form actions, fetch/axios calls, and menu items")
                parts.append("  that point to this route — they will all require update.")
            else:
                parts.append(f"No matching route or page file found for feature: {feature!r}")
                parts.append("This may be a feature not yet indexed, or a non-standard path structure.")
                parts.append("Confidence is LOW — manual codebase inspection recommended.")
            parts.append(f"\nConfidence: {confidence.upper()}")
            return "\n".join(parts), confidence, ["Route/feature impact via structural file search."]

        # -- CONFIG_IMPACT — config/env/infra deletion
        if intent in (QueryIntent.CONFIG_IMPACT, "config_impact"):
            top = evidence[:6]
            confidence = "medium" if top else "low"
            key_files = list(dict.fromkeys(e.get("file_path","") for e in top if e.get("file_path")))
            parts = ["Config / Infrastructure Impact Analysis", "=" * 40]
            parts.append("Impact Breakdown:")
            parts.append("  ENV / CONFIG files: removing an entry can cause startup failure if the")
            parts.append("  application reads that key at boot time via os.environ / config.get.")
            parts.append("  Docker/Compose files: removing a service or directive affects container")
            parts.append("  orchestration on the next `docker compose up`.")
            if key_files:
                parts.append(f"\nMatched config files:")
                for fp in key_files[:4]:
                    parts.append(f"  - {fp}")
            parts.append(f"\nConfidence: {confidence.upper()}")
            return "\n".join(parts), confidence, ["Config impact analysis."]

        # -- REPO SUMMARY / ARCHITECTURE — conversational natural-language overview
        if intent in (QueryIntent.REPO_SUMMARY, QueryIntent.ARCHITECTURE_EXPLANATION):
            confidence = "high" if len(evidence) >= 3 else "medium"

            # ── Extract structured signals from evidence ──────────────────
            # Check if we have the full-repo intelligence artifact
            intel_snippet = next((e.get("snippet", "") for e in evidence if e.get("match_type") == "repo_intelligence"), "")
            
            if intel_snippet:
                # Parse out the fields for a clean output
                paras = []
                lines = intel_snippet.splitlines()
                fields = {}
                for line in lines:
                    if ": " in line:
                        k, v = line.split(": ", 1)
                        if v and v.lower() != "none" and v.strip():
                            fields[k] = v
                
                # Opening
                if fields.get("Summary"):
                    paras.append(fields["Summary"].replace("\\n", "\n"))
                else:
                    paras.append("This repository is a software project, but I don't have a detailed summary available.")
                    
                paras.append("")
                
                # Architecture
                if fields.get("Architecture"):
                    arch = fields['Architecture'].replace('\\n', '\n')
                    paras.append(f"**Architecture Overview:**\n{arch}")
                    paras.append("")
                    
                # Tech Stack
                techs = []
                if fields.get("Frameworks"): techs.append(f"Frameworks: {fields['Frameworks']}")
                if fields.get("Build Tools"): techs.append(f"Build Tools: {fields['Build Tools']}")
                if fields.get("Database"): techs.append(f"Database: {fields['Database']}")
                if techs:
                    paras.append("**Tech Stack:** " + " | ".join(techs))
                    paras.append("")
                    
                # Components
                if fields.get("Backend") or fields.get("Frontend"):
                    paras.append("**Components:**")
                    if fields.get("Backend"): paras.append(f"- Backend: {fields['Backend']}")
                    if fields.get("Frontend"): paras.append(f"- Frontend: {fields['Frontend']}")
                    paras.append("")
                    
                paras.append(f"Confidence: {confidence.upper()}")
                notes.append("Detailed RepoIntelligence artifact found and used for deterministic response.")
                return "\n".join(paras), confidence, notes

            # (Fallback if no RepoIntelligence artifact exists)
            repo_name = ""
            primary_language = ""
            frameworks: list[str] = []
            total_files = 0
            file_types_line = ""
            entrypoints: list[str] = []
            readme_text = ""
            repo_summary_stored = ""
            key_files: dict[str, str] = {}   # path -> role hint
            route_files: list[str] = []
            model_files: list[str] = []

            for e in evidence:
                mt = e.get("match_type", "")
                snippet = e.get("snippet", "") or ""
                fp = (e.get("file_path", "") or "").strip()

                if mt == "repo_metadata":
                    for ln in snippet.splitlines():
                        ln = ln.strip()
                        if ln.startswith("Name:"):
                            repo_name = ln.split(":", 1)[-1].strip()
                        elif ln.startswith("Primary Language:"):
                            primary_language = ln.split(":", 1)[-1].strip()
                        elif ln.startswith("Frameworks / Tools:") or ln.startswith("Framework:"):
                            fw = ln.split(":", 1)[-1].strip()
                            for _fw in fw.split(","):
                                _fw = _fw.strip()
                                if _fw and _fw.lower() not in ("none","unknown","not detected") and _fw not in frameworks:
                                    frameworks.append(_fw)
                        elif ln.startswith("Total Files Indexed:"):
                            try: total_files = int(ln.split(":", 1)[-1].strip())
                            except Exception: pass
                        elif ln.startswith("Repository Summary:"):
                            repo_summary_stored = ln.split(":", 1)[-1].strip()[:600]
                elif mt == "structure_census":
                    for ln in snippet.splitlines():
                        if "Total files indexed:" in ln:
                            try: total_files = int(ln.split(":")[-1].strip())
                            except Exception: pass
                        elif "File types:" in ln:
                            file_types_line = ln.split(":", 1)[-1].strip()
                        elif "Detected entrypoints:" in ln:
                            ep = ln.split(":", 1)[-1].strip()
                            if ep and ep != "none detected":
                                for _ep in ep.split(", "):
                                    if _ep and _ep not in entrypoints:
                                        entrypoints.append(_ep)
                elif mt == "readme":
                    if not readme_text and fp:
                        body = snippet.replace(f"DOCUMENTATION FILE: {fp}\n", "").strip()
                        readme_text = body[:800]
                elif mt == "entrypoint" and fp:
                    if fp not in entrypoints:
                        entrypoints.append(fp)
                    key_files[fp] = "application entry point"
                elif mt == "route_file" and fp:
                    route_files.append(fp)
                    key_files[fp] = "API route / page handler"
                elif mt == "model_file" and fp:
                    model_files.append(fp)
                    key_files[fp] = "data model"
                elif fp and fp not in key_files:
                    # Infer role from filename
                    _bn = fp.split("/")[-1].lower()
                    if "index" in _bn:
                        key_files[fp] = "main entry / index"
                    elif any(x in _bn for x in ("config", "setting", "env")):
                        key_files[fp] = "configuration"
                    elif any(x in _bn for x in ("package.json","requirements","go.mod","gemfile")):
                        key_files[fp] = "dependency manifest"
                    elif any(_bn.endswith(x) for x in (".css",".scss",".sass",".less")):
                        key_files[fp] = "stylesheet"
                    elif any(_bn.endswith(x) for x in (".md",".rst",".txt")):
                        key_files[fp] = "documentation"

            # ── Infer architecture from signals ───────────────────────────
            all_fps = " ".join(e.get("file_path","") for e in evidence)
            fw_str = " ".join(frameworks).lower()
            _is_next = "next.config" in all_fps or "/pages/" in all_fps
            _is_react = "react" in fw_str or ".jsx" in all_fps or ".tsx" in all_fps
            _is_static = ".html" in all_fps or ".css" in all_fps
            _is_ejs = ".ejs" in all_fps or ".hbs" in all_fps or ".njk" in all_fps
            _is_express = "express" in fw_str or ".ejs" in all_fps
            _is_fastapi = "fastapi" in fw_str or "routers/" in all_fps
            _is_flask = "flask" in fw_str
            _is_django = "django" in fw_str or "settings.py" in all_fps
            _is_node = ".js" in all_fps and ("node" in fw_str or "express" in fw_str or "package.json" in all_fps)
            _is_db = bool(model_files) or "sqlalchemy" in all_fps or "prisma" in all_fps or "mongoose" in all_fps
            _has_csv = ".csv" in all_fps
            _has_api = bool(route_files)

            arch_tags: list[str] = []
            if _is_next: arch_tags.append("Next.js")
            elif _is_react: arch_tags.append("React")
            elif _is_ejs or _is_express: arch_tags.append("Express / Node.js")
            elif _is_static and not _is_express: arch_tags.append("static web app")
            if _is_fastapi: arch_tags.append("FastAPI")
            if _is_flask: arch_tags.append("Flask")
            if _is_django: arch_tags.append("Django")
            if _is_node and not arch_tags: arch_tags.append("Node.js")
            if _is_db: arch_tags.append("database-backed")
            if _has_csv: arch_tags.append("data-driven (CSV/data files)")
            if frameworks:
                for fw in frameworks[:4]:
                    if fw.lower() not in " ".join(arch_tags).lower():
                        arch_tags.append(fw)

            arch_desc = ", ".join(arch_tags) if arch_tags else "general-purpose application"
            lang_str = primary_language if primary_language else (frameworks[0] if frameworks else "Unknown")

            # ── Scale label ───────────────────────────────────────────────
            if total_files <= 5: scale = "a small starter or demo project"
            elif total_files <= 20: scale = "a small project"
            elif total_files <= 80: scale = "a mid-size project"
            else: scale = "a production-scale project"

            # ── Build conversational natural-language answer ───────────────
            paras: list[str] = []

            # Opening paragraph — synthesized from metadata + README
            _name_label = f"**{repo_name}**" if repo_name else "This repository"
            if repo_summary_stored:
                paras.append(f"{_name_label} — {repo_summary_stored}")
            elif readme_text:
                # Extract first real paragraph from README (skip headings/badges)
                _readme_lines = [l for l in readme_text.splitlines()
                                 if l.strip() and not l.strip().startswith("#")
                                 and not l.strip().startswith("[![")]
                _readme_intro = " ".join(_readme_lines[:3]).strip()[:400]
                if _readme_intro:
                    paras.append(f"{_name_label} is {_readme_intro}")
                else:
                    paras.append(f"{_name_label} is {scale} built with {arch_desc}.")
            else:
                paras.append(f"{_name_label} is {scale} built with {arch_desc}.")

            paras.append("")

            # Tech stack line
            tech_line = f"**Tech Stack:** {lang_str}"
            if frameworks:
                tech_line += f" · {', '.join(frameworks[:5])}"
            if file_types_line:
                tech_line += f"  |  File types: {file_types_line}"
            if total_files:
                tech_line += f"  |  {total_files} files indexed"
            paras.append(tech_line)
            paras.append("")

            # Key files section
            if key_files or entrypoints:
                paras.append("**Key files and their roles:**")
                shown = set()
                for ep in entrypoints[:3]:
                    role = key_files.get(ep, "entry point")
                    paras.append(f"- `{ep}` — {role}")
                    shown.add(ep)
                for fp_kf, role_kf in list(key_files.items())[:8]:
                    if fp_kf not in shown:
                        paras.append(f"- `{fp_kf}` — {role_kf}")
                        shown.add(fp_kf)
                        if len(shown) >= 7:
                            break
                paras.append("")

            # Route/API surface
            if route_files:
                paras.append(f"**API / Routes ({len(route_files)} files):** " +
                              ", ".join(f"`{r.split('/')[-1]}`" for r in route_files[:4]))
                paras.append("")

            # Data models
            if model_files:
                paras.append(f"**Data Models ({len(model_files)} files):** " +
                              ", ".join(f"`{m.split('/')[-1]}`" for m in model_files[:4]))
                paras.append("")

            # Architecture inference summary
            if arch_tags:
                paras.append(f"**Architecture:** {arch_desc}.")
                if _is_ejs or _is_express:
                    paras.append("The project uses server-side rendering with EJS templates served by Express.js.")
                elif _is_static:
                    paras.append("This appears to be a client-side application with no backend server.")
                paras.append("")

            answer = "\n".join(paras).strip()
            return answer, confidence, notes

        # -- CODE_SNIPPET_IMPACT — grounded deletion/change impact analysis
        if intent in (QueryIntent.CODE_SNIPPET_IMPACT, "code_snippet_impact",
                      QueryIntent.LINE_IMPACT, "line_impact"):
            try:
                import re as _re2
                snippet_text = str((line_metadata or {}).get("matched_line", "") or
                               (line_metadata or {}).get("line_text", "") or "")
                file_path = str((line_metadata or {}).get("file_path", "") or "")
                if not file_path or file_path == "unknown file":
                    file_path = next((e.get("file_path","unknown") for e in evidence if e.get("file_path")), "unknown file")
                # Pre-compute file-type flags for use throughout setup block
                _is_css_file_early = file_path.lower().endswith((".css", ".scss", ".sass", ".less"))
                _is_html_file_early = file_path.lower().endswith((".html", ".htm"))
                # Derive line_no from evidence when not in metadata
                raw_line_no = (line_metadata or {}).get("line_no")
                if raw_line_no:
                    line_no = raw_line_no
                else:
                    # Try to extract from evidence snippet (numbered lines like "42: some code")
                    _ev0_snip = evidence[0].get("snippet", "") if evidence else ""
                    _ev0_sl = evidence[0].get("start_line") if evidence else None
                    _ev0_el = evidence[0].get("end_line") if evidence else None
                    if snippet_text and _ev0_snip:
                        for _ln in _ev0_snip.splitlines():
                            _m_ln = _re2.match(r"^\s*(\d+):\s*(.+)", _ln)
                            if _m_ln and snippet_text.strip().lower() in _m_ln.group(2).lower():
                                line_no = int(_m_ln.group(1))
                                break
                        else:
                            line_no = f"{_ev0_sl}-{_ev0_el}" if _ev0_sl and _ev0_el else (_ev0_sl or "~")
                    else:
                        line_no = f"{_ev0_sl}-{_ev0_el}" if _ev0_sl and _ev0_el else (_ev0_sl or "~")

                # If snippet_text is still empty, try to extract from evidence
                if not snippet_text and evidence:
                    _ev0_snip = evidence[0].get("snippet", "") or ""
                    for _ln in _ev0_snip.splitlines():
                        _m_ln = _re2.match(r"^\s*(\d+):\s*(.+)", _ln)
                        if _m_ln:
                            snippet_text = _m_ln.group(2).strip()
                            break
                    if not snippet_text:
                        # grab first non-empty line of snippet
                        for _ln in _ev0_snip.splitlines():
                            if _ln.strip() and not _ln.strip().startswith("FILE:") \
                                    and not _ln.strip().startswith("TARGET") \
                                    and not _ln.strip().startswith("---"):
                                snippet_text = _ln.strip()[:120]
                                break

                line_type = str((line_metadata or {}).get("line_type", "") or "")
                # Re-detect line type from snippet if metadata says "unknown" or is empty
                if (not line_type or line_type in ("unknown", "other")) and snippet_text:
                    line_type = LineTypeDetector.detect(snippet_text)
                if not line_type:
                    line_type = "other"

                js = dict((line_metadata or {}).get("js_heuristics", {}) or {})

                # Infer config_prop from evidence if js_heuristics empty (lexical match path)
                if not js and (snippet_text or evidence) and not _is_css_file_early:
                    probe = snippet_text or (evidence[0].get("snippet", "") if evidence else "")
                    m_prop = _re2.search(r"^\s*([\w]+)\s*:\s*(.+?)(?:,|;|\s*$)", probe.strip())
                    if m_prop and "function" not in probe.lower() and "=>" not in probe:
                        js = {
                            "config_prop": m_prop.group(1),
                            "config_val": m_prop.group(2).strip()[:80],
                            "config_context": "inferred from snippet",
                        }

                top = evidence[:8]
                all_ctx = " ".join(e.get("snippet", "") for e in top[:3]).lower()
                confidence = "high" if line_metadata and line_metadata.get("found") else "medium"

                parts = []
                parts.append("Impact Analysis")
                parts.append("=" * 40)
                parts.append("Matched Line:")
                parts.append(f"{file_path} (line {line_no})")
                if snippet_text:
                    parts.append(f"  `{snippet_text.strip()}`")
                parts.append("")

                parts.append("What This Line Does:")
                severity = "MEDIUM"
                # ── Resolve file type FIRST to prevent code-logic language on CSS/HTML ──
                _fp_lower = file_path.lower()
                _is_css_file = _fp_lower.endswith((".css", ".scss", ".sass", ".less"))
                _is_html_file = _fp_lower.endswith((".html", ".htm", ".ejs", ".handlebars", ".hbs", ".pug"))
                _file_kind = (line_metadata or {}).get("file_kind", "")

                # ── Pre-compute manifest file flag ────────────────────────
                _MANIFEST_FILES = {
                    "package.json", "package-lock.json", "tsconfig.json",
                    "jsconfig.json", "composer.json", "cargo.toml",
                    "pyproject.toml", "pipfile", "pipfile.lock",
                    "requirements.txt", "poetry.lock", "go.mod", "go.sum",
                    "pom.xml", "build.gradle", "build.gradle.kts",
                    "gradle.properties", "dockerfile", "docker-compose.yml",
                    "docker-compose.yaml", ".env", ".env.example",
                    "app.json", "manifest.json", "setup.cfg", "setup.py",
                    ".npmrc", ".yarnrc", "yarn.lock", "bun.lockb",
                }
                _fp_basename = _fp_lower.split("/")[-1].split("\\")[-1]
                _is_manifest_file = (
                    _fp_basename in _MANIFEST_FILES
                    or _fp_lower.endswith((".toml", ".lock", ".gradle"))
                    or (_fp_lower.endswith(".json") and "node_modules" not in _fp_lower
                        and not _fp_lower.endswith((".min.json",)))
                    or _fp_lower.endswith((".env", ".cfg", ".ini", ".properties"))
                )


                if "os.getenv" in snippet_text or "os.environ" in snippet_text or "process.env" in snippet_text:
                    parts.append("Reads a value from the process environment with an optional fallback default.")
                    parts.append("  - This is a standard pattern for externalising configuration from source code.")
                    severity = "HIGH"
                elif js.get("config_prop") and not _is_css_file and not _is_html_file:
                    prop = js.get("config_prop", "")
                    val = str(js.get("config_val", ""))[:60]
                    ctx = js.get("config_context", "object")
                    parts.append(f"Defines the '{prop}' property (set to `{val}`) inside a {ctx}.")
                    parts.append("  - This configures library, chart, UI, or application behavior.")
                    if "initializeapp" in all_ctx or "initapp" in all_ctx:
                        parts.append("  - Context: SDK or app initialization config.")
                        severity = "HIGH"
                    elif "chart" in all_ctx or "chartjs" in all_ctx:
                        parts.append("  - Context: Chart configuration options block.")
                        severity = "LOW"
                    else:
                        severity = "LOW"
                elif js.get("event_type") and not _is_css_file and not _is_html_file:
                    parts.append("Listens for the '" + js.get("event_type","") + "' DOM event.")
                    severity = "MEDIUM"
                elif js.get("var_name") and not _is_css_file and not _is_html_file:
                    var = js.get("var_name", "")
                    parts.append(f"Initializes variable tracking '{var}'.")
                    severity = "HIGH" if js.get("is_used") else "LOW"
                # ── Function declaration / function signature ──────────────
                elif line_type in ("function_def", "function_signature") or                         (not _is_css_file and not _is_html_file and _re2.search(
                            r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s+\w+|"
                            r"^\s*(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s+)?(\(|function)"
                        , snippet_text)):
                    # Extract function name and attributes
                    _fname = ""
                    _is_async = "async" in snippet_text.lower().split("function")[0] or                                 "async" in snippet_text.lower().split("=>")[0]
                    _is_exported = snippet_text.strip().startswith("export")
                    _m_fn = _re2.search(r"function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=", snippet_text)
                    if _m_fn:
                        _fname = _m_fn.group(1) or _m_fn.group(2) or ""
                    # Extract parameter count from snippet
                    _m_params = _re2.search(r"\(([^)]*)\)", snippet_text)
                    _params_str = _m_params.group(1).strip() if _m_params else ""
                    _param_count = len([p for p in _params_str.split(",") if p.strip()]) if _params_str else 0
                    # Infer purpose from name
                    _fn_purpose = "a reusable operation"
                    _fname_l = _fname.lower()
                    if any(w in _fname_l for w in ("decrypt", "encrypt", "hash", "sign")):
                        _fn_purpose = "cryptographic / data-security processing"
                    elif any(w in _fname_l for w in ("fetch", "get", "load", "request", "api")):
                        _fn_purpose = "data fetching / API communication"
                    elif any(w in _fname_l for w in ("render", "draw", "paint", "display", "show")):
                        _fn_purpose = "UI rendering / display logic"
                    elif any(w in _fname_l for w in ("validate", "check", "verify", "assert")):
                        _fn_purpose = "validation / verification logic"
                    elif any(w in _fname_l for w in ("handle", "on", "click", "submit", "change")):
                        _fn_purpose = "event handling"
                    elif any(w in _fname_l for w in ("init", "setup", "start", "boot", "create")):
                        _fn_purpose = "initialization / setup logic"
                    elif any(w in _fname_l for w in ("parse", "format", "transform", "convert")):
                        _fn_purpose = "data transformation / parsing"
                    _async_label = "async " if _is_async else ""
                    _export_label = "exported " if _is_exported else ""
                    if _fname:
                        parts.append(f"Defines the {_export_label}{_async_label}function `{_fname}` ({_param_count} param(s)).")
                    else:
                        parts.append(f"Defines an {_export_label}{_async_label}function.")
                    parts.append(f"  - Encapsulates {_fn_purpose}.")
                    # Lightweight call-site scan
                    _call_count = 0
                    _call_files = []
                    if _fname and evidence:
                        _call_pat = _re2.compile(_re2.escape(_fname) + r"\s*\(")
                        for _ev in evidence:
                            _ev_snip = _ev.get("snippet", "") or ""
                            _hits = _call_pat.findall(_ev_snip)
                            if _hits:
                                _call_count += len(_hits)
                                _evfp = _ev.get("file_path", "")
                                if _evfp and _evfp not in _call_files:
                                    _call_files.append(_evfp)
                    if _call_count > 0:
                        parts.append(f"  - Found {_call_count} likely call site(s) in evidence: {', '.join(_call_files[:3])}.")
                        severity = "HIGH"
                    else:
                        parts.append("  - No obvious call sites found in indexed evidence (may still be called dynamically).")
                        severity = "MEDIUM"
                # ── Manifest / config document (NON-EXECUTABLE) ──────────
                elif _is_manifest_file and not _is_css_file and not _is_html_file:
                    # Classify the specific manifest field type
                    _snip_s = snippet_text.strip().strip('"').strip("'")
                    _mn_key = ""
                    _m_mn = _re2.search(r'"([^"]+)"\s*:', snippet_text) or \
                             _re2.search(r"([\w\-]+)\s*=", snippet_text) or \
                             _re2.search(r"^\s*([\w\-]+):", snippet_text)
                    if _m_mn:
                        _mn_key = _m_mn.group(1).lower()
                    # Distinguish field type by key name
                    _META_KEYS = {"name","version","description","author","license","homepage",
                                  "repository","keywords","contributors","maintainers","email"}
                    _SCRIPT_KEYS = {"main","module","browser","bin","types","typings","exports",
                                    "scripts","entry","start","build","test","dev"}
                    _DEP_KEYS = {"dependencies","devdependencies","peerdependencies",
                                 "optionaldependencies","bundleddependencies","requires"}
                    _ENV_KEYS = {"port","host","database_url","secret_key","api_key","token",
                                 "debug","env","node_env","app_env"}
                    if _mn_key in _META_KEYS:
                        parts.append(f"A package metadata field that declares the project's {_mn_key}.")
                        parts.append("  - Used by npm/package tooling, registries, and build metadata.")
                        severity = "LOW"
                    elif _mn_key in _SCRIPT_KEYS or "script" in _mn_key:
                        parts.append(f"Defines the `{_mn_key}` entry point or script in this manifest.")
                        parts.append("  - Used by the package manager or build tool to locate or run code.")
                        severity = "MEDIUM"
                    elif _mn_key in _DEP_KEYS or "depend" in _mn_key:
                        parts.append(f"A dependency block entry in the manifest.")
                        parts.append("  - Declares a package that must be installed for this project.")
                        severity = "HIGH"
                    elif any(w in _mn_key for w in ("port", "host", "url", "key", "token", "secret", "env", "password", "db", "database")):
                        parts.append(f"An environment or service configuration value: `{_mn_key}`.")
                        parts.append("  - Controls runtime connectivity, secrets, or service identity.")
                        severity = "MEDIUM"
                    else:
                        _fn_ext = _fp_lower.rsplit(".", 1)[-1] if "." in _fp_lower else ""
                        _doc_type = (
                            "package manifest" if "package" in _fp_basename else
                            "build config" if any(x in _fp_basename for x in ("gradle","cargo","cmake")) else
                            "deployment config" if any(x in _fp_basename for x in ("docker","compose")) else
                            "environment config" if ".env" in _fp_basename else
                            "project manifest"
                        )
                        parts.append(f"A {_doc_type} entry — a non-executable metadata or config field.")
                        severity = "LOW"
                elif _is_css_file or _file_kind == "style":
                    # CSS / Stylesheet classification
                    _is_media = snippet_text.strip().startswith("@media")
                    _is_keyframes = snippet_text.strip().startswith("@keyframes")
                    _is_custom_prop = snippet_text.strip().startswith("--")
                    _is_declaration = ":" in snippet_text and "{" not in snippet_text
                    if _is_media:
                        parts.append("Defines a CSS media query breakpoint rule.")
                    elif _is_keyframes:
                        parts.append("Defines a CSS @keyframes animation sequence.")
                    elif _is_custom_prop:
                        parts.append("Declares a CSS custom property (CSS variable).")
                    elif _is_declaration:
                        parts.append("Sets a CSS style declaration (a property: value pair).")
                    else:
                        parts.append("Defines a CSS selector rule that targets specific HTML elements.")
                    severity = "LOW"
                elif _is_html_file or _file_kind == "markup" or line_type == "html_markup" or                         (snippet_text and "<" in snippet_text and ">" in snippet_text):
                    # Markup / HTML element classification
                    if snippet_text.strip().startswith("<!--"):
                        parts.append("An HTML comment — has no effect on rendering or behavior.")
                    else:
                        parts.append("An HTML element or tag that contributes to the page DOM structure.")
                    severity = "LOW"
                elif line_type == "import":
                    parts.append("Imports an external dependency or module.")
                    severity = "HIGH"
                elif line_type in ("config_property",) or                         (":" in snippet_text and not snippet_text.strip().startswith("/")):
                    parts.append("Defines a configuration or object property.")
                    severity = "LOW"
                else:
                    parts.append(f"Executes a `{line_type}` logic statement.")

                parts.append("")
                parts.append("Likely Impact If Deleted:")
                if "os.getenv" in snippet_text or "os.environ" in snippet_text or "process.env" in snippet_text:
                    parts.append("- Environment variable resolution will fail or return None/undefined.")
                    parts.append("- Any code that depends on this value will receive None, an empty string, or throw.")
                    parts.append("- Features relying on this configuration (credentials, paths, URLs) may fail at startup or first use.")
                elif line_type == "import":
                    parts.append("- File will fail to compile or throw a ReferenceError/NameError.")
                    parts.append("- All downstream usage of this import will break.")
                elif js.get("config_prop"):
                    prop = js.get("config_prop", "this property")
                    if "initializeapp" in all_ctx or "initapp" in all_ctx:
                        parts.append("- SDK or app initialization will receive an incomplete config object.")
                        parts.append("- Features depending on this SDK may fail at startup or on first use.")
                        parts.append("- The UI may load, but backend-connected features will be broken.")
                    elif "chart" in all_ctx or "chartjs" in all_ctx:
                        parts.append(f"- The charting library will use its default value for '{prop}'.")
                        parts.append("- Chart behavior or appearance may change.")
                    else:
                        parts.append(f"- The library or component will fall back to its default for '{prop}'.")
                        parts.append("- User-visible impact is likely cosmetic or behavioral, not a crash.")
                        parts.append("- No runtime error expected unless this property is strictly required.")
                elif js.get("event_type"):
                    parts.append("- The user interaction will no longer trigger the expected behavior.")
                    parts.append("- Visual elements remain but become unresponsive.")
                elif js.get("used_in_dom"):
                    parts.append("- DOM mutations associated with this state will stop.")
                    parts.append("- UI will no longer reflect updated data.")
                elif line_type == "html_markup":
                    parts.append("- This element will no longer be visible.")
                    parts.append("- UI layout will change accordingly.")
                elif line_type in ("function_def", "function_signature") or                         (not _is_css_file and not _is_html_file and _re2.search(
                            r"(^|\s)(export\s+)?(async\s+)?function\s+\w+|"
                            r"(const|let|var)\s+\w+\s*=\s*(async\s+)?(\(|function)"
                        , snippet_text)):
                    _m_fn2 = _re2.search(r"function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=", snippet_text)
                    _fn2 = (_m_fn2.group(1) or _m_fn2.group(2)) if _m_fn2 else "this function"
                    parts.append(f"- Any code calling `{_fn2}(...)` will throw a ReferenceError or TypeError.")
                    parts.append("- Features or behaviors depending on this function will stop working.")
                    if "decrypt" in _fn2.lower() or "encrypt" in _fn2.lower():
                        parts.append("- Encrypted/sensitive data will no longer be processed correctly.")
                    elif "fetch" in _fn2.lower() or "api" in _fn2.lower() or "request" in _fn2.lower():
                        parts.append("- Data loading from APIs or servers will break at the call site.")
                    elif "render" in _fn2.lower() or "display" in _fn2.lower():
                        parts.append("- UI components that depend on this render function will be blank.")
                    elif "handle" in _fn2.lower() or "on" in _fn2.lower():
                        parts.append("- Events wired to this handler will produce no response.")
                    parts.append("- Unrelated code paths that do not invoke this function are unaffected.")
                # ── Manifest impact ────────────────────────────────────────
                elif _is_manifest_file and not _is_css_file and not _is_html_file:
                    _m_mn2 = _re2.search(r'"([^"]+)"\s*:', snippet_text) or \
                              _re2.search(r"([\w\-]+)\s*=", snippet_text) or \
                              _re2.search(r"^\s*([\w\-]+):", snippet_text)
                    _mn_key2 = _m_mn2.group(1).lower() if _m_mn2 else ""
                    _META_KEYS2 = {"name","version","description","author","license","homepage",
                                   "repository","keywords","contributors","maintainers"}
                    _DEP_KEYS2 = {"dependencies","devdependencies","peerdependencies",
                                  "optionaldependencies","bundleddependencies","requires"}
                    if _mn_key2 in _META_KEYS2:
                        parts.append("- Application runtime is generally unaffected.")
                        parts.append("- npm/yarn scripts and local execution will still work.")
                        parts.append(f"- Package publishing, tooling, and identity metadata may be impacted.")
                        parts.append("- Some tools may warn or fall back to inferred defaults.")
                    elif _mn_key2 in _DEP_KEYS2 or "depend" in _mn_key2:
                        parts.append("- The dependency will no longer be installed on the next `npm install`.")
                        parts.append("- Code that imports or requires this package will fail at runtime.")
                        parts.append("- Build or test pipelines that rely on it will break.")
                    elif any(w in _mn_key2 for w in ("script","main","module","entry","bin")):
                        parts.append("- The package manager or build tool may fail to locate the entry point.")
                        parts.append("- `npm start` / `npm run build` / similar commands may fail.")
                        parts.append("- Direct code execution is generally unaffected.")
                    elif any(w in _mn_key2 for w in ("port","host","url","key","token","secret","env","password","db","database")):
                        parts.append("- Application may fail to connect to services or authenticate.")
                        parts.append("- Runtime behavior may break if this config is required at startup.")
                    else:
                        _doc_type2 = (
                            "package manifest" if "package" in _fp_basename else
                            "deployment config" if any(x in _fp_basename for x in ("docker","compose")) else
                            "environment config" if ".env" in _fp_basename else
                            "project manifest"
                        )
                        parts.append(f"- This is a non-executable {_doc_type2} field.")
                        parts.append("- App runtime is generally unaffected unless a tool reads this field.")
                        parts.append("- Tooling, CI/CD pipelines, or metadata enrichment may be impacted.")
                # ── CSS impact ─────────────────────────────────────────────
                elif file_path.lower().endswith((".css", ".scss", ".sass", ".less")) or                         (line_metadata or {}).get("file_kind") in ("style",):
                    _is_media = snippet_text.strip().startswith("@media")
                    _is_selector = "{" in snippet_text or "." in snippet_text or "#" in snippet_text
                    if _is_media:
                        parts.append("- Styles inside this media query will apply at all viewport sizes.")
                        parts.append("- Responsive layout at the targeted breakpoint will be lost.")
                    else:
                        parts.append("- The targeted elements lose the styles defined in this rule.")
                        parts.append("- Styling falls back to inherited values or browser defaults.")
                        parts.append("- The page DOM and JS logic are completely unaffected.")
                    parts.append("- No runtime errors. Visual change only.")
                # ── HTML impact ────────────────────────────────────────────
                elif file_path.lower().endswith((".html", ".htm")):
                    parts.append("- The corresponding DOM element will be removed from the page.")
                    parts.append("- Users will no longer see or interact with it.")
                    parts.append("- JS that queries this element by ID/class may return null.")
                    parts.append("- No compile errors. Browser renders the remaining markup.")
                else:
                    parts.append("- Program execution flow will change.")
                    parts.append("- May cause errors if the removed symbol is used downstream.")

                parts.append("")
                parts.append("Severity:")
                parts.append(f"[{severity}]")

                return "\n".join(parts), confidence, ["Impact analysis generated using local metadata heuristics."]

            except Exception as _impact_err:
                import logging as _lg
                _lg.getLogger(__name__).error(f"CODE_SNIPPET_IMPACT formatter failed: {_impact_err}", exc_info=True)
                top_ev = evidence[:3]
                safe_parts = ["Impact Analysis"]
                safe_parts.append("=" * 40)
                if top_ev:
                    fp = top_ev[0].get("file_path", "?")
                    sl = top_ev[0].get("start_line", "?")
                    safe_parts.append(f"Matched in: {fp} (around line {sl})")
                safe_parts.append("")
                safe_parts.append("This appears to be a configuration or code property deletion.")
                safe_parts.append("Impact: The library or system will fall back to its default value.")
                safe_parts.append("Severity: [LOW-MEDIUM]")
                return "\n".join(safe_parts), "medium", ["Fallback mode: internal formatter error was safely handled."]


        # -- Generic deterministic answer (query-specific, grounded in evidence)
        top = evidence[:6]
        confidence = "high" if len(top) >= 3 else "medium"

        import re as _gen_re
        _STOPWORDS_GEN = {"what", "does", "this", "that", "repo", "file", "line",
                          "code", "the", "and", "for", "with", "from", "into",
                          "how", "why", "when", "where", "which", "will", "would",
                          "should", "could", "have", "been", "being", "about"}
        q_tokens_gen = [
            t.lower().strip("'\"`.,()")
            for t in question.split()
            if len(t) >= 4 and t.lower().strip("'\"`.(),") not in _STOPWORDS_GEN
        ]

        best_lines_gen: list[str] = []
        best_file_gen: str = ""
        best_score_gen = 0
        for chunk in top:
            fp = chunk.get("file_path") or ""
            snip = (chunk.get("snippet") or "").strip()
            if not snip:
                continue
            for raw_line in snip.splitlines():
                line_l = raw_line.lower()
                hits = sum(1 for t in q_tokens_gen if t in line_l)
                if hits > best_score_gen:
                    best_score_gen = hits
                    best_lines_gen = [raw_line.strip()]
                    best_file_gen = fp
                elif hits == best_score_gen and hits > 0 and best_file_gen == fp:
                    if len(best_lines_gen) < 4:
                        best_lines_gen.append(raw_line.strip())

        if best_lines_gen and best_score_gen > 0:
            evidence_text = "\n".join(l for l in best_lines_gen if l)[:400]
            gen_answer = f"{evidence_text}\n\n(Source: `{best_file_gen}`)"
        else:
            first = top[0]
            loc = first.get("file_path") or "the indexed repository files"
            snip_lines = [
                l.strip() for l in (first.get("snippet") or "").splitlines()
                if l.strip() and not l.strip().startswith("[") and len(l.strip()) > 10
            ][:6]
            gen_answer = (
                f"Based on the indexed repository, the most relevant context is in `{loc}`:\n\n"
                + "\n".join(snip_lines)[:400]
            )

        return gen_answer, confidence, notes
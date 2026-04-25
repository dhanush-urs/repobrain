def build_system_prompt(intent: str = "") -> str:
    """
    Build an intent-aware system prompt.
    Different question types get different answer shape instructions.
    """
    base = (
        "You are a precise repository analysis assistant.\n"
        "\n"
        "Your job is to answer the user's exact question using ONLY the repository evidence provided.\n"
        "\n"
        "Core rules:\n"
        "1. Answer the specific question asked — do not answer a different or broader question.\n"
        "2. Use ONLY the provided repository context. Do not invent files, symbols, or behaviors.\n"
        "3. Explain what the code DOES and WHY it matters — do not just restate or quote the snippet.\n"
        "4. Never restate the user's code literally in a redundant way. Start with the consequence or purpose.\n"
        "5. Choose the most relevant evidence snippet(s). Ignore unrelated or noisy matches.\n"
        "6. If multiple snippets are relevant, synthesize them into a single coherent explanation.\n"
        "7. Write in plain natural prose. No markdown bold (**text**), no bullet headers, no section labels.\n"
        "8. Never output labels like 'Direct Answer', 'Evidence', 'Confidence', 'Analysis', 'Summary', "
        "'Immediate effect:', 'Startup impact:', 'Runtime impact:'.\n"
        "9. If the context is genuinely insufficient, say so briefly and specifically — do not fabricate.\n"
        "10. Do not repeat the question back to the user. Start directly with the answer.\n"
        "11. Avoid absolute claims unless the evidence clearly supports them.\n"
    )

    # Intent-specific answer shape guidance
    _IMPACT_INTENTS = {
        "line_impact", "code_snippet_impact", "line_change_impact",
        "dependency_impact", "route_feature_impact", "config_impact",
    }
    if intent in _IMPACT_INTENTS:
        base += (
            "\nFor this impact question: state the direct consequence first. "
            "Then explain when the failure occurs (startup vs runtime vs never if unused). "
            "End with whether it is safe to remove if the symbol is not referenced elsewhere. "
            "2-5 sentences maximum."
        )
    elif intent in ("repo_summary", "architecture_explanation"):
        base += (
            "\nFor this repo overview question: write 2-4 sentences covering what the project does, "
            "the primary language/framework, and the key structural components. "
            "Then optionally add 3-5 concise bullets for stack, entrypoint, major capabilities, integrations. "
            "Cite the files that support each claim. Do not let dependency files dominate the answer."
        )
    elif intent in ("flow_question",):
        base += (
            "\nFor this flow/architecture question: explain the execution path in plain language. "
            "Name the key files and layers involved (entrypoint → route → service → data). "
            "Be specific about what each layer does. 3-6 sentences or a short numbered list. "
            "Cite the files that show this flow."
        )
    elif intent in ("symbol_lookup",):
        base += (
            "\nFor this symbol question: state where the symbol is defined (file + line if available), "
            "then where it is used or called. 2-4 sentences. Be specific about file paths."
        )
    elif intent in ("semantic_qa",):
        base += (
            "\nFor this code explanation: explain what the code does and why it exists. "
            "Mention the source file. 2-4 sentences. Start with the purpose, not a restatement."
        )

    return base


def build_user_prompt(question: str, retrieved_chunks: list[dict], intent: str = "general") -> str:
    context = _format_context_for_llm(retrieved_chunks, intent=intent)
    intent_hint = _intent_hint_for_prompt(intent)
    return (
        f"USER QUESTION:\n{question}\n\n"
        f"TOP REPOSITORY EVIDENCE:\n{context}\n\n"
        f"{intent_hint}"
        "Answer the user's exact question based only on the evidence above. "
        "Write in plain prose. No section headers, no bold text, no meta labels."
    )


def _intent_hint_for_prompt(intent: str) -> str:
    """Return a short intent-specific instruction appended to the user prompt."""
    if intent in ("line_impact", "code_snippet_impact", "line_change_impact",
                  "dependency_impact", "route_feature_impact", "config_impact"):
        return (
            "ANSWER SHAPE: State the direct consequence first. "
            "Then explain when the failure occurs (startup vs runtime vs never if unused). "
            "End with whether it is safe to remove if the symbol is not referenced elsewhere. "
            "2-5 sentences maximum.\n\n"
        )
    if intent in ("repo_summary", "architecture_explanation"):
        return (
            "ANSWER SHAPE: Write 2-4 sentences of plain-English summary covering: "
            "what this project does, the primary language/framework, and the key capabilities. "
            "Then optionally add 3-5 bullets: stack/framework, likely entrypoint, "
            "major capabilities, notable integrations. "
            "Cite the files that support each claim. "
            "Do not list every file. Do not let requirements.txt dominate the answer.\n\n"
        )
    if intent in ("symbol_lookup",):
        return (
            "ANSWER SHAPE: State where the symbol is defined and where it is used. "
            "2-3 sentences. Include the file path and line if available in the evidence.\n\n"
        )
    return ""


def build_repo_summary_prompt(question: str, retrieved_chunks: list[dict]) -> str:
    return build_user_prompt(question, retrieved_chunks, intent="repo_summary")


def build_flow_question_prompt(
    question: str,
    retrieved_chunks: list[dict],
    flow_summary: str,
    intent: str = "flow_question",
) -> str:
    """
    Build a prompt for flow/architecture questions.
    Injects synthesized flow context (routes, services, entrypoints) as top context.
    """
    context = _format_context_for_llm(retrieved_chunks, intent=intent)

    flow_section = ""
    if flow_summary:
        flow_section = (
            f"EXECUTION FLOW CONTEXT (routes, services, entrypoints):\n"
            f"{flow_summary}\n\n"
        )

    return (
        f"USER QUESTION:\n{question}\n\n"
        f"{flow_section}"
        f"SUPPORTING EVIDENCE:\n{context}\n\n"
        "ANSWER SHAPE: Explain the execution flow in plain language. "
        "Name the key files and layers (entrypoint → route → service → data). "
        "Be specific. 3-6 sentences or a short numbered list. "
        "Cite the files that show this flow.\n\n"
        "Answer the user's question based on the flow context and evidence above. "
        "Write in plain prose. No section headers, no bold text, no meta labels."
    )


def build_repo_overview_prompt(
    question: str,
    retrieved_chunks: list[dict],
    repo_overview: str,
    intent: str = "repo_summary",
) -> str:
    """
    Build a prompt for repo-level questions that injects a structured repo overview
    as top context, ensuring the LLM answers from repo-level understanding rather
    than random snippet retrieval.

    The overview is prepended before the retrieved evidence so it dominates the answer.
    """
    context = _format_context_for_llm(retrieved_chunks, intent=intent)

    is_arch = intent == "architecture_explanation"
    if is_arch:
        answer_shape = (
            "ANSWER SHAPE: Write 2-4 sentences covering the overall architecture: "
            "how the layers are organized, what the main components are, and how data flows. "
            "Then optionally add 3-5 bullets covering: stack/framework, entrypoint, "
            "major modules, auth/db integrations, deployment hints. "
            "Cite the files that support each claim."
        )
    else:
        answer_shape = (
            "ANSWER SHAPE: Write 2-4 sentences of plain-English summary covering: "
            "what this project does, the primary language/framework, and the key capabilities. "
            "Then optionally add 3-5 bullets covering: stack/framework, likely entrypoint, "
            "major capabilities, notable integrations. "
            "Cite the files that support each claim. "
            "Do not list every file — focus on the most informative signals."
        )

    overview_section = ""
    if repo_overview:
        overview_section = (
            f"REPO OVERVIEW (synthesized from README, entrypoints, config, routes):\n"
            f"{repo_overview}\n\n"
        )

    return (
        f"USER QUESTION:\n{question}\n\n"
        f"{overview_section}"
        f"SUPPORTING EVIDENCE:\n{context}\n\n"
        f"{answer_shape}\n\n"
        "Answer the user's question based on the repo overview and supporting evidence above. "
        "Write in plain prose. No section headers, no bold text, no meta labels."
    )


def build_code_prompt(question: str, retrieved_chunks: list[dict]) -> str:
    return build_user_prompt(question, retrieved_chunks, intent="code")


def build_impact_prompt(
    question: str,
    retrieved_chunks: list[dict],
    line_metadata: dict,
) -> str:
    return build_user_prompt(question, retrieved_chunks, intent="impact")


def _format_context_for_llm(chunks: list[dict], intent: str = "general") -> str:
    """
    Build a clean, compressed context string for the LLM.

    Compression rules:
    - Skip chunks with no meaningful content.
    - For each chunk, extract the smallest high-signal window around the best matching lines.
    - Prefer symbol-bearing lines (imports, defs, assignments, calls, routes).
    - Preserve critical comments (SECURITY, TODO, WARN, NOTE, IMPORTANT, FIXME).
    - Strip blank lines and routine comment-only lines.
    - Hard cap per block (varies by intent).
    - Cap total blocks at 6.
    - Number each block so the model can reference them.
    """
    if not chunks:
        return "NO REPO EVIDENCE FOUND."

    import re as _re_fmt

    _SYMBOL_INDICATORS = (
        "import ", "from ", "def ", "class ", "async def ", "async function ",
        "function ", "const ", "let ", "var ", "export ", "export default ",
        "return ", "raise ", "@", "->", "=>", "route", "app.",
        "interface ", "type ", "enum ", "struct ", "func ",
        "@app.", "@router.", "@blueprint.",
    )

    # Critical comment patterns — preserve these even in compressed mode
    _CRITICAL_COMMENT_RE = _re_fmt.compile(
        r"^\s*(?:#|//|/\*)\s*(?:SECURITY|TODO|WARN|WARNING|NOTE|IMPORTANT|FIXME|HACK|BUG|XXX)[\s:]",
        _re_fmt.IGNORECASE,
    )

    # Intent-specific block size limits
    _is_summary = intent in ("repo_summary", "architecture_explanation")
    _is_code = intent in ("semantic_qa", "symbol_lookup", "flow_question")
    _is_impact = intent in ("line_impact", "code_snippet_impact", "line_change_impact",
                            "dependency_impact", "route_feature_impact", "config_impact")

    if _is_summary:
        _MAX_BLOCK_CHARS = 800
        _MAX_BLOCKS = 6
    elif _is_code:
        _MAX_BLOCK_CHARS = 600
        _MAX_BLOCKS = 6
    elif _is_impact:
        _MAX_BLOCK_CHARS = 500
        _MAX_BLOCKS = 5
    else:
        _MAX_BLOCK_CHARS = 450
        _MAX_BLOCKS = 5

    blocks = []
    for idx, c in enumerate(chunks[:_MAX_BLOCKS * 2], 1):  # over-fetch, then cap
        if len(blocks) >= _MAX_BLOCKS:
            break

        fp = c.get("file_path") or "unknown"
        sl = c.get("start_line")
        el = c.get("end_line")
        loc = f"{fp}:{sl}-{el}" if sl else fp
        mt = c.get("match_type", "chunk")

        raw_snippet = (c.get("snippet") or c.get("chunk_text") or "").strip()
        if not raw_snippet:
            continue

        # Strip retrieval-injected header lines
        lines = raw_snippet.splitlines()
        lines = [
            l for l in lines
            if not _re_fmt.match(
                r"^(Found matching snippet|Snippet is inside symbol|FILE:|TARGET LINE|ENCLOSING|"
                r"Context before|Context after|---|\[FILE\]|\[REPO\]|REPO INTELLIGENCE|"
                r"REPOSITORY METADATA|FILE STRUCTURE CENSUS|PROJECT MANIFEST|ENTRYPOINT CODE|"
                r"ROUTE/API FILE|DATA MODEL|DATA SAMPLE|README CONTENT|DEPENDENCY MANIFEST|"
                r"PACKAGE USAGE|FEATURE MATCH)",
                l.strip(),
                _re_fmt.IGNORECASE,
            )
        ]

        # Filter noise lines — but preserve critical comments
        meaningful_lines = []
        for l in lines:
            stripped = l.strip()
            if not stripped or len(stripped) <= 3:
                continue
            # Preserve critical comments
            if _CRITICAL_COMMENT_RE.match(l):
                meaningful_lines.append(l)
                continue
            # Skip routine comment-only lines
            if (stripped.startswith("#") or stripped.startswith("//")
                    or stripped.startswith("/*") or stripped.startswith("*")):
                continue
            meaningful_lines.append(l)

        if not meaningful_lines:
            continue

        # For large chunks: extract the smallest window around symbol-bearing lines
        if len(meaningful_lines) > 15 and not _is_summary:
            symbol_line_indices = [
                i for i, l in enumerate(meaningful_lines)
                if any(tok in l for tok in _SYMBOL_INDICATORS)
            ]
            if symbol_line_indices:
                # Take a ±4 window around the first symbol-bearing line (was ±3)
                center = symbol_line_indices[0]
                window_start = max(0, center - 4)
                window_end = min(len(meaningful_lines), center + 5)
                meaningful_lines = meaningful_lines[window_start:window_end]
            else:
                # No symbol lines — take first 15 meaningful lines (was 12)
                meaningful_lines = meaningful_lines[:15]

        snippet_text = "\n".join(meaningful_lines)
        if len(snippet_text) > _MAX_BLOCK_CHARS:
            snippet_text = snippet_text[:_MAX_BLOCK_CHARS] + "\n..."

        blocks.append(f"[{idx}] {loc} ({mt})\n{snippet_text}")

    if not blocks:
        return "NO REPO EVIDENCE FOUND."

    return "\n\n---\n\n".join(blocks)


# Keep the old name as an alias so any other callers don't break
def _format_context(chunks: list[dict]) -> str:
    return _format_context_for_llm(chunks)

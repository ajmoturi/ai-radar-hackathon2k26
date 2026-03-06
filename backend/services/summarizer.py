"""LLM-powered summarization with structured JSON output.

Supports three providers, controlled by the LLM_PROVIDER env var:
  - "anthropic"    → Claude via Anthropic SDK (default)
  - "azure_openai" → GPT-4o via Azure OpenAI SDK
  - "openai"       → Any OpenAI-compatible API (Groq, Ollama, Gemini, etc.)

All providers are called with tool-use / function-calling to enforce structured
JSON output.  The Anthropic SDK uses native tool_use blocks; OpenAI-compatible
providers use the function-calling interface.

Groq quirk: llama-3.3-70b-versatile sometimes returns valid JSON in a
non-standard format inside a failed_generation error field.  _parse_failed_generation()
recovers usable structured data from these responses.
"""
import json
import logging
from typing import Any, Optional

import anthropic

from backend.config import settings

logger = logging.getLogger(__name__)

# Lazy-initialised singleton clients — created on first use to avoid import-time
# side-effects and to respect the LLM_PROVIDER setting at runtime.
_anthropic_client: Optional[anthropic.Anthropic] = None
_azure_client = None   # openai.AzureOpenAI, lazily imported
_openai_client = None  # openai.OpenAI, lazily imported


def _get_anthropic_client() -> anthropic.Anthropic:
    """Return the shared Anthropic client, creating it on first call."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


def _get_azure_client():
    """Return the shared Azure OpenAI client, creating it on first call."""
    global _azure_client
    if _azure_client is None:
        from openai import AzureOpenAI
        _azure_client = AzureOpenAI(
            api_key=settings.azure_openai_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )
    return _azure_client


def _get_openai_client():
    """Return the shared OpenAI-compatible client, creating it on first call.

    base_url can point at Groq, Ollama, Gemini, or any OpenAI-compatible endpoint.
    """
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    return _openai_client


# Backward-compatible alias for any code that imported get_client() directly.
def get_client() -> anthropic.Anthropic:
    return _get_anthropic_client()


# ------------------------------------------------------------------ #
# Tool definitions (Anthropic tool-use schema)                         #
# These are converted to OpenAI function-calling format when needed.   #
# ------------------------------------------------------------------ #

RELEASE_SUMMARY_TOOL = {
    "name": "extract_release_finding",
    "description": "Extract structured information from a release note, changelog, or product update.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title of the update"},
            "category": {
                "type": "string",
                "enum": ["Models", "APIs", "Pricing", "Benchmarks", "Safety", "Tooling", "Research", "Other"],
            },
            "summary_short": {
                "type": "string",
                "description": "One-sentence summary of what changed (≤60 words)",
            },
            "summary_long": {
                "type": "string",
                "description": "Bullet-point summary: what changed, key details, any numbers",
            },
            "why_it_matters": {
                "type": "string",
                "description": "Why this matters to AI practitioners (1-3 sentences)",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Direct quotes or key facts from the source (max 3)",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence 0-1: 1.0=official source+clear date, 0.5=ambiguous, 0.2=repost",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Relevant tags (e.g. gpt-4, multimodal, pricing-change)",
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Company/model/dataset names mentioned",
            },
            "publisher": {"type": "string", "description": "Publishing organization"},
        },
        "required": ["title", "category", "summary_short", "summary_long",
                     "why_it_matters", "confidence", "publisher"],
    },
}

RESEARCH_SUMMARY_TOOL = {
    "name": "extract_research_finding",
    "description": "Extract structured information from an AI research paper abstract/content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "core_contribution": {
                "type": "string",
                "description": "Core contribution in 1-2 sentences",
            },
            "summary_short": {
                "type": "string",
                "description": "What's new vs prior work (≤60 words)",
            },
            "summary_long": {
                "type": "string",
                "description": "Detailed bullet points: methodology, results, implications",
            },
            "why_it_matters": {
                "type": "string",
                "description": "Practical implications for eval, training, inference, agents, safety",
            },
            "relevance_score": {
                "type": "number",
                "description": "0-1 relevance to: benchmarks/eval, data-centric, agentic, multimodal, safety",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
            },
            "confidence": {"type": "number"},
        },
        "required": ["title", "core_contribution", "summary_short", "summary_long",
                     "why_it_matters", "relevance_score", "confidence"],
    },
}

BENCHMARK_SUMMARY_TOOL = {
    "name": "extract_benchmark_finding",
    "description": "Extract structured information from HuggingFace leaderboard or benchmark results.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary_short": {"type": "string", "description": "Key leaderboard movement (≤60 words)"},
            "summary_long": {
                "type": "string",
                "description": "Bullet points: who moved up/down, which tasks improved, model family trends",
            },
            "why_it_matters": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "entities": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": ["title", "summary_short", "summary_long", "why_it_matters", "confidence"],
    },
}

DIGEST_NARRATIVE_TOOL = {
    "name": "generate_digest_narrative",
    "description": "Generate executive narrative for the daily AI digest.",
    "input_schema": {
        "type": "object",
        "properties": {
            "exec_summary": {
                "type": "string",
                "description": "Executive summary: top 7 most important developments today (bullet points)",
            },
            "what_changed": {
                "type": "string",
                "description": "What changed since yesterday (2-3 paragraphs)",
            },
            "why_it_matters": {
                "type": "string",
                "description": "Why today's developments matter to your organization (2-3 paragraphs)",
            },
        },
        "required": ["exec_summary", "what_changed", "why_it_matters"],
    },
}


def _call_with_tool(prompt: str, tool: dict, system: str = "") -> Optional[dict]:
    """Route the LLM call to the provider configured by LLM_PROVIDER env var."""
    if settings.llm_provider == "azure_openai":
        return _call_azure(prompt, tool, system)
    if settings.llm_provider == "openai":
        return _call_openai(prompt, tool, system)
    return _call_anthropic(prompt, tool, system)


def _call_anthropic(prompt: str, tool: dict, system: str = "") -> Optional[dict]:
    """Call Claude via the Anthropic SDK using native tool_use blocks.

    Returns the tool input dict on success, or None on error.
    """
    client = _get_anthropic_client()
    messages = [{"role": "user", "content": prompt}]
    kwargs: dict[str, Any] = {
        "model": settings.anthropic_model,
        "max_tokens": 2048,
        "tools": [tool],
        "tool_choice": {"type": "any"},  # force tool use — don't allow plain text fallback
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    try:
        response = client.messages.create(**kwargs)
        for block in response.content:
            if block.type == "tool_use":
                return block.input
    except Exception as e:
        logger.error(f"Anthropic summarizer error: {e}")
    return None


def _call_azure(prompt: str, tool: dict, system: str = "") -> Optional[dict]:
    """Call GPT-4o via Azure OpenAI SDK using function calling.

    The Anthropic input_schema maps directly to OpenAI's parameters field.
    """
    client = _get_azure_client()
    # Convert Anthropic tool schema → OpenAI function-calling format.
    openai_tool = {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        response = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            max_tokens=2048,
            tools=[openai_tool],
            tool_choice={"type": "function", "function": {"name": tool["name"]}},
            messages=messages,
        )
        choice = response.choices[0]
        if choice.message.tool_calls:
            return json.loads(choice.message.tool_calls[0].function.arguments)
    except Exception as e:
        logger.error(f"Azure OpenAI summarizer error: {e}")
    return None


def _parse_failed_generation(text: str) -> Optional[dict]:
    """Recover structured data from Groq's failed_generation error field.

    Groq's llama-3.3-70b-versatile sometimes generates valid JSON but wraps it
    in a non-standard format that causes a 400 error.  Known formats:

      <function=name>{"key": "val"}>                     → {"key": "val"}
      <function=name [{"k":"v"}, {"k2":"v2"}]>           → merged dict

    Strips the wrapper, parses JSON, and merges array-of-dicts into one dict.
    """
    import re
    # Remove the <function=name ...> prefix in all its variants.
    text = re.sub(r"^<function=\w+[>\s]*", "", text.strip())
    if text.endswith(">"):
        text = text[:-1]
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            # Array format — merge all key-value pairs into a single dict.
            merged: dict = {}
            for item in parsed:
                if isinstance(item, dict):
                    merged.update(item)
            return merged or None
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return None


def _call_openai(prompt: str, tool: dict, system: str = "") -> Optional[dict]:
    """Call any OpenAI-compatible API (Groq, Ollama, Gemini, vanilla OpenAI, etc.).

    Uses tool_choice="required" to force a function call response.
    Includes Groq-specific failed_generation recovery as a secondary fallback.
    """
    client = _get_openai_client()
    # Convert Anthropic tool schema → OpenAI function-calling format.
    openai_tool = {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            max_tokens=2048,
            tools=[openai_tool],
            tool_choice="required",  # force function call (not "auto")
            messages=messages,
        )
        choice = response.choices[0]
        if choice.message.tool_calls:
            return json.loads(choice.message.tool_calls[0].function.arguments)
    except Exception as e:
        # Groq sometimes puts valid structured data inside a 400 error's
        # failed_generation field — attempt recovery before giving up.
        body = getattr(e, "body", None)
        if isinstance(body, dict):
            failed_gen = body.get("error", {}).get("failed_generation", "")
            if failed_gen:
                recovered = _parse_failed_generation(failed_gen)
                if recovered:
                    logger.warning("Recovered structured data from failed_generation (model format issue)")
                    return recovered
        logger.error(f"OpenAI-compatible summarizer error: {e}")
    return None


SYSTEM_PROMPT = (
    "You are an expert AI analyst. Extract factual information only. "
    "Never invent benchmark scores or statistics. If a number is not stated in the source, "
    "omit it. Always cite evidence from the provided text."
)


def summarize_release(text: str, url: str, agent_type: str = "competitor") -> Optional[dict]:
    prompt = f"""Analyze this content from {url} and extract a structured finding.

Content:
{text}

Important: Only include claims that are explicitly stated in the content. Confidence should be:
- 0.8-1.0: Official source, clear date, unambiguous change
- 0.5-0.7: Some ambiguity or unclear date
- 0.1-0.4: Third-party repost or speculative"""
    return _call_with_tool(prompt, RELEASE_SUMMARY_TOOL, SYSTEM_PROMPT)


def summarize_research(text: str, url: str) -> Optional[dict]:
    prompt = f"""Analyze this research paper from {url} and extract a structured finding.

Content:
{text}

Rate relevance_score higher (0.7-1.0) for papers covering:
- New benchmarks or evaluation methodology
- Data-centric techniques (curation, synthetic data, RLHF, preference learning)
- Agentic workflows, tool use, memory systems
- Multimodal reasoning, video, robotics
- Safety, alignment, red-teaming, policy compliance

Lower relevance (0.0-0.4) for narrow, incremental, or domain-specific work."""
    return _call_with_tool(prompt, RESEARCH_SUMMARY_TOOL, SYSTEM_PROMPT)


def summarize_benchmark(text: str, url: str) -> Optional[dict]:
    prompt = f"""Analyze this benchmark/leaderboard content from {url} and extract findings.

Content:
{text}

Focus on: who moved up/down, new SOTA claims, model family trends, caveats."""
    return _call_with_tool(prompt, BENCHMARK_SUMMARY_TOOL, SYSTEM_PROMPT)


def generate_digest_narrative(findings_summary: str) -> Optional[dict]:
    prompt = f"""Generate an executive narrative for today's Frontier AI Radar digest.

Today's findings:
{findings_summary}

Create an insightful narrative suitable for senior AI/ML practitioners."""
    return _call_with_tool(prompt, DIGEST_NARRATIVE_TOOL, SYSTEM_PROMPT)

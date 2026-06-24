"""DAT-620 lane-1 labeler: two legs over the same inputs (top_values + ontology).

Leg A (feed-only)  — what the graph agent would do if simply fed top_values + the
                     ontology concept list, with no dedicated contract. ≈ DAT-616 alone.
Leg B (value-level semantic) — a dedicated value-labeling contract: complete enumeration,
                     explicit abstention, exclude-pattern awareness. The "extend the
                     semantic agent one grain finer" candidate.

Same inputs, same model — the only difference is the prompt/contract richness. That is
the A-vs-B fork the kill gate decides.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dataraum.llm.providers.anthropic import AnthropicConfig, AnthropicProvider
from dataraum.llm.providers.base import (
    ConversationRequest,
    Message,
    ToolDefinition,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ONTOLOGY = (
    _REPO_ROOT
    / "vendor/dataraum-context/packages/dataraum-config/verticals/finance/ontology.yaml"
)

PROVIDER_CONFIG = {
    "default_model": "claude-sonnet-4-6",
    "models": {"fast": "claude-haiku-4-5", "balanced": "claude-sonnet-4-6"},
}

_LABEL_TOOL = ToolDefinition(
    name="label_values",
    description="Assign each account_type value to one ontology concept or 'unmapped'.",
    input_schema={
        "type": "object",
        "properties": {
            "labels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "concept": {
                            "type": "string",
                            "description": "exact ontology concept name, or 'unmapped'",
                        },
                        "confidence": {"type": "number"},
                    },
                    "required": ["value", "concept", "confidence"],
                },
            }
        },
        "required": ["labels"],
    },
)


def load_finance_concepts() -> list[dict]:
    """The finance ontology concepts (name/description/indicators/exclude_patterns)."""
    doc = yaml.safe_load(_ONTOLOGY.read_text())
    return doc["concepts"]


def _format_concepts(concepts: list[dict]) -> str:
    lines = []
    for c in concepts:
        ind = ", ".join(c.get("indicators", []))
        exc = ", ".join(c.get("exclude_patterns", []))
        line = f"- {c['name']}: {c.get('description', '')}"
        if ind:
            line += f" | indicators: {ind}"
        if exc:
            line += f" | exclude: {exc}"
        lines.append(line)
    return "\n".join(lines)


def _format_top_values(top_values: list[tuple[str, int]]) -> str:
    return "\n".join(f'- "{v}" (count {n})' for v, n in top_values)


_SYSTEM_A = (
    "You map the distinct values of a categorical column to business concepts."
)
_SYSTEM_B = (
    "You ground a finance metric by labeling EVERY distinct value of a discriminator "
    "column with the business concept it denotes, so downstream SQL filters on the "
    "right rows instead of guessing. Rules: enumerate every value exactly once; assign "
    "each to exactly one ontology concept by MEANING; use 'unmapped' when no concept "
    "applies (a value left unmapped is safer than a wrong label — never force-fit); a "
    "value may contain a word listed as a concept's exclude_pattern yet still belong to "
    "that concept — judge by the whole meaning, not a single word. Give a per-value "
    "confidence in [0,1]."
)


def _build_request(leg: str, top_values, concepts, model: str | None) -> ConversationRequest:
    system = _SYSTEM_A if leg == "A" else _SYSTEM_B
    user = (
        f"Column: account_type\nDistinct values (with row counts):\n"
        f"{_format_top_values(top_values)}\n\n"
        f"Business concepts:\n{_format_concepts(concepts)}\n\n"
        f"Label every value via the label_values tool."
    )
    return ConversationRequest(
        messages=[Message(role="user", content=user)],
        system=system,
        tools=[_LABEL_TOOL],
        tool_choice={"type": "tool", "name": "label_values"},
        max_tokens=2000,
        temperature=0.0,
        model=model,
    )


def make_provider():
    # Direct construction — skip the engine's full Settings (DB/temporal/s3) the
    # probe doesn't need; only the Anthropic key is required.
    return AnthropicProvider(
        AnthropicConfig(**PROVIDER_CONFIG), os.environ["ANTHROPIC_API_KEY"]
    )


def label(
    provider, leg: str, top_values, concepts, model: str | None = None
) -> dict[str, tuple[str, float]]:
    """Run one leg → {account_type value: (predicted concept, confidence)}.

    Concepts are normalized to lowercase; anything unrecognized collapses to 'unmapped'.
    """
    request = _build_request(leg, top_values, concepts, model)
    result = provider.converse(request)
    if not result.success:
        raise RuntimeError(f"converse failed (leg {leg}): {result.error}")
    response = result.value
    if not response.tool_calls:
        raise RuntimeError(f"no tool call returned (leg {leg}): {response.content!r}")

    known = {c["name"].lower() for c in concepts} | {"unmapped"}
    out: dict[str, tuple[str, float]] = {}
    for item in response.tool_calls[0].input.get("labels", []):
        value = str(item.get("value", ""))
        concept = str(item.get("concept", "unmapped")).strip().lower()
        if concept not in known:
            concept = "unmapped"
        out[value] = (concept, float(item.get("confidence", 0.0)))
    return out

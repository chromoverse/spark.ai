"""
Entity extractor: scraped text + schema name → list of typed entity dicts.

Architectural role: **fallback / enrichment only**. The primary retrieval
substrate for entity intents is the structured-providers package
(``providers/osm_provider.py`` today; Google Places / Foursquare next).
This LLM path is reached only when no structured provider covers the
intent (or all available providers returned empty). Coordinates extracted
here must come from page-visible signals, never from the model's prior.

Single LLM call with schema-constrained prompt. Returns plain dicts so
the caller doesn't need to import Pydantic models.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.ai.providers.router import routed_chat  # type: ignore

from .entity_schemas import ENTITY_FIELD_DESCRIPTIONS, ENTITY_SCHEMA_MAP

logger = logging.getLogger(__name__)

_MAX_CONTEXT_CHARS = 12_000


async def extract_entities(
    scraped_texts: List[Dict[str, Any]],
    entity_schema: str,
    query: str,
    location: str = "",
) -> List[Dict[str, Any]]:
    """
    scraped_texts: list of {"url": ..., "title": ..., "text": ...}
    entity_schema: one of hotel | product | restaurant | local_business | person | movie | event | college | place | flight
    query: user's original query
    location: detected location (e.g., "Kathmandu, Bagmati Province")
    Returns: list of entity dicts (validated against the schema, extras dropped).
    """
    schema_cls = ENTITY_SCHEMA_MAP.get(entity_schema)
    if schema_cls is None:
        logger.warning(f"Unknown entity_schema '{entity_schema}', skipping extraction")
        return []

    field_hint = ENTITY_FIELD_DESCRIPTIONS.get(entity_schema, "")

    # Build context — trim to avoid huge token bills
    context_parts: List[str] = []
    total = 0
    for item in scraped_texts:
        if not item.get("text"):
            continue
        chunk = f"URL: {item.get('url', '')}\nTitle: {item.get('title', '')}\n{item['text']}"
        if total + len(chunk) > _MAX_CONTEXT_CHARS:
            remaining = _MAX_CONTEXT_CHARS - total
            if remaining > 200:
                context_parts.append(chunk[:remaining])
            break
        context_parts.append(chunk)
        total += len(chunk)

    if not context_parts:
        return []

    context = "\n\n---\n\n".join(context_parts)

    system_msg = (
        "You are a structured data extractor. You receive scraped web page text "
        "and return a strict JSON array of entity objects. No markdown, no fences, "
        "no explanation — only a JSON array."
    )

    location_filter = ""
    if location:
        city = location.split(",")[0].strip()
        location_filter = f"\n- CRITICAL: Only extract entities located in or near {location}. Ignore entities from other cities/countries."

    user_msg = f"""Extract all distinct {entity_schema} entities from the text below.

USER QUERY: {query}

EXTRACTION RULES:
- {field_hint}
- Each object must have at minimum a "name" field.
- "type" field must be "{entity_schema}".
- Omit fields you cannot find — do not guess.
- If the same entity appears in multiple sources, merge into one entry (keep the richer data).
- Deduplicate: never return two objects with the same or near-identical name.
- Return an empty array [] if no entities are found.
- source_url: set to the URL where this entity was found.{location_filter}

CONTEXT:
{context}

OUTPUT (strict JSON array only):"""

    try:
        response_text, _ = await routed_chat(
            "entity_extract",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=3500,
        )
    except Exception as exc:
        logger.error(f"LLM call failed in entity_extractor: {exc}")
        return []

    raw_entities = _parse_json_array(response_text)
    if raw_entities is None:
        logger.warning("entity_extractor: could not parse LLM response as JSON array")
        return []

    # Validate + coerce each entity through the Pydantic schema
    validated: List[Dict[str, Any]] = []
    seen_names: set = set()
    for raw in raw_entities:
        if not isinstance(raw, dict):
            continue
        # Deduplicate by normalised name
        name = str(raw.get("name", "")).strip().lower()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        try:
            entity = schema_cls(**raw)
            validated.append(entity.model_dump(exclude_none=True))
        except Exception:
            # Best-effort: keep raw if schema validation fails
            raw["type"] = entity_schema
            validated.append(raw)

    return validated


def _parse_json_array(text: str) -> List[Any] | None:
    """Extract a JSON array from LLM output, tolerating markdown fences and truncation."""
    clean = text.strip()
    for prefix in ("```json", "```"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()

    start = clean.find("[")
    if start == -1:
        return None

    # Try full parse first
    end = clean.rfind("]")
    if end > start:
        try:
            result = json.loads(clean[start : end + 1])
            return result if isinstance(result, list) else None
        except json.JSONDecodeError:
            pass

    # Truncation repair: find the last complete object `}` and close the array
    fragment = clean[start:]
    last_close = fragment.rfind("}")
    if last_close != -1:
        repaired = fragment[: last_close + 1] + "\n]"
        # Strip trailing comma before `]`
        repaired = repaired.replace(",\n]", "\n]").replace(", ]", "]")
        try:
            result = json.loads(repaired)
            return result if isinstance(result, list) else None
        except json.JSONDecodeError:
            pass

    return None

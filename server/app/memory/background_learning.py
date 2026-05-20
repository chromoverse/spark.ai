"""
Tier 3: Background Post-Conversation Learning

After each conversation ends (or periodically), this module:
1. Extracts new facts/preferences about the user from recent messages
2. Updates the user profile summary (Tier 1)
3. Detects habit patterns over time

Runs AFTER conversation — zero latency cost to the user.
Uses a cheap/fast LLM call to extract structured facts.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Minimum messages before triggering learning
_MIN_MESSAGES_FOR_LEARNING = 4

# Cooldown between learning runs per user (seconds)
_LEARNING_COOLDOWN = 120  # 2 min — learn fast during active conversations

# Track last learning time per user
_last_learning: Dict[str, float] = {}

_FACT_EXTRACTION_PROMPT = """Analyze this conversation between a user and their AI assistant.
Extract information that would help the assistant remember and proactively support this person.

Return a JSON object with:
- "facts": list of factual statements about the user (max 5). Include: plans, goals, projects, people mentioned, places, events, deadlines, interests.
- "preferences": dict of preference key-value pairs (max 3). e.g. {"music": "lo-fi", "response_style": "concise"}
- "habits": list of behavioral patterns (max 2). e.g. "codes late at night", "asks about weather in morning"
- "active_plans": list of things the user is currently planning/working on (max 3). e.g. "going to Finland for hackathon", "building AI assistant called Spark"

Rules:
- Capture ANYTHING the user might want remembered: trips, deadlines, people, projects, opinions, decisions
- "I need to go to Finland for hackathon" → active_plan
- "I hate verbose code" → preference
- "My friend Ram is helping me" → fact about their social circle
- If nothing new, return empty lists/dicts

Conversation:
{conversation}

Return ONLY valid JSON, no explanation."""

_SUMMARY_PROMPT = """You are updating a user profile summary for a personal AI assistant.
Given the existing profile and new facts, write a concise updated summary (max 200 words).
The summary should read naturally and help the AI understand this person instantly.

Existing profile:
{existing_summary}

New facts: {new_facts}
Preferences: {preferences}
Habits: {habits}

Write a natural, concise profile summary. Include all important facts. Be specific, not generic.
Return ONLY the summary text, nothing else."""


async def run_post_conversation_learning(user_id: str, force: bool = False) -> None:
    """
    Main entry point — call this after a conversation ends.
    Runs in background, never blocks the user.
    """
    now = time.time()
    last = _last_learning.get(user_id, 0)
    if not force and (now - last) < _LEARNING_COOLDOWN:
        logger.debug("Learning cooldown active for %s, skipping", user_id)
        return

    _last_learning[user_id] = now

    try:
        await _learn_from_recent(user_id)
    except Exception as e:
        logger.error("Background learning failed for %s: %s", user_id, e)


async def _learn_from_recent(user_id: str) -> None:
    """Extract facts from recent conversation and update profile."""
    from app.cache import get_last_n_messages
    from app.memory.user_profile import get_user_profile_memory

    messages = await get_last_n_messages(user_id, n=20)
    if len(messages) < _MIN_MESSAGES_FOR_LEARNING:
        return

    # Format conversation for the LLM
    conversation_text = _format_conversation(messages)

    # Extract facts using a fast LLM call
    extracted = await _extract_facts(conversation_text)
    if not extracted:
        return

    facts = extracted.get("facts", [])
    preferences = extracted.get("preferences", {})
    habits = extracted.get("habits", [])
    active_plans = extracted.get("active_plans", [])

    # Merge active_plans into facts (they're the most important for proactive recall)
    if active_plans:
        facts = facts + [f"[ACTIVE] {p}" for p in active_plans]

    if not facts and not preferences and not habits:
        logger.debug("No new facts extracted for %s", user_id)
        return

    # Update user profile
    profile_memory = get_user_profile_memory()

    if facts:
        await profile_memory.add_facts(user_id, facts)
        logger.info("📝 Learned %d new facts for %s", len(facts), user_id)

    if preferences:
        await profile_memory.update_preferences(user_id, preferences)
        logger.info("📝 Updated %d preferences for %s", len(preferences), user_id)

    if habits:
        await profile_memory.add_habits(user_id, habits)

    # Regenerate summary if we have enough data
    profile = await profile_memory.get_profile(user_id)
    all_facts = profile.get("facts", [])
    if len(all_facts) >= 3:
        await _regenerate_summary(user_id, profile)


async def _extract_facts(conversation_text: str) -> Optional[Dict[str, Any]]:
    """Use LLM to extract facts from conversation."""
    try:
        from app.ai.providers.router import routed_chat

        prompt = _FACT_EXTRACTION_PROMPT.format(conversation=conversation_text)
        response, _ = await routed_chat(
            "summarize",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )

        if not response:
            return None

        # Parse JSON from response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[-1].rsplit("```", 1)[0]

        return json.loads(response)
    except (json.JSONDecodeError, Exception) as e:
        logger.debug("Fact extraction failed: %s", e)
        return None


async def _regenerate_summary(user_id: str, profile: Dict[str, Any]) -> None:
    """Regenerate the profile summary using all accumulated facts."""
    try:
        from app.ai.providers.router import routed_chat
        from app.memory.user_profile import get_user_profile_memory

        existing = profile.get("summary", "No existing summary.")
        facts = profile.get("facts", [])
        prefs = profile.get("preferences", {})
        habits = profile.get("habits", [])

        prompt = _SUMMARY_PROMPT.format(
            existing_summary=existing,
            new_facts="; ".join(facts),
            preferences=json.dumps(prefs),
            habits="; ".join(habits),
        )

        response, _ = await routed_chat(
            "summarize",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=250,
        )

        if response and len(response.strip()) > 20:
            await get_user_profile_memory().set_summary(user_id, response.strip())
            logger.info("📝 Profile summary regenerated for %s", user_id)
    except Exception as e:
        logger.debug("Summary regeneration failed: %s", e)


def _format_conversation(messages: List[Dict[str, Any]]) -> str:
    """Format messages into readable conversation text."""
    lines = []
    for msg in messages:
        role = msg.get("role", "user")
        content = str(msg.get("content", "")).strip()
        if content:
            prefix = "User" if role == "user" else "Assistant"
            lines.append(f"{prefix}: {content}")
    return "\n".join(lines[-20:])  # Last 20 turns max

"""
Tiered Memory Architecture for Spark.

Tier 1: User Profile Memory (0ms cost - lives in system prompt)
Tier 2: Parallel RAG (0ms felt - runs alongside STT)
Tier 3: Background Learning (0ms felt - runs after conversation)
"""

from app.memory.user_profile import UserProfileMemory, get_user_profile_memory

__all__ = ["UserProfileMemory", "get_user_profile_memory"]

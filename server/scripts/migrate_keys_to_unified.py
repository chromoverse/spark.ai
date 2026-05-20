"""
Migration script: Unify API key storage format.

1. MongoDB: Moves old individual fields (groq_api_keys, gemini_api_keys, etc.)
   into the unified api_keys dict, then removes old fields.

2. Windows Registry: Reads existing unscoped keys (GROQ_API_KEY, etc.)
   and re-saves them as {username}:{ENV_NAME} format.

Run once:
    cd server
    python -m app.scripts.migrate_keys_to_unified
"""
import asyncio
import sys
import os
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

OLD_FIELDS = [
    "groq_api_keys", "gemini_api_keys", "openrouter_api_keys",
    "cerebras_api_keys", "sambanova_api_keys", "mistral_api_keys",
    "gemini_api_key", "openrouter_api_key",
]

PROVIDER_FROM_FIELD = {
    "groq_api_keys": "groq",
    "gemini_api_keys": "gemini",
    "openrouter_api_keys": "openrouter",
    "cerebras_api_keys": "cerebras",
    "sambanova_api_keys": "sambanova",
    "mistral_api_keys": "mistral",
    "gemini_api_key": "gemini",
    "openrouter_api_key": "openrouter",
}


async def migrate_mongodb():
    """Migrate all users from old fields to api_keys dict."""
    from app.db.mongo import connect_to_mongo, get_db
    await connect_to_mongo()
    db = get_db()

    cursor = db.users.find({})
    migrated = 0

    async for user in cursor:
        api_keys = user.get("api_keys") or {}
        changed = False

        for field, provider in PROVIDER_FROM_FIELD.items():
            old_value = user.get(field)
            if not old_value:
                continue

            # Normalize: single string → list
            if isinstance(old_value, str):
                old_value = [old_value]

            # Merge into api_keys (don't overwrite if already has keys)
            existing = api_keys.get(provider) or []
            merged = list(set(existing + old_value))
            if merged:
                api_keys[provider] = merged
                changed = True

        if changed:
            # Set api_keys and remove old fields
            update = {"$set": {"api_keys": api_keys}, "$unset": {f: "" for f in OLD_FIELDS}}
            await db.users.update_one({"_id": user["_id"]}, update)
            migrated += 1
            logger.info(f"  ✅ Migrated user {user.get('username') or user['_id']}")
        else:
            # Just remove old fields if they exist (even if empty)
            has_old = any(user.get(f) is not None for f in OLD_FIELDS)
            if has_old:
                await db.users.update_one(
                    {"_id": user["_id"]},
                    {"$unset": {f: "" for f in OLD_FIELDS}}
                )

    logger.info(f"\n📦 MongoDB: {migrated} users migrated to api_keys dict format.")


def migrate_registry():
    """Migrate existing unscoped registry keys to username:ENV_NAME format."""
    if sys.platform != "win32":
        logger.info("⏭️  Skipping registry migration (not Windows)")
        return

    import winreg

    env_names = ["GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY",
                 "CEREBRAS_API_KEY", "SAMBANOVA_API_KEY", "MISTRAL_API_KEY"]

    # Ask for username
    username = input("Enter username for registry key scoping (e.g. 'siddhant'): ").strip()
    if not username:
        logger.error("Username required. Aborting registry migration.")
        return

    try:
        reg_key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Environment", 0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        )
    except OSError as e:
        logger.error(f"Cannot open registry: {e}")
        return

    migrated = 0
    try:
        for env_name in env_names:
            try:
                value, _ = winreg.QueryValueEx(reg_key, env_name)
                if not value:
                    continue
            except FileNotFoundError:
                continue

            # Write as username:ENV_NAME
            new_name = f"{username}:{env_name}"
            winreg.SetValueEx(reg_key, new_name, 0, winreg.REG_SZ, str(value))
            logger.info(f"  ✅ {env_name} → {new_name}")
            migrated += 1

            # Remove old unscoped key
            try:
                winreg.DeleteValue(reg_key, env_name)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(reg_key)

    logger.info(f"\n🔑 Registry: {migrated} keys migrated to {username}:* format.")


async def main():
    logger.info("=" * 50)
    logger.info("  API Key Migration: Unified Format")
    logger.info("=" * 50)
    logger.info("")

    logger.info("── Step 1: Migrate Windows Registry ──")
    migrate_registry()
    logger.info("")

    logger.info("── Step 2: Migrate MongoDB Users ──")
    await migrate_mongodb()
    logger.info("")

    logger.info("✅ Migration complete. All keys now use unified format.")


if __name__ == "__main__":
    asyncio.run(main())

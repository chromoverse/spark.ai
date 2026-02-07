LanceDB Integration Plan
Goal
Integrate LanceDB as a local vector store backend for the "desktop" environment. It will serve as a drop-in provider for both chat history (with semantic search) and user cache (key-value storage).

User Review Required
IMPORTANT

Schema:
user_queries: Stores chat history + vectors.
kv_store: Stores generic key-value pairs (for 
UserCache
).
Logic:
ChatCacheMixin
 and 
UserCacheMixin
 will be updated to route operations to LanceDB specific methods when in 'desktop' mode.
Generic Redis commands (
set
, 
get
, 
delete
) will be implemented in LanceDBManager backed by kv_store.
Proposed Changes
1. server/app/cache
[NEW] lancedb_manager.py
Class LanceDBManager:
Init: Connects to userdata/db/lanceData. Ensure tables user_queries and kv_store exist.
Schema Definition: Pydantic models for UserQuery and KeyValueItem.
Methods (Chat):
add_chat_message(user_id, role, content, vector, timestamp)
get_chat_history(user_id, limit) -> Returns list of dicts.
search_chat_messages(user_id, query_vector, limit, threshold) -> Returns weighted results.
Methods (Generic/KV):
set(key, value, ex=None) -> Upsert into kv_store. (Ignore ex expiry for now or store it).
get(key) -> Select value from kv_store.
delete(*keys) -> Delete from kv_store.
scan(match) -> Search keys in kv_store. (Low priority, but good for completeness).
[MODIFY] base_manager.py
BaseRedisManager._async_init:
Check settings.environment == "desktop".
If True: self.client = LanceDBManager(); self._is_lancedb = True.
2. server/app/cache/chat_cache.py
ChatCacheMixin:
add_message:
If self._is_lancedb:
Compute embedding via embedding_service.
self.client.add_chat_message(...).
Else: Existing Redis logic.
get_last_n_messages:
If self._is_lancedb: self.client.get_chat_history(...).
Else: Existing Redis logic.
semantic_search_messages:
If self._is_lancedb:
Compute embedding.
self.client.search_chat_messages(...).
Else: Existing logic.
3. server/app/cache/user_cache.py
UserCacheMixin:
Relies on self.set / self.get.
Since LanceDBManager implements set/get using kv_store, this requires NO CHANGE in UserCacheMixin logic itself, as long as BaseRedisManager delegates correctly!
Correction: BaseRedisManager.set calls self.client.set. If LanceDBManager.set exists, it works.
Verification
Run test_lancedb_integration.py (new test) to verify:
Chat flow (add, search, retrieve).
User cache flow (set details, get details).
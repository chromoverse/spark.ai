from app.db.pinecone.config import search_user_queries,get_user_all_queries
import json
import logging

from app.cache.redis.config import get_last_n_messages, process_query_and_get_context
logger = logging.getLogger(__name__)

query_context, is_pinecone_needed = process_query_and_get_context("user1", "When did i slept yesterday", search_user_queries, get_user_all_queries, threshold=0.2)
print(f"Query context from chat_service: {json.dumps(query_context, indent=2)}")
logger.info(f"Query context from chat_service: {json.dumps(query_context, indent=2)}")

#     # Get Local Context from redis
# local_context = get_last_n_messages("user_1", n=20)
# logger.info(f"local context from chat_service: {json.dumps(local_context, indent=2)}")
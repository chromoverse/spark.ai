from app.cache.redis.config import get_last_n_messages,compute_similarity,add_message,set_cache
from app.db.pinecone.config import search_user_queries,get_user_all_queries,upsert_query
import json
from app.utils.build_prompt import format_context,build_prompt


def test_format_context():
  text = "I implemented the electron now its time to implement websocket"
  recent_context = get_last_n_messages("guest")
  print("Recent context:", json.dumps(recent_context, indent=2))
  query_based_context = search_user_queries("guest", text)
  print("Query based context:", json.dumps(query_based_context, indent=2))

  recent_str, query_str = format_context(recent_context, [])

  # # print("Recent str:",recent_str)
  # print("Query str:",query_str)
  print("----------------------------------------------------------------------------------------------------------------")
  print("recent_str", recent_str)

  # print("----------------------------------------------------------------------------------------------------------------")
  # prompt = build_prompt("neutral", text, recent_context, query_based_context)
  # print(prompt)

test_format_context()  

# print(get_formatted_datetime())

open cmd and save the value as :  setx GROQ_API_KEY "[""REMOVED""]"

SUCCESS: Specified value was saved.
import os
import json
key = os.getenv("GROQ_API_KEY")
keys = json.loads(key)  # Parse the JSON array
print(keys)  # ['gsk_key1...', 'gsk_key2...']
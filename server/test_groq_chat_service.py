
from openai import OpenAI
import os
client = OpenAI(
    api_key="REMOVED",
    base_url="https://api.groq.com/openai/v1",
)

stream = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role":"user","content":"What is the meaning of life?"}],
    stream=True
)
 
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
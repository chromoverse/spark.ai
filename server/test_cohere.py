from openai import OpenAI

client = OpenAI(
    base_url="https://api.cohere.ai/compatibility/v1",
    api_key="",
)

completion = client.chat.completions.create(
    model="command-a-plus-05-2026",
    messages=[
        {
            "role": "user",
            "content": "Write a haiku about recursion in programming.",
        },
    ],
)

print(completion.choices[0].message)

stream = client.chat.completions.create(
    model="command-a-plus-05-2026",
    messages=[
        {
            "role": "user",
            "content": "Write a haiku about recursion in programming.",
        },
    ],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
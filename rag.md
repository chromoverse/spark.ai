What production voice assistants actually do

They separate memory into layers:

Layer	Purpose	Speed
Active Context	Current conversation	Instant
Working Memory	Recent important facts	Very fast
Semantic Memory (RAG)	Old searchable memories	Slower
Episodic Summaries	Session summaries	Medium

You need all 4.

Best practical architecture for your app
1. ACTIVE CONTEXT WINDOW (FASTEST)

Keep:

last 5–15 messages
recent tool results
current task state

Store in:

RAM
Zustand
Redis
in-memory Node cache

This is what realtime voice uses.

NO vector DB here.

Latency:

~1ms

Example:

session.activeMessages = [
  ...
]
2. WORKING MEMORY (MOST IMPORTANT)

This is the secret sauce.

Instead of searching entire RAG every turn:

Maintain:

user preferences
ongoing topics
current emotional/task state
temporary entities

Example:

{
  "userName": "Alex",
  "building": "AI interview app",
  "currentProblem": "audio latency",
  "preferredLanguage": "English"
}

Store:

Redis
in-memory cache
low latency KV store

This becomes:

SYSTEM MEMORY:
User is building AI interview app.
Current issue: realtime voice latency.

NO embedding search needed.

Latency:

~1–5ms

This solves 70% of “memory”.

3. SEMANTIC MEMORY / RAG

Use only when needed.

NOT every message.

Trigger retrieval only if:

user references old topic
assistant confidence low
long gap exists
“remember when…”
conversation topic changed

Bad:

Every user message -> vector search

Good:

Need memory?
  yes -> retrieve
  no -> skip

This alone massively improves speed.

4. SESSION SUMMARIZATION

Every X messages:

compress conversation
extract facts
create memory objects

Example:

{
  "type": "project",
  "content": "User building realtime AI interview platform",
  "importance": 0.92
}

Store in vector DB later asynchronously.

NEVER during realtime voice response.

Biggest mistake people make

They do this:

speech -> STT -> vector DB -> rerank -> LLM -> TTS

That kills latency.

Instead:

speech
 -> STT
 -> active memory only
 -> immediate response start
 -> async semantic retrieval if needed

The assistant should start speaking BEFORE deep retrieval finishes.

The best modern approach
Hybrid memory system
A. Hot Memory (RAM/Redis)

Fast temporary memory.

B. Warm Memory (Structured DB)

Recent summarized facts.

Use:

Postgres
MongoDB
C. Cold Memory (Vector DB)

Deep long-term retrieval.

Use:

Qdrant
Pinecone
Weaviate
FASTEST retrieval strategy

Do NOT vector search first.

First do:

metadata filtering

Example:

{
  "userId": "...",
  "project": "interview-app",
  "lastActive": "7d"
}

Then search only narrowed memories.

Huge speedup.

Ultra-fast production trick
Memory prefetching

While user is speaking:

run probable retrievals in background

Example:
User says:

“about that interview thing…”

Immediately prefetch:

interview memories
voice latency memories
avatar memories

By the time STT finishes:
memory already cached.

This is how advanced assistants feel instant.

Best stack for your use case

Since you're building realtime AI assistant:

Realtime layer
Redis
in-memory cache
Zustand (frontend)
Persistent structured memory
MongoDB/Postgres
Semantic memory
Qdrant (very fast)
pgvector if simpler
Streaming
WebSocket
LiveKit
WebRTC
Your ideal flow
User speaks
   ↓
Streaming STT
   ↓
Immediate context from RAM
   ↓
LLM starts streaming reply
   ↓
Background semantic retrieval
   ↓
If important memory found:
   inject into later response

NOT:

Wait for full RAG first
Another important thing

Most old memories are irrelevant.

You should rank memories by:

recency
emotional importance
frequency
task relevance

Not just cosine similarity.

If you want near-"instant"

Target:

Active memory only during first response token
RAG async after response starts

That is how you achieve “human-like” responsiveness.

True 1ms full semantic retrieval across years of memory is unrealistic once embeddings/vector search/networking are involved.

But perceived instant response is achievable with:

hot cache
memory layering
async retrieval
streaming responses
predictive prefetching

That is the real architecture used in serious assistants.
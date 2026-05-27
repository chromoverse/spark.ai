The Real Problem

Your flow for hotel_search:

user query
→ DDGS search
→ scrape SEO pages
→ LLM extracts entities
→ rank entities

This is fundamentally weak for:

hotels
restaurants
local services
flights
products
events

Why?

Because:

SEO pages mention random cities
snippets are location-agnostic
“best hotels near me” often resolves globally
LLM extraction amplifies garbage
scraping introduces latency + hallucinated structure

The moment you scraped Yelp SEO pages, you already lost.

What Production Systems Actually Do

Real systems split search into 3 independent layers:

Type	Engine
Web knowledge	Search engine
Local/business/entity	Maps/Places APIs
Real-time actions	Browser automation

You currently merged all 3.

That is the architectural mistake.

Correct Architecture

You need intent-native retrieval.

1. Web Search ≠ Local Search

Your current:

hotel_search -> DDGS
restaurant_search -> DDGS
local_service -> DDGS

Wrong.

Replace with:

hotel_search -> Google Places / Maps
restaurant_search -> Maps API
local_service -> Maps API

Use:

Google Places API
Foursquare API
Mapbox Search
OpenStreetMap Nominatim + Overpass
SerpAPI Google Maps
Geoapify

Even OpenStreetMap alone will outperform your current system.

2. Stop Scraping SEO Articles For Entity Search

This:

site:hostelworld.com
site:tripadvisor.com
site:yelp.com

is poison for retrieval quality.

You are retrieving:

blogs
“Top 10 hotels”
affiliate pages
city lists
outdated rankings

Instead:

location coords
→ nearby places API
→ structured entities directly

No scraping.
No extraction.
No hallucinated parsing.

3. Your LLM Extractor Is Being Used Incorrectly

LLMs should normalize entities, not discover them from garbage HTML.

Bad:

HTML → LLM entity extraction

Better:

Places API JSON → LLM enrichment/ranking

LLM should:

summarize reviews
cluster amenities
infer vibe
personalize ranking

NOT parse random pages.

4. Your Ranker Is Too Primitive

Keyword overlap is weak for entity retrieval.

For hotels/restaurants you need weighted ranking:

score =
distance_weight +
rating_weight +
review_count_weight +
open_now +
price_match +
query_embedding_similarity +
popularity +
trust_score

Right now:

no geo scoring
no semantic locality
no proximity decay
no business confidence

So Miami ranks despite Kathmandu coords existing.

5. Your Query Expansion Is Hurting Results

This:

site:budgetyourtrip.com cheap hotels

is catastrophic.

You injected:

“cheap”
“budget”
“hostel”
generic tourism SEO

even though user asked:

best hotels near me

You corrupted intent.

6. Browser Agent Is Misused

Browser automation should be LAST-mile action execution.

NOT primary retrieval.

Correct usage:

booking
checkout
reservation
form filling
ticket purchasing

NOT:

“find nearby hotels”

Playwright is absurdly expensive for retrieval.

What You Should Build Instead
Recommended Search Stack
A. Knowledge Search

Keep DDGS/Bing/Brave for:

factual lookup
research
news
technical topics

Good enough.

B. Local Entity Search

Create dedicated provider abstraction:

class LocalEntityProvider:
    async def search_hotels(...)
    async def search_restaurants(...)
    async def search_places(...)

Backends:

Google Places
Foursquare
Geoapify
OSM Overpass

Response:

{
  "name": "",
  "lat": "",
  "lng": "",
  "rating": 4.7,
  "reviews": 1200,
  "price_level": 3,
  "open_now": true,
  "photos": [],
  "address": "",
  "maps_url": ""
}

This alone fixes 70% of your problem.

C. Semantic Re-ranking

After retrieval:

embed query
embed entity metadata
rerank semantically

Example:

“quiet luxury hotel”
“good for remote work”
“cheap but clean”
“family friendly”

Traditional keyword rankers fail here.

Use:

bge-small
jina embeddings
nomic embeddings
voyage
e5-small
7. Add Geo Hard Constraints

This is critical.

Before ranking:

if distance_km > 50:
    discard()

Right now you have no geographic hard filter.

That is why Miami survived.

8. You Need Intent Router Before Retrieval

Current:

query → web research

Correct:

query
→ classify intent
→ choose retrieval system

Example:

Intent	Retrieval
factual	web search
nearby entities	maps API
shopping	shopping API
booking	browser automation
academic	scholarly search
realtime	news/search
9. Your Latency Is Too High

18.9s is unacceptable.

Production target:

local search: 1–3s
web research: 5–10s
browser action: 10–30s

Your pipeline:

search
→ scrape
→ extract
→ enrich

is serially expensive.

Remove scraping for local search entirely.

10. Biggest Missing Piece: Structured Sources

The modern AI stack trend is:

structured APIs > scraping

Scraping is fallback only.

You currently made scraping the foundation.

That is why quality collapses.

Immediate Fixes (Highest ROI)

Do these first:

Priority 1

Remove DDGS for:

hotels
restaurants
nearby places

Use Maps API only.

Priority 2

Add geo radius hard filter.

Priority 3

Kill SEO scraping for entity search.

Priority 4

Use embeddings for ranking.

Priority 5

Move browser automation to booking only.

What Spark Should Eventually Become

Your best long-term architecture:

Intent Router
    ↓
Retriever Layer
    ├── Web Search
    ├── Maps/Places
    ├── Shopping APIs
    ├── News APIs
    ├── Academic Search
    └── Browser Agent
            ↓
Semantic Re-ranker
            ↓
LLM Synthesizer
            ↓
Action Executor

That is the architecture used by serious AI assistants.

Right now Spark is overusing:

scraping
browser automation
LLM extraction

…and underusing:

structured retrieval
geo systems
semantic ranking
intent-native providers

That imbalance is the root cause.




## GUIDE.md — Spark Retrieval Architecture Redesign
Core Diagnosis

Spark currently uses a deterministic DAG executor to orchestrate non-deterministic retrieval systems.

This works well for:

OS automation
local tools
filesystem actions
deterministic workflows

It fails for:

local entity search
hotel discovery
restaurants
products
travel
geo-aware recommendations

because the retrieval stack is currently:

DDGS
→ scrape SEO pages
→ LLM extracts entities
→ rank

This pipeline is fundamentally unsuitable for high-quality entity retrieval.

PRIMARY ARCHITECTURAL CHANGE

Spark must split retrieval into 3 independent subsystems.

1. Knowledge Retrieval

Purpose:

factual lookup
research
technical knowledge
news
general web understanding

Current stack:

DDGS
scrape
summarize

This is acceptable.

Keep:

web_search
web_research(research)
scrape.py

Do NOT use these for local entity discovery.

2. Structured Entity Retrieval

Purpose:

hotels
restaurants
places
local businesses
nearby services
flights
products

This must become API-first.

Current approach:

search → scrape → extract

New approach:

provider APIs
→ normalize
→ semantic rerank
→ enrich
3. Transactional Action Layer

Purpose:

booking
checkout
reservations
authenticated browsing
purchases

Current BrowserAgent should move here.

Browser automation must NOT be used as a retrieval engine.

CRITICAL RULES
Rule 1 — Never Use DDGS For Nearby Entity Search

REMOVE DDGS retrieval for:

hotel_search
restaurant_search
local_service
place_search

These intents must NEVER touch SEO search as primary retrieval.

Allowed fallback only.

Rule 2 — Retrieval Must Be Structured First

The preferred hierarchy:

Structured API
→ Maps provider
→ specialized provider
→ browser extraction
→ web scrape

NOT the reverse.

Rule 3 — LLMs Must Not Discover Entities From HTML

LLMs should:

enrich
summarize
rerank
cluster
personalize

LLMs should NOT:

parse arbitrary HTML into trusted entities

The current entity_extractor introduces silent corruption.

NEW TARGET ARCHITECTURE
User Query
    ↓
Intent Router
    ↓
Retrieval Strategy Selector
    ↓
Retriever
    ├── Web Search
    ├── Maps Provider
    ├── Product Provider
    ├── News Provider
    ├── Browser Agent
    └── Scraper Fallback
            ↓
Normalization Layer
            ↓
Geo Validation
            ↓
Semantic Reranker
            ↓
LLM Enrichment
            ↓
Response Formatter
PHASE 1 — IMMEDIATE FIXES
1. Remove Entity Search From web_search

Current anti-pattern:

hotel_search -> DDGS

Replace with:

hotel_search -> local_entity_provider
2. Build LocalEntityProvider

Create:

server/plugins/installed/web/providers/

Add:

local_entity_provider.py
maps_provider.py
geo_provider.py
provider_models.py
provider_registry.py
3. Introduce Provider Abstraction
class LocalEntityProvider(ABC):
    async def search_hotels(...)
    async def search_restaurants(...)
    async def search_places(...)

All providers normalize into a shared schema.

4. Add Structured Entity Schema

Replace LLM-discovered entities with provider-normalized entities.

Required schema:

class PlaceEntity(BaseModel):
    id: str
    source: str

    name: str
    category: str

    latitude: float
    longitude: float
    address: str

    rating: float | None
    review_count: int | None
    price_level: int | None

    images: list[str]
    description: str | None

    maps_url: str | None
    website: str | None

    confidence: float
5. Add Geo Hard Filtering

Current problem:
Kathmandu query returns Miami hotels.

Cause:
No geographic constraints exist.

Fix:

distance_km = haversine(user_coords, entity_coords)

if distance_km > MAX_RADIUS_KM:
    discard()

Recommended:

hotel_search: 30km
restaurant_search: 15km
local_service: 25km

Hard discard.
Not reranking.

6. Pass Coordinates Everywhere

Current:

location_string = "Kathmandu, Bagmati Province"

Insufficient.

Change current_location output:

{
  "city": "Kathmandu",
  "country": "Nepal",
  "latitude": 27.7103,
  "longitude": 85.3222
}

Coordinates must propagate through:

SQH bindings
research.py
providers
ranker
PHASE 2 — REMOVE LLM CORRUPTION
7. Reduce entity_extractor Responsibility

Current:

HTML → LLM → entities

New:

Provider JSON → normalized entities

LLM extraction becomes fallback-only.

8. Add Entity Verification Layer

Before ranking:

verify_entity(entity)

Checks:

coordinates valid
city matches user region
rating range sane
review count sane
URL reachable
source trustworthy

Reject low-confidence entities.

9. Add Confidence Scoring

Every entity must include:

confidence: float

Derived from:

provider trust
geo match
field completeness
semantic relevance
source quality
PHASE 3 — SEMANTIC RETRIEVAL
10. Add Embeddings

Spark currently has zero semantic retrieval.

This is a major weakness.

Add:

server/shared/embeddings/

Recommended models:

bge-small-en-v1.5
nomic-embed-text
jina-embeddings-v2-small
e5-small

Cloud acceptable initially.

11. Replace Keyword Overlap Relevance

Current:

len(query_words ∩ entity_words)

This is extremely weak.

Replace with:

cosine_similarity(
    embed(query),
    embed(entity_text)
)

Entity text:

name + description + tags + amenities + reviews
12. Redesign ranker.py

New scoring:

score =
0.35 semantic_similarity +
0.20 rating +
0.15 review_confidence +
0.15 geo_proximity +
0.10 source_trust +
0.05 personalization

NOT:

rating + cheapness
PHASE 4 — BROWSER AGENT REPOSITIONING
13. BrowserAgent Must Become Transactional

Current:
retrieval-oriented

Target:
action-oriented

Use for:

booking
checkout
reservations
ticketing
authenticated flows

NOT:

nearby discovery
entity retrieval
14. Add Session-Aware Browser Mode

Future architecture:

Anonymous BrowserAgent
Authenticated BrowserAgent

Authenticated mode:

user Chrome profile
cookies
session persistence

Required for:

Booking.com
Agoda
airline flows
e-commerce checkout
PHASE 5 — INTENT SYSTEM REDESIGN
15. Replace Prompt-Only Intent Detection

Current SQH intent routing is fragile.

Add deterministic pre-router.

Example:

LOCAL_ENTITY_PATTERNS = [
    "near me",
    "best hotels",
    "restaurants nearby",
]

Fast deterministic override before LLM.

16. Add Intent Confidence

Current:
binary execution.

Required:

IntentResult(
    intent="hotel_search",
    confidence=0.82
)

If confidence low:

clarify
fallback
broaden
PHASE 6 — CACHING
17. Add Redis

Current:
30-second in-memory cache.

Insufficient.

Need:

Redis
persistent query cache
normalized cache keys
18. Cache Provider Results

Nearby entity queries are highly cacheable.

Example:

hotels near kathmandu

TTL:

10–30 minutes

This massively reduces latency and cost.

PHASE 7 — RESEARCH VS RETRIEVAL SPLIT
19. Split web_research Into Two Tools

Current tool is overloaded.

Split into:

web_research
entity_search

Different architectures.
Different guarantees.
Different pipelines.

20. Remove Scraping From entity_search

Allowed only as fallback.

Primary flow must be:

structured retrieval
PHASE 8 — LONG TERM ARCHITECTURE
21. Spark Should Become Three Engines
A. Knowledge Engine

Research, summarization, learning.

B. Action Engine

Browser automation, execution.

C. Personal OS Engine

Files, apps, local tools.

These share orchestration infrastructure but NOT retrieval logic.

MOST IMPORTANT ARCHITECTURAL INSIGHT

Your DAG executor is not the problem.

Your retrieval substrate is.

The executor assumes:

deterministic tools
predictable outputs
stable schemas

Web retrieval violates all of these.

Therefore:

deterministic orchestration
probabilistic retrieval
must be separated.
WHAT NOT TO DO

Do NOT:

add more scraping
add more site templates
add more prompt engineering
add more regexes
increase timeouts
add more extraction examples

Those will increase complexity without fixing retrieval quality.

HIGHEST ROI IMPLEMENTATION ORDER
Add coordinates everywhere
Add geo hard filtering
Replace DDGS for nearby entity search
Add LocalEntityProvider
Add semantic embeddings
Redesign ranker
Reduce LLM extraction
Split retrieval vs action systems
Add Redis
Add transactional browser flows
EXPECTED RESULTS AFTER REFACTOR

Current:

10–20s latency
wrong cities
SEO garbage
hallucinated entities
inconsistent ranking

After redesign:

1–4s local retrieval
geographically correct results
structured entities
semantic relevance
lower hallucination rate
lower token usage
lower scrape dependency
more scalable architecture
FINAL NOTE

Spark already has:

a solid orchestration core
a good plugin system
deterministic execution
replanning infrastructure
local OS capability

The weakness is specifically:
retrieval architecture.

Do not rebuild the agent system.

Rebuild the retrieval substrate.
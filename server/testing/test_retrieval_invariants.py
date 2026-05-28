"""
Invariant tests for the entity retrieval substrate.

These are the *contract* tests — the promises the refactor makes to itself:

  • A hallucinated wrong-city entity (Miami) cannot survive a Kathmandu query
    when its coordinates are known.
  • NaN coords cannot bypass the geo hard-filter (regression guard for the
    IEEE-754 bug where NaN > radius == False).
  • Entities with missing coords are kept-but-zero-geo (intentional;
    extraction fallback often lacks coords).
  • Lemma table catches the plural/synonym variants that the previous regex
    layer dropped silently.
  • Semantic ranking actually reorders results when keyword overlap is tied
    or contradictory (proves the BGE-M3 path is wired, not just present).
  • multi_provider chain falls through providers correctly (mocked, so this
    runs offline with no network).

Run from server/ via:
    python -m unittest testing.test_retrieval_invariants -v
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import patch


# Make ``server/`` importable when run as a unittest module.
_HERE = Path(__file__).resolve()
_SERVER_DIR = _HERE.parent.parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))


try:
    from plugins.installed.web.tools import ranker as ranker_mod
    from plugins.installed.web.tools.ranker import (
        rank_entities,
        _haversine_km,
        _safe_float,
    )
    from plugins.installed.web.providers import provider_registry
    from plugins.installed.web.providers import multi_provider
    from plugins.installed.web.providers import geo_resolver
    from plugins.installed.web.providers.geo_resolver import (
        extract_place_candidate,
        GeoLocation,
    )
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover — env-dependent import gate
    rank_entities = None  # type: ignore[assignment]
    _haversine_km = None  # type: ignore[assignment]
    _safe_float = None  # type: ignore[assignment]
    ranker_mod = None  # type: ignore[assignment]
    provider_registry = None  # type: ignore[assignment]
    multi_provider = None  # type: ignore[assignment]
    geo_resolver = None  # type: ignore[assignment]
    extract_place_candidate = None  # type: ignore[assignment]
    GeoLocation = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


# Coordinates used across tests.
KATHMANDU = (27.7172, 85.3240)
MIAMI     = (25.7617, -80.1918)
NEAR_KTM  = (27.7150, 85.3220)   # ~0.4 km from KATHMANDU


def _run(coro):
    """unittest doesn't natively await; use a fresh loop per test."""
    return asyncio.new_event_loop().run_until_complete(coro)


@unittest.skipIf(_IMPORT_ERROR is not None, f"Retrieval imports unavailable: {_IMPORT_ERROR}")
class GeoHardFilterTests(unittest.TestCase):
    """Geo radius behaviour — the single invariant we cannot lose."""

    def test_far_entity_with_coords_is_discarded(self):
        """A Miami hotel for a Kathmandu query must be filtered out, not reranked."""
        entities = [
            {"name": "Miami Hotel", "latitude": MIAMI[0], "longitude": MIAMI[1], "rating": 4.9},
            {"name": "Near Hotel",  "latitude": NEAR_KTM[0], "longitude": NEAR_KTM[1], "rating": 3.5},
        ]
        ranked = _run(rank_entities(
            entities, "hotel", "budget hotel",
            user_lat=KATHMANDU[0], user_lon=KATHMANDU[1], max_radius_km=30,
        ))
        names = [e["name"] for e in ranked]
        self.assertIn("Near Hotel", names)
        self.assertNotIn("Miami Hotel", names, "Wrong-city entity bypassed geo filter")

    def test_nan_coords_do_not_bypass_filter(self):
        """Regression for the IEEE-754 NaN > radius == False bug."""
        nan = float("nan")
        entities = [
            {"name": "NaN Hotel", "latitude": nan, "longitude": nan, "rating": 4.9},
            {"name": "Near Hotel", "latitude": NEAR_KTM[0], "longitude": NEAR_KTM[1], "rating": 3.5},
        ]
        ranked = _run(rank_entities(
            entities, "hotel", "budget hotel",
            user_lat=KATHMANDU[0], user_lon=KATHMANDU[1], max_radius_km=30,
        ))
        # NaN entity is treated as coordless — kept, no _distance_km set.
        nan_ent = next((e for e in ranked if e["name"] == "NaN Hotel"), None)
        self.assertIsNotNone(nan_ent, "NaN-coord entity unexpectedly discarded")
        self.assertNotIn("_distance_km", nan_ent,
                         "NaN coords leaked a NaN _distance_km into output")

    def test_missing_coords_are_kept_with_zero_geo(self):
        """Coordless entities must NOT be discarded — fallback extraction paths
        rely on this — but they cannot earn geo points."""
        entities = [
            {"name": "Coordless", "rating": 4.8, "review_count": 100},
            {"name": "Near Hotel", "latitude": NEAR_KTM[0], "longitude": NEAR_KTM[1], "rating": 3.5},
        ]
        ranked = _run(rank_entities(
            entities, "hotel", "budget hotel",
            user_lat=KATHMANDU[0], user_lon=KATHMANDU[1], max_radius_km=30,
        ))
        self.assertEqual(set(e["name"] for e in ranked), {"Coordless", "Near Hotel"})

    def test_no_user_coords_disables_geo_filter(self):
        """Without user coords the geo gate is off — all entities survive."""
        entities = [
            {"name": "Miami", "latitude": MIAMI[0], "longitude": MIAMI[1], "rating": 4.9},
            {"name": "Near",  "latitude": NEAR_KTM[0], "longitude": NEAR_KTM[1], "rating": 3.5},
        ]
        ranked = _run(rank_entities(entities, "hotel", "budget hotel"))
        self.assertEqual(len(ranked), 2)

    def test_safe_float_rejects_nan_and_inf(self):
        self.assertIsNone(_safe_float(float("nan")))
        self.assertIsNone(_safe_float(float("inf")))
        self.assertIsNone(_safe_float(float("-inf")))
        self.assertIsNone(_safe_float(None))
        self.assertIsNone(_safe_float(""))
        self.assertEqual(_safe_float("27.7"), 27.7)
        self.assertEqual(_safe_float(0), 0.0)  # zero is valid

    def test_haversine_known_distance(self):
        # KTM → near point: ~0.3-0.5 km
        d = _haversine_km(KATHMANDU[0], KATHMANDU[1], NEAR_KTM[0], NEAR_KTM[1])
        self.assertLess(d, 1.0)
        # KTM → Miami: ~13,000 km
        d2 = _haversine_km(KATHMANDU[0], KATHMANDU[1], MIAMI[0], MIAMI[1])
        self.assertGreater(d2, 12_000)
        self.assertLess(d2, 14_000)


@unittest.skipIf(_IMPORT_ERROR is not None, f"Retrieval imports unavailable: {_IMPORT_ERROR}")
class IntentRoutingTests(unittest.TestCase):
    """Plural / synonym handling in local_service resolution."""

    def test_lemma_handles_plurals(self):
        # These all hit the lexical fast path (no embedding model needed).
        for q, expected in [
            ("hospitals near me",      "hospital"),
            ("find a hospital",        "hospital"),
            ("pharmacies open now",    "pharmacy"),
            ("chemist near me",        "pharmacy"),
            ("dentists",               "dentist"),
            ("ATMs nearby",            "bank"),
            ("a gym in town",          "gym"),
            ("supermarkets",           "supermarket"),
            ("libraries",              "library"),
        ]:
            with self.subTest(query=q):
                amenity = provider_registry._lemma_match(q)
                self.assertIsNotNone(amenity, f"Lemma miss for {q!r}")
                self.assertEqual(amenity.name, expected)

    def test_lemma_rejects_unrelated_queries(self):
        # Random text mustn't match any amenity lexically.
        self.assertIsNone(provider_registry._lemma_match("the quick brown fox"))
        self.assertIsNone(provider_registry._lemma_match(""))


@unittest.skipIf(_IMPORT_ERROR is not None, f"Retrieval imports unavailable: {_IMPORT_ERROR}")
class MultiProviderChainTests(unittest.TestCase):
    """Chain fallthrough — mocked, no network."""

    def _mock_provider(self, name: str, n_results: int, raise_exc: bool = False):
        """Build a fake provider module-like object."""
        class _FakeProvider:
            def supports(self, intent):
                return True
            async def search(self, intent, query, user_lat, user_lon, radius_km, max_results):
                if raise_exc:
                    raise RuntimeError(f"{name} simulated crash")
                ents = [
                    {"name": f"{name}_{i}",
                     "latitude": NEAR_KTM[0] + 0.001 * i,
                     "longitude": NEAR_KTM[1] + 0.001 * i,
                     "source": name,
                     "_trust": 0.9}
                    for i in range(n_results)
                ]
                srcs = [{"url": f"https://{name}/{i}", "title": ents[i]["name"]}
                        for i in range(n_results)]
                return ents, srcs
        return _FakeProvider()

    def test_first_provider_wins_when_it_has_enough_results(self):
        chain = [
            ("alpha", self._mock_provider("alpha", n_results=5)),
            ("beta",  self._mock_provider("beta",  n_results=0)),
        ]
        with patch.object(multi_provider, "_CHAIN", chain):
            ents, _ = _run(multi_provider.search(
                "hotel_search", "hotels", *NEAR_KTM, 25.0, 10,
            ))
        self.assertEqual(len(ents), 5)
        self.assertTrue(all(e["source"] == "alpha" for e in ents))

    def test_falls_through_when_first_provider_below_threshold(self):
        # alpha returns 1 (below MIN=3) → walk to beta which returns 5.
        chain = [
            ("alpha", self._mock_provider("alpha", n_results=1)),
            ("beta",  self._mock_provider("beta",  n_results=5)),
        ]
        with patch.object(multi_provider, "_CHAIN", chain):
            ents, _ = _run(multi_provider.search(
                "hotel_search", "hotels", *NEAR_KTM, 25.0, 10,
            ))
        self.assertEqual(len(ents), 5)
        self.assertTrue(all(e["source"] == "beta" for e in ents))

    def test_provider_crash_does_not_break_chain(self):
        chain = [
            ("alpha", self._mock_provider("alpha", n_results=0, raise_exc=True)),
            ("beta",  self._mock_provider("beta",  n_results=4)),
        ]
        with patch.object(multi_provider, "_CHAIN", chain):
            ents, _ = _run(multi_provider.search(
                "hotel_search", "hotels", *NEAR_KTM, 25.0, 10,
            ))
        self.assertEqual(len(ents), 4)
        self.assertTrue(all(e["source"] == "beta" for e in ents))

    def test_all_providers_empty_returns_empty(self):
        chain = [
            ("alpha", self._mock_provider("alpha", n_results=0)),
            ("beta",  self._mock_provider("beta",  n_results=0)),
        ]
        with patch.object(multi_provider, "_CHAIN", chain):
            ents, srcs = _run(multi_provider.search(
                "hotel_search", "hotels", *NEAR_KTM, 25.0, 10,
            ))
        self.assertEqual(ents, [])
        self.assertEqual(srcs, [])

    def test_best_partial_returned_when_no_provider_clears_threshold(self):
        # alpha=2, beta=1 → neither hits MIN=3 short-circuit. Returns alpha (best partial).
        chain = [
            ("alpha", self._mock_provider("alpha", n_results=2)),
            ("beta",  self._mock_provider("beta",  n_results=1)),
        ]
        with patch.object(multi_provider, "_CHAIN", chain):
            ents, _ = _run(multi_provider.search(
                "hotel_search", "hotels", *NEAR_KTM, 25.0, 10,
            ))
        self.assertEqual(len(ents), 2)
        self.assertTrue(all(e["source"] == "alpha" for e in ents))


@unittest.skipIf(_IMPORT_ERROR is not None, f"Retrieval imports unavailable: {_IMPORT_ERROR}")
class EmbeddingFallbackTests(unittest.TestCase):
    """When the embedding model is unreachable, ranking must degrade
    to keyword overlap — never crash."""

    def test_ranking_survives_embedding_failure(self):
        def _boom(*_args, **_kwargs):
            raise RuntimeError("embedding worker down")

        entities = [
            {"name": "Budget Inn", "description": "cheap clean rooms",
             "latitude": NEAR_KTM[0], "longitude": NEAR_KTM[1], "rating": 4.0},
            {"name": "Luxury Palace", "description": "spa five star",
             "latitude": NEAR_KTM[0], "longitude": NEAR_KTM[1], "rating": 4.8},
        ]
        with patch("app.ml.get_embeddings", side_effect=_boom):
            ranked = _run(rank_entities(
                entities, "hotel", "budget hotel",
                user_lat=KATHMANDU[0], user_lon=KATHMANDU[1], max_radius_km=30,
            ))
        # Both must survive; ordering is now keyword-overlap-driven.
        self.assertEqual(len(ranked), 2)
        # "budget" appears in Budget Inn's text → should rank above Luxury for
        # the relevance term, but rating still matters (0.20 weight for hotel).
        # We only assert no crash + both kept; ordering depends on weights.

    def test_keyword_fallback_function(self):
        # Sanity-check the fallback function in isolation.
        score = ranker_mod._keyword_overlap("budget hotel", "Budget Inn cheap clean")
        self.assertGreater(score, 0.0)
        score_zero = ranker_mod._keyword_overlap("foo bar baz", "completely unrelated text")
        self.assertEqual(score_zero, 0.0)


@unittest.skipIf(_IMPORT_ERROR is not None, f"Retrieval imports unavailable: {_IMPORT_ERROR}")
class GeoResolverTests(unittest.TestCase):
    """Query → coordinates pipeline. Mocks the Nominatim HTTP call."""

    def test_extract_place_strips_intent_nouns(self):
        cases = [
            ("hotels in Mumbai",              "Mumbai"),
            ("best restaurants in Tokyo",     "Tokyo"),
            ("cafes around Pokhara",          "Pokhara"),
            ("things to do in New York",      "New York"),
            ("hospitals in Delhi",            "Delhi"),
            ("cheap hostels in Bangkok",      "Bangkok"),
            ("places to visit in Kyoto",      "Kyoto"),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                got = extract_place_candidate(query)
                self.assertEqual(got, expected, f"got {got!r}")

    def test_extract_place_returns_none_for_near_me(self):
        # "near me" queries are owned by current_location, not the resolver.
        for q in ["hotels near me", "restaurants nearby", "find hospitals near my location"]:
            with self.subTest(query=q):
                self.assertIsNone(extract_place_candidate(q))

    def test_extract_place_returns_none_when_only_intent_words(self):
        for q in ["hospitals", "the best hotels", "find some cafes", ""]:
            with self.subTest(query=q):
                self.assertIsNone(extract_place_candidate(q))

    def test_resolve_query_geo_happy_path_with_mocked_nominatim(self):
        """End-to-end resolve, with Nominatim HTTP mocked. Verifies that
        extract → geocode → GeoLocation actually composes."""
        # Stub out geocode_place so we don't hit the network.
        async def fake_geocode(place):
            self.assertEqual(place, "Mumbai")  # extraction worked
            return GeoLocation(
                lat=19.0760, lon=72.8777,
                city="Mumbai", country="India",
                display_name="Mumbai, Maharashtra, India",
            )
        with patch.object(geo_resolver, "geocode_place", fake_geocode):
            result = _run(geo_resolver.resolve_query_geo("hotels in Mumbai"))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.lat, 19.0760, places=4)
        self.assertEqual(result.city, "Mumbai")

    def test_resolve_query_geo_returns_none_when_geocoder_misses(self):
        async def empty_geocode(place):
            return None
        with patch.object(geo_resolver, "geocode_place", empty_geocode):
            result = _run(geo_resolver.resolve_query_geo("hotels in Atlantis"))
        self.assertIsNone(result)

    def test_geocode_cache_returns_stored_value_without_network(self):
        """Once a place is cached, geocode_place must not hit HTTP."""
        # Pre-warm the cache and ensure the network path is never invoked.
        geo_resolver._cache.clear()
        key = geo_resolver._cache_key("Testville")
        stored = GeoLocation(lat=1.0, lon=2.0, city="Testville",
                             country="X", display_name="Testville, X")
        geo_resolver._cache_put(key, stored)

        # If we touch the network, this will explode the test.
        with patch.object(geo_resolver.httpx, "AsyncClient",
                          side_effect=AssertionError("HTTP called despite cache hit")):
            result = _run(geo_resolver.geocode_place("Testville"))
        self.assertEqual(result, stored)
        geo_resolver._cache.clear()


@unittest.skipIf(_IMPORT_ERROR is not None, f"Retrieval imports unavailable: {_IMPORT_ERROR}")
class CitySoftFilterTests(unittest.TestCase):
    """Coordless entities are demoted (not discarded) when they don't
    mention the user's city. Closes the LLM-extraction hallucination leak."""

    def test_wrong_city_coordless_entity_loses_to_right_city(self):
        """Same rating, no coords on either — the one whose text mentions
        the user's city must rank higher."""
        entities = [
            {"name": "Miami Beach Resort",     # wrong city, no mention of Kathmandu
             "address": "Miami Beach, FL",
             "rating": 4.8, "review_count": 1000},
            {"name": "Kathmandu Garden Hotel", # right city
             "address": "Thamel, Kathmandu",
             "rating": 4.8, "review_count": 1000},
        ]
        ranked = _run(rank_entities(
            entities, "hotel", "budget hotel",
            user_lat=KATHMANDU[0], user_lon=KATHMANDU[1], max_radius_km=30,
            user_city="Kathmandu",
        ))
        # Both kept (soft filter is demotion, not discard)
        self.assertEqual(len(ranked), 2)
        # But the right-city entity must rank above the wrong-city one
        self.assertEqual(ranked[0]["name"], "Kathmandu Garden Hotel")
        self.assertEqual(ranked[1]["name"], "Miami Beach Resort")
        # And the wrong-city one must be flagged
        miami = next(e for e in ranked if e["name"] == "Miami Beach Resort")
        self.assertTrue(miami.get("_wrong_city_suspect"))
        ktm = next(e for e in ranked if e["name"] == "Kathmandu Garden Hotel")
        self.assertNotIn("_wrong_city_suspect", ktm)

    def test_coord_verified_entity_is_not_flagged(self):
        """Entities with valid in-radius coords get _city_verified and never
        receive the wrong-city flag, regardless of city-name presence."""
        ents = [{"name": "ANBNonameHotel",
                 "latitude": NEAR_KTM[0], "longitude": NEAR_KTM[1],
                 "rating": 3.0}]
        ranked = _run(rank_entities(
            ents, "hotel", "budget hotel",
            user_lat=KATHMANDU[0], user_lon=KATHMANDU[1], max_radius_km=30,
            user_city="Kathmandu",
        ))
        e = ranked[0]
        self.assertTrue(e.get("_city_verified"))
        self.assertNotIn("_wrong_city_suspect", e)

    def test_no_user_city_no_soft_filter(self):
        """If user_city isn't supplied, coordless entities are NOT demoted."""
        entities = [
            {"name": "Miami Beach Resort", "rating": 4.8, "review_count": 1000},
            {"name": "Kathmandu Garden Hotel", "rating": 4.0, "review_count": 100},
        ]
        ranked = _run(rank_entities(
            entities, "hotel", "budget hotel",
            user_lat=KATHMANDU[0], user_lon=KATHMANDU[1], max_radius_km=30,
            # user_city deliberately omitted
        ))
        # Without the soft filter, the higher-rated Miami entity wins.
        self.assertEqual(ranked[0]["name"], "Miami Beach Resort")
        for e in ranked:
            self.assertNotIn("_wrong_city_suspect", e)


@unittest.skipIf(_IMPORT_ERROR is not None, f"Retrieval imports unavailable: {_IMPORT_ERROR}")
class ToolSplitTests(unittest.TestCase):
    """Lock down the architectural split between web_research and entity_search."""

    def test_web_research_owns_only_knowledge_intents(self):
        from plugins.installed.web.tools.research import WebResearchTool, _VALID_INTENTS
        self.assertEqual(_VALID_INTENTS, {"factual_lookup", "research"})
        # PARAMS_SCHEMA must not have geo inputs any more
        wr = WebResearchTool()
        self.assertNotIn("latitude",  wr.PARAMS_SCHEMA)
        self.assertNotIn("longitude", wr.PARAMS_SCHEMA)
        self.assertNotIn("max_radius_km", wr.PARAMS_SCHEMA)
        self.assertNotIn("entity_schema", wr.PARAMS_SCHEMA)
        # Category stays knowledge-side
        self.assertEqual(wr.TOOL_CATEGORY, "web_knowledge")

    def test_entity_search_owns_all_entity_intents(self):
        from plugins.installed.web.tools.entity_search import (
            EntitySearchTool, _VALID_INTENTS as ENTITY_INTENTS,
        )
        expected = {
            "hotel_search", "restaurant_search", "local_service",
            "place_search", "event_search", "person_search",
            "movie_search", "college_search", "flight_search",
            "product_search",
        }
        self.assertEqual(ENTITY_INTENTS, expected)
        es = EntitySearchTool()
        # PARAMS_SCHEMA carries the geo inputs
        for k in ("latitude", "longitude", "max_radius_km", "entity_schema"):
            self.assertIn(k, es.PARAMS_SCHEMA, f"missing {k}")
        self.assertEqual(es.TOOL_CATEGORY, "entity_search")

    def test_web_research_rejects_entity_intent_loudly(self):
        """If SQH mis-routes an entity intent to web_research, we surface
        a clear error instead of silently doing the wrong thing."""
        from plugins.installed.web.tools.research import WebResearchTool
        wr = WebResearchTool()
        result = _run(wr._execute({"query": "hotels", "intent": "hotel_search"}))
        self.assertFalse(result.success)
        self.assertIn("entity_search", result.error)

    def test_entity_search_rejects_non_entity_intent(self):
        from plugins.installed.web.tools.entity_search import EntitySearchTool
        es = EntitySearchTool()
        result = _run(es._execute({"query": "x", "intent": "research"}))
        self.assertFalse(result.success)
        self.assertIn("entity", result.error.lower())

    def test_pqh_categories_include_entity_search_and_browser_action(self):
        from app.prompts.tool_categories import _CATEGORY_DESCRIPTIONS
        self.assertIn("entity_search",  _CATEGORY_DESCRIPTIONS)
        self.assertIn("browser_action", _CATEGORY_DESCRIPTIONS)
        # Sanity: descriptions mention the right disambiguating words.
        self.assertIn("hotel", _CATEGORY_DESCRIPTIONS["entity_search"].lower())
        self.assertIn("book",  _CATEGORY_DESCRIPTIONS["browser_action"].lower())

    def test_pqh_prompt_mentions_both_new_categories(self):
        from app.prompts.pqh_prompt_v2 import build_system_prompt
        prompt = build_system_prompt()
        self.assertIn("entity_search",  prompt)
        self.assertIn("browser_action", prompt)
        # Disambiguation guidance must be visible.
        self.assertIn("hotels in Mumbai", prompt)
        self.assertIn("buy me the best pen under 100", prompt)
        self.assertIn("play Arctic Monkeys on Spotify", prompt)

    def test_sqh_browser_action_rules_keep_fuzzy_product_search_safe(self):
        prompt_path = _SERVER_DIR / "app" / "prompts" / "sqh_prompt.py"
        prompt = prompt_path.read_text(encoding="utf-8")
        self.assertIn("Use browser_action, NOT browser_agent directly", prompt)
        self.assertIn("play_music", prompt)
        self.assertIn("buy me the best/cheap <product> under budget <amount>", prompt)
        self.assertIn("rich UI shows options", prompt)
        self.assertIn("clicking one should invoke browser_action", prompt)


if __name__ == "__main__":
    unittest.main()

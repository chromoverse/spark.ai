import json
import sys

try:
    from ddgs import DDGS
    with DDGS(timeout=10) as ddgs:
        res = list(ddgs.images(
            "Old House Cafe Kathmandu",
            max_results=5,
            safesearch="moderate",
        ))
        print("Success:")
        for r in res:
            print("Title:", r.get("title"))
            print("Image URL:", r.get("image"))
            print("Thumbnail URL:", r.get("thumbnail"))
            print("-" * 30)
except Exception as e:
    print("Error:", e)

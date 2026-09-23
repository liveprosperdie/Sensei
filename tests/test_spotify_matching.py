import os
import sys
from pathlib import Path
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import executor

class TestSpotifyMatching(unittest.TestCase):
    def test_spotify_search_starboy_ranking(self):
        sp, err = executor._spotify_client()
        if not sp:
            self.skipTest(f"Spotify client not configured: {err}")
        
        # Test that searching for 'Starboy' resolves to 'Starboy by The Weeknd'
        res = sp.search("Starboy", limit=5, type="track")
        items = res.get("tracks", {}).get("items", [])
        self.assertTrue(len(items) > 0, "No tracks returned for Starboy")
        
        want = "Starboy".strip().lower()
        best = next((t for t in items if want in t["name"].lower() or any(want in a["name"].lower() for a in t["artists"])), items[0])
        
        print(f"\n[Test] Matched: {best['name']} by {best['artists'][0]['name']} (id={best['id']})")
        self.assertIn("starboy", best["name"].lower())
        self.assertEqual(best["artists"][0]["name"], "The Weeknd")

if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from bot.helper.tmdb import FALLBACK_POSTER, fetch_metadata


class FetchMetadataTests(unittest.TestCase):
    def test_episode_caption_returns_direct_tmdb_and_episode_metadata(self):
        with patch("bot.helper.tmdb._request", return_value={"name": "Daredevil"}):
            metadata = fetch_metadata("262838/2/1")

        self.assertEqual(
            metadata,
            {
                "tmdb_id": 262838,
                "tmdb_type": "tv",
                "tmdb_title": "Daredevil",
                "season": 2,
                "episode": 1,
                "poster_url": FALLBACK_POSTER,
            },
        )

    def test_non_episode_caption_has_empty_episode_fields_without_tmdb_key(self):
        with patch("bot.helper.tmdb.TMDB_API_KEY", ""):
            metadata = fetch_metadata("A normal file name")

        self.assertIsNone(metadata["season"])
        self.assertIsNone(metadata["episode"])

    def test_search_result_includes_tmdb_title(self):
        with patch("bot.helper.tmdb.TMDB_API_KEY", "key"), patch(
            "bot.helper.tmdb._request",
            return_value={
                "results": [{"id": 11, "title": "The Matrix", "poster_path": "/poster.jpg"}]
            },
        ):
            metadata = fetch_metadata("The Matrix 1999")

        self.assertEqual(metadata["tmdb_title"], "The Matrix")


if __name__ == "__main__":
    unittest.main()

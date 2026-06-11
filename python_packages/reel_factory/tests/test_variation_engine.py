import unittest

from variation_engine import VariationConfig, get_pack_version, vary_caption_text


class VariationEngineTests(unittest.TestCase):
    def test_variation_off_preserves_text(self):
        text = "You and your friend should come over"
        self.assertEqual(vary_caption_text(text, "seed", mode="off"), text)

    def test_variation_is_deterministic(self):
        text = "You and your friend should come over"
        first = vary_caption_text(text, "same-seed", mode="auto")
        second = vary_caption_text(text, "same-seed", mode="auto")
        self.assertEqual(first, second)

    def test_variation_unknown_mode_raises(self):
        with self.assertRaisesRegex(ValueError, "unknown text variation mode"):
            vary_caption_text("hello", "seed", mode="wild")

    def test_pack_version_is_explicit(self):
        self.assertEqual(get_pack_version("default"), "default@1")
        self.assertEqual(VariationConfig(pack="default").version, "default@1")


if __name__ == "__main__":
    unittest.main()

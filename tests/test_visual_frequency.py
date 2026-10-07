from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from scripts.visual_frequency import compare, write_diff


class VisualFrequencyTests(unittest.TestCase):
    def test_identical_render_passes_with_perfect_score(self):
        img = Image.new("RGB", (320, 180), "#020812")
        draw = ImageDraw.Draw(img)
        draw.rectangle((20, 20, 300, 160), outline="#25c8ff", width=3)
        draw.line((20, 110, 300, 70), fill="#eef7ff", width=3)
        result = compare(img, img.copy())
        self.assertEqual(result["score"], 1.0)

    def test_large_blank_region_is_detected(self):
        ref = Image.new("RGB", (320, 180), "#020812")
        draw = ImageDraw.Draw(ref)
        draw.rectangle((10, 10, 310, 170), fill="#0d3555")
        draw.line((0, 130, 320, 40), fill="#eef7ff", width=5)

        candidate = Image.new("RGB", (320, 180), "#020812")
        candidate.paste(ref.crop((0, 0, 160, 180)).resize((160, 180)), (0, 0))
        result = compare(ref, candidate)
        self.assertLess(result["score"], 0.80)

    def test_diff_artifact_is_written(self):
        ref = Image.new("RGB", (64, 64), "black")
        cand = Image.new("RGB", (64, 64), "white")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diff.png"
            write_diff(ref, cand, path)
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()

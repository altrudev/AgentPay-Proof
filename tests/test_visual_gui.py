from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageDraw
from scripts.visual_frequency import compare

ROOT = Path(__file__).resolve().parents[1]

class ApprovedV6GuiTests(unittest.TestCase):
    def test_exact_approved_v6_assets_exist(self):
        root = ROOT / "web" / "assets" / "approved-v6"
        names = [
            "agentpay-mark.png","hero-background.webp","vyshyvanka-bridge.png",
            "proof-card-fan.png","icon-intent.png","icon-quote.png","icon-authority.png",
            "icon-settlement.png","icon-execution.png","icon-observation.png","icon-proof.png",
            "service-code-analysis.webp","service-data-research.webp","service-3d-generation.webp",
        ]
        for name in names:
            self.assertTrue((root / name).is_file(), name)

    def test_interface_is_single_proportional_scene(self):
        css = (ROOT / "web" / "styles.css").read_text()
        js = (ROOT / "web" / "app.js").read_text()
        self.assertIn("width:1672px;height:940px", css)
        self.assertIn("Math.min(innerWidth/1672,innerHeight/940)", js)
        self.assertIn('translate(-50%,-50%) scale(', js)

    def test_interface_uses_regenerated_art(self):
        html = (ROOT / "web" / "index.html").read_text()
        self.assertIn("/assets/approved-v6/hero-background.webp", html)
        self.assertIn("/assets/approved-v6/agentpay-mark.png", html)
        self.assertIn("/assets/approved-v6/vyshyvanka-bridge.png", html)
        self.assertIn("/assets/approved-v6/proof-card-fan.png", html)

    def test_runtime_truth_is_not_baked_into_art(self):
        html = (ROOT / "web" / "index.html").read_text()
        for target in ["network-block","network-gas","network-rpc","wallet-state","activity-list"]:
            self.assertIn(f'id="{target}"', html)
        for fake in ["8456721","0.0012 USDC","42 ms","7d 12h 46m","Base Sepolia"]:
            self.assertNotIn(fake, html)

    def test_visual_gate_penalizes_major_layout_loss(self):
        ref = Image.new("RGB",(320,180),"#03101c")
        d = ImageDraw.Draw(ref)
        d.rectangle((10,10,310,170),fill="#0d4168")
        d.line((0,145,320,45),fill="#ffffff",width=5)
        bad = Image.new("RGB",(320,180),"#03101c")
        bad.paste(ref.crop((0,0,160,180)),(0,0))
        self.assertLess(compare(ref,bad)["score"],.80)

if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text()
CSS = (ROOT / "web" / "styles.css").read_text()
JS = (ROOT / "web" / "app.js").read_text()


class ApprovedGuiContractTests(unittest.TestCase):
    def test_accessible_hero_copy_is_present(self):
        self.assertIn("LET AGENTS PAY.", HTML)
        self.assertIn("KEEP AUTHORITY", HTML)
        self.assertIn("VERIFIABLE.", HTML)
        self.assertIn("Autonomous agent commerce with real payments", HTML)
        self.assertIn("independently verifiable proof", HTML)

    def test_exact_approved_navigation_order(self):
        labels = ["Home", "Explore", "Run Service", "Proofs", "Developers", "Docs", "GitHub"]
        positions = [HTML.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_exact_seven_stage_order(self):
        labels = ["Intent", "Quote", "Authority", "Settlement", "Execution", "Observation", "Proof"]
        stage_markup = HTML.split("<ol>", 1)[1].split("</ol>", 1)[0]
        positions = [stage_markup.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_approved_surface_is_composed_from_reference_slices(self):
        assets = [
            "logo.png", "header.png", "sidebar.png", "hero.png", "flow.png",
            "featured.png", "activity.png", "status.png", "footer.png",
        ]
        for asset in assets:
            self.assertIn(f'/approved/{asset}', HTML)

    def test_reference_geometry_is_locked(self):
        self.assertIn("width:1672px;height:940px", CSS)
        expected = {
            ".art-logo": "left:28px;top:12px;width:442px;height:98px",
            ".art-header": "left:470px;top:0;width:1202px;height:112px",
            ".art-sidebar": "left:0;top:112px;width:198px;height:782px",
            ".art-hero": "left:198px;top:112px;width:1474px;height:309px",
            ".art-flow": "left:198px;top:421px;width:1474px;height:191px",
            ".art-footer": "left:0;top:894px;width:1672px;height:46px",
        }
        for selector, geometry in expected.items():
            self.assertIn(selector, CSS)
            self.assertIn(geometry, CSS)

    def test_art_fidelity_budget_is_bounded(self):
        approved = ROOT / "web" / "approved"
        files = list(approved.glob("*.png"))
        self.assertEqual(len(files), 9)
        total_bytes = sum(path.stat().st_size for path in files)
        self.assertLessEqual(total_bytes, 2_500_000)

    def test_runtime_truth_overlays_exist(self):
        for target in ["network-block", "network-gas", "network-rpc", "wallet-state", "activity-list"]:
            self.assertIn(f'id="{target}"', HTML)
        self.assertIn("/api/live/network", JS)
        self.assertIn("/api/live/reconcile", JS)

    def test_no_old_fake_network_telemetry_in_html_or_js(self):
        combined = HTML + JS
        for fake in ["8456721", "0.0012 USDC", "42 ms", "7d 12h 46m", "Base Sepolia"]:
            self.assertNotIn(fake, combined)

    def test_live_wallet_stays_explicit(self):
        self.assertIn("eth_requestAccounts", JS)
        self.assertIn("eth_sendTransaction", JS)
        self.assertIn("/api/live/abort", JS)
        self.assertIn("/api/live/uncertain", JS)


if __name__ == "__main__":
    unittest.main()

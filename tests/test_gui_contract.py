from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text()
CSS = (ROOT / "web" / "styles.css").read_text()
JS = (ROOT / "web" / "app.js").read_text()

ASSETS = [
    "agentpay-logo.png",
    "hero-background.png",
    "vyshyvanka-bridge.png",
    "proof-card-fan.png",
    "icon-intent.png",
    "icon-quote.png",
    "icon-authority.png",
    "icon-settlement.png",
    "icon-execution.png",
    "icon-observation.png",
    "icon-proof.png",
    "service-code-analysis.png",
    "service-data-research.png",
    "service-3d-generation.png",
]

class ApprovedGuiContractTests(unittest.TestCase):
    def test_approved_reference_identity(self):
        manifest = (ROOT / "web" / "assets" / "approved-v5" / "ASSET-MANIFEST.md").read_text()
        self.assertIn("AgentPay Proof Futuristic Dashboard(5).png", manifest)
        self.assertIn("b3ade8790ca78244e1e9961424632b1d3c6b410301d4dc5d089805869f8d9169", manifest)

    def test_semantic_hero_copy_is_present(self):
        for phrase in ["LET AGENTS PAY.", "KEEP AUTHORITY", "VERIFIABLE.", "Autonomous agent commerce with real payments"]:
            self.assertIn(phrase, HTML)

    def test_exact_stage_order(self):
        labels = ["Intent", "Quote", "Authority", "Settlement", "Execution", "Observation", "Proof"]
        positions = [HTML.index(f"<b>{label}</b>") for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_regenerated_assets_exist(self):
        root = ROOT / "web" / "assets" / "approved-v5"
        for name in ASSETS:
            self.assertTrue((root / name).is_file(), name)

    def test_interface_uses_regenerated_assets_not_slices(self):
        for name in ASSETS:
            self.assertIn(f"/assets/approved-v5/{name}", HTML)
        for old in ["/approved/logo.png", "/approved/header.png", "/approved/sidebar.png", "/approved/hero.png", "/approved/flow.png"]:
            self.assertNotIn(old, HTML)

    def test_reference_geometry_is_locked(self):
        self.assertIn("width:1672px;height:940px", CSS)
        self.assertIn("left:198px;top:112px;width:1474px;height:782px", CSS)

    def test_runtime_truth_remains_live(self):
        for target in ["network-block", "network-gas", "network-rpc", "wallet-state", "activity-list"]:
            self.assertIn(f'id="{target}"', HTML)
        self.assertIn("/api/live/network", JS)
        self.assertIn("/api/live/reconcile", JS)

    def test_no_fake_mock_telemetry(self):
        combined = HTML + JS
        for fake in ["8456721", "0.0012 USDC", "42 ms", "7d 12h 46m", "Base Sepolia"]:
            self.assertNotIn(fake, combined)

    def test_wallet_approval_is_explicit(self):
        self.assertIn("eth_requestAccounts", JS)
        self.assertIn("eth_sendTransaction", JS)
        self.assertIn("/api/live/abort", JS)
        self.assertIn("/api/live/uncertain", JS)

if __name__ == "__main__":
    unittest.main()

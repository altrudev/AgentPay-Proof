from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text()
CSS = (ROOT / "web" / "styles.css").read_text()
JS = (ROOT / "web" / "app.js").read_text()

ASSETS = [
    "agentpay-logo.svg",
    "hero-background.webp",
    "vyshyvanka-bridge-exact.webp",
    "proof-card-fan.svg",
    "icon-intent.svg",
    "icon-quote.svg",
    "icon-authority.svg",
    "icon-settlement.svg",
    "icon-execution.svg",
    "icon-observation.svg",
    "icon-proof.svg",
    "service-code-analysis.webp",
    "service-data-research.webp",
    "service-3d-generation.webp",
]

class ApprovedGuiContractTests(unittest.TestCase):
    def test_single_approved_reference_is_authoritative(self):
        manifest = (ROOT / "web" / "assets" / "approved-v6" / "ASSET-MANIFEST.md").read_text()
        self.assertIn("single user-approved AgentPay Proof mockup", manifest)
        self.assertIn("1672 × 940", manifest)
        self.assertIn("no earlier mockup", manifest)

    def test_semantic_hero_copy_is_present(self):
        for phrase in [
            "LET AGENTS PAY.",
            "KEEP AUTHORITY",
            "VERIFIABLE.",
            "Autonomous agent commerce with real payments",
        ]:
            self.assertIn(phrase, HTML)

    def test_exact_stage_order(self):
        labels = ["Intent", "Quote", "Authority", "Settlement", "Execution", "Observation", "Proof"]
        positions = [HTML.index(f"<b>{label}</b>") for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_production_assets_exist(self):
        root = ROOT / "web" / "assets" / "approved-v6"
        for name in ASSETS:
            self.assertTrue((root / name).is_file(), name)

    def test_interface_uses_v6_layered_assets(self):
        for name in ASSETS:
            self.assertIn(f"/assets/approved-v6/{name}", HTML)
        self.assertNotIn("/assets/approved-v6/flow-background.webp", HTML)
        for old in ["/approved/", "/assets/approved-v5/"]:
            self.assertNotIn(old, HTML)

    def test_reference_geometry_is_locked(self):
        self.assertIn("width:1672px;height:940px", CSS)
        self.assertIn("left:198px;top:112px;width:1474px;height:782px", CSS)
        self.assertIn("top:309px;width:100%;height:191px", CSS)

    def test_workflow_has_one_visual_flow_not_a_second_river_plate(self):
        self.assertNotIn("flow-background.webp", HTML)
        self.assertIn(".flow-line{position:absolute", CSS)

    def test_runtime_truth_remains_live(self):
        for target in ["network-block", "network-gas", "network-rpc", "wallet-state", "activity-list"]:
            self.assertIn(f'id="{target}"', HTML)
        self.assertIn("/api/live/network", JS)
        self.assertIn("/api/live/reconcile", JS)

    def test_no_fake_mock_telemetry(self):
        combined = HTML + JS
        for fake in ["8456721", "0.0012 USDC", "42 ms", "7d 12h 46m"]:
            self.assertNotIn(fake, combined)

    def test_wallet_approval_is_explicit(self):
        self.assertIn("eth_requestAccounts", JS)
        self.assertIn("eth_sendTransaction", JS)
        self.assertIn("/api/live/abort", JS)
        self.assertIn("/api/live/uncertain", JS)

    def test_populated_service_and_companion_surfaces_exist(self):
        for target in [
            "service-dialog", "service-title", "service-input", "service-submit",
            "proof-download", "artifact-download", "status-dialog",
        ]:
            self.assertIn(f'id="{target}"', HTML)
        self.assertIn("/api/catalog", JS)
        self.assertIn("openCompanion", JS)
        self.assertIn("sessionStorage", JS)

    def test_service_prices_are_runtime_catalog_values(self):
        self.assertIn('data-price="code"', HTML)
        self.assertIn('data-price="research"', HTML)
        self.assertIn('data-price="3d"', HTML)
        self.assertNotIn("<b>1.00 USDC</b>", HTML)

    def test_production_raster_budget_is_lightweight(self):
        root = ROOT / "web" / "assets" / "approved-v6"
        total = sum(p.stat().st_size for p in root.glob("*.webp"))
        self.assertLessEqual(total, 700_000)

if __name__ == "__main__":
    unittest.main()

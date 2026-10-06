from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text()
CSS = (ROOT / "web" / "styles.css").read_text()


class ApprovedGuiContractTests(unittest.TestCase):
    def test_exact_approved_hero_copy_is_present(self):
        self.assertIn("LET AGENTS PAY.", HTML)
        self.assertIn("KEEP AUTHORITY", HTML)
        self.assertIn("<em>VERIFIABLE.</em>", HTML)
        self.assertIn("Autonomous agent commerce with real payments,", HTML)
        self.assertIn("governed boundaries, and independently verifiable proof.", HTML)

    def test_exact_approved_navigation_order(self):
        labels = ["Home", "Explore", "Run Service", "Proofs", "Developers", "Docs", "GitHub"]
        positions = [HTML.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_exact_seven_stage_order(self):
        js = (ROOT / "web" / "app.js").read_text()
        labels = ["Intent", "Quote", "Authority", "Settlement", "Execution", "Observation", "Proof"]
        positions = [js.index(f'"{label}"') for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_front_page_has_only_approved_primary_actions(self):
        self.assertIn('id="run-service"', HTML)
        self.assertIn(">Run a Service <span>→</span>", HTML)
        self.assertIn('id="explore"', HTML)
        self.assertNotIn("Connect Wallet", HTML)
        self.assertNotIn("Run Demo", HTML)
        self.assertNotIn("Run Live", HTML)

    def test_approved_fixed_design_space_is_locked(self):
        self.assertIn("width:1672px;height:941px", CSS)
        self.assertIn("grid-template-columns:198px 1fr", CSS)
        self.assertIn("grid-template-rows:118px 1fr 43px", CSS)

    def test_no_old_fake_network_telemetry(self):
        for fake in ["8456721", "0.0012 USDC", "42 ms", "7d 12h 46m", "Base Sepolia"]:
            self.assertNotIn(fake, HTML)

    def test_approved_footer_identity(self):
        self.assertIn("© 2026&nbsp;&nbsp; Altru.dev", HTML)
        self.assertIn("AgentPay Proof", HTML)
        self.assertIn("Powered by Frequency assurance", HTML)


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

from src.webapp import Handler, ThreadingHTTPServer, run_demo, tamper_demo


class WebAppTests(unittest.TestCase):
    def test_authorized_demo_is_explicitly_demo_and_verified(self):
        out = run_demo(250_000, "TODO: inspect.", "code")
        self.assertEqual(out["environment"], "DEMO")
        self.assertEqual(out["status"], "VERIFIED")
        self.assertEqual(out["proof"]["settlement"]["transaction_hash"], "demo:not-on-chain")
        self.assertEqual(out["artifact"]["service_id"], "code-analysis-v1")

    def test_denied_demo_has_no_settlement(self):
        out = run_demo(2_000_000, "One.", "code")
        self.assertEqual(out["status"], "DENIED")
        self.assertIsNone(out["proof"]["settlement"])

    def test_tamper_endpoint_logic_fails_verification(self):
        out = run_demo(250_000, "One.", "code")
        tampered = tamper_demo(out["proof"])
        self.assertEqual(tampered["verification"]["verdict"], "NOT VERIFIED")

    def test_commercial_demo_endpoint_plans_but_never_executes(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/commercial/demo") as r:
                data = json.load(r)
                self.assertEqual(data["schema"], "agentpay-commercial-demo/1")
                self.assertEqual(data["plan"]["selected_offer_id"], "privacy-render-validator")
                self.assertEqual(data["execution"]["status"], "NOT_EXECUTED")
                self.assertTrue(data["plan"]["requires_human_approval"])
        finally:
            server.shutdown()
            server.server_close()

    def test_commercial_prepare_and_explicit_execute_reference_boundary(self):
        fd, db_path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(db_path)
        previous = os.environ.get("AGENTPAY_COMMERCIAL_STATE_DB")
        os.environ["AGENTPAY_COMMERCIAL_STATE_DB"] = db_path
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/commercial/prepare-demo") as r:
                prepared = json.load(r)
            self.assertEqual(prepared["status"], "PREPARED")
            self.assertEqual(prepared["execution"], "NOT_DISPATCHED")
            self.assertTrue(prepared["requires_human_approval"])

            payload = json.dumps({
                "grant_id": prepared["grant"]["grant_id"],
                "approval_digest": prepared["approval_digest"],
                "rendered_page_digest": "rendered:test",
                "reference_digest": "reference:test",
            }).encode()
            req = Request(
                f"http://127.0.0.1:{server.server_port}/api/commercial/execute-demo",
                data=payload,
                method="POST",
                headers={"content-type": "application/json"},
            )
            with urlopen(req) as r:
                executed = json.load(r)
            self.assertEqual(executed["status"], "VERIFIED")
            self.assertEqual(executed["execution_state"], "CONSUMED")
            self.assertEqual(executed["monetary_settlement"], "NOT_PERFORMED")
            self.assertEqual(executed["verification"], {"verdict": "VERIFIED", "errors": []})
        finally:
            server.shutdown()
            server.server_close()
            if previous is None:
                os.environ.pop("AGENTPAY_COMMERCIAL_STATE_DB", None)
            else:
                os.environ["AGENTPAY_COMMERCIAL_STATE_DB"] = previous
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_catalog_endpoint_is_truthful_and_machine_readable(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/catalog") as r:
                data = json.load(r)
                self.assertEqual(data["schema"], "agentpay-catalog/1")
                self.assertEqual([s["slug"] for s in data["services"]], ["code", "research", "3d"])
        finally:
            server.shutdown()
            server.server_close()

    def test_logo_asset_is_served(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/agentpay-logo.webp") as r:
                self.assertEqual(r.status, 200)
                self.assertEqual(r.headers["content-type"], "image/webp")
                self.assertGreater(int(r.headers["content-length"]), 1000)
        finally:
            server.shutdown()
            server.server_close()

    def test_http_head_for_home(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            req = Request(f"http://127.0.0.1:{server.server_port}/", method="HEAD")
            with urlopen(req) as r:
                self.assertEqual(r.status, 200)
                self.assertIn("text/html", r.headers["content-type"])
        finally:
            server.shutdown()
            server.server_close()

    def test_http_health_and_security_headers(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/health") as r:
                data = json.load(r)
                self.assertTrue(data["ok"])
                self.assertEqual(r.headers["x-content-type-options"], "nosniff")
                self.assertIn("default-src 'self'", r.headers["content-security-policy"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()

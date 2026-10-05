import json
import threading
import unittest
from urllib.request import Request, urlopen

from src.webapp import Handler, ThreadingHTTPServer, run_demo, tamper_demo


class WebAppTests(unittest.TestCase):
    def test_authorized_demo_is_explicitly_demo_and_verified(self):
        out = run_demo(250_000, "One. Two. Three.")
        self.assertEqual(out["environment"], "DEMO")
        self.assertEqual(out["status"], "VERIFIED")
        self.assertEqual(out["proof"]["settlement"]["transaction_hash"], "demo:not-on-chain")

    def test_denied_demo_has_no_settlement(self):
        out = run_demo(2_000_000, "One.")
        self.assertEqual(out["status"], "DENIED")
        self.assertIsNone(out["proof"]["settlement"])

    def test_tamper_endpoint_logic_fails_verification(self):
        out = run_demo(250_000, "One.")
        tampered = tamper_demo(out["proof"])
        self.assertEqual(tampered["verification"]["verdict"], "NOT VERIFIED")

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

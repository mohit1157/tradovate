"""
Minimal local signal server for NinjaTrader strategy testing.

Run:
  python signal_server.py

Then NinjaTrader strategy can call:
  http://127.0.0.1:8787/signal?symbol=MNQ%2003-26

This is intentionally simple. Replace `compute_signal()` with your Gemini + news/social pipeline.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import json
import random
import time

HOST = "127.0.0.1"
PORT = 8787

def compute_signal(symbol: str):
    # Placeholder logic:
    # - 10% BUY, 10% SELL, else HOLD
    r = random.random()
    if r < 0.10:
        return {"action": "BUY", "qty": 1, "confidence": 0.70}
    if r < 0.20:
        return {"action": "SELL", "qty": 1, "confidence": 0.70}
    return {"action": "HOLD", "qty": 1, "confidence": 0.60}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/signal":
            self.send_response(404)
            self.end_headers()
            return

        qs = parse_qs(parsed.query)
        symbol = (qs.get("symbol", ["UNKNOWN"])[0] or "UNKNOWN")

        payload = compute_signal(symbol)

        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # quiet
        return

if __name__ == "__main__":
    print(f"Signal server running on http://{HOST}:{PORT}/signal")
    HTTPServer((HOST, PORT), Handler).serve_forever()

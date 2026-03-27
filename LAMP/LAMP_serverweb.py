#!/usr/bin/env python3
"""
Simple WebRelay simulator for local GUI testing.

Supported examples:
  GET /state.xml
  GET /state.xml?relayState=1
  GET /state.xml?relayState=0
  GET /state.xml?relay1State=1
  GET /state.xml?relay1State=0
  GET /relay1on
  GET /relay1off

Run:
  python webrelay_simulator.py

Then set your GUI target to:
  127.0.0.1:8080

So your existing GUI URL style will work:
  http://127.0.0.1:8080/state.xml?relayState=1
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from dataclasses import dataclass
from datetime import datetime
import argparse
import html
import threading


@dataclass
class RelayState:
    relay1: int = 0


STATE = RelayState()
LOCK = threading.Lock()


def xml_response() -> bytes:
    with LOCK:
        relay = STATE.relay1

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    body = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<datavalues>
    <relay1state>{relay}</relay1state>
    <relaystate>{relay}</relaystate>
    <timeutc>{now}</timeutc>
    <model>WebRelay Simulator</model>
</datavalues>
"""
    return body.encode("utf-8")


def html_page(host: str, port: int) -> bytes:
    with LOCK:
        relay = STATE.relay1

    state_text = "ON" if relay else "OFF"
    state_color = "green" if relay else "black"
    base = f"http://{host}:{port}"
    page = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>WebRelay Simulator</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 40px; }}
    .card {{ max-width: 720px; padding: 24px; border: 1px solid #ccc; border-radius: 12px; }}
    .state {{ font-size: 24px; font-weight: bold; color: {state_color}; }}
    button {{ padding: 10px 16px; margin-right: 8px; cursor: pointer; }}
    code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 6px; }}
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>WebRelay Simulator</h1>
    <p class=\"state\">Relay 1: {state_text}</p>
    <p>
      <a href=\"/relay1on\"><button>Relay ON</button></a>
      <a href=\"/relay1off\"><button>Relay OFF</button></a>
      <a href=\"/state.xml\"><button>View XML</button></a>
    </p>
    <h3>GUI test target</h3>
    <p>Set your GUI WebRelay IP field to <code>{html.escape(host)}:{port}</code></p>
    <p>Example ON URL: <code>{base}/state.xml?relayState=1</code></p>
    <p>Example OFF URL: <code>{base}/state.xml?relayState=0</code></p>
  </div>
</body>
</html>
"""
    return page.encode("utf-8")


class WebRelayHandler(BaseHTTPRequestHandler):
    server_version = "WebRelaySimulator/0.1"

    def log_message(self, format: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), format % args))

    def _send(self, content: bytes, content_type: str = "text/plain; charset=utf-8", status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _set_relay_from_query(self, query: dict[str, list[str]]) -> bool:
        desired = None
        for key in ("relayState", "relay1State", "relay1state"):
            if key in query and query[key]:
                desired = query[key][0]
                break

        if desired is None:
            return False

        if desired not in {"0", "1"}:
            self._send(b"Invalid relay state. Use 0 or 1.\n", status=400)
            return True

        with LOCK:
            STATE.relay1 = int(desired)
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            content = html_page(self.server.server_address[0], self.server.server_address[1])
            self._send(content, content_type="text/html; charset=utf-8")
            return

        if path in {"/relay1on", "/on"}:
            with LOCK:
                STATE.relay1 = 1
            self._send(xml_response(), content_type="application/xml; charset=utf-8")
            return

        if path in {"/relay1off", "/off"}:
            with LOCK:
                STATE.relay1 = 0
            self._send(xml_response(), content_type="application/xml; charset=utf-8")
            return

        if path == "/state.xml":
            handled_error = self._set_relay_from_query(query)
            if handled_error:
                return
            self._send(xml_response(), content_type="application/xml; charset=utf-8")
            return

        self._send(b"Not found\n", status=404)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local WebRelay simulator.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host, default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8080, help="Bind port, default: 8080")
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), WebRelayHandler)
    print(f"WebRelay simulator running at http://{args.host}:{args.port}")
    print(f"Test XML: http://{args.host}:{args.port}/state.xml")
    print(f"Relay ON : http://{args.host}:{args.port}/state.xml?relayState=1")
    print(f"Relay OFF: http://{args.host}:{args.port}/state.xml?relayState=0")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping simulator...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()


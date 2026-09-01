#!/usr/bin/env python3
"""Serve the study app on your Wi-Fi so you can open it on your phone right now.

    python mobile/serve.py

Rebuilds the content bundle first, then prints the address to type into the phone's
browser. Both devices must be on the same Wi-Fi.

Note: over plain http on a LAN address the browser will not offer "Install app"
(that needs https). For a real installed app use GitHub Pages or the APK - see
mobile/README.md. This is for reading and for checking changes quickly.
"""

import argparse
import http.server
import socket
import socketserver
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WWW = HERE / "www"


def lan_ip() -> str:
    """Best guess at this machine's address on the local network."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))       # no packets are actually sent
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# A service worker outlives a reload: once registered it answers from its own cache,
# so an edit to app.js can appear to do nothing for hours. While developing, hand out
# a worker that deletes every cache, unregisters itself and reloads open tabs. The real
# sw.js still ships in www/ for GitHub Pages and the APK (use --pwa to serve it here).
KILL_SW = """/* dev server: self-destructing service worker */
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) {
  e.waitUntil((function () {
    return caches.keys()
      .then(function (keys) { return Promise.all(keys.map(function (k) { return caches.delete(k); })); })
      .then(function () { return self.registration.unregister(); })
      .then(function () { return self.clients.matchAll({ type: 'window' }); })
      .then(function (cs) { cs.forEach(function (c) { c.navigate(c.url); }); });
  })());
});
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    serve_real_sw = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WWW), **kwargs)

    def do_GET(self):
        if self.path.split("?")[0] in ("/sw.js", "/mobile/www/sw.js") and not self.serve_real_sw:
            body = KILL_SW.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        # always serve fresh files while developing
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "404" in (fmt % args):
            sys.stderr.write("  404  %s\n" % (args[0] if args else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-build", action="store_true", help="skip rebuilding content.js")
    ap.add_argument("--pwa", action="store_true",
                    help="serve the real service worker (offline test) instead of the dev kill-switch")
    args = ap.parse_args()

    if not args.no_build:
        rc = subprocess.call([sys.executable, str(HERE / "build.py")])
        if rc != 0:
            return rc
        print()

    Handler.serve_real_sw = args.pwa

    ip = lan_ip()
    if not args.pwa:
        print("  service worker : dev kill-switch (caches cleared on load)")
    else:
        print("  service worker : real one, offline caching ON")
    print("  On this computer :  http://localhost:%d/" % args.port)
    print("  On your phone    :  http://%s:%d/" % (ip, args.port))
    print()
    print("  Same Wi-Fi on both. Ctrl+C to stop.")
    print()

    # NOT allow_reuse_address: on Windows that lets a second server bind a port that is
    # already serving, and requests then land on whichever instance the OS picks - which
    # looks exactly like the browser refusing to pick up your changes.
    socketserver.TCPServer.allow_reuse_address = False
    try:
        srv = socketserver.TCPServer(("0.0.0.0", args.port), Handler)
    except OSError:
        print("  port %d is already in use." % args.port)
        print("  Stop the server that owns it, or use --port %d" % (args.port + 1))
        return 1
    with srv as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Serve app/ locally and accept content written back by the app.

The PWA fetches non-scripture paragraph text at runtime. That text is useful to
the *next* build, but a browser cannot write into webapp/.cache/, so this
development server accepts it over one narrow endpoint:

    POST /_cache/<sha256-of-uri>    body: the cache document JSON

This is a development affordance, not part of the deployed product -- static
hosts serve app/ unchanged and the app's write-back POST simply fails and is
ignored. Because it writes files from HTTP input it is deliberately locked down:
loopback only, one path shape, a body cap, strict schema validation, and the
URI must already be referenced by the built dataset.

Usage:
    python3 dev_server.py [--port 8000] [--db app/data/app.sqlite]
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gospel_content import CacheError, cache_key, validate_cache_doc, write_cache

CACHE_PATH = re.compile(r"^/_cache/([0-9a-f]{64})$")
MAX_BODY = 256 * 1024


class Handler(SimpleHTTPRequestHandler):
    cache_dir = None
    known_uris = frozenset()

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        match = CACHE_PATH.match(self.path)
        if not match:
            self._json(404, {"error": "no such endpoint"})
            return

        # Host must name loopback. Without this, a hostile page on
        # http://evil.example:8000 whose DNS is rebound to 127.0.0.1 counts as
        # same-origin to the browser, and every check below would pass.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ("localhost", "127.0.0.1", "::1"):
            self._json(403, {"error": "unexpected Host header"})
            return

        # A POST with a simple content type needs no preflight, so any web page
        # the user happens to be visiting could otherwise write into the cache
        # while this server is running. Require the request to come from the
        # app itself: a same-origin fetch sends Sec-Fetch-Site: same-origin in
        # every browser that supports it, and older ones still send Origin.
        site = self.headers.get("Sec-Fetch-Site")
        origin = self.headers.get("Origin")
        if site is not None:
            if site != "same-origin":
                self._json(403, {"error": "cross-site requests are not accepted"})
                return
        elif origin is not None and origin != "http://%s" % self.headers.get("Host", ""):
            self._json(403, {"error": "cross-origin requests are not accepted"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "bad Content-Length"})
            return
        if length <= 0 or length > MAX_BODY:
            self._json(413, {"error": "body must be 1..%d bytes" % MAX_BODY})
            return

        try:
            doc = validate_cache_doc(json.loads(self.rfile.read(length).decode("utf-8")),
                                     expected_key=match.group(1))
        except (ValueError, UnicodeDecodeError) as err:
            self._json(400, {"error": str(err)})
            return

        # The dataset is the allow-list: only documents this build already
        # references may be written, so the endpoint cannot be used to drop
        # arbitrary files into the cache. It must fail closed -- an empty
        # allow-list means the dataset could not be read, which is a reason to
        # accept nothing, not a reason to accept everything.
        if doc["uri"] not in self.known_uris:
            self._json(403, {"error": "uri is not referenced by the dataset"})
            return

        try:
            write_cache(self.cache_dir, doc)
        except (OSError, CacheError) as err:
            self._json(500, {"error": str(err)})
            return
        self._json(200, {"ok": True, "uri": doc["uri"],
                         "paragraphs": len(doc["paragraphs"])})

    def end_headers(self):
        # The dataset is refetched on every load during development; letting a
        # browser cache it makes rebuilds invisible and wastes debugging time.
        self.send_header("Cache-Control", "no-store")
        SimpleHTTPRequestHandler.end_headers(self)

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


def load_known_uris(db_path):
    """The write-back allow-list. An empty result disables write-back entirely.

    Returns empty on a missing database or a schema without `documents` (an
    app.sqlite built before this feature), which is the safe direction: the
    endpoint then refuses everything rather than accepting everything.
    """
    if not os.path.exists(db_path):
        return frozenset()
    try:
        con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(db_path), uri=True)
        rows = con.execute("SELECT uri FROM documents").fetchall()
        con.close()
    except sqlite3.Error:
        return frozenset()
    return frozenset(r[0] for r in rows)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--root", default=os.path.join(here, "app"))
    parser.add_argument("--cache", default=os.path.join(here, ".cache", "documents"))
    parser.add_argument("--db", default=os.path.join(here, "app", "data", "app.sqlite"))
    args = parser.parse_args()

    Handler.cache_dir = args.cache
    Handler.known_uris = load_known_uris(args.db)
    os.makedirs(args.cache, exist_ok=True)
    os.chdir(args.root)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("serving %s on http://localhost:%d  (ctrl-c to stop)" % (args.root, args.port))
    if Handler.known_uris:
        print("write-back -> %s  (%d documents known)" % (args.cache, len(Handler.known_uris)))
    else:
        print("write-back DISABLED: no documents found in %s -- build first" % args.db)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()

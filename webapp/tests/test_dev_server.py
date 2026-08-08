#!/usr/bin/env python3
"""Tests for the write-back endpoint.

This endpoint writes files to disk from an HTTP request body, so the negative
cases matter more than the happy path. It talks to a server bound on loopback;
no external network is used.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dev_server  # noqa: E402
from gospel_content import cache_key  # noqa: E402

URI = "/general-conference/2022/10/43gong"
DOC = {"uri": URI, "paragraphs": [{"para_id": "p25", "pid": "1", "sort": 0, "text": "Hello."}]}


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cache = os.path.join(self.dir, "cache")
        self.root = os.path.join(self.dir, "root")
        os.makedirs(self.root)
        with open(os.path.join(self.root, "index.html"), "w", encoding="utf-8") as f:
            f.write("<h1>ok</h1>")

        class Handler(dev_server.Handler):
            cache_dir = self.cache
            known_uris = frozenset({URI})

            def __init__(inner, *a, **kw):
                super().__init__(*a, directory=self.root, **kw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.dir, ignore_errors=True)

    def post(self, path, body, raw=False, headers=None):
        data = body if raw else json.dumps(body).encode("utf-8")
        head = {"Content-Type": "application/json"}
        head.update(headers or {})
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                     data=data, method="POST", headers=head)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read() or b"{}")

    def test_binds_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_accepts_a_valid_document(self):
        status, payload = self.post("/_cache/" + cache_key(URI), DOC)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(os.path.exists(os.path.join(self.cache, cache_key(URI) + ".json")))

    def test_repeated_post_is_idempotent(self):
        for _ in range(2):
            self.assertEqual(self.post("/_cache/" + cache_key(URI), DOC)[0], 200)
        self.assertEqual(len(os.listdir(self.cache)), 1)

    def test_rejects_unknown_path(self):
        self.assertEqual(self.post("/anything-else", DOC)[0], 404)

    def test_rejects_path_traversal(self):
        # The path must be exactly /_cache/<64 hex>; nothing else is routable.
        for bad in ["/_cache/../../etc/passwd", "/_cache/" + "z" * 64, "/_cache/abc"]:
            self.assertEqual(self.post(bad, DOC)[0], 404, bad)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "etc")))

    def test_rejects_uri_not_referenced_by_the_dataset(self):
        other = {"uri": "/somewhere/else", "paragraphs": []}
        status, _ = self.post("/_cache/" + cache_key(other["uri"]), other)
        self.assertEqual(status, 403)
        self.assertFalse(os.path.isdir(self.cache) and os.listdir(self.cache))

    def test_rejects_body_over_the_cap(self):
        huge = json.dumps({"uri": URI, "paragraphs": [
            {"para_id": "p1", "text": "x" * (dev_server.MAX_BODY + 100), "sort": 0}]}).encode()
        self.assertEqual(self.post("/_cache/" + cache_key(URI), huge, raw=True)[0], 413)

    def test_rejects_malformed_json(self):
        self.assertEqual(self.post("/_cache/" + cache_key(URI), b"{not json", raw=True)[0], 400)

    def test_rejects_hash_mismatch(self):
        self.assertEqual(self.post("/_cache/" + "0" * 64, DOC)[0], 400)

    def test_rejects_invalid_document_shape(self):
        bad = {"uri": URI, "paragraphs": [{"para_id": "1-cannot-start-with-a-digit", "text": "x"}]}
        self.assertEqual(self.post("/_cache/" + cache_key(URI), bad)[0], 400)

    def test_rejects_cross_site_requests(self):
        # A POST with a simple content type needs no preflight, so any page the
        # user is browsing could otherwise write into the cache while this is up.
        status, _ = self.post("/_cache/" + cache_key(URI), DOC,
                              headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)
        self.assertFalse(os.path.isdir(self.cache) and os.listdir(self.cache))

    def test_rejects_foreign_origin_when_fetch_metadata_absent(self):
        status, _ = self.post("/_cache/" + cache_key(URI), DOC,
                              headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_accepts_same_origin_request(self):
        self.assertEqual(self.post("/_cache/" + cache_key(URI), DOC,
                                   headers={"Sec-Fetch-Site": "same-origin"})[0], 200)

    def test_rejects_non_loopback_host_header(self):
        # DNS rebinding: a page on http://evil.example:8000 whose DNS resolves
        # to 127.0.0.1 is same-origin to the browser, so Sec-Fetch-Site alone
        # would let it through.
        status, _ = self.post("/_cache/" + cache_key(URI), DOC,
                              headers={"Host": "evil.example:%d" % self.port,
                                       "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(status, 403)
        self.assertFalse(os.path.isdir(self.cache) and os.listdir(self.cache))

    def test_accepts_loopback_host_variants(self):
        for host in ["localhost:%d" % self.port, "127.0.0.1:%d" % self.port]:
            self.assertEqual(self.post("/_cache/" + cache_key(URI), DOC,
                                       headers={"Host": host})[0], 200, host)

    def test_still_serves_static_files(self):
        with urllib.request.urlopen("http://127.0.0.1:%d/index.html" % self.port, timeout=10) as r:
            self.assertEqual(r.status, 200)
            self.assertIn(b"ok", r.read())


class FailsClosed(unittest.TestCase):
    """An unreadable dataset must disable write-back, not disable the check."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cache = os.path.join(self.dir, "cache")

        class Handler(dev_server.Handler):
            cache_dir = self.cache
            known_uris = frozenset()          # e.g. served before the first build

            def __init__(inner, *a, **kw):
                super().__init__(*a, directory=self.dir, **kw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_empty_allow_list_refuses_everything(self):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/_cache/%s" % (self.port, cache_key(URI)),
            data=json.dumps(DOC).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
            self.fail("write-back accepted with an empty allow-list")
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 403)
        self.assertFalse(os.path.isdir(self.cache) and os.listdir(self.cache))


class KnownUris(unittest.TestCase):
    def test_missing_database_yields_empty_allow_list(self):
        self.assertEqual(dev_server.load_known_uris("/definitely/not/here.sqlite"), frozenset())

    def test_database_without_documents_table_yields_empty_allow_list(self):
        # An app.sqlite built before this feature has no documents table.
        path = os.path.join(tempfile.mkdtemp(), "old.sqlite")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE annotations (id TEXT)")
        con.commit()
        con.close()
        self.assertEqual(dev_server.load_known_uris(path), frozenset())


if __name__ == "__main__":
    unittest.main()

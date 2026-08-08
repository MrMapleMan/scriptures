#!/usr/bin/env python3
"""Reader logic tests for app.js, driven through node.

Roughly half the paragraph-selection logic lives in the browser, and R51 forbids
adding a build toolchain or an npm test runner. Node is already a dependency of
the project's checks (`node --check` on app.js and the service worker), so this
extracts the pure functions by name and evaluates them against a stub `state`.
No DOM, no bundler, no package.json.

It skips when node is absent rather than failing, so the suite still runs on a
machine that only has Python.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP_JS = os.path.join(os.path.dirname(HERE), "app", "app.js")
NODE = shutil.which("node")


def extract(source, name):
    """Return the full text of `function name(...) {...}`, brace-matched.

    Deliberately not a parser: these are top-level functions in a file with no
    modules, and matching braces from the signature is enough. A string or
    comment containing an unbalanced brace inside one of them would break this,
    so the extraction is asserted before use.
    """
    start = source.find("function %s(" % name)
    if start < 0:
        raise AssertionError("function %s not found in app.js" % name)
    depth, i = 0, source.index("{", start)
    for j in range(i, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
    raise AssertionError("unbalanced braces extracting %s" % name)


FUNCTIONS = ["paraKey", "resolveParagraph", "spanHighlights", "documentPassages",
             "documentContext", "stateStoresWholeDocument"]

# A stub of the pieces of `state` the extracted functions touch, built from a
# plain description of a document so each test reads as data.
HARNESS = r"""
function buildState(doc) {
  const state = { paragraphs: new Map(), paragraphsByPid: new Map(),
                  paragraphsByDoc: new Map(), docHighlights: new Map(),
                  docHighlightsByDoc: new Map() };
  const all = [];
  (doc.paragraphs || []).forEach((p) => {
    const record = { paraId: p.para_id, text: p.text, pid: p.pid || null, sort: p.sort };
    state.paragraphs.set(paraKey(doc.uri, p.para_id), record);
    if (p.pid) state.paragraphsByPid.set(paraKey(doc.uri, p.pid), record);
    all.push(record);
  });
  all.sort((a, b) => a.sort - b.sort);
  if (all.length) state.paragraphsByDoc.set(doc.uri, all);
  const shape = (h) => ({
    docUri: doc.uri, paraId: h.para_id, pid: h.pid || null,
    s: h.s === undefined ? null : h.s, e: h.e === undefined ? null : h.e,
    color: "yellow", style: null,
  });
  state.docHighlights.set("ann", (doc.highlights || []).map(shape));
  // Highlights belonging to other annotations on the same document.
  const everything = (doc.highlights || []).concat(doc.otherHighlights || []);
  state.docHighlightsByDoc.set(doc.uri, everything.map(shape));
  return state;
}
"""


@unittest.skipUnless(NODE, "node not installed")
class ReaderJs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(APP_JS, encoding="utf-8") as f:
            cls.source = f.read()
        cls.functions = "\n".join(extract(cls.source, n) for n in FUNCTIONS)

    def run_js(self, doc, body):
        script = "\n".join([
            "let state;", self.functions, HARNESS,
            "const doc = %s;" % json.dumps(doc),
            "state = buildState(doc);",
            'const ann = { id: "ann", docUri: doc.uri };',
            body,
        ])
        proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    # ---------------------------------------------------------------- R24

    def talk(self, n=10, highlights=None):
        return {
            "uri": "/general-conference/2022/10/43gong",
            "paragraphs": [{"para_id": "p%d" % i, "pid": "aid%d" % i,
                            "sort": i - 1, "text": "para %d" % i}
                           for i in range(1, n + 1)],
            "highlights": highlights if highlights is not None else [{"para_id": "p3"}],
        }

    def context_of(self, doc):
        return self.run_js(doc, """
            const passages = documentPassages(ann);
            const ctx = documentContext(ann, passages);
            console.log(JSON.stringify(ctx === null ? null
              : ctx.map((p) => ({ text: p.text, focus: p.focus, hl: (p.hl || []).length }))));
        """)

    def test_conference_reader_renders_the_whole_talk_with_one_focus(self):
        ctx = self.context_of(self.talk())
        self.assertEqual(len(ctx), 10)
        self.assertEqual([p["focus"] for p in ctx].count(True), 1)
        self.assertTrue(ctx[2]["focus"])
        self.assertEqual(ctx[2]["text"], "para 3")

    def test_unannotated_context_paragraphs_carry_no_highlights(self):
        ctx = self.context_of(self.talk())
        self.assertEqual(ctx[2]["hl"], 1)
        self.assertEqual(sum(p["hl"] for p in ctx if not p["focus"]), 0)

    def test_shows_highlights_from_other_annotations_on_the_same_talk(self):
        """The whole talk is on screen, so every mark in it should show.

        Emphasis still belongs to the annotation that opened the reader --
        the other paragraph is highlighted but not focused.
        """
        doc = self.talk()
        doc["otherHighlights"] = [{"para_id": "p8"}]
        ctx = self.context_of(doc)
        self.assertEqual(ctx[7]["hl"], 1)
        self.assertFalse(ctx[7]["focus"])
        self.assertTrue(ctx[2]["focus"])
        self.assertEqual(sum(p["hl"] for p in ctx), 2)

    def test_two_annotations_on_one_paragraph_both_render(self):
        doc = self.talk()
        doc["otherHighlights"] = [{"para_id": "p3"}]
        ctx = self.context_of(doc)
        self.assertEqual(ctx[2]["hl"], 2)

    def test_focus_follows_the_pid_when_the_page_was_renumbered(self):
        # The annotation records p3, but the current page calls that paragraph
        # p7 and only the Pid matches. Emphasis must land on the real paragraph.
        doc = self.talk()
        doc["highlights"] = [{"para_id": "p3", "pid": "aid7"}]
        ctx = self.context_of(doc)
        self.assertTrue(ctx[6]["focus"])
        self.assertFalse(ctx[2]["focus"])

    def test_every_annotated_paragraph_is_focused(self):
        doc = self.talk(highlights=[{"para_id": "p2"}, {"para_id": "p9"}])
        ctx = self.context_of(doc)
        self.assertEqual([i for i, p in enumerate(ctx) if p["focus"]], [1, 8])

    # --------------------------------------------------------------- R24a

    def test_non_conference_never_gets_context(self):
        doc = self.talk()
        doc["uri"] = "/manual/general-handbook/32-repentance-and-membership-councils"
        self.assertIsNone(self.context_of(doc))

    def test_referenced_only_storage_renders_as_before(self):
        # A pre-R15 cache entry: nothing stored beyond the annotated paragraph.
        doc = self.talk(n=1, highlights=[{"para_id": "p1"}])
        self.assertIsNone(self.context_of(doc))

    def test_gapped_storage_is_not_rendered_as_a_talk(self):
        # An archive talk whose map missed the middle. Rendering these three
        # consecutively would imply the gap does not exist.
        doc = self.talk()
        doc["paragraphs"] = [p for p in doc["paragraphs"] if p["sort"] in (0, 1, 7)]
        self.assertIsNone(self.context_of(doc))

    def test_context_still_renders_when_every_anchor_misses(self):
        doc = self.talk(highlights=[{"para_id": "p99"}])
        ctx = self.context_of(doc)
        self.assertEqual(len(ctx), 10)
        self.assertEqual([p["focus"] for p in ctx].count(True), 0)

    # --------------------------------------------------------------- R24b

    def test_card_passages_do_not_grow_to_the_whole_talk(self):
        """The card must stay annotation-sized even when the talk is stored."""
        got = self.run_js(self.talk(), """
            const passages = documentPassages(ann);
            console.log(JSON.stringify({ count: passages.length,
                                         texts: passages.map((p) => p.text) }));
        """)
        self.assertEqual(got["count"], 1)
        self.assertEqual(got["texts"], ["para 3"])


if __name__ == "__main__":
    sys.exit(unittest.main())

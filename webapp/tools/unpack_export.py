#!/usr/bin/env python3
"""Unpack the app's "Export fetched content" download into the content cache.

The app runs on phones and static hosts where the dev server's write-back
endpoint is not reachable, so it can also export everything it has fetched as
one JSON file. Splitting that by hand is not reasonable, so this does it.

    python3 tools/unpack_export.py ~/Downloads/scripture-notes-content.json

Re-running with the same export is idempotent: each document is written to the
file named for its URI hash, replacing any earlier copy.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gospel_content import CacheError, write_cache

SUPPORTED_VERSION = 1


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export", help="the JSON file downloaded from the app")
    parser.add_argument("--cache", default=os.path.join(here, ".cache", "documents"))
    args = parser.parse_args()

    with open(args.export, encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, list):
        # Tolerated so a hand-assembled list still works.
        documents, version = payload, 0
    elif isinstance(payload, dict):
        documents = payload.get("documents") or []
        version = payload.get("version", 0)
    else:
        sys.exit("unrecognised export: expected an object or a list")

    if not isinstance(version, int) or version > SUPPORTED_VERSION:
        sys.exit("export version %r is not one this script understands (<= %d)"
                 % (version, SUPPORTED_VERSION))
    if not isinstance(documents, list):
        sys.exit("unrecognised export: 'documents' is not a list")

    written = skipped = 0
    for doc in documents:
        label = doc.get("uri", "?") if isinstance(doc, dict) else "?"
        try:
            write_cache(args.cache, doc)
            written += 1
        except (CacheError, OSError, AttributeError, TypeError) as err:
            skipped += 1
            print("  skipped %s: %s" % (label, err))

    print("wrote %d document(s) to %s%s"
          % (written, args.cache, ", skipped %d" % skipped if skipped else ""))
    if written:
        print("rebuild to embed them: python3 build_data.py --annotations <export>.sqlite")


if __name__ == "__main__":
    main()

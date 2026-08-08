#!/usr/bin/env python3
"""Shared helpers for reading Gospel Library content: text normalisation,
paragraph extraction, content-type classification, and the on-disk cache.

Kept separate from build_data.py so the pure logic is testable without a
database, and so the normalisation rule has exactly one home. Reading the same
text out of two sources and comparing it is only meaningful if both sides were
normalised identically -- entity decoding and Unicode composition differences
look exactly like corrupted data otherwise.
"""

import hashlib
import html
import json
import os
import re
import unicodedata

# Anchor ids are not all of the form pN. Real annotations target headings
# (title29), pull quotes (aside2_p1), hymn lines (figure1_p29), study summaries,
# and -- in talks from 2025 on -- opaque ids like p_iilzI. Every one of those
# sits on a <p> or heading and carries a data-aid, so the id pattern is what
# has to be permissive, not the tag set.
ANCHOR = r"[A-Za-z][\w-]*"
PARA_RE = re.compile(r'<(p|h[1-6])\b[^>]*\bid="(%s)"[^>]*>(.*?)</\1>' % ANCHOR, re.S | re.I)
AID_RE = re.compile(r'\bdata-aid="([^"]+)"', re.I)
TAG_RE = re.compile(r"<[^>]+>")

# /scriptures/<volume>/<book>/<chapter>
CHAPTER_URI = re.compile(r"^/scriptures/([^/]+)/([^/]+)/(\d+)$")
# '<uri>.<anchor>' in any namespace. The anchor must start with a letter so a
# handbook section number (/handbook/general-handbook/8.1) is not mistaken for
# one -- that trailing '.1' is part of the document's own address.
HIGHLIGHT_URI = re.compile(r"^(/.+)\.(%s)$" % ANCHOR)
# Only this shape carries a verse number in the scripture namespace.
VERSE_ANCHOR = re.compile(r"^p(\d+)$")

CONTENT_API = ("https://www.churchofjesuschrist.org/study/api/v3"
               "/language-pages/type/content?lang=eng&uri=")

GC_PREFIX = "/general-conference/"


def stores_whole_document(uri):
    """Does this namespace store every paragraph, or only annotated ones?

    General Conference only. Talks are short and bounded (34.8 paragraphs mean)
    and their full text is already held locally, so keeping all of it costs
    ~4.2 MB and buys the reader real context. The other namespaces are handbook
    and manual chapters that are far longer, where the same rule was measured at
    +15-20 MB and is deliberately not applied.

    One home for the rule because three writers depend on it -- the build, the
    alignment tool, and the reader -- and a split-brain answer would silently
    store one thing and render another.
    """
    return bool(uri) and uri.startswith(GC_PREFIX)

# Display order of the content-type buckets.
BUCKETS = [
    "Scriptures",
    "General Conference",
    "My Notes",
    "Magazines",
    "Books & Lessons",
    "Church History",
    "Come, Follow Me",
    "Handbooks & Callings",
    "Videos & Images",
    "Topics",
    "Music",
    "Other",
]

# URI root -> bucket, for every namespace whose root alone is decisive.
ROOT_BUCKETS = {
    "scriptures": "Scriptures",
    "general-conference": "General Conference",
    "ensign": "Magazines",
    "liahona": "Magazines",
    "new-era": "Magazines",
    "ya-weekly": "Magazines",
    "friend": "Magazines",
    "ftsoy": "Magazines",
    "history": "Church History",
    "church-historians-press": "Church History",
    "broadcasts": "Videos & Images",
    "handbook": "Handbooks & Callings",
    "journal": "My Notes",
}

# /manual is the one root that fans out, so it is refined by slug.
MANUAL_RULES = [
    ("Come, Follow Me", lambda s: s.startswith("come-follow-me")),
    ("Church History", lambda s: s in {"gospel-topics-essays", "revelations-in-context",
                                       "first-vision-accounts"}
     or s.startswith("saints-") or s.startswith("daughters-in-my-kingdom")),
    ("Topics", lambda s: s == "gospel-topics"),
    ("Music", lambda s: s in {"hymns", "childrens-songbook"}),
    # Preach My Gospel goes to Books & Lessons by the owner's decision, which
    # overrides the 2023 edition's "Handbooks and Callings" CategoryName. Listed
    # before the handbook rule so the override actually takes effect.
    ("Books & Lessons", lambda s: s.startswith("preach-my-gospel")
     or s.startswith("for-the-strength-of-youth")),
    # Not a study manual -- a campaign. Named explicitly because no slug
    # pattern separates it from the manuals that share the namespace.
    ("Other", lambda s: s.startswith("hear-him")),
    ("Handbooks & Callings", lambda s: s.startswith("general-handbook")
     or s.startswith("handbook-") or s.startswith("my-calling")
     or s.startswith("providing-in-the-lords-way")
     or s.startswith("leadership-instruction")),
]

# CategoryName is only ever a tiebreaker, used when no slug rule matched.
CATEGORY_HINTS = {
    "Come, Follow Me": "Come, Follow Me",
    "Church History": "Church History",
    "Handbooks and Callings": "Handbooks & Callings",
    "Topics": "Topics",
    "Music": "Music",
    "Videos and Images": "Videos & Images",
    "Life Help": "Other",
    "Youth": "Other",
    "Archived Content": "Other",
}


def norm_text(s):
    """Canonical form for any text compared or stored across sources.

    Entity decoding and NFC composition both matter: the live site serves
    'D&amp;C' and precomposed 'ü' inconsistently against other exports,
    and either difference makes identical text compare unequal.
    """
    if not s:
        return ""
    s = html.unescape(TAG_RE.sub("", s))
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_paragraphs(body):
    """Return [{para_id, pid, sort, text}] in document order.

    `sort` is DOM position, deliberately not derived from the number in
    para_id: ids are non-contiguous and non-monotonic (pull quotes and sidebars
    are interleaved), so ordering by the numeric part reorders the document.
    """
    out = []
    for order, match in enumerate(PARA_RE.finditer(body or "")):
        opening = match.group(0)[:match.group(0).find(">") + 1]
        aid = AID_RE.search(opening)
        text = norm_text(match.group(3))
        if not text:
            continue
        out.append({
            "para_id": match.group(2),
            "pid": aid.group(1) if aid else None,
            "sort": order,
            "text": text,
        })
    return out


def uri_root(uri):
    if not uri or not uri.startswith("/"):
        return ""
    parts = uri.split("/")
    return parts[1] if len(parts) > 1 else ""


def uri_slug(uri):
    parts = (uri or "").split("/")
    return parts[2] if len(parts) > 2 else ""


def classify(uri, category_name=None):
    """Content-type bucket for an annotation.

    URI first: the root is a perfect classifier for every namespace except
    /manual, whereas CategoryName is null on 754 rows, never set on /handbook,
    and inconsistent across identical content. CategoryName only breaks ties
    that the URI genuinely cannot.
    """
    if not uri:
        return "My Notes"
    root = uri_root(uri)
    if root == "manual":
        slug = uri_slug(uri)
        for bucket, test in MANUAL_RULES:
            if test(slug):
                return bucket
        hinted = CATEGORY_HINTS.get((category_name or "").strip())
        if hinted:
            return hinted
        return "Books & Lessons"
    if root in ROOT_BUCKETS:
        return ROOT_BUCKETS[root]
    hinted = CATEGORY_HINTS.get((category_name or "").strip())
    return hinted or "Other"


# ---------------------------------------------------------------- cache

def cache_key(uri):
    """Cache files are named for the sha256 of the URI they hold."""
    return hashlib.sha256((uri or "").encode("utf-8")).hexdigest()


class CacheError(ValueError):
    """A cache document that must be skipped rather than trusted."""


def safe_url(value):
    """Keep only links that are safe to put in an href.

    The app renders canonical_url as a link, and cache documents are untrusted
    input -- they arrive over an HTTP endpoint or from a hand-edited export --
    so a 'javascript:' URL here would execute in the app's origin on click.
    """
    if not isinstance(value, str):
        return None
    if value.startswith("https://") or value.startswith("http://"):
        return value
    return None


def validate_cache_doc(obj, expected_key=None):
    """Return a normalised cache document, or raise CacheError.

    Deliberately strict: this data is written by a browser through an HTTP
    endpoint, so it is untrusted input even though it is local.
    """
    if not isinstance(obj, dict):
        raise CacheError("not an object")
    uri = obj.get("uri")
    if not isinstance(uri, str) or not uri.startswith("/"):
        raise CacheError("missing or invalid 'uri'")
    if expected_key is not None and cache_key(uri) != expected_key:
        raise CacheError("uri does not match filename hash")
    paras = obj.get("paragraphs")
    if not isinstance(paras, list):
        raise CacheError("missing 'paragraphs' list")
    clean = []
    seen = set()
    for p in paras:
        if not isinstance(p, dict):
            raise CacheError("paragraph is not an object")
        pid_name = p.get("para_id")
        text = p.get("text")
        if not isinstance(pid_name, str) or not re.fullmatch(ANCHOR, pid_name):
            raise CacheError("invalid para_id %r" % (pid_name,))
        if not isinstance(text, str):
            raise CacheError("invalid text for %s" % pid_name)
        if pid_name in seen:
            raise CacheError("duplicate para_id %s" % pid_name)
        seen.add(pid_name)
        sort = p.get("sort")
        clean.append({
            "para_id": pid_name,
            "pid": p.get("pid") if isinstance(p.get("pid"), str) else None,
            "sort": sort if isinstance(sort, int) and not isinstance(sort, bool)
                    and sort >= 0 else len(clean),
            # Always normalised, never conditionally: text that skips entity
            # decoding or NFC here compares unequal against the same paragraph
            # read from any other source, and changes the word count that
            # highlight spans are clamped against.
            "text": norm_text(text),
        })
    error = obj.get("error")
    # Text reconstructed from a local corpus is not the live page and must stay
    # distinguishable from it, so the reader can say where it came from.
    source = obj.get("source")
    return {
        "uri": uri,
        "fetched_at": obj.get("fetched_at") if isinstance(obj.get("fetched_at"), str) else None,
        "canonical_url": safe_url(obj.get("canonical_url")),
        "restricted": bool(obj.get("restricted")),
        "error": error[:200] if isinstance(error, str) and error else None,
        "source": source if source in ("fetched", "archive") else "fetched",
        "paragraphs": clean,
    }


def read_cache(cache_dir, warn=None):
    """Load every valid cache document. Invalid ones are skipped, not fatal.

    A corrupt cache file must never fail a build -- the annotations it would
    have decorated are still worth keeping, and the document simply stays
    'unfetched' until it is fetched again.
    """
    docs = {}
    if not cache_dir or not os.path.isdir(cache_dir):
        return docs
    for name in sorted(os.listdir(cache_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(cache_dir, name)
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            doc = validate_cache_doc(raw, expected_key=name[:-5])
        except (OSError, ValueError) as err:
            if warn:
                warn("skipping cache file %s: %s" % (name, err))
            continue
        docs[doc["uri"]] = doc
    return docs


def write_cache(cache_dir, doc):
    """Write one validated document into the cache directory."""
    doc = validate_cache_doc(doc)
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, cache_key(doc["uri"]) + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, path)
    return path

# Alignment verification — 242 annotated General Conference talks

Sampling per request: all 428 annotated GC talks present in `conference_talks.db`, minus
the 25 already spot-checked, leaving a pool of 403. Selected **242 (60%)** comprising the
10 oldest, the 10 newest, **every talk from 2016 onward** (153 mandatory), and the
remainder spread evenly across time. Span 1971–2024. Zero fetch failures.

Method: `difflib.SequenceMatcher` over normalised paragraph *sequences* (`html.unescape`
→ NFC → whitespace collapse), matching `<p>` and `<h1>`–`<h6>` elements carrying an
`id="pN"`, then mapping each real id to its DB index. `p1`/`p2` are synthesised from the
`speaker`/`calling` columns when the live markup numbers the byline.

## Result

| metric | value |
|---|---|
| anchors resolved | **1048/1049 — 99.90%** |
| documents fully resolved | 241/242 |
| documents partially resolved | 1 |
| documents with nothing resolved | 0 |
| mean sequence similarity | 0.9795 (min 0.875) |
| anchors recovered via byline synthesis | 282 |

## By decade

| decade | docs | anchors resolved | mean similarity |
|---|---:|---|---:|
| 1970s | 14 | 38/38 — 100.0% | 0.9669 |
| 1980s | 11 | 89/89 — 100.0% | 0.9802 |
| 1990s | 13 | 35/35 — 100.0% | 0.9734 |
| 2000s | 30 | 152/152 — 100.0% | 0.9691 |
| 2010s | 95 | 406/406 — 100.0% | 0.9703 |
| 2020s | 79 | 328/329 — 99.7% | 0.9978 |

No era-dependent degradation. The 1970s show the lowest similarity (0.967) but still
resolve 100% of anchors — similarity measures whole-document overlap, which older
talks lose to dropped headings and editorial notes, not to anchor-bearing body text.

## The single unresolved anchor

`/general-conference/2021/04/26andersen` — anchor `p36`, 3/4 resolved.

```html
<h2 data-aid="146039650" id="p36">The Sacred Responsibility of Safeguarding Life</h2>
```

It is a **section heading**, and the scraper omits headings from the `talk` column, so
no DB row can match it. Permanent for this corpus, and rare: 1 of 1,049.

The annotation's `Pid` is `146039650`, identical to that element's `data-aid` — so the
Pid-first anchoring already planned (F4) resolves it against fetched content. The corpus
simply can't be the source for heading highlights.

## Lowest-similarity documents

All still resolve every anchor; the gap is dropped headings, counted in `live` but absent from `db`.

| talk | similarity | anchors | live | db |
|---|---:|---|---:|---:|
| `/general-conference/2018/04/ministering` | 0.875 | 2/2 | 9 | 7 |
| `/general-conference/2021/04/26andersen` | 0.904 | 3/4 | 40 | 33 |
| `/general-conference/2016/04/a-sacred-trust` | 0.917 | 4/4 | 13 | 11 |
| `/general-conference/2017/04/the-power-of-the-book-of-mormon` | 0.923 | 1/1 | 7 | 6 |
| `/general-conference/2016/04/choices` | 0.929 | 3/3 | 15 | 13 |
| `/general-conference/1972/10/i-know-that-my-redeemer-lives` | 0.933 | 1/1 | 16 | 14 |

## Conclusion

Combined with the earlier 25-talk pass, **267 of 428 annotated talks (62%) are verified**,
covering 1168 anchors with 1167 resolved — **99.91%**.
The corpus is a reliable paragraph source for General Conference once the three
normalisation rules are applied. It still cannot *replace* fetching, because computing
the alignment requires the live paragraph sequence; its value is as a durable, verified
offline archive and as a full-text search corpus.
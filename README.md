# Más Móvil Panamá — User Feedback → Product Roadmap

A live brand-sentiment dashboard for Más Móvil (Cable & Wireless Panamá). It pulls customer voice from the app stores,
social media and X, scores sentiment in Spanish and English, tags themes, pulls out what users are asking for, and
shows it all in a Streamlit dashboard.

## Run
```bash
cd /workspace/masmovil-sentiment
MMS_ALLOW_REFRESH=1 .venv/bin/streamlit run streamlit_app.py --server.port 8501   # dashboard → http://localhost:8501 (refresh button shown only with MMS_ALLOW_REFRESH=1)
.venv/bin/python refresh.py                            # incremental: pull only items newer than data/masmovil.db, analyse only those
.venv/bin/python refresh.py --only google_play,app_store   # pull selected sources only
.venv/bin/python refresh.py --full                     # ignore watermarks: full 90-day re-pull (stored items still skipped)
.venv/bin/python tests/test_incremental.py             # offline test of the incremental logic (fake Apify, no credit)
.venv/bin/python refresh.py --analyze-only             # re-run analysis on cached raw data (no credits used)
.venv/bin/python build_snapshot.py                     # → dashboard_snapshot.html (self-contained, interactive Plotly)
.venv/bin/python screenshot.py                         # → dashboard.png (headless Chrome via Playwright)
```
Socials need `APIFY_TOKEN` in the environment. It is read at runtime only, sent in the Authorization header,
and never logged or written to d## Layout
Read-only Streamlit app (all analysis is precomputed into `data/insights.json` + `item_insight` table):
1. Header with coverage (window, items, channels)
2. **Top user problems** — sub-issue cards with real counts, % and a verbatim quote
3. **What users want** — explicit requests, ranked
4. **Product improvement opportunities** — complaint | need | product change | mentions (n, %) | channels | priority | evidence
5. Category deep-dives (6 app categories) + secondary **Non-app / service issues** (network, pricing, support)
6. **Supporting reviews** — searchable, filter by category / channel / date (sentiment secondary)

Real feedback (counts, quotes, links) is kept separate from interpretation: "What users need" and
"Potential product change" come from `recommendations.json` and are labelled **Recommendation (AI-generated)**.

## Insight method (`python -m mms.insights`)
- Keyword/regex rules per sub-issue (`mms/product.py`, Spanish + English, accent-insensitive), severity 1–3.
- Multilingual embeddings (`paraphrase-multilingual-MiniLM-L12-v2`, local CPU) assign uncaught negative app
  complaints to the nearest sub-issue centroid (cosine ≥ 0.62, margin ≥ 0.03).
- Praise without request language is not counted; overlapping sub-issues are de-duplicated.
- Priority = frequency × severity (High / Medium / Low).
- Classifications are cached per item id + text hash (+ rules version) and embeddings per text hash,
  so re-runs only process new items. `refresh.py` runs collect → analyze → insights.

ot |

## Sources
| Source | How | Caps | Cost |
|---|---|---|---|
| Google Play `com.cwp.app` (Mi Más / Más) | `google-play-scraper` (public endpoint, gl=PA hl=es) | Newest reviews back to 90 days (hard cap 1,500) | free |
| App Store `id1391146262` (PA storefront) | Apple public customer-reviews RSS | 300 most recent | free |
| Facebook `facebook.com/masmovilpanama` | `apify/facebook-posts-scraper` + `apify/facebook-comments-scraper` | 30 posts in 90 days × 15 comments | Apify credits |
| Instagram `@masmovilpanama` | `apify/instagram-scraper` + `apify/instagram-comment-scraper` | 30 posts × 15 comments | Apify credits |
| TikTok `@masmovilpanama` + `#masmovilpanama` | `clockworks/tiktok-scraper` + `clockworks/tiktok-comments-scraper` | 30 per profile/hashtag; 15 comments per video; Panama-relevance + 90-day filter | Apify credits |
| X / Twitter | `apidojo/tweet-scraper` with searches for @MasMovilPanama, @masmovilayuda, "más móvil" panamá, #MasMovilPanama | 300 items requested (FREE plan returns ~10/run, so X history accumulates across runs) | Apify credits |
| LinkedIn | Not connected. There's no cheap, reliable company-posts actor (LinkedIn needs a login), and it carries little customer-sentiment value | – | – |

Every Apify run passes `maxItems` so pay-per-result actors can't overspend. The real cost of each run (`usageTotalUsd`)
is saved per source and shown under **Sources & method**. At these caps a full social refresh should cost roughly
**US$2–4** (Facebook posts+comments ≈ $1–1.5, Instagram ≈ $0.5–1, TikTok ≈ $0.5–1, X ≈ $0.15–0.3), based on Apify
Store list prices. Treat that as an estimate until a real run records the actual cost.

**First build (10 Oct 2026):** Apify rejected the token we were given (HTTP 401 `user-or-token-not-found`), so
Facebook, Instagram and TikTok show as **failed** and no Apify credits were spent. For X, the dashboard is using a
one-time import pulled through the X API (up to the 25 newest posts per weekly window, 24 Jul to 10 Oct 2026). Put a valid
token in `APIFY_TOKEN` and press **Refresh data** to connect the social sources.

## Method
- **Sentiment:** `cardiffnlp/twitter-xlm-roberta-base-sentiment` (multilingual). Score = P(pos) − P(neg). For a store
  review the model calls neutral, the star rating decides (≤2★ negative, ≥4★ positive). Brand-owned posts are left out
  of sentiment and count only toward engagement.
- **Themes:** keyword rules on accent-stripped text. An item can carry several themes; the first one matched (by priority) is its primary theme. On social and X, the app-specific labels only apply if the text mentions the app.
- **Asks:** counted when a pain-point pattern matches *and* the item is negative, ≤2★, or contains request language.
- **Translation:** `Helsinki-NLP/opus-mt-es-en` (machine translation, may be imperfect).
- **Alerts:** negatives in the latest week (or the current partial week) ≥5 and ≥1.5× the prior 4-week average, or net sentiment down more than 15 pts.
- No LLM key was available, so everything runs on local models (CPU). If you want LLM-quality asks, plug one into `analyze.py`.

## Limitations
- The X sample is capped and skewed toward the newest posts in each week. It also includes news and bystander chatter (e.g. Starlink and earthquake threads), not just customers.
- App Store reviews in the 90-day window are few (66), so App Store numbers are less reliable.
- Rule-based themes and asks miss sarcasm and unusual wording. Read the quotes, not just the counts.
- The TikTok handle `@masmovilpanama` couldn't be confirmed without a login.

## Actual Apify cost (first full run, 10 Oct 2026, Apify FREE plan, $5/month limit)
Facebook $0.40 · Instagram $1.04 · TikTok $0.53 · X $0.004, so **≈ $1.97 per full social pull**. Every run also has a hard
`maxTotalChargeUsd` cap (posts $0.50, comments $1.25, X $0.20).

## Weekly incremental refresh (current setup)
The GitHub workflow runs **once a week, Monday 00:30 UTC = Monday 06:00 IST**, and pulls **all** sources in that one run,
strictly incrementally (`mms/state.py` reads per-source watermarks from `data/masmovil.db`):
- **Google Play / App Store** (free): page newest-first and stop at the first already-stored review.
- **Facebook / Instagram / TikTok**: posts only since the newest stored post (−1 day overlap, and at least the last
  `COMMENT_RECHECK_DAYS`=10 days so recent posts' comment counters are re-read), max `MAX_POSTS_PER_RUN`=15 results.
  Comments are re-pulled **only for posts whose public comment counter grew** since the last pull (`fetch_state` table);
  Facebook also uses `onlyCommentsNewerThan` + recent-activity sort; Instagram (no date filter) asks only for as many
  comments as the counter grew by (≤15).
- **X**: `since:<newest stored date − 1 day>`, max 100 items.
- Already-stored ids are dropped; `mms.analyze` appends only new rows, sentiment/translation run only on new texts and
  `mms.insights` classifies/embeds only new items (cached by item id + text hash).
Expected Apify spend ≈ US$0.25–0.40 per weekly run ≈ **US$1.2–1.8/month** (vs ≈ US$3–4/month before).
A manual run with **full** ticked (default off) ignores the watermarks and re-pulls the 90-day window (≈ US$1.5–2).

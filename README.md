# Más Móvil Panamá — Brand Sentiment Dashboard

A live brand-sentiment dashboard for Más Móvil (Cable & Wireless Panamá). It pulls customer voice from the app stores,
social media and X, scores sentiment in Spanish and English, tags themes, pulls out what users are asking for, and
shows it all in a Streamlit dashboard.

## Run
```bash
cd /workspace/masmovil-sentiment
MMS_ALLOW_REFRESH=1 .venv/bin/streamlit run streamlit_app.py --server.port 8501   # dashboard → http://localhost:8501 (refresh button shown only with MMS_ALLOW_REFRESH=1)
.venv/bin/python refresh.py                            # re-pull every source and re-analyse (also the 🔄 button in the UI)
.venv/bin/python refresh.py --only google_play,app_store   # pull selected sources only
.venv/bin/python refresh.py --analyze-only             # re-run analysis on cached raw data (no credits used)
.venv/bin/python build_snapshot.py                     # → dashboard_snapshot.html (self-contained, interactive Plotly)
.venv/bin/python screenshot.py                         # → dashboard.png (headless Chrome via Playwright)
```
Socials need `APIFY_TOKEN` in the environment. It is read at runtime only, sent in the Authorization header,
and never logged or written to disk.

## Layout
| Path | What |
|---|---|
| `mms/config.py` | App IDs, handles, caps, Apify actor IDs |
| `mms/collect.py` | One collector per source → `data/raw/<source>.json` (status, reason, cost, normalized items) |
| `mms/apify.py` | Small Apify REST client (start run, poll, read cost, fetch dataset) |
| `mms/taxonomy.py` | Theme and ask rules (Panamanian Spanish + English) |
| `mms/analyze.py` | Sentiment + translation + themes/asks → SQLite `data/masmovil.db` (NLP cached by text hash) |
| `mms/metrics.py` | Metrics and Plotly figures shared by the app and the snapshot |
| `streamlit_app.py` | Streamlit dashboard (Streamlit Cloud entry; read-only, no ML at runtime). `app.py` is a thin local wrapper |
| `requirements.txt` / `requirements-refresh.txt` | Cloud runtime deps (streamlit, pandas, plotly) / refresh + analysis deps |
| `.github/workflows/refresh.yml` | Daily 06:00 IST refresh on GitHub Actions; commits `data/masmovil.db` |
| `DEPLOY.md` | Streamlit Community Cloud deployment steps |
| `build_snapshot.py`, `screenshot.py` | Static HTML export and PNG screenshot |

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
`maxTotalChargeUsd` cap (posts $0.50, comments $1.25, X $0.20). On the FREE plan the GitHub workflow runs daily for app stores + X,
and pulls Facebook/Instagram/TikTok only on the 1st and 15th (or on a manual run with "full" ticked), which keeps it inside $5/month.

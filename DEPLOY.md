# Deploying to Streamlit Community Cloud (daily auto-refresh)

How it fits together:
- **GitHub repo** holds the code plus the precomputed results (`data/masmovil.db`, `data/status.json`).
- **GitHub Actions** (`.github/workflows/refresh.yml`) runs every day at **06:00 IST** (00:30 UTC), and you can also start it by hand.
  It pulls the app stores (free) and Facebook, Instagram, TikTok and X through Apify (using the `APIFY_TOKEN` secret), runs the analysis
  (XLM-RoBERTa sentiment + Marian ES→EN translation on CPU, with the Hugging Face models cached), then commits the updated DB.
- **Streamlit Community Cloud** serves `streamlit_app.py`. It only reads the DB: no ML models, about 200 MB RAM.
  Every commit from Actions makes it redeploy automatically.

## One-time steps (Rishabh)
1. **Repo:** `github.com/rishabh1afk/masmovilpanama` exists and is empty. **Make it private first:**
   Settings → General → Danger Zone → *Change repository visibility* → Private.
   (The committed DB contains scraped review/comment text and usernames; a private repo also keeps the app private on Streamlit Cloud.)
2. **Push the code** (Grok Bot does this once you approve). It's a single `main` branch with the files listed in the README.
3. **Add the Apify secret:** repo → Settings → *Secrets and variables* → *Actions* → *New repository secret*
   → Name `APIFY_TOKEN`, Value = your Apify API token (Apify Console → Settings → API & Integrations; it starts with `apify_api_`).
4. **Enable Actions write access:** Settings → Actions → General → *Workflow permissions* → **Read and write permissions** → Save.
5. **First refresh:** Actions tab → *Refresh sentiment data* → *Run workflow*. The first run downloads about 1.5 GB of models
   (roughly 10–15 min); after that, runs are quicker because only new texts get analysed.
6. **Streamlit Cloud:** go to https://share.streamlit.io → sign in with GitHub (rishabh1afk) → authorise access to private repos
   → *Create app* → *Deploy a public app from GitHub* (the app's visibility is set separately in sharing settings) →
   Repository `rishabh1afk/masmovilpanama`, Branch `main`, Main file `streamlit_app.py`, Python 3.13 (Advanced settings) → Deploy.
   No secrets are needed in Streamlit Cloud.
7. **Restrict viewers:** app → *Share* (or ⋮ → Settings → Sharing) → *Who can view this app*: **Only specific people** →
   add invited emails (e.g. vasu.mittal@paytm.com). Viewers sign in with that Google/GitHub email.
   (Apps from private repos are private by default. Check your Community Cloud plan's limit on private apps.)

## Operating
- Change the schedule by editing `cron` in `.github/workflows/refresh.yml` (it's in UTC).
- If a source fails in a run, the dashboard keeps showing its last good data with status **stale** and the reason.
- Apify cost per run is recorded per source (see *Sources & method*). At current caps, expect about US$2–4 per daily run
  (≈ $60–120/month). Lower `MAX_POSTS_PER_ACCOUNT` / `MAX_COMMENTS_PER_POST` / `MAX_X_ITEMS` in `mms/config.py`
  or switch the cron to weekly to cut that.
- X in the cloud comes from Apify only (`apidojo/tweet-scraper`). The one-off X import used locally isn't committed.

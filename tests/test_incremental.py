"""Offline test of the incremental refresh (no network, no Apify credit).

Works on a COPY of data/masmovil.db + status.json + insights.json in a temp dir. The Apify client,
Google Play scraper and Apple RSS are replaced by fakes that return a realistic mix of already-stored
items (rebuilt from the DB) plus a few brand-new ones. Checks: actor inputs use watermark date filters
+ small limits, only new items are stored and analysed, no duplicates, comments re-pulled only for
posts whose counter grew, a second run is a no-op, the DB passes integrity_check and the Streamlit app
renders from it.   Run:  python tests/test_incremental.py"""
import os, sys, json, shutil, sqlite3, tempfile, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("APIFY_TOKEN", None)          # make sure nothing real can authenticate
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import requests
from mms import config as C

TMP = Path(tempfile.mkdtemp(prefix="mms-test-"))
for f in ("masmovil.db", "status.json", "insights.json"):
    shutil.copy(C.DATA / f, TMP / f)
C.DATA, C.RAW, C.DB_PATH, C.STATUS_PATH = TMP, TMP / "raw", TMP / "masmovil.db", TMP / "status.json"

from mms import collect, analyze, insights, apify, state  # noqa: E402
insights.INSIGHTS_PATH = TMP / "insights.json"

UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)
iso = lambda d: d.isoformat().replace("+00:00", "Z")
con0 = sqlite3.connect(C.DB_PATH)
rows = lambda q, *a: con0.execute(q, a).fetchall()
BEFORE = {r[0]: r[1] for r in rows("SELECT channel, count(*) FROM items GROUP BY 1")}
TOTAL0 = sum(BEFORE.values())
IDS0 = {r[0] for r in rows("SELECT id FROM items")}
NLP0 = rows("SELECT count(*) FROM nlp_cache")[0][0]
sfx = lambda i: i.split(":", 1)[1]

# ---------------- fakes ----------------
CALLS = []


def blocked(*a, **k):
    raise AssertionError("real network call attempted")


requests.post = blocked                      # no Apify run can ever start
apify.requests.post = blocked
collect.check_token = lambda: (True, "ok (fake)")


def stored_posts(ch):
    return rows("SELECT id,date,text,url,comments,author FROM items WHERE channel=? AND kind!='comment' ORDER BY date DESC", ch)


def stored_comments(ch, url):
    return rows("SELECT id,date,text,parent_url,author FROM items WHERE channel=? AND kind='comment' AND parent_url=?", ch, url)


NEW_TS = iso(NOW - dt.timedelta(hours=3))
fb_posts, ig_posts, tt_posts = stored_posts("facebook"), stored_posts("instagram"), stored_posts("tiktok")
FB_GROW, IG_GROW = fb_posts[0][3], ig_posts[0][3]     # newest stored post on each gets new comments
TT_GROW = [p for p in tt_posts if (p[4] or 0) > 0][0][3]
NEW_FB_URL = "https://www.facebook.com/masmovilpanama/posts/NEWPOST1"
NEW_IG_URL = "https://www.instagram.com/p/NEWPOST1/"
NEW_TT_URL = "https://www.tiktok.com/@someone/video/999000111"
EXTRA = {"facebook": {FB_GROW: 2, NEW_FB_URL: 1}, "instagram": {IG_GROW: 1, NEW_IG_URL: 2},
         "tiktok": {TT_GROW: 1, NEW_TT_URL: 1}}
ROUND = {"n": 1}


def since_ok(d, since):
    return (d or "") >= since


def fake_run_actor(actor, inp, timeout_s=900, max_items=None, max_charge_usd=None):
    CALLS.append(dict(actor=actor, input=inp, max_items=max_items, max_charge=max_charge_usd))
    if actor == C.ACTORS["facebook_posts"]:
        since, lim = inp["onlyPostsNewerThan"], inp["resultsLimit"]
        out = [dict(postId=sfx(i), url=u, time=d, text=t, likes=1,
                    comments=(c or 0) + EXTRA["facebook"].get(u, 0)) for i, d, t, u, c, a in fb_posts if since_ok(d, since)]
        out.insert(0, dict(postId="NEWPOST1", url=NEW_FB_URL, time=NEW_TS, text="Nuevo plan prepago", likes=3, comments=1))
        return out[:lim], 0.01
    if actor == C.ACTORS["facebook_comments"]:
        out = []
        for s in inp["startUrls"]:
            u = s["url"]
            out += [dict(id=sfx(i), date=d, text=t, facebookUrl=u, profileName=a) for i, d, t, pu, a in stored_comments("facebook", u)]
            out += [dict(id=f"fbnew-{u[-8:]}-{k}", date=NEW_TS, text=f"La app Mi Más no carga el saldo, error {k} ({u[-6:]})",
                         facebookUrl=u, profileName="cliente") for k in range(EXTRA["facebook"].get(u, 0))]
        return out, 0.02
    if actor == C.ACTORS["instagram_posts"]:
        since, lim = inp["onlyPostsNewerThan"], inp["resultsLimit"]
        out = [dict(id=sfx(i), url=u, timestamp=d, caption=t, ownerUsername=a,
                    commentsCount=(c or 0) + EXTRA["instagram"].get(u, 0)) for i, d, t, u, c, a in ig_posts if since_ok(d, since)]
        out.insert(0, dict(id="NEWPOST1", url=NEW_IG_URL, timestamp=NEW_TS, caption="Promo", ownerUsername="masmovilpanama", commentsCount=2))
        return out[:lim], 0.01
    if actor == C.ACTORS["instagram_comments"]:
        out = []
        for u in inp["directUrls"]:   # no date filter on this actor: also returns already-stored comments
            out += [dict(id=sfx(i), timestamp=d, text=t, postUrl=u, ownerUsername=a) for i, d, t, pu, a in stored_comments("instagram", u)][:3]
            out += [dict(id=f"ignew-{u[-10:]}-{k}", timestamp=NEW_TS, text=f"No puedo pagar en la app, me da error {k} ({u[-8:]})",
                         postUrl=u, ownerUsername="fan") for k in range(EXTRA["instagram"].get(u, 0))]
        return out, 0.02
    if actor == C.ACTORS["tiktok_posts"]:
        out = [dict(id=sfx(i), webVideoUrl=u, createTimeISO=d, text=t, authorMeta=dict(name=a),
                    commentCount=(c or 0) + EXTRA["tiktok"].get(u, 0)) for i, d, t, u, c, a in tt_posts]
        out.insert(0, dict(id="999000111", webVideoUrl=NEW_TT_URL, createTimeISO=NEW_TS, text="+Móvil Panamá señal en PTY",
                           authorMeta=dict(name="someone"), commentCount=1))
        return out[:inp["resultsPerPage"]], 0.01
    if actor == C.ACTORS["tiktok_comments"]:
        out = []
        for u in inp["postURLs"]:
            out += [dict(cid=sfx(i), createTimeISO=d, text=t, videoWebUrl=u, uniqueId=a) for i, d, t, pu, a in stored_comments("tiktok", u)]
            out += [dict(cid=f"ttnew-{u[-6:]}-{k}", createTimeISO=NEW_TS, text=f"La señal de +Móvil en Panamá está lenta {k}",
                         videoWebUrl=u, uniqueId="tt") for k in range(EXTRA["tiktok"].get(u, 0))]
        return out, 0.01
    if actor == C.ACTORS["x_search"]:
        old = [dict(id=sfx(i), createdAt=d, text=t, author=dict(userName=a), url=u)
               for i, d, t, u, c, a in stored_posts("x")[:3]]
        new = [dict(id=f"177000000000000000{k}", createdAt=NEW_TS, text=f"@MasMovilPanama sin internet en Panamá desde ayer {k}",
                    author=dict(userName=f"user{k}"), url=f"https://x.com/u/status/{k}") for k in range(2)]
        return new + old, 0.004
    raise AssertionError(f"unexpected actor {actor}")


collect.run_actor = fake_run_actor

import google_play_scraper  # noqa: E402
GP = [dict(reviewId=sfx(i), at=dt.datetime.fromisoformat(d).replace(tzinfo=None), content=t, score=r, userName=a)
      for i, d, t, r, a in rows("SELECT id,date,text,rating,author FROM items WHERE channel='google_play' ORDER BY date DESC")]
GP_NEW = [dict(reviewId=f"gp-new-{k}", at=(NOW - dt.timedelta(hours=k + 1)).replace(tzinfo=None),
               content=f"La aplicación se cierra sola al abrir {k}", score=1, userName="x") for k in range(3)]
GP_PAGES = []


def fake_reviews(app_id, continuation_token=None, count=100, **kw):
    allr = (GP_NEW if ROUND["n"] == 1 else []) + GP
    start = continuation_token or 0
    GP_PAGES.append((start, count))
    nxt = start + count
    return allr[start:nxt], (nxt if nxt < len(allr) else None)


google_play_scraper.reviews = fake_reviews

AS = rows("SELECT id,date,text,rating,author FROM items WHERE channel='app_store' ORDER BY date DESC")
AS_NEW = [(f"app_store:as-new-{k}", NEW_TS, f"Título. No me deja iniciar sesión {k}", 2, "y") for k in range(2)]
AS_PAGES = []


class Resp:
    status_code = 200

    def __init__(self, j):
        self._j = j

    def json(self):
        return self._j


def fake_get(url, timeout=30, **kw):
    assert "itunes.apple.com" in url, url
    page = int(url.split("page=")[1].split("/")[0])
    AS_PAGES.append(page)
    allr = (AS_NEW if ROUND["n"] == 1 else []) + AS
    chunk = allr[(page - 1) * 50: page * 50]
    return Resp({"feed": {"entry": [{"id": {"label": sfx(i)}, "updated": {"label": d}, "title": {"label": ""},
                                     "content": {"label": t}, "im:rating": {"label": str(int(r))},
                                     "author": {"name": {"label": a}}} for i, d, t, r, a in chunk]}})


collect.requests.get = fake_get

NLP_CALLS, EMB_CALLS = [], []
_run_nlp, _embed = analyze.run_nlp, insights.embed


def spy_nlp(con, texts):
    todo = [t for t in set(texts) if t and not con.execute("SELECT 1 FROM nlp_cache WHERE hash=?", (analyze.h(t),)).fetchone()]
    NLP_CALLS.append(len(todo))
    return _run_nlp(con, texts)


def spy_embed(con, texts):
    todo = [t for t in dict.fromkeys(texts) if not con.execute("SELECT 1 FROM emb_cache WHERE hash=?", (insights.h(t),)).fetchone()]
    EMB_CALLS.append(len(todo))
    return _embed(con, texts)


analyze.run_nlp, insights.embed = spy_nlp, spy_embed


def run():
    CALLS.clear(); GP_PAGES.clear(); AS_PAGES.clear(); NLP_CALLS.clear(); EMB_CALLS.clear()
    collect.main(None)
    res = analyze.main()
    insights.run()
    return res


ok = True


def check(cond, msg):
    global ok
    print(("PASS " if cond else "FAIL ") + msg)
    ok &= bool(cond)


# ---------------- round 1: new items exist ----------------
print(f"temp copy: {TMP}\nbefore: {TOTAL0} items {BEFORE}")
r1 = run()
con = sqlite3.connect(C.DB_PATH)
q = lambda s, *a: con.execute(s, a).fetchall()
by = {c["actor"]: c for c in CALLS if "comment" not in c["actor"]}
com = {c["actor"]: c for c in CALLS if "comment" in c["actor"]}
d_fb = by[C.ACTORS["facebook_posts"]]["input"]["onlyPostsNewerThan"]
recheck = (NOW - dt.timedelta(days=C.COMMENT_RECHECK_DAYS)).strftime("%Y-%m-%d")
check(d_fb == min(recheck, (dt.datetime.fromisoformat(fb_posts[0][1]) - dt.timedelta(days=1)).strftime("%Y-%m-%d")),
      f"facebook posts: date filter onlyPostsNewerThan={d_fb} (recheck window {C.COMMENT_RECHECK_DAYS}d), limit={by[C.ACTORS['facebook_posts']]['input']['resultsLimit']}")
check(by[C.ACTORS["facebook_posts"]]["input"]["resultsLimit"] == C.MAX_POSTS_PER_RUN, "facebook posts: small results limit")
fbc = com[C.ACTORS["facebook_comments"]]["input"]
check(sorted(s["url"] for s in fbc["startUrls"]) == sorted([FB_GROW, NEW_FB_URL]) and fbc.get("onlyCommentsNewerThan"),
      f"facebook comments: only {len(fbc['startUrls'])} posts with grown counters, onlyCommentsNewerThan={fbc.get('onlyCommentsNewerThan')}")
igc = com[C.ACTORS["instagram_comments"]]["input"]
check(sorted(igc["directUrls"]) == sorted([IG_GROW, NEW_IG_URL]) and igc["resultsLimit"] <= C.MAX_COMMENTS_PER_POST,
      f"instagram comments: only {len(igc['directUrls'])} posts, resultsLimit={igc['resultsLimit']}")
ttc = com[C.ACTORS["tiktok_comments"]]["input"]
check(sorted(ttc["postURLs"]) == sorted([TT_GROW, NEW_TT_URL]), f"tiktok comments: only {len(ttc['postURLs'])} videos with grown counters")
check(by[C.ACTORS["tiktok_posts"]]["input"]["oldestPostDateUnified"] >= recheck[:8], f"tiktok: oldestPostDateUnified={by[C.ACTORS['tiktok_posts']]['input']['oldestPostDateUnified']}")
xs = by[C.ACTORS["x_search"]]
check(all("since:" in t for t in xs["input"]["searchTerms"]) and xs["max_items"] == C.MAX_X_ITEMS_INCREMENTAL,
      f"x: {xs['input']['searchTerms'][0]!r}, maxItems={xs['max_items']}")
check(len(GP_PAGES) == 1 and GP_PAGES[0][1] == C.STORE_FIRST_PAGE_INCREMENTAL, f"google play: stopped paging at stored reviews (pages={GP_PAGES})")
check(AS_PAGES == [1], f"app store: stopped at first page containing stored reviews (pages={AS_PAGES})")
EXP = {"facebook": 1 + 2 + 1, "instagram": 1 + 1 + 2, "tiktok": 1 + 1 + 1, "x": 2, "google_play": 3, "app_store": 2}
after = {r[0]: r[1] for r in q("SELECT channel, count(*) FROM items GROUP BY 1")}
pruned = r1["pruned"]
for ch, n in EXP.items():
    exp = BEFORE.get(ch, 0) + n - (pruned if ch == "x" else 0)
    check(after.get(ch) == exp, f"{ch}: +{n} new rows ({BEFORE.get(ch)} -> {after.get(ch)})")
check(r1["new"] == sum(EXP.values()), f"analyze appended exactly the new items: {r1['new']} (skipped {r1['skipped']} already stored)")
check(q("SELECT count(*), count(DISTINCT id) FROM items")[0][0] == q("SELECT count(DISTINCT id) FROM items")[0][0], "no duplicate ids")
new_texts = {t for i, t, k in q("SELECT id, text, kind FROM items") if i not in IDS0 and k != "owned_post" and t}
check(NLP_CALLS == [len(new_texts)], f"sentiment/translation ran only on new texts: {NLP_CALLS} (expected {len(new_texts)} unique new non-owned texts; "
      f"2 new owned posts skipped by design)")
check(q("SELECT count(*) FROM fetch_state")[0][0] == 6, "fetch_state recorded comment counters for the 6 re-pulled posts")
st = json.loads(C.STATUS_PATH.read_text())
check(all(st[s].get("new") == n for s, n in EXP.items()), "status.json reports per-source new counts: " + str({s: st[s].get('new') for s in EXP}))
check(st["facebook"]["count"] == after["facebook"], "status.json count = total stored per channel")
check(q("PRAGMA integrity_check")[0][0] == "ok", "SQLite integrity_check ok")
check(q("SELECT count(*) FROM item_insight i JOIN items t ON t.id=i.id WHERE t.id LIKE 'google_play:gp-new-%'")[0][0] == 3,
      "new items are in item_insight (categorised)")

# ---------------- round 2: nothing new -> no-op ----------------
ROUND["n"] = 2
EXTRA.update({"facebook": {FB_GROW: 2, NEW_FB_URL: 1}, "instagram": {IG_GROW: 1, NEW_IG_URL: 2}, "tiktok": {TT_GROW: 1, NEW_TT_URL: 1}})
fb_posts[:] = stored_posts("facebook") and fb_posts   # sources keep returning the same counters as round 1
total1 = q("SELECT count(*) FROM items")[0][0]
r2 = run()
check(r2["new"] == 0, f"round 2: no new rows (skipped {r2['skipped']} already stored)")
check(q("SELECT count(*) FROM items")[0][0] == total1, "round 2: row count unchanged")
check(not any("comment" in c["actor"] for c in CALLS), "round 2: no comment actors called (counters unchanged)")
check(NLP_CALLS in ([], [0]) and EMB_CALLS in ([0], []), f"round 2: no NLP / embedding work (nlp={NLP_CALLS}, emb={EMB_CALLS})")
check(q("PRAGMA integrity_check")[0][0] == "ok", "round 2: integrity_check ok")
con.close()

# ---------------- Streamlit renders from the updated DB ----------------
from streamlit.testing.v1 import AppTest  # noqa: E402
at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=120).run()
check(not at.exception, f"streamlit_app renders on the updated test DB (exceptions: {[e.message for e in at.exception][:2]})")
check(len(at.markdown) > 3, f"streamlit_app produced {len(at.markdown)} markdown blocks")
print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if ok else 1)

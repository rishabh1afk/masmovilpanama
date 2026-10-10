"""Data collection. Each source writes data/raw/<source>.json with a status block
and normalized items. Run:  python -m mms.collect [--only google_play,app_store,...] [--full]

Incremental by default: every collector first reads its watermark from data/masmovil.db (mms.state) and
asks the source / Apify actor only for items newer than what is stored (date filters + small limits),
drops ids that are already stored, and re-pulls comments only for posts whose comment counter grew.
Raw files therefore contain only NEW items; mms.analyze appends them to the DB. --full ignores the
date watermarks (full LOOKBACK_DAYS re-pull) but still skips stored ids."""
import json, sys, time, datetime as dt, traceback, argparse
import requests
from . import config as C
from .apify import run_actor, check_token, ApifyError
from . import state as S

UTC = dt.timezone.utc
NOW = lambda: dt.datetime.now(UTC)
CUTOFF = lambda: NOW() - dt.timedelta(days=C.LOOKBACK_DAYS)


def _iso(x):
    if x is None or x == "":
        return None
    if isinstance(x, (int, float)):
        if x > 1e12:
            x = x / 1000
        return dt.datetime.fromtimestamp(x, UTC).isoformat()
    if isinstance(x, dt.datetime):
        return (x if x.tzinfo else x.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    s = str(x).replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(s)
        return (d if d.tzinfo else d.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    except ValueError:
        try:
            return dt.datetime.strptime(str(x), "%a %b %d %H:%M:%S %z %Y").astimezone(UTC).isoformat()
        except ValueError:
            return None


def _iso_s(x):
    """_iso at whole-second precision: keeps the stored date format uniform (the app parses one format)."""
    d = _iso(x)
    return dt.datetime.fromisoformat(d).replace(microsecond=0).isoformat() if d else None


def item(channel, kind, id, date, text, **kw):
    d = dict(id=f"{channel}:{id}", channel=channel, kind=kind, date=_iso_s(date), text=(text or "").strip(),
             author=None, rating=None, app_version=None, likes=None, comments=None, shares=None,
             views=None, url=None, parent_id=None, parent_url=None, reply=None)
    d.update(kw)
    return d


def save(source, status, items=None, reason="", cost=0.0, note="", raw=None, fetched=None, fetch_state=None, mode="-"):
    """items = NEW items only (ids not yet in the DB). fetched = items returned by the source before dedupe.
    fetch_state = [{post_url, comments_seen}] applied to the DB by mms.analyze after the items are stored."""
    C.RAW.mkdir(parents=True, exist_ok=True)
    items = items or []
    dates = sorted(i["date"] for i in items if i.get("date"))
    out = dict(source=source, status=status, reason=reason, note=note, fetched_at=NOW().isoformat(),
               count=len(items), new=len(items), fetched=len(items) if fetched is None else fetched, mode=mode,
               cost_usd=round(cost, 4),
               date_min=dates[0] if dates else None, date_max=dates[-1] if dates else None,
               fetch_state=fetch_state or [], items=items)
    (C.RAW / f"{source}.json").write_text(json.dumps(out, ensure_ascii=False, default=str))
    if raw is not None:
        (C.RAW / f"{source}.raw.json").write_text(json.dumps(raw, ensure_ascii=False, default=str))
    print(f"[{source}] {status} mode={mode} fetched={out['fetched']} new={len(items)} cost=${cost:.3f} {reason}")


def _new(wm, items):
    """Drop items already stored (and in-run duplicates)."""
    seen, out = set(), []
    for i in items:
        if i["id"] in seen or not wm.is_new(i["id"]):
            continue
        seen.add(i["id"])
        out.append(i)
    return out


def _mode(wm, full):
    return "full" if full or wm.empty else "incremental"


def _day(d):
    return d.strftime("%Y-%m-%d")


# ---------------- App stores (free public endpoints, no Apify credits) ----------------
def collect_google_play(full=False):
    from google_play_scraper import reviews, Sort
    # Free public endpoint (no Apify credits). Page newest-first and stop as soon as we reach reviews
    # that are already stored (incremental) or the LOOKBACK_DAYS window / GOOGLE_PLAY_HARD_CAP.
    wm = S.load("google_play", full)
    mode = _mode(wm, full)
    stop = wm.since(overlap_days=C.INCREMENTAL_OVERLAP_DAYS).replace(tzinfo=None) if mode == "incremental" else None
    cutoff = CUTOFF().replace(tzinfo=None)
    first = C.STORE_FIRST_PAGE_INCREMENTAL if mode == "incremental" else C.MAX_REVIEWS_PER_STORE
    res, token = reviews(C.GOOGLE_PLAY_APP_ID, lang=C.STORE_LANG, country=C.STORE_COUNTRY, sort=Sort.NEWEST, count=first)

    def more_needed():
        if not (token and res and len(res) < C.GOOGLE_PLAY_HARD_CAP and res[-1]["at"] > cutoff):
            return False
        if stop is not None and (res[-1]["at"] <= stop or any(not wm.is_new(f"google_play:{r['reviewId']}") for r in res[-50:])):
            return False
        return True

    while more_needed():
        more, token = reviews(C.GOOGLE_PLAY_APP_ID, continuation_token=token, count=200)
        if not more:
            break
        res.extend(more)
    res = [r for r in res if r["at"] >= cutoff] or ([] if mode == "incremental" else res)
    items = []
    for r in res:
        items.append(item("google_play", "review", r["reviewId"], r["at"], r.get("content"),
                          author=r.get("userName"), rating=r.get("score"), app_version=r.get("reviewCreatedVersion") or r.get("appVersion"),
                          likes=r.get("thumbsUpCount"), reply=r.get("replyContent"),
                          url=f"https://play.google.com/store/apps/details?id={C.GOOGLE_PLAY_APP_ID}&hl=es&gl=PA&reviewId={r['reviewId']}"))
    new = _new(wm, items)
    save("google_play", "ok", new, fetched=len(items), mode=mode, raw=res,
         note=f"google-play-scraper (public), {mode}: newest reviews within {C.LOOKBACK_DAYS} days not yet stored, gl=PA hl=es")


def collect_app_store(full=False):
    wm = S.load("app_store", full)
    mode = _mode(wm, full)
    items, raw = [], []
    for page in range(1, 11):
        u = f"https://itunes.apple.com/{C.STORE_COUNTRY}/rss/customerreviews/page={page}/id={C.APPLE_APP_ID}/sortby=mostrecent/json"
        r = requests.get(u, timeout=30)
        if r.status_code != 200:
            break
        entries = r.json().get("feed", {}).get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        entries = [e for e in entries if "im:rating" in e]
        if not entries:
            break
        raw.extend(entries)
        page_items = []
        for e in entries:
            title = e.get("title", {}).get("label", "")
            body = e.get("content", {}).get("label", "")
            page_items.append(item("app_store", "review", e["id"]["label"], e.get("updated", {}).get("label"),
                                   f"{title}. {body}" if title else body, author=e.get("author", {}).get("name", {}).get("label"),
                                   rating=int(e["im:rating"]["label"]), app_version=e.get("im:version", {}).get("label"),
                                   likes=int(e.get("im:voteCount", {}).get("label", 0) or 0),
                                   url=f"https://apps.apple.com/pa/app/mi-mas/id{C.APPLE_APP_ID}?see-all=reviews"))
        items.extend(page_items)
        # incremental: the feed is newest-first, so a page that reaches stored reviews is the last one we need
        if mode == "incremental" and any(not wm.is_new(i["id"]) for i in page_items):
            break
        if len(items) >= C.MAX_REVIEWS_PER_STORE:
            break
    items = items[:C.MAX_REVIEWS_PER_STORE]
    if not items:
        return save("app_store", "failed", reason="Apple RSS returned no reviews for PA storefront", mode=mode)
    new = _new(wm, items)
    save("app_store", "ok", new, fetched=len(items), mode=mode, raw=raw,
         note=f"Apple public RSS customer-reviews feed (PA storefront, most recent; Apple caps it at 500), {mode}")


# ---------------- Apify-backed socials ----------------
def _apify_guard(source):
    ok, msg = check_token()
    if not ok:
        save(source, "failed", reason=msg)
    return ok


def _post_window(wm, full):
    """(since datetime, results limit) for an owned-account post scrape."""
    if _mode(wm, full) == "full":
        return CUTOFF(), C.MAX_POSTS_PER_ACCOUNT
    return wm.since(overlap_days=C.INCREMENTAL_OVERLAP_DAYS, recheck_days=C.COMMENT_RECHECK_DAYS), C.MAX_POSTS_PER_RUN


def collect_facebook(full=False):
    if not _apify_guard("facebook"):
        return
    wm = S.load("facebook", full)
    mode = _mode(wm, full)
    since, limit = _post_window(wm, full)
    cost = 0.0
    posts, c = run_actor(C.ACTORS["facebook_posts"], {"startUrls": [{"url": C.FACEBOOK_PAGE}],
                         "resultsLimit": limit, "onlyPostsNewerThan": _day(since)},
                         max_items=limit, max_charge_usd=C.MAX_CHARGE_POSTS_USD)
    cost += c
    items = []
    for p in posts:
        if not p.get("postId") and not p.get("url"):
            continue
        items.append(item("facebook", "owned_post", p.get("postId") or p.get("url"), p.get("time") or p.get("timestamp"),
                          p.get("text"), author=C.BRAND, likes=p.get("likes"), comments=p.get("comments"),
                          shares=p.get("shares"), views=p.get("viewsCount"), url=p.get("url")))
    # comments only for posts whose public comment counter grew since we last pulled them
    want = [p for p in items if p.get("url") and wm.comments_wanted(p["url"], p.get("comments"))]
    urls = [p["url"] for p in want]
    state = []
    if urls:
        inp = {"startUrls": [{"url": u} for u in urls], "resultsLimit": C.MAX_COMMENTS_PER_POST,
               "includeNestedComments": False}
        if mode == "incremental":
            inp.update(viewOption="RECENT_ACTIVITY",
                       onlyCommentsNewerThan=_day(wm.since(overlap_days=C.INCREMENTAL_OVERLAP_DAYS, kind="comment")))
        com, c = run_actor(C.ACTORS["facebook_comments"], inp,
                           max_items=len(urls) * C.MAX_COMMENTS_PER_POST, max_charge_usd=C.MAX_CHARGE_COMMENTS_USD)
        cost += c
        state = [dict(post_url=p["url"], comments_seen=int(p.get("comments") or 0)) for p in want]
        for k in com:
            if not k.get("text"):
                continue
            purl = k.get("facebookUrl") or k.get("inputUrl")
            items.append(item("facebook", "comment", k.get("id") or k.get("commentUrl"), k.get("date"), k.get("text"),
                              author=k.get("profileName"), likes=int(k.get("likesCount") or 0) if str(k.get("likesCount") or "0").isdigit() else None,
                              url=k.get("commentUrl") or purl, parent_url=purl))
    new = _new(wm, items)
    save("facebook", "ok", new, cost=cost, fetched=len(items), mode=mode, fetch_state=state,
         note=f"{C.ACTORS['facebook_posts']} + {C.ACTORS['facebook_comments']} ({mode} since {_day(since)}; comments re-pulled for {len(urls)} posts)")


def collect_instagram(full=False):
    if not _apify_guard("instagram"):
        return
    wm = S.load("instagram", full)
    mode = _mode(wm, full)
    since, limit = _post_window(wm, full)
    cost = 0.0
    posts, c = run_actor(C.ACTORS["instagram_posts"], {"directUrls": [C.INSTAGRAM_PROFILE], "resultsType": "posts",
                         "resultsLimit": limit, "onlyPostsNewerThan": _day(since),
                         "addParentData": False}, max_items=limit, max_charge_usd=C.MAX_CHARGE_POSTS_USD)
    cost += c
    items = []
    for p in posts:
        if not p.get("url"):
            continue
        items.append(item("instagram", "owned_post", p.get("id") or p.get("shortCode"), p.get("timestamp"), p.get("caption"),
                          author=p.get("ownerUsername"), likes=p.get("likesCount"), comments=p.get("commentsCount"),
                          views=p.get("videoViewCount") or p.get("videoPlayCount"), url=p.get("url")))
    # instagram-comment-scraper has no date filter: only pull posts whose comment counter grew, and only
    # as many comments as the counter grew by (capped), so we pay for as few already-stored comments as possible.
    want = [p for p in items if wm.comments_wanted(p["url"], p.get("comments"))]
    state = []
    if want:
        per = C.MAX_COMMENTS_PER_POST
        if mode == "incremental":
            per = max(min(C.MAX_COMMENTS_PER_POST,
                          max(int(p.get("comments") or 0) - wm.seen_count(p["url"]) for p in want)), 1)
        com, c = run_actor(C.ACTORS["instagram_comments"], {"directUrls": [p["url"] for p in want], "resultsLimit": per},
                           max_items=len(want) * per, max_charge_usd=C.MAX_CHARGE_COMMENTS_USD)
        cost += c
        state = [dict(post_url=p["url"], comments_seen=int(p.get("comments") or 0)) for p in want]
        for k in com:
            if not k.get("text"):
                continue
            items.append(item("instagram", "comment", k.get("id"), k.get("timestamp"), k.get("text"),
                              author=k.get("ownerUsername"), likes=k.get("likesCount"),
                              url=k.get("postUrl"), parent_url=k.get("postUrl")))
    new = _new(wm, items)
    save("instagram", "ok", new, cost=cost, fetched=len(items), mode=mode, fetch_state=state,
         note=f"{C.ACTORS['instagram_posts']} + {C.ACTORS['instagram_comments']} ({mode} since {_day(since)}; comments re-pulled for {len(want)} posts)")


# TikTok hashtag search is noisy (Spain's MásMóvil, "móvil" gaming, ATH Móvil...). Keep only Panama-relevant,
# in-window videos, and only comments on those videos.
import re as _re
from .taxonomy import norm as _norm
_TT_REL = _re.compile(r"panama|\bpty\b|\b507\b|\+ ?movil|masmovilpanama|mas ?movil")
_TT_NOISE = _re.compile(r"€|espana|masmovil_es|movistar|ath ?movil|free ?fire|roblox|yarts|mobilador|movilador")


def filter_tiktok(items):
    cut = CUTOFF().isoformat()
    vids = {i["url"] for i in items if i["kind"] != "comment"
            and (i["date"] or "") >= cut
            and (i["kind"] == "owned_post" or (_TT_REL.search(_norm(i["text"]) + " " + _norm(i.get("author")))
                                               and not _TT_NOISE.search(_norm(i["text"]) + " " + _norm(i.get("author")))))}
    seen, out = set(), []
    for i in items:
        key = i["id"]
        if key in seen:
            continue
        seen.add(key)
        if i["kind"] == "comment":
            if i.get("parent_url") in vids and (i["date"] or "") >= cut:
                out.append(i)
        elif i["url"] in vids:
            out.append(i)
    return out


def collect_tiktok(full=False):
    if not _apify_guard("tiktok"):
        return
    wm = S.load("tiktok", full)
    mode = _mode(wm, full)
    since, limit = _post_window(wm, full)
    cost = 0.0
    posts, c = run_actor(C.ACTORS["tiktok_posts"], {"profiles": [C.TIKTOK_PROFILE], "hashtags": C.TIKTOK_HASHTAGS,
                         "resultsPerPage": limit, "oldestPostDateUnified": _day(since), "profileSorting": "latest",
                         "shouldDownloadVideos": False, "shouldDownloadCovers": False},
                         max_items=limit * (1 + len(C.TIKTOK_HASHTAGS)), max_charge_usd=C.MAX_CHARGE_POSTS_USD)
    cost += c
    items = []
    for p in posts:
        if not p.get("webVideoUrl"):
            continue
        author = (p.get("authorMeta") or {}).get("name")
        kind = "owned_post" if (author or "").lower() == C.TIKTOK_PROFILE.lower() else "mention"
        items.append(item("tiktok", kind, p.get("id"), p.get("createTimeISO") or p.get("createTime"), p.get("text"),
                          author=author, likes=p.get("diggCount"), comments=p.get("commentCount"),
                          shares=p.get("shareCount"), views=p.get("playCount"), url=p.get("webVideoUrl")))
    items = filter_tiktok(items)
    want = [p for p in items if wm.comments_wanted(p["url"], p.get("comments"))][: C.MAX_POSTS_PER_ACCOUNT]
    state = []
    if want:
        com, c = run_actor(C.ACTORS["tiktok_comments"], {"postURLs": [p["url"] for p in want], "commentsPerPost": C.MAX_COMMENTS_PER_POST},
                           max_items=len(want) * C.MAX_COMMENTS_PER_POST, max_charge_usd=C.MAX_CHARGE_COMMENTS_USD)
        cost += c
        state = [dict(post_url=p["url"], comments_seen=int(p.get("comments") or 0)) for p in want]
        for k in com:
            if not k.get("text"):
                continue
            items.append(item("tiktok", "comment", k.get("cid"), k.get("createTimeISO") or k.get("createTime"), k.get("text"),
                              author=k.get("uniqueId"), likes=k.get("diggCount"),
                              url=k.get("videoWebUrl"), parent_url=k.get("videoWebUrl")))
    items = filter_tiktok(items)
    new = _new(wm, items)
    save("tiktok", "ok", new, cost=cost, fetched=len(items), mode=mode, fetch_state=state,
         note=f"{C.ACTORS['tiktok_posts']} + {C.ACTORS['tiktok_comments']} ({mode} since {_day(since)}; comments re-pulled for {len(want)} videos)")


def collect_x(full=False):
    ok, msg = check_token()
    if not ok:
        # No Apify token: keep the stored X history (analyze marks the channel stale). The one-time snapshot
        # imported via the X API connector is only used to seed an empty DB.
        snap = C.RAW / "x_mcp_import.json"
        wm = S.load("x", full)
        if snap.exists():
            j = json.loads(snap.read_text())
            items = []
            for d in j["items"]:
                pm = d.get("public_metrics", {})
                items.append(item("x", "mention", d["id"], d["created_at"], d.get("text"), author=d.get("username"),
                                  likes=pm.get("like_count"), comments=pm.get("reply_count"),
                                  shares=(pm.get("retweet_count", 0) + pm.get("quote_count", 0)),
                                  views=pm.get("impression_count"),
                                  url=f"https://x.com/{d.get('username') or 'i'}/status/{d['id']}"))
            return save("x", "partial", _new(wm, items), cost=0.0, fetched=len(items), mode=_mode(wm, full),
                        reason=f"Apify unavailable ({msg}); using snapshot imported via X API (max 25 newest posts per week)",
                        note=j.get("method", ""))
        return save("x", "failed", reason=msg)
    wm = S.load("x", full)
    mode = _mode(wm, full)
    since_dt = CUTOFF() if mode == "full" else wm.since(overlap_days=C.INCREMENTAL_OVERLAP_DAYS)
    since = _day(since_dt)
    cap = C.MAX_X_ITEMS if mode == "full" else C.MAX_X_ITEMS_INCREMENTAL
    res, cost = run_actor(C.ACTORS["x_search"], {"searchTerms": [f"{q} since:{since} -filter:retweets" for q in C.X_SEARCH],
                          "maxItems": cap, "sort": "Latest"}, max_items=cap, max_charge_usd=C.MAX_CHARGE_X_USD)
    items = []
    for t in res:
        if not t.get("id") or t.get("type") == "mock_tweet":
            continue
        a = (t.get("author") or {}).get("userName")
        if (a or "").lower() == C.X_HANDLE.lower():
            kind = "owned_post"
        else:
            kind = "mention"
        items.append(item("x", kind, t["id"], t.get("createdAt"), t.get("text"), author=a, likes=t.get("likeCount"),
                          comments=t.get("replyCount"), shares=(t.get("retweetCount") or 0) + (t.get("quoteCount") or 0),
                          views=t.get("viewCount"), url=t.get("url")))
    # Panama-only guard: keep tweets that reference the Panama brand/handles (drops Spain's MásMóvil etc.)
    pan = _re.compile(r"masmovilpanama|masmovilayuda|panama|\bpty\b|\b507\b|\+ ?movil")
    before = len(items)
    items = [i for i in items if pan.search(_norm(i["text"]) + " " + _norm(i.get("author")))]
    new = _new(wm, items)
    save("x", "ok", new, cost=cost, fetched=len(items), mode=mode,
         note=f"{C.ACTORS['x_search']} ({mode} since {since}; Panama filter kept {len(items)}/{before})")


def collect_linkedin(full=False):
    if not C.ACTORS.get("linkedin_posts"):
        return save("linkedin", "not_connected",
                    reason="No low-cost, reliable LinkedIn company-posts actor configured (LinkedIn needs login/cookies); low customer-sentiment value")


SOURCES = {"google_play": collect_google_play, "app_store": collect_app_store, "facebook": collect_facebook,
           "instagram": collect_instagram, "tiktok": collect_tiktok, "x": collect_x, "linkedin": collect_linkedin}


def main(only=None, full=False):
    # Start from a clean slate so analyze only ever sees raw files written by THIS run.
    if C.RAW.exists():
        for f in C.RAW.glob("*.json"):
            if f.name != "x_mcp_import.json" and (not only or f.name.split(".")[0] in only):
                f.unlink()
    for name, fn in SOURCES.items():
        if only and name not in only:
            continue
        try:
            fn(full=full)
        except ApifyError as e:
            save(name, "failed", reason=str(e)[:300])
        except Exception as e:
            traceback.print_exc()
            save(name, "failed", reason=f"{type(e).__name__}: {str(e)[:250]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--full", action="store_true", help="ignore date watermarks (full LOOKBACK_DAYS re-pull); stored ids still skipped")
    a = ap.parse_args()
    main([s for s in a.only.split(",") if s] or None, full=a.full)

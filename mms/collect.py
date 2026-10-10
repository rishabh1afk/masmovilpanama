"""Data collection. Each source writes data/raw/<source>.json with a status block
and normalized items. Run:  python -m mms.collect [--only google_play,app_store,...]"""
import json, sys, time, datetime as dt, traceback, argparse
import requests
from . import config as C
from .apify import run_actor, check_token, ApifyError

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


def item(channel, kind, id, date, text, **kw):
    d = dict(id=f"{channel}:{id}", channel=channel, kind=kind, date=_iso(date), text=(text or "").strip(),
             author=None, rating=None, app_version=None, likes=None, comments=None, shares=None,
             views=None, url=None, parent_id=None, parent_url=None, reply=None)
    d.update(kw)
    return d


def save(source, status, items=None, reason="", cost=0.0, note="", raw=None):
    C.RAW.mkdir(parents=True, exist_ok=True)
    items = items or []
    dates = sorted(i["date"] for i in items if i.get("date"))
    out = dict(source=source, status=status, reason=reason, note=note, fetched_at=NOW().isoformat(),
               count=len(items), cost_usd=round(cost, 4),
               date_min=dates[0] if dates else None, date_max=dates[-1] if dates else None, items=items)
    (C.RAW / f"{source}.json").write_text(json.dumps(out, ensure_ascii=False, default=str))
    if raw is not None:
        (C.RAW / f"{source}.raw.json").write_text(json.dumps(raw, ensure_ascii=False, default=str))
    print(f"[{source}] {status} items={len(items)} cost=${cost:.3f} {reason}")


# ---------------- App stores (free public endpoints, no Apify credits) ----------------
def collect_google_play():
    from google_play_scraper import reviews, Sort
    # Free public endpoint (no Apify credits): page newest-first until the 90-day window is covered
    # or GOOGLE_PLAY_HARD_CAP is hit.
    res, token = reviews(C.GOOGLE_PLAY_APP_ID, lang=C.STORE_LANG, country=C.STORE_COUNTRY,
                         sort=Sort.NEWEST, count=C.MAX_REVIEWS_PER_STORE)
    cutoff = CUTOFF().replace(tzinfo=None)
    while token and len(res) < C.GOOGLE_PLAY_HARD_CAP and res and res[-1]["at"] > cutoff:
        more, token = reviews(C.GOOGLE_PLAY_APP_ID, continuation_token=token, count=200)
        if not more:
            break
        res.extend(more)
    res = [r for r in res if r["at"] >= cutoff] or res
    items = []
    for r in res:
        items.append(item("google_play", "review", r["reviewId"], r["at"], r.get("content"),
                          author=r.get("userName"), rating=r.get("score"), app_version=r.get("reviewCreatedVersion") or r.get("appVersion"),
                          likes=r.get("thumbsUpCount"), reply=r.get("replyContent"),
                          url=f"https://play.google.com/store/apps/details?id={C.GOOGLE_PLAY_APP_ID}&hl=es&gl=PA&reviewId={r['reviewId']}"))
    save("google_play", "ok", items, note=f"google-play-scraper (public), newest reviews within {C.LOOKBACK_DAYS} days, gl=PA hl=es", raw=res)


def collect_app_store():
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
        for e in entries:
            title = e.get("title", {}).get("label", "")
            body = e.get("content", {}).get("label", "")
            items.append(item("app_store", "review", e["id"]["label"], e.get("updated", {}).get("label"),
                              f"{title}. {body}" if title else body, author=e.get("author", {}).get("name", {}).get("label"),
                              rating=int(e["im:rating"]["label"]), app_version=e.get("im:version", {}).get("label"),
                              likes=int(e.get("im:voteCount", {}).get("label", 0) or 0),
                              url=f"https://apps.apple.com/pa/app/mi-mas/id{C.APPLE_APP_ID}?see-all=reviews"))
        if len(items) >= C.MAX_REVIEWS_PER_STORE:
            break
    items = items[:C.MAX_REVIEWS_PER_STORE]
    if not items:
        return save("app_store", "failed", reason="Apple RSS returned no reviews for PA storefront")
    save("app_store", "ok", items, note="Apple public RSS customer-reviews feed (PA storefront, most recent; Apple caps it at 500)", raw=raw)


# ---------------- Apify-backed socials ----------------
def _apify_guard(source):
    ok, msg = check_token()
    if not ok:
        save(source, "failed", reason=msg)
    return ok


def collect_facebook():
    if not _apify_guard("facebook"):
        return
    cost = 0.0
    posts, c = run_actor(C.ACTORS["facebook_posts"], {"startUrls": [{"url": C.FACEBOOK_PAGE}],
                         "resultsLimit": C.MAX_POSTS_PER_ACCOUNT, "onlyPostsNewerThan": f"{C.LOOKBACK_DAYS} days"},
                         max_items=C.MAX_POSTS_PER_ACCOUNT)
    cost += c
    items = []
    for p in posts:
        if not p.get("postId") and not p.get("url"):
            continue
        items.append(item("facebook", "owned_post", p.get("postId") or p.get("url"), p.get("time") or p.get("timestamp"),
                          p.get("text"), author=C.BRAND, likes=p.get("likes"), comments=p.get("comments"),
                          shares=p.get("shares"), views=p.get("viewsCount"), url=p.get("url")))
    urls = [p["url"] for p in items if p.get("url")]
    if urls:
        com, c = run_actor(C.ACTORS["facebook_comments"], {"startUrls": [{"url": u} for u in urls],
                           "resultsLimit": C.MAX_COMMENTS_PER_POST, "includeNestedComments": False},
                           max_items=len(urls) * C.MAX_COMMENTS_PER_POST)
        cost += c
        for k in com:
            if not k.get("text"):
                continue
            purl = k.get("facebookUrl") or k.get("inputUrl")
            items.append(item("facebook", "comment", k.get("id") or k.get("commentUrl"), k.get("date"), k.get("text"),
                              author=k.get("profileName"), likes=int(k.get("likesCount") or 0) if str(k.get("likesCount") or "0").isdigit() else None,
                              url=k.get("commentUrl") or purl, parent_url=purl))
    save("facebook", "ok", items, cost=cost, note=f"{C.ACTORS['facebook_posts']} + {C.ACTORS['facebook_comments']}")


def collect_instagram():
    if not _apify_guard("instagram"):
        return
    cost = 0.0
    posts, c = run_actor(C.ACTORS["instagram_posts"], {"directUrls": [C.INSTAGRAM_PROFILE], "resultsType": "posts",
                         "resultsLimit": C.MAX_POSTS_PER_ACCOUNT, "onlyPostsNewerThan": f"{C.LOOKBACK_DAYS} days",
                         "addParentData": False}, max_items=C.MAX_POSTS_PER_ACCOUNT)
    cost += c
    items = []
    for p in posts:
        if not p.get("url"):
            continue
        items.append(item("instagram", "owned_post", p.get("id") or p.get("shortCode"), p.get("timestamp"), p.get("caption"),
                          author=p.get("ownerUsername"), likes=p.get("likesCount"), comments=p.get("commentsCount"),
                          views=p.get("videoViewCount") or p.get("videoPlayCount"), url=p.get("url")))
    urls = [p["url"] for p in items]
    if urls:
        com, c = run_actor(C.ACTORS["instagram_comments"], {"directUrls": urls, "resultsLimit": C.MAX_COMMENTS_PER_POST},
                           max_items=len(urls) * C.MAX_COMMENTS_PER_POST)
        cost += c
        for k in com:
            if not k.get("text"):
                continue
            items.append(item("instagram", "comment", k.get("id"), k.get("timestamp"), k.get("text"),
                              author=k.get("ownerUsername"), likes=k.get("likesCount"),
                              url=k.get("postUrl"), parent_url=k.get("postUrl")))
    save("instagram", "ok", items, cost=cost, note=f"{C.ACTORS['instagram_posts']} + {C.ACTORS['instagram_comments']}")


def collect_tiktok():
    if not _apify_guard("tiktok"):
        return
    cost = 0.0
    posts, c = run_actor(C.ACTORS["tiktok_posts"], {"profiles": [C.TIKTOK_PROFILE], "hashtags": C.TIKTOK_HASHTAGS,
                         "resultsPerPage": C.MAX_POSTS_PER_ACCOUNT, "oldestPostDateUnified": f"{C.LOOKBACK_DAYS} days",
                         "shouldDownloadVideos": False, "shouldDownloadCovers": False},
                         max_items=C.MAX_POSTS_PER_ACCOUNT * (1 + len(C.TIKTOK_HASHTAGS)))
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
    urls = [p["url"] for p in items if (p.get("comments") or 0) > 0][: C.MAX_POSTS_PER_ACCOUNT]
    if urls:
        com, c = run_actor(C.ACTORS["tiktok_comments"], {"postURLs": urls, "commentsPerPost": C.MAX_COMMENTS_PER_POST},
                           max_items=len(urls) * C.MAX_COMMENTS_PER_POST)
        cost += c
        for k in com:
            if not k.get("text"):
                continue
            items.append(item("tiktok", "comment", k.get("cid"), k.get("createTimeISO") or k.get("createTime"), k.get("text"),
                              author=k.get("uniqueId"), likes=k.get("diggCount"),
                              url=k.get("videoWebUrl"), parent_url=k.get("videoWebUrl")))
    save("tiktok", "ok", items, cost=cost, note=f"{C.ACTORS['tiktok_posts']} + {C.ACTORS['tiktok_comments']}")


def collect_x():
    ok, msg = check_token()
    if not ok:
        # Fall back to the one-time snapshot imported through the X API connector (if present).
        snap = C.RAW / "x_mcp_import.json"
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
            return save("x", "partial", items, cost=0.0,
                        reason=f"Apify unavailable ({msg}); using snapshot imported via X API (max 25 newest posts per week)",
                        note=j.get("method", ""))
        return save("x", "failed", reason=msg)
    since = (NOW() - dt.timedelta(days=C.LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    res, cost = run_actor(C.ACTORS["x_search"], {"searchTerms": [f"{q} since:{since} -filter:retweets" for q in C.X_SEARCH],
                          "maxItems": C.MAX_X_ITEMS, "sort": "Latest"}, max_items=C.MAX_X_ITEMS)
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
    save("x", "ok", items, cost=cost, note=C.ACTORS["x_search"])


def collect_linkedin():
    if not C.ACTORS.get("linkedin_posts"):
        return save("linkedin", "not_connected",
                    reason="No low-cost, reliable LinkedIn company-posts actor configured (LinkedIn needs login/cookies); low customer-sentiment value")


SOURCES = {"google_play": collect_google_play, "app_store": collect_app_store, "facebook": collect_facebook,
           "instagram": collect_instagram, "tiktok": collect_tiktok, "x": collect_x, "linkedin": collect_linkedin}


def main(only=None):
    for name, fn in SOURCES.items():
        if only and name not in only:
            continue
        try:
            fn()
        except ApifyError as e:
            save(name, "failed", reason=str(e)[:300])
        except Exception as e:
            traceback.print_exc()
            save(name, "failed", reason=f"{type(e).__name__}: {str(e)[:250]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    main([s for s in a.only.split(",") if s] or None)

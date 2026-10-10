"""Feedback -> product-roadmap insight extraction (incremental, cached).

Per item (keyed by item id + text hash + RULES_VERSION) we cache in SQLite table `item_class`:
app-relatedness, matched product sub-issues (keyword rules), non-app service issues, request intent.
Sentence embeddings (paraphrase-multilingual-MiniLM-L12-v2, local CPU) are cached in `emb_cache` by text hash;
they assign app complaints that no keyword rule caught to the nearest sub-issue centroid (method='embedding').
Aggregates are written to data/insights.json; the Streamlit app only reads that file + the DB.
Run: python -m mms.insights"""
import json, os, re, sqlite3, hashlib, datetime as dt
import numpy as np
from . import config as C
from . import product as P
from .taxonomy import norm

os.environ.setdefault("HF_HOME", str(C.HF_HOME))
EMB_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
INSIGHTS_PATH = C.DATA / "insights.json"
RECS_PATH = C.ROOT / "recommendations.json"
SIM_MIN, SIM_MARGIN = 0.62, 0.03
STORES = {"google_play", "app_store"}
CH_LABEL = {"google_play": "Google Play", "app_store": "App Store", "facebook": "Facebook", "instagram": "Instagram",
            "tiktok": "TikTok", "x": "X"}

SUB = {s["id"]: s for s in P.SUBISSUES + P.NONAPP}
RX = {s["id"]: re.compile(s["rx"]) for s in P.SUBISSUES + P.NONAPP}
APP_RX = re.compile(P.APP_WORDS)
REQ_RX = re.compile(P.REQUEST_MARKERS)


def h(t):
    return hashlib.sha1(t.encode("utf-8")).hexdigest()


def ensure_tables(con):
    con.execute("""CREATE TABLE IF NOT EXISTS item_class (id TEXT, hash TEXT, rules_version INT, app_related INT,
                   rule_subissues TEXT, nonapp TEXT, is_request INT, PRIMARY KEY (id, hash, rules_version))""")
    con.execute("CREATE TABLE IF NOT EXISTS emb_cache (hash TEXT PRIMARY KEY, vec BLOB)")
    con.execute("""CREATE TABLE IF NOT EXISTS item_insight (id TEXT PRIMARY KEY, app_related INT, subissues TEXT,
                   categories TEXT, method TEXT, nonapp TEXT, is_request INT, emb_sim REAL)""")


def classify(text, channel):
    t = norm(text)
    app = channel in STORES or bool(APP_RX.search(t))
    subs = [s["id"] for s in P.SUBISSUES if RX[s["id"]].search(t)] if app else []
    # de-duplicate overlapping rules: keep the more specific sub-issue
    drop = {"bug_errors": ("bug_login", "bug_crash", "bug_security_block", "pay_failed", "conn_data_required",
                           "pay_charged_not_applied", "acct_plans"),
            "bug_login": ("bug_security_block",), "bug_compat": ("bug_security_block",),
            "bug_crash": ("conn_data_required", "bug_security_block"),
            "pay_extra_day": (), "acct_plans": ("pay_charged_not_applied",)}
    subs = [x for x in subs if not any(y in subs for y in drop.get(x, ()))]
    # "lenta" about data/internet speed is a network complaint, not app slowness
    if "ux_slow" in subs and re.search(r"(data|datos|internet|senal|\bred\b|velocidad)", t) and not re.search(r"\bapp|aplicacion|carga", t):
        subs.remove("ux_slow")
    nonapp = [s["id"] for s in P.NONAPP if RX[s["id"]].search(t)]
    return int(app), subs, nonapp, int(bool(REQ_RX.search(t)))


def embed(con, texts):
    todo = [t for t in dict.fromkeys(texts) if not con.execute("SELECT 1 FROM emb_cache WHERE hash=?", (h(t),)).fetchone()]
    if todo:
        print(f"embedding {len(todo)} new texts")
        import torch
        from transformers import AutoTokenizer, AutoModel
        tok = AutoTokenizer.from_pretrained(EMB_MODEL)
        mdl = AutoModel.from_pretrained(EMB_MODEL).eval()
        for i in range(0, len(todo), 64):
            b = todo[i:i + 64]
            enc = tok(b, return_tensors="pt", padding=True, truncation=True, max_length=192)
            with torch.no_grad():
                out = mdl(**enc).last_hidden_state
            m = enc["attention_mask"].unsqueeze(-1).float()
            v = (out * m).sum(1) / m.sum(1)
            v = torch.nn.functional.normalize(v, dim=-1).numpy().astype(np.float16)
            con.executemany("INSERT OR REPLACE INTO emb_cache VALUES (?,?)", [(h(t), x.tobytes()) for t, x in zip(b, v)])
        con.commit()
    vecs = {}
    for t in texts:
        r = con.execute("SELECT vec FROM emb_cache WHERE hash=?", (h(t),)).fetchone()
        vecs[t] = np.frombuffer(r[0], dtype=np.float16).astype(np.float32)
    return vecs


def run():
    con = sqlite3.connect(C.DB_PATH)
    ensure_tables(con)
    items = con.execute("""SELECT id, channel, kind, date, text, text_en, rating, sentiment, score, url
                           FROM items WHERE kind != 'owned_post' AND text IS NOT NULL AND length(trim(text)) > 0""").fetchall()
    cols = ["id", "channel", "kind", "date", "text", "text_en", "rating", "sentiment", "score", "url"]
    items = [dict(zip(cols, r)) for r in items]
    end = max(i["date"] for i in items if i["date"])
    start = (dt.datetime.fromisoformat(end) - dt.timedelta(days=C.LOOKBACK_DAYS)).isoformat()
    items = [i for i in items if i["date"] and i["date"] >= start]

    # 1) rule classification, cached per (id, text hash, rules version)
    new = 0
    for i in items:
        key = (i["id"], h(i["text"]), P.RULES_VERSION)
        r = con.execute("SELECT app_related, rule_subissues, nonapp, is_request FROM item_class WHERE id=? AND hash=? AND rules_version=?", key).fetchone()
        if not r:  # new item or rules changed
            app, subs, nonapp, req = classify(i["text"], i["channel"])
            con.execute("INSERT OR REPLACE INTO item_class VALUES (?,?,?,?,?,?,?)", (*key, app, json.dumps(subs), json.dumps(nonapp), req))
            r = (app, json.dumps(subs), json.dumps(nonapp), req)
            new += 1
        i["app"], i["rule_subs"], i["nonapp"], i["req"] = r[0], json.loads(r[1]), json.loads(r[2]), r[3]
        # Only complaints/requests count: drop clearly positive items (praise that merely mentions a feature)
        is_pos = i["sentiment"] == "positive" and (i["rating"] is None or i["rating"] >= 4)
        if is_pos and not i["req"]:
            i["rule_subs"], i["nonapp"] = [], []
    con.commit()
    print(f"rule-classified {new} new items (cached: {len(items) - new})")

    # 2) embeddings (cached) -> centroid assignment for uncaught app complaints
    app_items = [i for i in items if i["app"]]
    vecs = embed(con, [i["text"] for i in app_items])
    cents = {}
    for sid in [s["id"] for s in P.SUBISSUES]:
        seeds = [vecs[i["text"]] for i in app_items if sid in i["rule_subs"]]
        if len(seeds) >= 3:
            c = np.mean(seeds, axis=0)
            cents[sid] = c / np.linalg.norm(c)
    ids, M = list(cents), np.stack(list(cents.values())) if cents else None
    n_emb = 0
    for i in items:
        i["subs"], i["method"], i["sim"] = list(i["rule_subs"]), "rule" if i["rule_subs"] else None, None
        negative = i["sentiment"] == "negative" or (i["rating"] or 5) <= 2
        if i["app"] and not i["rule_subs"] and negative and M is not None:
            # only for complaints that are not purely about network/pricing/support
            sims = M @ vecs[i["text"]]
            o = np.argsort(-sims)
            if sims[o[0]] >= SIM_MIN and sims[o[0]] - sims[o[1]] >= SIM_MARGIN and not i["nonapp"]:
                i["subs"], i["method"], i["sim"] = [ids[o[0]]], "embedding", float(sims[o[0]])
                n_emb += 1
        i["cats"] = sorted({SUB[s]["cat"] for s in i["subs"]})
    print(f"embedding-assigned {n_emb} additional app complaints")
    con.execute("DELETE FROM item_insight")
    con.executemany("INSERT INTO item_insight VALUES (?,?,?,?,?,?,?,?)",
                    [(i["id"], i["app"], json.dumps(i["subs"]), json.dumps(i["cats"]), i["method"], json.dumps(i["nonapp"]),
                      i["req"], i["sim"]) for i in items])
    con.commit()
    aggregate(items, start, end)


def _quote(i):
    d = i["date"][:10]
    return dict(es=i["text"][:320], en=(i["text_en"] or "")[:320], channel=CH_LABEL.get(i["channel"], i["channel"]),
                date=dt.date.fromisoformat(d).strftime("%d %b %Y"), url=i["url"], rating=i["rating"], method=i["method"])


def _pick_quotes(group, k=3, used=None):
    used = used if used is not None else set()
    def q(i):
        L = len(i["text"])
        return (i["method"] == "rule", i["sentiment"] == "negative", 60 <= L <= 320, min(L, 320))
    out = []
    for i in sorted(group, key=q, reverse=True):
        if i["id"] in used or len(i["text"]) < 25:
            continue
        out.append(_quote(i)); used.add(i["id"])
        if len(out) == k:
            break
    return out


def priority(n, sev):
    score = n * sev
    if (sev == 3 and n >= 10) or score >= 60:
        return "High", score
    if score >= 20:
        return "Medium", score
    return "Low", score


def aggregate(items, start, end):
    recs = json.loads(RECS_PATH.read_text()) if RECS_PATH.exists() else {}
    app_items = [i for i in items if i["app"]]
    n_app = len(app_items)
    used = set()
    n_app_issue = sum(1 for i in app_items if i["subs"]) or 1
    n_nonapp_items = sum(1 for i in items if i["nonapp"]) or 1
    subs_out = []
    for s in P.SUBISSUES + P.NONAPP:
        nonapp = s["cat"] == P.NONAPP_CATEGORY
        g = [i for i in items if s["id"] in (i["nonapp"] if nonapp else i["subs"])]
        if not g:
            continue
        den = len(items) if nonapp else n_app
        reqs = [i for i in g if i["req"]]
        chans = {}
        for i in g:
            chans[CH_LABEL[i["channel"]]] = chans.get(CH_LABEL[i["channel"]], 0) + 1
        pr, score = priority(len(g), s["sev"])
        rec = recs.get(s["id"], {})
        quotes = _pick_quotes(g, 3, used)
        subs_out.append(dict(
            id=s["id"], category=s["cat"], label=s["label"], severity=s["sev"], n=len(g),
            pct=round(len(g) / den * 100, 1), pct_base="all feedback" if nonapp else "app feedback",
            pct_complaints=round(len(g) / (n_nonapp_items if nonapp else n_app_issue) * 100, 1),
            n_rule=sum(i["method"] == "rule" or nonapp for i in g), n_embedding=sum(i["method"] == "embedding" for i in g),
            n_negative=sum(i["sentiment"] == "negative" for i in g), n_requests=len(reqs),
            channels=dict(sorted(chans.items(), key=lambda x: -x[1])), priority=pr, priority_score=score,
            first_seen=min(i["date"] for i in g)[:10], last_seen=max(i["date"] for i in g)[:10],
            quotes=quotes, request_quotes=_pick_quotes(reqs, 2, used),
            evidence_url=quotes[0]["url"] if quotes else None,
            user_need=rec.get("user_need"), product_change=rec.get("product_change")))
    cats = []
    for c in P.APP_CATEGORIES + [P.NONAPP_CATEGORY]:
        nonapp = c == P.NONAPP_CATEGORY
        g = [i for i in items if (i["nonapp"] if nonapp else c in i["cats"])]
        cats.append(dict(category=c, n=len(g), pct=round(len(g) / (len(items) if nonapp else n_app) * 100, 1) if g else 0,
                         subissues=[s["id"] for s in sorted([x for x in subs_out if x["category"] == c], key=lambda x: -x["n"])]))
    ch = {}
    for i in items:
        ch[CH_LABEL[i["channel"]]] = ch.get(CH_LABEL[i["channel"]], 0) + 1
    out = dict(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(), rules_version=P.RULES_VERSION,
        coverage=dict(n_items=len(items), n_app=n_app, n_app_issue=sum(1 for i in app_items if i["subs"]),
                      n_nonapp=sum(1 for i in items if i["nonapp"]), start=start[:10], end=end[:10], channels=ch),
        method=dict(rules="Keyword rules per sub-issue (Panamanian Spanish + English), cached per item id + text hash",
                    embeddings=f"{EMB_MODEL} (local CPU); uncaught negative app items assigned to nearest sub-issue centroid "
                               f"if cosine ≥ {SIM_MIN} and margin ≥ {SIM_MARGIN}",
                    priority="score = mentions × severity (3 blocker, 2 major, 1 minor); High if blocker with ≥10 mentions or score ≥ 60; Medium if score ≥ 20; else Low",
                    recommendations="AI-generated: hand-written by Grok Bot from the quotes in each cluster (recommendations.json)"),
        categories=cats, subissues=subs_out)
    INSIGHTS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"wrote {INSIGHTS_PATH}: {n_app} app items, {len(subs_out)} sub-issues")


if __name__ == "__main__":
    run()

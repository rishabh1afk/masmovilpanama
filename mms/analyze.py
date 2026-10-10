"""Normalize raw source files -> SQLite (data/masmovil.db) with sentiment, themes,
asks and English translations. Incremental: only items not yet stored are analysed and
appended; NLP results are also cached by text hash.  Run: python -m mms.analyze"""
import json, os, sqlite3, hashlib, datetime as dt
from . import config as C
from .taxonomy import themes_for, asks_for, has_request
from .state import ensure_fetch_state

os.environ.setdefault("HF_HOME", str(C.HF_HOME))
SENT_MODEL = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
MT_MODEL = "Helsinki-NLP/opus-mt-es-en"


def h(t):
    return hashlib.sha1(t.encode("utf-8")).hexdigest()


def db():
    con = sqlite3.connect(C.DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS nlp_cache (hash TEXT PRIMARY KEY, lang TEXT, p_neg REAL, p_neu REAL,
                   p_pos REAL, en TEXT)""")
    return con


def detect_lang(t):
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
    try:
        return detect(t) if len(t) >= 12 else "es"
    except Exception:
        return "es"


def run_nlp(con, texts):
    todo = [t for t in set(texts) if t and not con.execute("SELECT 1 FROM nlp_cache WHERE hash=?", (h(t),)).fetchone()]
    if not todo:
        return
    print(f"NLP on {len(todo)} new texts")
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification, MarianMTModel, MarianTokenizer
    torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
    tok = AutoTokenizer.from_pretrained(SENT_MODEL)
    mdl = AutoModelForSequenceClassification.from_pretrained(SENT_MODEL).eval()
    probs = {}
    for i in range(0, len(todo), 32):
        b = todo[i:i + 32]
        enc = tok(b, return_tensors="pt", padding=True, truncation=True, max_length=256)
        with torch.no_grad():
            p = torch.softmax(mdl(**enc).logits, -1).tolist()
        for t, pp in zip(b, p):
            probs[t] = pp  # label order: negative, neutral, positive
    del mdl
    langs = {t: detect_lang(t) for t in todo}
    es = [t for t in todo if langs[t] not in ("en",)]
    en = {t: t for t in todo if langs[t] == "en"}
    mtok = MarianTokenizer.from_pretrained(MT_MODEL)
    mt = MarianMTModel.from_pretrained(MT_MODEL).eval()
    es.sort(key=len)
    for i in range(0, len(es), 16):
        b = es[i:i + 16]
        enc = mtok([x[:600] for x in b], return_tensors="pt", padding=True, truncation=True, max_length=256)
        with torch.no_grad():
            out = mt.generate(**enc, max_new_tokens=200, num_beams=2)
        for t, o in zip(b, mtok.batch_decode(out, skip_special_tokens=True)):
            en[t] = o if langs[t] == "es" or len(o) > 3 else None
        if i % 160 == 0:
            print(f"  translated {i}/{len(es)}")
    con.executemany("INSERT OR REPLACE INTO nlp_cache VALUES (?,?,?,?,?,?)",
                    [(h(t), langs[t], *probs[t], en.get(t)) for t in todo])
    con.commit()


COLS = """id TEXT PRIMARY KEY, channel TEXT, kind TEXT, date TEXT, text TEXT, text_en TEXT,
                   lang TEXT, author TEXT, rating REAL, app_version TEXT, likes REAL, comments REAL, shares REAL,
                   views REAL, url TEXT, parent_url TEXT, sentiment TEXT, score REAL, theme TEXT, themes TEXT,
                   asks TEXT, has_request INT"""


def build_row(con, i):
    """Sentiment/theme row for one item; NLP comes from nlp_cache (run_nlp must have run on its text)."""
    t = i["text"] or ""
    r = con.execute("SELECT lang,p_neg,p_neu,p_pos,en FROM nlp_cache WHERE hash=?", (h(t),)).fetchone() if t else None
    lang, pn, pu, pp, en = r if r else (None, None, None, None, None)
    if i["kind"] == "owned_post":
        label, score = None, None
    elif r:
        score = pp - pn
        label = ["negative", "neutral", "positive"][max(range(3), key=lambda k: (pn, pu, pp)[k])]
        # Store reviews: when the text model is unsure (neutral), the star rating decides.
        if label == "neutral" and i.get("rating"):
            label = "negative" if i["rating"] <= 2 else "positive" if i["rating"] >= 4 else "neutral"
    elif i.get("rating"):  # rating-only review
        label = "negative" if i["rating"] <= 2 else "positive" if i["rating"] >= 4 else "neutral"
        score = (i["rating"] - 3) / 2
    else:
        label, score = None, None
    th = themes_for(t, i["channel"])
    asks = asks_for(t, i["channel"])
    is_ask = bool(asks) and (label == "negative" or (i.get("rating") or 5) <= 2 or has_request(t))
    return (i["id"], i["channel"], i["kind"], i["date"], t, en, lang, i.get("author"), i.get("rating"),
            i.get("app_version"), i.get("likes"), i.get("comments"), i.get("shares"), i.get("views"),
            i.get("url"), i.get("parent_url"), label, score, th[0], json.dumps(th), json.dumps(asks if is_ask else []),
            int(has_request(t)))


def main():
    """Incremental: append NEW items from this run's raw files to the existing `items` table.
    Items already stored are never re-analysed or rewritten; NLP (sentiment + translation) runs only on
    texts not in nlp_cache. Every channel accumulates history; X keeps only the last LOOKBACK_DAYS days
    (as before). Sources that failed or weren't pulled keep their stored rows."""
    con = db()
    ensure_fetch_state(con)
    con.execute(f"CREATE TABLE IF NOT EXISTS items ({COLS})")
    status, items, fetch_state = {}, [], []
    for f in sorted(C.RAW.glob("*.json")):
        if f.name.endswith(".raw.json") or f.name == "x_mcp_import.json":
            continue
        j = json.loads(f.read_text())
        status[j["source"]] = {k: v for k, v in j.items() if k not in ("items", "fetch_state")}
        items.extend(j["items"])
        fetch_state.extend((j["source"], s["post_url"], s["comments_seen"]) for s in j.get("fetch_state") or [])
    pulled = set(status)
    try:
        prev_status = json.loads(C.STATUS_PATH.read_text())
    except Exception:
        prev_status = {}
    for s in prev_status:
        if s not in status:   # not pulled in this run: keep previous status as-is
            status[s] = prev_status[s]

    # skip anything already stored (collectors already dedupe; this also covers stale/hand-made raw files)
    known = {r[0] for r in con.execute("SELECT id FROM items")}
    new, seen = [], set()
    for i in items:
        if i["id"] in known or i["id"] in seen:
            continue
        seen.add(i["id"])
        new.append(i)
    run_nlp(con, [i["text"] for i in new if i["text"] and i["kind"] != "owned_post"])
    rows = [build_row(con, i) for i in new]
    con.executemany("INSERT OR IGNORE INTO items VALUES (" + ",".join("?" * 22) + ")", rows)
    if fetch_state:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        con.executemany("INSERT OR REPLACE INTO fetch_state VALUES (?,?,?,?)", [(*s, now) for s in fetch_state])
    # X: keep a rolling LOOKBACK_DAYS window (unchanged behaviour)
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=C.LOOKBACK_DAYS)).isoformat()
    pruned = con.execute("DELETE FROM items WHERE channel='x' AND date < ?", (cutoff,)).rowcount
    con.commit()

    # status: counts/dates describe everything stored for the channel; `new` = added this run
    added = {}
    for r in rows:
        added[r[1]] = added.get(r[1], 0) + 1
    for src, st in status.items():
        n, dmin, dmax = con.execute("SELECT count(*), min(date), max(date) FROM items WHERE channel=?", (src,)).fetchone()
        if st.get("status") == "failed" and n:
            st["status"] = "stale"
            st["reason"] = f"Refresh failed ({(st.get('reason') or '')[:120]}); showing last good data"
        elif not n and st.get("status") not in ("not_connected", "failed"):
            st.update(status="pending", reason="Not pulled yet in this deployment; included in the next refresh")
        if src in pulled:
            st["new"] = added.get(src, 0)
        st["count"], st["date_min"], st["date_max"] = n, dmin, dmax
    C.STATUS_PATH.write_text(json.dumps(status, indent=2, ensure_ascii=False))
    total = con.execute("SELECT count(*) FROM items").fetchone()[0]
    print(f"items table: {total} rows (+{len(rows)} new, {len(items) - len(new)} already stored skipped, {pruned} X rows aged out)")
    con.close()
    return dict(new=len(rows), skipped=len(items) - len(new), total=total, pruned=pruned)


if __name__ == "__main__":
    main()

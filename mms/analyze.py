"""Normalize raw source files -> SQLite (data/masmovil.db) with sentiment, themes,
asks and English translations. NLP results are cached by text hash so re-running
is cheap.  Run: python -m mms.analyze"""
import json, os, sqlite3, hashlib, datetime as dt
from . import config as C
from .taxonomy import themes_for, asks_for, has_request

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


def main():
    con = db()
    status, items = {}, []
    for f in sorted(C.RAW.glob("*.json")):
        if f.name.endswith(".raw.json") or f.name == "x_mcp_import.json":
            continue
        j = json.loads(f.read_text())
        status[j["source"]] = {k: v for k, v in j.items() if k != "items"}
        items.extend(j["items"])
    C.STATUS_PATH.write_text(json.dumps(status, indent=2, ensure_ascii=False))
    texts = [i["text"] for i in items if i["text"] and i["kind"] != "owned_post"]
    run_nlp(con, texts)
    rows = []
    for i in items:
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
        rows.append((i["id"], i["channel"], i["kind"], i["date"], t, en, lang, i.get("author"), i.get("rating"),
                     i.get("app_version"), i.get("likes"), i.get("comments"), i.get("shares"), i.get("views"),
                     i.get("url"), i.get("parent_url"), label, score, th[0], json.dumps(th), json.dumps(asks if is_ask else []),
                     int(has_request(t))))
    # Keep the last good data for any source that failed this run (e.g. a flaky actor or a bad token),
    # so one failure doesn't blank a channel on the hosted dashboard.
    fresh = {r[1] for r in rows}
    kept = []
    has_items = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='items'").fetchone()
    if has_items:
        for src, st in status.items():
            if st.get("status") in ("failed",) and src not in fresh:
                old_rows = con.execute("SELECT * FROM items WHERE channel=?", (src,)).fetchall()
                if old_rows:
                    kept.extend(old_rows)
                    st["status"] = "stale"
                    st["reason"] = f"Refresh failed ({st.get('reason', '')[:120]}); showing last good data"
                    st["count"] = len(old_rows)
                    ds = sorted(r[3] for r in old_rows if r[3])
                    st["date_min"], st["date_max"] = (ds[0], ds[-1]) if ds else (None, None)
        if kept:
            C.STATUS_PATH.write_text(json.dumps(status, indent=2, ensure_ascii=False))
    rows.extend(kept)
    con.execute("DROP TABLE IF EXISTS items")
    con.execute("""CREATE TABLE items (id TEXT PRIMARY KEY, channel TEXT, kind TEXT, date TEXT, text TEXT, text_en TEXT,
                   lang TEXT, author TEXT, rating REAL, app_version TEXT, likes REAL, comments REAL, shares REAL,
                   views REAL, url TEXT, parent_url TEXT, sentiment TEXT, score REAL, theme TEXT, themes TEXT,
                   asks TEXT, has_request INT)""")
    con.executemany("INSERT OR REPLACE INTO items VALUES (" + ",".join("?" * 22) + ")", rows)
    con.commit()
    print(f"items table: {len(rows)} rows")


if __name__ == "__main__":
    main()

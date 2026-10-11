"""Data shaping + HTML fragments for the card-style Streamlit dashboard (streamlit_app.py).
Pure pandas on the precomputed DB (no models); everything here is cheap enough to run per filter change."""
import html, json, sqlite3, datetime as dt
import pandas as pd
from . import config as C
from . import product as P
from .taxonomy import norm, OTHER

TZ = "America/Panama"          # customers are in Panama: day buckets use Panama time
CH = {"google_play": "Google Play", "app_store": "App Store", "facebook": "Facebook", "instagram": "Instagram",
      "tiktok": "TikTok", "x": "X"}
SOCIAL = {"facebook", "instagram", "tiktok", "x"}
KIND = {"review": "review", "comment": "comment", "mention": "mention"}
NONAPP_NAME = {"svc_network": "Network & coverage", "svc_pricing": "Prices & bill hikes", "svc_support": "Customer service"}
NONAPP_ID = {v: k for k, v in NONAPP_NAME.items()}
ASK_SHORT = {
    "Stop false security blocks (USB debugging, 'modified app', VPN)": "No false security blocks",
    "Fix sign-in, verification codes & account access": "Easier sign-in & codes",
    "Fix failed payments, recharges & card errors": "Payments & recharges that work",
    "Stop price hikes / unexpected charges without notice": "No surprise charges or hikes",
    "Improve signal & coverage, fix outages": "Better signal & coverage",
    "Faster, more helpful customer service": "Faster customer service",
    "Make the app faster & more stable": "A faster, more stable app",
    "Cheaper plans / more data & better offers": "Cheaper plans & more data",
    "Show balance, usage & invoices correctly": "Clear balance, usage & bills",
}
THEME_SHORT = {"Login, security & app blocks": "Login & security", "Payments & recharge": "Payments",
               "Billing & charges": "Billing", "App performance & bugs": "App bugs", "Network & coverage": "Network",
               "Data plans & pricing": "Plans & pricing", "Customer service": "Customer service",
               "Promotions, rewards & content": "Promotions", OTHER: "General"}
SENT_COL = {"negative": "#e05252", "neutral": "#a1a1aa", "positive": "#3b6fe0"}
SENT_FILL = {"negative": "rgba(224,82,82,0.07)", "neutral": "rgba(161,161,170,0.06)", "positive": "rgba(59,111,224,0.07)"}

e = lambda s: html.escape("" if s is None else str(s))
_MD_SPECIAL = set("\\`*_{}[]()#+-.!|~<>$:=")


def md(s):
    """Escape user text for a Streamlit markdown widget label (no emphasis, links, LaTeX, directives or emoji codes)."""
    s = " ".join(("" if s is None else str(s)).split())
    return "".join("\\" + c if c in _MD_SPECIAL else c for c in s)


def _jl(x):
    if isinstance(x, list):
        return x
    if not isinstance(x, str) or not x:
        return []
    try:
        v = json.loads(x)
        return v if isinstance(v, list) else []
    except Exception:
        return []


# ---------------------------------------------------------------- data
def load_voice(db_path=None):
    """Customer voice (everything but the brand's own posts) + product classification, one row per item."""
    con = sqlite3.connect(db_path or C.DB_PATH)
    d = pd.read_sql("""SELECT i.id, i.channel, i.kind, i.date, i.text, i.text_en, i.lang, i.author, i.rating, i.url,
                              i.parent_url, i.sentiment, i.score, i.themes, i.asks, i.has_request,
                              ii.subissues, ii.categories, ii.nonapp, ii.is_request
                       FROM items i LEFT JOIN item_insight ii ON i.id = ii.id
                       WHERE i.kind != 'owned_post' AND i.sentiment IS NOT NULL""", con)
    con.close()
    d["ts"] = pd.to_datetime(d["date"], utc=True, errors="coerce").dt.tz_convert(TZ).dt.tz_localize(None)
    d = d[d.ts.notna()].copy()
    d["day"] = d.ts.dt.normalize()
    for c in ["themes", "asks", "subissues", "categories", "nonapp"]:
        d[c] = d[c].apply(_jl)
    d["themes"] = d.themes.apply(lambda L: [t for t in L if t != OTHER])
    d["groups"] = d.apply(lambda r: list(r.categories) + [NONAPP_NAME[x] for x in r.nonapp if x in NONAPP_NAME], axis=1)
    d["request"] = (d.has_request.fillna(0).astype(int) == 1) | (d.is_request.fillna(0).astype(int) == 1)
    neg = d.sentiment == "negative"
    d["unhappy"] = neg
    d["needs_reply"] = neg & ((d.groups.str.len() > 0) | (d.themes.str.len() > 0) | (d.asks.str.len() > 0) | d.request
                              | (d.rating.fillna(5) <= 2))
    d["channel_label"] = d.channel.map(CH).fillna(d.channel)
    d["topic"] = d.apply(lambda r: r.groups[0] if r.groups else THEME_SHORT.get(r.themes[0], r.themes[0]) if r.themes else "General", axis=1)
    d["author"] = d.author.fillna("").astype(str)
    d["rkey"] = d.author.str.lower() + "|" + d.text.fillna("").map(lambda t: norm(t)[:120])
    d["rep_n"] = d.groupby("rkey").id.transform("size").where(d.author != "", 1)
    d["rep_posts"] = d.groupby("rkey").parent_url.transform("nunique")
    return d.sort_values("ts", ascending=False).reset_index(drop=True)


def load_status(path=None):
    try:
        return json.loads((path or C.STATUS_PATH).read_text())
    except Exception:
        return {}


def sync_banner(status, now=None, stale_days=8):
    """(bold, text) for the yellow banner, or None when the last sync is recent and clean."""
    if not status:
        return ("No sync status yet.", "The weekly refresh hasn't written data/status.json; the dashboard shows saved comments.")
    now = now or pd.Timestamp.now(tz="UTC")
    active = {k: v for k, v in status.items() if v.get("status") != "not_connected"}
    failed = {k: v for k, v in active.items() if v.get("status") not in ("ok",)}
    last = max((pd.Timestamp(v["fetched_at"]) for v in status.values() if v.get("fetched_at")), default=None)
    age = (now - last).days if last is not None else None
    if failed:
        names = ", ".join(CH.get(k, k) for k in failed)
        why = next((v.get("reason") for v in failed.values() if v.get("reason")), "")
        why = (why[:140] + "…") if len(why) > 140 else why
        why = why + "." if why and why[-1] not in ".!?…" else why
        bold = "Live sync paused." if len(failed) == len(active) else "Live sync partly failed."
        return (bold, f"Sync failed: {len(failed)} of {len(active)} channels could not fetch data ({names}). "
                      f"{e(why) + ' ' if why else ''}The dashboard still works with saved comments; "
                      "check the Apify token and account credits, then re-run the GitHub Actions refresh.")
    if age is not None and age >= stale_days:
        return ("Data is out of date.", f"Last successful sync was {age} days ago (the refresh runs weekly, Mondays 6:00 AM IST). "
                                        "The dashboard still works with saved comments; check the GitHub Actions refresh workflow.")
    return None


def last_updated(status):
    last = max((v.get("fetched_at") or "" for v in status.values()), default="")
    return pd.Timestamp(last).tz_convert("Asia/Kolkata") if last else None


def window(d, start, end):
    return d[(d.day >= pd.Timestamp(start)) & (d.day <= pd.Timestamp(end))]


def prev_window(d, start, end):
    n = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    p_end = pd.Timestamp(start) - pd.Timedelta(days=1)
    return window(d, p_end - pd.Timedelta(days=n - 1), p_end)


def score100(v):
    return None if v.empty else round((v.score.mean() + 1) * 50)


def unhappy_pct(v):
    return None if v.empty else round(v.unhappy.mean() * 100)


def comparable(n, pn, min_prev=20):
    """Only compare with the previous period when it has enough data (sources started on different dates)."""
    return pn >= min_prev and pn >= 0.3 * n


def complaints(v, pv):
    """Top complaints: 6 app product categories + 3 service groups, from the product classification."""
    x = v[v.groups.str.len() > 0]
    tot = len(x)
    ex = x.explode("groups")
    pex = pv[pv.groups.str.len() > 0].explode("groups")
    sev = {s["id"]: s["sev"] for s in P.SUBISSUES + P.NONAPP}
    rows = []
    for g, sub in ex.groupby("groups"):
        if g in NONAPP_ID:
            pscore = len(sub) * sev[NONAPP_ID[g]]
        else:
            ids = [s for L in sub.subissues for s in L if s in sev]
            pscore = sum(sev[s] for s in ids) if ids else len(sub)
        prio = "High" if pscore >= 60 else "Medium" if pscore >= 20 else "Low"
        prev = int((pex.groups == g).sum())
        ptot = pex.id.nunique()
        share, pshare = (len(sub) / tot if tot else 0), (prev / ptot if ptot else 0)
        rows.append(dict(name=g, n=len(sub), pct=round(share * 100), people=sub.author.nunique(),
                         prio=prio, pscore=pscore, prev=prev, rising=comparable(tot, ptot) and len(sub) >= 5 and share > pshare + 0.05,
                         service=g in NONAPP_ID))
    return sorted(rows, key=lambda r: (-r["n"], -r["pscore"])), tot


def asks(v, pv):
    ex = v[v.asks.str.len() > 0].explode("asks")
    pc = pv[pv.asks.str.len() > 0].explode("asks").asks.value_counts()
    vc = ex.asks.value_counts()
    ok = comparable(int(vc.sum()), int(pc.sum()))
    rows = []
    for i, (a, n) in enumerate(vc.items()):
        prev = int(pc.get(a, 0))
        pill = "Popular" if i < 2 and n >= 5 else "Growing" if ok and n >= 3 and n / vc.sum() > prev / pc.sum() + 0.03 else None
        rows.append(dict(ask=a, short=ASK_SHORT.get(a, a), n=int(n), prev=prev, pill=pill))
    return rows


def reply_first(v):
    r = v[v.needs_reply].copy()
    if r.empty:
        return r
    end = r.ts.max()
    age = (end - r.ts).dt.total_seconds() / 86400
    r["urgency"] = (-r.score) * (1 / (1 + age / 7)) * (1 + 0.25 * (r.rep_n > 1)) * (1 + 0.15 * r.request)
    return r.sort_values("urgency", ascending=False)


SENT_LABEL = {"negative": "Unhappy", "positive": "Happy", "neutral": "Neutral"}


def trend(v, start, end):
    """Comment counts per calendar day (Panama time) and sentiment, zero-filled, for any range length."""
    idx = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    g = v.groupby(["day", "sentiment"]).size().unstack(fill_value=0).reindex(idx, fill_value=0)
    for s in SENT_COL:
        if s not in g:
            g[s] = 0
    return g[list(SENT_COL)].astype(int)


def overview(v, pv, comp, ask_rows, rng_label):
    if v.empty:
        return "No customer comments in this range and channel selection."
    u, pu = unhappy_pct(v), unhappy_pct(pv)
    d = f" ({u - pu:+d} pts vs the previous period)" if pu is not None and comparable(len(v), len(pv)) else ""
    nr = int(v.needs_reply.sum())
    top_ch = v[v.needs_reply].channel_label.value_counts()
    ch = f", mostly on {top_ch.index[0]}" if len(top_ch) else ""
    s = (f"Negative sentiment stands at <b>{u}%</b> of {len(v):,} comments{d}, with <b>{nr}</b> comments flagged as "
         f"needing a reply{ch}.")
    if comp:
        top = " and ".join(f"<b>{e(c['name'])}</b> ({c['n']})" for c in comp[:2])
        s += f" Most complaints are about {top}."
    if ask_rows:
        s += f" The most common ask is <b>{e(ask_rows[0]['short'])}</b>."
    return s


# ---------------------------------------------------------------- HTML
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {background:#f3f4f6 !important}
[data-testid="stAppViewContainer"] *:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded) {font-family:Inter,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.block-container {padding-top:1.6rem !important; max-width:1320px !important}
[data-testid="stHeader"] {height:0; min-height:0}
.mm {color:#111827}
[data-testid="stWidgetLabel"] p {font-size:10.5px !important; font-weight:600 !important; color:#9ca3af !important; letter-spacing:.06em}
[data-testid="stMain"] [data-testid="stSelectbox"] div[data-baseweb="select"] > div {background:#fff; border-color:#e5e7eb; border-radius:9px; font-size:13px}
[data-testid="stMain"] [data-testid="stVerticalBlock"] {gap:0.9rem}
div[class*="st-key-card_"] [data-testid="stVerticalBlock"] {gap:0.15rem}
.mm-h1 {font-size:26px; font-weight:700; letter-spacing:-.01em; margin:4px 0 2px}
.mm-sub {color:#6b7280; font-size:13px}
.mm-lbl {font-size:10.5px; font-weight:600; color:#9ca3af; letter-spacing:.06em; text-transform:uppercase}
.mm-banner {background:#fdf3c4; border:1px solid #f4e3a1; color:#7c5b06; border-radius:10px; padding:12px 16px; font-size:13px; line-height:1.55; margin:6px 0 2px}
.mm-banner b {color:#5c4204}
/* white cards = native bordered st.container(border=True, key="card_*" / "kpi_*"); CSS only restyles them */
div[class*="st-key-card_"], div[class*="st-key-kpi_"] {
  background:#fff !important; border:1px solid #eceef1 !important; border-radius:14px !important;
  box-shadow:0 1px 3px rgba(16,24,40,.05) !important; padding:18px 20px 12px !important}
div[class*="st-key-kpi_"] {gap:0.35rem !important; justify-content:space-between}
.st-key-kpirow [data-testid="stColumn"] > div, .st-key-kpirow [data-testid="stColumn"] div:has(> div[class*="st-key-kpi_"]),
.st-key-kpirow [data-testid="stColumn"] div[class*="st-key-kpi_"] {height:100%}
.kpi {min-height:112px}
.kpi .ic {width:28px; height:28px; border-radius:7px; background:#e8efff; color:#2f5fe0; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; margin-bottom:14px}
.kpi .v {font-size:30px; font-weight:700; letter-spacing:-.02em; margin-top:4px; line-height:1.15}
.kpi .v small {font-size:15px; font-weight:500; color:#6b7280}
.kpi .v.t {font-size:19px; margin-top:8px}
.kpi .d {font-size:12px; margin-top:6px; color:#6b7280}
.up {color:#16a34a !important} .down {color:#dc2626 !important}
.card-h {display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px}
.card-h .t {font-size:15px; font-weight:650}
.card-h .r {font-size:11.5px; color:#9ca3af}
.ov {font-size:13.5px; line-height:1.6; color:#374151}
.ov .u {font-size:11.5px; color:#9ca3af; margin-top:14px}
.pill {font-size:10.5px; font-weight:600; border-radius:999px; padding:2px 9px; white-space:nowrap}
.p-y {background:#fdf0c2; color:#9a6b00} .p-g {background:#dcfce7; color:#15803d} .p-r {background:#fde2e2; color:#b42318}
.p-b {background:#e8efff; color:#2f5fe0} .p-n {background:#eef2f7; color:#94a3b8}
/* list rows = native full-width tertiary st.button (key go_<row>) */
div[class*="st-key-list_"] [data-testid="stVerticalBlock"], div[class*="st-key-card_"] div[class*="st-key-list_"] {gap:2px !important}
div[class*="st-key-list_"] .stButton button {width:100%; justify-content:flex-start; text-align:left; padding:8px 10px; margin:0;
  border-radius:8px; color:#111827; min-height:0; border:0}
div[class*="st-key-list_"] .stButton button:hover {background:#f6f8fb; color:#111827}
div[class*="st-key-list_"] .stButton button:focus:not(:active) {color:#111827}
div[class*="st-key-list_"] .stButton button > div {width:100%; justify-content:space-between; gap:12px}
div[class*="st-key-list_"] .stButton button > div > span:first-child {flex:1; min-width:0; display:flex !important;
  align-items:center; justify-content:space-between; gap:12px; width:100%}
div[class*="st-key-list_"] .stButton button [data-testid="stMarkdownContainer"] {flex:1; min-width:0}
div[class*="st-key-list_"] .stButton button p {text-align:left; font-size:13.5px; line-height:1.5; margin:0; white-space:normal}
div[class*="st-key-list_"] .stButton button strong {font-weight:500}
div[class*="st-key-list_"] .stButton button p > span:not(.stMarkdownBadge) {font-size:11.5px}
div[class*="st-key-list_"] .stButton button .stMarkdownBadge {float:right; margin:9px 0 0 10px; font-size:10.5px !important; font-weight:600}
div[class*="st-key-list_"] .stButton button [data-testid="stIconMaterial"] {color:#9ca3af}
div[class*="st-key-go_kpi_"] button {padding:0; min-height:0; font-size:12px; color:#2f5fe0}
div[class*="st-key-go_kpi_"] button p {font-size:12px; white-space:nowrap; text-align:left}
/* drawer */
div[role="dialog"] {border-radius:0 !important}
.dr-cat {font-size:10.5px; font-weight:700; color:#2f5fe0; letter-spacing:.07em; text-transform:uppercase}
.dr-sub {color:#6b7280; font-size:13px; margin:2px 0 10px}
.cc {background:#f5f6f8; border:1px solid #eceef1; border-radius:12px; padding:14px 16px; margin:0 0 10px}
.cc .top {display:flex; gap:12px; align-items:flex-start}
.cc .av {width:34px; height:34px; border-radius:50%; background:#e3eafc; color:#2f5fe0; display:flex; align-items:center; justify-content:center; font-weight:600; font-size:14px; flex:none}
.cc .who {flex:1; min-width:0}
.cc .who b {font-size:13.5px}
.cc .src {font-size:11.5px; color:#6b7280}
.cc .src a {color:#2f5fe0; text-decoration:none}
.cc .tags {display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end}
.tag {font-size:10px; font-weight:700; letter-spacing:.04em; border-radius:999px; padding:2px 8px}
.t-un {background:#fde2e2; color:#c0392b} .t-rn {background:#fdf0c2; color:#9a6b00} .t-ok {background:#dcfce7; color:#15803d}
.cc .qt {font-style:italic; font-size:13.5px; color:#111827; margin:10px 0 4px 46px; line-height:1.5}
.cc .en {font-size:12px; color:#6b7280; margin:0 0 6px 46px; line-height:1.45}
.cc .ft {display:flex; gap:8px; align-items:center; margin-left:46px; flex-wrap:wrap}
.cc .dt {font-size:11.5px; color:#6b7280}
.chip {font-size:10.5px; border:1px solid #e3e5e8; background:#fff; border-radius:6px; padding:1px 7px; color:#4b5563}
.rep {font-size:10.5px; font-weight:600; border:1px solid #f3c969; background:#fdf3d0; color:#8a5a00; border-radius:5px; padding:1px 7px}
.dr-foot {font-size:12px; color:#6b7280}
.sbar {display:flex; gap:8px; align-items:center; font-size:12.5px; padding:5px 0; border-bottom:1px solid #f1f2f4}
.sbar .l {flex:1} .sbar .k {color:#6b7280; font-size:11.5px}
[data-testid="stExpander"] details {border:1px solid #eceef1 !important; border-radius:10px !important; background:#fff}
"""


def kpi(icon, label, value, delta_html, title_value=False):
    return (f"<div class='kpi mm'><div class='ic'>{icon}</div><div class='mm-lbl'>{e(label)}</div>"
            f"<div class='v{' t' if title_value else ''}'>{value}</div><div class='d'>{delta_html}</div></div>")


def delta(cur, prev, unit, good_up=True):
    if cur is None or prev is None:
        return "<span>no comparable prior-period data</span>"
    x = cur - prev
    cls = "" if x == 0 else ("up" if (x > 0) == good_up else "down")
    return f"<span class='{cls}'>{x:+d}{unit} vs previous period</span>"


def handle(r):
    a = r.author or "anonymous"
    return a if (r.channel not in SOCIAL or a.startswith("@")) else "@" + a


def comment_card(r, show_en=True):
    h = handle(r)
    ini = (h.lstrip("@")[:1] or "?").upper()
    src = f"{e(r.channel_label)} · {KIND.get(r.kind, r.kind)}"
    if pd.notna(r.rating):
        src += f" · {int(r.rating)}★"
    if isinstance(r.url, str) and r.url.startswith("http"):
        src += f" · <a href='{e(r.url)}' target='_blank'>open ↗</a>"
    tags = ""
    if r.unhappy:
        tags += "<span class='tag t-un'>UNHAPPY</span>"
    elif r.sentiment == "positive":
        tags += "<span class='tag t-ok'>HAPPY</span>"
    if r.needs_reply:
        tags += "<span class='tag t-rn'>REPLY NOW</span>"
    txt = (r.text or "").strip()
    txt = txt if len(txt) <= 600 else txt[:600] + "…"
    en = ""
    if show_en and r.lang != "en" and isinstance(r.text_en, str) and r.text_en.strip() and r.text_en.strip() != txt:
        en = f"<div class='en'>EN: {e(r.text_en[:600])}</div>"
    rep = ""
    if r.rep_n > 1:
        rep = (f"<span class='rep'>Said {int(r.rep_n)}× on different posts</span>" if r.rep_posts > 1
               else f"<span class='rep'>Said {int(r.rep_n)}×</span>")
    return (f"<div class='cc mm'><div class='top'><div class='av'>{e(ini)}</div><div class='who'><b>{e(h)}</b>"
            f"<div class='src'>{src}</div></div><div class='tags'>{tags}</div></div>"
            f"<div class='qt'>“{e(txt)}”</div>{en}<div class='ft'><span class='dt'>{r.ts.strftime('%d %b %Y, %H:%M')}</span>"
            f"{rep}<span class='chip'>{e(r.topic)}</span></div></div>")


def rng(a, b):
    return f"{pd.Timestamp(a).strftime('%Y-%m-%d')} – {pd.Timestamp(b).strftime('%Y-%m-%d')}"

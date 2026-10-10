"""Más Móvil Panamá: user feedback → product roadmap (Streamlit).  streamlit run streamlit_app.py

Read-only at runtime: reads precomputed data/insights.json and data/masmovil.db (items + item_insight).
No ML models are loaded here; extraction runs in `python -m mms.insights` (locally or in GitHub Actions)."""
import json, os, sqlite3, datetime as dt
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from mms import config as C
from mms import product as P
from mms import render as R

st.set_page_config(page_title="Más Móvil · Feedback → Roadmap", page_icon="📶", layout="wide")
st.markdown(f"""<style>{R.CSS}
.block-container{{padding-top:2.2rem;max-width:1280px}}
[data-testid="stAppViewContainer"],[data-testid="stHeader"],[data-testid="stSidebar"]{{background:#fff}}
[data-testid="stExpander"] details{{border:1px solid #e5e7eb;border-radius:10px}}
</style>""", unsafe_allow_html=True)

INS = C.DATA / "insights.json"


@st.cache_data(show_spinner=False)
def load(mtime):
    ins = json.loads(INS.read_text())
    con = sqlite3.connect(C.DB_PATH)
    df = pd.read_sql("""SELECT i.id, i.channel, i.date, i.text, i.text_en, i.rating, i.sentiment, i.url,
                               ii.app_related, ii.subissues, ii.categories, ii.nonapp, ii.method
                        FROM items i JOIN item_insight ii ON i.id = ii.id""", con)
    con.close()
    try:
        status = json.loads(C.STATUS_PATH.read_text())
    except Exception:
        status = {}
    return ins, df, status


def ready():
    if not (INS.exists() and C.DB_PATH.exists()):
        return False
    try:
        con = sqlite3.connect(C.DB_PATH)
        ok = con.execute("SELECT count(*) FROM sqlite_master WHERE name='item_insight'").fetchone()[0] == 1
        con.close()
        return ok
    except Exception:
        return False


if not ready():
    st.markdown("### Más Móvil Panamá: user feedback → product roadmap")
    st.info("⏳ Data is loading, first refresh pending. The GitHub Actions workflow *Refresh sentiment data* builds the data; "
            "this page shows the roadmap once it has run.")
    st.stop()

ins, df, status = load(INS.stat().st_mtime + C.DB_PATH.stat().st_mtime)
last = max((s.get("fetched_at") or "" for s in status.values()), default="")
refreshed = pd.Timestamp(last).tz_convert("Asia/Kolkata").strftime("%d %b %Y, %I:%M %p IST") if last else None

st.markdown(R.header(ins, refreshed), unsafe_allow_html=True)
st.markdown(R.problems(ins), unsafe_allow_html=True)

# one small bar: complaints by product category
cats = [c for c in ins["categories"] if c["category"] != P.NONAPP_CATEGORY]
fig = go.Figure(go.Bar(x=[c["n"] for c in cats][::-1], y=[c["category"] for c in cats][::-1], orientation="h",
                       marker_color=R.ACC, text=[c["n"] for c in cats][::-1], textposition="outside"))
fig.update_layout(height=210, margin=dict(l=0, r=30, t=26, b=0), paper_bgcolor="white", plot_bgcolor="white",
                  title=dict(text="App complaints by product category (an item can sit in more than one)", font=dict(size=13, color="#374151"), x=0),
                  xaxis=dict(visible=False), yaxis=dict(tickfont=dict(size=12, color="#111827")), font=dict(color="#111827"))
st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key="catbar")

st.markdown(R.wants(ins), unsafe_allow_html=True)
st.markdown(R.opportunities(ins), unsafe_allow_html=True)

st.markdown("<div class='mm'><h2>Category deep-dives</h2><div class='sub'>Clustered sub-issues with verbatim quotes "
            "(Spanish + machine translation) and AI-generated recommendations.</div></div>", unsafe_allow_html=True)
for c in cats:
    with st.expander(f"{c['category']}: {c['n']} items · {c['pct']}% of app feedback", expanded=False):
        st.markdown(R.category(ins, c["category"]), unsafe_allow_html=True)

na = next(c for c in ins["categories"] if c["category"] == P.NONAPP_CATEGORY)
st.markdown(f"<div class='mm'><h2>Non-app / service issues</h2><div class='sub'>Secondary: network, pricing and customer service. "
            f"{na['n']} items ({na['pct']}% of all feedback), mostly from social and X. Not app changes, but worth routing to the owning teams.</div></div>",
            unsafe_allow_html=True)
with st.expander("Show non-app issues", expanded=False):
    st.markdown(R.category(ins, P.NONAPP_CATEGORY), unsafe_allow_html=True)

# ---------------- Supporting reviews ----------------
st.markdown("<div class='mm'><h2>Supporting reviews</h2><div class='sub'>Every classified item, searchable.</div></div>", unsafe_allow_html=True)
LAB = {s["id"]: s["label"] for s in ins["subissues"]}
CHL = {"google_play": "Google Play", "app_store": "App Store", "facebook": "Facebook", "instagram": "Instagram", "tiktok": "TikTok", "x": "X"}
d = df.copy()
d["date"] = pd.to_datetime(d["date"], utc=True).dt.tz_convert(None)
d["Channel"] = d.channel.map(CHL)
d["cats"] = d.categories.apply(json.loads) + d.nonapp.apply(lambda x: [P.NONAPP_CATEGORY] if json.loads(x) else [])
d["Issue"] = (d.subissues.apply(json.loads) + d.nonapp.apply(json.loads)).apply(lambda L: "; ".join(LAB.get(x, x) for x in L))
d = d[d.cats.str.len() > 0]
f1, f2, f3, f4 = st.columns([2, 2, 2, 1.4])
cat_sel = f1.multiselect("Category", P.APP_CATEGORIES + [P.NONAPP_CATEGORY], placeholder="All categories")
ch_sel = f2.multiselect("Channel", sorted(d.Channel.unique()), placeholder="All channels")
dr = f3.date_input("Date range", (d.date.min().date(), d.date.max().date()))
sent_sel = f4.multiselect("Sentiment", ["negative", "neutral", "positive"], placeholder="All")
q = st.text_input("Search text", placeholder="e.g. tarjeta, día extra, código, Yappy")
if cat_sel:
    d = d[d.cats.apply(lambda L: any(c in L for c in cat_sel))]
if ch_sel:
    d = d[d.Channel.isin(ch_sel)]
if isinstance(dr, (list, tuple)) and len(dr) == 2:
    d = d[(d.date.dt.date >= dr[0]) & (d.date.dt.date <= dr[1])]
if sent_sel:
    d = d[d.sentiment.isin(sent_sel)]
if q:
    d = d[d.text.str.contains(q, case=False, na=False) | d.text_en.fillna("").str.contains(q, case=False)]
st.caption(f"{len(d):,} items")
st.dataframe(d.sort_values("date", ascending=False)[["date", "Channel", "rating", "Issue", "text", "text_en", "sentiment", "url"]]
             .rename(columns={"date": "Date", "rating": "★", "text": "Quote (original)", "text_en": "English (MT)", "sentiment": "Sentiment", "url": "Link"}),
             width="stretch", hide_index=True, height=480,
             column_config={"Link": st.column_config.LinkColumn("Link", display_text="open"),
                            "Date": st.column_config.DatetimeColumn(format="DD MMM YYYY")})

st.markdown(R.method(ins), unsafe_allow_html=True)

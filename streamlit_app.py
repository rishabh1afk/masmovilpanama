"""Más Móvil Panamá — Brand Sentiment Dashboard (Streamlit).  streamlit run streamlit_app.py

Read-only at runtime: it only reads the precomputed data/masmovil.db + data/status.json
(produced by refresh.py locally or by the GitHub Actions workflow). No ML models are loaded here."""
import os, sys, subprocess, html, datetime as dt
import pandas as pd
import streamlit as st
from mms import config as C
from mms import metrics as M

st.set_page_config(page_title="Más Móvil · Brand Sentiment", page_icon="📶", layout="wide")
st.markdown("""<style>
.block-container{padding-top:3rem;max-width:1500px}
.kpi{background:#111a2e;border:1px solid #1f2a44;border-radius:12px;padding:14px 16px}
.kpi .l{color:#94a3b8;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.kpi .v{font-size:30px;font-weight:700;color:#f8fafc;line-height:1.2}
.kpi .s{color:#94a3b8;font-size:12px}
.src{background:#111a2e;border:1px solid #1f2a44;border-radius:10px;padding:10px 12px;font-size:12.5px;height:100%}
.ok{color:#22c55e}.partial,.stale{color:#f59e0b}.failed{color:#ef4444}.not_connected{color:#94a3b8}
.alert{border-left:4px solid #ef4444;background:#1a1420;padding:8px 12px;margin:6px 0;border-radius:6px}
.alert.medium{border-color:#f59e0b}
.quote{border-left:3px solid #38bdf8;padding:4px 10px;margin:6px 0;color:#cbd5e1;font-size:13px}
.quote .en{color:#94a3b8;font-style:italic}
h1,h2,h3{color:#f8fafc}
</style>""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def get_data(mtime):
    return M.load(), M.load_status()


if not C.DB_PATH.exists():
    st.error("No data yet. Run `python refresh.py` (or the GitHub Actions refresh) first."); st.stop()
df_all, status = get_data(C.DB_PATH.stat().st_mtime)

# ---------------- Header ----------------
h1, h2 = st.columns([5, 1.3])
with h1:
    st.markdown("## 📶 Más Móvil Panamá — Brand Sentiment")
    last = max((s.get("fetched_at") or "" for s in status.values()), default="")
    if last:
        t = pd.Timestamp(last).tz_convert("Asia/Kolkata").strftime("%d %b %Y, %I:%M %p IST")
        st.caption(f"Data last refreshed {t} · Sources: app stores, social & X · Sentiment: multilingual XLM-RoBERTa · Themes/asks: Panamanian-Spanish rules")
# The in-app refresh needs Apify + the ML models, so it is only offered locally (never on Streamlit Cloud).
ALLOW_REFRESH = os.environ.get("MMS_ALLOW_REFRESH", "0") == "1"
with h2:
    if not ALLOW_REFRESH:
        st.caption("🔄 Data refreshes daily at 06:00 IST (automated)")
    elif st.button("🔄 Refresh data", width="stretch", help="Re-pulls every source (spends Apify credits for socials) and re-runs analysis"):
        with st.spinner("Pulling sources and re-analysing… this can take several minutes"):
            r = subprocess.run([sys.executable, "refresh.py"], cwd=str(C.ROOT), capture_output=True, text=True)
        st.cache_data.clear()
        st.toast("Refresh finished" if r.returncode == 0 else "Refresh finished with errors — see source status")
        st.rerun()

# ---------------- Filters ----------------
with st.sidebar:
    st.markdown("### Filters")
    chans = [M.CH_LABEL[c] for c in M.CH_ORDER if c in set(df_all.channel)]
    sel_ch = st.multiselect("Channel", chans, default=chans)
    dmin = df_all.date.min().date(); dmax = df_all.date.max().date()
    default_start = max(dmin, dmax - dt.timedelta(days=C.LOOKBACK_DAYS))
    dr = st.date_input("Date range", (default_start, dmax), min_value=dmin, max_value=dmax)
    sel_sent = st.multiselect("Sentiment", ["positive", "neutral", "negative"], default=["positive", "neutral", "negative"])
    themes = sorted({t for ts in df_all.themes for t in ts})
    sel_th = st.multiselect("Theme", themes, default=[])
    st.caption("Theme filter keeps items tagged with any selected theme. Brand-owned posts are excluded from sentiment metrics.")

df = df_all[df_all.channel_label.isin(sel_ch)]
if isinstance(dr, (list, tuple)) and len(dr) == 2:
    df = df[(df.date.dt.date >= dr[0]) & (df.date.dt.date <= dr[1])]
df = df[df.sentiment.isin(sel_sent) | df.sentiment.isna()]
if sel_th:
    df = df[df.themes.apply(lambda ts: any(t in ts for t in sel_th))]

# ---------------- Source status ----------------
cols = st.columns(len(M.CH_ORDER))
for c, ch in zip(cols, M.CH_ORDER):
    s = status.get(ch, {"status": "not run"})
    rng = ""
    if s.get("date_min"):
        rng = f"{pd.Timestamp(s['date_min']).strftime('%d %b %y')} → {pd.Timestamp(s['date_max']).strftime('%d %b %y')}"
    icon = {"ok": "●", "partial": "◐", "stale": "◐", "failed": "✕", "not_connected": "○"}.get(s["status"], "○")
    c.markdown(f"<div class='src'><b>{M.CH_LABEL[ch]}</b><br><span class='{s['status']}'>{icon} {s['status'].replace('_', ' ')}</span>"
               f" · {s.get('count', 0)} items<br><span style='color:#94a3b8'>{rng}</span>"
               f"<br><span style='color:#94a3b8;font-size:11px'>{html.escape((s.get('reason') or '')[:140])}</span></div>",
               unsafe_allow_html=True)

# ---------------- KPIs ----------------
k = M.kpis(df)
st.write("")
kc = st.columns(6)
def kpi(col, label, val, sub=""):
    col.markdown(f"<div class='kpi'><div class='l'>{label}</div><div class='v'>{val}</div><div class='s'>{sub}</div></div>", unsafe_allow_html=True)
fmt = lambda x, suf="": "—" if x is None else f"{x:+.1f}{suf}" if suf in ("", " pts") else f"{x}{suf}"
kpi(kc[0], "Brand sentiment score", fmt(k["score"]), "mean(P(pos) − P(neg)) × 100, range −100…+100")
kpi(kc[1], "Net sentiment", fmt(k["net"], " pts"), "% positive − % negative")
kpi(kc[2], "Customer voice volume", f"{k['n']:,}", "reviews, comments & mentions")
kpi(kc[3], "Positive", "—" if k["pos"] is None else f"{k['pos']}%", "share of volume")
kpi(kc[4], "Negative", "—" if k["neg"] is None else f"{k['neg']}%", "share of volume")
kpi(kc[5], "Avg store rating", "—" if k["rating"] is None else f"{k['rating']}★", "Google Play + App Store")

tabs = st.tabs(["Overview", "Channels", "Themes", "What users ask for", "App stores", "Alerts", "Raw feed", "Sources & method"])

with tabs[0]:
    st.plotly_chart(M.fig_trend(df), width="stretch", key="chart1")
    a, b = st.columns(2)
    a.plotly_chart(M.fig_channel_split(df), width="stretch", key="chart2")
    b.plotly_chart(M.fig_theme_net(df), width="stretch", key="chart3")
    al = M.alerts(df)
    if al:
        st.markdown("#### 🚨 Alerts")
        for x in al[:6]:
            st.markdown(f"<div class='alert {x['level']}'><b>{x['scope']}</b> — {x['message']}</div>", unsafe_allow_html=True)

with tabs[1]:
    st.dataframe(M.channel_table(df, status), width="stretch", hide_index=True)
    st.plotly_chart(M.fig_channel_split(df), width="stretch", key="chart4")
    a, b = st.columns(2)
    show = ["date", "channel_label", "kind", "author", "text", "likes", "comments", "shares", "sentiment", "url"]
    with a:
        st.markdown("##### Top items by engagement")
        st.dataframe(M.top_items(df, "engagement")[show], width="stretch", hide_index=True,
                     column_config={"url": st.column_config.LinkColumn("link", display_text="open")})
    with b:
        st.markdown("##### Most negative items")
        st.dataframe(M.top_items(df, negative=True)[show], width="stretch", hide_index=True,
                     column_config={"url": st.column_config.LinkColumn("link", display_text="open")})

with tabs[2]:
    a, b = st.columns(2)
    a.plotly_chart(M.fig_theme_heatmap(df), width="stretch", key="chart5")
    b.plotly_chart(M.fig_theme_net(df), width="stretch", key="chart6")
    st.plotly_chart(M.fig_theme_trend(df), width="stretch", key="chart7")
    t = M.theme_stats(df)
    if not t.empty:
        st.dataframe(t.round(1), width="stretch", hide_index=True)

with tabs[3]:
    at = M.asks_table(df, n_quotes=3)
    if at.empty:
        st.info("No asks in the current filter.")
    for i, r in at.iterrows():
        with st.expander(f"#{i + 1}  {r.ask} — {r['count']} mentions · {r.negative_pct}% negative · {r.channels}", expanded=i < 3):
            for q in r.quotes:
                st.markdown(f"<div class='quote'>“{html.escape(q['es'])}”<br><span class='en'>EN: {html.escape(q['en'] or '—')}</span>"
                            f"<br><span style='font-size:11px;color:#64748b'>{q['channel']} · {q['date']} · <a href='{q['url']}' target='_blank'>source</a></span></div>",
                            unsafe_allow_html=True)

with tabs[4]:
    a, b = st.columns(2)
    a.plotly_chart(M.fig_rating_dist(df), width="stretch", key="chart8")
    b.plotly_chart(M.fig_version(df), width="stretch", key="chart9")
    a, b = st.columns([1, 2])
    with a:
        st.markdown("##### 1★ review themes (last 30 days of data)")
        st.dataframe(M.one_star_themes(df), width="stretch", hide_index=True)
    with b:
        st.markdown("##### Latest 1★ reviews")
        ones = df[df.rating == 1].sort_values("date", ascending=False).head(15)
        st.dataframe(ones[["date", "channel_label", "app_version", "theme", "text", "text_en", "url"]], width="stretch",
                     hide_index=True, column_config={"url": st.column_config.LinkColumn("link", display_text="open")})
    st.dataframe(M.version_table(df), width="stretch", hide_index=True)

with tabs[5]:
    al = M.alerts(df)
    if not al:
        st.success("No week-over-week spikes detected in the current filter.")
    for x in al:
        st.markdown(f"<div class='alert {x['level']}'><b>[{x['level'].upper()}] {x['scope']}</b> — {x['message']}</div>", unsafe_allow_html=True)
    st.caption("Rule: negatives in the latest week ≥5 and ≥1.5× the prior 4-week average, or net sentiment down >15 pts (≥10 items). The current, incomplete week is also checked.")

with tabs[6]:
    q = st.text_input("Search text (Spanish or English)")
    f = df.copy()
    if q:
        f = f[f.text.str.contains(q, case=False, na=False) | f.text_en.fillna("").str.contains(q, case=False)]
    f = f.sort_values("date", ascending=False)
    st.caption(f"{len(f):,} items")
    st.dataframe(f[["date", "channel_label", "kind", "author", "rating", "sentiment", "score", "theme", "text", "text_en", "url"]],
                 width="stretch", hide_index=True, height=600,
                 column_config={"url": st.column_config.LinkColumn("link", display_text="open"),
                                "score": st.column_config.NumberColumn(format="%.2f")})

with tabs[7]:
    st.markdown("#### Source status")
    st.dataframe(pd.DataFrame([{"Source": M.CH_LABEL.get(k_, k_), "Status": v.get("status"), "Items": v.get("count"),
                                "From": v.get("date_min"), "To": v.get("date_max"), "Apify cost (USD)": v.get("cost_usd"),
                                "Method": v.get("note"), "Reason / note": v.get("reason")} for k_, v in status.items()]),
                 width="stretch", hide_index=True)
    st.markdown("""
**Method**
- *Sentiment*: `cardiffnlp/twitter-xlm-roberta-base-sentiment` (multilingual, trained on tweets incl. Spanish). Score = P(positive) − P(negative). For store reviews where the text model says *neutral*, the star rating decides (≤2★ negative, ≥4★ positive).
- *Themes & asks*: keyword rules tuned for Panamanian Spanish (e.g. *recarga, yappy, señal, opciones de desarrollador*). An item can have several themes; the first match is its primary theme. An *ask* is counted when a pain-point pattern matches **and** the item is negative, ≤2★, or contains request language (*arreglen, deberían, por favor…*).
- *Translation*: `Helsinki-NLP/opus-mt-es-en` (machine translation, may be imperfect).
- Brand-owned posts are used for engagement only and excluded from sentiment.
""")

"""Más Móvil Panamá: customer sentiment dashboard (Streamlit).  streamlit run streamlit_app.py

Read-only at runtime: reads precomputed data/masmovil.db (items + item_insight), data/insights.json and data/status.json.
No ML models are loaded here; analysis runs in the weekly GitHub Actions refresh (`python refresh.py`).
Tap any row, card or chart point to open a side panel with the comments behind it."""
import json, sqlite3
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from mms import config as C
from mms import product as P
from mms import render as R
from mms import ui as U

st.set_page_config(page_title="Más Móvil · Customer sentiment", page_icon="📶", layout="wide")
st.markdown(f"<style>{R.CSS}{U.CSS}</style>", unsafe_allow_html=True)

INS = C.DATA / "insights.json"


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


@st.cache_data(show_spinner=False)
def load(mtime):
    return json.loads(INS.read_text()), U.load_voice(), U.load_status()


if not ready():
    st.markdown("<div class='mm-h1'>Dashboard</div>", unsafe_allow_html=True)
    st.info("⏳ Data is loading, first refresh pending. The GitHub Actions workflow *Refresh sentiment data* builds the data; "
            "this page shows the dashboard once it has run.")
    st.stop()

mt = INS.stat().st_mtime + C.DB_PATH.stat().st_mtime + (C.STATUS_PATH.stat().st_mtime if C.STATUS_PATH.exists() else 0)
ins, D, status = load(mt)
SUBLAB = {s["id"]: s["label"] for s in ins["subissues"]}
ss = st.session_state
ss.setdefault("chart_nonce", 0)

# ------------------------------------------------------------------ header + filters
today = pd.Timestamp.now(tz=U.TZ).tz_localize(None).normalize()
end_all = max(today, D.day.max())
PRESETS = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90, "All time": None, "Custom range": "custom"}


def preset_range(k):
    n = PRESETS[k]
    if n is None:
        return D.day.min(), end_all
    if n == "custom":
        return None
    return end_all - pd.Timedelta(days=n - 1), end_all


h1, h2, h3 = st.columns([4.4, 2.2, 1.5], vertical_alignment="bottom")
h1.markdown("<div class='mm'><div class='mm-h1'>Dashboard</div>"
            "<div class='mm-sub'>Tap any row or chart point to see the comments behind it.</div></div>", unsafe_allow_html=True)
preset = h2.selectbox("DATE RANGE", list(PRESETS), index=2, key="rng",
                      format_func=lambda k: f"{k} ({preset_range(k)[0]:%d %b} – {preset_range(k)[1]:%d %b})" if PRESETS[k] != "custom" else k)
chan_opts = ["All channels"] + [U.CH[c] for c in U.CH if c in set(D.channel)]
chan = h3.selectbox("CHANNELS", chan_opts, key="chan")
if PRESETS[preset] == "custom":
    _, cc = st.columns([5, 3.2])
    dr = cc.date_input("Custom range", (end_all.date() - pd.Timedelta(days=29), end_all.date()),
                       min_value=D.day.min().date(), max_value=end_all.date(), key="custom_rng")
    start, end = (pd.Timestamp(dr[0]), pd.Timestamp(dr[1])) if isinstance(dr, (list, tuple)) and len(dr) == 2 else preset_range("Last 30 days")
else:
    start, end = preset_range(preset)
RNG = U.rng(start, end)

DC = D if chan == "All channels" else D[D.channel_label == chan]
V = U.window(DC, start, end)
PV = U.prev_window(DC, start, end)

banner = U.sync_banner(status)
if banner:
    st.markdown(f"<div class='mm-banner'><b>{banner[0]}</b> {banner[1]}</div>", unsafe_allow_html=True)

COMP, COMP_TOT = U.complaints(V, PV)
ASKS = U.asks(V, PV)
RF = U.reply_first(V)


# ------------------------------------------------------------------ drawer (st.dialog docked right)
def _lm(key):
    ss[f"lm_{key}"] = ss.get(f"lm_{key}", 10) + 10


def _body(key, cat, title, df, intro=None, filt=None, order_reply=True):
    st.markdown(f"<div class='mm'><div class='dr-cat'>{U.e(cat)}</div><div class='mm-h1' style='font-size:22px'>{U.e(title)}</div></div>",
                unsafe_allow_html=True)
    if intro:
        intro()
    if filt:
        df = filt(df)
    if order_reply and len(df):
        df = df.assign(_o=df.needs_reply.astype(int)).sort_values(["_o", "ts"], ascending=[False, False])
    ppl = df.author.replace("", pd.NA).nunique()
    span = f" ({df.ts.min():%Y-%m-%d} to {df.ts.max():%Y-%m-%d})" if len(df) else ""
    st.markdown(f"<div class='dr-sub'>{len(df):,} mentions from {ppl:,} unique people{span}</div>", unsafe_allow_html=True)
    n = ss.get(f"lm_{key}", 10)
    st.markdown("".join(U.comment_card(r) for r in df.head(n).itertuples()) or
                "<div class='dr-sub'>No comments match.</div>", unsafe_allow_html=True)
    f1, f2 = st.columns([3, 1.2], vertical_alignment="center")
    f1.markdown(f"<div class='dr-foot'>{ppl:,} people · {len(df):,} comments · showing {min(n, len(df)):,}</div>", unsafe_allow_html=True)
    if n < len(df):
        f2.button("Load more", key=f"more_{key}", on_click=_lm, args=(key,), width="stretch")


def open_drawer(kind, param=None):
    key = f"{kind}:{param}"
    ss[f"lm_{key}"] = 10

    def body():
        if kind == "complaint":
            df = V[V.groups.apply(lambda L: param in L)]
            svc = param in U.NONAPP_ID

            def intro():
                subs = [s for s in ins["subissues"] if (s["id"] == U.NONAPP_ID[param] if svc else s["category"] == param)]
                if subs:
                    with st.expander("Sub-issues, quotes & AI recommendations (full 90-day analysis)"):
                        st.markdown(R.category({"subissues": subs}, subs[0]["category"]), unsafe_allow_html=True)

            def filt(x):
                if svc:
                    return x
                ids = sorted({s for L in x.subissues for s in L if s in SUBLAB}, key=lambda s: -sum(s in L for L in x.subissues))
                pick = st.selectbox("Sub-issue", ["All sub-issues"] + ids, key=f"si_{key}",
                                    format_func=lambda s: s if s == "All sub-issues" else f"{SUBLAB[s]} ({sum(s in L for L in x.subissues)})")
                return x if pick == "All sub-issues" else x[x.subissues.apply(lambda L: pick in L)]
            _body(key, "Service complaint" if svc else "Complaint", param, df, intro, filt)
        elif kind == "ask":
            df = V[V.asks.apply(lambda L: param in L)]
            _body(key, "What people are asking for", U.ASK_SHORT.get(param, param), df,
                  intro=lambda: st.caption(f"Matched request: {param}"))
        elif kind == "day":
            day, sent = param
            d0 = pd.Timestamp(day)
            d1 = d0 + pd.Timedelta(days=6 if FREQ != "D" else 0)
            df = V[(V.day >= d0) & (V.day <= d1)]

            def filt(x):
                pick = st.segmented_control("Sentiment", ["negative", "neutral", "positive", "all"], default=sent,
                                            key=f"sg_{key}", format_func=str.title) or "all"
                return x if pick == "all" else x[x.sentiment == pick]
            lab = f"{d0:%a %d %b %Y}" if FREQ == "D" else f"Week of {d0:%d %b %Y}"
            _body(key, "How customers feel", lab, df, filt=filt)
        elif kind == "reply":
            r0 = V[V.id == param]
            same = V[(V.author == r0.author.iloc[0]) & (V.id != param)] if len(r0) and r0.author.iloc[0] else V.iloc[0:0]
            _body(key, "Reply first", U.handle(r0.iloc[0]) if len(r0) else "Comment", pd.concat([r0, same]),
                  intro=lambda: st.caption("The comment to answer first, followed by this person's other comments in the range."),
                  order_reply=False)
        elif kind == "needs_reply":
            _body(key, "Needs reply now", "Comments to answer", RF, order_reply=False,
                  intro=lambda: st.caption("Unhappy comments that raise a complaint, a request or a 1–2★ rating, most urgent first "
                                           "(more negative, more recent, repeated)."))
        elif kind == "unhappy":
            _body(key, "Unhappy comments", "Negative comments", V[V.unhappy])
        elif kind == "score":
            def intro():
                g = V.groupby("channel_label").agg(n=("id", "size"), s=("score", "mean"), u=("unhappy", "mean")).sort_values("n", ascending=False)
                st.markdown("<div class='mm'>" + "".join(
                    f"<div class='sbar'><span class='l'>{U.e(c)}</span><span class='k'>{int(r.n):,} comments · {round(r.u * 100)}% unhappy</span>"
                    f"<b>{round((r.s + 1) * 50)}/100</b></div>" for c, r in g.iterrows()) + "</div>", unsafe_allow_html=True)
                st.caption("Score = average sentiment of every comment mapped to 0–100 (0 = all very negative, 50 = neutral, 100 = all very positive).")

            def filt(x):
                pick = st.segmented_control("Sentiment", ["all", "negative", "neutral", "positive"], default="all",
                                            key=f"sg_{key}", format_func=str.title) or "all"
                return x if pick == "all" else x[x.sentiment == pick]
            _body(key, "Overall score", "Score by channel", V, intro, filt, order_reply=False)

    st.dialog(" ", width="medium", position="right")(body)()


def clickable(key, html, kind, param=None):
    with st.container(key=f"row_{key}"):
        st.markdown(html, unsafe_allow_html=True)
        if st.button("Open", key=f"go_{key}"):
            open_drawer(kind, param)


def card_head(title, right=""):
    return f"<div class='card-h mm'><span class='t'>{U.e(title)}</span><span class='r'>{U.e(right)}</span></div>"


# ------------------------------------------------------------------ KPI cards
CMP = U.comparable(len(V), len(PV))
sc, psc = U.score100(V), (U.score100(PV) if CMP else None)
up, pup = U.unhappy_pct(V), (U.unhappy_pct(PV) if CMP else None)
k1, k2, k3, k4 = st.columns(4)
KP = [
    (k1, "score", U.kpi("♥", "Overall score", f"{sc if sc is not None else '–'}<small>/100</small>", U.delta(sc, psc, "", True))),
    (k2, "unhappy", U.kpi("▼", "Unhappy comments", f"{up if up is not None else '–'}%", U.delta(up, pup, " pts", False))),
    (k3, "needs_reply", U.kpi("!", "Needs reply now", f"{int(V.needs_reply.sum()):,}", f"{len(V):,} comments · {RNG}")),
    (k4, "ask", U.kpi("★", "Most requested", U.e(ASKS[0]["short"]) if ASKS else "–", f"in {RNG}", title_value=True)),
]
for col, kind, h in KP:
    with col:
        with st.container(key=f"kpi_{kind}"):
            st.markdown(h, unsafe_allow_html=True)
            if st.button("Open", key=f"go_kpi_{kind}"):
                if kind == "ask":
                    if ASKS:
                        open_drawer("ask", ASKS[0]["ask"])
                else:
                    open_drawer(kind)

# ------------------------------------------------------------------ trend + overview
TR, FREQ = U.trend(V, start, end)
c1, c2 = st.columns([2.2, 1])
with c1:
    with st.container(key="card_trend"):
        st.markdown(card_head("How customers feel", f"{RNG} · tap a point for details"), unsafe_allow_html=True)
        fig = go.Figure()
        for s in ["neutral", "positive", "negative"]:
            fig.add_scatter(x=TR.index, y=TR[s], name=s.title(), mode="lines+markers", line=dict(color=U.SENT_COL[s], width=2, shape="spline", smoothing=0.9),
                            marker=dict(size=6, color=U.SENT_COL[s], opacity=0.0), fill="tozeroy", fillcolor=U.SENT_FILL[s],
                            hovertemplate="%{x|%d %b %Y}<br>" + s.title() + ": %{y}<extra></extra>")
        fig.update_layout(height=372, margin=dict(l=0, r=6, t=6, b=0), paper_bgcolor="white", plot_bgcolor="white",
                          hovermode="closest", showlegend=True, clickmode="event+select", dragmode=False,
                          legend=dict(orientation="h", x=1, xanchor="right", y=1.1, font=dict(size=11, color="#6b7280")),
                          font=dict(family="Inter, sans-serif", color="#6b7280", size=11))
        fig.update_xaxes(showgrid=False, tickformat="%d %b", linecolor="#e5e7eb")
        fig.update_yaxes(gridcolor="#eef0f3", griddash="dash", zeroline=False, rangemode="tozero")
        ev = st.plotly_chart(fig, key=f"trend_{ss.chart_nonce}", on_select="rerun", selection_mode="points",
                             config={"displayModeBar": False}, width="stretch")
        pts = (ev or {}).get("selection", {}).get("points", []) if ev else []
        if pts:
            p = pts[0]
            sent = ["neutral", "positive", "negative"][p.get("curve_number", 2)]
            ss.chart_nonce += 1          # remount the chart next run so the selection doesn't re-open the panel
            open_drawer("day", (str(pd.Timestamp(p["x"]).date()), sent))
with c2:
    with st.container(key="card_overview"):
        upd = U.last_updated(status)
        st.markdown(card_head("Today's overview", "Today") +
                    f"<div class='ov mm'>{U.overview(V, PV, COMP, ASKS, RNG)}"
                    f"<div class='u'>Updated {upd:%d/%m/%Y, %H:%M} IST · refresh runs weekly, Mondays 6:00 AM IST</div></div>"
                    if upd is not None else card_head("Today's overview") + f"<div class='ov mm'>{U.overview(V, PV, COMP, ASKS, RNG)}</div>",
                    unsafe_allow_html=True)
        st.markdown("<div class='ov mm' style='margin-top:12px'>" + "".join(
            f"<div class='sbar'><span class='l'>{U.e(c)}</span><span class='k'>{n:,}</span></div>"
            for c, n in V.channel_label.value_counts().items()) + "</div>", unsafe_allow_html=True)

# ------------------------------------------------------------------ top complaints
with st.container(key="card_complaints"):
    st.markdown(card_head("Top complaints", RNG), unsafe_allow_html=True)
    if not COMP:
        st.caption("No classified complaints in this range.")
    for i, c in enumerate(COMP[:9]):
        pill, cls = ("Rising", "p-r") if c["rising"] else ("Many posts", "p-y") if c["n"] >= 20 else ("Some posts", "p-b") if c["n"] >= 5 else ("Few posts", "p-n")
        meta = f"{c['n']:,} comments · {c['pct']}% of complaints" + (" · service, not app" if c["service"] else "")
        clickable(f"c{i}", U.lrow(c["name"], meta, pill, cls), "complaint", c["name"])

# ------------------------------------------------------------------ asks + reply first
a1, a2 = st.columns([1.55, 1])
with a1:
    with st.container(key="card_asks"):
        st.markdown(card_head("What people are asking for", RNG), unsafe_allow_html=True)
        if not ASKS:
            st.caption("No requests in this range.")
        for i, a in enumerate(ASKS[:8]):
            clickable(f"a{i}", U.lrow(a["short"], f"{a['n']:,} comments · tap to read them", a["pill"],
                                      "p-g" if a["pill"] == "Popular" else "p-y"), "ask", a["ask"])
with a2:
    with st.container(key="card_reply"):
        st.markdown(card_head("Reply first", RNG), unsafe_allow_html=True)
        if RF.empty:
            st.caption("Nothing waiting for a reply in this range.")
        for i, r in enumerate(RF.head(6).itertuples()):
            t = (r.text or "").strip()
            clickable(f"r{i}", U.lrow(t[:160] + ("…" if len(t) > 160 else ""), f"{U.e(U.handle(r))} · {U.e(r.channel_label)} · {r.kind}",
                                      "Reply now", "p-y", quote=True), "reply", r.id)
        if len(RF) > 6:
            if st.button(f"See all {len(RF):,} comments to answer", key="all_reply", type="tertiary"):
                open_drawer("needs_reply")

# ------------------------------------------------------------------ product roadmap (previous deep-dives, kept)
cats = [c for c in ins["categories"] if c["category"] != P.NONAPP_CATEGORY]
with st.container(key="card_roadmap"):
    cov = ins["coverage"]
    st.markdown(card_head("Product roadmap", f"full analysis {cov['start']} – {cov['end']} · not affected by the filters above"),
                unsafe_allow_html=True)
    st.markdown(R.header(ins).replace("font-size:26px", "font-size:0;display:none"), unsafe_allow_html=True)
    with st.expander("Top user problems (app issues ranked by priority)"):
        st.markdown(R.problems(ins), unsafe_allow_html=True)
        fig = go.Figure(go.Bar(x=[c["n"] for c in cats][::-1], y=[c["category"] for c in cats][::-1], orientation="h",
                               marker_color="#3b6fe0", text=[c["n"] for c in cats][::-1], textposition="outside"))
        fig.update_layout(height=210, margin=dict(l=0, r=30, t=26, b=0), paper_bgcolor="white", plot_bgcolor="white",
                          title=dict(text="App complaints by product category (an item can sit in more than one)", font=dict(size=13, color="#374151"), x=0),
                          xaxis=dict(visible=False), yaxis=dict(tickfont=dict(size=12, color="#111827")), font=dict(color="#111827"))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key="catbar")
    with st.expander("What users want (explicit requests, with AI need statements)"):
        st.markdown(R.wants(ins), unsafe_allow_html=True)
    with st.expander("Product improvement opportunities (AI recommendations)"):
        st.markdown(R.opportunities(ins), unsafe_allow_html=True)
    st.markdown("<div class='mm-lbl' style='margin:14px 0 6px'>Category deep-dives</div>", unsafe_allow_html=True)
    for c in cats:
        with st.expander(f"{c['category']}: {c['n']} items · {c['pct']}% of app feedback"):
            st.markdown(R.category(ins, c["category"]), unsafe_allow_html=True)
    na = next(c for c in ins["categories"] if c["category"] == P.NONAPP_CATEGORY)
    with st.expander(f"Non-app / service issues: {na['n']} items ({na['pct']}% of all feedback)"):
        st.markdown(R.category(ins, P.NONAPP_CATEGORY), unsafe_allow_html=True)

# ------------------------------------------------------------------ all comments (searchable table, kept)
with st.container(key="card_table"):
    st.markdown(card_head("All comments", f"{RNG} · {chan}"), unsafe_allow_html=True)
    f1, f2, f3 = st.columns([2.2, 1.6, 2.2])
    groups = P.APP_CATEGORIES + list(U.NONAPP_ID)
    cat_sel = f1.multiselect("Category", groups, placeholder="All categories", key="t_cat")
    sent_sel = f2.multiselect("Sentiment", ["negative", "neutral", "positive"], placeholder="All", key="t_sent")
    q = f3.text_input("Search text", placeholder="e.g. tarjeta, día extra, código, Yappy", key="t_q")
    T = V
    if cat_sel:
        T = T[T.groups.apply(lambda L: any(c in L for c in cat_sel))]
    if sent_sel:
        T = T[T.sentiment.isin(sent_sel)]
    if q:
        T = T[T.text.str.contains(q, case=False, na=False, regex=False) | T.text_en.fillna("").str.contains(q, case=False, regex=False)]
    T = T.assign(Issue=(T.subissues + T.nonapp).apply(lambda L: "; ".join(SUBLAB.get(x, x) for x in L)))
    st.caption(f"{len(T):,} comments")
    st.dataframe(T[["ts", "channel_label", "rating", "author", "topic", "Issue", "text", "text_en", "sentiment", "url"]]
                 .rename(columns={"ts": "Date", "channel_label": "Channel", "rating": "★", "author": "Author", "topic": "Topic",
                                  "text": "Quote (original)", "text_en": "English (MT)", "sentiment": "Sentiment", "url": "Link"}),
                 width="stretch", hide_index=True, height=420,
                 column_config={"Link": st.column_config.LinkColumn("Link", display_text="open"),
                                "Date": st.column_config.DatetimeColumn(format="DD MMM YYYY")})

st.markdown(R.method(ins) + "<div class='mm small muted'>Comment times and day buckets are Panama time (UTC−5). "
            "Score = average sentiment mapped to 0–100. Previous period = the same number of days just before the selected range.</div>",
            unsafe_allow_html=True)

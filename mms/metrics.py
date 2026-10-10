"""Data loading, metrics and Plotly figures shared by the Streamlit app and the static snapshot."""
import json, sqlite3, datetime as dt
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from . import config as C

CH_LABEL = {"google_play": "Google Play", "app_store": "App Store", "facebook": "Facebook", "instagram": "Instagram",
            "tiktok": "TikTok", "x": "X / Twitter", "linkedin": "LinkedIn"}
CH_ORDER = list(CH_LABEL)
SENT_COL = {"positive": "#22c55e", "neutral": "#94a3b8", "negative": "#ef4444"}
BG, CARD, GRID, TXT, ACC = "#0b1220", "#111a2e", "#1f2a44", "#e2e8f0", "#38bdf8"


def style(fig, h=360, title=None):
    fig.update_layout(template="plotly_dark", paper_bgcolor=CARD, plot_bgcolor=CARD, height=h,
                      margin=dict(l=10, r=10, t=40 if title else 10, b=10), font=dict(color=TXT, size=12),
                      title=dict(text=title, x=0.01, font=dict(size=14)) if title else None,
                      legend=dict(orientation="h", y=-0.25))
    fig.update_xaxes(gridcolor=GRID); fig.update_yaxes(gridcolor=GRID)
    return fig


def load():
    con = sqlite3.connect(C.DB_PATH)
    df = pd.read_sql("SELECT * FROM items", con)
    con.close()
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    df["week"] = df["date"].dt.tz_convert(None).dt.to_period("W-SUN").dt.start_time
    df["themes"] = df["themes"].apply(json.loads)
    df["asks"] = df["asks"].apply(json.loads)
    df["channel_label"] = df["channel"].map(CH_LABEL)
    for c in ["likes", "comments", "shares", "views"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["engagement"] = df[["likes", "comments", "shares"]].fillna(0).sum(axis=1)
    return df


def load_status():
    try:
        return json.loads(C.STATUS_PATH.read_text())
    except Exception:
        return {}


def voice(df):
    """Customer voice = everything except the brand's own posts, with a sentiment."""
    return df[(df["kind"] != "owned_post") & df["sentiment"].notna()]


def kpis(df):
    v = voice(df)
    n = len(v)
    if not n:
        return dict(n=0, score=None, net=None, pos=None, neg=None, rating=None)
    pos = (v.sentiment == "positive").mean() * 100
    neg = (v.sentiment == "negative").mean() * 100
    r = df[df.rating.notna()].rating
    return dict(n=n, score=round(v.score.mean() * 100, 1), net=round(pos - neg, 1), pos=round(pos, 1),
                neg=round(neg, 1), rating=round(r.mean(), 2) if len(r) else None)


def weekly(df):
    v = voice(df)
    if v.empty:
        return pd.DataFrame()
    g = v.groupby(["week", "sentiment"]).size().unstack(fill_value=0)
    for s in SENT_COL:
        if s not in g:
            g[s] = 0
    g["total"] = g[list(SENT_COL)].sum(axis=1)
    g["net"] = (g.positive - g.negative) / g.total * 100
    g["score"] = v.groupby("week").score.mean() * 100
    return g.reset_index()


def fig_trend(df):
    g = weekly(df)
    fig = go.Figure()
    if g.empty:
        return style(fig, title="Weekly sentiment trend")
    for s in ["negative", "neutral", "positive"]:
        fig.add_bar(x=g.week, y=g[s], name=s.title(), marker_color=SENT_COL[s], opacity=0.85)
    net = g.net.where(g.total >= 10)  # hide net line for thin weeks
    fig.add_scatter(x=g.week, y=net, name="Net sentiment (%, weeks with ≥10 items)", yaxis="y2", mode="lines+markers",
                    line=dict(color=ACC, width=3))
    fig.update_layout(barmode="stack", yaxis=dict(title="Mentions / reviews"),
                      yaxis2=dict(title="Net sentiment %", overlaying="y", side="right", range=[-100, 100], dtick=50, showgrid=False, zeroline=True, zerolinecolor="#475569"))
    return style(fig, 380, "Weekly volume by sentiment & net sentiment (week starting Monday)")


def channel_table(df, status):
    rows = []
    for ch in CH_ORDER:
        st = status.get(ch, {})
        d = df[df.channel == ch]
        v = voice(d)
        n = len(v)
        rows.append({
            "Channel": CH_LABEL[ch], "Status": st.get("status", "not run"),
            "Items": len(d), "Customer voice": n,
            "Positive %": round((v.sentiment == "positive").mean() * 100, 1) if n else None,
            "Negative %": round((v.sentiment == "negative").mean() * 100, 1) if n else None,
            "Net sentiment": round(((v.sentiment == "positive").mean() - (v.sentiment == "negative").mean()) * 100, 1) if n else None,
            "Avg rating": round(d.rating.mean(), 2) if d.rating.notna().any() else None,
            "Likes": int(d.likes.fillna(0).sum()) if d.likes.notna().any() else None,
            "Comments/replies": int(d.comments.fillna(0).sum()) if d.comments.notna().any() else None,
            "Shares/RTs": int(d.shares.fillna(0).sum()) if d.shares.notna().any() else None,
        })
    return pd.DataFrame(rows)


def fig_channel_split(df):
    v = voice(df)
    if v.empty:
        return style(go.Figure(), title="Sentiment split by channel")
    g = v.groupby(["channel_label", "sentiment"]).size().unstack(fill_value=0)
    pct = g.div(g.sum(axis=1), axis=0) * 100
    fig = go.Figure()
    for s in ["negative", "neutral", "positive"]:
        if s in pct:
            fig.add_bar(y=pct.index, x=pct[s], name=s.title(), orientation="h", marker_color=SENT_COL[s],
                        text=[f"{x:.0f}%" for x in pct[s]], textposition="inside",
                        customdata=g[s], hovertemplate="%{y}: %{x:.1f}% (%{customdata})<extra>" + s + "</extra>")
    fig.update_layout(barmode="stack", xaxis=dict(range=[0, 100], title="% of channel volume"))
    return style(fig, 300, "Sentiment split by channel")


def theme_stats(df):
    v = voice(df).explode("themes")
    if v.empty:
        return pd.DataFrame()
    g = v.groupby(["themes", "sentiment"]).size().unstack(fill_value=0)
    for s in SENT_COL:
        if s not in g:
            g[s] = 0
    g["total"] = g[list(SENT_COL)].sum(axis=1)
    g["net"] = (g.positive - g.negative) / g.total * 100
    g["neg_share"] = g.negative / g.total * 100
    return g.sort_values("total", ascending=False).reset_index().rename(columns={"themes": "theme"})


def fig_theme_heatmap(df):
    t = theme_stats(df)
    if t.empty:
        return style(go.Figure(), title="Themes")
    z = t[["negative", "neutral", "positive"]].values
    fig = go.Figure(go.Heatmap(z=z, x=["Negative", "Neutral", "Positive"], y=t.theme, colorscale="Blues",
                               text=z, texttemplate="%{text}", showscale=False))
    fig.update_yaxes(autorange="reversed")
    return style(fig, 380, "Theme × sentiment (mentions; an item can carry several themes)")


def fig_theme_net(df):
    t = theme_stats(df)
    if t.empty:
        return style(go.Figure(), title="Net sentiment by theme")
    t = t.sort_values("net")
    fig = go.Figure(go.Bar(x=t.net, y=t.theme, orientation="h",
                           marker_color=["#ef4444" if x < 0 else "#22c55e" for x in t.net],
                           text=[f"{x:+.0f} (n={n})" for x, n in zip(t.net, t.total)], textposition="auto"))
    fig.update_layout(xaxis=dict(range=[-100, 100], title="Net sentiment % (pos − neg)"))
    return style(fig, 380, "Net sentiment by theme")


def fig_theme_trend(df):
    v = voice(df).explode("themes")
    v = v[v.sentiment == "negative"]
    if v.empty:
        return style(go.Figure(), title="Negative mentions by theme per week")
    g = v.groupby(["week", "themes"]).size().reset_index(name="n")
    fig = px.line(g, x="week", y="n", color="themes", markers=True)
    return style(fig, 360, "Negative mentions by theme per week")


def asks_table(df, n_quotes=2):
    v = voice(df)
    v = v[v.asks.str.len() > 0].explode("asks")
    if v.empty:
        return pd.DataFrame()
    out, used = [], set()
    order = v.asks.value_counts().index
    for ask in order:
        g = v[v.asks == ask]
        g = g.assign(qscore=g.text.str.len().clip(upper=300) + g.likes.fillna(0) * 20 +
                     (g.sentiment == "negative") * 200)
        g2 = g.sort_values(["qscore", "date"], ascending=False)
        quotes = []
        for _, r in g2[~g2.id.isin(used)].head(n_quotes).iterrows():
            used.add(r.id)
            quotes.append(dict(es=r.text[:280], en=(r.text_en or "")[:280], url=r.url, channel=r.channel_label,
                               date=r.date.strftime("%d %b %Y") if pd.notna(r.date) else ""))
        out.append(dict(ask=ask, count=len(g), negative_pct=round((g.sentiment == "negative").mean() * 100),
                        channels=", ".join(f"{k} {v}" for k, v in g.channel_label.value_counts().items()),
                        last_seen=g.date.max().strftime("%d %b %Y") if g.date.notna().any() else "", quotes=quotes))
    return pd.DataFrame(out).sort_values("count", ascending=False).reset_index(drop=True)


def fig_rating_dist(df):
    s = df[df.rating.notna()]
    if s.empty:
        return style(go.Figure(), title="Rating distribution")
    g = s.groupby(["channel_label", "rating"]).size().reset_index(name="n")
    g["pct"] = g.n / g.groupby("channel_label").n.transform("sum") * 100
    g["rating"] = g.rating.astype(int).astype(str) + "★"
    fig = px.bar(g, x="rating", y="pct", color="channel_label", barmode="group", text=g.n,
                 color_discrete_map={"Google Play": "#34d399", "App Store": "#60a5fa"})
    fig.update_layout(yaxis_title="% of reviews", xaxis_title="")
    return style(fig, 320, "Rating distribution (labels = review count)")


def version_table(df, min_n=5):
    s = df[df.rating.notna() & df.app_version.notna()]
    if s.empty:
        return pd.DataFrame()
    g = s.groupby(["channel_label", "app_version"]).agg(reviews=("rating", "size"), avg_rating=("rating", "mean"),
                                                         one_star_pct=("rating", lambda x: (x == 1).mean() * 100),
                                                         first_seen=("date", "min")).reset_index()
    g = g[g.reviews >= min_n].sort_values(["channel_label", "first_seen"])
    g["avg_rating"] = g.avg_rating.round(2); g["one_star_pct"] = g.one_star_pct.round(0)
    g["first_seen"] = g.first_seen.dt.strftime("%d %b %Y")
    return g


def fig_version(df):
    g = version_table(df)
    if g.empty:
        return style(go.Figure(), title="Avg rating by app version")
    fig = px.bar(g, x="app_version", y="avg_rating", color="channel_label", barmode="group", text="reviews",
                 color_discrete_map={"Google Play": "#34d399", "App Store": "#60a5fa"},
                 hover_data=["one_star_pct", "first_seen"])
    fig.update_layout(yaxis=dict(range=[0, 5], title="Avg rating"), xaxis=dict(type="category", title="App version"))
    return style(fig, 320, "Avg rating by app version (≥5 reviews; label = review count)")


def one_star_themes(df, days=30):
    s = df[(df.rating == 1)]
    if s.empty:
        return pd.DataFrame()
    end = s.date.max()
    s = s[s.date >= end - pd.Timedelta(days=days)].explode("themes")
    return s.groupby("themes").size().sort_values(ascending=False).reset_index(name="1★ reviews").rename(columns={"themes": "Theme"})


def alerts(df):
    """Week-over-week checks on the latest complete week vs the previous 4 weeks."""
    v = voice(df)
    out = []
    if v.empty:
        return out
    weeks = sorted(v.week.dropna().unique())
    if len(weeks) < 3:
        return out
    last_full = weeks[-2] if (pd.Timestamp.utcnow().tz_localize(None) - weeks[-1]).days < 7 else weeks[-1]
    cur_partial = weeks[-1] if last_full != weeks[-1] else None
    def check(sub, label, check_week):
        w = sub.groupby("week")
        neg = w.apply(lambda g: (g.sentiment == "negative").sum())
        tot = w.size()
        prev = [x for x in weeks if x < check_week][-4:]
        if check_week not in neg.index or not prev:
            return
        base = neg.reindex(prev).fillna(0).mean()
        cur = neg[check_week]
        base_net = ((sub[sub.week.isin(prev)].sentiment == "positive").mean() - (sub[sub.week.isin(prev)].sentiment == "negative").mean()) * 100
        cs = sub[sub.week == check_week]
        cur_net = ((cs.sentiment == "positive").mean() - (cs.sentiment == "negative").mean()) * 100
        wk = pd.Timestamp(check_week).strftime("%d %b")
        if cur >= 5 and cur >= 1.5 * max(base, 1):
            out.append(dict(level="high" if cur >= 2 * max(base, 1) else "medium", scope=label, week=wk,
                            message=f"Negatives {int(cur)} in week of {wk} vs {base:.1f}/week avg over prior {len(prev)} weeks (×{cur / max(base, 1):.1f})"))
        if tot.get(check_week, 0) >= 10 and pd.notna(base_net) and cur_net < base_net - 15:
            out.append(dict(level="medium", scope=label, week=wk,
                            message=f"Net sentiment {cur_net:+.0f} in week of {wk} vs {base_net:+.0f} in prior {len(prev)} weeks"))
    for wk in [w for w in [last_full, cur_partial] if w is not None]:
        check(v, "All channels", wk)
        for ch, sub in v.groupby("channel_label"):
            check(sub, ch, wk)
        ve = v.explode("themes")
        for th, sub in ve.groupby("themes"):
            check(sub, f"Theme: {th}", wk)
    return out


def top_items(df, by="engagement", n=10, negative=False):
    d = df[df.text.str.len() > 0].copy()
    if negative:
        d = d[d.sentiment == "negative"].sort_values(["score", "engagement"], ascending=[True, False])
    else:
        d = d.sort_values(by, ascending=False)
    return d.head(n)

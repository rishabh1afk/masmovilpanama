"""Export a self-contained static HTML snapshot of the dashboard (interactive Plotly charts).
python build_snapshot.py  ->  dashboard_snapshot.html"""
import html, json, datetime as dt
import pandas as pd
from mms import config as C
from mms import metrics as M

OUT = C.ROOT / "dashboard_snapshot.html"
e = lambda s: html.escape(str(s if s is not None and not (isinstance(s, float) and pd.isna(s)) else ""))


def main():
    df_all, status = M.load(), M.load_status()
    end = df_all.date.max()
    df = df_all[df_all.date >= end - pd.Timedelta(days=C.LOOKBACK_DAYS)]
    first = [True]

    def fig(f):
        s = f.to_html(full_html=False, include_plotlyjs=first[0], config={"displaylogo": False, "responsive": True})
        first[0] = False
        return f"<div class='card'>{s}</div>"

    def table(d, links=("url",)):
        if d is None or len(d) == 0:
            return "<p class='muted'>No data.</p>"
        hdr = "".join(f"<th>{e(c)}</th>" for c in d.columns)
        rows = []
        for _, r in d.iterrows():
            cells = []
            for c in d.columns:
                v = r[c]
                if c in links and isinstance(v, str) and v.startswith("http"):
                    cells.append(f"<td><a href='{e(v)}' target='_blank'>open</a></td>")
                elif isinstance(v, pd.Timestamp):
                    cells.append(f"<td>{v.strftime('%d %b %Y')}</td>")
                elif isinstance(v, float):
                    cells.append(f"<td>{'' if pd.isna(v) else f'{v:,.2f}'.rstrip('0').rstrip('.')}</td>")
                else:
                    cells.append(f"<td>{e(v)}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return f"<div class='tw'><table><thead><tr>{hdr}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"

    k = M.kpis(df)
    last = max((s.get("fetched_at") or "" for s in status.values()), default="")
    last_s = pd.Timestamp(last).tz_convert("Asia/Kolkata").strftime("%d %b %Y, %I:%M %p IST") if last else ""
    src = []
    for ch in M.CH_ORDER:
        s = status.get(ch, {"status": "not run"})
        rng = f"{pd.Timestamp(s['date_min']).strftime('%d %b %y')} → {pd.Timestamp(s['date_max']).strftime('%d %b %y')}" if s.get("date_min") else ""
        src.append(f"<div class='src'><b>{M.CH_LABEL[ch]}</b><br><span class='{s['status']}'>{s['status'].replace('_', ' ')}</span> · {s.get('count', 0)} items"
                   f"<br><span class='muted'>{rng}</span><br><span class='muted small'>{e((s.get('reason') or '')[:150])}</span></div>")
    def kpi(l, v, sub):
        return f"<div class='kpi'><div class='l'>{l}</div><div class='v'>{v}</div><div class='s'>{sub}</div></div>"
    kp = "".join([
        kpi("Brand sentiment score", f"{k['score']:+.1f}", "mean(P(pos) − P(neg)) × 100"),
        kpi("Net sentiment", f"{k['net']:+.1f} pts", "% positive − % negative"),
        kpi("Customer voice volume", f"{k['n']:,}", "reviews, comments & mentions"),
        kpi("Positive", f"{k['pos']}%", "share of volume"),
        kpi("Negative", f"{k['neg']}%", "share of volume"),
        kpi("Avg store rating", f"{k['rating']}★" if k["rating"] else "—", "Google Play + App Store")])
    al = M.alerts(df)
    al_html = "".join(f"<div class='alert {a['level']}'><b>[{a['level'].upper()}] {e(a['scope'])}</b> — {e(a['message'])}</div>" for a in al) or "<p class='muted'>No spikes detected.</p>"
    at = M.asks_table(df, n_quotes=2)
    asks_html = ""
    for i, r in at.iterrows():
        qs = "".join(f"<div class='quote'>“{e(q['es'])}”<br><span class='en'>EN: {e(q['en'] or '—')}</span><br>"
                     f"<span class='muted small'>{e(q['channel'])} · {e(q['date'])} · <a href='{e(q['url'])}' target='_blank'>source</a></span></div>" for q in r.quotes)
        asks_html += (f"<div class='ask'><div class='askh'><span class='rank'>#{i + 1}</span> {e(r.ask)} <span class='pill'>{r['count']} mentions</span>"
                      f"<span class='pill red'>{r.negative_pct}% negative</span><span class='muted small'> {e(r.channels)}</span></div>{qs}</div>")
    show = ["date", "channel_label", "kind", "author", "text", "likes", "shares", "sentiment", "url"]
    feed = df.sort_values("date", ascending=False)[["date", "channel_label", "rating", "sentiment", "theme", "text", "text_en", "url"]]
    feed_rows = [{"d": r.date.strftime("%Y-%m-%d") if pd.notna(r.date) else "", "c": r.channel_label, "r": "" if pd.isna(r.rating) else int(r.rating),
                  "s": r.sentiment or "", "t": r.theme, "x": r.text, "en": r.text_en or "", "u": r.url or ""} for r in feed.itertuples()]

    body = f"""
<header><div><h1>📶 Más Móvil Panamá — Brand Sentiment</h1>
<div class='muted'>Static snapshot · data refreshed {last_s} · window: last {C.LOOKBACK_DAYS} days of data ({(end - pd.Timedelta(days=C.LOOKBACK_DAYS)).strftime('%d %b')} – {end.strftime('%d %b %Y')})</div></div></header>
<div class='grid7'>{''.join(src)}</div>
<div class='grid6'>{kp}</div>
<h2>Overview</h2>{fig(M.fig_trend(df))}
<div class='grid2'>{fig(M.fig_channel_split(df))}{fig(M.fig_theme_net(df))}</div>
<h2>🚨 Alerts</h2>{al_html}
<h2>Channel performance</h2>{table(M.channel_table(df, status))}
<div class='grid2'><div><h3>Top items by engagement</h3>{table(M.top_items(df, 'engagement')[show])}</div>
<div><h3>Most negative items</h3>{table(M.top_items(df, negative=True)[show])}</div></div>
<h2>Themes</h2><div class='grid2'>{fig(M.fig_theme_heatmap(df))}{fig(M.fig_theme_trend(df))}</div>
<h2>What users are asking for</h2>{asks_html}
<h2>App stores</h2><div class='grid2'>{fig(M.fig_rating_dist(df))}{fig(M.fig_version(df))}</div>
<div class='grid2'><div><h3>1★ review themes (last 30 days)</h3>{table(M.one_star_themes(df))}</div>
<div><h3>Rating by app version</h3>{table(M.version_table(df))}</div></div>
<h2>Raw feed</h2><input id='q' placeholder='Search Spanish or English text…' oninput='render()'> <span id='cnt' class='muted'></span>
<div class='tw' style='max-height:600px'><table id='feed'><thead><tr><th>Date</th><th>Channel</th><th>★</th><th>Sentiment</th><th>Theme</th><th>Text</th><th>English</th><th></th></tr></thead><tbody></tbody></table></div>
<p class='muted small'>Sentiment: cardiffnlp/twitter-xlm-roberta-base-sentiment (neutral store reviews fall back to stars). Themes/asks: Panamanian-Spanish keyword rules. Translation: Helsinki-NLP/opus-mt-es-en. Brand-owned posts excluded from sentiment.</p>
<script>
const FEED={json.dumps(feed_rows, ensure_ascii=False).replace('</', '<\\/')};
function esc(s){{return String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]))}}
function render(){{const q=document.getElementById('q').value.toLowerCase();
const rows=FEED.filter(r=>!q||r.x.toLowerCase().includes(q)||r.en.toLowerCase().includes(q));
document.getElementById('cnt').textContent=rows.length+' items';
document.querySelector('#feed tbody').innerHTML=rows.slice(0,500).map(r=>`<tr><td>${{r.d}}</td><td>${{r.c}}</td><td>${{r.r}}</td><td class="${{r.s}}">${{r.s}}</td><td>${{esc(r.t)}}</td><td>${{esc(r.x)}}</td><td class="muted">${{esc(r.en)}}</td><td>${{r.u?`<a href="${{esc(r.u)}}" target="_blank">open</a>`:''}}</td></tr>`).join('');}}
render();
</script>"""
    css = """
body{background:#0b1220;color:#e2e8f0;font-family:Inter,Segoe UI,Roboto,Arial,sans-serif;margin:0;padding:22px 30px}
h1{margin:0 0 4px;font-size:26px}h2{margin:26px 0 10px;font-size:19px;border-bottom:1px solid #1f2a44;padding-bottom:6px}h3{font-size:14px;color:#cbd5e1}
a{color:#38bdf8}.muted{color:#94a3b8}.small{font-size:11px}
.grid7{display:grid;grid-template-columns:repeat(7,1fr);gap:10px;margin:16px 0}.grid6{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.src,.kpi,.card{background:#111a2e;border:1px solid #1f2a44;border-radius:12px;padding:10px 12px}.src{font-size:12.5px}
.card{padding:6px;margin-bottom:12px}
.kpi .l{color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:.06em}.kpi .v{font-size:28px;font-weight:700}.kpi .s{color:#94a3b8;font-size:11px}
.ok,.positive{color:#22c55e}.partial,.stale{color:#f59e0b}.failed,.negative{color:#ef4444}.not_connected,.neutral{color:#94a3b8}
.alert{border-left:4px solid #ef4444;background:#1a1420;padding:8px 12px;margin:6px 0;border-radius:6px}.alert.medium{border-color:#f59e0b}
.tw{overflow:auto;max-height:420px;border:1px solid #1f2a44;border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:12px}th{position:sticky;top:0;background:#16223b;text-align:left;padding:6px}
td{padding:5px 6px;border-top:1px solid #1f2a44;vertical-align:top;max-width:520px}
.ask{background:#111a2e;border:1px solid #1f2a44;border-radius:10px;padding:10px 14px;margin:8px 0}.askh{font-weight:600}
.rank{color:#38bdf8;margin-right:6px}.pill{background:#1e3a5f;border-radius:20px;padding:2px 8px;margin-left:8px;font-size:11px}.pill.red{background:#4c1d1d}
.quote{border-left:3px solid #38bdf8;padding:4px 10px;margin:6px 0;color:#cbd5e1;font-size:13px}.quote .en{color:#94a3b8;font-style:italic}
input#q{background:#111a2e;border:1px solid #1f2a44;color:#e2e8f0;padding:8px;border-radius:8px;width:360px;margin-bottom:8px}"""
    OUT.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>Más Móvil · Brand Sentiment snapshot</title><style>{css}</style></head><body>{body}</body></html>", encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()

"""Static, self-contained HTML snapshot of the roadmap dashboard (same structure, white).
python build_snapshot.py  ->  dashboard_snapshot.html"""
import json, sqlite3, html
import pandas as pd
import plotly.graph_objects as go
from mms import config as C
from mms import product as P
from mms import render as R

OUT = C.ROOT / "dashboard_snapshot.html"


def main():
    ins = json.loads((C.DATA / "insights.json").read_text())
    try:
        status = json.loads(C.STATUS_PATH.read_text())
        last = max((s.get("fetched_at") or "" for s in status.values()), default="")
        refreshed = pd.Timestamp(last).tz_convert("Asia/Kolkata").strftime("%d %b %Y, %I:%M %p IST") if last else None
    except Exception:
        refreshed = None
    cats = [c for c in ins["categories"] if c["category"] != P.NONAPP_CATEGORY]
    fig = go.Figure(go.Bar(x=[c["n"] for c in cats][::-1], y=[c["category"] for c in cats][::-1], orientation="h",
                           marker_color=R.ACC, text=[c["n"] for c in cats][::-1], textposition="outside"))
    fig.update_layout(height=210, margin=dict(l=0, r=30, t=26, b=0), paper_bgcolor="white", plot_bgcolor="white",
                      title=dict(text="App complaints by product category (an item can sit in more than one)", font=dict(size=13, color="#374151"), x=0),
                      xaxis=dict(visible=False), font=dict(color="#111827"))
    bar = fig.to_html(full_html=False, include_plotlyjs=True, config={"displayModeBar": False})
    deep = "".join(f"<details><summary>{html.escape(c['category'])}: {c['n']} items · {c['pct']}% of app feedback</summary>{R.category(ins, c['category'])}</details>" for c in cats)
    na = next(c for c in ins["categories"] if c["category"] == P.NONAPP_CATEGORY)
    nonapp = (f"<div class='mm'><h2>Non-app / service issues</h2><div class='sub'>Secondary: network, pricing and customer service. {na['n']} items "
              f"({na['pct']}% of all feedback), mostly from social and X.</div></div><details><summary>Show non-app issues</summary>{R.category(ins, P.NONAPP_CATEGORY)}</details>")
    con = sqlite3.connect(C.DB_PATH)
    df = pd.read_sql("""SELECT i.channel, i.date, i.text, i.text_en, i.rating, i.sentiment, i.url, ii.subissues, ii.categories, ii.nonapp
                        FROM items i JOIN item_insight ii ON i.id = ii.id""", con)
    LAB = {s["id"]: s["label"] for s in ins["subissues"]}
    CHL = {"google_play": "Google Play", "app_store": "App Store", "facebook": "Facebook", "instagram": "Instagram", "tiktok": "TikTok", "x": "X"}
    rows = []
    for r in df.sort_values("date", ascending=False).itertuples():
        cs = json.loads(r.categories) + ([P.NONAPP_CATEGORY] if json.loads(r.nonapp) else [])
        if not cs:
            continue
        rows.append(dict(d=r.date[:10], c=CHL[r.channel], cat=cs, s=r.sentiment or "", r="" if pd.isna(r.rating) else int(r.rating),
                         i="; ".join(LAB.get(x, x) for x in json.loads(r.subissues) + json.loads(r.nonapp)), x=r.text, en=r.text_en or "", u=r.url or ""))
    opts = "".join(f"<option>{html.escape(c)}</option>" for c in P.APP_CATEGORIES + [P.NONAPP_CATEGORY])
    chopts = "".join(f"<option>{c}</option>" for c in sorted({r['c'] for r in rows}))
    reviews = f"""<div class='mm'><h2>Supporting reviews</h2><div class='sub'>Every classified item, searchable.</div>
<div class='flt'><select id='fc'><option value=''>All categories</option>{opts}</select><select id='fch'><option value=''>All channels</option>{chopts}</select>
<select id='fs'><option value=''>All sentiment</option><option>negative</option><option>neutral</option><option>positive</option></select>
<input id='q' placeholder='Search text…'> <span id='cnt' class='muted small'></span></div>
<div style='max-height:520px;overflow:auto;border:1px solid #e5e7eb;border-radius:8px'><table id='rv'><thead><tr><th>Date</th><th>Channel</th><th>★</th><th>Issue</th><th>Quote (original)</th><th>English (MT)</th><th>Sentiment</th><th></th></tr></thead><tbody></tbody></table></div></div>
<script>
const RV={json.dumps(rows, ensure_ascii=False).replace('</', '<\\/')};
const E=s=>String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
function draw(){{const c=fc.value,ch=fch.value,s=fs.value,q=document.getElementById('q').value.toLowerCase();
const f=RV.filter(r=>(!c||r.cat.includes(c))&&(!ch||r.c==ch)&&(!s||r.s==s)&&(!q||r.x.toLowerCase().includes(q)||r.en.toLowerCase().includes(q)));
cnt.textContent=f.length+' items';
document.querySelector('#rv tbody').innerHTML=f.slice(0,600).map(r=>`<tr><td style="white-space:nowrap">${{r.d}}</td><td>${{r.c}}</td><td>${{r.r}}</td><td class="small">${{E(r.i)}}</td><td>${{E(r.x)}}</td><td class="muted">${{E(r.en)}}</td><td>${{r.s}}</td><td>${{r.u?`<a href="${{E(r.u)}}" target="_blank">open</a>`:''}}</td></tr>`).join('');}}
['fc','fch','fs','q'].forEach(id=>document.getElementById(id).addEventListener('input',draw));draw();
</script>"""
    css = R.CSS + """body{background:#fff;margin:0;padding:28px 40px;max-width:1280px;margin:auto}
details{border:1px solid #e5e7eb;border-radius:10px;padding:10px 14px;margin:8px 0;font-family:Inter,Segoe UI,Arial,sans-serif}
summary{cursor:pointer;font-weight:600;font-size:14px;color:#111827}
.flt select,.flt input{border:1px solid #d1d5db;border-radius:6px;padding:6px 8px;margin:0 6px 10px 0;font-size:13px;background:#fff}"""
    body = (R.header(ins, refreshed) + R.problems(ins) + f"<div style='margin-top:14px'>{bar}</div>" + R.wants(ins) + R.opportunities(ins)
            + "<div class='mm'><h2>Category deep-dives</h2><div class='sub'>Clustered sub-issues with verbatim quotes and AI-generated recommendations.</div></div>"
            + deep + nonapp + reviews + R.method(ins))
    OUT.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>Más Móvil · Feedback → Roadmap</title><style>{css}</style></head><body>{body}</body></html>", encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()

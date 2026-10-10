"""HTML fragments shared by the Streamlit app and the static snapshot (white, minimal)."""
import html, json, datetime as dt
from . import product as P

ACC = "#0F5FD7"
CSS = f"""
.mm{{font-family:Inter,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#111827}}
.mm h2{{font-size:19px;font-weight:650;margin:30px 0 4px;color:#111827}}
.mm .sub{{color:#6b7280;font-size:13px;margin:0 0 12px}}
.mm .cov{{color:#374151;font-size:13.5px;line-height:1.6}}
.mm .cov b{{color:#111827}}
.mm .grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}}
.mm .card{{border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;background:#fff}}
.mm .card .t{{font-size:13.5px;font-weight:600;line-height:1.35;min-height:36px}}
.mm .card .n{{font-size:24px;font-weight:700;margin-top:6px}}
.mm .card .m{{font-size:12px;color:#6b7280}}
.mm .badge{{display:inline-block;font-size:11px;font-weight:600;border-radius:999px;padding:1px 8px;margin-left:6px;vertical-align:middle}}
.mm .High{{background:#fde8e8;color:#b42318}} .mm .Medium{{background:#fef3c7;color:#92400e}} .mm .Low{{background:#f3f4f6;color:#4b5563}}
.mm table{{border-collapse:collapse;width:100%;font-size:13px}}
.mm th{{text-align:left;font-weight:600;color:#374151;border-bottom:2px solid #e5e7eb;padding:8px 8px;background:#fafafa}}
.mm td{{border-bottom:1px solid #f0f0f0;padding:8px 8px;vertical-align:top}}
.mm .ai{{color:#1e3a8a}}
.mm .ailabel{{font-size:10.5px;font-weight:600;color:{ACC};text-transform:uppercase;letter-spacing:.04em}}
.mm a{{color:{ACC};text-decoration:none}}
.mm .q{{border-left:3px solid #d1d5db;padding:4px 10px;margin:6px 0;font-size:13px;color:#111827}}
.mm .q .en{{color:#6b7280;font-style:italic}}
.mm .q .meta{{color:#9ca3af;font-size:11.5px}}
.mm .want{{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #f0f0f0}}
.mm .want .r{{color:{ACC};font-weight:700;width:22px}}
.mm .want .b{{flex:1}}
.mm .rec{{background:#f5f8ff;border:1px solid #dbe6ff;border-radius:8px;padding:8px 12px;margin:8px 0 4px;font-size:13px}}
.mm .si{{border-top:1px solid #f0f0f0;padding:12px 0}}
.mm .si .h{{font-weight:600;font-size:14px}}
.mm .muted{{color:#6b7280}} .mm .small{{font-size:12px}}
"""

e = lambda s: html.escape("" if s is None else str(s))


def _ch(chans):
    return ", ".join(f"{k} {v}" for k, v in chans.items())


def subs_by(ins, app=True):
    S = [s for s in ins["subissues"] if (s["category"] != P.NONAPP_CATEGORY) == app]
    return sorted(S, key=lambda s: (-s["priority_score"], -s["n"]))


def header(ins, refreshed=None):
    c = ins["coverage"]
    d0 = dt.date.fromisoformat(c["start"]).strftime("%d %b %Y"); d1 = dt.date.fromisoformat(c["end"]).strftime("%d %b %Y")
    ch = " · ".join(f"{k} {v:,}" for k, v in sorted(c["channels"].items(), key=lambda x: -x[1]))
    r = f" · refreshed {e(refreshed)}" if refreshed else ""
    return (f"<div class='mm'><div style='font-size:26px;font-weight:700'>Más Móvil Panamá: user feedback → product roadmap</div>"
            f"<div class='cov'><b>{c['n_items']:,}</b> customer items ({d0} – {d1}) · {ch}<br>"
            f"<b>{c['n_app']:,}</b> are about the app · <b>{c['n_app_issue']:,}</b> app complaints or requests classified into product issues · "
            f"<b>{c['n_nonapp']:,}</b> non-app service complaints{r}</div></div>")


def problems(ins, k=8):
    cards = []
    for s in subs_by(ins)[:k]:
        cards.append(f"<div class='card'><div class='t'>{e(s['label'])}</div>"
                     f"<div class='n'>{s['n']}<span class='badge {s['priority']}'>{s['priority']}</span></div>"
                     f"<div class='m'>{s['pct_complaints']}% of app complaints · {s['pct']}% of app feedback<br>{e(s['category'])}</div></div>")
    return ("<div class='mm'><h2>Top user problems</h2><div class='sub'>App issues ranked by priority (mentions × severity). "
            "Counts are real items.</div><div class='grid'>" + "".join(cards) + "</div></div>")


def wants(ins, k=8):
    S = [s for s in subs_by(ins) if s["n_requests"] > 0 or s["request_quotes"]]
    S = sorted(S, key=lambda s: (-(3 * s["n_requests"] + s["n"]), -s["n"]))[:k]
    rows = []
    for i, s in enumerate(S, 1):
        q = (s["request_quotes"] or s["quotes"])[:1]
        qh = "".join(f"<div class='q'>“{e(x['es'])}”<br><span class='en'>{e(x['en'])}</span><br>"
                     f"<span class='meta'>{e(x['channel'])} · {e(x['date'])} · <a href='{e(x['url'])}' target='_blank'>source</a></span></div>" for x in q)
        rows.append(f"<div class='want'><div class='r'>{i}</div><div class='b'><b>{e(s['user_need'] or s['label'])}</b> "
                    f"<span class='muted small'>· {s['n_requests']} explicit requests · {s['n']} related complaints</span>{qh}</div></div>")
    return ("<div class='mm'><h2>What users want</h2><div class='sub'>Ranked by explicit requests (weighted ×3) plus related complaints "
            "(explicit = <i>arreglen, deberían, me gustaría, por favor…</i>). Bold need statements are AI summaries; quotes are verbatim.</div>"
            + "".join(rows) + "</div>")


def opportunities(ins):
    rows = []
    for s in subs_by(ins):
        if s["n"] < 2:
            continue
        ev = f"<a href='{e(s['evidence_url'])}' target='_blank'>quote ↗</a>" if s["evidence_url"] else ""
        rows.append(f"<tr><td><b>{e(s['label'])}</b><div class='muted small'>{e(s['category'])}</div></td>"
                    f"<td class='ai'>{e(s['user_need'] or '—')}</td><td class='ai'>{e(s['product_change'] or '—')}</td>"
                    f"<td style='white-space:nowrap'><b>{s['n']}</b> · {s['pct_complaints']}%</td><td class='small'>{e(_ch(s['channels']))}</td>"
                    f"<td><span class='badge {s['priority']}' style='margin:0'>{s['priority']}</span></td>"
                    f"<td>{ev}</td></tr>")
    return ("<div class='mm'><h2>Product improvement opportunities</h2>"
            "<div class='sub'>User complaint, mentions and channels come from real items. "
            "<span class='ailabel'>Recommendation (AI-generated)</span>: the blue columns are interpretations to validate. "
            "Mentions % = share of the app complaints classified into product issues.</div>"
            "<table><thead><tr><th>User complaint</th><th>What users need <span class='ailabel'>AI</span></th>"
            "<th>Potential product change <span class='ailabel'>AI</span></th><th>Mentions (n, %)</th><th>Channels</th><th>Priority</th><th>Evidence</th></tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table></div>")


def _quotes(qs):
    return "".join(f"<div class='q'>“{e(x['es'])}”<br><span class='en'>EN: {e(x['en'] or '—')}</span><br>"
                   f"<span class='meta'>{e(x['channel'])} · {e(x['date'])}{' · ' + str(int(x['rating'])) + '★' if x.get('rating') else ''}"
                   f" · <a href='{e(x['url'])}' target='_blank'>source</a></span></div>" for x in qs)


def category(ins, cat):
    S = [s for s in ins["subissues"] if s["category"] == cat]
    S = sorted(S, key=lambda s: (-s["priority_score"], -s["n"]))
    out = []
    for s in S:
        asks = f"<div class='small muted' style='margin-top:6px'>What users explicitly ask ({s['n_requests']}):</div>{_quotes(s['request_quotes'])}" if s["request_quotes"] else ""
        out.append(f"<div class='si'><div class='h'>{e(s['label'])}<span class='badge {s['priority']}'>{s['priority']}</span></div>"
                   f"<div class='small muted'>{s['n']} mentions · {s['pct']}% of {e(s['pct_base'])} · {e(_ch(s['channels']))} · "
                   f"{s['n_negative']} negative · seen {e(s['first_seen'])} → {e(s['last_seen'])}"
                   f"{' · ' + str(s['n_embedding']) + ' matched by embeddings' if s['n_embedding'] else ''}</div>"
                   f"{_quotes(s['quotes'])}{asks}"
                   f"<div class='rec'><span class='ailabel'>Recommendation (AI-generated)</span><br>{e(s['product_change'] or '—')}</div></div>")
    return "<div class='mm'>" + "".join(out) + "</div>"


def method(ins):
    m = ins["method"]
    return (f"<div class='mm small muted' style='margin-top:24px'><b>Method.</b> {e(m['rules'])}. Embeddings: {e(m['embeddings'])}. "
            f"Priority: {e(m['priority'])}. Recommendations: {e(m['recommendations'])}. Praise that only mentions a feature is not counted as a complaint. "
            f"Translations are machine-generated (opus-mt-es-en).</div>")

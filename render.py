"""Dựng trang báo cáo HTML từ output/analysis.json và output/news.json (do agent viết).

Ghi ra docs/index.html (bản mới nhất) và docs/archive/<ngày>.html (lưu trữ) để GitHub Pages phục vụ.
"""
import glob
import html
import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
VERDICT_CLASS = {"Tích cực": "pos", "Tiêu cực": "neg", "Thận trọng": "neg", "Trung lập": "neu", "Không có lợi thế thống kê": "none"}
SIG_TEXT = {1: "tăng", -1: "giảm", 0: "trung tính"}


def e(x):
    return html.escape(str(x)) if x is not None else ""


def pct(x, sign=True):
    if x is None:
        return "–"
    return f"{x * 100:+.1f}%" if sign else f"{x * 100:.0f}%"


def num(x, d=2):
    return "–" if x is None else f"{x:,.{d}f}"


def links(text):
    return e(text)


def asset_card(key, a, commentary):
    import analyze
    rows = []
    for label, hz in a["horizons"].items():
        st, wf, lv = hz["stats"], hz["walk_forward"], hz.get("live", {})
        wf_txt = "–"
        if wf:
            wf_txt = (f"{pct(wf['model_hit'], False)} vs {pct(wf['naive_hit'], False)}" if wf["model_hit"] is not None
                      else f"không dùng (nền {pct(wf['naive_hit'], False)})")
        live_txt = f"{lv['n']} lần, đúng {pct(lv.get('hit_rate'), False)}" if lv.get("n") else "chưa có"
        rows.append(f"""<tr>
<td><b>{e(label)}</b></td>
<td><span class="tag {VERDICT_CLASS.get(hz['verdict'], 'none')}">{e(hz['verdict'])}</span></td>
<td>{pct(hz['prob_up_final'], False)} <span class="muted">(nền {pct(st['base_prob_up'], False)})</span></td>
<td>{pct(st['median'])}</td>
<td>{pct(st['p10'])} → {pct(st['p90'])}</td>
<td>{pct(st['avg_max_drawdown'])} <span class="muted">/ tệ nhất {pct(st['worst_drawdown'])}</span></td>
<td>{wf_txt}</td>
<td>{live_txt}</td></tr>""")
        if hz.get("verdict_note"):
            rows.append(f'<tr class="note"><td></td><td colspan="7">{e(hz["verdict_note"])}</td></tr>')
    used = sorted({analyze.SIGNAL_NAMES[k] for hz in a["horizons"].values() for k, v in hz["weights"].items() if v})
    sigs = " · ".join(f"{analyze.SIGNAL_NAMES[k]}: <b>{SIG_TEXT[v]}</b>" for k, v in a["signals_today"].items())
    comm = commentary.get(key)
    comm_html = f'<div class="comm"><h4>Nhận định từ tin tức</h4><p>{links(comm)}</p></div>' if comm else ""
    return f"""<section class="card" id="{e(key)}">
<div class="head"><div><h2>{e(a['name'])}</h2>
<div class="muted">Phiên {e(a['last_date'])} · nguồn {e(a['source'])} · {a['n_days']:,} phiên từ {e(a['first_date'])}</div></div>
<div class="price"><b>{num(a['close'])}</b><span class="{'up' if a['change_1d'] >= 0 else 'down'}">{pct(a['change_1d'])}</span></div></div>
<canvas id="c_{e(key)}" height="90"></canvas>
<div class="grid">
<div><span class="muted">RSI14</span><b>{num(a['rsi'], 1)}</b></div>
<div><span class="muted">MA20 / MA50 / MA200</span><b>{num(a['sma20'])} / {num(a['sma50'])} / {num(a['sma200'])}</b></div>
<div><span class="muted">Hỗ trợ / kháng cự 20 phiên</span><b>{num(a['support_20'])} / {num(a['resist_20'])}</b></div>
<div><span class="muted">Đáy / đỉnh 52 tuần</span><b>{num(a['low_52w'])} / {num(a['high_52w'])}</b></div>
<div><span class="muted">Biến động 20 phiên</span><b>{pct(a['change_20d'])}</b></div>
<div><span class="muted">Mức cắt lỗ tham khảo (giá − 2×ATR)</span><b>{num(list(a['horizons'].values())[0]['stop_ref'])}</b></div>
</div>
<p class="sigs">{sigs}</p>
<div class="tw"><table>
<thead><tr><th>Kỳ hạn</th><th>Tín hiệu</th><th>Xác suất tăng</th><th>Trung vị</th><th>Khoảng 10%–90%</th><th>Sụt tối đa TB</th><th>Kiểm định 250 phiên</th><th>Thực tế</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p class="muted small">Chỉ báo có ý nghĩa thống kê hôm nay: {e(', '.join(used)) if used else 'không có'}.</p>
{comm_html}
</section>"""


def reco_section(an, news):
    st = an.get("stances", {})
    if not st:
        return ""
    best = an.get("best_pick")
    notes = news.get("stance_notes", {})
    if best:
        head = f"Mã có lợi thế thống kê tốt nhất hôm nay: <b>{e(st[best]['name'])}</b>"
    else:
        head = ("Hôm nay <b>không có mã nào đủ điều kiện Tích cực</b>. Phương án khớp nhất với dữ liệu: "
                "chưa mở vị thế mới dựa trên tín hiệu kỹ thuật, tiếp tục theo dõi.")
    order = sorted(st, key=lambda k: (-st[k]["sign"], -st[k]["edge"]))
    cards = []
    for k in order:
        s = st[k]
        lv = s.get("live") or {}
        track = (f"Quan điểm này đã chấm {lv['n']} lần, đúng {pct(lv.get('hit_rate'), False)}" if lv.get("n")
                 else "Chưa có lịch sử chấm điểm")
        note = notes.get(k)
        cards.append(f"""<div class="reco">
<div class="rh"><b>{e(s['name'])}</b><span class="tag {VERDICT_CLASS.get(s['view'], 'none')}">{e(s['view'])}</span></div>
<div class="muted small">Kỳ hạn {e(s['horizon'])} · Tin cậy: {e(s['confidence'])} · {track}</div>
<p><b>Hành động gợi ý chung:</b> {e(s['action'])}</p>
<ul class="small">{''.join(f'<li>{e(r)}</li>' for r in s['reasons'])}</ul>
{f'<p class="small"><b>Tin tức cần lưu ý:</b> {e(note)}</p>' if note else ''}
<p class="small muted"><b>Điều kiện đổi quan điểm:</b> {e(s['change_if'])}</p></div>""")
    return f"""<section class="card"><h2>Khuyến nghị hôm nay</h2>
<p class="big">{head}</p>
{f'<p>{e(news["recommendation"])}</p>' if news.get("recommendation") else ''}
<div class="recos">{''.join(cards)}</div>
<p class="muted small">Quan điểm do quy tắc cố định sinh ra: chỉ tín hiệu đã qua kiểm định mới được chuyển sang Tích cực hoặc Thận trọng; tin tức chỉ được nêu để theo dõi, không được đổi quan điểm. Đây là nhận định chung cho mọi nhà đầu tư, không tính đến vốn, mục tiêu hay khả năng chịu rủi ro của riêng bạn.</p></section>"""


def build(an, news):
    commentary = news.get("commentary", {})
    order = [k for k in ["GOLD_VND", "GOLD_USD", "VNINDEX"] if k in an["assets"]] + \
            [k for k in an["assets"] if k not in ("GOLD_VND", "GOLD_USD", "VNINDEX")]
    cards = "".join(asset_card(k, an["assets"][k], commentary) for k in order)
    charts = {k: an["assets"][k]["chart"] for k in order}

    sjc = an.get("sjc")
    sjc_html = ""
    if sjc:
        sjc_html = f"""<section class="card"><h2>Vàng miếng SJC</h2>
<div class="grid">
<div><span class="muted">Mua vào / bán ra</span><b>{num(sjc['buy'])} / {num(sjc['sell'])} tr/lượng</b></div>
<div><span class="muted">Vàng thế giới quy đổi</span><b>{num(sjc.get('world_equiv'))} tr/lượng</b></div>
<div><span class="muted">SJC đắt hơn thế giới</span><b>{num(sjc.get('premium'))} tr ({pct(sjc.get('premium_pct'))})</b></div>
<div><span class="muted">Chênh mua–bán</span><b>{num(sjc['sell'] - sjc['buy'])} tr ({pct((sjc['sell'] - sjc['buy']) / sjc['sell'], False)})</b></div>
</div>
<p class="muted small">Nguồn {e(sjc['source'])}, cập nhật {e(sjc['updated'])}. Tỷ giá USD/VND {num(an.get('fx', {}).get('usdvnd'), 0)}.
Đã lưu {sjc['history_days']} ngày lịch sử giá SJC. Mua vàng miếng hôm nay rồi bán lại ngay sẽ lỗ khoảng {pct((sjc['sell'] - sjc['buy']) / sjc['sell'], False)} do chênh mua–bán. Nếu chênh lệch với thế giới thu hẹp, giá SJC có thể giảm ngay cả khi vàng thế giới đứng yên.</p></section>"""

    items = "".join(
        f"<li><a href=\"{e(n.get('url'))}\" target=\"_blank\" rel=\"noopener\">{e(n.get('title'))}</a> "
        f"<span class=\"muted\">({e(n.get('source'))}, {e(n.get('date'))})</span>"
        f"{'<br><span class=small>' + e(n.get('impact')) + '</span>' if n.get('impact') else ''}</li>"
        for n in news.get("items", []))
    summary = news.get("summary", "")
    errors = "".join(f"<li>{e(x)}</li>" for x in an.get("errors", []) + news.get("errors", []))

    archive = sorted(glob.glob(os.path.join(ROOT, "docs", "archive", "*.html")), reverse=True)[:30]
    arch_links = " · ".join(f'<a href="archive/{os.path.basename(p)}">{os.path.basename(p)[:-5]}</a>' for p in archive)

    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bản tin đầu tư</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{{--bg:#f6f5f1;--card:#fff;--fg:#1d1d1b;--muted:#6b6a65;--line:#e4e2dc;--pos:#1f7a4d;--neg:#b3362b;--neu:#8a6d1a;--acc:#2c5f8a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161615;--card:#1f1f1d;--fg:#ecebe6;--muted:#a09f99;--line:#34332f;--pos:#5cc08b;--neg:#ef7a6e;--neu:#d8b75a;--acc:#7fb2dd}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:24px 16px 60px}}h1{{font-size:26px;margin:0 0 4px}}h2{{font-size:19px;margin:0}}h4{{margin:0 0 4px;font-size:14px}}
.muted{{color:var(--muted)}}.small{{font-size:13px}}a{{color:var(--acc)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin:16px 0}}
.head{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-start}}
.price{{text-align:right}}.price b{{font-size:22px;display:block}}.up{{color:var(--pos)}}.down{{color:var(--neg)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:12px 0}}
.grid div{{border-left:3px solid var(--line);padding-left:10px}}.grid span{{display:block;font-size:12px}}
.tw{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13.5px;min-width:760px}}
th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}}th{{font-weight:600;color:var(--muted);font-size:12px}}
tr.note td{{font-size:12.5px;color:var(--neu);border-bottom:1px solid var(--line)}}
.tag{{padding:2px 8px;border-radius:99px;font-size:12px;font-weight:600;white-space:nowrap;border:1px solid currentColor}}
.tag.pos{{color:var(--pos)}}.tag.neg{{color:var(--neg)}}.tag.neu{{color:var(--neu)}}.tag.none{{color:var(--muted)}}
.sigs{{font-size:13px;color:var(--muted)}}.comm{{margin-top:12px;padding:12px;background:var(--bg);border-radius:8px}}.comm p{{margin:0}}
.warn{{border-left:4px solid var(--neu)}}.big{{font-size:17px}}
.recos{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}.reco{{border:1px solid var(--line);border-radius:10px;padding:12px}}
.rh{{display:flex;justify-content:space-between;align-items:center;gap:8px}}.reco p{{margin:8px 0}}.reco ul{{margin:6px 0}}ul{{padding-left:20px}}li{{margin:6px 0}}
</style></head><body><main>
<h1>Bản tin đầu tư</h1>
<div class="muted">Tạo lúc {e(an['generated_at'])}</div>

<section class="card warn"><b>Đọc trước:</b> Đây là phân tích thống kê tự động, không phải lời khuyên đầu tư cá nhân.
"Xác suất tăng" là tỷ lệ các lần trong lịch sử có trạng thái chỉ báo tương tự hôm nay mà giá cao hơn sau kỳ hạn. Đây không phải dự báo chắc chắn.
"Nền" là tỷ lệ tăng chung của mọi ngày trong lịch sử. Tín hiệu chỉ có ý nghĩa khi khác rõ so với nền và qua được kiểm định 250 phiên gần nhất.</section>

{reco_section(an, news)}
<section class="card"><h2>Tóm tắt hôm nay</h2><p>{e(summary) or '<span class="muted">Chưa có phần tổng hợp tin tức.</span>'}</p></section>
{sjc_html}
{cards}
<section class="card"><h2>Tin tức đã tổng hợp</h2><ul>{items or '<li class="muted">Không có</li>'}</ul></section>
{'<section class="card warn"><h2>Lỗi dữ liệu</h2><ul>' + errors + '</ul></section>' if errors else ''}
<section class="card small"><h2>Phương pháp</h2>
<p>Giá lấy từ VNDirect/VPS (cổ phiếu, VN-Index), Yahoo Finance (vàng GC=F, USD/VND), PNJ (vàng miếng SJC). Mỗi sáng hệ thống tính lại 7 chỉ báo và đo tương quan của từng chỉ báo với lợi suất tương lai trên toàn bộ lịch sử. Chỉ báo nào không đạt |t| ≥ 2 (sau khi đã tính đến việc các quan sát chồng lấn nhau) thì có trọng số 0. "Kiểm định 250 phiên" dùng trọng số huấn luyện trên dữ liệu cũ, rồi so tỷ lệ đoán đúng hướng trên 250 phiên gần nhất với cách đoán đơn giản theo tỷ lệ nền. "Thực tế" là nhật ký chấm điểm các dự báo mà hệ thống đã phát hành. Khi thực tế kém hơn tỷ lệ nền, xác suất tự được kéo về gần nền.</p>
<p>Lưu trữ: {arch_links or 'chưa có'}</p></section>
</main>
<script>
const CH={json.dumps(charts)};
const css=getComputedStyle(document.documentElement);
for(const [k,c] of Object.entries(CH)){{
 const el=document.getElementById('c_'+k); if(!el||!window.Chart) continue;
 new Chart(el,{{type:'line',data:{{labels:c.dates,datasets:[
  {{label:'Giá',data:c.close,borderColor:css.getPropertyValue('--fg'),borderWidth:1.6,pointRadius:0}},
  {{label:'MA50',data:c.sma50,borderColor:css.getPropertyValue('--acc'),borderWidth:1.2,pointRadius:0}},
  {{label:'MA200',data:c.sma200,borderColor:css.getPropertyValue('--neu'),borderWidth:1.2,pointRadius:0,borderDash:[4,3]}}]}},
  options:{{interaction:{{mode:'index',intersect:false}},plugins:{{legend:{{labels:{{boxWidth:12,color:css.getPropertyValue('--muted')}}}}}},
  scales:{{x:{{ticks:{{maxTicksLimit:6,color:css.getPropertyValue('--muted')}},grid:{{display:false}}}},y:{{ticks:{{color:css.getPropertyValue('--muted')}},grid:{{color:css.getPropertyValue('--line')}}}}}}}}}});
}}
</script></body></html>"""


def main():
    an = json.load(open(os.path.join(ROOT, "output", "analysis.json"), encoding="utf-8"))
    news_path = os.path.join(ROOT, "output", "news.json")
    news = json.load(open(news_path, encoding="utf-8")) if os.path.exists(news_path) else {}
    page = build(an, news)
    day = an["generated_at"][:10]
    os.makedirs(os.path.join(ROOT, "docs", "archive"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "archive", f"{day}.html"), "w", encoding="utf-8") as f:
        f.write(page.replace('href="archive/', 'href="'))
    page = build(an, news)  # dựng lại để danh sách lưu trữ có cả ngày hôm nay
    with open(os.path.join(ROOT, "docs", "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    print("Đã ghi docs/index.html và docs/archive/" + day + ".html")


if __name__ == "__main__":
    main()

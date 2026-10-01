/* Giả lập đầu tư cổ phiếu VN — lưu ở data/paper.json trên GitHub.
 * Quy tắc mô phỏng theo HOSE: lô 100, bước giá, biên độ trần/sàn, phí 0,15%/chiều, thuế bán 0,1%, T+2,
 * lệnh thị trường chỉ trong giờ giao dịch, lệnh giới hạn khớp khi giá chạm và hết hiệu lực cuối phiên.
 */
(() => {
"use strict";
const A = window.APP;
const { $, ic, esc, nf, pct, gh, token, say } = A;
const PATH = "data/paper.json";
const FEE_BUY = 0.0015, FEE_SELL = 0.0015, TAX_SELL = 0.001, LOT = 100;
const P = { state: null, loaded: false, quotes: {}, side: "buy", type: "limit", charts: [], busy: false, lastMatch: 0, navKey: "" };

// ---------- thời gian & quy tắc sàn ----------
const vnParts = (d = new Date()) => { const v = new Date(d.getTime() + 7 * 3600e3); return { date: v.toISOString().slice(0, 10), min: v.getUTCHours() * 60 + v.getUTCMinutes(), day: v.getUTCDay() }; };
const isTradingDay = ds => { const d = new Date(ds + "T00:00:00Z").getUTCDay(); return d >= 1 && d <= 5; };
function nextTradingDay(ds) { let d = new Date(ds + "T00:00:00Z"); do { d = new Date(d.getTime() + 86400e3); } while (!isTradingDay(d.toISOString().slice(0, 10))); return d.toISOString().slice(0, 10); }
function tradingDaysAfter(a, b) { let n = 0, d = a; while (d < b) { d = nextTradingDay(d); if (d <= b) n++; } return n; }
function sessionOpen() { const { day, min } = vnParts(); return day >= 1 && day <= 5 && ((min >= 540 && min <= 690) || (min >= 780 && min <= 885)); }
const tickOf = p => p < 10000 ? 10 : p < 50000 ? 50 : 100;
const vnd = x => x == null || isNaN(x) ? "–" : Math.round(x).toLocaleString("vi-VN");
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
const today = () => vnParts().date;

// ---------- đọc / ghi GitHub ----------
async function load() {
  try {
    if (token()) {
      const j = await (await gh(`/contents/${PATH}?ref=main`)).json();
      P.state = JSON.parse(A.b64dec(j.content));
    } else {
      const r = await fetch(`https://raw.githubusercontent.com/${A.OWNER}/${A.REPO}/main/${PATH}?t=${Date.now()}`, { cache: "no-store" });
      P.state = r.ok ? await r.json() : null;
    }
  } catch (e) { if (/404/.test(e.message)) P.state = null; else throw e; }
  P.loaded = true;
}
async function mutate(fn, msg) {
  if (!token()) throw new Error("Cần token GitHub (nút cài đặt) để lưu giao dịch giả lập.");
  for (let k = 0; k < 3; k++) {
    let sha = null, st = null;
    try { const j = await (await gh(`/contents/${PATH}?ref=main`)).json(); sha = j.sha; st = JSON.parse(A.b64dec(j.content)); }
    catch (e) { if (!/404/.test(e.message)) throw e; }
    const next = fn(st ? structuredClone(st) : null);
    if (!next) return st;
    const body = { message: msg, content: A.b64enc(JSON.stringify(next, null, 1) + "\n"), branch: "main" };
    if (sha) body.sha = sha;
    try { await gh(`/contents/${PATH}`, { method: "PUT", body: JSON.stringify(body) }); P.state = next; return next; }
    catch (e) { if (/409|422/.test(e.message) && k < 2) continue; throw e; }
  }
}

// ---------- giá ----------
const g = s => { const v = parseFloat(String(s || "").split("|")[0]); return isFinite(v) && v > 0 ? v * 1000 : null; };
async function fetchQuotes(syms) {
  syms = [...new Set(syms.filter(Boolean))]; if (!syms.length) return;
  try {
    const arr = await A.getJSON(`https://bgapidatafeed.vps.com.vn/getliststockdata/${syms.join(",")}`);
    for (const d of arr) P.quotes[d.sym] = {
      last: +d.lastPrice ? +d.lastPrice * 1000 : null, ref: +d.r * 1000, ceil: +d.c * 1000, floor: +d.f * 1000,
      bid: g(d.g1), ask: g(d.g4), at: new Date() };
  } catch {}
}
const markPrice = s => { const q = P.quotes[s]; return q ? (q.last || q.ref) : null; };

// ---------- sổ cái ----------
function ledger(st) {
  const pos = {}, closed = []; let cash = st.initial_cash, fees = 0, taxes = 0, realized = 0, deposits = st.initial_cash;
  const ev = [...(st.cash_flows || []).map(c => ({ t: c.time, c })), ...st.orders.filter(o => o.status === "filled").map(o => ({ t: o.fill_time, o }))]
    .sort((a, b) => a.t < b.t ? -1 : 1);
  for (const e of ev) {
    if (e.c) { cash += e.c.amount; deposits += e.c.amount; continue; }
    const o = e.o, val = o.fill_price * o.qty, p = pos[o.sym] ||= { qty: 0, cost: 0, lots: [] };
    if (o.side === "buy") {
      const fee = val * FEE_BUY; cash -= val + fee; fees += fee;
      p.qty += o.qty; p.cost += val + fee; p.lots.push({ qty: o.qty, date: o.fill_date });
    } else {
      const fee = val * FEE_SELL, tax = val * TAX_SELL, avg = p.cost / p.qty, pl = val - fee - tax - avg * o.qty;
      cash += val - fee - tax; fees += fee; taxes += tax; realized += pl;
      closed.push({ sym: o.sym, pl, ret: pl / (avg * o.qty), date: o.fill_date });
      p.cost -= avg * o.qty; p.qty -= o.qty;
      let q = o.qty; while (q > 0 && p.lots.length) { const l = p.lots[0], t = Math.min(q, l.qty); l.qty -= t; q -= t; if (!l.qty) p.lots.shift(); }
    }
  }
  const pending = st.orders.filter(o => o.status === "pending");
  const reserved = pending.filter(o => o.side === "buy").reduce((s, o) => s + o.limit * o.qty * (1 + FEE_BUY), 0);
  const d = today();
  for (const [s, p] of Object.entries(pos)) {
    p.sellable = p.lots.filter(l => tradingDaysAfter(l.date, d) >= 2).reduce((a, l) => a + l.qty, 0)
      - pending.filter(o => o.side === "sell" && o.sym === s).reduce((a, o) => a + o.qty, 0);
    p.avg = p.qty ? p.cost / p.qty : 0;
    p.price = markPrice(s) ?? p.lastClose ?? p.avg;
    p.value = p.qty * p.price;
    p.upl = p.value - p.cost;
    if (!p.qty) delete pos[s];
  }
  const stock = Object.values(pos).reduce((a, p) => a + p.value, 0);
  const upl = Object.values(pos).reduce((a, p) => a + p.upl, 0);
  return { pos, cash, reserved, avail: cash - reserved, stock, nav: cash + stock, fees, taxes, realized, upl, deposits, closed, pending };
}

// ---------- khớp lệnh chờ ----------
async function bars1m(sym, fromTs) {
  const to = Math.floor(Date.now() / 1000);
  const j = await A.getJSON(`https://dchart-api.vndirect.com.vn/dchart/history?symbol=${sym}&resolution=1&from=${fromTs - 60}&to=${to}`);
  return (j.t || []).map((t, i) => ({ t, o: j.o[i] * 1000, h: j.h[i] * 1000, l: j.l[i] * 1000, date: vnParts(new Date(t * 1000)).date }));
}
function fillOrder(o, price, when) {
  o.status = "filled"; o.fill_price = price; o.fill_time = when.toISOString(); o.fill_date = vnParts(when).date;
}
async function matchPending(force) {
  if (!P.state || P.busy || !token()) return;
  const pend = P.state.orders.filter(o => o.status === "pending");
  if (!pend.length) return;
  if (!force && Date.now() - P.lastMatch < 20000) return;
  P.lastMatch = Date.now();
  const updates = {};
  const d = today(), { min } = vnParts();
  for (const o of pend) {
    try {
      const bars = (await bars1m(o.sym, Math.floor(new Date(o.time).getTime() / 1000)))
        .filter(b => b.t * 1000 >= new Date(o.time).getTime() - 60e3 && b.date >= o.vn_date && b.date <= o.valid_date && isTradingDay(b.date));
      const hit = bars.find(b => o.side === "buy" ? b.l <= o.limit : b.h >= o.limit);
      if (hit) { updates[o.id] = { k: "fill", price: o.side === "buy" ? Math.min(o.limit, hit.o) : Math.max(o.limit, hit.o), when: new Date(Math.max(hit.t * 1000, new Date(o.time).getTime())) }; continue; }
      const q = P.quotes[o.sym];
      if (sessionOpen() && d === o.valid_date && q) {
        if (o.side === "buy" && q.ask && q.ask <= o.limit) { updates[o.id] = { k: "fill", price: q.ask, when: new Date() }; continue; }
        if (o.side === "sell" && q.bid && q.bid >= o.limit) { updates[o.id] = { k: "fill", price: q.bid, when: new Date() }; continue; }
      }
      if (d > o.valid_date || (d === o.valid_date && min >= 885)) updates[o.id] = { k: "expire" };
    } catch {}
  }
  if (!Object.keys(updates).length) return;
  P.busy = true;
  try {
    await mutate(st => {
      let changed = false;
      for (const o of st.orders) {
        const u = updates[o.id]; if (!u || o.status !== "pending") continue;
        if (u.k === "fill") fillOrder(o, u.price, u.when); else { o.status = "expired"; o.reason = "Hết hiệu lực cuối phiên, chưa khớp"; }
        changed = true;
      }
      return changed ? st : null;
    }, "Giả lập: khớp/huỷ lệnh chờ");
  } catch (e) { flash(e.message, "bad"); }
  P.busy = false;
  render();
}

// ---------- đặt lệnh ----------
async function placeOrder() {
  const sym = $("ptSym").value.trim().toUpperCase(), qty = +$("ptQty").value, side = P.side, type = P.type;
  const q = P.quotes[sym];
  if (!/^[A-Z0-9]{3,10}$/.test(sym) || !q) return flash("Mã không hợp lệ hoặc chưa lấy được giá.", "bad");
  if (!(qty > 0) || qty % LOT) return flash(`Khối lượng phải là bội số của ${LOT}.`, "bad");
  const open = sessionOpen();
  let price;
  if (type === "market") {
    if (!open) return flash("Ngoài giờ giao dịch (9:00–11:30, 13:00–14:45): chỉ đặt được lệnh giới hạn.", "bad");
    price = side === "buy" ? (q.ask || q.last || q.ref) : (q.bid || q.last || q.ref);
  } else {
    price = Math.round(+$("ptPrice").value * 1000);
    if (!(price > 0)) return flash("Nhập giá đặt.", "bad");
    if (price % tickOf(price)) return flash(`Giá phải theo bước ${vnd(tickOf(price))}đ.`, "bad");
    if (price > q.ceil || price < q.floor) return flash(`Giá phải trong khoảng sàn ${vnd(q.floor)} – trần ${vnd(q.ceil)}.`, "bad");
  }
  const L = ledger(P.state);
  if (side === "buy" && price * qty * (1 + FEE_BUY) > L.avail + 1) return flash(`Không đủ tiền: cần ${vnd(price * qty * (1 + FEE_BUY))}đ, khả dụng ${vnd(L.avail)}đ.`, "bad");
  if (side === "sell" && qty > (L.pos[sym]?.sellable || 0)) return flash(`Chỉ bán được tối đa ${nf(L.pos[sym]?.sellable || 0, 0)} cổ phiếu ${sym} (T+2, trừ lệnh đang chờ).`, "bad");
  const marketable = open && (type === "market" || (side === "buy" ? q.ask && price >= q.ask : q.bid && price <= q.bid));
  const fillPx = type === "market" ? price : side === "buy" ? q.ask : q.bid;
  const label = `${side === "buy" ? "MUA" : "BÁN"} ${nf(qty, 0)} ${sym} ${type === "market" ? "giá thị trường (~" + vnd(price) + "đ)" : "giá " + vnd(price) + "đ"}`;
  if (!confirm(`Xác nhận đặt lệnh giả lập:\n${label}\n\nGiá trị ≈ ${vnd(price * qty)}đ`)) return;
  const { date, min } = vnParts();
  const o = { id: uid(), time: new Date().toISOString(), vn_date: date, side, sym, qty, type, limit: type === "limit" ? price : null,
    valid_date: (open || (isTradingDay(date) && min < 540)) ? date : nextTradingDay(date), status: "pending" };
  if (marketable) fillOrder(o, fillPx, new Date());
  $("ptSubmit").disabled = true;
  try {
    await mutate(st => { if (!st) throw new Error("Chưa có tài khoản giả lập."); st.orders.push(o); return st; }, `Giả lập: ${label}`);
    flash(o.status === "filled" ? `✓ Đã khớp ${label.replace(/giá.*$/, "")} giá ${vnd(o.fill_price)}đ` : `✓ Đã đặt lệnh chờ khớp (hiệu lực đến hết phiên ${o.valid_date.split("-").reverse().join("/")})`, "ok");
  } catch (e) { flash("Đặt lệnh thất bại: " + e.message, "bad"); }
  $("ptSubmit").disabled = false;
  render();
}
async function cancelOrder(id) {
  if (!confirm("Huỷ lệnh này?")) return;
  try { await mutate(st => { const o = st.orders.find(x => x.id === id && x.status === "pending"); if (!o) return null; o.status = "cancelled"; return st; }, "Giả lập: huỷ lệnh"); }
  catch (e) { flash(e.message, "bad"); }
  render();
}
const flash = (t, k) => say("ptMsg", t, k);
const fmtTime = iso => { const v = new Date(new Date(iso).getTime() + 7 * 3600e3).toISOString(); return v.slice(8, 10) + "/" + v.slice(5, 7) + " " + v.slice(11, 16); };

// ---------- hiệu quả theo ngày ----------
async function navSeries(st) {
  const traded = [...new Set(st.orders.filter(o => o.status === "filled").map(o => o.sym))];
  const start = (st.created || new Date().toISOString()).slice(0, 10);
  const key = traded.join(",") + "|" + st.orders.filter(o => o.status === "filled").length + "|" + (st.cash_flows || []).length + "|" + start;
  if (P.navKey === key && P.nav) return P.nav;
  const from = Math.floor(new Date(start + "T00:00:00Z").getTime() / 1000) - 10 * 86400, to = Math.floor(Date.now() / 1000);
  const closes = {};
  await Promise.all(["VNINDEX", ...traded].map(async s => {
    try { const j = await A.getJSON(`https://dchart-api.vndirect.com.vn/dchart/history?symbol=${s}&resolution=D&from=${from}&to=${to}`);
      closes[s] = new Map(j.t.map((t, i) => [vnParts(new Date(t * 1000)).date, j.c[i] * (s === "VNINDEX" ? 1 : 1000)])); } catch { closes[s] = new Map(); }
  }));
  const days = [...closes.VNINDEX.keys()].filter(d => d >= start).sort();
  if (!days.includes(today()) && isTradingDay(today())) days.push(today());
  const filled = st.orders.filter(o => o.status === "filled").sort((a, b) => a.fill_time < b.fill_time ? -1 : 1);
  const lastC = {};
  const out = days.map(d => {
    for (const s of traded) { const c = closes[s].get(d); if (c) lastC[s] = c; }
    const sub = { ...st, orders: filled.filter(o => o.fill_date <= d), cash_flows: (st.cash_flows || []).filter(c => c.time.slice(0, 10) <= d) };
    let cash = sub.initial_cash; const qty = {};
    for (const c of sub.cash_flows) cash += c.amount;
    for (const o of sub.orders) { const v = o.fill_price * o.qty;
      if (o.side === "buy") { cash -= v * (1 + FEE_BUY); qty[o.sym] = (qty[o.sym] || 0) + o.qty; }
      else { cash += v * (1 - FEE_SELL - TAX_SELL); qty[o.sym] -= o.qty; } }
    const px = s => d === today() ? (markPrice(s) ?? lastC[s]) : lastC[s];
    const stock = Object.entries(qty).reduce((a, [s, q]) => a + q * (px(s) || 0), 0);
    const flows = sub.cash_flows.reduce((a, c) => a + c.amount, sub.initial_cash);
    return { d, nav: cash + stock, flows, vni: closes.VNINDEX.get(d) ?? null };
  });
  P.navKey = key; P.nav = out;
  return out;
}

// ---------- vẽ ----------
function kpi(lab, val, sub, icon, tone, cls = "") {
  return `<div class="kpi"><div class="kic t-${tone}">${ic(icon)}</div><div class="lab">${esc(lab)}</div><div class="val ${cls}">${val}</div><div class="sub">${sub}</div></div>`;
}
const plc = x => x > 0 ? "up" : x < 0 ? "down" : "";
const sgn = x => (x > 0 ? "+" : "") + vnd(x);

function renderSetup() {
  $("ppBody").innerHTML = `<div class="panel pp-setup">${ic("coins", "lg")}<div>
    <h4>Tạo tài khoản giả lập</h4>
    <p class="muted small">Tiền ảo, giao dịch theo giá thị trường thật. Dữ liệu lưu ở <code>data/paper.json</code> trên GitHub (repo công khai nên người khác có thể xem).</p>
    <label class="fl" for="ppInit">Vốn ban đầu (đồng)</label>
    <div class="addrow"><input class="in" id="ppInit" inputmode="numeric" value="100.000.000"><button class="b2 primary" id="ppCreate">${ic("check", "sm")} Tạo tài khoản</button></div>
    ${token() ? "" : `<p class="msg show info">Cần token GitHub (nút cài đặt ở đầu trang) để tạo và lưu tài khoản.</p>`}
    <div class="msg" id="ptMsg"></div></div></div>`;
  $("ppCreate").onclick = async () => {
    const v = +$("ppInit").value.replace(/\D/g, "");
    if (!(v >= 1e6)) return flash("Vốn tối thiểu 1.000.000đ.", "bad");
    try { await mutate(() => ({ version: 1, created: new Date().toISOString(), initial_cash: v, cash_flows: [], orders: [] }), "Giả lập: tạo tài khoản"); render(); }
    catch (e) { flash(e.message, "bad"); }
  };
}

function render() {
  if (!$("viewPaper") || $("viewPaper").hidden) return;
  if (!P.loaded) { $("ppBody").innerHTML = `<div class="skeleton"></div>`; return; }
  $("ppMain").hidden = !P.state;
  if (!P.state) return renderSetup();
  if ($("ppBody").firstChild) $("ppBody").innerHTML = "";
  const st = P.state, L = ledger(st), ret = L.nav / L.deposits - 1;
  $("ppKpis").innerHTML = [
    kpi("Tổng tài sản", `${vnd(L.nav)}<span class="unit">đ</span>`, `<span class="${plc(ret)}">${pct(ret, true, 2)}</span> so với vốn ${vnd(L.deposits)}đ`, "landmark", "idx"),
    kpi("Tiền mặt khả dụng", `${vnd(L.avail)}<span class="unit">đ</span>`, L.reserved ? `Tạm giữ cho lệnh chờ ${vnd(L.reserved)}đ` : "Không có tiền tạm giữ", "dollar", "fx"),
    kpi("Giá trị cổ phiếu", `${vnd(L.stock)}<span class="unit">đ</span>`, `${Object.keys(L.pos).length} mã · ${pct(L.nav ? L.stock / L.nav : 0, false, 0)} tài sản`, "building", "idx"),
    kpi("Lãi/lỗ chưa chốt", `<span class="${plc(L.upl)}">${sgn(L.upl)}</span><span class="unit">đ</span>`, "Theo giá thị trường hiện tại", "activity", "gold"),
    kpi("Lãi/lỗ đã chốt", `<span class="${plc(L.realized)}">${sgn(L.realized)}</span><span class="unit">đ</span>`, `${L.closed.length} lần bán · phí ${vnd(L.fees)}đ · thuế ${vnd(L.taxes)}đ`, "check", "sjc"),
  ].join("");

  // danh mục
  const rows = Object.entries(L.pos).sort((a, b) => b[1].value - a[1].value).map(([s, p]) => {
    const q = P.quotes[s], ch = q && q.last ? q.last / q.ref - 1 : null;
    return `<tr><td class="sym">${esc(s)}</td><td>${nf(p.qty, 0)}</td><td>${nf(Math.max(0, p.sellable), 0)}</td><td>${vnd(p.avg)}</td>
      <td class="${plc(ch)}">${vnd(p.price)}${ch != null ? `<br><small>${pct(ch, true, 1)}</small>` : ""}</td><td>${vnd(p.value)}</td>
      <td class="${plc(p.upl)}">${sgn(p.upl)}<br><small>${pct(p.cost ? p.upl / p.cost : 0, true, 2)}</small></td><td>${pct(L.nav ? p.value / L.nav : 0, false, 1)}</td>
      <td><button class="b2 sm" data-sell="${esc(s)}">${ic("down", "sm")} Bán</button></td></tr>`;
  }).join("");
  $("ppHold").innerHTML = rows || `<tr><td colspan="9" class="muted" style="text-align:left">Chưa nắm giữ cổ phiếu nào. Đặt lệnh mua ở khung bên cạnh.</td></tr>`;
  $("ppHold").querySelectorAll("[data-sell]").forEach(b => b.onclick = () => prefill(b.dataset.sell, "sell"));

  // sổ lệnh
  const st2 = { filled: "Đã khớp", pending: "Chờ khớp", cancelled: "Đã huỷ", expired: "Hết hiệu lực", rejected: "Từ chối" };
  const ord = [...st.orders].sort((a, b) => a.time < b.time ? 1 : -1).slice(0, 60).map(o => `<tr>
    <td>${fmtTime(o.time)}</td>
    <td class="${o.side === "buy" ? "up" : "down"}"><b>${o.side === "buy" ? "Mua" : "Bán"}</b></td><td class="sym">${esc(o.sym)}</td><td>${nf(o.qty, 0)}</td>
    <td>${o.type === "market" ? "Thị trường" : vnd(o.limit)}</td><td>${o.fill_price ? vnd(o.fill_price) : "–"}</td>
    <td><span class="ost ${o.status}">${st2[o.status] || o.status}</span>${o.status === "pending" ? `<br><small class="muted">đến ${o.valid_date.split("-").reverse().join("/")}</small>` : ""}</td>
    <td>${o.status === "pending" && token() ? `<button class="b2 sm danger" data-cancel="${o.id}">Huỷ</button>` : ""}</td></tr>`).join("");
  $("ppOrders").innerHTML = ord || `<tr><td colspan="8" class="muted" style="text-align:left">Chưa có lệnh nào.</td></tr>`;
  $("ppOrders").querySelectorAll("[data-cancel]").forEach(b => b.onclick = () => cancelOrder(b.dataset.cancel));

  // hiệu quả (tính bất đồng bộ)
  const wins = L.closed.filter(c => c.pl > 0);
  $("ppStats").innerHTML = `
    <div><span>Lợi nhuận tổng</span><b class="${plc(ret)}">${pct(ret, true, 2)}</b></div>
    <div><span>Số lần bán đã chốt</span><b>${L.closed.length}</b></div>
    <div><span>Tỷ lệ thắng</span><b>${L.closed.length ? pct(wins.length / L.closed.length, false, 0) : "–"}</b></div>
    <div><span>Lãi TB lần thắng / lỗ TB lần thua</span><b>${wins.length ? pct(wins.reduce((a, c) => a + c.ret, 0) / wins.length, true, 1) : "–"} / ${L.closed.length - wins.length ? pct(L.closed.filter(c => c.pl <= 0).reduce((a, c) => a + c.ret, 0) / (L.closed.length - wins.length), true, 1) : "–"}</b></div>
    <div><span>Tổng phí + thuế</span><b>${vnd(L.fees + L.taxes)}đ</b></div>
    <div id="ppDD"><span>Sụt giảm tối đa</span><b>…</b></div>`;
  // biểu đồ: chỉ vẽ lại khi dữ liệu đổi hoặc sau 60 giây, tránh nháy
  const pk = P.navKey + "|" + Object.keys(L.pos).join(",") + "|" + Math.floor(Date.now() / 60000);
  if (pk !== P.perfKey) navSeries(st).then(s => { P.perfKey = P.navKey + "|" + Object.keys(L.pos).join(",") + "|" + Math.floor(Date.now() / 60000); drawPerf(s, L); }).catch(() => {});
  ticketInfo();
  $("ppNote").textContent = token() ? "" : "Chế độ chỉ xem: dán token GitHub (nút cài đặt) để đặt lệnh.";
}

function drawPerf(s, L) {
  P.charts.forEach(c => c.destroy()); P.charts = [];
  if (!window.Chart) return;
  // sụt giảm tối đa
  let peak = -Infinity, dd = 0;
  for (const p of s) { const r = p.nav / p.flows; peak = Math.max(peak, r); dd = Math.min(dd, r / peak - 1); }
  const el = document.querySelector("#ppDD b"); if (el) { el.textContent = s.length > 1 ? pct(dd, true, 2) : "–"; el.className = dd < 0 ? "down" : ""; }
  const cv = $("ppNav");
  if (s.length < 2) { $("ppNavNote").textContent = "Biểu đồ hiện từ phiên giao dịch thứ 2 kể từ khi tạo tài khoản."; }
  else {
    $("ppNavNote").textContent = "";
    const v0 = s.find(p => p.vni)?.vni, n0 = s[0].nav / s[0].flows;
    P.charts.push(new Chart(cv, { type: "line", data: { labels: s.map(p => p.d.slice(5).split("-").reverse().join("/")), datasets: [
      { label: "Danh mục giả lập", data: s.map(p => ((p.nav / p.flows) / n0 - 1) * 100), borderColor: A.cssv("--s1"), borderWidth: 2, pointRadius: 0, tension: .15 },
      { label: "VN-Index", data: s.map(p => p.vni && v0 ? (p.vni / v0 - 1) * 100 : null), borderColor: A.cssv("--s2"), borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, spanGaps: true }] },
      options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
        plugins: { legend: { labels: { color: A.cssv("--muted"), boxWidth: 12 } }, tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${c.parsed.y == null ? "–" : (c.parsed.y > 0 ? "+" : "") + c.parsed.y.toFixed(2) + "%"}` } } },
        scales: { x: { ticks: { maxTicksLimit: 6, color: A.cssv("--muted") }, grid: { display: false } },
          y: { ticks: { color: A.cssv("--muted"), callback: v => v + "%" }, grid: { color: A.cssv("--line") } } } } }));
  }
  // tỷ trọng
  const items = Object.entries(L.pos).map(([k, p]) => [k, p.value]).sort((a, b) => b[1] - a[1]);
  const top = items.slice(0, 7), rest = items.slice(7).reduce((a, x) => a + x[1], 0);
  const lab = [...top.map(x => x[0]), ...(rest ? ["Khác"] : []), "Tiền mặt"], val = [...top.map(x => x[1]), ...(rest ? [rest] : []), Math.max(0, L.cash)];
  const pal = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#8d97ad"];
  P.charts.push(new Chart($("ppAlloc"), { type: "doughnut", data: { labels: lab, datasets: [{ data: val, backgroundColor: lab.map((l, i) => l === "Tiền mặt" ? A.cssv("--line") : pal[i % 8]), borderColor: A.cssv("--surface"), borderWidth: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: "62%", plugins: { legend: { position: "right", labels: { color: A.cssv("--text-2"), boxWidth: 12 } },
      tooltip: { callbacks: { label: c => ` ${c.label}: ${vnd(c.parsed)}đ (${pct(c.parsed / val.reduce((a, b) => a + b, 0), false, 1)})` } } } } }));
}

// ---------- phiếu lệnh ----------
function setSide(s) { P.side = s; document.querySelectorAll("[data-side]").forEach(b => b.classList.toggle("on", b.dataset.side === s)); $("ptSubmit").className = "b2 primary " + (s === "buy" ? "buy" : "sell"); $("ptSubmit").innerHTML = s === "buy" ? `${ic("up", "sm")} Đặt lệnh MUA` : `${ic("down", "sm")} Đặt lệnh BÁN`; ticketInfo(); }
function setType(t) { P.type = t; document.querySelectorAll("[data-otype]").forEach(b => b.classList.toggle("on", b.dataset.otype === t)); $("ptPriceRow").hidden = t === "market"; ticketInfo(); }
async function onSym() {
  const s = $("ptSym").value.trim().toUpperCase(); $("ptSym").value = s;
  if (!/^[A-Z0-9]{3,10}$/.test(s)) { $("ptQuote").innerHTML = ""; return; }
  await fetchQuotes([s]);
  const q = P.quotes[s];
  if (!q) { $("ptQuote").innerHTML = `<span class="down">Không tìm thấy mã ${esc(s)} trên HOSE/HNX/UPCoM.</span>`; return; }
  if (!$("ptPrice").value || $("ptPrice").dataset.sym !== s) { $("ptPrice").value = ((P.side === "buy" ? q.ask : q.bid) || q.last || q.ref) / 1000; $("ptPrice").dataset.sym = s; }
  ticketInfo();
}
function ticketInfo() {
  const s = $("ptSym")?.value.trim().toUpperCase(), q = P.quotes[s];
  if (q) {
    const ch = q.last ? q.last / q.ref - 1 : null;
    $("ptQuote").innerHTML = `<div class="qt"><div><span>Giá khớp</span><b class="${plc(ch)}">${vnd(q.last || q.ref)}</b>${ch != null ? `<small class="${plc(ch)}">${pct(ch, true, 2)}</small>` : ""}</div>
      <div><span>Mua tốt nhất</span><b>${vnd(q.bid)}</b></div><div><span>Bán tốt nhất</span><b>${vnd(q.ask)}</b></div>
      <div style="grid-column:1/-1"><span>Trần / TC / Sàn</span><b><span class="ceil">${vnd(q.ceil)}</span> / <span class="ref">${vnd(q.ref)}</span> / <span class="floor">${vnd(q.floor)}</span></b></div></div>`;
    $("ptPrice").step = tickOf((+$("ptPrice").value || 0) * 1000) / 1000;
  }
  if (!P.state || !$("ptEst")) return;
  const L = ledger(P.state), qty = +$("ptQty").value || 0;
  const price = P.type === "market" ? (q ? (P.side === "buy" ? q.ask || q.last || q.ref : q.bid || q.last || q.ref) : 0) : (+$("ptPrice").value || 0) * 1000;
  const val = price * qty, fee = val * (P.side === "buy" ? FEE_BUY : FEE_SELL), tax = P.side === "sell" ? val * TAX_SELL : 0;
  const maxQ = P.side === "buy" ? (price ? Math.floor(L.avail / (price * (1 + FEE_BUY)) / LOT) * LOT : 0) : Math.max(0, L.pos[s]?.sellable || 0);
  $("ptEst").innerHTML = `<div><span>Giá trị</span><b>${vnd(val)}đ</b></div><div><span>Phí${tax ? " + thuế" : ""}</span><b>${vnd(fee + tax)}đ</b></div>
    <div><span>${P.side === "buy" ? "Tổng tiền trả" : "Tiền nhận về"}</span><b>${vnd(P.side === "buy" ? val + fee : val - fee - tax)}đ</b></div>
    <div><span>${P.side === "buy" ? "Mua tối đa" : "Bán được"}</span><b>${nf(maxQ, 0)} cp</b></div>`;
  $("ptMax").dataset.max = maxQ;
}
function prefill(sym, side, price) {
  location.hash = "gia-lap";
  setTimeout(() => {
    setSide(side); $("ptSym").value = sym; $("ptPrice").dataset.sym = "";
    if (price) { $("ptPrice").value = price; $("ptPrice").dataset.sym = sym; setType("limit"); }
    onSym(); $("ptQty").focus(); document.querySelector(".pp-ticket").scrollIntoView({ behavior: "smooth", block: "start" });
  }, 50);
}

// ---------- nạp / rút / đặt lại ----------
async function cashFlow(sign) {
  const v = +prompt(sign > 0 ? "Số tiền nạp thêm (đồng):" : "Số tiền rút (đồng):", "10000000")?.replace(/\D/g, "");
  if (!v) return;
  try { await mutate(st => { if (sign < 0 && v > ledger(st).avail) throw new Error("Không đủ tiền khả dụng để rút."); (st.cash_flows ||= []).push({ time: new Date().toISOString(), amount: sign * v, note: sign > 0 ? "Nạp tiền" : "Rút tiền" }); return st; },
    `Giả lập: ${sign > 0 ? "nạp" : "rút"} ${vnd(v)}đ`); render(); } catch (e) { flash(e.message, "bad"); }
}
async function resetAcc() {
  const v = prompt("ĐẶT LẠI tài khoản sẽ xoá toàn bộ lệnh và danh mục giả lập (lịch sử cũ vẫn còn trong git).\nNhập vốn ban đầu mới để xác nhận:", "100000000");
  const n = +String(v || "").replace(/\D/g, ""); if (!n) return;
  try { await mutate(() => ({ version: 1, created: new Date().toISOString(), initial_cash: n, cash_flows: [], orders: [] }), "Giả lập: đặt lại tài khoản"); P.navKey = ""; render(); }
  catch (e) { flash(e.message, "bad"); }
}

// ---------- điều hướng & vòng lặp ----------
async function show(on) {
  document.body.classList.toggle("paper", on);
  $("viewPaper").hidden = !on; $("viewNews").hidden = on;
  document.querySelectorAll("[data-v]").forEach(b => b.classList.toggle("on", (b.dataset.v === "paper") === on));
  if (!on) return;
  render();
  try { await load(); } catch (e) { $("ppBody").innerHTML = `<div class="panel err">${esc(e.message)}</div>`; return; }
  if (P.state) {
    $("ppBody").innerHTML = ""; $("ppMain").hidden = false;
    await fetchQuotes([...Object.keys(ledger(P.state).pos), ...P.state.orders.filter(o => o.status === "pending").map(o => o.sym)]);
    await matchPending(true);
  } else $("ppMain").hidden = true;
  render();
}
function route() { show(location.hash === "#gia-lap"); }
window.addEventListener("hashchange", route);
document.querySelectorAll("[data-v]").forEach(b => b.onclick = () => { location.hash = b.dataset.v === "paper" ? "gia-lap" : ""; if (b.dataset.v !== "paper") history.replaceState(null, "", location.pathname + location.search); route(); });
document.querySelectorAll("[data-side]").forEach(b => b.onclick = () => setSide(b.dataset.side));
document.querySelectorAll("[data-otype]").forEach(b => b.onclick = () => setType(b.dataset.otype));
$("ptSym").addEventListener("change", onSym);
$("ptSym").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); onSym(); } });
["ptQty", "ptPrice"].forEach(id => $(id).addEventListener("input", ticketInfo));
$("ptMax").onclick = () => { $("ptQty").value = $("ptMax").dataset.max || 0; ticketInfo(); };
document.querySelectorAll("[data-pctq]").forEach(b => b.onclick = () => { const m = +$("ptMax").dataset.max || 0; $("ptQty").value = Math.floor(m * +b.dataset.pctq / LOT) * LOT; ticketInfo(); });
$("ptSubmit").onclick = placeOrder;
$("ppDeposit").onclick = () => cashFlow(1); $("ppWithdraw").onclick = () => cashFlow(-1); $("ppReset").onclick = resetAcc;
document.addEventListener("click", e => { const b = e.target.closest("[data-paperbuy]"); if (b) prefill(b.dataset.paperbuy, "buy", b.dataset.price); });

setInterval(async () => {
  if ($("viewPaper").hidden || document.hidden || !P.state) return;
  const syms = [...Object.keys(ledger(P.state).pos), ...P.state.orders.filter(o => o.status === "pending").map(o => o.sym), $("ptSym").value.trim().toUpperCase()];
  await fetchQuotes(syms); await matchPending(false); render();
}, 3000);
setSide("buy"); setType("limit");
route();
})();

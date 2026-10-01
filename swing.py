"""Bộ lọc lướt sóng ngắn hạn cho cổ phiếu VN (VN100).

Mỗi chiến lược (setup) được kiểm định trên lịch sử với điều kiện sát thực tế:
- Vào lệnh ở giá mở cửa phiên sau tín hiệu; bỏ qua nếu mở cửa cao hơn vùng mua (không mua đuổi).
- T+2: cổ phiếu mua phiên T chỉ bán được từ phiên T+2.
- Cắt lỗ / chốt lời theo ATR; nếu cùng phiên chạm cả hai thì tính cắt lỗ (giả định bất lợi).
- Hết hạn nắm giữ thì bán ở giá đóng cửa.
- Trừ phí + thuế khứ hồi COST.
Chỉ setup có lãi kỳ vọng dương sau phí ở phần ngoài mẫu (2 năm gần nhất) mới được dùng để chọn mã.
"""
import csv
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

import data

ROOT = os.path.dirname(os.path.abspath(__file__))
JOURNAL = os.path.join(ROOT, "data", "swing_journal.csv")
COST = 0.004          # phí mua ~0.15% + phí bán ~0.15% + thuế bán 0.1%
MIN_HOLD = 2          # T+2
MAX_HOLD = 10         # tối đa 10 phiên
STOP_ATR, TARGET_ATR, CHASE_ATR = 1.5, 2.5, 0.5
MIN_VALUE = 10e9      # thanh khoản trung bình 20 phiên tối thiểu 10 tỷ đồng/phiên
OOS_BARS = 500        # ~2 năm giao dịch gần nhất dùng làm ngoài mẫu
TOP_N = 5

SETUPS = {
    "breakout": "Bứt phá đỉnh 20 phiên kèm khối lượng lớn, trong xu hướng tăng",
    "pullback": "Điều chỉnh về MA20 trong xu hướng tăng, RSI trung tính",
    "rsi2": "Quá bán ngắn hạn (RSI 2 phiên < 10) trong xu hướng tăng dài hạn (trên MA200)",
}


def universe():
    try:
        r = requests.get("https://bgapidatafeed.vps.com.vn/getlistckindex/VN100", headers=data.UA, timeout=20)
        syms = [s for s in r.json() if isinstance(s, str)]
        if syms:
            return syms, "VPS (danh sách VN100 hiện tại)"
    except Exception:
        pass
    return [], "không lấy được danh sách VN100"


def features(df):
    c, h, l, o, v = df["close"], df["high"], df["low"], df["open"], df["volume"]
    f = pd.DataFrame(index=df.index)
    f["open"], f["high"], f["low"], f["close"] = o, h, l, c
    f["sma20"], f["sma50"], f["sma200"] = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    f["atr"] = tr.rolling(14).mean()
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    ls = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    f["rsi"] = 100 - 100 / (1 + g / ls.replace(0, np.nan))
    g2 = d.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    l2 = (-d.clip(upper=0)).ewm(alpha=1 / 2, adjust=False).mean()
    f["rsi2"] = 100 - 100 / (1 + g2 / l2.replace(0, np.nan))
    f["vol_ratio"] = v / v.rolling(20).mean()
    f["value20"] = (c * 1000 * v).rolling(20).mean()       # giá VNDirect tính theo nghìn đồng
    f["hi20_prev"] = c.rolling(20).max().shift(1)
    f["ret60"] = c.pct_change(60)
    uptrend = (c > f.sma50) & (f.sma50 > f.sma200)
    liquid = f.value20 >= MIN_VALUE
    f["sig_breakout"] = uptrend & liquid & (c > f.hi20_prev) & (f.vol_ratio >= 1.5)
    f["sig_pullback"] = (liquid & (f.sma20 > f.sma50) & (f.sma50 > f.sma200)
                         & (c >= f.sma20 * 0.98) & (c <= f.sma20 * 1.01) & f.rsi.between(40, 55) & (c >= o))
    f["sig_rsi2"] = liquid & (c > f.sma200) & (f.rsi2 < 10)
    return f


def simulate(f, i):
    """Mô phỏng một lệnh với tín hiệu ở phiên i. Trả về dict hoặc None nếu không khớp / thiếu dữ liệu."""
    n = len(f)
    if i + 1 >= n:
        return None
    close, atr = f["close"].iat[i], f["atr"].iat[i]
    if not atr or np.isnan(atr):
        return None
    e = f["open"].iat[i + 1]
    if e > close + CHASE_ATR * atr:
        return {"filled": False}
    stop, target = e - STOP_ATR * atr, e + TARGET_ATR * atr
    last = min(i + 1 + MAX_HOLD, n - 1)
    for j in range(i + 1 + MIN_HOLD, last + 1):
        o, hi, lo = f["open"].iat[j], f["high"].iat[j], f["low"].iat[j]
        if o <= stop:
            return {"filled": True, "exit": o, "why": "cắt lỗ (mở cửa dưới mức cắt lỗ)", "j": j, "e": e}
        if o >= target:
            return {"filled": True, "exit": o, "why": "chốt lời (mở cửa trên mục tiêu)", "j": j, "e": e}
        if lo <= stop:
            return {"filled": True, "exit": stop, "why": "cắt lỗ", "j": j, "e": e}
        if hi >= target:
            return {"filled": True, "exit": target, "why": "chốt lời", "j": j, "e": e}
    if last < i + 1 + MAX_HOLD:
        return {"filled": True, "open": True, "e": e}     # lệnh chưa kết thúc (dữ liệu chưa đủ)
    return {"filled": True, "exit": f["close"].iat[last], "why": "hết hạn nắm giữ", "j": last, "e": e}


def backtest(f, setup):
    trades, busy_until = [], -1
    sig = f[f"sig_{setup}"].values
    for i in np.nonzero(sig)[0]:
        if i <= busy_until or i < 200:
            continue
        t = simulate(f, i)
        if not t or not t.get("filled") or t.get("open"):
            continue
        trades.append({"i": i, "ret": t["exit"] / t["e"] - 1 - COST, "hold": t["j"] - i - 1})
        busy_until = t["j"]
    return trades


def stats(rets):
    r = np.array(rets)
    if len(r) == 0:
        return {"n": 0}
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": int(len(r)), "win": float((r > 0).mean()), "avg": float(r.mean()), "median": float(np.median(r)),
            "pf": float(wins / losses) if losses > 0 else None, "worst": float(r.min()), "best": float(r.max())}


def fetch_all(syms, years=10):
    from datetime import datetime
    now = datetime.now(data.VN_TZ)
    today = pd.Timestamp(now.date())

    def one(s):
        try:
            df = data.vn_history(s, years)
            # Trong phiên (trước 15:00) nến hôm nay chưa đóng: chỉ lọc trên các phiên đã đóng cửa
            if now.hour < 15 and len(df) and df.index[-1] >= today:
                df = df[df.index < today]
            return s, df
        except Exception:
            return s, None
    with ThreadPoolExecutor(8) as ex:
        return {s: df for s, df in ex.map(one, syms) if df is not None and len(df) > 260}


def run(index_close=None, record=True):
    syms, uni_src = universe()
    out = {"universe": uni_src, "n_universe": len(syms), "setups": {}, "picks": [], "params": {
        "cost": COST, "min_hold": MIN_HOLD, "max_hold": MAX_HOLD, "stop_atr": STOP_ATR, "target_atr": TARGET_ATR,
        "chase_atr": CHASE_ATR, "min_value": MIN_VALUE, "oos_bars": OOS_BARS}, "errors": []}
    if not syms:
        out["errors"].append("Không lấy được danh sách VN100")
        return out, {}
    hist = fetch_all(syms)
    out["n_loaded"] = len(hist)
    feats = {s: features(df) for s, df in hist.items()}

    # kiểm định từng setup trên toàn bộ vũ trụ, tách trong mẫu / ngoài mẫu theo thời gian
    for setup, desc in SETUPS.items():
        ins, oos = [], []
        for s, f in feats.items():
            cut = len(f) - OOS_BARS
            for t in backtest(f, setup):
                (oos if t["i"] >= cut else ins).append(t["ret"])
        st_in, st_out = stats(ins), stats(oos)
        # đạt chuẩn khi có lãi sau phí ở CẢ trong mẫu lẫn ngoài mẫu
        valid = (st_out.get("n", 0) >= 30 and st_out["avg"] > 0 and (st_out.get("pf") or 0) > 1.1
                 and st_in.get("n", 0) >= 30 and st_in["avg"] > 0)
        out["setups"][setup] = {"desc": desc, "in_sample": st_in, "out_of_sample": st_out, "valid": bool(valid)}

    # tín hiệu hôm nay
    cands = []
    ix_ret60 = index_close.pct_change(60).iloc[-1] if index_close is not None else 0.0
    for s, f in feats.items():
        last = f.iloc[-1]
        for setup in SETUPS:
            if not bool(last[f"sig_{setup}"]):
                continue
            atr, c = float(last.atr), float(last.close)
            cands.append({
                "sym": s, "setup": setup, "date": str(f.index[-1].date()), "close": c, "atr": atr,
                "buy_max": c + CHASE_ATR * atr, "stop": c - STOP_ATR * atr, "target": c + TARGET_ATR * atr,
                "stop_pct": -STOP_ATR * atr / c, "target_pct": TARGET_ATR * atr / c,
                "rs60": float(last.ret60 - ix_ret60), "vol_ratio": float(last.vol_ratio), "rsi": float(last.rsi),
                "value20_bn": float(last.value20 / 1e9), "valid_setup": out["setups"][setup]["valid"],
                "spark": [round(float(x), 2) for x in f["close"].tail(60)],
            })
    # xếp hạng: setup đã kiểm định trước, rồi sức mạnh tương đối 60 phiên
    cands.sort(key=lambda x: (x["valid_setup"], out["setups"][x["setup"]]["out_of_sample"].get("avg", -1), x["rs60"]), reverse=True)
    out["candidates_total"] = len(cands)
    out["picks"] = [c for c in cands if c["valid_setup"]][:TOP_N]
    out["watch"] = [c for c in cands if not c["valid_setup"]][:TOP_N]   # có tín hiệu nhưng setup chưa đạt chuẩn

    # nhật ký: chấm lệnh cũ, ghi lệnh mới
    j = load_journal()
    j = evaluate_journal(j, feats)
    if record:
        for p in out["picks"]:
            j = [r for r in j if not (r["date"] == p["date"] and r["sym"] == p["sym"])]
            j.append({"date": p["date"], "sym": p["sym"], "setup": p["setup"], "close": p["close"], "atr": p["atr"],
                      "buy_max": p["buy_max"], "status": "chờ khớp", "entry": "", "exit": "", "exit_date": "", "ret": ""})
    save_journal(j)
    done = [float(r["ret"]) for r in j if r["ret"] not in ("", None)]
    out["live"] = {**stats(done), "open": sum(1 for r in j if r["status"] in ("chờ khớp", "đang giữ")),
                   "recent": j[-15:][::-1]}
    return out, feats


# ---------- nhật ký lướt sóng ----------
FIELDS = ["date", "sym", "setup", "close", "atr", "buy_max", "status", "entry", "exit", "exit_date", "ret"]


def load_journal():
    if not os.path.exists(JOURNAL):
        return []
    with open(JOURNAL, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def save_journal(rows):
    os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
    with open(JOURNAL, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def evaluate_journal(rows, feats):
    for r in rows:
        if r["status"] not in ("chờ khớp", "đang giữ"):
            continue
        f = feats.get(r["sym"])
        if f is None:
            continue
        idx = f.index.get_indexer([pd.Timestamp(r["date"])])[0]
        if idx < 0:
            continue
        t = simulate(f, idx)
        if t is None:
            continue
        if not t.get("filled"):
            r["status"] = "không khớp (mở cửa cao hơn vùng mua)"
        elif t.get("open"):
            r["status"], r["entry"] = "đang giữ", round(t["e"], 2)
        else:
            r.update(status=t["why"], entry=round(t["e"], 2), exit=round(t["exit"], 2),
                     exit_date=str(f.index[t["j"]].date()), ret=round(t["exit"] / t["e"] - 1 - COST, 4))
    return rows

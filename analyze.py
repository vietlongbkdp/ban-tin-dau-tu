"""Chỉ báo kỹ thuật, trọng số tự hiệu chỉnh và kiểm định lịch sử.

Mọi con số đều tính từ chuỗi giá đầu vào. Trọng số của từng chỉ báo được tính lại
mỗi ngày trên toàn bộ lịch sử mới nhất (chỉ báo nào không có ý nghĩa thống kê thì
trọng số = 0), và được kiểm định walk-forward trên 250 phiên gần nhất.
"""
import numpy as np
import pandas as pd

SIGNAL_NAMES = {
    "trend": "Xu hướng (giá vs MA50/MA200)",
    "macd": "MACD histogram",
    "rsi": "RSI14 quá mua/quá bán",
    "boll": "Bollinger Bands (20, 2)",
    "mom20": "Động lượng 20 phiên",
    "mom60": "Động lượng 60 phiên",
    "volume": "Đột biến khối lượng",
}
OOS_DAYS = 250


def indicators(df):
    c = df["close"]
    out = pd.DataFrame(index=df.index)
    out["close"] = c
    out["sma20"] = c.rolling(20).mean()
    out["sma50"] = c.rolling(50).mean()
    out["sma200"] = c.rolling(200).mean()
    d = c.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    out["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]
    sd = c.rolling(20).std()
    out["bb_up"], out["bb_lo"] = out["sma20"] + 2 * sd, out["sma20"] - 2 * sd
    tr = pd.concat([df["high"] - df["low"], (df["high"] - c.shift()).abs(), (df["low"] - c.shift()).abs()], axis=1).max(axis=1)
    out["atr"] = tr.rolling(14).mean()
    out["ret20"], out["ret60"] = c.pct_change(20), c.pct_change(60)
    out["vol_ratio"] = df["volume"] / df["volume"].rolling(20).mean()
    return out


def signals(ind):
    s = pd.DataFrame(index=ind.index)
    c = ind["close"]
    s["trend"] = np.where((c > ind.sma50) & (ind.sma50 > ind.sma200), 1, np.where((c < ind.sma50) & (ind.sma50 < ind.sma200), -1, 0))
    s["macd"] = np.sign(ind.macd_hist).fillna(0)
    s["rsi"] = np.where(ind.rsi < 30, 1, np.where(ind.rsi > 70, -1, 0))
    s["boll"] = np.where(c < ind.bb_lo, 1, np.where(c > ind.bb_up, -1, 0))
    s["mom20"] = np.sign(ind.ret20).fillna(0)
    s["mom60"] = np.sign(ind.ret60).fillna(0)
    daily = c.pct_change()
    vr = ind.vol_ratio.replace([np.inf, -np.inf], np.nan)
    s["volume"] = np.where(vr > 1.5, np.sign(daily), 0)
    s = s.fillna(0)
    s[ind.sma200.isna()] = np.nan  # chưa đủ dữ liệu để tính đủ chỉ báo
    return s


def forward(c, h):
    fwd = c.shift(-h) / c - 1
    fut_min = pd.concat([c.shift(-i) for i in range(1, h + 1)], axis=1).min(axis=1)
    dd = fut_min / c - 1
    dd[fwd.isna()] = np.nan
    return fwd, dd


def fit_weights(sig, fwd, h):
    """Trọng số = tương quan giữa tín hiệu và lợi suất tương lai, chỉ giữ khi có ý nghĩa thống kê.
    Các quan sát chồng lấn nên cỡ mẫu hiệu dụng ~ n/h; yêu cầu |t| >= 2."""
    m = sig.notna().all(axis=1) & fwd.notna()
    X, y = sig[m], fwd[m]
    n_eff = max(len(y) / h, 1)
    w = {}
    for k in sig.columns:
        x = X[k]
        if x.std() == 0 or len(x) < 100:
            w[k] = 0.0
            continue
        r = float(np.corrcoef(x, y)[0, 1])
        t = r * np.sqrt(n_eff) / np.sqrt(max(1 - r * r, 1e-9))
        w[k] = round(r, 4) if abs(t) >= 2 else 0.0
    return w


def score(sig, w):
    return sum(sig[k] * v for k, v in w.items())


def bucket_stats(hist_score, fwd, dd, today_score):
    """Thống kê lợi suất tương lai của các ngày có điểm tổng hợp cùng nhóm với hôm nay."""
    m = hist_score.notna() & fwd.notna()
    hs, fw, d = hist_score[m], fwd[m], dd[m]
    if (hs == 0).all():
        sel = pd.Series(True, index=hs.index)
    else:
        qs = np.unique(np.quantile(hs, [0.2, 0.4, 0.6, 0.8]))
        b_today = np.searchsorted(qs, today_score, side="right")
        sel = pd.Series(np.searchsorted(qs, hs.values, side="right") == b_today, index=hs.index)
    f = fw[sel]
    return {
        "n": int(sel.sum()),
        "prob_up": float((f > 0).mean()),
        "median": float(f.median()),
        "p10": float(f.quantile(0.1)),
        "p90": float(f.quantile(0.9)),
        "avg_max_drawdown": float(d[sel].mean()),
        "worst_drawdown": float(d[sel].min()),
        "base_prob_up": float((fw > 0).mean()),
        "base_median": float(fw.median()),
    }


def walk_forward(sig, c, h):
    """Huấn luyện trên dữ liệu cũ, kiểm tra trên OOS_DAYS phiên gần nhất chưa từng dùng để huấn luyện."""
    fwd, _ = forward(c, h)
    valid = fwd.dropna().index
    if len(valid) < OOS_DAYS + 500:
        return None
    test_idx = valid[-OOS_DAYS:]
    train_end = valid[-OOS_DAYS - h]  # chừa khoảng h phiên để không rò rỉ dữ liệu tương lai
    tr = sig.index <= train_end
    w = fit_weights(sig[tr], fwd[tr], h)
    base_up = (fwd[tr].dropna() > 0).mean()
    sc = score(sig.loc[test_idx], w)
    actual_up = fwd.loc[test_idx] > 0
    active = sc != 0
    model_hit = float(((sc[active] > 0) == actual_up[active]).mean()) if active.any() else None
    naive_hit = float((actual_up == (base_up >= 0.5)).mean())
    return {"model_hit": model_hit, "naive_hit": naive_hit, "active_days": int(active.sum()), "test_days": OOS_DAYS}


def analyze(df, horizons):
    ind = indicators(df)
    sig = signals(ind)
    last = ind.iloc[-1]
    today_sig = sig.iloc[-1]
    c = df["close"]
    res = {
        "source": df.attrs.get("source"),
        "last_date": str(df.index[-1].date()),
        "first_date": str(df.index[0].date()),
        "n_days": len(df),
        "close": float(last.close),
        "change_1d": float(c.pct_change().iloc[-1]),
        "change_20d": float(last.ret20),
        "rsi": float(last.rsi),
        "sma20": float(last.sma20), "sma50": float(last.sma50), "sma200": float(last.sma200),
        "macd_hist": float(last.macd_hist),
        "bb_up": float(last.bb_up), "bb_lo": float(last.bb_lo),
        "atr": float(last.atr),
        "support_20": float(df["low"].tail(20).min()), "resist_20": float(df["high"].tail(20).max()),
        "support_60": float(df["low"].tail(60).min()), "resist_60": float(df["high"].tail(60).max()),
        "high_52w": float(df["high"].tail(250).max()), "low_52w": float(df["low"].tail(250).min()),
        "signals_today": {k: int(today_sig[k]) for k in sig.columns},
        "horizons": {},
        "chart": {
            "dates": [str(d.date()) for d in ind.index[-180:]],
            "close": [round(float(x), 2) for x in ind.close.tail(180)],
            "sma50": [None if pd.isna(x) else round(float(x), 2) for x in ind.sma50.tail(180)],
            "sma200": [None if pd.isna(x) else round(float(x), 2) for x in ind.sma200.tail(180)],
        },
    }
    for label, h in horizons.items():
        fwd, dd = forward(c, h)
        w = fit_weights(sig, fwd, h)
        hist_score = score(sig, w)
        today = float(score(sig.iloc[[-1]], w).iloc[0])
        st = bucket_stats(hist_score, fwd, dd, today)
        res["horizons"][label] = {
            "days": h,
            "weights": w,
            "score": today,
            "stats": st,
            "walk_forward": walk_forward(sig, c, h),
            "stop_ref": float(last.close - 2 * last.atr),
        }
    return res


def verdict(hz):
    """Nhãn tín hiệu tổng hợp, lấy hoàn toàn từ số liệu kiểm định."""
    st, wf = hz["stats"], hz["walk_forward"]
    if all(v == 0 for v in hz["weights"].values()):
        return "Không có lợi thế thống kê", "Không chỉ báo nào có ý nghĩa thống kê cho kỳ hạn này; kết quả chỉ phản ánh tỷ lệ nền của lịch sử."
    no_edge = wf is not None and wf["model_hit"] is not None and wf["model_hit"] <= wf["naive_hit"]
    p = st["prob_up"]
    if p >= 0.6 and st["median"] > 0:
        lab = "Tích cực"
    elif p <= 0.4 and st["median"] < 0:
        lab = "Tiêu cực"
    else:
        lab = "Trung lập"
    note = ""
    if no_edge:
        note = "Cảnh báo: trong kiểm định 250 phiên gần nhất, mô hình không đoán đúng hướng tốt hơn cách đoán đơn giản theo tỷ lệ nền, nên độ tin cậy thấp."
    return lab, note

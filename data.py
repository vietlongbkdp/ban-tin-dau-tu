"""Lấy dữ liệu giá từ các nguồn công khai. Không nguồn nào trả dữ liệu thì báo lỗi, không đoán."""
import csv
import os
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128 Safari/537.36"}
VN_TZ = timezone(timedelta(hours=7))
ROOT = os.path.dirname(os.path.abspath(__file__))


def _ohlcv_from_tv(j, source):
    df = pd.DataFrame({"open": j["o"], "high": j["h"], "low": j["l"], "close": j["c"], "volume": j["v"]},
                      index=pd.to_datetime(j["t"], unit="s").normalize())
    df = df[~df.index.duplicated(keep="last")].astype(float)
    df.attrs["source"] = source
    return df


def vn_history(symbol, years=10):
    """Giá ngày cổ phiếu/chỉ số VN. Nguồn chính VNDirect, dự phòng VPS."""
    now = int(time.time())
    frm = now - years * 365 * 86400
    sources = [
        ("VNDirect dchart", f"https://dchart-api.vndirect.com.vn/dchart/history?symbol={symbol}&resolution=D&from={frm}&to={now}"),
        ("VPS histdatafeed", f"https://histdatafeed.vps.com.vn/tradingview/history?symbol={symbol}&resolution=D&from={frm}&to={now}"),
    ]
    errors = []
    for name, url in sources:
        try:
            r = requests.get(url, headers=UA, timeout=30)
            j = r.json()
            if j.get("t"):
                return _ohlcv_from_tv(j, name)
            errors.append(f"{name}: rỗng")
        except Exception as e:
            errors.append(f"{name}: {e}")
    raise RuntimeError(f"Không lấy được {symbol}: " + "; ".join(errors))


def yf_history(ticker, years=10):
    import yfinance as yf
    d = yf.download(ticker, period=f"{years}y", progress=False, auto_adjust=False)
    if d.empty:
        raise RuntimeError(f"Yahoo Finance không trả dữ liệu cho {ticker}")
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    df = d.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"]).astype(float)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.attrs["source"] = f"Yahoo Finance ({ticker})"
    return df


def sjc_snapshot():
    """Giá vàng miếng SJC hiện tại (triệu VND/lượng) qua API bảng giá PNJ."""
    r = requests.get("https://edge-api.pnj.io/ecom-frontend/v1/get-gold-price?zone=00", headers=UA, timeout=30)
    j = r.json()
    row = next(x for x in j["data"] if x["masp"] == "SJC")
    # PNJ niêm yết nghìn đồng/chỉ -> triệu đồng/lượng (1 lượng = 10 chỉ)
    return {
        "buy": row["giamua"] / 100.0,
        "sell": row["giaban"] / 100.0,
        "updated": j.get("updateDate"),
        "source": "PNJ edge-api (bảng giá vàng miếng SJC)",
    }


def append_sjc_history(snap):
    """Lưu giá SJC mỗi ngày để tích lũy lịch sử (nguồn không cung cấp lịch sử)."""
    path = os.path.join(ROOT, "data", "sjc_history.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["date"] != today]
    rows.append({"date": today, "buy": snap["buy"], "sell": snap["sell"], "updated": snap["updated"]})
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "buy", "sell", "updated"])
        w.writeheader()
        w.writerows(rows)
    return pd.DataFrame(rows)


def gold_spot():
    """Giá vàng giao ngay XAU/USD hiện tại. Thử lần lượt nhiều nguồn độc lập."""
    errors = []
    try:
        q = requests.get("https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD",
                         headers=UA, timeout=20).json()[0]["spreadProfilePrices"][0]
        return {"price": (q["bid"] + q["ask"]) / 2, "source": "Swissquote (giữa giá mua/bán)",
                "at": datetime.now(VN_TZ).strftime("%H:%M %d/%m")}
    except Exception as e:
        errors.append(f"Swissquote: {e}")
    try:
        j = requests.get("https://api.coinbase.com/v2/prices/XAU-USD/spot", headers=UA, timeout=20).json()
        return {"price": float(j["data"]["amount"]), "source": "Coinbase XAU-USD spot",
                "at": datetime.now(VN_TZ).strftime("%H:%M %d/%m")}
    except Exception as e:
        errors.append(f"Coinbase: {e}")
    try:
        j = requests.get("https://api.gold-api.com/price/XAU", headers=UA, timeout=20).json()
        return {"price": float(j["price"]), "source": "gold-api.com", "at": j.get("updatedAt")}
    except Exception as e:
        errors.append(f"gold-api: {e}")
    raise RuntimeError("Không lấy được giá vàng giao ngay: " + "; ".join(errors))

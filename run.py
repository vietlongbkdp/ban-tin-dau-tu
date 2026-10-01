"""Chạy toàn bộ phần định lượng: lấy dữ liệu -> phân tích -> nhật ký -> output/analysis.json.

python run.py            lượt chạy định kỳ (ghi dự báo mới vào nhật ký)
python run.py --manual   lượt chạy tay giữa phiên: vẫn chấm điểm nhật ký nhưng không ghi dự báo mới,
                         vì giá giữa phiên chưa phải giá đóng cửa
"""
import json
import os
import re
import sys
import traceback
from datetime import datetime

import analyze
import data
import journal

ROOT = os.path.dirname(os.path.abspath(__file__))
OZ_PER_LUONG = 37.5 / 31.1034768


def parse_symbol(raw):
    """'FPT' -> cổ phiếu VN; 'AAPL.US' -> cổ phiếu Mỹ qua Yahoo Finance."""
    s = raw.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,10}(\.US)?", s):
        return None
    return s


def parse_crypto(raw):
    """'btc' -> 'BTC' (phân tích bằng lịch sử Yahoo Finance BTC-USD)."""
    s = raw.strip().upper()
    return s if re.fullmatch(r"[A-Z0-9]{2,10}", s) else None


def main():
    manual = "--manual" in sys.argv
    cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    years, horizons = cfg["history_years"], cfg["horizons"]
    gold = cfg.get("gold", {"world": True, "sjc": True})
    out = {"generated_at": datetime.now(data.VN_TZ).strftime("%Y-%m-%d %H:%M (giờ VN)"),
           "run_kind": "manual" if manual else "scheduled",
           "watchlist": {"stocks": cfg["stocks"], "crypto": cfg.get("crypto", []), "gold": gold},
           "assets": {}, "errors": []}
    series = {}

    def run_asset(key, name, kind, loader):
        try:
            df = loader()
            series[key] = df
            a = analyze.analyze(df, horizons)
            a.update(name=name, kind=kind)
            out["assets"][key] = a
        except Exception as e:
            out["errors"].append(f"{name}: {e}")
            traceback.print_exc()

    run_asset(cfg["index"], "VN-Index", "index", lambda: data.vn_history(cfg["index"], years))
    for raw in cfg["stocks"]:
        s = parse_symbol(raw)
        if not s:
            out["errors"].append(f"Mã không hợp lệ: {raw!r}")
            continue
        if s.endswith(".US"):
            t = s[:-3]
            run_asset(s, f"Cổ phiếu Mỹ {t}", "stock", lambda t=t: data.yf_history(t, years))
        else:
            run_asset(s, f"Cổ phiếu {s}", "stock", lambda s=s: data.vn_history(s, years))

    for raw in cfg.get("crypto", []):
        c = parse_crypto(raw)
        if not c:
            out["errors"].append(f"Mã crypto không hợp lệ: {raw!r}")
            continue
        run_asset(f"{c}-USD", f"Crypto {c} (USD)", "crypto", lambda c=c: data.yf_history(f"{c}-USD", years))

    if gold.get("world") or gold.get("sjc"):
        run_asset("GOLD_USD", "Vàng tương lai COMEX GC=F (USD/oz)", "gold", lambda: data.yf_history(cfg["gold_world"], years))
        # Vàng thế giới quy đổi VND/lượng: đại diện xu hướng cho giá vàng trong nước
        try:
            g, fx = series["GOLD_USD"], data.yf_history(cfg["fx"], years)
            f = fx["close"].reindex(g.index).ffill()
            gv = g.mul(f, axis=0).mul(OZ_PER_LUONG / 1e6).dropna()
            gv["volume"] = g["volume"].reindex(gv.index)
            gv.attrs["source"] = "Yahoo Finance: hợp đồng tương lai GC=F × tỷ giá VND=X (triệu VND/lượng)"
            out["fx"] = {"usdvnd": float(fx["close"].iloc[-1]), "date": str(fx.index[-1].date()), "source": fx.attrs["source"]}
            run_asset("GOLD_VND", "Vàng thế giới quy đổi VND (theo GC=F, triệu/lượng)", "gold", lambda: gv)
        except Exception as e:
            out["errors"].append(f"Vàng quy đổi VND: {e}")

    if gold.get("world") or gold.get("sjc"):
        try:
            out["gold_spot"] = data.gold_spot()
        except Exception as e:
            out["errors"].append(str(e))

    if gold.get("sjc"):
        try:
            snap = data.sjc_snapshot()
            hist = data.append_sjc_history(snap)
            # Chênh lệch SJC tính theo giá giao ngay (như báo chí), chỉ dùng GC=F khi không có giá giao ngay
            if out.get("gold_spot") and out.get("fx"):
                world = out["gold_spot"]["price"] * out["fx"]["usdvnd"] * OZ_PER_LUONG / 1e6
                snap["world_basis"] = f"giá giao ngay {out['gold_spot']['source']} × tỷ giá Yahoo VND=X"
            elif "GOLD_VND" in out["assets"]:
                world = out["assets"]["GOLD_VND"]["close"]
                snap["world_basis"] = "hợp đồng tương lai GC=F (không lấy được giá giao ngay)"
            else:
                world = None
            if world:
                snap["world_equiv"] = world
                snap["premium"] = snap["sell"] - world
                snap["premium_pct"] = snap["sell"] / world - 1
            snap["history_days"] = len(hist)
            snap["history"] = hist.to_dict(orient="records")[-120:]
            out["sjc"] = snap
        except Exception as e:
            out["errors"].append(f"Giá SJC: {e}")

    # Nhật ký dự báo: chấm điểm dự báo cũ, hiệu chỉnh, ghi dự báo mới (chỉ ở lượt chạy định kỳ)
    j = journal.load()
    j = journal.evaluate(j, {k: v["close"] for k, v in series.items()})
    sh = cfg["stance_horizon"]
    for key, a in out["assets"].items():
        for label, hz in a["horizons"].items():
            st = hz["stats"]
            skill = journal.live_skill(j, key, label)
            p_adj, note = journal.calibrate(st["prob_up"], st["base_prob_up"], skill)
            hz["live"] = skill
            hz["prob_up_final"] = p_adj
            hz["calibration_note"] = note
            hz["verdict"], hz["verdict_note"] = analyze.verdict(hz)
            if not manual:
                j = journal.record(j, a["last_date"], key, label, hz["days"], p_adj, st["base_prob_up"], a["close"])

    # Quan điểm hằng ngày theo quy tắc cố định; cũng được ghi nhật ký để chấm điểm khi đến hạn
    stances = {}
    for key, a in out["assets"].items():
        if key == "GOLD_USD" or (a["kind"] == "gold" and not gold.get("world")):
            continue  # vàng thế giới đã có bản quy đổi VND; tắt 'world' thì chỉ giữ SJC
        s = analyze.stance(a, sh)
        s["name"] = a["name"]
        stances[key] = s
        if not manual:
            hz = a["horizons"][sh]
            j = journal.record(j, a["last_date"], key, f"Quan điểm ({sh})", hz["days"],
                               {1: 1.0, -1: 0.0, 0: 0.5}[s["sign"]], hz["stats"]["base_prob_up"], a["close"])
    if out.get("sjc", {}).get("premium_pct") is not None:
        s = analyze.sjc_stance(out["sjc"])
        s["name"] = "Vàng miếng SJC"
        stances["SJC"] = s
    for key, s in stances.items():
        if key in out["assets"]:
            s["live"] = journal.live_skill(j, key, f"Quan điểm ({sh})")
    out["stances"] = stances
    out["best_pick"] = analyze.best_pick(stances)
    if not gold.get("world"):
        out["assets"].pop("GOLD_USD", None)
        out["assets"].pop("GOLD_VND", None)
    journal.save(j)

    # Bộ lọc lướt sóng ngắn hạn (VN100). Chỉ ghi lệnh mới vào nhật ký ở lượt chạy định kỳ.
    try:
        import swing
        ix = series.get(cfg["index"])
        out["swing"], _ = swing.run(ix["close"] if ix is not None else None, record=not manual)
    except Exception as e:
        out["errors"].append(f"Bộ lọc lướt sóng: {e}")
        traceback.print_exc()

    os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
    with open(os.path.join(ROOT, "output", "analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
    print(f"OK ({out['run_kind']}): {len(out['assets'])} tài sản, lỗi: {out['errors']}")
    return 0 if out["assets"] else 1


if __name__ == "__main__":
    sys.exit(main())

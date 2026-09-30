"""Chạy toàn bộ phần định lượng: lấy dữ liệu -> phân tích -> nhật ký -> output/analysis.json."""
import json
import os
import sys
import traceback
from datetime import datetime

import analyze
import data
import journal

ROOT = os.path.dirname(os.path.abspath(__file__))
OZ_PER_LUONG = 37.5 / 31.1034768


def main():
    cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    years, horizons = cfg["history_years"], cfg["horizons"]
    out = {"generated_at": datetime.now(data.VN_TZ).strftime("%Y-%m-%d %H:%M (giờ VN)"), "assets": {}, "errors": []}
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
    for s in cfg["stocks"]:
        run_asset(s, f"Cổ phiếu {s}", "stock", lambda s=s: data.vn_history(s, years))
    run_asset("GOLD_USD", "Vàng thế giới (USD/oz)", "gold", lambda: data.yf_history(cfg["gold_world"], years))

    # Vàng thế giới quy đổi VND/lượng: đại diện xu hướng cho giá vàng trong nước
    try:
        g, fx = series["GOLD_USD"], data.yf_history(cfg["fx"], years)
        f = fx["close"].reindex(g.index).ffill()
        gv = g.mul(f, axis=0).mul(OZ_PER_LUONG / 1e6).dropna()
        gv["volume"] = g["volume"].reindex(gv.index)
        gv.attrs["source"] = "Tính từ Yahoo Finance GC=F × VND=X (triệu VND/lượng)"
        out["fx"] = {"usdvnd": float(fx["close"].iloc[-1]), "date": str(fx.index[-1].date()), "source": fx.attrs["source"]}
        run_asset("GOLD_VND", "Vàng thế giới quy đổi (triệu VND/lượng)", "gold", lambda: gv)
    except Exception as e:
        out["errors"].append(f"Vàng quy đổi VND: {e}")

    try:
        snap = data.sjc_snapshot()
        hist = data.append_sjc_history(snap)
        if "GOLD_VND" in out["assets"]:
            world = out["assets"]["GOLD_VND"]["close"]
            snap["world_equiv"] = world
            snap["premium"] = snap["sell"] - world
            snap["premium_pct"] = snap["sell"] / world - 1
        snap["history_days"] = len(hist)
        out["sjc"] = snap
    except Exception as e:
        out["errors"].append(f"Giá SJC: {e}")

    # Nhật ký dự báo: chấm điểm dự báo cũ, hiệu chỉnh, ghi dự báo mới
    j = journal.load()
    j = journal.evaluate(j, {k: v["close"] for k, v in series.items()})
    for key, a in out["assets"].items():
        for label, hz in a["horizons"].items():
            st = hz["stats"]
            skill = journal.live_skill(j, key, label)
            p_adj, note = journal.calibrate(st["prob_up"], st["base_prob_up"], skill)
            hz["live"] = skill
            hz["prob_up_final"] = p_adj
            hz["calibration_note"] = note
            hz["verdict"], hz["verdict_note"] = analyze.verdict(hz)
            j = journal.record(j, a["last_date"], key, label, hz["days"], p_adj, st["base_prob_up"], a["close"])

    # Quan điểm hằng ngày theo quy tắc cố định; cũng được ghi nhật ký để chấm điểm khi đến hạn
    sh = cfg["stance_horizon"]
    stances = {}
    for key, a in out["assets"].items():
        if key == "GOLD_USD":
            continue  # đã có bản quy đổi VND
        s = analyze.stance(a, sh)
        s["name"] = a["name"]
        stances[key] = s
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
    journal.save(j)

    os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
    with open(os.path.join(ROOT, "output", "analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
    print(f"OK: {len(out['assets'])} tài sản, lỗi: {out['errors']}")
    return 0 if out["assets"] else 1


if __name__ == "__main__":
    sys.exit(main())

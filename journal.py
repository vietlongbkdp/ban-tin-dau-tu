"""Nhật ký dự báo: ghi lại xác suất mỗi ngày, chấm điểm khi đến hạn, đo độ chính xác thực tế.

Đây là cơ chế tự kiểm tra: nếu dự báo thực tế kém hơn tỷ lệ nền, báo cáo sẽ nói rõ
và xác suất ngày hôm sau được kéo về gần tỷ lệ nền (giảm độ tự tin).
"""
import os

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "data", "journal.csv")
COLS = ["pred_date", "asset", "horizon", "days", "prob_up", "base_prob_up", "ref_close",
        "due_close", "realized_ret", "hit", "brier", "brier_base"]
MIN_LIVE = 20


def load():
    if os.path.exists(PATH):
        return pd.read_csv(PATH, dtype={"asset": str})
    return pd.DataFrame(columns=COLS)


def save(j):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    j[COLS].to_csv(PATH, index=False)


def evaluate(j, closes):
    """closes: {asset: Series giá đóng cửa}. Chấm điểm các dự báo đã đến hạn."""
    for i, r in j[j["realized_ret"].isna()].iterrows():
        c = closes.get(r["asset"])
        if c is None:
            continue
        after = c[c.index > pd.Timestamp(r["pred_date"])]
        if len(after) < int(r["days"]):
            continue
        due = float(after.iloc[int(r["days"]) - 1])
        ret = due / float(r["ref_close"]) - 1
        up = 1.0 if ret > 0 else 0.0
        j.loc[i, ["due_close", "realized_ret", "brier", "brier_base"]] = [
            due, ret, (float(r["prob_up"]) - up) ** 2, (float(r["base_prob_up"]) - up) ** 2]
        j.loc[i, "hit"] = None if r["prob_up"] == 0.5 else float((r["prob_up"] > 0.5) == (ret > 0))
    return j


def live_skill(j, asset, horizon):
    done = j[(j["asset"] == asset) & (j["horizon"] == horizon) & j["realized_ret"].notna()]
    if len(done) == 0:
        return {"n": 0}
    bm, bb = done["brier"].mean(), done["brier_base"].mean()
    return {
        "n": int(len(done)),
        "hit_rate": float(done["hit"].dropna().mean()) if done["hit"].notna().any() else None,
        "brier": float(bm),
        "brier_base": float(bb),
        "skill": float(1 - bm / bb) if bb > 0 else None,
    }


def calibrate(prob, base, skill):
    """Chưa đủ MIN_LIVE dự báo đã chấm thì giữ nguyên. Nếu thực tế kém tỷ lệ nền thì giảm một nửa độ lệch."""
    if skill.get("n", 0) < MIN_LIVE or skill.get("skill") is None:
        return prob, "Chưa đủ dữ liệu thực tế để hiệu chỉnh"
    if skill["skill"] < 0:
        return base + (prob - base) * 0.5, "Đã giảm độ tự tin vì dự báo thực tế kém hơn tỷ lệ nền"
    return prob, "Dự báo thực tế tốt hơn tỷ lệ nền, giữ nguyên"


def record(j, pred_date, asset, horizon, days, prob_up, base_prob_up, ref_close):
    j = j[~((j["pred_date"] == pred_date) & (j["asset"] == asset) & (j["horizon"] == horizon))]
    row = {c: None for c in COLS}
    row.update(pred_date=pred_date, asset=asset, horizon=horizon, days=days,
               prob_up=round(prob_up, 4), base_prob_up=round(base_prob_up, 4), ref_close=ref_close)
    return pd.concat([j, pd.DataFrame([row])], ignore_index=True)

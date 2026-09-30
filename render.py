"""Xuất dữ liệu cho trang web: gộp output/analysis.json + output/news.json.

Ghi ra docs/data/latest.json, docs/data/archive/<ngày>.json và docs/data/dates.json.
Giao diện là docs/index.html (tĩnh), tự đọc các file JSON này.
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "docs", "data")


def main():
    an = json.load(open(os.path.join(ROOT, "output", "analysis.json"), encoding="utf-8"))
    news_path = os.path.join(ROOT, "output", "news.json")
    news = json.load(open(news_path, encoding="utf-8")) if os.path.exists(news_path) else {}
    bundle = {"analysis": an, "news": news}
    day = an["generated_at"][:10]
    os.makedirs(os.path.join(DATA, "archive"), exist_ok=True)
    for path in (os.path.join(DATA, "latest.json"), os.path.join(DATA, "archive", f"{day}.json")):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False, separators=(",", ":"))
    dates = sorted((os.path.basename(p)[:-5] for p in glob.glob(os.path.join(DATA, "archive", "*.json"))), reverse=True)
    with open(os.path.join(DATA, "dates.json"), "w", encoding="utf-8") as f:
        json.dump(dates, f)
    print(f"Đã ghi docs/data/latest.json và archive/{day}.json ({len(dates)} ngày lưu trữ)")


if __name__ == "__main__":
    main()

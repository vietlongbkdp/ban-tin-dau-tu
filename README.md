# ban-tin-dau-tu — Bản tin đầu tư tự động

Mỗi sáng 8:30 (giờ VN), một agent Claude trên cloud chạy quy trình trong `AGENT.md`, rồi đăng báo cáo lên GitHub Pages (thư mục `docs/`).

| File | Vai trò |
|---|---|
| `config.json` | Danh sách mã theo dõi và các kỳ hạn |
| `data.py` | Lấy giá: VNDirect/VPS (cổ phiếu VN), Yahoo Finance (vàng, USD/VND), PNJ (vàng SJC) |
| `analyze.py` | Chỉ báo kỹ thuật, trọng số tự hiệu chỉnh, kiểm định walk-forward |
| `journal.py` | Nhật ký dự báo: chấm điểm khi đến hạn, giảm độ tự tin nếu dự báo kém |
| `run.py` | Chạy phần định lượng, ghi ra `output/analysis.json` |
| `render.py` | Dựng `docs/index.html` và bản lưu trữ theo ngày |
| `data/` | Bộ nhớ giữa các ngày (nhật ký, lịch sử giá SJC). Không xoá |

Chạy thủ công: `pip install -r requirements.txt && python run.py && python render.py`

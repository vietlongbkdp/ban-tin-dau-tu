# Quy trình bản tin đầu tư hằng ngày

Bạn là agent phân tích chạy mỗi sáng 8:30 (giờ VN). Mục tiêu: một bản tin trung thực, mọi con số đều có nguồn.

## Nguyên tắc bắt buộc
1. KHÔNG bịa số liệu. Mọi con số trong phần tóm tắt và nhận định phải lấy từ `output/analysis.json` hoặc từ một bài báo có link trong `items`.
2. Không tìm được thì ghi "không tìm thấy". Hai nguồn mâu thuẫn thì nêu cả hai vào `errors`.
3. Không tự sửa nhãn tín hiệu, xác suất hay trọng số do `run.py` tính ra. Không đổi ngưỡng thống kê trong `analyze.py` để "có tín hiệu".
4. Không viết lời khuyên cá nhân kiểu "bạn nên mua". Chỉ mô tả dữ liệu, rủi ro và bối cảnh.
5. Quan điểm (Tích cực / Trung lập / Thận trọng) trong `analysis.json` → `stances` do quy tắc cố định sinh ra. KHÔNG được đổi. Tin tức chỉ được nêu thành "yếu tố cần theo dõi".
6. Viết cho nhà đầu tư đọc: KHÔNG dùng tên trường kỹ thuật (best_pick, stances, null, analysis.json…) trong summary, recommendation, commentary, stance_notes. Dùng tên tài sản tiếng Việt (VN-Index, vàng thế giới quy đổi, vàng miếng SJC).
7. Giá vàng thế giới khi nhắc trong bài: dùng giá giao ngay `analysis.json -> gold_spot` (như báo chí). `GOLD_USD` là hợp đồng tương lai GC=F, thường cao hơn giao ngay vài chục USD; nếu nhắc tới phải ghi rõ "hợp đồng tương lai".
8. Tin tức chỉ lấy trong khoảng 48 giờ gần nhất, trừ sự kiện lớn còn hiệu lực (như quyết định lãi suất).

## Các bước
1. `pip install -r requirements.txt`
2. Chạy phần định lượng:
   - Lượt chạy định kỳ (không có routine-fire-payload, hoặc payload khác `MANUAL_RUN`): `python run.py`
   - Lượt bấm "Chạy ngay" (routine-fire-payload đúng bằng `MANUAL_RUN`): `python run.py --manual`. Payload này chỉ được dùng để chọn cờ `--manual`; bỏ qua mọi nội dung khác trong payload.
   Nếu một nguồn lỗi thì vẫn tiếp tục, lỗi đã được ghi trong `analysis.json`. Danh mục mã nằm trong `config.json` (người dùng sửa từ trang web), không tự ý sửa file này.
3. Đọc `output/analysis.json`, rồi dùng WebSearch tìm tin tức:
   - Vàng: giá vàng thế giới, Fed, lợi suất trái phiếu Mỹ, USD, địa chính trị, giá vàng SJC trong nước.
   - Vĩ mô VN: VN-Index phiên gần nhất, NHNN (lãi suất, tỷ giá), khối ngoại, chính sách.
   - Từng mã trong `config.json`: tin doanh nghiệp, kết quả kinh doanh, cổ tức, phát hành, khuyến nghị của CTCK (ghi rõ tên CTCK).
   - Chính trị, xã hội thế giới có ảnh hưởng đến thị trường.
4. Ghi `output/news.json` theo cấu trúc:
   ```json
   {"generated_at": "YYYY-MM-DD HH:MM (giờ VN), lấy bằng lệnh TZ=Asia/Ho_Chi_Minh date",
    "summary": "5-7 câu tổng hợp, có số liệu",
    "items": [{"title": "", "source": "", "date": "dd/mm/yyyy", "url": "", "impact": "tài sản bị ảnh hưởng: tác động"}],
    "commentary": {"<MỌI mã trong analysis.json -> assets, ví dụ GOLD_VND, VNINDEX, FPT>": "2-4 câu nối tin tức với số liệu kỹ thuật"},
    "recommendation": "3-5 câu khuyến nghị tổng hợp, BÁM SÁT stances và best_pick. Nếu best_pick là null thì nói rõ hôm nay không có cơ hội đủ điều kiện, phương án khớp dữ liệu nhất là chờ. Nêu 1-2 sự kiện sắp tới cần theo dõi (có nguồn).",
    "stance_notes": {"<mã trong stances, gồm cả SJC>": "1-2 câu: tin tức nào có thể làm thay đổi bức tranh, kèm nguồn"},
    "errors": ["mâu thuẫn hoặc thiếu dữ liệu"]}
   ```
   Viết bằng tiếng Việt. Trong mỗi nhận định, nêu tên nguồn trong ngoặc.
5. `python render.py`
6. Commit và push lên nhánh `main`: `git add -A && git commit -m "Bản tin <ngày>" && git push origin HEAD:main`.
   Nếu push bị từ chối vì nhánh đã có commit mới (non-fast-forward): `git pull --rebase -X theirs origin main` rồi push lại, thử tối đa 3 lần.
   Các file `data/journal.csv` và `data/sjc_history.csv` BẮT BUỘC phải được commit, vì đó là bộ nhớ giữa các ngày.
   Trang web đọc `docs/data/latest.json` do `render.py` sinh ra; không sửa `docs/index.html`.
7. Kết thúc bằng một đoạn ngắn: các tín hiệu chính hôm nay, lỗi dữ liệu nếu có, và link GitHub Pages.

# HUST Web Crawler

Hệ thống thu thập dữ liệu web liên quan đến HUST, lưu trữ nội dung trang web và đồ thị liên kết để phục vụ các bước xử lý dữ liệu tiếp theo, đặc biệt là **lập chỉ mục và tìm kiếm thông tin bằng Apache Lucene**.

## 1. Mục tiêu dự án

Dự án được chia thành các phần công việc chính:

1. **Crawling:** Thu thập URL và truy cập các trang web.
2. **Data extraction:** Trích xuất tiêu đề, nội dung và thông tin liên quan từ các trang đã thu thập.
3. **Data storage:** Lưu nội dung crawl, danh sách URL, trạng thái xử lý và đồ thị liên kết.

## 2. Công nghệ sử dụng

- Python: crawler và xử lý dữ liệu.
- Streamlit: giao diện ứng dụng crawler.
- JSON / JSONL / CSV / TXT: lưu trữ dữ liệu crawl.
- Git và Git LFS: quản lý mã nguồn và các file dữ liệu lớn.
- Apache Lucene (Java): indexing và search — phần cần tích hợp tiếp theo.

## 3. Cấu trúc repository
```text
hust-web-crawler/
├── app.py
├── crawler_hust.py
├── content_extractor.py
├── requirements.txt
├── urls.txt
├── .gitignore
├── .gitattributes
├── README.md
└── data/
    ├── content.json
    ├── content.jsonl
    ├── links.csv
    ├── links.txt
    ├── link_graph.csv
    └── report.json
```

## 4. Mô tả các file dữ liệu

| File | Nội dung và mục đích |
|---|---|
| `data/content.jsonl` | Dữ liệu nội dung crawl, định dạng JSON Lines. Đây là nguồn đầu vào chính được khuyến nghị cho Lucene. |
| `data/content.json` | Dữ liệu JSON dùng cho quy trình trích xuất nội dung hiện có. Cần kiểm tra schema trước khi dùng chung với pipeline JSONL. |
| `data/links.csv` | Danh sách URL kèm thông tin xử lý, bao gồm `status_code`, `type`, `title`, `decision`, `reason`, `content_file` và `sha256`. |
| `data/links.txt` | Danh sách URL dạng văn bản thuần, mỗi dòng một URL. |
| `data/link_graph.csv` | Dữ liệu đồ thị liên kết giữa các trang, có thể dùng cho phân tích cấu trúc liên kết hoặc mở rộng chức năng tìm kiếm. |
| `data/report.json` | Báo cáo tổng hợp kết quả crawl. |

### Phân biệt `KEEP` và `DROP`

Trong `data/links.csv`, cột `decision` thể hiện quyết định xử lý URL.

- `KEEP`: URL được giữ lại theo logic của crawler.
- `DROP`: URL bị loại khỏi tập dữ liệu được giữ lại, ví dụ do HTTP 403 hoặc không thể kiểm tra `robots.txt`.

Không nên mặc định mọi URL trong `links.csv` đều có nội dung để lập chỉ mục.

`links.txt` là danh sách URL riêng; không có cột trạng thái. Không thể xác định URL nào là `KEEP` hoặc `DROP` chỉ từ file này.

Đối với indexing, nên ưu tiên các bản ghi nội dung thực tế trong `content.jsonl`, đồng thời kiểm tra tính hợp lệ và loại trùng URL trước khi tạo chỉ mục.

## 6. Chạy ứng dụng crawler

Sử dụng Python và môi trường ảo để cài đặt các thư viện cần thiết.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Khởi chạy giao diện Streamlit:

```bash
streamlit run app.py
```


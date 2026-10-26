# HUST Web Crawler

Hệ thống thu thập dữ liệu web liên quan đến HUST, lưu trữ nội dung trang web và đồ thị liên kết để phục vụ các bước xử lý dữ liệu tiếp theo, đặc biệt là **lập chỉ mục và tìm kiếm thông tin bằng Apache Lucene**.

## 1. Mục tiêu dự án

Dự án được chia thành các phần công việc chính:

1. **Crawling:** Thu thập URL và truy cập các trang web.
2. **Data extraction:** Trích xuất tiêu đề, nội dung và thông tin liên quan từ các trang đã thu thập.
3. **Data storage:** Lưu nội dung crawl, danh sách URL, trạng thái xử lý và đồ thị liên kết.
4. **Indexing (Apache Lucene):** Đọc dữ liệu crawl, chuẩn hóa và tạo chỉ mục tìm kiếm.
5. **Search:** Tìm kiếm trên chỉ mục, trả về kết quả phù hợp gồm tiêu đề, URL và đoạn trích nội dung.

> Lưu ý: Apache Lucene phụ trách indexing và search. Lucene không thay thế crawler và không tự thu thập nội dung từ website.

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

Các file trong `data/` được tạo ra trong quá trình crawl. Một số file runtime và dữ liệu lớn khác không được đưa lên repository.

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

## 5. Tải repository và dữ liệu crawl

### Yêu cầu

Cài đặt Git và Git LFS trước khi tải các file dữ liệu lớn.

### Clone lần đầu

```bash
git lfs install
git clone https://github.com/dinhthuyanh/hust-web-crawler.git
cd hust-web-crawler
git lfs pull
```

### Cập nhật repository đã clone

```bash
git pull origin main
git lfs pull
```

Hai file lớn được quản lý bằng Git LFS:

- `data/content.jsonl`
- `data/link_graph.csv`

Nếu file tải về chỉ chứa nội dung con trỏ LFS thay vì dữ liệu thực, hãy chạy `git lfs pull` và kiểm tra lại.

**Lưu ý:** Việc tải dữ liệu phụ thuộc vào quyền truy cập repository và hạn mức Git LFS hiện có.

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

Ứng dụng crawler có thể được sử dụng độc lập với module indexing và search. Không cần chạy lại crawler chỉ để thử nghiệm Lucene nếu dữ liệu crawl đã có sẵn.

## 7. Hướng dẫn phát triển Apache Lucene

Phần indexing và search nên được phát triển như một module riêng, đọc dữ liệu từ `data/content.jsonl`.

### Pipeline đề xuất

```text
data/content.jsonl
        |
        v
Đọc từng dòng JSON
        |
        v
Kiểm tra dữ liệu và chuẩn hóa văn bản
        |
        v
Loại bản ghi thiếu nội dung / xử lý URL trùng
        |
        v
Apache Lucene Index
        |
        v
Nhận truy vấn tìm kiếm
        |
        v
Xếp hạng kết quả và trả về thông tin
```

### Trường dữ liệu nên lập chỉ mục

| Trường | Mục đích |
|---|---|
| `title` | Tìm kiếm theo tiêu đề |
| `content_text` | Tìm kiếm toàn văn |
| `url` | Hiển thị và truy cập trang nguồn |
| `final_url` | Theo dõi URL sau chuyển hướng |
| `type` | Phân loại dữ liệu nếu cần |

Các trường bổ sung có thể được giữ dưới dạng metadata để phục vụ lọc kết quả hoặc hiển thị.

### Yêu cầu đối với module Lucene

1. Đọc JSONL theo từng dòng, không tải toàn bộ file vào bộ nhớ cùng lúc.
2. Xử lý lỗi JSON hoặc bản ghi không đầy đủ mà không làm dừng toàn bộ quá trình.
3. Chuẩn hóa văn bản và xác định quy tắc loại trùng URL.
4. Tạo chỉ mục bền vững trên ổ đĩa để không phải lập chỉ mục lại mỗi lần tìm kiếm.
5. Hỗ trợ truy vấn theo tiêu đề và nội dung.
6. Trả về tiêu đề, URL, điểm xếp hạng và đoạn trích phù hợp.
7. Có cơ chế cập nhật hoặc xây dựng lại chỉ mục khi dữ liệu crawl thay đổi.

Cần kiểm tra cấu trúc bản ghi JSONL thực tế trước khi triển khai bộ đọc dữ liệu.

## 8. Những dữ liệu không được commit

Một số file và thư mục lớn được giữ cục bộ, không đưa lên repository trong commit dữ liệu hiện tại:

- `data/crawl_state.json`: checkpoint trạng thái crawler.
- `data/downloads/`: các file tải xuống.
- Log và file PID phục vụ runtime.

Nếu cần sử dụng các dữ liệu này, hãy trao đổi với người quản lý crawler để lấy đúng dữ liệu cần thiết. Không nên đưa toàn bộ checkpoint hoặc thư mục tải xuống vào Git chỉ để xây dựng chức năng search.

## 9. Phân chia công việc

| Module | Trách nhiệm |
|---|---|
| Crawler | Thu thập URL và nội dung trang web |
| Data processing | Chuẩn hóa, lọc và kiểm tra dữ liệu đầu vào |
| Apache Lucene indexing | Tạo và quản lý chỉ mục tìm kiếm |
| Search | Xử lý truy vấn, xếp hạng và trả kết quả |
| Integration | Kết nối dữ liệu crawl với module indexing/search |

Các module nên có giao diện đầu vào và đầu ra rõ ràng để có thể phát triển, kiểm thử độc lập.

## 10. Repository

GitHub: https://github.com/dinhthuyanh/hust-web-crawler

**Mục tiêu tiếp theo:** Hoàn thiện module Apache Lucene để biến dữ liệu crawler đã thu thập thành một hệ thống tìm kiếm toàn văn có thể sử dụng và cập nhật được.

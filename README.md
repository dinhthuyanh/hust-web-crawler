# HUST Web Crawler

Hệ thống thu thập dữ liệu web liên quan đến HUST, lưu trữ nội dung trang web và đồ thị liên kết để phục vụ các bước xử lý dữ liệu tiếp theo, đặc biệt là **lập chỉ mục và tìm kiếm thông tin bằng Apache Lucene**.

## 1. Mục tiêu dự án

Dự án được chia thành các phần công việc chính:

1. **Crawling:** Thu thập URL và truy cập các trang web.
2. **Data extraction:** Trích xuất tiêu đề, nội dung và thông tin liên quan từ các trang đã thu thập.
3. **Data storage:** Lưu nội dung crawl, danh sách URL, trạng thái xử lý và đồ thị liên kết.

## 2. Công nghệ sử dụng

- Python: crawler và xử lý dữ liệu.
- HTML / CSS / JavaScript thuần trong `FE/`: giao diện crawler và tìm kiếm.
- Python HTTP server: phục vụ FE, API crawler và proxy Java searcher.
- JSON / JSONL / CSV / TXT: lưu trữ dữ liệu crawl.
- Git và Git LFS: quản lý mã nguồn và các file dữ liệu lớn.
- Apache Lucene (Java): indexing và search — phần cần tích hợp tiếp theo.

## 3. Cấu trúc repository
```text
hust-web-crawler/
├── FE/                      # Toàn bộ HTML / CSS / JS
├── searcher/                # Java API index/search
├── app.py                   # Python gateway / API crawler
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

## 6. Chạy toàn bộ ứng dụng

Cần Python 3.10+, Java 21 và Maven. Không còn dùng Streamlit. Giao diện duy nhất nằm trong `FE/`; Java chỉ cung cấp API.

Từ thư mục gốc, Terminal 1:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Terminal 2:

```bash
cd searcher
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
export PATH="$JAVA_HOME/bin:$PATH"
mvn spring-boot:run
```

Mở **http://127.0.0.1:8000/** để tìm kiếm, hoặc **http://127.0.0.1:8000/crawler.html** để quản lý crawler. Java API chạy ở cổng 8080. Không mở HTML bằng `file://`.

`app.py` dùng thư viện chuẩn Python, không cần dependency để hiển thị FE; các dependency trong `requirements.txt` dùng cho crawler/extractor. Crawler cần được dừng an toàn trước khi cập nhật chỉ mục. Crawler đang chạy sẽ không bị dừng khi đóng gateway.

Java tự rebuild khi khởi động. Lần đầu sau thay đổi này cần rebuild index để nạp JSONL và trường sắp xếp URL mới. Java tự tìm thư mục dự án từ working directory hoặc vị trí class/JAR; chạy từ IntelliJ tại thư mục gốc hoặc từ `searcher` đều dùng `data/` và `searcher/index/`. Có thể ghi đè bằng `DATA_DIR` và `INDEX_DIR`. Không sử dụng các thư mục index cũ bị tạo nhầm ở thư mục gốc.

Gateway bind `127.0.0.1:8000`, Java bind `127.0.0.1:8080`. Đổi cổng FE: `python app.py --port 8001`. Đổi địa chỉ Java upstream bằng `SEARCH_URL=http://127.0.0.1:8081 python app.py`. Đây là công cụ local; không công khai API điều khiển crawler ra Internet.

## 7. Search và top-k

5 mode: `BM25` (từ khóa), `BOOLEAN`, `PHRASE`, `FUZZY`, `PREFIX`; ranking `BM25` hoặc `TFIDF`.

```bash
curl -G http://127.0.0.1:8000/api/search \
  --data-urlencode 'q=tuyen sinh' \
  --data-urlencode 'mode=PHRASE' \
  --data-urlencode 'top_k=25' \
  --data-urlencode 'size=10' \
  --data-urlencode 'page=2'
```

`top_k=25` giữ tối đa 25 kết quả có điểm cao nhất trên toàn bộ index; `size=10` hiển thị 10 kết quả/trang. Trang thứ ba (`page=2`) có tối đa 5 kết quả, dù tổng số tài liệu khớp lớn hơn 25. Các kết quả được sắp theo score giảm dần rồi URL tăng dần khi bằng điểm. Mỗi request dùng snapshot index hiện tại; sau rebuild hãy tìm lại từ trang đầu.

`total` là tổng số tài liệu khớp chính xác; `returned=min(total,top_k)` là kích thước tập kết quả được giữ; `hasNext` chỉ xét các trang trong tập top-k. `top_k` mặc định 100, giới hạn 1–10.000; `size` 1–100. Bản ghi hợp lệ trong JSONL được ưu tiên khi URL trùng với JSON.

Xem [chi tiết API Java](searcher/README.md) và [cấu trúc FE](FE/README.md).

## 8. Kiểm thử

```bash
python3 -m unittest discover -s tests -v
cd searcher
mvn test
```

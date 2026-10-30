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
- Git: chỉ quản lý source code; dữ liệu, index và output được ignore.
- Java 21, Spring Boot 3 và Apache Lucene: lập chỉ mục và tìm kiếm.

## 3. Cấu trúc repository
```text
hust-web-crawler/
├── FE/                      # HTML / CSS / JS thuần
├── searcher/                # Source Java, pom.xml (target/ sinh khi build)
├── input/                   # urls.txt tùy chọn; urls.example.txt làm mẫu
├── data/                    # Nội dung crawl, checkpoint, báo cáo, log/PID
├── index/                   # Lucene index tự sinh
├── output/downloads/        # File tài liệu tải về
├── tests/                   # Test Python
├── app.py                   # Gateway / API crawler / phục vụ FE
├── crawler_hust.py          # Crawl và trích xuất nội dung
├── content_extractor.py     # Công cụ trích xuất riêng (tùy chọn)
└── requirements.txt
```

`data/`, `index/`, `output/` và `input/urls.txt` là dữ liệu local, không commit. Các thư mục đầu ra được tạo khi cần. `.venv/` là môi trường Python, `.idea/` là cấu hình IDE; không xóa khi đang dùng. Không còn index bên trong `searcher/` hoặc thư mục `hust-web-crawler/` lồng nhau.


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

## 6. Chạy từ đầu khi chưa có dữ liệu

Cần Python 3.10+, Java 21, Maven. Mở các terminal tại thư mục gốc repository. Không cần Node.js, Streamlit, Git LFS hay database.

### Bước 1 — Cài thư viện Python (một lần)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp input/urls.example.txt input/urls.txt
```

Có thể sửa `input/urls.txt`, mỗi dòng một URL trong domain `hust.edu.vn` hoặc `www.hust.edu.vn`. Nếu không có file, crawler mặc định bắt đầu từ `https://hust.edu.vn/`. Khi có `data/crawl_state.json`, crawler tiếp tục checkpoint cũ thay vì đọc lại seed.

### Bước 2 — Chạy giao diện/gateway (Terminal 1)

```bash
.venv/bin/python app.py
```

Mở http://127.0.0.1:8000/crawler.html, bấm **Bắt đầu**. Gateway tự chạy crawler bằng Python trong `.venv`. Không chạy thêm `crawler_hust.py` cùng lúc. Chờ crawl hoàn tất hoặc bấm **Dừng an toàn**, chờ trạng thái đã dừng để crawler ghi xong dữ liệu. Crawl toàn bộ website có thể kéo dài; có thể dừng để thử tìm kiếm trước.

Crawler tự tạo `data/content.jsonl`, `data/crawl_state.json`, danh sách liên kết và báo cáo; tài liệu tải về nằm ở `output/downloads/`. Chỉ tài liệu có nội dung văn bản hợp lệ mới được index. Không bắt buộc chạy riêng `content_extractor.py` vì crawler đã trích xuất nội dung.

Nếu muốn crawl bằng terminal thay cho nút trên giao diện:

```bash
.venv/bin/python crawler_hust.py
```

Dùng Ctrl+C một lần rồi đợi lưu checkpoint/đầu ra xong.

### Bước 3 — Chạy Java (Terminal 2)

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
export PATH="$JAVA_HOME/bin:$PATH"
mvn -f searcher/pom.xml spring-boot:run
```

Maven cần Internet lần đầu để tải dependency. Java chạy ở http://127.0.0.1:8080 và tự index dữ liệu hiện có vào `index/` ở root. Nếu chưa có dữ liệu, Java vẫn khởi động và trả 0 kết quả; có thể chạy Java trước bước crawl.

Trong IntelliJ: chọn JDK 21, chạy `vn.edu.hust.searcher.SearcherApplication`. Xóa override `INDEX_DIR` / `DATA_DIR` và các tham số `--searcher.index-dir` / `--searcher.data-dir` cũ để dùng mặc định tự nhận diện root.

### Bước 4 — Tìm kiếm

Mở http://127.0.0.1:8000/, nhập từ khóa và chọn mode. Nếu Java đã chạy trước lúc crawl xong, bấm **Cập nhật chỉ mục**, hoặc:

```bash
curl -X POST http://127.0.0.1:8000/api/index/rebuild
```

Chỉ rebuild sau khi crawler đã dừng và ghi xong dữ liệu. Kiểm tra số tài liệu:

```bash
curl http://127.0.0.1:8000/api/index
```

Lần chạy sau chỉ cần chạy gateway và Java; chỉ chạy crawler khi cần thu thập thêm. Để crawl lại hoàn toàn, dừng crawler và Java rồi chuyển `data/`, `index/`, `output/` cũ sang nơi lưu trữ khác trước khi làm lại các bước trên. Không cần xóa source hoặc môi trường `.venv`.

Gateway bind `127.0.0.1:8000`, Java bind `127.0.0.1:8080`. Đổi cổng FE bằng `python app.py --port 8001`, đổi Java upstream bằng `SEARCH_URL=http://127.0.0.1:8081 python app.py`. Đóng gateway không tự dừng crawler; dùng nút dừng trước khi đóng nếu cần.

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

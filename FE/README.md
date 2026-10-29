# HUST FE

Frontend HTML + CSS + JavaScript thuần, không framework, CDN hoặc bước build.

- `index.html`, `search.js`: tìm kiếm Lucene, chọn mode/ranking/top-k, phân trang và rebuild index.
- `crawler.html`, `crawler.js`: điều khiển crawler, thống kê, tiến độ, biểu đồ HTML/CSS, lọc URL, phân trang và xuất CSV.
- `styles.css`: giao diện chung, responsive.

## Chạy

Từ thư mục gốc: `python3 app.py`, mở http://127.0.0.1:8000/. Chạy Java searcher ở một terminal khác (`cd searcher && mvn spring-boot:run`, dùng Java 21). Không cần Node.js, Streamlit hoặc mở frontend trên cổng khác.

## API cùng origin

| API | Mục đích |
|---|---|
| `GET /api/crawler/status` | Trạng thái tiến trình, thống kê, các loại URL |
| `POST /api/crawler/start` | Khởi chạy crawler, từ chối nếu đã chạy |
| `POST /api/crawler/stop` | Gửi SIGINT để crawler lưu checkpoint |
| `GET /api/crawler/links?q=&decision=&type=&page=0&size=25` | Lọc và phân trang URL |
| `GET /api/crawler/export?q=&decision=&type=` | Tải toàn bộ URL theo bộ lọc dưới dạng CSV |
| `GET /api/search?q=...&mode=BM25&ranking=BM25&top_k=100&page=0&size=10` | Proxy tìm kiếm Java |
| `GET /api/index` | Proxy trạng thái index |
| `POST /api/index/rebuild` | Proxy rebuild index |

`top_k` giới hạn tổng số kết quả tốt nhất; `size` là số kết quả mỗi trang trong tập top-k. FE dùng `hasNext` từ backend, không dùng tổng số match để mở trang ngoài top-k. Đổi bộ lọc search rồi bấm tìm để bắt đầu từ trang đầu; phân trang giữ nguyên truy vấn đã gửi.

Dashboard đọc các file báo cáo do crawler xuất, tự làm mới mỗi 10 giây khi tab hiển thị. Giao diện hiển thị dữ liệu chưa tin cậy bằng textContent; chỉ tạo liên kết HTTP/HTTPS. CSV export thêm dấu nháy trước các giá trị có thể bị spreadsheet hiểu thành công thức.

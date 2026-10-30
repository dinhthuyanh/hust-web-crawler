# HUST Searcher

Module độc lập Java 21 + Spring Boot 3.5.16 + Apache Lucene 9.12.2. Không cần database hoặc Elasticsearch. module chỉ đọc dữ liệu nguồn và ghi Lucene index vào `index/` ở root.

## Chạy trên macOS

Cần JDK 21 và Maven 3.6.3+. Mở terminal:

```bash
cd "/Users/khanhpd2002/Desktop/khanhpd/ThS-HUST/BTL/hust-web-crawler/searcher"
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
export PATH="$JAVA_HOME/bin:$PATH"
java -version
mvn test
mvn spring-boot:run
```

Lần đầu Maven cần Internet để tải dependency. Java API mặc định nghe tại `http://localhost:8080`, chỉ bind loopback; giao diện nằm trong `../FE` và được phục vụ bởi `python app.py` tại cổng 8000. Tự lập lại chỉ mục khi khởi động nếu có dữ liệu; nếu chưa có nguồn thì giữ index hiện tại (index rỗng trong lần chạy đầu). Nhấn Ctrl+C để dừng.

Hoặc đóng gói:

```bash
mvn clean package
java -jar target/searcher-1.0.0.jar
```

Ứng dụng tự tìm thư mục dự án từ working directory hoặc vị trí class/JAR. Có thể ghi đè đường dẫn khi cần:

```bash
DATA_DIR=/absolute/path/to/data INDEX_DIR=/absolute/path/to/index java -jar /absolute/path/to/searcher-1.0.0.jar
```

Biến môi trường: `DATA_DIR` (mặc định `auto` → `<project>/data`), `INDEX_DIR` (`auto` → `<project>/index`), `PORT` (`8080`), `INDEX_ON_STARTUP` (`true`). Chỉ chạy một instance trên cùng thư mục index.

## Đầu vào và lập chỉ mục

Đọc lần lượt `content.jsonl` (mỗi dòng một object) và `content.json` (mảng object):

| Trường index | Crawler JSONL | Extractor JSON |
|---|---|---|
| URL | `url` | `url`, dự phòng `source_url` |
| Nội dung | `content_text` | `content` |
| Tiêu đề | `title` | `title` |
| Loại | `type` | `document_type` |

- Bỏ bản ghi thiếu URL/nội dung, `decision` khác `KEEP` hoặc `status` khác `success` khi có các trường này.
- Loại trùng theo chuỗi URL; bản ghi hợp lệ đầu tiên thắng, ưu tiên JSONL. Chưa hợp nhất URL canonical/redirect hoặc loại trùng theo nội dung.
- Không lập chỉ mục `links.csv`, ảnh hoặc file tải về chưa trích xuất: cần crawler/extractor tạo văn bản trước.
- Nội dung gốc được lưu để trả kết quả. Analyzer chia từ bằng StandardTokenizer, chuyển chữ thường và bỏ dấu tiếng Việt, gồm `đ → d`. Đây là token hóa theo từ cách nhau, chưa phải bộ tách từ tiếng Việt chuyên biệt.
- Tiêu đề có trọng số 3, nội dung 1.
- Rebuild thay thế toàn bộ index, xóa bản ghi không còn trong nguồn. JSON lỗi làm rollback để giữ snapshot cũ; thiếu cả hai nguồn cũng không xóa index cũ. Dữ liệu lỗi khi khởi động với auto-index bật sẽ khiến ứng dụng không khởi động thành công.
- File được đọc tuần tự; vẫn giữ tập URL trong RAM để loại trùng. Indexing và tìm kiếm được đồng bộ bằng lock, nên request search chờ nếu đang rebuild.
- Nên dừng crawler trước rebuild vì crawler ghi đè JSONL trực tiếp. Không tự theo dõi thay đổi dữ liệu; gọi API rebuild sau khi crawl xong.
- Hai chương trình Python đang dùng schema khác nhau cho cùng file `link_graph.csv`; module này không sử dụng file đó.

## API

### Xem trạng thái

```bash
curl http://localhost:8080/api/index
```

### Lập lại chỉ mục

```bash
curl -X POST http://localhost:8080/api/index/rebuild
```

Trả về `documents`, `skipped`, `sources`.

### Tìm kiếm

```bash
curl -G http://localhost:8080/api/search \
  --data-urlencode 'q=tuyen sinh' \
  --data-urlencode 'mode=BM25' \
  --data-urlencode 'ranking=BM25' \
  --data-urlencode 'page=0' \
  --data-urlencode 'size=10'
```

| `mode` | Hành vi | Ví dụ `q` |
|---|---|---|
| `BM25` | Từ khóa văn bản thường, mặc định OR giữa các từ | `tuyển sinh` |
| `BOOLEAN` | Cú pháp Lucene: AND, OR, NOT, ngoặc, trường, phrase | `tuyen AND sinh NOT "sau dai hoc"` |
| `PHRASE` | Cụm từ đúng thứ tự, liền nhau sau chuẩn hóa | `đại học bách khoa` |
| `FUZZY` | Cho phép lệch tối đa 1 ký tự mỗi token, tất cả token phải khớp trong cùng trường | `tuyem sinh` |
| `PREFIX` | Mỗi token là tiền tố, tất cả phải khớp trong cùng trường | `tuy sin` |

`ranking=BM25` (mặc định) hoặc `ranking=TFIDF` (Lucene ClassicSimilarity). `mode` chọn cách khớp, `ranking` chọn tính điểm; có thể dùng `mode=PHRASE&ranking=TFIDF`. Prefix dùng cơ chế rewrite của Lucene nên điểm không nhất thiết thay đổi khi đổi ranking.

Ví dụ Boolean và so sánh TF-IDF:

```bash
curl -G http://localhost:8080/api/search \
  --data-urlencode 'q=title:(bach AND khoa) OR content:"tuyen sinh"' \
  --data-urlencode 'mode=BOOLEAN' \
  --data-urlencode 'ranking=TFIDF'
```

Kết quả gồm `query`, `mode`, `ranking`, `total`, `totalRelation`, `page`, `size`, `topK`, `returned`, `hasNext`, `hits`. Mỗi hit có `url`, `title`, `type`, `score`, `snippet` (300 ký tự đầu nội dung, chưa highlight). `total` được đếm chính xác (`totalRelation=EQUAL_TO`). `top_k` mặc định 100, từ 1 đến 10.000; `returned=min(total,top_k)`. Trang cuối chỉ trả phần còn lại trong top-k. Kết quả theo score giảm dần, URL tăng dần nếu bằng điểm. Sau cập nhật này cần rebuild để tạo trường URL docvalues.

Trang bắt đầu từ 0; size 1–100; cửa sổ `(page + 1) * size` tối đa 10.000; q tối đa 500 ký tự và 32 token. Tên mode/ranking viết HOA. Query/cấu hình tham số sai trả HTTP 400. Lỗi đọc dữ liệu/index trả HTTP 500. Cú pháp BOOLEAN không hỗ trợ wildcard ở đầu từ.

## Kiểm thử

```bash
mvn test
```

Test dùng index tạm: hai schema dữ liệu, loại trùng, lọc trạng thái, tiếng Việt có/không dấu, 5 kiểu truy vấn, 2 cách xếp hạng, phân trang, validation, rebuild xóa dữ liệu cũ và rollback khi nguồn lỗi.

## Tài liệu

- [Spring Boot 3.5 – yêu cầu hệ thống](https://docs.spring.io/spring-boot/3.5/system-requirements.html)
- [Apache Lucene 9.12.2](https://lucene.apache.org/core/9_12_2/)

## Giao diện tìm kiếm

Toàn bộ giao diện đã chuyển ra `../FE/` (HTML/CSS/JS thuần); không còn static HTML trong Java. Chạy `python app.py` từ thư mục gốc rồi mở **http://127.0.0.1:8000/**. Gateway chuyển `/api/search`, `/api/index` và `/api/index/rebuild` sang Java; không cần CORS hoặc Node.js. Trang quản lý crawler nằm tại `/crawler.html`.

## Chạy / Debug trong IntelliJ

Chạy main class `vn.edu.hust.searcher.SearcherApplication`, dùng JDK 21. Working directory có thể là thư mục gốc `hust-web-crawler` hoặc module `searcher`; mặc định `auto` xác định cùng một thư mục dữ liệu và index ở cả hai trường hợp. Sau khi cập nhật source, bấm Build → Rebuild Project rồi Run/Debug lại.

Nếu Run Configuration còn khai báo `DATA_DIR=../data` hoặc `--searcher.data-dir=../data`, bỏ cấu hình cũ để dùng tự nhận diện hoặc đặt đường dẫn tuyệt đối. Đường dẫn tự khai báo luôn được tính theo working directory. Khi mang riêng JAR ra ngoài repo, khai báo cả `DATA_DIR` và `INDEX_DIR` thành đường dẫn tuyệt đối.

Quy trình từ dữ liệu rỗng: xem [README gốc](../README.md#6-chạy-từ-đầu-khi-chưa-có-dữ-liệu). Crawl xong mới rebuild; Java có thể khởi động trước crawler.

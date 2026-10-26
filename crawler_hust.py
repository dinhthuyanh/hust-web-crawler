
"""Crawler công khai cho hust.edu.vn: khám phá URL, phân loại, lọc và trích xuất nội dung."""
from __future__ import annotations
import csv, hashlib, json, os, re, signal, time, xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None
try:
    from docx import Document
except Exception:
    Document = None
try:
    from pptx import Presentation
except Exception:
    Presentation = None

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DOWNLOAD_DIR = DATA_DIR / "downloads"
SEED_FILE = BASE_DIR / "urls.txt"
LINKS_TXT = DATA_DIR / "links.txt"
LINKS_CSV = DATA_DIR / "links.csv"
GRAPH_CSV = DATA_DIR / "link_graph.csv"
GRAPH_TXT = DATA_DIR / "link_graph.txt"
CONTENT_JSONL = DATA_DIR / "content.jsonl"
STATE_FILE = DATA_DIR / "crawl_state.json"
REPORT_FILE = DATA_DIR / "report.json"

ALLOWED_HOSTS = {"hust.edu.vn", "www.hust.edu.vn"}
USER_AGENT = "HUST-Public-Research-Crawler/1.0 (academic project; public pages only)"
REQUEST_DELAY_SECONDS = 0   # giữ mức lịch sự; tăng nếu website phản hồi chậm
TIMEOUT_SECONDS = (5, 15)  # (thời gian kết nối, thời gian chờ dữ liệu)
MAX_PAGES_PER_RUN = None      # đặt None để chạy hết hàng đợi đã phát hiện
MAX_BYTES_PER_FILE = 25 * 1024 * 1024
MAX_SITEMAP_DEPTH = 5
ALLOWED_DOC_EXTS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".txt", ".rtf", ".odt", ".ods", ".xls", ".xlsx", ".csv"}
SKIP_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".mp3", ".mp4", ".avi", ".zip", ".rar", ".7z", ".exe", ".dmg", ".css", ".js", ".woff", ".woff2", ".ttf"}
SKIP_PATH_PARTS = ("/login", "/dang-nhap", "/logout", "/wp-admin", "/account", "/register", "/dang-ky-tai-khoan")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation,*/*;q=0.7"})
# Thử lại có giới hạn với lỗi kết nối/lỗi máy chủ; không lặp vô hạn.
retry = Retry(
    total=2, connect=2, read=1, status=1,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    respect_retry_after_header=True,
)
adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)
ROBOTS: dict[str, RobotFileParser | None] = {}
STOP_REQUESTED = False


def request_stop(signum, frame) -> None:
    """Ctrl+C chỉ yêu cầu dừng; không ngắt ngang lúc đang ghi checkpoint."""
    global STOP_REQUESTED
    if not STOP_REQUESTED:
        STOP_REQUESTED = True
        print("\nĐã nhận Ctrl+C. Sẽ dừng sau tác vụ hiện tại và lưu checkpoint...", flush=True)


def normalize_url(url: str, base: str | None = None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if base:
        url = urljoin(base, url)
    p = urlparse(url)
    if p.scheme.lower() not in ("http", "https") or not p.netloc:
        return None
    host = (p.hostname or "").lower().rstrip(".")
    # Hạn chế trong tên miền HUST và các subdomain của HUST.
    if not (host == "hust.edu.vn" or host.endswith(".hust.edu.vn")):
        return None
    if p.username or p.password:
        return None
    path = re.sub(r"/{2,}", "/", p.path or "/")
    # Bỏ tham số tracking nhưng giữ tham số còn lại vì có thể là URL nội dung.
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}]
    netloc = host
    if p.port and not ((p.scheme == "http" and p.port == 80) or (p.scheme == "https" and p.port == 443)):
        netloc += f":{p.port}"
    return urlunparse((p.scheme.lower(), netloc, path, "", urlencode(query, doseq=True), ""))


def is_publicly_allowed(url: str) -> bool:
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    if origin not in ROBOTS:
        rp = RobotFileParser()
        robots_url = origin + "/robots.txt"
        try:
            r = SESSION.get(robots_url, timeout=TIMEOUT_SECONDS, allow_redirects=True)
            if r.status_code < 400:
                rp.parse(r.text.splitlines())
                ROBOTS[origin] = rp
            else:
                # Nếu robots.txt không tồn tại, tiếp tục theo quy tắc chung của website.
                ROBOTS[origin] = None
        except requests.RequestException:
            # Không thể kiểm tra robots.txt: thận trọng, bỏ qua URL này.
            ROBOTS[origin] = False  # type: ignore[assignment]
    rp = ROBOTS[origin]
    if rp is False:
        return False
    if rp is None:
        return True
    return rp.can_fetch(USER_AGENT, url)


def get_state() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            state.setdefault("queue", [])
            state.setdefault("queued", [])
            state.setdefault("visited", {})
            state.setdefault("records", {})
            state.setdefault("sitemaps_seen", [])
            return state
        except (json.JSONDecodeError, OSError):
            print("Cảnh báo: không đọc được tiến độ cũ; tạo tiến độ mới.")
    seeds = []
    if SEED_FILE.exists():
        for line in SEED_FILE.read_text(encoding="utf-8").splitlines():
            u = normalize_url(line)
            if u:
                seeds.append(u)
    if not seeds:
        seeds = ["https://hust.edu.vn/"]
    return {"queue": list(dict.fromkeys(seeds)), "queued": list(dict.fromkeys(seeds)),
            "visited": {}, "records": {}, "sitemaps_seen": []}


def save_state(state: dict) -> None:
    """Ghi checkpoint gọn vào file tạm rồi thay thế nguyên tử."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    state_to_save = dict(state)
    state_to_save["queue"] = list(state.get("queue", []))
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state_to_save, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(STATE_FILE)


def parse_sitemap_xml(text: str) -> tuple[list[str], list[str]]:
    urls, maps = [], []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return urls, maps
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower()
        if tag == "loc" and el.text:
            loc = el.text.strip()
            # Determine whether this <loc> belongs to a sitemap or URL entry.
            parent_tag = ""
            # Simpler classification: sitemap-index entries usually end in sitemap XML.
            if loc.lower().endswith((".xml", ".xml.gz")) or "sitemap" in loc.lower():
                maps.append(loc)
            else:
                urls.append(loc)
    return urls, maps


def discover_sitemaps(state: dict) -> None:
    candidates = ["https://hust.edu.vn/robots.txt", "https://hust.edu.vn/sitemap.xml"]
    found = []
    for u in candidates:
        if STOP_REQUESTED:
            break
        try:
            r = SESSION.get(u, timeout=TIMEOUT_SECONDS)
            if r.status_code >= 400:
                continue
            if u.endswith("robots.txt"):
                for line in r.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        found.append(line.split(":", 1)[1].strip())
            else:
                found.append(u)
        except requests.RequestException:
            continue
    q = deque((u, 0) for u in dict.fromkeys(found))
    seen = set(state.get("sitemaps_seen", []))
    while q and not STOP_REQUESTED:
        sm_url, depth = q.popleft()
        sm_url = normalize_url(sm_url)
        if not sm_url or sm_url in seen or depth > MAX_SITEMAP_DEPTH:
            continue
        seen.add(sm_url)
        try:
            r = SESSION.get(sm_url, timeout=TIMEOUT_SECONDS)
            if r.status_code >= 400 or len(r.content) > MAX_BYTES_PER_FILE:
                continue
            urls, maps = parse_sitemap_xml(r.text)
            for raw in urls:
                u = normalize_url(raw)
                if u and u not in state["queued"] and u not in state["visited"]:
                    state["queue"].append(u); state["queued"].append(u)
            for raw in maps:
                sm = normalize_url(raw)
                if sm and sm not in seen:
                    q.append((sm, depth + 1))
        except requests.RequestException:
            pass
    state["sitemaps_seen"] = sorted(seen)
    save_state(state)


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_html(response: requests.Response) -> tuple[str, str, list[dict[str, str]], str]:
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    # Thu thập liên kết TRƯỚC khi bỏ menu/header/footer để không mất link điều hướng.
    links: list[dict[str, str]] = []
    for a in soup.find_all("a", href=True):
        u = normalize_url(a.get("href", ""), response.url)
        if u:
            links.append({
                "source_url": response.url,
                "target_url": u,
                "anchor_text": clean_text(a.get_text(" ", strip=True)) or a.get("title", "").strip(),
            })
    # Chỉ trích xuất phần nội dung chính; loại bỏ phần giao diện.
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    for tag in soup.find_all(["nav", "header", "footer", "aside"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.find(id=re.compile(r"content|main", re.I)) or soup.body or soup
    text = clean_text(main.get_text("\n", strip=True))
    canonical = soup.find("link", rel=lambda x: x and "canonical" in x)
    canonical_url = normalize_url(canonical.get("href", ""), response.url) if canonical else response.url
    # Deduplicate link dictionaries using their scalar fields (dicts are unhashable).
    unique_links = []
    seen_links = set()
    for link in links:
        key = (link["source_url"], link["target_url"], link["anchor_text"])
        if key not in seen_links:
            seen_links.add(key)
            unique_links.append(link)
    return title, text, unique_links, canonical_url or response.url


def extract_document(content: bytes, ext: str) -> tuple[str, str]:
    title, text = "", ""
    temp = DATA_DIR / ("temp_document" + ext)
    temp.write_bytes(content)
    try:
        if ext == ".pdf" and PdfReader:
            reader = PdfReader(str(temp))
            title = str(reader.metadata.title or "") if reader.metadata else ""
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        elif ext == ".docx" and Document:
            doc = Document(str(temp))
            text = "\n".join(p.text for p in doc.paragraphs)
            title = next((p.text for p in doc.paragraphs if p.text.strip()), "")
            for table in doc.tables:
                text += "\n" + "\n".join(" | ".join(c.text.strip() for c in row.cells) for row in table.rows)
        elif ext == ".pptx" and Presentation:
            prs = Presentation(str(temp))
            chunks = []
            for i, slide in enumerate(prs.slides, 1):
                vals = [sh.text for sh in slide.shapes if getattr(sh, "has_text_frame", False) and sh.text.strip()]
                if vals:
                    chunks.append(f"Slide {i}: " + "\n".join(vals))
            text = "\n\n".join(chunks)
            title = text.splitlines()[0] if text else ""
        elif ext in {".txt", ".csv", ".rtf"}:
            text = content.decode("utf-8", errors="replace")
            title = text.splitlines()[0][:200] if text else ""
        else:
            # .doc/.ppt/.xls/.xlsx/ODF được ghi nhận và tải về; bộ trích xuất cần thư viện phù hợp.
            text = ""
    finally:
        try: temp.unlink(missing_ok=True)
        except OSError: pass
    return clean_text(title), clean_text(text)


def is_login_or_private(response: requests.Response, text: str) -> bool:
    url = response.url.lower()
    if any(part in url for part in SKIP_PATH_PARTS):
        return True
    sample = text[:8000].lower()
    login_signals = ["name=\"password\"", "type=\"password\"", "đăng nhập để xem", "please log in", "sign in to continue"]
    return any(s in sample for s in login_signals)


def classify(url: str, content_type: str) -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    ctype = content_type.lower()
    if ext in ALLOWED_DOC_EXTS or any(x in ctype for x in ("application/pdf", "officedocument", "msword", "ms-powerpoint", "ms-excel")):
        return "document"
    if "text/html" in ctype or not ctype:
        return "html"
    if "text/plain" in ctype:
        return "text"
    return "other"


def write_outputs(state: dict) -> None:
    records = list(state.get("records", {}).values())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LINKS_TXT.open("w", encoding="utf-8") as f:
        for row in sorted(records, key=lambda x: x.get("url", "")):
            if row.get("decision") == "KEEP":
                f.write(row.get("url", "") + "\n")
    fields = ["url", "final_url", "status_code", "type", "title", "decision", "reason", "content_file", "sha256"]
    with LINKS_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(sorted(records, key=lambda x: x.get("url", "")))
    # Đồ thị liên kết: mỗi dòng là một cạnh source -> target kèm văn bản liên kết.
    edges_by_key = {}
    for row in records:
        for edge in row.get("outgoing_links", []):
            key = (edge.get("source_url", ""), edge.get("target_url", ""), edge.get("anchor_text", ""))
            edges_by_key[key] = {"source_url": key[0], "target_url": key[1], "anchor_text": key[2]}
    with GRAPH_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["source_url", "target_url", "anchor_text"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(edges_by_key.values(), key=lambda e: (e["source_url"], e["target_url"])))
    with GRAPH_TXT.open("w", encoding="utf-8") as f:
        for edge in sorted(edges_by_key.values(), key=lambda e: (e["source_url"], e["target_url"])):
            f.write(f'{edge["source_url"]} -> {edge["target_url"]} : {edge["anchor_text"]}\n')
    with CONTENT_JSONL.open("w", encoding="utf-8") as f:
        for row in sorted(records, key=lambda x: x.get("url", "")):
            if row.get("decision") == "KEEP" and row.get("content_text"):
                f.write(json.dumps({k: row.get(k) for k in ("url", "final_url", "type", "title", "content_text", "sha256")}, ensure_ascii=False) + "\n")
    report = {"seed_urls": len(state.get("queued", [])), "processed_urls": len(state.get("visited", {})),
              "kept": sum(1 for x in records if x.get("decision") == "KEEP"),
              "discarded": sum(1 for x in records if x.get("decision") == "DROP"),
              "pending_urls": len(state.get("queue", [])), "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def process_url(url: str, state: dict) -> None:
    if not is_publicly_allowed(url):
        state["visited"][url] = "robots_or_private"
        state["records"][url] = {"url": url, "final_url": url, "status_code": "", "type": "", "title": "", "decision": "DROP", "reason": "Disallowed by robots.txt or robots.txt could not be checked", "content_file": "", "sha256": ""}
        return
    try:
        response = SESSION.get(url, timeout=TIMEOUT_SECONDS, allow_redirects=True, stream=True)
        status = response.status_code
        final_url = normalize_url(response.url)
        if not final_url:
            response.close(); state["visited"][url] = "external_redirect"
            state["records"][url] = {"url": url, "final_url": response.url, "status_code": status, "type": "", "title": "", "decision": "DROP", "reason": "Redirect outside allowed domain", "content_file": "", "sha256": ""}
            return
        if status < 200 or status >= 400:
            response.close(); state["visited"][url] = f"http_{status}"
            state["records"][url] = {"url": url, "final_url": final_url, "status_code": status, "type": "", "title": "", "decision": "DROP", "reason": f"HTTP status {status}", "content_file": "", "sha256": ""}
            return
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_BYTES_PER_FILE:
            response.close(); state["visited"][url] = "too_large"
            state["records"][url] = {"url": url, "final_url": final_url, "status_code": status, "type": "", "title": "", "decision": "DROP", "reason": "File exceeds size limit", "content_file": "", "sha256": ""}
            return
        content_type = response.headers.get("Content-Type", "")
        kind = classify(final_url, content_type)
        chunks, total = [], 0
        for chunk in response.iter_content(65536):
            if not chunk: continue
            total += len(chunk)
            if total > MAX_BYTES_PER_FILE:
                raise ValueError("Nội dung vượt giới hạn kích thước")
            chunks.append(chunk)
        response.close()
        body = b"".join(chunks)
        digest = hashlib.sha256(body).hexdigest()
        title, text, discovered, canonical_url = "", "", [], final_url
        if kind == "html":
            # Reuse response metadata and parse downloaded bytes; no second HTTP request.
            response._content = body
            response.encoding = response.encoding or "utf-8"
            title, text, discovered, canonical_url = extract_html(response)
            if is_login_or_private(response, text):
                decision, reason = "DROP", "Login/private page detected"
            elif not text:
                decision, reason = "DROP", "No meaningful text extracted"
            else:
                decision, reason = "KEEP", "Public HTML page with text"
        elif kind == "document":
            ext = Path(urlparse(final_url).path).suffix.lower()
            title, text = extract_document(body, ext)
            DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            name = hashlib.sha1(final_url.encode("utf-8")).hexdigest()[:16] + (ext or ".bin")
            (DOWNLOAD_DIR / name).write_bytes(body)
            discovered = []
            if text:
                decision, reason = "KEEP", "Public document downloaded and text extracted"
            else:
                decision, reason = "KEEP", "Public document downloaded; extractor for this format is not enabled"
        elif kind == "text":
            text = clean_text(body.decode("utf-8", errors="replace")); title = text.splitlines()[0][:200] if text else ""
            decision, reason = ("KEEP", "Public text content") if text else ("DROP", "Empty text")
        else:
            decision, reason = "DROP", f"Unsupported content type: {content_type or 'unknown'}"
        # Only follow links discovered on public HTML pages.
        for edge in discovered:
            link = edge["target_url"]
            if link not in state["queued"] and link not in state["visited"]:
                state["queue"].append(link); state["queued"].append(link)
        record = {"url": url, "final_url": canonical_url, "status_code": status, "type": kind,
                  "title": title, "decision": decision, "reason": reason,
                  "content_file": "data/content.jsonl" if text else "", "sha256": digest,
                  "content_text": text,
                  "outgoing_links": discovered if kind == "html" else []}
        state["records"][url] = record
        state["visited"][url] = status
        print(f"[{len(state['visited'])}] {decision} | {kind} | {status} | {url}")
    except (requests.RequestException, ValueError, OSError, Exception) as exc:
        state["visited"][url] = "error"
        state["records"][url] = {"url": url, "final_url": url, "status_code": "", "type": "", "title": "", "decision": "DROP", "reason": f"Error: {type(exc).__name__}: {exc}", "content_file": "", "sha256": ""}
        print(f"[LOI] {url} — {type(exc).__name__}: {exc}")
    finally:
        time.sleep(REQUEST_DELAY_SECONDS)


def main() -> None:
    global STOP_REQUESTED
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = get_state()
    # SIGINT (Ctrl+C) chỉ đặt cờ; chương trình dừng có kiểm soát và không cắt ngang lúc ghi file.
    signal.signal(signal.SIGINT, request_stop)

    print("Crawler công khai HUST — HTML và tài liệu được hỗ trợ")
    print(f"URL chờ ban đầu: {len(state['queue'])}; đã xử lý: {len(state['visited'])}")
    state["queue"] = deque(state.get("queue", []))
    processed_this_run = 0

    try:
        # Bao cả bước sitemap trong try để luôn lưu checkpoint nếu có lỗi/dừng.
        if not STOP_REQUESTED:
            discover_sitemaps(state)
        print(f"Sau khi đọc sitemap: còn {len(state['queue'])} URL trong hàng đợi")

        while state["queue"] and not STOP_REQUESTED and (
            MAX_PAGES_PER_RUN is None or processed_this_run < MAX_PAGES_PER_RUN
        ):
            url = state["queue"].popleft()
            if url in state["visited"]:
                continue

            process_url(url, state)
            processed_this_run += 1

            if processed_this_run % 10 == 0:
                save_state(state)
            if processed_this_run % 100 == 0:
                write_outputs(state)
                print(
                    f"Tiến độ: xử lý {processed_this_run} URL lượt này; "
                    f"còn {len(state['queue'])} URL"
                )

    except Exception as exc:
        print(f"Lỗi không mong muốn: {type(exc).__name__}: {exc}")
        raise
    finally:
        # Cờ dừng không ngắt đoạn này; lưu checkpoint trước, rồi mới xuất các báo cáo.
        print("Đang lưu checkpoint...")
        try:
            save_state(state)
            print(f"Đã lưu checkpoint: {STATE_FILE}")
        except Exception as exc:
            print(f"LỖI khi lưu checkpoint: {type(exc).__name__}: {exc}")
        try:
            write_outputs(state)
            print("Đã cập nhật các file đầu ra.")
        except Exception as exc:
            print(f"LỖI khi ghi file đầu ra: {type(exc).__name__}: {exc}")

    print("\n=== KẾT QUẢ ===")
    print(f"Đã xử lý: {len(state['visited'])}")
    print(f"Còn trong hàng đợi: {len(state['queue'])}")
    print(f"Danh sách link: {LINKS_TXT}")
    print(f"CSV: {LINKS_CSV}")
    print(f"Đồ thị liên kết CSV: {GRAPH_CSV}")
    print(f"Đồ thị liên kết dạng văn bản: {GRAPH_TXT}")
    print(f"Nội dung trích xuất: {CONTENT_JSONL}")
    print(f"Báo cáo: {REPORT_FILE}")
    if STOP_REQUESTED:
        print("Crawler đã dừng an toàn. Chạy lại lệnh cũ để tiếp tục từ checkpoint.")

if __name__ == "__main__":
    main()

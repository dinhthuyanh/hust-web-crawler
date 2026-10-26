
from __future__ import annotations

import csv
import json
import logging
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urldefrag

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag


# ============================================================
# CAU HINH
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DOWNLOAD_DIR = DATA_DIR / "downloads"

CONTENT_FILE = DATA_DIR / "content.json"
LINK_GRAPH_FILE = DATA_DIR / "link_graph.csv"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "HUSTDiscovery/1.0 (public-content research crawler)"
REQUEST_TIMEOUT = 25
MAX_FILE_SIZE = 30 * 1024 * 1024

HEADERS = {
    "User-Agent": USER_AGENT,
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("content_extractor")


# ============================================================
# HAM TIEN ICH
# ============================================================

def now_iso() -> str:
    """Thoi diem xu ly theo UTC."""
    return datetime.now(timezone.utc).isoformat()


def clean_text(text: str | None) -> str:
    """Chuan hoa khoang trang, dong va ky tu xuong dong."""
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def normalize_url(url: str) -> str:
    """Bo fragment (#...) va khoang trang thua."""
    url = (url or "").strip()

    if not url:
        return ""

    return urldefrag(url)[0]


def safe_filename(name: str) -> str:
    """Tao ten file an toan."""
    name = Path(name).name
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    return name[:180] or "downloaded_file"


def is_http_url(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))


def load_existing_content() -> list[dict[str, Any]]:
    """Doc du lieu da co, khong ghi de mat du lieu cu."""
    if not CONTENT_FILE.exists():
        return []

    try:
        with CONTENT_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, list) else []

    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Khong doc duoc content.json: %s", exc)
        return []


def save_content(
    record: dict[str, Any],
    output_file: Path = CONTENT_FILE,
) -> None:
    """Luu ban ghi, cap nhat neu URL da ton tai."""
    output_file.parent.mkdir(parents=True, exist_ok=True)

    records = load_existing_content() if output_file == CONTENT_FILE else []

    source_url = record.get("url", "")
    replaced = False

    for i, old_record in enumerate(records):
        if old_record.get("url") == source_url and source_url:
            records[i] = record
            replaced = True
            break

    if not replaced:
        records.append(record)

    with output_file.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def append_link_graph(
    source_url: str,
    links: list[dict[str, str]],
) -> None:
    """Ghi do thi lien ket source-target-anchor."""
    LINK_GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_exists = (
        LINK_GRAPH_FILE.exists()
        and LINK_GRAPH_FILE.stat().st_size > 0
    )

    with LINK_GRAPH_FILE.open(
        "a",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["source", "target", "anchor_text", "rel"],
        )

        if not file_exists:
            writer.writeheader()

        for link in links:
            writer.writerow({
                "source": source_url,
                "target": link.get("url", ""),
                "anchor_text": link.get("anchor_text", ""),
                "rel": link.get("rel", ""),
            })


# ============================================================
# TRICH XUAT HTML
# ============================================================

def extract_html_metadata(
    soup: BeautifulSoup,
) -> dict[str, str]:
    """Trich xuat tieu de, tac gia va ngay dang."""
    title = ""

    if soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))

    if not title:
        h1 = soup.find("h1")
        if h1:
            title = clean_text(h1.get_text(" ", strip=True))

    author = ""
    date_published = ""

    author_selectors = [
        ("name", "author"),
        ("property", "article:author"),
        ("name", "article:author"),
        ("name", "byl"),
    ]

    for attr, value in author_selectors:
        node = soup.find("meta", attrs={attr: value})
        if node and node.get("content"):
            author = clean_text(node["content"])
            break

    date_selectors = [
        ("property", "article:published_time"),
        ("name", "date"),
        ("name", "publishdate"),
        ("name", "pubdate"),
        ("name", "datePublished"),
        ("itemprop", "datePublished"),
    ]

    for attr, value in date_selectors:
        node = soup.find("meta", attrs={attr: value})

        if node and node.get("content"):
            date_published = clean_text(node["content"])
            break

    if not date_published:
        node = soup.find("time")
        if node:
            date_published = clean_text(
                node.get("datetime") or node.get_text(" ", strip=True)
            )

    description = ""
    description_node = soup.find(
        "meta",
        attrs={"name": "description"},
    )

    if description_node:
        description = clean_text(
            description_node.get("content", "")
        )

    return {
        "title": title,
        "author": author,
        "date_published": date_published,
        "description": description,
    }


def extract_links(
    soup: BeautifulSoup,
    page_url: str,
) -> list[dict[str, str]]:
    """Lay lien ket voi URL dich va anchor text."""
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()

        if not href:
            continue

        target = normalize_url(urljoin(page_url, href))

        if not is_http_url(target):
            continue

        anchor_text = clean_text(a.get_text(" ", strip=True))

        # Neu anchor rong, thu lay mo ta tu aria-label/title.
        if not anchor_text:
            anchor_text = clean_text(
                a.get("aria-label") or a.get("title") or ""
            )

        rel_value = a.get("rel", [])
        if isinstance(rel_value, list):
            rel = " ".join(str(item) for item in rel_value)
        else:
            rel = str(rel_value)

        key = (target, anchor_text)

        if key in seen:
            continue

        seen.add(key)
        links.append({
            "url": target,
            "anchor_text": anchor_text,
            "rel": rel,
        })

    return links


def extract_images(
    soup: BeautifulSoup,
    page_url: str,
) -> list[dict[str, str]]:
    """Ghi nhan anh va trang nguon chua anh."""
    images: list[dict[str, str]] = []
    seen: set[str] = set()

    for img in soup.select("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-original")
            or ""
        ).strip()

        if not src:
            continue

        image_url = normalize_url(urljoin(page_url, src))

        if not is_http_url(image_url) or image_url in seen:
            continue

        seen.add(image_url)

        images.append({
            "image_url": image_url,
            "source_url": page_url,
            "alt": clean_text(img.get("alt", "")),
            "title": clean_text(img.get("title", "")),
        })

    return images


def extract_main_text_with_trafilatura(
    html: str,
    page_url: str,
) -> str:
    """Uu tien Trafilatura; neu loi thi tra chuoi rong."""
    try:
        import trafilatura

        result = trafilatura.extract(
            html,
            url=page_url,
            include_comments=False,
            include_tables=True,
            include_links=False,
            favor_precision=True,
            output_format="txt",
        )

        return clean_text(result or "")

    except Exception as exc:
        logger.warning(
            "Trafilatura khong trich xuat duoc %s: %s",
            page_url,
            exc,
        )
        return ""


def extract_main_text_fallback(
    soup: BeautifulSoup,
) -> str:
    """Phuong an du phong khi Trafilatura khong kha dung."""
    # Xoa cac thanh phan thuong khong phai noi dung chinh.
    for tag in soup.select(
        "script, style, noscript, iframe, svg, "
        "nav, footer, header, aside, form, button"
    ):
        tag.decompose()

    # Thu tim vung noi dung chinh.
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.body
        or soup
    )

    parts: list[str] = []

    for element in main.find_all(
        ["h1", "h2", "h3", "h4", "p", "li", "td", "th", "blockquote"]
    ):
        text = clean_text(element.get_text(" ", strip=True))

        if text and text not in parts:
            parts.append(text)

    result = "\n\n".join(parts)

    # Du phong cuoi: lay toan bo van ban.
    if not result:
        result = clean_text(main.get_text("\n", strip=True))

    return result


def extract_html(url: str) -> dict[str, Any]:
    """
    Tai va boc tach mot trang HTML cong khai.

    Tra ve metadata, noi dung, lien ket va hinh anh.
    """
    url = normalize_url(url)

    record: dict[str, Any] = {
        "url": url,
        "source_url": url,
        "content_type": "text/html",
        "document_type": "html",
        "title": "",
        "author": "",
        "date_published": "",
        "description": "",
        "content": "",
        "links": [],
        "images": [],
        "status": "error",
        "error": "",
        "extracted_at": now_iso(),
    }

    if not is_http_url(url):
        record["error"] = "URL khong hop le: chi chap nhan HTTP/HTTPS."
        return record

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
        response.raise_for_status()

        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_FILE_SIZE:
            record["error"] = "Trang vuot qua gioi han dung luong."
            return record

        content_type = response.headers.get("Content-Type", "")
        record["content_type"] = content_type
        record["final_url"] = response.url
        record["http_status"] = response.status_code

        # Chi xu ly HTML trong ham nay.
        if "html" not in content_type.lower():
            record["status"] = "unsupported"
            record["error"] = (
                "URL khong tra ve HTML. "
                "Hay dung extract_document() cho tep tai ve."
            )
            return record

        chunks: list[bytes] = []
        total_bytes = 0

        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue

            total_bytes += len(chunk)

            if total_bytes > MAX_FILE_SIZE:
                record["error"] = (
                    "Noi dung HTML vuot qua gioi han dung luong."
                )
                return record

            chunks.append(chunk)

        raw_bytes = b"".join(chunks)

        # requests tu nhan dien encoding khi doc response.text.
        html = response.encoding and raw_bytes.decode(
            response.encoding, errors="replace"
        ) or raw_bytes.decode("utf-8", errors="replace")

        final_url = response.url
        soup = BeautifulSoup(html, "html.parser")

        metadata = extract_html_metadata(soup)
        links = extract_links(soup, final_url)
        images = extract_images(soup, final_url)

        content = extract_main_text_with_trafilatura(
            html,
            final_url,
        )

        extraction_method = "trafilatura"

        if len(content) < 80:
            fallback_soup = BeautifulSoup(html, "html.parser")
            fallback_content = extract_main_text_fallback(
                fallback_soup
            )

            if len(fallback_content) > len(content):
                content = fallback_content
                extraction_method = "beautifulsoup_fallback"

        record.update(metadata)
        record.update({
            "url": final_url,
            "source_url": final_url,
            "content": content,
            "links": links,
            "images": images,
            "extraction_method": extraction_method,
            "status": "success" if content else "empty_content",
            "error": (
                "" if content
                else "Khong trich xuat duoc noi dung van ban."
            ),
        })

        # Ghi do thi lien ket.
        append_link_graph(final_url, links)

        # Luu ban ghi.
        save_content(record)

        return record

    except requests.RequestException as exc:
        record["error"] = f"Loi tai trang: {exc}"
        return record

    except Exception as exc:
        logger.exception("Loi extract_html(%s)", url)
        record["error"] = f"Loi xu ly HTML: {exc}"
        return record


# ============================================================
# TAI TEP VA TRICH XUAT TAI LIEU
# ============================================================

def download_file(url: str) -> dict[str, Any]:
    """Tai tep cong khai ve data/downloads."""
    url = normalize_url(url)

    result: dict[str, Any] = {
        "url": url,
        "status": "error",
        "file_path": "",
        "content_type": "",
        "error": "",
    }

    if not is_http_url(url):
        result["error"] = "URL khong hop le."
        return result

    try:
        with requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            stream=True,
        ) as response:
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            result["content_type"] = content_type
            result["final_url"] = response.url

            # Lay ten tep tu URL, bo query string.
            path_name = Path(
                response.url.split("?", 1)[0]
            ).name

            filename = safe_filename(path_name or "downloaded_file")

            # Neu URL khong co phan mo rong, thu suy ra tu MIME type.
            if not Path(filename).suffix:
                guessed_ext = mimetypes.guess_extension(
                    content_type.split(";", 1)[0].strip()
                )
                if guessed_ext:
                    filename += guessed_ext

            destination = DOWNLOAD_DIR / filename

            # Tranh ghi de tep da ton tai.
            if destination.exists():
                stem = destination.stem
                suffix = destination.suffix
                destination = DOWNLOAD_DIR / (
                    f"{stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    f"{suffix}"
                )

            total = 0

            with destination.open("wb") as f:
                for chunk in response.iter_content(
                    chunk_size=64 * 1024
                ):
                    if not chunk:
                        continue

                    total += len(chunk)

                    if total > MAX_FILE_SIZE:
                        f.close()
                        destination.unlink(missing_ok=True)
                        result["error"] = (
                            "Tep vuot qua gioi han 30 MB."
                        )
                        return result

                    f.write(chunk)

            result.update({
                "status": "success",
                "file_path": str(destination),
                "size_bytes": total,
            })

            return result

    except requests.RequestException as exc:
        result["error"] = f"Loi tai tep: {exc}"
        return result

    except OSError as exc:
        result["error"] = f"Loi ghi tep: {exc}"
        return result


def extract_pdf(file_path: Path) -> str:
    """Trich xuat PDF bang PyMuPDF, fallback sang pypdf."""
    try:
        import fitz

        text_parts: list[str] = []

        with fitz.open(str(file_path)) as document:
            for page in document:
                text_parts.append(page.get_text("text"))

        return clean_text("\n\n".join(text_parts))

    except ImportError:
        pass

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        return clean_text(
            "\n\n".join(page.extract_text() or "" for page in reader.pages)
        )

    except ImportError as exc:
        raise RuntimeError(
            "Can cai pymupdf hoac pypdf de doc PDF."
        ) from exc


def extract_docx(file_path: Path) -> str:
    """Trich xuat van ban va bang trong DOCX."""
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError(
            "Can cai python-docx de doc DOCX."
        ) from exc

    document = Document(str(file_path))
    parts: list[str] = []

    for paragraph in document.paragraphs:
        text = clean_text(paragraph.text)
        if text:
            parts.append(text)

    for table in document.tables:
        for row in table.rows:
            cells = [
                clean_text(cell.text)
                for cell in row.cells
            ]
            if any(cells):
                parts.append(" | ".join(cells))

    return clean_text("\n\n".join(parts))


def extract_text_file(file_path: Path) -> str:
    """Doc TXT va cac tep van ban don gian."""
    for encoding in ("utf-8", "utf-8-sig", "cp1258", "latin-1"):
        try:
            return clean_text(
                file_path.read_text(encoding=encoding)
            )
        except UnicodeDecodeError:
            continue

    return ""


def extract_csv_file(file_path: Path) -> str:
    """Chuyen noi dung CSV thanh van ban de tim kiem."""
    rows: list[str] = []

    with file_path.open(
        "r",
        encoding="utf-8-sig",
        errors="replace",
        newline="",
    ) as f:
        reader = csv.reader(f)

        for row in reader:
            cleaned = [clean_text(cell) for cell in row]

            if any(cleaned):
                rows.append(" | ".join(cleaned))

    return clean_text("\n".join(rows))


def extract_document(
    file_path: str | Path,
    source_url: str = "",
) -> dict[str, Any]:
    """
    Trich xuat tai lieu da co tren may.

    Ho tro PDF, DOCX, TXT, CSV, HTML.
    DOC cu va cac dinh dang khac can bo sung thu vien rieng.
    """
    path = Path(file_path).expanduser().resolve()

    record: dict[str, Any] = {
        "url": source_url or path.as_uri(),
        "source_url": source_url,
        "file_name": path.name,
        "content_type": mimetypes.guess_type(path.name)[0] or "",
        "document_type": path.suffix.lower().lstrip("."),
        "title": path.stem,
        "author": "",
        "date_published": "",
        "description": "",
        "content": "",
        "links": [],
        "images": [],
        "status": "error",
        "error": "",
        "extracted_at": now_iso(),
    }

    try:
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Khong tim thay tep: {path}")

        if path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError("Tep vuot qua gioi han 30 MB.")

        suffix = path.suffix.lower()

        if suffix == ".pdf":
            content = extract_pdf(path)

        elif suffix == ".docx":
            content = extract_docx(path)

        elif suffix in {".txt", ".md", ".log", ".html", ".htm"}:
            content = extract_text_file(path)

            if suffix in {".html", ".htm"}:
                soup = BeautifulSoup(content, "html.parser")
                metadata = extract_html_metadata(soup)
                record.update(metadata)
                content = extract_main_text_with_trafilatura(
                    content, source_url or path.as_uri()
                ) or extract_main_text_fallback(soup)

        elif suffix == ".csv":
            content = extract_csv_file(path)

        else:
            raise ValueError(
                f"Chua ho tro dinh dang {suffix or '(khong co duoi tep)'}. "
                "Hien ho tro PDF, DOCX, TXT, MD, HTML va CSV."
            )

        record["content"] = content
        record["status"] = "success" if content else "empty_content"

        if not content:
            record["error"] = (
                "Khong trich xuat duoc van ban. "
                "PDF scan co the can OCR."
            )

        save_content(record)
        return record

    except Exception as exc:
        record["error"] = str(exc)
        logger.exception("Loi extract_document(%s)", path)
        return record


# ============================================================
# API TONG HOP: TU URL DEN NOI DUNG
# ============================================================

def extract_url(url: str) -> dict[str, Any]:
    """
    Tu dong phan loai URL:
    - HTML: trich xuat truc tiep.
    - Tep tai ve: tai xuong roi trich xuat theo dinh dang.
    """
    url = normalize_url(url)

    if not is_http_url(url):
        return {
            "url": url,
            "status": "error",
            "error": "Chi chap nhan URL HTTP/HTTPS.",
        }

    try:
        # Lay headers de nhan biet HTML hay tep tai ve.
        with requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            stream=True,
        ) as response:
            response.raise_for_status()

            content_type = response.headers.get(
                "Content-Type", ""
            ).lower()

            final_url = response.url
            first_chunk = next(
                response.iter_content(chunk_size=1),
                b"",
            )

        # Neu la HTML, dung ham chuyen biet.
        if "html" in content_type or not content_type:
            return extract_html(final_url)

        # Neu la tep, tai xuong va trich xuat.
        downloaded = download_file(final_url)

        if downloaded["status"] != "success":
            return {
                "url": final_url,
                "status": "error",
                "error": downloaded.get("error", "Tai tep that bai."),
            }

        return extract_document(
            downloaded["file_path"],
            source_url=final_url,
        )

    except requests.RequestException as exc:
        return {
            "url": url,
            "status": "error",
            "error": f"Loi truy cap URL: {exc}",
        }


def extract_urls(urls: list[str]) -> list[dict[str, Any]]:
    """Xu ly nhieu URL lan luot va tra ve ket qua."""
    results: list[dict[str, Any]] = []

    for url in urls:
        url = url.strip()

        if not url:
            continue

        logger.info("Dang boc tach: %s", url)
        results.append(extract_url(url))

    return results


# ============================================================
# CHAY THU DOC LAP
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="HUST Discovery - Content Extractor"
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="URL cong khai can boc tach",
    )
    parser.add_argument(
        "--file",
        dest="file_path",
        help="Duong dan tep PDF/DOCX/TXT/CSV can boc tach",
    )

    args = parser.parse_args()

    if args.file_path:
        result = extract_document(args.file_path)
    elif args.url:
        result = extract_url(args.url)
    else:
        parser.error("Hay cung cap URL hoac --file.")

    print(json.dumps(result, ensure_ascii=False, indent=2))

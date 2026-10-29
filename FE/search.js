'use strict';
const $ = (id) => document.getElementById(id);
const help = {
  BM25: 'Tìm các từ khóa trong tiêu đề và nội dung. Kết quả có thể khớp một hoặc nhiều từ.',
  BOOLEAN: 'Kết hợp AND, OR, NOT (viết hoa), dấu ngoặc hoặc tên trường. Ví dụ: title:(bach AND khoa) OR content:"tuyen sinh".',
  PHRASE: 'Tìm các từ liền nhau, đúng thứ tự. Ví dụ: đại học bách khoa. Không cần thêm dấu ngoặc kép.',
  FUZZY: 'Tìm gần đúng, cho phép sai 1 ký tự mỗi từ. Ví dụ: tuyem sinh. Các từ phải cùng khớp trong tiêu đề hoặc nội dung.',
  PREFIX: 'Tìm theo phần đầu mỗi từ. Ví dụ: tuy sin. Không cần thêm dấu *. Các từ phải cùng khớp trong một trường.'
};
let activeRequest = null;
let lastSearch = null;
let currentPage = 0;
let searching = false;
let rebuilding = false;

function message(text, error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
  $('message').hidden = !text;
}
async function request(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.message || `Yêu cầu thất bại (${response.status}).`);
  return data;
}
function buttons() {
  $('search-button').disabled = rebuilding;
  $('search-button').textContent = searching ? 'Đang tìm…' : 'Tìm kiếm ↗';
  $('rebuild').disabled = rebuilding || searching;
  $('rebuild').textContent = rebuilding ? 'Đang cập nhật…' : 'Cập nhật chỉ mục';
  $('previous').disabled = searching || rebuilding || currentPage === 0;
  $('next').disabled = searching || rebuilding || $('next').dataset.available !== 'true';
  $('results').setAttribute('aria-busy', String(searching));
}
function safeLink(value) {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}
function render(data) {
  $('results').replaceChildren();
  $('results-section').hidden = false;
  const lowerBound = data.totalRelation === 'GREATER_THAN_OR_EQUAL_TO';
  $('results-meta').textContent = `${lowerBound ? 'Ít nhất ' : ''}${data.total.toLocaleString('vi-VN')} khớp · Giữ ${data.returned} / top-${data.topK} · ${data.mode} · ${data.ranking}`;
  if (!data.hits.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = data.page === 0 ? 'Chưa tìm thấy kết quả. Thử từ khóa ngắn hơn hoặc chuyển sang chế độ Từ khóa / Gần đúng.' : 'Trang này không có kết quả. Hãy quay lại trang trước.';
    $('results').append(empty);
  }
  for (const hit of data.hits) {
    const card = $('hit-template').content.cloneNode(true);
    const link = card.querySelector('a');
    link.textContent = hit.title || '(Không có tiêu đề)';
    const href = safeLink(hit.url);
    if (href) link.href = href;
    card.querySelector('.hit-url').textContent = hit.url;
    card.querySelector('.hit-type').textContent = hit.type || 'Tài liệu';
    card.querySelector('.hit-score').textContent = `Điểm ${Number(hit.score).toFixed(3)}`;
    card.querySelector('.hit-snippet').textContent = hit.snippet || '';
    $('results').append(card);
  }
  currentPage = data.page;
  $('pagination').hidden = data.total === 0;
  $('page-label').textContent = `Trang ${data.page + 1}`;
  $('next').dataset.available = String(data.hasNext);
}
async function search(params, page = 0) {
  if (rebuilding) return;
  activeRequest?.abort();
  const controller = new AbortController();
  activeRequest = controller;
  searching = true;
  message('');
  buttons();
  try {
    const query = new URLSearchParams({...params, page});
    const data = await request(`/api/search?${query}`, {signal: controller.signal});
    if (activeRequest !== controller) return;
    lastSearch = {...params};
    render(data);
  } catch (error) {
    if (error.name !== 'AbortError' && activeRequest === controller) {
      // Hide old results so a failed query cannot be mistaken for a successful search.
      $('results-section').hidden = true;
      message(`Không thể tìm kiếm: ${error.message}`, true);
    }
  } finally {
    if (activeRequest === controller) { searching = false; buttons(); }
  }
}
async function status() {
  try {
    const data = await request('/api/index');
    $('index-status').textContent = `${data.documents.toLocaleString('vi-VN')} tài liệu sẵn sàng tra cứu`;
  } catch {
    $('index-status').textContent = 'Không đọc được trạng thái chỉ mục. Kiểm tra ứng dụng Java và thử tải lại trang.';
  }
}
$('mode').addEventListener('change', () => { $('mode-help').textContent = help[$('mode').value]; });
$('mode-help').textContent = help[$('mode').value];
$('search-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const q = $('query').value.trim();
  if (!q) { message('Nhập từ khóa để bắt đầu tìm kiếm.', true); $('query').focus(); return; }
  search({q, mode: $('mode').value, ranking: $('ranking').value, size: $('size').value, top_k: $('top-k').value});
});
document.querySelectorAll('.example').forEach((button) => button.addEventListener('click', () => {
  $('query').value = button.dataset.query;
  $('search-form').requestSubmit();
}));
$('previous').addEventListener('click', () => { if (lastSearch && currentPage > 0) search(lastSearch, currentPage - 1); });
$('next').addEventListener('click', () => { if (lastSearch && $('next').dataset.available === 'true') search(lastSearch, currentPage + 1); });
$('rebuild').addEventListener('click', async () => {
  rebuilding = true;
  buttons();
  message('Đang cập nhật chỉ mục. Vui lòng chờ…');
  try {
    const data = await request('/api/index/rebuild', {method: 'POST'});
    $('results-section').hidden = true;
    lastSearch = null;
    currentPage = 0;
    message(`Đã cập nhật ${data.documents.toLocaleString('vi-VN')} tài liệu; bỏ qua ${data.skipped.toLocaleString('vi-VN')} bản ghi không hợp lệ hoặc trùng lặp. Hãy tìm lại để xem dữ liệu mới.`);
    await status();
  } catch (error) { message(`Cập nhật thất bại: ${error.message}`, true); }
  finally { rebuilding = false; buttons(); }
});
status();

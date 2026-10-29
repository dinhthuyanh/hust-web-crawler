'use strict';
const el = (id) => document.getElementById(id);
const number = (value) => Number(value || 0).toLocaleString('vi-VN');
let page = 0;
let filters = {q: '', decision: '', type: ''};
let refreshing = false;
let controlling = false;
let stopping = false;
let running = false;
let linksRequest = null;
let total = 0;
async function api(path, method = 'GET', signal) {
  const response = await fetch(path, {method, signal});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Không thực hiện được yêu cầu.');
  return data;
}
function message(text, error = false) {
  el('crawler-message').hidden = !text;
  el('crawler-message').textContent = text;
  el('crawler-message').className = error ? 'notice error' : 'notice';
}
function controls() {
  el('start').disabled = controlling || running;
  el('stop').disabled = controlling || !running || stopping;
  el('stop').textContent = stopping && running ? 'Đang chờ lưu tiến độ…' : 'Dừng an toàn';
}
function chart(id, values) {
  const root = el(id);
  root.replaceChildren();
  const sorted = Object.entries(values).sort((a,b) => b[1] - a[1]).slice(0,8);
  const max = Math.max(1, ...sorted.map((item) => item[1]));
  for (const [label, count] of sorted) {
    const row = document.createElement('div'); row.className = 'bar-row';
    const text = document.createElement('span'); text.textContent = `${label} · ${number(count)}`;
    const bar = document.createElement('span'); bar.className = 'bar'; bar.style.width = `${Math.max(1, count / max * 100)}%`;
    row.append(text, bar); root.append(row);
  }
  if (!sorted.length) root.textContent = 'Chưa có dữ liệu.';
}
async function links() {
  linksRequest?.abort();
  const controller = new AbortController(); linksRequest = controller;
  const query = new URLSearchParams({...filters, page, size: 25});
  el('links-previous').disabled = true; el('links-next').disabled = true;
  el('export').href = `/api/crawler/export?${new URLSearchParams(filters)}`;
  try {
    const data = await api(`/api/crawler/links?${query}`, 'GET', controller.signal);
    if (linksRequest !== controller) return;
    total = data.total;
    el('links-body').replaceChildren();
    for (const item of data.rows) {
      const row = document.createElement('tr');
      for (const field of ['url', 'status_code', 'type', 'title', 'decision', 'reason']) {
        const cell = document.createElement('td');
        if (field === 'url') {
          const a = document.createElement('a'); a.textContent = item.url || '';
          try { const url = new URL(item.url); if (['http:', 'https:'].includes(url.protocol)) { a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; } } catch { /* Display invalid URLs as text. */ }
          cell.append(a);
        } else cell.textContent = item[field] || '—';
        row.append(cell);
      }
      el('links-body').append(row);
    }
    el('links-meta').textContent = `${number(data.total)} URL phù hợp${data.total === 0 ? ' · Chưa có dữ liệu hoặc không khớp bộ lọc' : ''}`;
    el('links-page').textContent = `Trang ${page + 1}`;
    el('links-previous').disabled = page === 0;
    el('links-next').disabled = (page + 1) * 25 >= total;
  } catch (error) { if (error.name !== 'AbortError') message(error.message, true); }
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const data = await api('/api/crawler/status');
    running = data.running;
    if (!running && stopping) { stopping = false; message('Crawler đã dừng. Tiến độ đã được crawler lưu.'); }
    el('crawler-status').textContent = running ? `Đang chạy · PID ${data.pid}` : 'Crawler đang dừng';
    el('updated-at').textContent = data.updatedAt ? `Cập nhật dữ liệu: ${data.updatedAt}` : 'Chưa có báo cáo crawl';
    for (const key of ['processed', 'kept', 'pending', 'dropped']) el(key).textContent = number(data[key]);
    const sum = Number(data.processed) + Number(data.pending);
    const progress = sum ? Math.min(1, data.processed / sum) : 0;
    el('progress').value = progress;
    el('progress-label').textContent = `${(progress * 100).toFixed(1)}% · ${number(data.processed)} / ${number(sum)} URL`;
    chart('decisions-chart', data.decisions); chart('statuses-chart', data.statuses);
    const current = el('type').value;
    el('type').replaceChildren(new Option('Tất cả', ''), ...data.types.map((type) => new Option(type, type)));
    el('type').value = current;
    controls();
    await links();
  } catch (error) { message(error.message, true); }
  finally { refreshing = false; }
}
async function control(action) {
  controlling = true; controls(); message('');
  try {
    const data = await api(`/api/crawler/${action}`, 'POST');
    stopping = action === 'stop'; message(data.message);
    await refresh();
  } catch (error) { message(error.message, true); }
  finally { controlling = false; controls(); }
}
el('start').addEventListener('click', () => control('start'));
el('stop').addEventListener('click', () => control('stop'));
el('refresh').addEventListener('click', refresh);
el('filter-form').addEventListener('submit', (event) => {
  event.preventDefault(); page = 0;
  filters = {q: el('filter-query').value.trim(), decision: el('decision').value, type: el('type').value}; links();
});
el('links-previous').addEventListener('click', () => { if (page > 0) { page--; links(); } });
el('links-next').addEventListener('click', () => { if ((page + 1) * 25 < total) { page++; links(); } });
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 10000);

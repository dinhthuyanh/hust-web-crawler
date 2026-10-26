from __future__ import annotations
import json, os, re, signal, subprocess, time
from pathlib import Path
import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
CRAWLER = BASE / 'crawler_hust.py'
PYTHON = BASE / '.venv' / 'bin' / 'python'
if not PYTHON.exists():
    # Fallback cho môi trường đã kích hoạt Python/venv nhưng không có đường dẫn .venv chuẩn.
    import sys
    PYTHON = Path(sys.executable)
LINKS, REPORT, CONTENT = DATA/'links.csv', DATA/'report.json', DATA/'content.jsonl'
LOG, PID = DATA/'crawler_app.log', DATA/'crawler_app.pid'
GRAPH, STATE = DATA/'link_graph.csv', DATA/'crawl_state.json'
st.set_page_config(page_title='HUST Discovery', page_icon='⌕', layout='wide')
st.markdown('''<style>
.block-container{max-width:1500px;padding-top:1.25rem;padding-bottom:2rem}
[data-testid="stSidebar"]{background:#f7f9fc;border-right:1px solid #e5eaf2}
.hero{padding:.9rem 1.2rem;border:1px solid #e2e8f0;border-radius:18px;background:linear-gradient(110deg,#f4f7ff,#fff 68%,#f4f7ff);margin-bottom:.7rem}
.eyebrow{color:#2456c6;font-size:.75rem;font-weight:800;letter-spacing:.14em}
.hero h1{color:#17233b;font-size:2rem;letter-spacing:-.035em;margin:.25rem 0}
.hero p{color:#64748b;margin:0}
.kpi{border:1px solid #e5eaf2;border-radius:13px;padding:.75rem;background:#fff;min-height:88px}
.klabel{font-size:.82rem;color:#64748b}.kvalue{font-size:1.5rem;font-weight:800;color:#17233b}.knote{font-size:.75rem;color:#8a94a6}
.stButton button,.stDownloadButton button{border-radius:10px;font-weight:650}
</style>''', unsafe_allow_html=True)
DATA.mkdir(parents=True, exist_ok=True)

def signature(p):
    if not p.exists(): return (0,0)
    s=p.stat(); return s.st_mtime_ns,s.st_size

def clean_url(v):
    v=str(v or '').strip(); m=re.fullmatch(r'\[(.*?)\]\((https?://.*?)\)',v)
    return m.group(2) if m else v

@st.cache_data(show_spinner=False)
def load_links(mtime,size):
    if not LINKS.exists(): return pd.DataFrame()
    d=pd.read_csv(LINKS,dtype=str,keep_default_na=False,encoding='utf-8-sig',low_memory=False)
    for c in ['url','final_url','status_code','type','title','decision','reason','content_file','downloaded_file','sha256']:
        if c not in d: d[c]=''
    d['url_view']=d.url.map(clean_url); d['final_view']=d.final_url.map(clean_url)
    return d

@st.cache_data(show_spinner=False)
def load_report(mtime,size):
    try: return json.loads(REPORT.read_text(encoding='utf-8')) if REPORT.exists() else {}
    except (OSError,json.JSONDecodeError): return {}

def get_pid():
    try:
        p=int(PID.read_text().strip()); os.kill(p,0)
        r=subprocess.run(['ps','-p',str(p),'-o','command='],capture_output=True,text=True,timeout=1)
        return p if r.returncode==0 and 'crawler_hust.py' in r.stdout else None
    except (OSError,ValueError,subprocess.SubprocessError): return None

def lines_count(path):
    if not path.exists(): return 0
    with path.open('rb') as f: return sum(1 for _ in f)

def search_jsonl(term,limit):
    out=[]; term=term.casefold().strip()
    if not term or not CONTENT.exists(): return out
    seen=set()
    try:
        with CONTENT.open(encoding='utf-8') as f:
            for line in f:
                try: x=json.loads(line)
                except json.JSONDecodeError: continue
                title=str(x.get('title','')); body=str(x.get('content_text','')); url=clean_url(x.get('url',''))
                key=url or (title, body[:120])
                if key in seen: continue
                text=f'{title}\n{body}\n{url}'; folded=text.casefold(); pos=folded.find(term)
                if pos<0: continue
                seen.add(key)
                # Ưu tiên ngữ cảnh quanh vị trí khớp, nhưng giữ tiêu đề riêng để dễ đọc.
                a=max(0,pos-90); b=min(len(text),pos+len(term)+180)
                excerpt=('…' if a else '')+text[a:b]+('…' if b<len(text) else '')
                out.append({'Tiêu đề':title or '(Không có tiêu đề)','Loại':x.get('type',''),'URL':url,'Trích đoạn':excerpt})
                if len(out)>=limit: break
    except OSError as exc:
        st.error(f'Không đọc được content.jsonl: {exc}')
    return out


def nfmt(n):
    try:return f'{int(n):,}'.replace(',','.')
    except (TypeError,ValueError):return '—'

links=load_links(*signature(LINKS)) if LINKS.exists() else pd.DataFrame()
report=load_report(*signature(REPORT))
pid=get_pid(); running=pid is not None
processed=int(report.get('processed_urls',len(links)) or 0)
kept=int(report.get('kept',(links['decision']=='KEEP').sum() if not links.empty else 0) or 0)
dropped=int(report.get('discarded',(links['decision']=='DROP').sum() if not links.empty else 0) or 0)
pending=int(report.get('pending_urls',0) or 0); total=processed+pending
progress=min(processed/total,1) if total else 0

with st.sidebar:
    st.markdown('## ⌕ HUST Discovery')
    st.caption('Public web collection · Search workspace')
    page=st.radio('KHÔNG GIAN LÀM VIỆC', ['Tổng quan'])
    st.divider(); st.markdown('**TRẠNG THÁI CRAWLER**')
    if running:
        st.success(f'Đang chạy · PID {pid}')
    else:
        st.info('Crawler đang dừng')
    a,b=st.columns(2)
    with a:
        if st.button('▶ Bắt đầu',disabled=running,width="stretch"):
            if not CRAWLER.exists(): st.error('Không tìm thấy crawler_hust.py cạnh app.py.')
            elif not PYTHON.exists(): st.error('Không tìm thấy .venv/bin/python. Hãy chạy website từ thư mục dự án.')
            elif get_pid(): st.warning('Crawler đã chạy; không khởi chạy bản thứ hai.')
            else:
                with LOG.open('a',encoding='utf-8') as log:
                    log.write(f'\n\n=== Phiên {time.strftime("%Y-%m-%d %H:%M:%S")} ===\n'); log.flush()
                    proc=subprocess.Popen([str(PYTHON),'-u',str(CRAWLER)],cwd=BASE,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                PID.write_text(str(proc.pid)); st.rerun()
    with b:
        if st.button('■ Dừng',disabled=not running,width="stretch", help='Gửi tín hiệu dừng an toàn; crawler sẽ lưu tiến độ khi kết thúc request hiện tại.'):
            try:
                # Gửi tín hiệu ngay, không sleep chặn giao diện.
                os.killpg(pid, signal.SIGINT)
                st.session_state['crawler_stop_requested'] = True
                st.toast('Đã gửi yêu cầu dừng. Crawler sẽ lưu tiến độ sau khi kết thúc request hiện tại.', icon='🛑')
            except ProcessLookupError:
                st.session_state['crawler_stop_requested'] = False
                st.warning('Crawler đã dừng trước khi nhận tín hiệu.')
            except OSError as e:
                st.error(f'Không gửi được tín hiệu dừng: {e}')
            st.rerun()
    if st.session_state.get('crawler_stop_requested'):
        if running:
            st.warning('Đang chờ crawler kết thúc request hiện tại và lưu tiến độ. Nếu website đích phản hồi chậm, có thể mất tối đa thời gian timeout của request.')
        else:
            st.session_state['crawler_stop_requested'] = False
            st.success('Crawler đã dừng.')
    if st.button('↻ Làm mới dữ liệu',width="stretch"): st.cache_data.clear(); st.rerun()
    st.caption('Không xóa dữ liệu crawl. Không chạy hai crawler cùng lúc.')
    # Nhật ký kỹ thuật được giữ trong crawler_app.log, không đổ traceback vào sidebar.

st.markdown(f'<div class="hero"><div class="eyebrow">HUST · PUBLIC WEB INTELLIGENCE</div><h1>{"HUST Discovery" if page=="Tổng quan" else page}</h1><p>Thu thập và phân loại nội dung công khai từ website HUST</p></div>',unsafe_allow_html=True)

if page=='Tổng quan':
    st.markdown('### Tổng quan nhanh')
    cols=st.columns(4)
    for c,label,val,note in zip(cols,['Đã xử lý','Giữ lại','Đang chờ','Bị loại'],[processed,kept,pending,dropped],['URL đã xử lý','Trang đạt tiêu chí','URL trong hàng đợi','URL không đạt tiêu chí']):
        c.markdown(f'<div class="kpi"><div class="klabel">{label}</div><div class="kvalue">{nfmt(val)}</div><div class="knote">{note}</div></div>',unsafe_allow_html=True)

    # Tiến độ ngắn gọn, không lặp phần trăm ở nhiều khối.
    st.markdown('#### Tiến độ thu thập')
    st.progress(progress)
    meta = f'{progress:.1%} hoàn thành · {nfmt(processed)} đã xử lý / {nfmt(total)} URL'
    if running:
        meta += ' · Crawler đang chạy'
    else:
        meta += ' · Crawler đang dừng'
    st.caption(meta)

    left, right = st.columns(2, gap='medium')
    with left:
        st.markdown('#### Quyết định crawler')
        if not links.empty:
            decisions_chart = links['decision'].replace('', 'Chưa phân loại').value_counts()
            st.bar_chart(decisions_chart, height=190)
        else:
            st.info('Chưa có links.csv.')
    with right:
        st.markdown('#### Mã HTTP')
        if not links.empty:
            status_chart = links['status_code'].replace('', 'Không rõ').value_counts().head(8)
            st.bar_chart(status_chart, height=190)
        else:
            st.info('Chưa có dữ liệu HTTP.')

    # Bảng URL để thu gọn theo nhu cầu; chỉ hiện 12 dòng đầu để giảm chiều cao.
    st.markdown('#### 🔎 Danh sách URL đã lưu')
    if not links.empty:
        url_df = links.copy()
        f1, f2, f3 = st.columns([1, 1, 2])
        decisions = ['Tất cả'] + sorted(x for x in url_df['decision'].fillna('').unique() if x)
        types = ['Tất cả'] + sorted(x for x in url_df['type'].fillna('').unique() if x)
        decision_filter = f1.selectbox('Lọc quyết định', decisions, key='overview_saved_urls_decision')
        type_filter = f2.selectbox('Lọc loại', types, key='overview_saved_urls_type')
        url_query = f3.text_input('Tìm URL hoặc tiêu đề', key='overview_saved_urls_query', placeholder='Nhập từ khóa...')
        if decision_filter != 'Tất cả':
            url_df = url_df[url_df['decision'] == decision_filter]
        if type_filter != 'Tất cả':
            url_df = url_df[url_df['type'] == type_filter]
        if url_query.strip():
            q = url_query.strip().casefold()
            url_df = url_df[url_df['url_view'].str.casefold().str.contains(q, na=False, regex=False) |
                            url_df['title'].fillna('').str.casefold().str.contains(q, na=False, regex=False)]
        display_cols = ['url_view', 'status_code', 'type', 'title', 'decision', 'reason', 'downloaded_file']
        display_cols = [col for col in display_cols if col in url_df.columns]
        table = url_df[display_cols].copy()
        table.columns = ['URL' if c == 'url_view' else 'HTTP' if c == 'status_code' else
                         'Loại' if c == 'type' else 'Tiêu đề' if c == 'title' else
                         'Quyết định' if c == 'decision' else 'Lý do' if c == 'reason' else
                         'Tệp tải xuống' if c == 'downloaded_file' else c for c in table.columns]
        st.caption(f'{nfmt(len(table))} URL phù hợp · Tổng số URL trong links.csv: {nfmt(len(links))}')
        st.dataframe(table, hide_index=True, width='stretch', height=420,
                     column_config={'URL': st.column_config.LinkColumn('Tên miền / URL', display_text=r'https?://([^/]+).*')})
        st.download_button('Tải toàn bộ danh sách URL đang lọc (CSV)', table.to_csv(index=False).encode('utf-8-sig'),
                           file_name='hust_saved_urls.csv', mime='text/csv', key='overview_download_saved_urls')
    else:
        st.info('Chưa có links.csv nên chưa có danh sách URL để hiển thị.')

st.divider(); st.caption('HUST Discovery · Chỉ thu thập nội dung công khai · Tôn trọng robots.txt và giới hạn truy cập.')

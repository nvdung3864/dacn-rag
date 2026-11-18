import hashlib, ipaddress, re, socket, unicodedata
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZipFile
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from .config import settings,pipeline_key
from .db import Session
from .models import Document,DocumentVersion,Chunk,Source,Job,now
from . import providers
from . import bksi

def file_fingerprint(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as file:
        for block in iter(lambda:file.read(65536),b''):digest.update(block)
    return digest.hexdigest()

def clean(text):
    text=unicodedata.normalize('NFC',text).replace('\x00','')
    return re.sub(r'\n{3,}','\n\n',re.sub(r'[^\S\n]+',' ',text)).strip()


def table_text(rows):
    """Keep empty cells and column names rather than flattening a table."""
    if not rows or len(rows)<2:return ''
    rows=[[clean(str(c)) if c is not None else '' for c in row] for row in rows]
    first=rows[0]
    two_headers=(len(rows)>2 and any(not c for c in first) and not rows[1][0]
                 and sum(bool(c) for c in rows[1])>=2)
    headers=[(rows[1][i] if two_headers else '') or first[i] or f'Cột {i+1}' for i in range(len(first))]
    start=2 if two_headers else 1
    return '\n'.join(' | '.join(f'{headers[i]}: {value or "(ô trống)"}' for i,value in enumerate(row)) for row in rows[start:] if any(row))


def pdf_page_text(page):
    tables=[]
    try:
        for table in page.find_tables().tables:
            text=table_text(table.extract())
            if text:tables.append((table.bbox,text))
    except Exception:
        # Some PDFs cannot be analyzed as tables; retain their original text.
        return clean(page.get_text())
    if not tables:return clean(page.get_text())
    items=[];inserted=set()
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines',[]):
            x0,y0,x1,y1=line['bbox'];cx=(x0+x1)/2;cy=(y0+y1)/2
            table_index=next((i for i,(rect,_) in enumerate(tables) if rect[0]<=cx<=rect[2] and rect[1]<=cy<=rect[3]),None)
            if table_index is not None:
                if table_index not in inserted:
                    items.append(tables[table_index][1]);inserted.add(table_index)
                continue
            # Preserve PDF block order; sorting all lines by y interleaves sidebar columns.
            items.append(''.join(span['text'] for span in line['spans']))
    items.extend(text for i,(_,text) in enumerate(tables) if i not in inserted)
    return clean('\n'.join(items))

def validate_url(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in [None,443] or parsed.hostname not in settings.wiki_hosts:
        raise ValueError('Chỉ đồng bộ HTTPS từ các tên miền nguồn WEB đã cấu hình.')
    if parsed.hostname=='mybk.hcmut.edu.vn' and not bksi.kind(url):
        raise ValueError('Chỉ đồng bộ nội dung BKSI tiếng Việt công khai.')
    try:
        addresses=socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
        if any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError('Không đồng bộ từ địa chỉ nội bộ.')
    except socket.gaierror: raise ValueError('Không phân giải được tên miền nguồn WEB.')
    return url

def fetch_html(url):
    validate_url(url)
    try:
        with httpx.Client(timeout=30,follow_redirects=False) as client:
            for attempt in range(5):
                with client.stream('GET',url,headers={'User-Agent':'DACN-RAG/0.1 (educational ingestion)'}) as r:
                    if r.is_redirect:
                        from urllib.parse import urljoin
                        url=validate_url(urljoin(url,r.headers.get('location','')))
                        continue
                    r.raise_for_status()
                    if 'text/html' not in r.headers.get('content-type',''): raise ValueError('Nguồn WEB không phải HTML.')
                    blob=bytearray()
                    for block in r.iter_bytes():
                        blob.extend(block)
                        if len(blob)>settings.max_upload:raise ValueError('Trang vượt giới hạn kích thước.')
                    soup=BeautifulSoup(bytes(blob),'html.parser')
                    if soup.select_one('input[type="password"]'):
                        raise ValueError('Trang yêu cầu đăng nhập; không lập chỉ mục trang đăng nhập.')
                    return url,soup
            raise ValueError('Nguồn chuyển hướng quá nhiều lần.')
    except httpx.HTTPStatusError as exc:raise ValueError(f'Nguồn WEB trả lỗi HTTP {exc.response.status_code}.')
    except httpx.HTTPError:raise ValueError('Không tải được nguồn WEB. Kiểm tra URL, quyền truy cập và kết nối mạng.')


def fetch_wiki(url):
    url,soup=fetch_html(url)
    if bksi.kind(url):
        if bksi.kind(url)!='article':raise ValueError('Đây là danh mục BKSI; cần đồng bộ nguồn để lấy các bài viết.')
        return bksi.article(soup,url)
    title=clean(soup.h1.get_text(' ',strip=True) if soup.h1 else soup.title.get_text(' ',strip=True) if soup.title else url)
    main=soup.select_one('.mw-parser-output') or soup.select_one('main') or soup.select_one('article') or soup.body
    if not main:raise ValueError('Trang không có nội dung chính.')
    for tag in main.select('script,style,nav,header,footer,.navbox,.toc,.mw-editsection'):tag.decompose()
    units=[];heading=None;parts=[]
    for node in main.find_all(['h1','h2','h3','h4','p','li','table']):
        if node.find_parent(['table','li']):continue
        if node.name.startswith('h'):
            if parts:units.append({'text':clean('\n'.join(parts)),'page':None,'section':heading});parts=[]
            heading=clean(node.get_text(' ',strip=True))
        else:parts.append(node.get_text(' ',strip=True))
    if parts:units.append({'text':clean('\n'.join(parts)),'page':None,'section':heading})
    if not units:units=[{'text':clean(main.get_text('\n',strip=True)),'page':None,'section':None}]
    return title,units

def extract_file(path,fmt):
    if fmt=='PDF':
        import fitz
        with fitz.open(path) as pdf:
            if pdf.page_count>1000:raise ValueError('PDF vượt giới hạn 1000 trang.')
            units=[{'text':pdf_page_text(page),'page':i+1,'section':None} for i,page in enumerate(pdf)]
    elif fmt=='DOCX':
        with ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist())>100*1024*1024:raise ValueError('DOCX vượt giới hạn nội dung giải nén.')
        from docx import Document as Docx
        from docx.text.paragraph import Paragraph
        from docx.table import Table
        d=Docx(path);units=[];section=None;parts=[]
        for el in d.element.body:
            if el.tag.endswith('}p'):
                para=Paragraph(el,d)
                if para.style and para.style.name.startswith('Heading'):
                    if parts:units.append({'text':clean('\n'.join(parts)),'page':None,'section':section});parts=[]
                    section=para.text
                elif para.text:parts.append(para.text)
            elif el.tag.endswith('}tbl'):
                for row in Table(el,d).rows:parts.append(' | '.join(c.text for c in row.cells))
        if parts:units.append({'text':clean('\n'.join(parts)),'page':None,'section':section})
    else:
        raw=Path(path).read_bytes()
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:raise ValueError('TXT phải được lưu theo UTF-8.')
        units=[{'text':clean(text),'page':None,'section':None}]
    if not any(u['text'] for u in units):
        if fmt=='PDF':raise ValueError('Không trích xuất được văn bản từ PDF. File có thể là ảnh scan và cần OCR; hãy kiểm tra lớp chữ của file.')
        raise ValueError(f'Không trích xuất được văn bản từ {fmt}. Kiểm tra file rỗng hoặc nội dung nằm trong hình ảnh/textbox.')
    if sum(len(u['text']) for u in units)>2_000_000:raise ValueError('Văn bản vượt giới hạn baseline.')
    return units

def split_units(units,size=None,overlap=None):
    size=size or settings.chunk_size
    overlap=settings.overlap if overlap is None else overlap
    if size<10 or overlap<0 or overlap>=size:raise ValueError('Chunk size và overlap không hợp lệ.')
    out=[]
    for unit in units:
        words=unit['text'].split()
        for start in range(0,len(words),size-overlap):
            out.append({'text':' '.join(words[start:start+size]),'page':unit['page'],'section':unit['section']})
            if start+size>=len(words):break
    if len(out)>5000:raise ValueError('Tài liệu vượt giới hạn số chunk.')
    return out

def index_document(db,document,units):
    # Row lock serializes reprocessing; old indexed version remains usable until commit.
    document=db.scalar(select(Document).where(Document.id==document.id).with_for_update())
    text='\n'.join(u['text'] for u in units)
    if not text.strip():raise ValueError('Nội dung rỗng, không tạo index.')
    digest=hashlib.sha256(text.encode()).hexdigest()
    if document.content_hash==digest and document.pipeline==pipeline_key() and document.status=='INDEXED':
        return {'unchanged':True,'chunks':0,'version':document.version}
    chunks=split_units(units)
    vectors=providers.embed([c['text'] for c in chunks])
    version=document.version+1
    for i,(c,vector) in enumerate(zip(chunks,vectors)):
        cid=hashlib.sha256(f'{document.id}:{version}:{digest}:{pipeline_key()}:{i}'.encode()).hexdigest()
        db.add(Chunk(id=cid,document_id=document.id,source_id=document.source_id,version=version,chunk_index=i,text=c['text'],page=c['page'],section=c['section'],embedding=vector,embedding_model=settings.embedding_model))
    db.add(DocumentVersion(document_id=document.id,version=version,content_hash=digest,pipeline=pipeline_key()))
    document.version=version;document.content_hash=digest;document.pipeline=pipeline_key();document.status='INDEXED';document.indexed_at=now()
    return {'unchanged':False,'chunks':len(chunks),'version':version}

def run_job(job_id):
    with Session() as db:
        job=db.get(Job,job_id)
        if not job:return
        job.status='PROCESSING';job.attempts+=1;db.commit()
        try:
            source=db.get(Source,job.source_id)
            if not source or not source.enabled:raise ValueError('Nguồn không hoạt động.')
            if job.kind=='SYNC' and bksi.kind(source.location):
                bksi.sync_source(db,job,source)
                return
            if job.kind=='SYNC':
                title,units=fetch_wiki(source.location)
                doc=db.scalar(select(Document).where(Document.source_id==source.id,Document.location==source.location))
                if not doc:
                    doc=Document(source_id=source.id,title=title,location=source.location,format='WEB');db.add(doc);db.flush()
                doc.title=title;job.document_id=doc.id
            else:
                doc=db.get(Document,job.document_id)
                if doc.format=='WEB':title,units=fetch_wiki(doc.location);doc.title=title
                else:units=extract_file(doc.file_path,doc.format)
            stats=index_document(db,doc,units)
            source.last_synced_at=now();job.status='SUCCEEDED';job.stats=stats;job.finished_at=now();db.commit()
        except Exception as exc:
            db.rollback();job=db.get(Job,job_id)
            if job:
                job.status='FAILED';job.finished_at=now()
                job.error=str(exc) if isinstance(exc,(ValueError,providers.ProviderError)) else 'Xử lý thất bại. Kiểm tra định dạng tài liệu hoặc kết nối database.'
                if job.document_id:
                    doc=db.get(Document,job.document_id)
                    if doc and doc.version==0:doc.status='FAILED'
                db.commit()

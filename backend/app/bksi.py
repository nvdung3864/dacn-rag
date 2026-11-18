import re
import time
from collections import deque
from urllib.parse import urlparse,urljoin,urlunparse
from sqlalchemy import select
from .config import settings

ROOT='https://mybk.hcmut.edu.vn/bksi/public/vi/'


class ArticleListing(ValueError):
    pass


def kind(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname!='mybk.hcmut.edu.vn' or parsed.username or parsed.password:return None
    try:
        if parsed.port not in (None,443):return None
    except ValueError:return None
    path=parsed.path.rstrip('/')
    if path in ('/bksi/public/vi','/bksi/public/vi/folder'):return 'listing'
    if re.fullmatch(r'/bksi/public/vi/category/\d+',path):return 'listing'
    if re.fullmatch(r'/bksi/public/vi/(?:article/\d+|blog/[^/]+)',path):return 'article'
    return None


def normalize(url,base=ROOT):
    parsed=urlparse(urljoin(base,url.strip()))
    if not kind(parsed.geturl()):return None
    path=parsed.path.rstrip('/')
    if path in ('/bksi/public/vi','/bksi/public/vi/folder'):path='/bksi/public/vi/'
    return urlunparse(('https','mybk.hcmut.edu.vn',path,'','',''))


def canonical(url,soup):
    tag=soup.find('link',rel='canonical')
    if tag and tag.get('href'):
        parsed=urlparse(urljoin(url,tag['href'].strip()))
        if parsed.scheme=='http' and parsed.hostname=='mybk.hcmut.edu.vn':parsed=parsed._replace(scheme='https')
        candidate=normalize(parsed.geturl())
        if candidate and kind(candidate)=='article':return candidate
    return normalize(url)


def table_rows(table):
    from .ingestion import clean
    grid=[];occupied={}
    for r,row in enumerate(table.find_all('tr')):
        if row.find_parent('table') is not table:continue
        values={c:value for (rr,c),value in occupied.items() if rr==r};column=0
        for cell in row.find_all(['td','th'],recursive=False):
            while column in values:column+=1
            try:
                width=max(1,min(int(cell.get('colspan',1)),100));height=max(1,min(int(cell.get('rowspan',1)),100))
            except (TypeError,ValueError):width=height=1
            value=clean(cell.get_text(' ',strip=True))
            for dr in range(height):
                for dc in range(width):
                    occupied[r+dr,column+dc]=value if dc==0 else None
                    if dr==0:values[column+dc]=value if dc==0 else None
            column+=width
            if column>100:raise ValueError('Bảng HTML vượt giới hạn số cột.')
        if values:grid.append([values.get(i) for i in range(max(values)+1)])
        if len(grid)>2000:raise ValueError('Bảng HTML vượt giới hạn số hàng.')
    if not grid:return []
    width=max(map(len,grid));grid=[row+[None]*(width-len(row)) for row in grid]
    if len(grid)>2 and any(v is None for v in grid[0]) and grid[1][0]==grid[0][0]:grid[1][0]=None
    return grid


def article(soup,url):
    from .ingestion import clean,table_text
    main=soup.select_one('.uv-paper-article > .uv-paper-section > section')
    if main is None or main.find('h1') is None:raise ValueError('Không tìm thấy nội dung bài viết BKSI.')
    title=clean(main.h1.get_text(' ',strip=True))
    for tag in main.select('script,style,nav,header,footer,form,.uv-article-feedback'):tag.decompose()
    units=[];parts=[];heading=title
    def flush():
        if parts:
            value=clean('\n'.join(parts));parts.clear()
            if value:units.append({'text':value,'page':None,'section':heading})
    for node in main.find_all(['h1','h2','h3','h4','p','li','table']):
        if node.find_parent(['table','li']):continue
        if node.name.startswith('h'):
            flush();heading=clean(node.get_text(' ',strip=True))
        elif node.name=='table':
            flush();value=table_text(table_rows(node))
            if value:units.append({'text':value,'page':None,'section':heading})
        elif node.name=='p' and node.find(['p','ul','ol','table','h1','h2','h3','h4']):continue
        else:
            value=clean(node.get_text(' ',strip=True))
            if value:parts.append(value)
    flush()
    if not units:
        remaining=' '.join(str(node).strip() for node in main.find_all(string=True) if not node.find_parent(['h1','h2','h3','h4','a']))
        if main.find('a') and not remaining.strip():raise ArticleListing('Trang BKSI chỉ chứa danh sách liên kết.')
        raise ValueError('Bài viết BKSI không có văn bản để lập chỉ mục.')
    if sum(len(u['text']) for u in units)>2_000_000:raise ValueError('Nội dung bài viết vượt giới hạn.')
    return title,units


def sync_source(db,job,source):
    from .ingestion import fetch_html,index_document
    from .models import Document,Job,Source,now
    from . import providers
    start=normalize(source.location)
    if not start:raise ValueError('URL BKSI không hợp lệ.')
    queue=deque([start]);scheduled={start};seen=set();articles=set()
    maximum=max(1,min(settings.bksi_max_articles,500));page_limit=max(1,min(settings.bksi_max_pages,1000))
    stats={'documents':0,'updated':0,'unchanged':0,'chunks':0,'visited_pages':0,'skipped_pages':0,'failed':0,'errors':[],'max_articles':maximum,'truncated':False,'stage':'fetching'}
    job_id=job.id;source_id=source.id
    def progress():
        current=db.get(Job,job_id);current.stats={**stats};db.commit()
    progress()
    while queue:
        if stats['visited_pages']>=page_limit or stats['documents']>=maximum:
            stats['truncated']=True;break
        url=queue.popleft()
        if url in seen:continue
        seen.add(url)
        if stats['visited_pages']:time.sleep(max(0,min(settings.web_delay_seconds,5)))
        stats['visited_pages']+=1
        try:
            final,soup=fetch_html(url)
            current=normalize(final)
            if not current:raise ValueError('Trang chuyển hướng ra ngoài BKSI tiếng Việt công khai.')
            for link in soup.select('a[href]') if kind(start)=='listing' else []:
                candidate=normalize(link['href'],current)
                if candidate and candidate not in scheduled:
                    scheduled.add(candidate);queue.append(candidate)
            if kind(current)=='listing':
                progress();continue
            location=canonical(current,soup)
            if location in articles:
                progress();continue
            articles.add(location);seen.add(location)
            title,units=article(soup,current)
            stats['stage']='indexing';progress()
            doc=db.scalar(select(Document).where(Document.source_id==source_id,Document.location==location))
            if not doc:
                doc=Document(source_id=source_id,title=title,location=location,format='WEB');db.add(doc);db.flush()
            doc.title=title
            result=index_document(db,doc,units)
            stats['documents']+=1;stats['unchanged' if result['unchanged'] else 'updated']+=1;stats['chunks']+=result['chunks'];stats['stage']='fetching'
            progress()
        except ArticleListing:
            stats['skipped_pages']+=1;progress()
        except providers.ProviderError:
            db.rollback();raise
        except (ValueError,TypeError) as exc:
            db.rollback();stats['failed']+=1
            if len(stats['errors'])<50:stats['errors'].append({'url':url,'error':str(exc)})
            progress()
    if stats['documents']==0:raise ValueError('Không đồng bộ được bài viết BKSI. Kiểm tra trạng thái nguồn và lỗi tác vụ.')
    source=db.get(Source,source_id);source.last_synced_at=now()
    job=db.get(Job,job_id);job.status='PARTIAL' if stats['failed'] or stats['truncated'] else 'SUCCEEDED';job.finished_at=now();stats['stage']='finished';job.stats={**stats}
    if stats['failed']:job.error=f'Đã đồng bộ {stats["documents"]} bài; {stats["failed"]} trang gặp lỗi.'
    elif stats['truncated']:job.error=f'Đã đồng bộ {stats["documents"]} bài; đạt giới hạn đồng bộ.'
    db.commit()

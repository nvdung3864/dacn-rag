import re

YEAR_NAMES={'1':1,'2':2,'3':3,'4':4,'nhất':1,'hai':2,'ba':3,'tư':4}
YEAR_PATTERN=r'chuẩn\s+(?:ngoại ngữ|anh văn|tiếng anh)\s+năm\s+(?:thứ\s+)?(nhất|hai|ba|tư|[1-4])\b'


def requested_year(question):
    match=re.search(r'năm\s+(?:thứ\s+)?(nhất|hai|ba|tư|[1-4])\b',question,re.I)
    if match:return YEAR_NAMES[match[1].lower()]
    code=re.search(r'\bccas[_ -]?([0-3])\b',question,re.I)
    return int(code[1])+1 if code else None


def requirements(text,title=''):
    rows=[text]
    if title:
        pattern=re.escape(title)+r'[^:|\n]{0,120}:\s*(?:\d+|STT)\s*\|'
        rows=re.split(r'(?='+pattern+r')',text,flags=re.I)
    results=[]
    for row in rows:
        for span in re.split(r'(?<=[.!?])\s+|\n+|\s+(?=\d{1,2}-\s+)',row):
            span=span.strip()
            year=re.search(YEAR_PATTERN,span,re.I)
            if not year or '?' in span:continue
            tail=span[year.end():]
            course=re.search(r'(?:phải\s+)?đạt\s+(Anh văn[^)|.]+)',tail,re.I)
            if not course:continue
            if re.search(YEAR_PATTERN,tail[:course.start()],re.I):continue
            cohort=re.search(r'từ\s+khóa\s+(20\d{2})',span,re.I)
            exact=re.search(r'(?<!từ )\bkhóa\s+(20\d{2})',span,re.I) if not cohort else None
            phrase=course[1].strip()
            if phrase.count('(')>phrase.count(')'):phrase+=')'
            results.append({'year':YEAR_NAMES[year[1].lower()],'course':phrase,
                            'quote':span,'cohort_min':int(cohort[1]) if cohort else None,
                            'cohort_exact':int(exact[1]) if exact else None})
    return results


def annual_answer(question,context):
    from .questions import annual_language_requirement
    if not annual_language_requirement(question):return None
    year=requested_year(question)
    cohort=re.search(r'khóa\s+(20\d{2})|\bk(\d{2})\b',question,re.I)
    cohort=int(cohort[1] or '20'+cohort[2]) if cohort else None
    found={}
    for index,hit in enumerate(context):
        for rule in requirements(hit['text'],hit.get('title','')):
            if year and rule['year']!=year:continue
            courses=tuple(sorted(set(re.findall(r'\d+[a-z]?',rule['course'].lower()))))
            key=(rule['year'],'cơ bản' in rule['course'].lower(),courses,rule['cohort_min'],rule['cohort_exact'])
            found.setdefault(key,{**rule,'index':index})
    if not found:
        return {'answer':'Các đoạn đã tìm được chưa có đủ điều kiện Anh văn theo năm học để đối chiếu. Bạn có thể chọn nguồn chứa bảng quy định các chuẩn hoặc cho biết năm học muốn xem.',
                'source_markers':[],'no_answer':True}
    lines=[];markers=[];evidence=[];rendered_years=set()
    for current_year in sorted({r['year'] for r in found.values()}):
        rules=[r for r in found.values() if r['year']==current_year and (cohort is None or r['cohort_exact'] in (None,cohort))]
        exact=[r for r in rules if cohort is not None and r['cohort_exact']==cohort]
        applicable=[r for r in rules if r['cohort_min'] is not None and cohort is not None and cohort>=r['cohort_min']]
        if exact:rules=exact
        elif applicable:
            latest=max(r['cohort_min'] for r in applicable)
            rules=[r for r in applicable if r['cohort_min']==latest]
        elif cohort is not None:
            rules=[r for r in rules if r['cohort_min'] is None]
        for rule in rules:
            marker=f'S{rule["index"]+1}'
            scope=f' (khóa {rule["cohort_exact"]})' if rule['cohort_exact'] else f' (từ khóa {rule["cohort_min"]})' if rule['cohort_min'] else ''
            condition=re.search(r'không áp dụng[^.]+',rule['quote'],re.I)
            suffix='; '+condition[0].rstrip('). ') if condition else ''
            lines.append(f'- Năm {current_year}{scope}: đạt {rule["course"]}{suffix}. [{marker}]')
            rendered_years.add(current_year)
            if marker not in markers:markers.append(marker)
            evidence.append({'source':marker,'quote':rule['quote']})
    if not lines:return {'answer':'Chưa tìm được điều kiện phù hợp với khóa bạn cung cấp trong các đoạn nguồn này.','source_markers':[],'no_answer':True}
    missing=({year} if year else {1,2,3,4})-rendered_years
    suffix='Các điều kiện và ngoại lệ về khóa/chương trình được giữ trong trích đoạn; đây là chuẩn theo năm học, không phải kết luận về hồ sơ cá nhân.'
    if missing:suffix+=' Chưa tìm đủ thông tin cho năm '+', '.join(map(str,sorted(missing)))+' trong ngữ cảnh hiện có.'
    return {'answer':'Chuẩn Anh văn theo năm học trong tài liệu:\n'+'\n'.join(lines)+'\n\n'+suffix,
            'source_markers':markers,'supporting_evidence':evidence,'no_answer':False}

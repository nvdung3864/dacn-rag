import re
from .questions import normalize_question


def requirements_for(question):
    text=normalize_question(question)
    requirements=[]
    numeric=bool(re.search(r'bao nhiêu|bao lâu|\bmấy\b|mức (?:điểm|phí)|điểm tối thiểu|số (?:điểm|tiền|tín chỉ)|tối đa|tối thiểu',text))
    if numeric:
        measures=[('score','Điểm số',r'toeic|ielts|vstep|vnu[ -]?ept|toefl|điểm'),
                  ('fee','Số tiền',r'lệ phí|học phí|bao nhiêu tiền|mấy tiền'),
                  ('credits','Số tín chỉ',r'tín chỉ'),
                  ('duration','Thời gian',r'bao (?:nhiêu|lâu).{0,30}(?:ngày|tuần|tháng|năm)|mấy (?:ngày|tuần|tháng|năm)|bao lâu')]
        for key,label,pattern in measures:
            if re.search(pattern,text):requirements.append({'id':key,'label':label,'kind':'quantity','question':text})
        if not requirements and not re.search(r'(?:bao nhiêu|mấy)\s*(?:kỹ|kĩ) năng',text):
            requirements.append({'id':'quantity','label':'Con số được hỏi','kind':'quantity','question':text})
    if re.search(r'(?:kỹ|kĩ) năng',text) and re.search(r'2|4|hai|bốn|hay|bao nhiêu|mấy',text):
        requirements.append({'id':'skills','label':'Số kỹ năng','kind':'skills','question':text})
    clauses=re.split(r'[,;?\n]+(?!\d)|\s+và\s+(?=(?:có|được|đạt|phải|cần|bao nhiêu|mấy|thủ tục|quy trình)\b)',text)
    for clause in clauses:
        if re.search(r'đúng(?:\s+hay\s+sai|\s+không|\s*/\s*sai)|sai\s+không|(?:có\b.+|được|phải|đủ|hợp lệ)\s+(?:hay\s+)?không|hay không',clause):
            part=text if len(clause.split())<=4 and re.search(r'đúng|sai',clause) else clause.strip()
            requirements.append({'id':f'verdict_{sum(r["kind"]=="verdict" for r in requirements)+1}',
                                 'label':part.capitalize(),'kind':'verdict','question':part})
    if requirements:
        for clause in clauses:
            if re.search(r'(?:được|là|những|các)\s+gì|môn\s+nào|thủ tục|quy trình|ở đâu|vì sao|tại sao',clause) and not re.search(r'bao nhiêu|\bmấy\b|không',clause):
                requirements.append({'id':f'detail_{sum(r["kind"]=="detail" for r in requirements)+1}',
                                     'label':clause.strip().capitalize(),'kind':'detail','question':clause.strip()})
    return sorted(requirements,key=lambda r:r['kind']!='verdict')


def project_scope(question):
    text=normalize_question(question)
    if not re.search(r'toeic|ielts|vstep|toefl|ngoại ngữ|anh văn|tiếng anh',text):return None
    if 'đồ án chuyên ngành' in text:return r'đồ án chuyên ngành|c_đacn'
    if re.search(r'(?:đồ án|luận văn|khóa luận) tốt nghiệp',text):
        return r'(?:đồ án|luận văn|khóa luận) tốt nghiệp|ccav[_ -]?1|c_lvtn'
    return None


def numeric_values(text):
    text=re.sub(r'\b(?:khóa|năm học|hk)\s*\d+(?:[-/]\d+)*','',normalize_question(text))
    text=re.sub(r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b','',text)
    values=set()
    for value in re.findall(r'\d+(?:[.,]\d+)*',text):
        if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',value):value=re.sub(r'[.,]','',value)
        else:value=value.replace(',','.')
        try:values.add(float(value))
        except ValueError:pass
    return values


def quantities_for(requirement,text):
    text=normalize_question(text)
    if requirement['id']=='score':
        text=re.sub(r'\b(?:[24]|hai|bốn)\s*(?:kỹ|kĩ) năng','',text)
        text=re.sub(r'(?:anh văn|av)\s+\d+(?:\s*[,/]\s*\d+)*','',text)
    if requirement['kind']=='skills':
        text=re.sub(r'\bhai\s+(kỹ|kĩ) năng',r'2 \1 năng',text)
        text=re.sub(r'\bbốn\s+(kỹ|kĩ) năng',r'4 \1 năng',text)
    return numeric_values(text)


def applicable_evidence(quote,question):
    text=normalize_question(quote);scope=project_scope(question)
    if scope and not re.search(scope,text):return False
    cohort=re.search(r'khóa\s+(20\d{2})',normalize_question(question))
    if cohort:
        year=int(cohort[1])
        for match in re.finditer(r'(từ\s+)?khóa\s+(20\d{2})(\s+(?:trở\s+)?(?:về\s+)?(?:sau|trước))?',text):
            bound=int(match[2]);suffix=match[3] or ''
            if 'trước' in suffix and year>bound:return False
            if ('sau' in suffix or match[1]) and 'trước' not in suffix and year<bound:return False
            if not match[1] and not suffix and year!=bound:return False
    return True


def candidates_for(requirement,evidence,question):
    matches={}
    for eid,item in evidence.items():
        quote=item['quote'];text=normalize_question(quote)
        if not applicable_evidence(quote,question):continue
        kind=requirement['kind'];key=requirement['id']
        if kind=='verdict':
            part=requirement['question']
            if 'tín chỉ' in part and not re.search(r'tín chỉ|tích lũy',text):continue
            if 'trung bình' in part and 'trung bình' not in text:continue
            if 'miễn' in normalize_question(question) and re.search(r'tín chỉ|trung bình',part) and 'miễn' not in text:continue
            certificate=re.search(r'\b(toeic|ielts|vstep|toefl)\b',normalize_question(question))
            if project_scope(question) and certificate and certificate[0] not in text:continue
            if certificate and not re.search(r'tín chỉ|trung bình',part):
                if certificate[0] not in text:continue
                if 'home edition' in normalize_question(question) and 'home edition' not in text:continue
        if kind=='quantity':
            if not quantities_for(requirement,quote):continue
            patterns={'score':r'toeic|ielts|vstep|vnu[ -]?ept|toefl|điểm',
                      'fee':r'đồng|\bvnđ\b|\bvnd\b|lệ phí|học phí',
                      'credits':r'tín chỉ','duration':r'ngày|tuần|tháng|năm|học kỳ'}
            if key in patterns and not re.search(patterns[key],text):continue
            if key=='score':
                certificate=re.search(r'\b(toeic|ielts|vstep|toefl|vnu[ -]?ept)\b',normalize_question(question))
                if certificate and not re.search(certificate[0],text):continue
        if kind=='skills' and not re.search(r'(?:[24]|hai|bốn)\s*(?:kỹ|kĩ) năng|nghe.{0,30}đọc|nói.{0,30}viết',text):continue
        matches[eid]=item
    return matches


def literal_verdict(requirement,candidates,question):
    full=normalize_question(question);part=requirement['question']
    if requirement['kind']!='verdict' or not re.search(r'anh văn|tiếng anh|ngoại ngữ|vstep|toeic|ielts',full) or 'miễn' not in full:return None
    if 'trung bình' in part:
        pattern=r'(?P<negative>không\s+(?:(?:được|còn)\s+)?)?tính\s+(?:vào\s+)?điểm trung bình'
        field='gpa'
    elif 'tín chỉ' in part and not re.search(r'học kỳ|tối đa|tối thiểu',part):
        pattern=r'(?P<negative>không\s+(?:(?:được|còn)\s+)?)?(?:tính|cộng)\s+(?:số\s+)?tín chỉ tích lũy'
        field='credits'
    else:return None
    facts=[]
    for eid,item in candidates.items():
        quote=normalize_question(item['quote'])
        if 'miễn' not in quote or re.search(r'\bnếu\b|chỉ khi|riêng|ngoại trừ|trừ khi|đối với|từ hk',quote):continue
        for match in re.finditer(pattern,quote):facts.append((not bool(match['negative']),eid,item['quote']))
    if not facts or len({f[0] for f in facts})!=1:return None
    value,eid,quote=min(facts,key=lambda f:len(f[2]))
    if field=='gpa' and re.search(r'kéo|tăng|lên',part) and value:return None
    negative=bool(re.search(r'không\s+(?:được\s+)?(?:tính|cộng|kéo|tăng|làm tăng)',part))
    agrees=value!=negative
    verdict=('Đúng' if agrees else 'Sai') if re.search(r'đúng|sai',part) else ('Có' if agrees else 'Không')
    if field=='gpa':
        fact='Các học phần Anh văn được xét miễn '+('có tính' if value else 'không tính')+' vào điểm trung bình.'
    else:
        fact='Các học phần Anh văn được xét miễn '+('được tính' if value else 'không tính')+' tín chỉ tích lũy.'
    return {'status':'supported','value':verdict,'text':verdict+'. '+fact,'evidence':[eid]}


def missing_text(requirement,question):
    labels={'score':'mức điểm','fee':'số tiền','credits':'số tín chỉ','duration':'thời gian','quantity':'giá trị'}
    if requirement['kind']=='verdict':
        verdict='Đúng/Sai' if re.search(r'đúng|sai',requirement['question']) else 'Có/Không'
        return f'Chưa đủ căn cứ để kết luận {verdict} cho ý “{requirement["question"]}”.'
    if requirement['kind']=='skills':
        certificate=re.search(r'\b(toeic|ielts|vstep|toefl)\b',normalize_question(question))
        name=certificate[0].upper() if certificate else 'chứng chỉ'
        return f'Số kỹ năng: các đoạn tài liệu truy hồi chưa xác định rõ số kỹ năng cần có của {name} cho trường hợp được hỏi (2 hay 4 kỹ năng).'
    if requirement['kind']=='detail':
        return f'Các đoạn tài liệu truy hồi chưa cung cấp thông tin cụ thể cho ý “{requirement["question"]}”.'
    certificate=re.search(r'\b(toeic|ielts|vstep|toefl|vnu[ -]?ept)\b',normalize_question(question))
    subject=' '+certificate[0].upper() if requirement['id']=='score' and certificate else ''
    return f'{requirement["label"]}{subject}: các đoạn tài liệu truy hồi chưa nêu con số cụ thể về {labels.get(requirement["id"],"giá trị")}{subject} áp dụng cho trường hợp được hỏi.'


def missing_answer(requirements,question):
    return {'answer':'\n\n'.join(missing_text(r,question) for r in requirements),'source_markers':[],
            'no_answer':True,'missing_information':[r['id'] for r in requirements]}


def contract_schema(requirements,candidates):
    properties={}
    for requirement in requirements:
        key=requirement['id'];available=candidates[key]
        values={'type':'string'}
        if requirement['kind']=='verdict':values['enum']=(['Đúng','Sai'] if re.search(r'đúng|sai',requirement['question']) else ['Có','Không'])+['']
        properties[key]={'type':'object','description':requirement['label']+': '+requirement['question'],
            'properties':{'status':{'type':'string','enum':['supported','missing'] if available else ['missing']},
                          'value':values,'text':{'type':'string'},
                          'evidence':{'type':'array','maxItems':3,'items':{'type':'string','enum':list(available) or ['UNAVAILABLE']}}},
            'required':['status','value','text','evidence'],'additionalProperties':False}
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def render_contract(obj,requirements,candidates,question):
    if not isinstance(obj,dict) or set(obj)!={r['id'] for r in requirements}:raise ValueError('Thiếu ý trả lời bắt buộc.')
    paragraphs=[];markers=[];selected=[];missing=[]
    for requirement in requirements:
        key=requirement['id'];item=obj[key]
        if not isinstance(item,dict) or item.get('status') not in ('supported','missing'):raise ValueError('Trạng thái ý trả lời không hợp lệ.')
        if item['status']=='missing':
            paragraphs.append(missing_text(requirement,question));missing.append(key);continue
        value=item.get('value');text=item.get('text');ids=item.get('evidence')
        if not isinstance(value,str) or not isinstance(text,str) or not isinstance(ids,list):raise ValueError('Ý trả lời sai định dạng.')
        available=candidates[key]
        if not ids or any(not isinstance(eid,str) or eid not in available for eid in ids):raise ValueError('Ý trả lời không có bằng chứng phù hợp.')
        proofs=[available[eid] for eid in dict.fromkeys(ids)]
        text=re.sub(r'\[S[^\]]*\]','',text).strip()
        if not text or text.endswith('?'):raise ValueError('Không dùng câu hỏi làm câu trả lời.')
        if requirement['kind']!='verdict':text=re.sub(r'^(?:Có|Đúng)[,.:]\s*','',text)
        valid=True
        if requirement['kind']=='quantity':
            numbers=numeric_values(value)
            valid=bool(numbers) and numbers<=numeric_values(text) and numbers<=set().union(*(quantities_for(requirement,p['quote']) for p in proofs))
        elif requirement['kind']=='skills':
            numbers=quantities_for(requirement,value)
            valid=bool(numbers) and numbers<={2,4} and numbers<=quantities_for(requirement,text) and numbers<=set().union(*(quantities_for(requirement,p['quote']) for p in proofs))
        elif requirement['kind']=='verdict':
            choices=('Đúng','Sai') if re.search(r'đúng|sai',requirement['question']) else ('Có','Không')
            valid=value in choices
            if valid and not re.match(r'^(?:Có|Không|Đúng|Sai)\b',text):text=value+'. '+text
            elif valid and not re.match(r'^'+value+r'\b',text):valid=False
        if not valid:
            paragraphs.append(missing_text(requirement,question));missing.append(key);continue
        sources=list(dict.fromkeys(p['source'] for p in proofs))
        paragraphs.append(text+' '+' '.join('['+s+']' for s in sources))
        markers.extend(s for s in sources if s not in markers)
        selected.extend(p for p in proofs if p not in selected)
    return {'answer':'\n\n'.join(paragraphs),'source_markers':markers,'no_answer':not markers,
            'supporting_evidence':selected,'missing_information':missing}

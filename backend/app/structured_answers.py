"""Read explicit numeric rules and table rows; never hard-code document values."""
import re
from decimal import Decimal
from .questions import normalize_question,minimum_credit_question


def table_lookup(question, context):
    question=normalize_question(question)
    requested=re.search(r'\b(vstep|vnu[ -]?ept)\s+(\d+(?:[.,]\d+)?)',question)
    if not requested or 'miễn' not in question:return None
    certificate=re.sub(r'\W','',requested[1]).lower()
    score=Decimal(requested[2].replace(',','.'))
    matches=[]
    for index,hit in enumerate(context):
        expected_columns={int(n) for n in re.findall(r'Anh văn\s+(\d+):',hit['text'],re.I)}
        for row in re.finditer(r'Chứng chỉ\s+([^:|]+):\s*(\d+(?:[.,]\d+)?)\s*\|(.+?)(?=Chứng chỉ\s+[^:|]+:\s*\d|https?://|$)',hit['text'],re.I):
            if re.sub(r'\W','',row[1]).lower()!=certificate or Decimal(row[2].replace(',','.'))!=score:continue
            cells=list(re.finditer(r'Anh văn\s+(\d+):\s*(Đạt|\(ô trống\))',row[3],re.I))
            values={int(cell[1]):cell[2].lower() for cell in cells}
            if not expected_columns or set(values)!=expected_columns:continue
            passed=tuple(sorted(n for n,v in values.items() if v=='đạt'))
            quote=hit['text'][row.start():row.start(3)+cells[-1].end()].strip()
            matches.append((passed,index,quote,row[1].strip(),row[2]))
    if not matches or len({m[0] for m in matches})!=1:return None
    passed,index,quote,name,grade=matches[0]
    if not passed:return None
    marker=f'S{index+1}'
    return {'answer':f'Theo bảng quy đổi, {name} mức {grade} được xét miễn các môn Anh văn '+', '.join(map(str,passed))+f'. [{marker}]',
            'source_markers':[marker],'no_answer':False,'supporting_evidence':[{'source':marker,'quote':quote}]}


def credit_limit(question, context):
    question=normalize_question(question)
    phase=re.search(r'\bđợt\s+(\d+)\b',question)
    amount=re.search(r'\b(\d+)\s+tín chỉ\b',question)
    if not phase or not amount or 'đăng ký' not in question or 'không đăng ký' in question:return None
    postgraduate=bool(re.search(r'cao học|học viên|nghiên cứu sinh|\bhv\b|\bncs\b',question))
    rules=[]
    for index,hit in enumerate(context):
        section=re.search(r'đăng ký môn học\s+đợt\s+'+phase[1]+r'\b(.*?)(?=đăng ký môn học\s+đợt\s+\d+|$)',hit['text'],re.I)
        if not section:continue
        pattern=(r'(?:HV\s*/\s*NCS)\s+tối đa\s+(\d+)\s+tín chỉ' if postgraduate
                 else r'\bSV\s+đăng ký[^.!?()]{0,300}?tối đa\s+(\d+)\s+tín chỉ')
        rule=re.search(pattern,section[0],re.I)
        if rule:rules.append((int(rule[1]),index,rule[0]))
    if not rules or len({r[0] for r in rules})!=1:return None
    limit,index,quote=rules[0];amount=int(amount[1])
    # A maximum can prove rejection, but being below it does not prove all prerequisites.
    if amount<=limit:return None
    role='học viên/nghiên cứu sinh' if postgraduate else 'sinh viên'
    marker=f'S{index+1}'
    return {'answer':f'Không. Đối với {role}, đợt {phase[1]} tối đa {limit} tín chỉ; đăng ký {amount} tín chỉ vượt giới hạn này. [{marker}]',
            'source_markers':[marker],'no_answer':False,'supporting_evidence':[{'source':marker,'quote':quote}]}


def minimum_credit_answer(question,context):
    if not minimum_credit_question(question):return None
    rules=[];consequences=[];numeric=[]
    for index,hit in enumerate(context):
        for sentence in re.split(r'(?<=[.!?])\s+|\n+',hit['text']):
            sentence=sentence.strip()
            if '?' in sentence or 'tối thiểu' not in sentence.lower():continue
            text=sentence.lower()
            if 'tín chỉ' not in text:continue
            found=re.search(r'(?:tối thiểu|ít nhất)\s*(?:là\s*)?(\d+)\s*tín chỉ|(\d+)\s*tín chỉ\s*tối thiểu',text)
            if found:numeric.append((int(found[1] or found[2]),index,sentence))
            if re.search(r'sau khi\s+(?:rút|hủy)',text) and re.search(r'phải|đảm bảo',text):
                rules.append((index,sentence))
            if re.search(r'(?:không đúng|không đủ|dưới).{0,100}(?:sẽ bị|bị tạm dừng|bị buộc)',text):
                consequences.append((index,sentence))
    selected=[]
    for group in (rules,consequences):
        if group:selected.append(group[0])
    distinct_limits=set()
    for limit,index,quote in numeric:
        if limit not in distinct_limits and (index,quote) not in selected:selected.append((index,quote))
        distinct_limits.add(limit)
    if not selected:
        return {'answer':'Chưa tìm thấy quy định đủ rõ về số tín chỉ tối thiểu và hậu quả sau khi hủy/rút môn trong các đoạn đã truy hồi. Cần đối chiếu quy định áp dụng cho chương trình và học kỳ của bạn.',
                'source_markers':[],'no_answer':True}
    paragraphs=[];markers=[];evidence=[]
    for index,quote in selected:
        marker=f'S{index+1}'
        prefix='Nếu bạn đang nói đến rút môn, nguồn quy định: ' if (index,quote) in rules else 'Tài liệu nêu: '
        paragraphs.append(prefix+'“'+quote+'” '+f'[{marker}]')
        if marker not in markers:markers.append(marker)
        evidence.append({'source':marker,'quote':quote})
    amount=re.search(r'(?:dưới|ít hơn|còn)\s+(\d+)\s*tín chỉ',normalize_question(question))
    if len({n[0] for n in numeric})>1:
        paragraphs.append('Các đoạn nguồn nêu nhiều mức tối thiểu; cần biết chương trình và học kỳ để xác định mức áp dụng, chưa thể kết luận trường hợp của bạn.')
    elif not numeric:
        missing=f'chưa nêu mức tối thiểu cụ thể là {amount[1]} tín chỉ' if amount else 'chưa nêu mức tối thiểu bằng số'
        paragraphs.append(f'Các đoạn nguồn này {missing}. Cần đối chiếu quy định áp dụng cho chương trình và học kỳ của bạn; chưa thể kết luận trường hợp cụ thể.')
    else:
        paragraphs.append('Cần đối chiếu mức tối thiểu với chương trình, học kỳ và số tín chỉ thực tế còn lại; không thể suy ra kết quả chỉ từ một cận “dưới” trong câu hỏi.')
    return {'answer':'\n\n'.join(paragraphs),'source_markers':markers,'no_answer':False,'supporting_evidence':evidence}


def structured_answer(question, context):
    from .annual_requirements import annual_answer
    return annual_answer(question,context) or minimum_credit_answer(question,context) or table_lookup(question,context) or credit_limit(question,context)

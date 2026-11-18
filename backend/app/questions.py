"""Conservative normalization: preserve numbers, negation and the original question."""
import re
import unicodedata


def normalize_question(question):
    text = unicodedata.normalize('NFC', question).lower().strip(' \t\n“”"')
    text = text.replace('đợt đăng ký môn học thứ nhất','đợt 1 đăng ký môn học')
    replacements = {
        'ko': 'không', 'khum': 'không', 'hông': 'không', 'hong': 'không',
        'dc': 'được', 'đc': 'được', 'đk': 'đăng ký', 'đkmh': 'đăng ký môn học',
        'tkb': 'thời khóa biểu', 'tb': 'trung bình',
        'ccnn': 'chứng chỉ ngoại ngữ',
        'datn': 'đồ án tốt nghiệp', 'đatn': 'đồ án tốt nghiệp',
        'dacn': 'đồ án chuyên ngành', 'đacn': 'đồ án chuyên ngành',
        'lvtn': 'luận văn tốt nghiệp', 'kltn': 'khóa luận tốt nghiệp',
    }
    for word, replacement in replacements.items():
        text = re.sub(r'\b' + word + r'\b', replacement, text)
    text = text.replace('khoá', 'khóa')
    text = re.sub(r'\bk\s*(20\d{2})\b', r'khóa \1', text)
    text = re.sub(r'\b(?:khóa\s+k\s*|k\s*)(\d{2})(?!\d)', r'khóa 20\1', text)
    text = re.sub(r'\b(\d+)\s+(?:chỉ|tín(?!\s+chỉ\b))\b', r'\1 tín chỉ', text)
    # Interpret slang only when its object explicitly concerns course credits.
    text = re.sub(r'\bquất(?=\s+\d+\s+tín chỉ\b)', 'đăng ký', text)
    text = re.sub(r'\b(\d+(?:[.,]\d+)?)\s+chấm\b', lambda m: (m[1] if re.search(r'[.,]',m[1]) else m[1]+'.0')+' điểm', text)
    if re.search(r'\bđợt\s+\d+\b', text) and 'tín chỉ' in text and 'môn học' not in text:
        text = re.sub(r'\bđăng ký\b', 'đăng ký môn học', text)
    return re.sub(r'\s+', ' ', text).strip()


def annual_language_requirement(question):
    text=normalize_question(question)
    language=bool(re.search(r'anh văn|tiếng anh|ngoại ngữ|\bccas[_ -]?\d?',text))
    annual=bool(re.search(r'(?:các|từng|hàng)\s+năm|năm\s+(?:thứ\s+)?(?:[1-4]|nhất|hai|ba|tư)\b|\bccas[_ -]?\d',text))
    procedural=bool(re.search(r'làm thế nào|làm sao|cách đạt|cách hoàn thành|nộp|ở đâu',text))
    return language and annual and not procedural


def minimum_credit_question(question):
    text=normalize_question(question)
    return bool(re.search(r'\b(?:hủy|rút)\b',text) and 'môn' in text
                and re.search(r'tín chỉ|\btín\b',text) and re.search(r'dưới|ít hơn|tối thiểu|còn\s+\d',text))


def requests_explanation(question):
    return bool(re.search(r'giải thích|nói rõ|làm rõ|chi tiết|ví dụ|vì sao|tại sao|ý nghĩa|phân tích',normalize_question(question)))


def annual_evidence_matches(question,sentence):
    if not question or not annual_language_requirement(question):return True
    from .annual_requirements import requested_year,requirements
    year=requested_year(question)
    return any(not year or r['year']==year for r in requirements(sentence))


def retrieval_question(question):
    text=normalize_question(question)
    if re.search(r'toeic|ielts|ngoại ngữ|anh văn|tiếng anh',text):
        if 'đồ án chuyên ngành' in text:
            return text+'; điều kiện ngoại ngữ đăng ký đồ án chuyên ngành C_ĐACN'
        if re.search(r'(?:đồ án|luận văn|khóa luận) tốt nghiệp',text):
            return text+'; chuẩn ngoại ngữ khi đăng ký luận văn tốt nghiệp khóa luận tốt nghiệp CCAV_1 C_LVTN'
    if minimum_credit_question(text):
        return text+'; điều kiện rút môn học, số tín chỉ tối thiểu của học kỳ'
    if annual_language_requirement(text):
        return text+'; chuẩn ngoại ngữ từng năm học CCAS'
    return text


def clarification_for(question):
    text = normalize_question(question)
    # Bare demonstratives have no referent in a standalone query. In a
    # conversation, resolve_question has already supplied the missing subject.
    if len(text.split())<=18 and re.search(r'cái (?:giấy|đó|này)|giấy đó|năm đó|mức này|đợt kia|đợt này|đổi vậy',text):
        if not re.search(r'ielts|toeic|vstep|học phí|ngoại ngữ|đăng ký môn|đợt\s+\d|năm\s+\d',text):
            return 'Bạn cho biết rõ loại giấy tờ, mức điểm, năm học hoặc đợt đăng ký đang muốn hỏi nhé. Mình chưa có đủ ngữ cảnh để áp dụng đúng quy định.'
    certificate = re.search(r'\b(ielts|vstep|vnu[ -]?ept|toeic|toefl|tcf|delf)\b', text)
    if (not certificate and re.search(r'\bmiễn\b', text)
            and re.search(r'\b\d+(?:[.,]\d+)?\s+(?:điểm|chấm|miễn)\b', text)):
        return 'Bạn đang hỏi mức điểm của chứng chỉ nào, ví dụ VSTEP hay IELTS?'
    if re.fullmatch(r'(?:đổi|đổi nhóm)(?:\s+(?:được|đc|dc|nữa|không|chứ|vậy|ạ|có))*[?.!]*', text):
        return 'Bạn muốn đổi gì và đang ở đợt đăng ký nào? Nếu đổi nhóm môn học, bạn cho biết đợt 2 hay đợt 3 nhé.'
    if not certificate and re.search(r'chứng chỉ (?:này|đó)', text):
        return 'Bạn đang hỏi loại chứng chỉ nào và muốn dùng để xét miễn môn học hay xét tốt nghiệp?'
    if (not certificate and 'chứng chỉ' in text and not re.search(r'ngoại ngữ|tiếng anh|tiếng pháp|công nghệ|tin học',text)
            and re.search(r'còn hạn|hiệu lực',text)):
        return 'Bạn đang hỏi chứng chỉ ngoại ngữ hay loại chứng chỉ nào? Mình cần biết loại chứng chỉ để áp dụng đúng quy định thời hạn nộp.'
    return None


def unavailable_personal_answer(question):
    text=normalize_question(question)
    if re.search(r'mật khẩu|mã (?:otp|xác thực|đăng nhập)|\botp\b',text) and not re.search(r'cách|hướng dẫn|quên|đổi|khôi phục|bảo vệ',text):
        return 'Mình không có quyền truy cập mật khẩu hay mã xác thực của bất kỳ ai và không thể cung cấp hoặc suy đoán thông tin đó.'
    if re.search(r'bỏ qua|vượt qua|vô hiệu',text) and re.search(r'quyền|phân quyền|bảo mật',text):
        return 'Mình chỉ tra cứu tài liệu tài khoản hiện tại được phép đọc; không thể bỏ qua phân quyền hoặc xuất nguồn riêng tư trái quyền.'
    if re.search(r'mã số sinh viên\s+(?:của\s+)?(?:tôi|em|mình)\b',text):
        return 'Mình chưa có hồ sơ cá nhân hoặc thời khóa biểu của bạn trong dữ liệu được cung cấp, nên không thể xác định mã số sinh viên hay các môn bạn đã đăng ký.'
    return None


def only_repeats_question(answer, question):
    def comparable(text):
        text = re.sub(r'\[S\d+\]', '', text)
        return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', normalize_question(text))).strip()
    return bool(comparable(question)) and comparable(answer) == comparable(question)

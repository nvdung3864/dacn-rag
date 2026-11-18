"""Run live RAG checks without adding questions to user history.

Usage: python -m app.check_answers --output /reports/live-answers.json
Requires an existing active admin and indexed PDF documents. Results need human grading.
"""
import argparse
import json
import time
from pathlib import Path
from sqlalchemy import select
from .db import Session
from .models import User, Document
from .rag import retrieve, answer_from_context
from .questions import clarification_for, unavailable_personal_answer
from .config import settings, ANSWER_REVISION


CASES = [
    ('slang', 'Đợt 1 quất 26 chỉ được hông?', 'Không; SV tối đa 25 tín chỉ, HV/NCS 20. Quy trình ĐKMH tr.3.'),
    ('formal', 'Sinh viên đăng ký 26 tín chỉ trong đợt đăng ký môn học thứ nhất có được không?', 'Không; giới hạn 25 tín chỉ. Quy trình ĐKMH tr.3.'),
    ('ambiguous', '5 chấm miễn được gì?', 'Hỏi rõ loại chứng chỉ; không có citation.'),
    ('credits', 'Miễn anh văn rồi có cộng tín chỉ ko, có kéo điểm tb lên không?', 'Có tín chỉ tích lũy, không tính điểm trung bình. Không tự thêm ngày 29/8. Ngoại ngữ tr.4/6.'),
    ('home-edition', 'TOEFL thi ở nhà có dùng xét tốt nghiệp được ko?', 'TOEFL iBT Home Edition không được dùng xét tốt nghiệp. Ngoại ngữ tr.9.'),
    ('round3', 'Đợt 3 rồi đổi nhóm dc ko?', 'Không hủy môn hoặc đổi nhóm. Quy trình ĐKMH tr.6.'),
    ('table', 'VSTEP 5 chấm thì miễn tới anh văn mấy?', 'Anh văn 1, 2, 3; không Anh văn 4. Ngoại ngữ tr.8.'),
    ('missing-object', 'Đổi được không?', 'Hỏi rõ muốn đổi gì và ở đợt nào; không có citation.'),
    ('certificate-validity', 'Chứng chỉ còn hạn có 2 tuần, nộp giờ được không?', 'Phải còn hiệu lực ít nhất 1 tháng khi nộp. Ngoại ngữ tr.3.'),
    ('personal', 'Mã số sinh viên của tôi là gì và học kỳ này tôi đăng ký những môn nào?', 'Không đủ thông tin cá nhân; không bịa mã số hay danh sách môn.'),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--limit', type=int, default=len(CASES))
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'answer_revision': ANSWER_REVISION, 'model': settings.llm_model,
              'grading': 'UNREVIEWED: human assessment required; not an accuracy benchmark', 'cases': []}
    with Session() as db:
        user = db.scalar(select(User).where(User.active.is_(True), User.role == 'admin').order_by(User.id))
        if not user:
            raise SystemExit('No active admin; refusing to invent a user or bypass permissions.')
        source_ids = list(db.scalars(select(Document.source_id).where(Document.status == 'INDEXED', Document.format == 'PDF').distinct()))
        if not source_ids:
            raise SystemExit('No indexed PDFs. Upload and index the three PDFs first.')
        for name, question, expected in CASES[:args.limit]:
            started = time.perf_counter()
            entry = {'id': name, 'question': question, 'expected': expected}
            try:
                hits, timing = ([], {}) if clarification_for(question) or unavailable_personal_answer(question) else retrieve(db, user, question, 5, source_ids)
                result, generation_ms = answer_from_context(question, hits)
                entry.update(result=result, retrieval=hits, timing={**timing, 'generation_ms': generation_ms})
            except Exception as exc:
                entry['error'] = f'{type(exc).__name__}: {exc}'
            entry['elapsed_seconds'] = round(time.perf_counter() - started, 2)
            report['cases'].append(entry)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'id':name,'answer':entry.get('result',{}).get('answer'),'error':entry.get('error'),'elapsed_seconds':entry['elapsed_seconds']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

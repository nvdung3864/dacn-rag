"""Small live smoke check; run inside the backend container."""
import httpx
from .config import settings
from .providers import embed,ProviderError
from .rag import answer_from_context

def main():
    if settings.provider!='ollama':raise SystemExit('Chưa chọn local. Chạy scripts/use-local-models.py rồi rebuild backend.')
    try:
        with httpx.Client(timeout=15) as client:
            response=client.get(settings.provider_url.rstrip('/')+'/api/tags')
            response.raise_for_status()
            names={m['name'] for m in response.json().get('models',[])}
        missing=[m for m in (settings.embedding_model,settings.llm_model) if m not in names]
        if missing:raise SystemExit('Chưa tải model: '+', '.join(missing)+'. Chạy ollama pull cho từng model.')
        print('OK: backend kết nối Ollama và tìm thấy cả hai model.',flush=True)
        vector=embed(['RAG truy xuất tài liệu rồi tạo câu trả lời.'])[0]
        print(f'OK: embedding có {len(vector)} chiều.',flush=True)
        obj,_=answer_from_context('RAG hoạt động như thế nào?',[{'title':'Tài liệu thử','text':'RAG tìm các đoạn liên quan trong tài liệu rồi dùng chúng làm ngữ cảnh để tạo câu trả lời.','score':1.0,'chunk_id':'smoke-test-only','document_id':'smoke-test-only','version':1}])
        if obj['no_answer'] or not obj['citations']:raise ProviderError('Model chưa trả lời có nguồn cho đoạn thử.')
        print('OK: câu trả lời qua kiểm tra định dạng và trích nguồn.',flush=True)
        print('Câu trả lời thử: '+obj['answer'],flush=True)
        print('Tiếp theo: mở web và hỏi lại. Bản vá citation không cần xử lý lại tài liệu.')
    except (httpx.HTTPError,ValueError,KeyError) as exc:
        raise SystemExit('Không kết nối được Ollama hoặc phản hồi sai định dạng. Kiểm tra Ollama đang mở, địa chỉ host.docker.internal và firewall Windows.') from None
    except ProviderError as exc:raise SystemExit(str(exc)) from None

if __name__=='__main__':main()

# ĐACN RAG

Ứng dụng web quản lý tài liệu và hỏi đáp có trích dẫn. Frontend dùng React, backend dùng FastAPI, PostgreSQL/pgvector lưu dữ liệu và Ollama chạy model local. Phiên bản hiện tại: `qa-v13`.

## Chạy trên Windows

Cần Docker Desktop. Nếu dùng Ollama, cài ứng dụng rồi tải model:

```powershell
ollama pull qwen3.5:9b-q4_K_M
ollama pull qwen3-embedding:0.6b
```

Tạo file cấu hình từ mẫu:

```powershell
Copy-Item .env.example .env
```

Mở `.env`, thay các giá trị mẫu của `POSTGRES_PASSWORD` và `JWT_SECRET` bằng secret riêng. Mật khẩu trong `DATABASE_URL` phải giống `POSTGRES_PASSWORD`. Với Ollama trên Windows, đặt các giá trị model như sau:

```env
MODEL_PROVIDER=ollama
MODEL_BASE_URL=http://host.docker.internal:11434
MODEL_API_KEY=
LLM_MODEL=qwen3.5:9b-q4_K_M
EMBEDDING_MODEL=qwen3-embedding:0.6b
EMBEDDING_DIM=1024
ANSWER_ENGINE=grounded
```

Không đưa `.env` lên GitHub. Khởi động ứng dụng:

```powershell
docker compose up --build -d --wait
docker compose exec backend python -m app.check_models
```

Web chạy tại http://localhost:8080, API docs tại http://localhost:8000/docs. Nếu đây là database mới, tạo tài khoản quản trị một lần:

```powershell
docker compose exec backend python -m app.bootstrap --email admin@example.com --name "Quản trị viên"
```

Lệnh yêu cầu nhập mật khẩu trong terminal. Không chạy lại nếu đã có tài khoản.

## Cập nhật hoặc dừng ứng dụng

Để cập nhật mã, chạy lại `docker compose up --build -d --wait`. Giữ nguyên `.env` và Docker volumes nếu cần giữ tài khoản, database và file đã tải lên. Tránh `docker compose down -v`: lệnh này xóa dữ liệu trong volumes.

`/api/ready` chỉ kiểm tra kết nối database. Dùng `docker compose exec backend python -m app.check_models` để kiểm tra Ollama và model.

## Cấu hình hiện tại

Máy phát triển dùng `qwen3.5:9b-q4_K_M` để trả lời và `qwen3-embedding:0.6b` để tạo embedding 1024 chiều. Cấu hình truy xuất mặc định: chunk 400, overlap 60, top-k 5 và ngưỡng cosine 0.25. Các giá trị cấu hình nằm trong `.env`; model khác có thể cho tốc độ và chất lượng khác.

Đổi model embedding hoặc số chiều thì cần xử lý lại tài liệu để tạo vector tương thích. `CONFIG_VERSION` là nhãn cấu hình model, không phải phiên bản mã nguồn.

## Chức năng và giới hạn

- Tải PDF có lớp văn bản, DOCX và TXT; xử lý tài liệu và trả lời kèm trích dẫn.
- Quản lý nguồn WEB/FILE, người dùng và quyền truy cập. Đồng bộ WEB chỉ lấy nội dung công khai trong allowlist.
- Hỗ trợ hội thoại nhiều lượt, lịch sử, phản hồi câu trả lời, trang vận hành và đánh giá.
- PDF scan chưa có OCR. Đây là bản chạy local, chưa có SSO hay triển khai nhiều máy.

Trích dẫn giúp đối chiếu câu trả lời với tài liệu, nhưng không tự chứng minh nội dung trả lời là đúng.

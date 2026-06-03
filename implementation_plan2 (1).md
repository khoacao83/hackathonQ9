# Tích hợp luồng chạy với VS Code Copilot LM API & Cơ chế Mock/Fallback

Nâng cấp VS Code Extension ở thư mục [vscode-extension/](file:///home/caokhoa/hkt-Q9/hackathonQ9/vscode-extension) để tích hợp gọi mô hình GitHub Copilot (Claude 3.5 Sonnet / GPT-4o) theo đặc tả Giai đoạn 2 (Phase 2). Do hiện tại người dùng chưa thể đăng nhập Copilot trên môi trường phát triển, chúng tôi sẽ xây dựng cơ chế Mock/Fallback thông minh trực tiếp trong Extension để giả lập phản hồi của Copilot, giúp chạy thử nghiệm toàn bộ luồng tự phục hồi (Self-Healing) với dự án demo hiện tại.

## User Review Required

> [!NOTE]
> Dự án mẫu (Demo Project) hiện có trong mã nguồn là `report_service.py` (chức năng xuất báo cáo) thay vì dịch vụ ngân hàng `payment_service.py` (vốn được mô tả trong file `README copy.md` cũ). Chúng tôi sẽ giữ nguyên demo `report_service.py` vì đây là mã nguồn thực tế đang tồn tại trong thư mục [demo_project/](file:///home/caokhoa/hkt-Q9/hackathonQ9/demo_project) và các tài liệu PDF đi kèm. Cấu trúc Mock/Fallback của Extension sẽ sinh các bản vá phù hợp cho `report_service.py`.

## Proposed Changes

### VS Code Extension

#### [MODIFY] [extension.js](file:///home/caokhoa/hkt-Q9/hackathonQ9/vscode-extension/extension.js)
- Cập nhật logic tìm kiếm model Copilot bằng cách tìm kiếm thứ tự ưu tiên: Claude 3.5 Sonnet -> GPT-4o -> Bất kỳ model Copilot nào có sẵn.
- Triển khai cơ chế đọc `outputs/run_log.json` khi chạy để phát hiện lần chạy trước đó có lỗi không (phục vụ tự động gửi error summary cho Copilot hoặc giả lập lần vá thứ 2 cho Mock).
- Xây dựng hàm `generateMockPatch` trong Extension để sinh bản vá thử nghiệm khi không thể kết nối Copilot (chưa đăng nhập):
  - **Lần 1**: Sinh bản vá chỉ sửa lỗi mảng rỗng (vẫn lỗi khi gặp `None`).
  - **Lần 2 (Sửa lỗi)**: Đọc từ `run_log.json` thấy trạng thái cũ thất bại, sinh bản vá kiểm tra đầy đủ `None` và mảng rỗng.
- Cập nhật cấu trúc Prompt trong `buildPrompt` để truyền thêm thông tin `errorSummary` của lần thất bại trước vào prompt gửi cho Copilot (nếu đã đăng nhập).

## Verification Plan

### Automated Tests
- Kiểm thử tích hợp chạy luồng extension bằng môi trường Extension Development Host (F5):
  - Chạy lần 1: Đảm bảo sinh ra file `.tmp/copilot_patch.diff` chỉ xử lý `len(data) == 0`. Pipeline Python chạy báo lỗi `pytest` thất bại và xuất ra `outputs/run_log.json` trạng thái `FAILED`.
  - Chạy lần 2: Đảm bảo extension đọc được `run_log.json` lỗi từ lần 1, sinh tiếp bản vá xử lý cả `data is None`, chạy Pipeline Python thành công và báo trạng thái `PASSED`.

### Manual Verification
- Xác nhận các tệp tin log và evidence trong thư mục `outputs/` được ghi nhận chính xác sau từng lần chạy thử.

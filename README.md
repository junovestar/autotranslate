# 🎬 Auto Translate Video

Ứng dụng web tự động dịch video từ tiếng Anh sang tiếng Việt.

## 🚀 Cách sử dụng

1. **Double-click** vào file `start.bat`
2. **Chờ** cài đặt dependencies
3. **Mở trình duyệt**: http://localhost:5000
4. **Nhập URL video** và bắt đầu xử lý

## ⚙️ Cấu hình

Vào **Settings** (⚙️) để cấu hình:
- **AI Provider**: Gemini hoặc DeepSeek
- **API Keys**: ElevenLabs, AssemblyAI
- **Voice Settings**: Giọng nói, ngôn ngữ

## 📁 Cấu trúc

- `start.bat` - File khởi động
- `web_app.py` - Ứng dụng chính
- `pipeline.py` - Xử lý video
- `templates/` - Giao diện web
- `projects/` - Thư mục lưu dự án

## 🔧 Yêu cầu

- Python 3.8+
- FFmpeg
- Internet connection
- API Keys (ElevenLabs, AssemblyAI, Gemini/DeepSeek)

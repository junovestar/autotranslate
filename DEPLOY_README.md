# 🚀 Auto Translate Video - Deploy Guide

## 📁 Files Deploy

Dự án này bao gồm các file deploy hoàn chỉnh:

### 1. `deploy.sh` - Script Deploy Chính
- **Chức năng**: Deploy tự động toàn bộ ứng dụng lên Ubuntu server
- **Tính năng**:
  - Cài đặt tất cả dependencies (Python, FFmpeg, Nginx, etc.)
  - Tạo user và thư mục ứng dụng
  - Cấu hình Gunicorn + Nginx
  - Tự động lấy SSL certificate từ Let's Encrypt
  - Tạo systemd service
  - Cấu hình firewall
  - Tạo scripts quản lý

### 2. `DEPLOY_GUIDE.md` - Hướng Dẫn Chi Tiết
- **Chức năng**: Hướng dẫn từng bước deploy
- **Nội dung**:
  - Yêu cầu hệ thống
  - Chuẩn bị server
  - Các bước deploy
  - Troubleshooting
  - Monitoring và bảo mật

### 3. `health_check.sh` - Script Kiểm Tra Sức Khỏe
- **Chức năng**: Kiểm tra toàn diện hệ thống sau deploy
- **Tính năng**:
  - Kiểm tra tài nguyên (CPU, RAM, Disk)
  - Kiểm tra services (Nginx, Gunicorn, Application)
  - Kiểm tra ports và SSL
  - Kiểm tra logs và errors
  - Kiểm tra dependencies

## 🎯 Cách Sử Dụng

### Bước 1: Chuẩn Bị Server
```bash
# Kết nối SSH vào Ubuntu server
ssh username@your-server-ip

# Tạo user deploy (khuyến nghị)
sudo adduser deploy
sudo usermod -aG sudo deploy
su - deploy
```

### Bước 2: Upload Code
```bash
# Từ máy local, upload toàn bộ project
scp -r . deploy@your-server-ip:/home/deploy/auto-translate-video
```

### Bước 3: Deploy
```bash
# SSH vào server
ssh deploy@your-server-ip

# Di chuyển vào thư mục project
cd auto-translate-video

# Cấp quyền thực thi
chmod +x deploy.sh

# Chạy deploy
./deploy.sh
```

### Bước 4: Cấu Hình API Keys
```bash
# Chỉnh sửa file environment
sudo nano /opt/auto-translate-video/.env

# Cập nhật các API keys:
FPT_API_KEY=your_actual_fpt_api_key
GEMINI_API_KEY=your_actual_gemini_api_key
ASSEMBLYAI_API_KEY=your_actual_assemblyai_api_key

# Khởi động lại ứng dụng
sudo /opt/auto-translate-video/manage.sh restart
```

### Bước 5: Kiểm Tra
```bash
# Chạy health check
chmod +x health_check.sh
./health_check.sh

# Truy cập website
# https://your-domain.com
```

## 🔧 Quản Lý Ứng Dụng

### Scripts Quản Lý (tự động tạo bởi deploy.sh):

```bash
# Khởi động ứng dụng
sudo /opt/auto-translate-video/manage.sh start

# Dừng ứng dụng
sudo /opt/auto-translate-video/manage.sh stop

# Khởi động lại
sudo /opt/auto-translate-video/manage.sh restart

# Xem trạng thái
sudo /opt/auto-translate-video/manage.sh status

# Xem logs
sudo /opt/auto-translate-video/manage.sh logs

# Cập nhật ứng dụng
sudo /opt/auto-translate-video/manage.sh update

# Gia hạn SSL
sudo /opt/auto-translate-video/manage.sh ssl-renew
```

### Backup:
```bash
# Backup thủ công
sudo /opt/auto-translate-video/backup.sh

# Backup tự động (thêm vào crontab)
echo "0 2 * * * sudo /opt/auto-translate-video/backup.sh" | crontab -
```

## 📋 Yêu Cầu Hệ Thống

### Server:
- **OS**: Ubuntu 20.04 LTS hoặc 22.04 LTS
- **RAM**: Tối thiểu 2GB (khuyến nghị 4GB+)
- **Storage**: Tối thiểu 20GB (khuyến nghị 50GB+)
- **CPU**: 2 cores trở lên
- **Network**: Kết nối internet ổn định

### Domain:
- **Domain name**: Đã trỏ về IP server
- **SSL**: Tự động từ Let's Encrypt

## 🛠️ Cấu Trúc Sau Deploy

```
/opt/auto-translate-video/
├── web_app.py              # Ứng dụng chính
├── pipeline.py             # Xử lý video
├── templates/              # Giao diện web
├── venv/                   # Python virtual environment
├── projects/               # Thư mục dự án
├── logs/                   # Logs ứng dụng
├── uploads/                # Files upload
├── temp/                   # Files tạm
├── .env                    # Cấu hình environment
├── gunicorn.conf.py        # Cấu hình Gunicorn
├── manage.sh               # Script quản lý
├── backup.sh               # Script backup
└── start.sh                # Script khởi động
```

## 🔍 Troubleshooting

### Lỗi Thường Gặp:

1. **Lỗi Permission**
```bash
sudo chown -R appuser:appuser /opt/auto-translate-video
```

2. **Lỗi Port đã sử dụng**
```bash
sudo systemctl restart auto-translate-video
```

3. **Lỗi SSL**
```bash
sudo certbot --nginx -d your-domain.com
```

4. **Lỗi FFmpeg**
```bash
sudo apt install ffmpeg
```

### Kiểm Tra Logs:
```bash
# Logs ứng dụng
sudo journalctl -u auto-translate-video -f

# Logs Nginx
sudo tail -f /var/log/nginx/error.log

# Logs Gunicorn
sudo tail -f /opt/auto-translate-video/logs/gunicorn_error.log
```

## 📊 Monitoring

### Kiểm Tra Tài Nguyên:
```bash
# CPU và RAM
htop

# Disk usage
df -h

# Process status
ps aux | grep gunicorn
```

### Health Check Định Kỳ:
```bash
# Chạy health check
./health_check.sh

# Thêm vào crontab để chạy hàng ngày
echo "0 6 * * * cd /opt/auto-translate-video && ./health_check.sh" | crontab -
```

## 🔒 Bảo Mật

### Firewall:
```bash
sudo ufw status
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
```

### Fail2ban (khuyến nghị):
```bash
sudo apt install fail2ban
sudo systemctl enable fail2ban
```

### Updates:
```bash
# Cập nhật hệ thống định kỳ
sudo apt update && sudo apt upgrade -y
```

## 📈 Scaling

### Tăng Workers:
```bash
sudo nano /opt/auto-translate-video/gunicorn.conf.py
# Thay đổi: workers = 4
sudo /opt/auto-translate-video/manage.sh restart
```

### Tăng Timeout:
```bash
sudo nano /opt/auto-translate-video/gunicorn.conf.py
# Thay đổi: timeout = 600
sudo /opt/auto-translate-video/manage.sh restart
```

## 🎉 Kết Quả

Sau khi deploy thành công:
- ✅ Website hoạt động tại `https://your-domain.com`
- ✅ SSL certificate tự động
- ✅ Systemd service tự khởi động
- ✅ Backup tự động
- ✅ Monitoring và health check
- ✅ Scripts quản lý đầy đủ

## 📞 Hỗ Trợ

Khi gặp vấn đề:
1. Chạy `health_check.sh` để kiểm tra
2. Xem logs: `sudo /opt/auto-translate-video/manage.sh logs`
3. Restart service: `sudo /opt/auto-translate-video/manage.sh restart`
4. Kiểm tra tài nguyên: `htop`, `df -h`

---

**🎯 Mục Tiêu**: Deploy hoàn chỉnh từ A-Z với tất cả tính năng cần thiết cho production environment.

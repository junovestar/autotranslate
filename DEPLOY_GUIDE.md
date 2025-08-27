# 🚀 Hướng Dẫn Deploy Auto Translate Video lên Ubuntu Server

## 📋 Yêu Cầu Hệ Thống

### Server Requirements
- **OS**: Ubuntu 20.04 LTS hoặc 22.04 LTS
- **RAM**: Tối thiểu 2GB (khuyến nghị 4GB+)
- **Storage**: Tối thiểu 20GB (khuyến nghị 50GB+)
- **CPU**: 2 cores trở lên
- **Network**: Kết nối internet ổn định

### Domain & SSL
- **Domain name**: Đã trỏ về IP server
- **SSL Certificate**: Tự động từ Let's Encrypt

## 🔧 Chuẩn Bị Server

### 1. Kết nối SSH vào server
```bash
ssh username@your-server-ip
```

### 2. Tạo user mới (khuyến nghị)
```bash
sudo adduser deploy
sudo usermod -aG sudo deploy
su - deploy
```

### 3. Cập nhật hệ thống
```bash
sudo apt update && sudo apt upgrade -y
```

## 📦 Deploy Tự Động

### Bước 1: Upload code lên server
```bash
# Từ máy local, upload toàn bộ project
scp -r . deploy@your-server-ip:/home/deploy/auto-translate-video
```

### Bước 2: Chạy script deploy
```bash
# SSH vào server
ssh deploy@your-server-ip

# Di chuyển vào thư mục project
cd auto-translate-video

# Cấp quyền thực thi cho script
chmod +x deploy.sh

# Chạy script deploy
./deploy.sh
```

### Bước 3: Nhập thông tin khi được hỏi
- **Domain name**: Ví dụ: `translate.example.com`
- **Email**: Email của bạn (cho SSL certificate)

## ⚙️ Cấu Hình Sau Deploy

### 1. Cập nhật API Keys
```bash
sudo nano /opt/auto-translate-video/.env
```

Cập nhật các API keys:
```env
FPT_API_KEY=your_actual_fpt_api_key
GEMINI_API_KEY=your_actual_gemini_api_key
ASSEMBLYAI_API_KEY=your_actual_assemblyai_api_key
```

### 2. Khởi động lại ứng dụng
```bash
sudo /opt/auto-translate-video/manage.sh restart
```

## 🔧 Quản Lý Ứng Dụng

### Các lệnh quản lý cơ bản:
```bash
# Khởi động ứng dụng
sudo /opt/auto-translate-video/manage.sh start

# Dừng ứng dụng
sudo /opt/auto-translate-video/manage.sh stop

# Khởi động lại ứng dụng
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

### Backup dữ liệu:
```bash
# Tạo backup thủ công
sudo /opt/auto-translate-video/backup.sh

# Backup tự động (thêm vào crontab)
echo "0 2 * * * sudo /opt/auto-translate-video/backup.sh" | crontab -
```

## 🌐 Kiểm Tra Website

### 1. Truy cập website
Mở trình duyệt và truy cập: `https://your-domain.com`

### 2. Kiểm tra các tính năng:
- ✅ Upload video
- ✅ Xử lý video
- ✅ Download kết quả
- ✅ Cài đặt API keys

## 🔍 Troubleshooting

### Kiểm tra logs:
```bash
# Logs ứng dụng
sudo journalctl -u auto-translate-video -f

# Logs Nginx
sudo tail -f /var/log/nginx/error.log

# Logs Gunicorn
sudo tail -f /opt/auto-translate-video/logs/gunicorn_error.log
```

### Các lỗi thường gặp:

#### 1. Lỗi Permission
```bash
sudo chown -R appuser:appuser /opt/auto-translate-video
sudo chmod -R 755 /opt/auto-translate-video
```

#### 2. Lỗi Port đã được sử dụng
```bash
sudo netstat -tlnp | grep :8000
sudo systemctl restart auto-translate-video
```

#### 3. Lỗi SSL Certificate
```bash
sudo certbot --nginx -d your-domain.com
```

#### 4. Lỗi FFmpeg
```bash
sudo apt install ffmpeg
```

## 📊 Monitoring

### Kiểm tra tài nguyên:
```bash
# CPU và RAM
htop

# Disk usage
df -h

# Process status
ps aux | grep gunicorn
```

### Monitoring logs:
```bash
# Theo dõi logs real-time
sudo tail -f /opt/auto-translate-video/logs/gunicorn_access.log
```

## 🔒 Bảo Mật

### 1. Firewall
```bash
# Kiểm tra firewall
sudo ufw status

# Mở port cần thiết
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
```

### 2. Fail2ban (khuyến nghị)
```bash
sudo apt install fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### 3. Regular updates
```bash
# Cập nhật hệ thống định kỳ
sudo apt update && sudo apt upgrade -y
```

## 📈 Scaling

### Tăng workers cho Gunicorn:
```bash
sudo nano /opt/auto-translate-video/gunicorn.conf.py
```

Thay đổi:
```python
workers = 4  # Tăng từ 2 lên 4
```

Khởi động lại:
```bash
sudo /opt/auto-translate-video/manage.sh restart
```

### Tăng timeout cho video lớn:
```bash
sudo nano /opt/auto-translate-video/gunicorn.conf.py
```

Thay đổi:
```python
timeout = 600  # Tăng từ 300 lên 600 giây
```

## 🆘 Hỗ Trợ

### Khi gặp vấn đề:
1. Kiểm tra logs: `sudo /opt/auto-translate-video/manage.sh logs`
2. Kiểm tra trạng thái: `sudo /opt/auto-translate-video/manage.sh status`
3. Restart service: `sudo /opt/auto-translate-video/manage.sh restart`
4. Kiểm tra tài nguyên: `htop`, `df -h`

### Backup và restore:
```bash
# Backup
sudo /opt/auto-translate-video/backup.sh

# Restore (nếu cần)
sudo tar -xzf /opt/backups/auto-translate-video/backup_YYYYMMDD_HHMMSS.tar.gz -C /opt/auto-translate-video/
```

---

## ✅ Checklist Deploy

- [ ] Server Ubuntu 20.04/22.04
- [ ] Domain đã trỏ về IP server
- [ ] Upload code lên server
- [ ] Chạy script deploy.sh
- [ ] Cập nhật API keys trong .env
- [ ] Test website hoạt động
- [ ] Test upload và xử lý video
- [ ] Cấu hình backup tự động
- [ ] Cấu hình monitoring (tùy chọn)

**🎉 Chúc mừng! Ứng dụng đã được deploy thành công!**

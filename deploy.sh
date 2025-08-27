#!/bin/bash

# ========================================
# AUTO TRANSLATE VIDEO - DEPLOY SCRIPT
# ========================================
# Script deploy hoàn chỉnh cho Ubuntu Server
# Hỗ trợ: Nginx, Gunicorn, SSL, Systemd Service

set -e  # Dừng script nếu có lỗi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   print_error "Script này không nên chạy với quyền root. Vui lòng chạy với user thường."
   exit 1
fi

# Configuration variables
APP_NAME="auto-translate-video"
APP_USER="appuser"
APP_DIR="/opt/$APP_NAME"
DOMAIN=""
EMAIL=""

# Get user input
echo "========================================"
echo "    AUTO TRANSLATE VIDEO - DEPLOY"
echo "========================================"
echo ""

# Get domain name
while [[ -z "$DOMAIN" ]]; do
    read -p "Nhập tên miền của bạn (ví dụ: translate.example.com): " DOMAIN
    if [[ -z "$DOMAIN" ]]; then
        print_warning "Tên miền không được để trống!"
    fi
done

# Get email for SSL
while [[ -z "$EMAIL" ]]; do
    read -p "Nhập email của bạn (cho SSL certificate): " EMAIL
    if [[ -z "$EMAIL" ]]; then
        print_warning "Email không được để trống!"
    fi
done

print_status "Bắt đầu deploy với domain: $DOMAIN"

# Update system
print_status "Cập nhật hệ thống..."
sudo apt update && sudo apt upgrade -y

# Install essential packages
print_status "Cài đặt các package cần thiết..."
sudo apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx ffmpeg curl wget git unzip software-properties-common apt-transport-https ca-certificates gnupg lsb-release

# Create application user
print_status "Tạo user cho ứng dụng..."
if ! id "$APP_USER" &>/dev/null; then
    sudo useradd -m -s /bin/bash "$APP_USER"
    sudo usermod -aG sudo "$APP_USER"
    print_success "Đã tạo user $APP_USER"
else
    print_warning "User $APP_USER đã tồn tại"
fi

# Create application directory
print_status "Tạo thư mục ứng dụng..."
sudo mkdir -p "$APP_DIR"
sudo chown "$APP_USER:$APP_USER" "$APP_DIR"

# Copy application files
print_status "Copy files ứng dụng..."
sudo cp -r . "$APP_DIR/"
sudo chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# Switch to application directory
cd "$APP_DIR"

# Create Python virtual environment
print_status "Tạo Python virtual environment..."
sudo -u "$APP_USER" python3 -m venv venv
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip

# Install Python dependencies
print_status "Cài đặt Python dependencies..."
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r web_requirements.txt
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install gunicorn

# Create necessary directories
print_status "Tạo các thư mục cần thiết..."
sudo -u "$APP_USER" mkdir -p "$APP_DIR/projects"
sudo -u "$APP_USER" mkdir -p "$APP_DIR/logs"
sudo -u "$APP_USER" mkdir -p "$APP_DIR/uploads"
sudo -u "$APP_USER" mkdir -p "$APP_DIR/temp"

# Set proper permissions
sudo chmod 755 "$APP_DIR"
sudo chmod -R 755 "$APP_DIR/templates"
sudo chmod -R 777 "$APP_DIR/projects"
sudo chmod -R 777 "$APP_DIR/logs"
sudo chmod -R 777 "$APP_DIR/uploads"
sudo chmod -R 777 "$APP_DIR/temp"

# Create Gunicorn configuration
print_status "Tạo cấu hình Gunicorn..."
sudo tee "$APP_DIR/gunicorn.conf.py" > /dev/null <<EOF
# Gunicorn configuration
bind = "127.0.0.1:8000"
workers = 2
worker_class = "sync"
worker_connections = 1000
timeout = 300
keepalive = 2
max_requests = 1000
max_requests_jitter = 100
preload_app = True
daemon = False
user = "$APP_USER"
group = "$APP_USER"
pidfile = "$APP_DIR/gunicorn.pid"
accesslog = "$APP_DIR/logs/gunicorn_access.log"
errorlog = "$APP_DIR/logs/gunicorn_error.log"
loglevel = "info"
capture_output = True
EOF

# Create systemd service
print_status "Tạo systemd service..."
sudo tee "/etc/systemd/system/$APP_NAME.service" > /dev/null <<EOF
[Unit]
Description=Auto Translate Video Web Application
After=network.target

[Service]
Type=exec
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/venv/bin
ExecStart=$APP_DIR/venv/bin/gunicorn -c $APP_DIR/gunicorn.conf.py web_app:app
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Create Nginx configuration
print_status "Tạo cấu hình Nginx..."
sudo tee "/etc/nginx/sites-available/$APP_NAME" > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    
    # Redirect to HTTPS
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN;
    
    # SSL configuration will be added by certbot
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    add_header Content-Security-Policy "default-src 'self' http: https: data: blob: 'unsafe-inline'" always;
    
    # Client max body size for video uploads
    client_max_body_size 500M;
    
    # Proxy settings
    proxy_connect_timeout 300s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;
    proxy_buffering off;
    
    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_proxied expired no-cache no-store private must-revalidate auth;
    gzip_types text/plain text/css text/xml text/javascript application/x-javascript application/xml+rss application/javascript;
    
    # Static files
    location /static/ {
        alias $APP_DIR/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    # Main application
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    # Health check
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
}
EOF

# Enable Nginx site
sudo ln -sf "/etc/nginx/sites-available/$APP_NAME" "/etc/nginx/sites-enabled/"
sudo rm -f /etc/nginx/sites-enabled/default

# Test Nginx configuration
print_status "Kiểm tra cấu hình Nginx..."
sudo nginx -t

# Start and enable services
print_status "Khởi động các service..."
sudo systemctl daemon-reload
sudo systemctl enable "$APP_NAME"
sudo systemctl start "$APP_NAME"
sudo systemctl restart nginx

# Get SSL certificate
print_status "Lấy SSL certificate từ Let's Encrypt..."
sudo certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive

# Create environment file
print_status "Tạo file environment..."
sudo -u "$APP_USER" tee "$APP_DIR/.env" > /dev/null <<EOF
# Auto Translate Video Environment Configuration
FLASK_ENV=production
FLASK_DEBUG=False
SECRET_KEY=$(openssl rand -hex 32)

# Domain configuration
DOMAIN=$DOMAIN

# API Keys (Cần cập nhật thủ công)
FPT_API_KEY=your_fpt_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
ASSEMBLYAI_API_KEY=your_assemblyai_api_key_here

# Application settings
UPLOAD_FOLDER=$APP_DIR/uploads
PROJECTS_FOLDER=$APP_DIR/projects
TEMP_FOLDER=$APP_DIR/temp
LOG_FOLDER=$APP_DIR/logs

# Gunicorn settings
GUNICORN_BIND=127.0.0.1:8000
GUNICORN_WORKERS=2
GUNICORN_TIMEOUT=300
EOF

# Create startup script
print_status "Tạo script khởi động..."
sudo tee "$APP_DIR/start.sh" > /dev/null <<EOF
#!/bin/bash
cd "$APP_DIR"
source venv/bin/activate
export \$(cat .env | xargs)
gunicorn -c gunicorn.conf.py web_app:app
EOF

sudo chmod +x "$APP_DIR/start.sh"

# Create management script
print_status "Tạo script quản lý..."
sudo tee "$APP_DIR/manage.sh" > /dev/null <<EOF
#!/bin/bash

APP_NAME="$APP_NAME"
APP_DIR="$APP_DIR"

case "\$1" in
    start)
        echo "Khởi động ứng dụng..."
        sudo systemctl start \$APP_NAME
        ;;
    stop)
        echo "Dừng ứng dụng..."
        sudo systemctl stop \$APP_NAME
        ;;
    restart)
        echo "Khởi động lại ứng dụng..."
        sudo systemctl restart \$APP_NAME
        ;;
    status)
        echo "Trạng thái ứng dụng:"
        sudo systemctl status \$APP_NAME
        ;;
    logs)
        echo "Xem logs:"
        sudo journalctl -u \$APP_NAME -f
        ;;
    update)
        echo "Cập nhật ứng dụng..."
        cd \$APP_DIR
        git pull
        source venv/bin/activate
        pip install -r web_requirements.txt
        sudo systemctl restart \$APP_NAME
        ;;
    ssl-renew)
        echo "Gia hạn SSL certificate..."
        sudo certbot renew
        ;;
    *)
        echo "Sử dụng: \$0 {start|stop|restart|status|logs|update|ssl-renew}"
        exit 1
        ;;
esac
EOF

sudo chmod +x "$APP_DIR/manage.sh"

# Create backup script
print_status "Tạo script backup..."
sudo tee "$APP_DIR/backup.sh" > /dev/null <<EOF
#!/bin/bash

BACKUP_DIR="/opt/backups/$APP_NAME"
DATE=\$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="backup_\$DATE.tar.gz"

echo "Tạo backup: \$BACKUP_FILE"

# Tạo thư mục backup
sudo mkdir -p "\$BACKUP_DIR"

# Backup application files
sudo tar -czf "\$BACKUP_DIR/\$BACKUP_FILE" \\
    --exclude='venv' \\
    --exclude='*.log' \\
    --exclude='temp/*' \\
    --exclude='uploads/*' \\
    -C "$APP_DIR" .

echo "Backup hoàn thành: \$BACKUP_DIR/\$BACKUP_FILE"

# Xóa backup cũ (giữ lại 7 ngày)
find "\$BACKUP_DIR" -name "backup_*.tar.gz" -mtime +7 -delete
EOF

sudo chmod +x "$APP_DIR/backup.sh"

# Create cron job for SSL renewal
print_status "Tạo cron job cho SSL renewal..."
(crontab -l 2>/dev/null; echo "0 12 * * * /usr/bin/certbot renew --quiet") | crontab -

# Create firewall rules
print_status "Cấu hình firewall..."
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw --force enable

# Final status check
print_status "Kiểm tra trạng thái cuối cùng..."
sleep 5

if sudo systemctl is-active --quiet "$APP_NAME"; then
    print_success "Ứng dụng đã khởi động thành công!"
else
    print_error "Ứng dụng khởi động thất bại. Kiểm tra logs:"
    sudo journalctl -u "$APP_NAME" --no-pager -n 20
fi

if sudo systemctl is-active --quiet nginx; then
    print_success "Nginx đã khởi động thành công!"
else
    print_error "Nginx khởi động thất bại!"
fi

# Display final information
echo ""
echo "========================================"
echo "    DEPLOY HOÀN THÀNH!"
echo "========================================"
echo ""
print_success "Ứng dụng đã được deploy thành công!"
echo ""
echo "📋 THÔNG TIN QUAN TRỌNG:"
echo "🌐 Website: https://$DOMAIN"
echo "📁 Thư mục ứng dụng: $APP_DIR"
echo "👤 User: $APP_USER"
echo ""
echo "🔧 QUẢN LÝ ỨNG DỤNG:"
echo "   Khởi động: sudo $APP_DIR/manage.sh start"
echo "   Dừng: sudo $APP_DIR/manage.sh stop"
echo "   Khởi động lại: sudo $APP_DIR/manage.sh restart"
echo "   Xem trạng thái: sudo $APP_DIR/manage.sh status"
echo "   Xem logs: sudo $APP_DIR/manage.sh logs"
echo "   Cập nhật: sudo $APP_DIR/manage.sh update"
echo "   Backup: sudo $APP_DIR/backup.sh"
echo ""
echo "⚠️  CẦN LÀM SAU KHI DEPLOY:"
echo "1. Cập nhật API keys trong file $APP_DIR/.env"
echo "2. Kiểm tra website tại https://$DOMAIN"
echo "3. Test tính năng upload và xử lý video"
echo "4. Cấu hình backup tự động nếu cần"
echo ""
print_warning "Lưu ý: SSL certificate sẽ tự động gia hạn mỗi 90 ngày"
echo ""
print_success "Deploy hoàn tất! 🎉"

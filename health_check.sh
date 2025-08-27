#!/bin/bash

# ========================================
# HEALTH CHECK SCRIPT
# ========================================
# Kiểm tra sức khỏe hệ thống sau deploy

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

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

# Configuration
APP_NAME="auto-translate-video"
APP_DIR="/opt/$APP_NAME"
DOMAIN=""

# Get domain from user
read -p "Nhập domain của bạn: " DOMAIN

echo "========================================"
echo "    HEALTH CHECK - AUTO TRANSLATE VIDEO"
echo "========================================"
echo ""

# Check system resources
print_status "Kiểm tra tài nguyên hệ thống..."

# CPU Usage
CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
if (( $(echo "$CPU_USAGE < 80" | bc -l) )); then
    print_success "CPU Usage: ${CPU_USAGE}% (OK)"
else
    print_warning "CPU Usage: ${CPU_USAGE}% (High)"
fi

# Memory Usage
MEMORY_USAGE=$(free | grep Mem | awk '{printf("%.2f", $3/$2 * 100.0)}')
if (( $(echo "$MEMORY_USAGE < 80" | bc -l) )); then
    print_success "Memory Usage: ${MEMORY_USAGE}% (OK)"
else
    print_warning "Memory Usage: ${MEMORY_USAGE}% (High)"
fi

# Disk Usage
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -lt 80 ]; then
    print_success "Disk Usage: ${DISK_USAGE}% (OK)"
else
    print_warning "Disk Usage: ${DISK_USAGE}% (High)"
fi

echo ""

# Check services
print_status "Kiểm tra các service..."

# Check if application service is running
if systemctl is-active --quiet "$APP_NAME"; then
    print_success "Application service is running"
else
    print_error "Application service is not running"
fi

# Check if nginx is running
if systemctl is-active --quiet nginx; then
    print_success "Nginx service is running"
else
    print_error "Nginx service is not running"
fi

# Check if gunicorn process is running
if pgrep -f "gunicorn" > /dev/null; then
    print_success "Gunicorn process is running"
else
    print_error "Gunicorn process is not running"
fi

echo ""

# Check ports
print_status "Kiểm tra ports..."

# Check port 80 (HTTP)
if netstat -tlnp | grep ":80 " > /dev/null; then
    print_success "Port 80 (HTTP) is listening"
else
    print_error "Port 80 (HTTP) is not listening"
fi

# Check port 443 (HTTPS)
if netstat -tlnp | grep ":443 " > /dev/null; then
    print_success "Port 443 (HTTPS) is listening"
else
    print_error "Port 443 (HTTPS) is not listening"
fi

# Check port 8000 (Gunicorn)
if netstat -tlnp | grep ":8000 " > /dev/null; then
    print_success "Port 8000 (Gunicorn) is listening"
else
    print_error "Port 8000 (Gunicorn) is not listening"
fi

echo ""

# Check SSL certificate
print_status "Kiểm tra SSL certificate..."

if [ -n "$DOMAIN" ]; then
    SSL_EXPIRY=$(echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN":443 2>/dev/null | openssl x509 -noout -dates | grep notAfter | cut -d= -f2)
    if [ -n "$SSL_EXPIRY" ]; then
        print_success "SSL certificate is valid until: $SSL_EXPIRY"
    else
        print_error "SSL certificate check failed"
    fi
else
    print_warning "Domain not provided, skipping SSL check"
fi

echo ""

# Check application files
print_status "Kiểm tra files ứng dụng..."

if [ -d "$APP_DIR" ]; then
    print_success "Application directory exists: $APP_DIR"
else
    print_error "Application directory not found: $APP_DIR"
fi

if [ -f "$APP_DIR/web_app.py" ]; then
    print_success "Main application file exists"
else
    print_error "Main application file not found"
fi

if [ -f "$APP_DIR/.env" ]; then
    print_success "Environment file exists"
else
    print_warning "Environment file not found"
fi

if [ -d "$APP_DIR/venv" ]; then
    print_success "Python virtual environment exists"
else
    print_error "Python virtual environment not found"
fi

echo ""

# Check logs
print_status "Kiểm tra logs..."

if [ -f "$APP_DIR/logs/gunicorn_error.log" ]; then
    ERROR_COUNT=$(tail -100 "$APP_DIR/logs/gunicorn_error.log" | grep -c "ERROR\|CRITICAL")
    if [ "$ERROR_COUNT" -eq 0 ]; then
        print_success "No recent errors in Gunicorn logs"
    else
        print_warning "Found $ERROR_COUNT recent errors in Gunicorn logs"
    fi
else
    print_warning "Gunicorn error log not found"
fi

if [ -f "/var/log/nginx/error.log" ]; then
    NGINX_ERROR_COUNT=$(tail -100 /var/log/nginx/error.log | grep -c "error")
    if [ "$NGINX_ERROR_COUNT" -eq 0 ]; then
        print_success "No recent errors in Nginx logs"
    else
        print_warning "Found $NGINX_ERROR_COUNT recent errors in Nginx logs"
    fi
else
    print_warning "Nginx error log not found"
fi

echo ""

# Check API connectivity
print_status "Kiểm tra kết nối API..."

# Check if domain is accessible
if [ -n "$DOMAIN" ]; then
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://$DOMAIN")
    if [ "$HTTP_STATUS" = "301" ] || [ "$HTTP_STATUS" = "200" ]; then
        print_success "Domain is accessible (HTTP: $HTTP_STATUS)"
    else
        print_error "Domain is not accessible (HTTP: $HTTP_STATUS)"
    fi
    
    HTTPS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN")
    if [ "$HTTPS_STATUS" = "200" ]; then
        print_success "HTTPS is working (Status: $HTTPS_STATUS)"
    else
        print_error "HTTPS is not working (Status: $HTTPS_STATUS)"
    fi
else
    print_warning "Domain not provided, skipping connectivity check"
fi

echo ""

# Check dependencies
print_status "Kiểm tra dependencies..."

# Check FFmpeg
if command -v ffmpeg >/dev/null 2>&1; then
    print_success "FFmpeg is installed"
else
    print_error "FFmpeg is not installed"
fi

# Check Python
if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    print_success "Python3 is installed: $PYTHON_VERSION"
else
    print_error "Python3 is not installed"
fi

# Check pip
if command -v pip3 >/dev/null 2>&1; then
    print_success "pip3 is installed"
else
    print_error "pip3 is not installed"
fi

echo ""

# Check firewall
print_status "Kiểm tra firewall..."

if command -v ufw >/dev/null 2>&1; then
    UFW_STATUS=$(sudo ufw status | grep "Status" | cut -d' ' -f2)
    if [ "$UFW_STATUS" = "active" ]; then
        print_success "Firewall is active"
    else
        print_warning "Firewall is not active"
    fi
else
    print_warning "UFW firewall not found"
fi

echo ""

# Check cron jobs
print_status "Kiểm tra cron jobs..."

SSL_RENEWAL_CRON=$(crontab -l 2>/dev/null | grep -c "certbot renew")
if [ "$SSL_RENEWAL_CRON" -gt 0 ]; then
    print_success "SSL renewal cron job is configured"
else
    print_warning "SSL renewal cron job is not configured"
fi

echo ""

# Final summary
echo "========================================"
echo "    HEALTH CHECK SUMMARY"
echo "========================================"

# Count issues
ERRORS=0
WARNINGS=0

# Simple check for critical issues
if ! systemctl is-active --quiet "$APP_NAME"; then
    ((ERRORS++))
fi

if ! systemctl is-active --quiet nginx; then
    ((ERRORS++))
fi

if [ ! -d "$APP_DIR" ]; then
    ((ERRORS++))
fi

if [ "$DISK_USAGE" -gt 90 ]; then
    ((WARNINGS++))
fi

if [ "$MEMORY_USAGE" -gt 90 ]; then
    ((WARNINGS++))
fi

echo ""
if [ "$ERRORS" -eq 0 ] && [ "$WARNINGS" -eq 0 ]; then
    print_success "🎉 Hệ thống hoạt động tốt!"
elif [ "$ERRORS" -eq 0 ]; then
    print_warning "⚠️  Hệ thống hoạt động với $WARNINGS cảnh báo"
else
    print_error "❌ Hệ thống có $ERRORS lỗi và $WARNINGS cảnh báo"
fi

echo ""
echo "📋 RECOMMENDATIONS:"
if [ "$ERRORS" -gt 0 ]; then
    echo "   - Kiểm tra và sửa các lỗi trước khi sử dụng"
fi
if [ "$WARNINGS" -gt 0 ]; then
    echo "   - Theo dõi tài nguyên hệ thống"
fi
echo "   - Chạy script này định kỳ để kiểm tra sức khỏe hệ thống"
echo "   - Backup dữ liệu thường xuyên"

echo ""
print_status "Health check hoàn tất!"

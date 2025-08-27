#!/usr/bin/env python3
"""
Service runner để chạy Auto Translate Video như một service/daemon
App sẽ chạy background và không phụ thuộc vào browser
"""

import os
import sys
import time
import signal
import logging
from pathlib import Path
import threading
import webbrowser
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('service.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class AutoTranslateService:
    def __init__(self):
        self.running = False
        self.app = None
        self.host = '0.0.0.0'  # Listen on all interfaces
        self.port = 5000
        self.debug = False
        
    def start(self):
        """Bắt đầu service"""
        logger.info("🚀 Starting Auto Translate Video Service")
        logger.info(f"   Host: {self.host}")
        logger.info(f"   Port: {self.port}")
        logger.info(f"   Web UI: http://localhost:{self.port}")
        
        self.running = True
        
        try:
            # Import và chạy Flask app
            from web_app import app
            self.app = app
            
            # Setup signal handlers for graceful shutdown
            signal.signal(signal.SIGINT, self.signal_handler)
            signal.signal(signal.SIGTERM, self.signal_handler)
            
            # Tự động mở browser sau 2 giây (tùy chọn)
            if not self.debug:
                threading.Timer(2.0, self.open_browser).start()
            
            # Chạy Flask app
            logger.info("✅ Service started successfully")
            self.app.run(
                host=self.host,
                port=self.port,
                debug=self.debug,
                use_reloader=False,  # Tắt reloader để tránh conflict
                threaded=True       # Enable threading
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to start service: {e}")
            self.running = False
            sys.exit(1)
    
    def stop(self):
        """Dừng service"""
        logger.info("🛑 Stopping Auto Translate Video Service")
        self.running = False
        
        # Cleanup nếu cần
        try:
            # Dừng queue processor
            if hasattr(self, 'app') and self.app:
                # Set global flag to stop queue processor
                import web_app
                web_app.queue_processor_running = False
                logger.info("   Queue processor stopped")
                
        except Exception as e:
            logger.error(f"   Error during cleanup: {e}")
        
        logger.info("✅ Service stopped")
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"   Received signal {signum}")
        self.stop()
        sys.exit(0)
    
    def open_browser(self):
        """Tự động mở browser"""
        try:
            url = f"http://localhost:{self.port}"
            logger.info(f"🌐 Opening browser: {url}")
            webbrowser.open(url)
        except Exception as e:
            logger.warning(f"   Could not open browser: {e}")
    
    def status(self):
        """Kiểm tra trạng thái service"""
        if self.running:
            return {
                'status': 'running',
                'host': self.host,
                'port': self.port,
                'url': f"http://localhost:{self.port}",
                'uptime': 'N/A'  # TODO: Track uptime
            }
        else:
            return {
                'status': 'stopped'
            }

def install_as_windows_service():
    """Cài đặt như Windows Service (tùy chọn)"""
    try:
        import win32serviceutil
        import win32service
        import win32event
        
        class AutoTranslateWindowsService(win32serviceutil.ServiceFramework):
            _svc_name_ = "AutoTranslateVideo"
            _svc_display_name_ = "Auto Translate Video Service"
            _svc_description_ = "Dịch video tự động với AI"
            
            def __init__(self, args):
                win32serviceutil.ServiceFramework.__init__(self, args)
                self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
                self.service = AutoTranslateService()
            
            def SvcStop(self):
                self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
                win32event.SetEvent(self.hWaitStop)
                self.service.stop()
            
            def SvcDoRun(self):
                self.service.start()
        
        if len(sys.argv) == 1:
            # Chạy service
            win32serviceutil.HandleCommandLine(AutoTranslateWindowsService)
        else:
            # Install/remove service
            win32serviceutil.HandleCommandLine(AutoTranslateWindowsService)
            
    except ImportError:
        logger.error("❌ pywin32 not installed. Cannot install as Windows Service.")
        logger.info("   Install with: pip install pywin32")
        return False

def main():
    """Main entry point"""
    service = AutoTranslateService()
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == 'start':
            service.start()
        elif command == 'stop':
            service.stop()
        elif command == 'status':
            status = service.status()
            print(json.dumps(status, indent=2))
        elif command == 'install':
            install_as_windows_service()
        elif command == 'debug':
            service.debug = True
            service.start()
        else:
            print("Usage: python service_runner.py [start|stop|status|install|debug]")
            print()
            print("Commands:")
            print("  start   - Start the service")
            print("  stop    - Stop the service")
            print("  status  - Check service status")
            print("  install - Install as Windows Service")
            print("  debug   - Start in debug mode")
            print()
            print("Default: start")
    else:
        # Default: start service
        service.start()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("   Service interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"   Service crashed: {e}")
        sys.exit(1)

from flask import Flask, render_template, request, jsonify, send_file, session
from flask_cors import CORS
import os
import json
import subprocess
import shutil
from pathlib import Path
import tempfile
import uuid
from datetime import datetime
import threading
import time
from werkzeug.utils import secure_filename

# Import các function từ pipeline gốc
from pipeline import (
    download_with_ytdlp, slow_down_video, extract_audio_for_stt,
    stt_assemblyai, translate_srt_ai, srt_to_aligned_audio_fpt_ai,
    srt_to_aligned_audio_fpt_ai_with_failover,
    replace_audio, speed_up_130, add_background_music, overlay_template,
    remove_silence_ffmpeg, get_vietnamese_error_message
)

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'
CORS(app)

# Cấu hình mặc định
DEFAULT_CONFIG = {
    # FPT AI API Keys - Hỗ trợ nhiều keys với auto-failover
    'fpt_api_keys': [
        'ffFujWkLFqAAZbEu5O3Fy1eplKiOVtGW'  # Key mặc định
    ],
    'fpt_current_key_index': 0,  # Index của key hiện tại
    'fpt_voice': 'banmai',  # Giọng nói FPT AI (theo tài liệu: banmai, lannhi, leminh, myan, thuminh, giahuy, linhsan)
    'fpt_speed': '-1',  # Tốc độ đọc (-1 ≈ 0.7x speed, phù hợp cho video translate)
    'fpt_speech_speed': '0.8',  # Tốc độ nói (0.5-2.0, 1.0 = bình thường, 0.8 = chậm hơn)
    'fpt_format': 'mp3',  # Format audio (mp3 hoặc wav)
    # AI Provider - chỉ sử dụng Gemini với multiple keys và failover
    'gemini_api_key': '',  # API key của người dùng (ưu tiên cao nhất)
    'gemini_backup_keys': [
        'AIzaSyClZFBCA_uXJLwBYG0rV3j0-flFEH6SyOU',  # Key mặc định
        'AIzaSyAkrlcnwqDuWci9Djgve3bVoYJYTACKLDw',  # Backup key 1
        'AIzaSyBXe18Cq2S97Pc7o7pvdL9tXzEabcKN5X4',  # Backup key 2
        'AIzaSyDk2UHw8Pghh8ROMAesrYCxv5bHuHsIrRM',  # Backup key 3
    ],
    'gemini_current_key_index': 0,  # Index của key hiện tại
    'gemini_model': 'gemini-2.0-flash',
    'ai_provider': 'gemini',  # Chỉ hỗ trợ Gemini
    'assemblyai_api_key': '3fcbc58eb11d489c820f00535c7f8fb5',
    'edge_voice': 'vi-VN-HoaiMyNeural',
    'tts_language': 'vi',
    'stt_language': 'en',
    'stt_method': 'utterances',  # 'utterances', 'json' hoặc 'srt' - Utterances cho câu hoàn chỉnh nhất
    'stt_chars_per_caption': 300,  # Số ký tự mỗi caption khi dùng SRT (tăng để có câu hoàn chỉnh)
    'stt_speech_threshold': 0.5,  # Ngưỡng phát hiện speech (0.0-1.0)
    'stt_disfluencies': False,    # Loại bỏ filler words
    'use_ai_segmentation': True,  # Sử dụng AI để cải thiện SRT segmentation
    'min_sentence_length': 20,    # Độ dài tối thiểu mỗi câu
    'max_sentence_length': 150,   # Độ dài tối đa mỗi câu
    # Silence Remover settings
    'enable_silence_removal': True,  # Bật tính năng cắt khoảng lặng
    'silence_threshold': -50.0,      # Ngưỡng âm thanh (dB)
    'min_silence_duration': 0.4,     # Thời gian tối thiểu khoảng lặng (giây)
    'max_silence_duration': 2.0,     # Thời gian tối đa khoảng lặng cần cắt (giây)
    'silence_padding': 0.1,          # Padding sau khi cắt (giây)
    
    # Proxy settings
    'proxy_enabled': False,          # Bật proxy
    'proxy_config': '',              # Format: IP:PORT:USER:PASS
}

# Lưu trữ trạng thái các project
projects = {}

# Hệ thống queue để xử lý nhiều dự án tuần tự
import queue
import threading

project_queue = queue.Queue()
queue_processor_running = False

# FPT AI Key Management
def get_current_fpt_key(config):
    """Lấy FPT API key hiện tại"""
    keys = config.get('fpt_api_keys', [])
    if not keys:
        return None
    
    current_index = config.get('fpt_current_key_index', 0)
    if current_index >= len(keys):
        current_index = 0
        config['fpt_current_key_index'] = current_index
    
    return keys[current_index]

def switch_to_next_fpt_key(config):
    """Chuyển sang FPT API key tiếp theo"""
    keys = config.get('fpt_api_keys', [])
    if len(keys) <= 1:
        return False  # Chỉ có 1 key hoặc không có key
    
    current_index = config.get('fpt_current_key_index', 0)
    next_index = (current_index + 1) % len(keys)
    config['fpt_current_key_index'] = next_index
    
    print(f"🔄 Switched to FPT API key #{next_index + 1}/{len(keys)}")
    return True

def get_current_gemini_key(config):
    """Lấy Gemini API key hiện tại (ưu tiên key của người dùng)"""
    # Ưu tiên key của người dùng
    user_key = config.get('gemini_api_key', '').strip()
    if user_key:
        return user_key
    
    # Nếu không có key của người dùng, dùng backup keys
    backup_keys = config.get('gemini_backup_keys', [])
    if not backup_keys:
        return None
    
    current_index = config.get('gemini_current_key_index', 0)
    if current_index >= len(backup_keys):
        current_index = 0
        config['gemini_current_key_index'] = current_index
    
    # Đảm bảo index hợp lệ
    if current_index < len(backup_keys):
        return backup_keys[current_index]
    
    # Fallback về key đầu tiên
    return backup_keys[0] if backup_keys else None

def switch_to_next_gemini_key(config):
    """Chuyển sang Gemini API key tiếp theo (chỉ áp dụng cho backup keys)"""
    # Nếu có key của người dùng, không chuyển
    user_key = config.get('gemini_api_key', '').strip()
    if user_key:
        return False
    
    backup_keys = config.get('gemini_backup_keys', [])
    if len(backup_keys) <= 1:
        return False  # Chỉ có 1 key hoặc không có key
    
    current_index = config.get('gemini_current_key_index', 0)
    next_index = (current_index + 1) % len(backup_keys)
    config['gemini_current_key_index'] = next_index
    
    print(f"🔄 Switched to Gemini API key #{next_index + 1}/{len(backup_keys)}")
    return True

def get_proxy_config(config):
    """Parse proxy config từ format IP:PORT:USER:PASS"""
    if not config.get('proxy_enabled', False):
        return None
    
    proxy_str = config.get('proxy_config', '').strip()
    if not proxy_str:
        return None
    
    try:
        parts = proxy_str.split(':')
        if len(parts) == 4:
            ip, port, user, password = parts
            return {
                'http': f'http://{user}:{password}@{ip}:{port}',
                'https': f'http://{user}:{password}@{ip}:{port}'
            }
        elif len(parts) == 2:
            ip, port = parts
            return {
                'http': f'http://{ip}:{port}',
                'https': f'http://{ip}:{port}'
            }
        else:
            print(f"⚠️ Invalid proxy format: {proxy_str}")
            return None
    except Exception as e:
        print(f"⚠️ Error parsing proxy config: {e}")
        return None

def start_queue_processor():
    """Bắt đầu queue processor để xử lý dự án tuần tự"""
    global queue_processor_running
    if not queue_processor_running:
        queue_processor_running = True
        processor_thread = threading.Thread(target=process_project_queue, daemon=True)
        processor_thread.start()
        
        # Thêm background thread để kiểm tra queue định kỳ
        queue_checker_thread = threading.Thread(target=queue_checker_loop, daemon=True)
        queue_checker_thread.start()
        
        # Khởi động ngay lập tức để kiểm tra queue
        check_and_start_next_project()
        
        print("✅ Queue processor and checker started")

def process_project_queue():
    """Xử lý queue dự án tuần tự (legacy - không sử dụng nữa)"""
    global queue_processor_running
    print("🔄 Queue processor running (legacy mode)...")
    
    while queue_processor_running:
        try:
            # Chỉ sleep để không block
            time.sleep(10)
        except Exception as e:
            print(f"❌ Queue processor error: {e}")
            continue

def queue_checker_loop():
    """Background loop để kiểm tra và khởi động dự án trong queue"""
    global queue_processor_running
    print("🔍 Queue checker started...")
    
    while queue_processor_running:
        try:
            # Kiểm tra mỗi 5 giây (nhanh hơn)
            time.sleep(5)
            
            # Kiểm tra xem có dự án nào đang chạy không
            running_projects = [p for p in projects.values() if p['status'] == 'running']
            queued_projects = [p for p in projects.values() if p['status'] == 'queued']
            
            print(f"🔍 Queue checker: {len(running_projects)} running, {len(queued_projects)} queued")
            
            # Kiểm tra các project đang chạy có bị stuck không
            current_time = time.time()
            for project in running_projects:
                # Kiểm tra nếu project đang chạy quá lâu (30 phút)
                if 'start_time' not in project:
                    project['start_time'] = current_time
                elif current_time - project['start_time'] > 1800:  # 30 phút
                    print(f"⚠️ Project {project['id'][:8]} seems stuck (running for 30+ minutes), marking as error")
                    project['status'] = 'error'
                    project['error'] = 'Project stuck - timeout after 30 minutes'
                    check_and_start_next_project()
                    break
            
            # Kiểm tra nếu không có project nào đang chạy và có project trong queue
            if len(running_projects) == 0 and len(queued_projects) > 0:
                print(f"🔍 Queue checker found {len(queued_projects)} projects in queue, no running projects")
                check_and_start_next_project()
                
        except Exception as e:
            print(f"❌ Queue checker error: {e}")
            continue

def get_queue_status():
    """Lấy trạng thái queue"""
    queued_projects = [p for p in projects.values() if p['status'] == 'queued']
    queue_size = len(queued_projects)
    
    # Cập nhật queue position cho các project
    position = 1
    for project_id, project in projects.items():
        if project['status'] == 'queued':
            project['queue_position'] = position
            position += 1
    
    return {
        'queue_size': queue_size,
        'processor_running': queue_processor_running
    }

def check_and_start_next_project():
    """Kiểm tra và bắt đầu dự án tiếp theo trong queue"""
    print(f"🔍 Checking for next project in queue...")
    
    # Kiểm tra xem có project nào đang chạy không
    running_projects = [p for p in projects.values() if p['status'] == 'running']
    queued_projects = [p for p in projects.values() if p['status'] == 'queued']
    
    print(f"📊 Current status: {len(running_projects)} running projects, {len(queued_projects)} queued projects")
    
    if len(running_projects) == 0 and len(queued_projects) > 0:
        # Không có project nào đang chạy và có project trong queue
        # Lấy project đầu tiên trong danh sách queued
        next_project = queued_projects[0]
        next_project_id = next_project['id']
        
        print(f"🎯 Starting next project from queue: {next_project_id}")
        
        # Cập nhật trạng thái
        next_project['status'] = 'running'
        next_project['queue_position'] = 0
        
        # Sử dụng DEFAULT_CONFIG thay vì session config để tránh lỗi context
        config = DEFAULT_CONFIG.copy()
        
        # Chạy project trong thread riêng
        thread = threading.Thread(target=run_pipeline_async, args=(next_project_id, next_project['url'], Path(f"projects/{next_project_id}"), config))
        thread.daemon = True
        thread.start()
        
        print(f"✅ Next project {next_project_id} started successfully")
        
        # Cập nhật queue positions cho các project còn lại
        remaining_queued = [p for p in projects.values() if p['status'] == 'queued']
        for i, project in enumerate(remaining_queued):
            project['queue_position'] = i + 1
            
    elif len(running_projects) > 0:
        print(f"📋 {len(running_projects)} projects still running, queue will be processed later")
    else:
        print(f"📋 No projects in queue to process")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config', methods=['GET', 'POST'])
def config():
    if request.method == 'POST':
        config_data = request.json
        session['config'] = config_data
        return jsonify({'status': 'success'})
    else:
        return jsonify(session.get('config', DEFAULT_CONFIG))

@app.route('/api/projects', methods=['GET'])
def get_projects():
    # Cập nhật queue positions
    get_queue_status()
    return jsonify(list(projects.values()))

@app.route('/api/queue/status')
def get_queue_status_api():
    """API để lấy trạng thái queue"""
    return jsonify(get_queue_status())

@app.route('/api/projects/<project_id>', methods=['GET'])
def get_project(project_id):
    if project_id in projects:
        return jsonify(projects[project_id])
    return jsonify({'error': 'Project not found'}), 404

@app.route('/api/start', methods=['POST'])
def start_project():
    data = request.json
    url = data.get('url')
    project_name = data.get('name', '')  # Lấy tên dự án từ request
    
    # Đảm bảo config có đầy đủ thông tin
    session_config = session.get('config', {})
    config = DEFAULT_CONFIG.copy()
    config.update(session_config)
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    # Tạo project ID và tên
    project_id = str(uuid.uuid4())
    if not project_name:
        # Tạo tên tự động từ URL
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            if 'youtube.com' in parsed_url.netloc:
                project_name = f"YouTube Video {project_id[:8]}"
            else:
                project_name = f"Video {project_id[:8]}"
        except:
            project_name = f"Project {project_id[:8]}"
    
    project_dir = Path(f"projects/{project_id}")
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # Khởi tạo project
    project = {
        'id': project_id,
        'name': project_name,
        'url': url,
        'status': 'starting',
        'current_step': 'download',
        'progress': 0,
        'steps': {
            'download': {'status': 'pending', 'progress': 0, 'error': None},
            'slow': {'status': 'pending', 'progress': 0, 'error': None},
            'stt': {'status': 'pending', 'progress': 0, 'error': None},
            'translate': {'status': 'pending', 'progress': 0, 'error': None},
            'tts': {'status': 'pending', 'progress': 0, 'error': None},
            'replace_audio': {'status': 'pending', 'progress': 0, 'error': None},
            'silence_removal': {'status': 'pending', 'progress': 0, 'error': None},
            'speed_up': {'status': 'pending', 'progress': 0, 'error': None},
            'music': {'status': 'pending', 'progress': 0, 'error': None},
            'overlay': {'status': 'pending', 'progress': 0, 'error': None}
        },
        'created_at': datetime.now().isoformat(),
        'output_file': None
    }
    
    projects[project_id] = project
    
    # Bắt đầu queue processor nếu chưa chạy
    start_queue_processor()
    
    # Kiểm tra xem có project nào đang chạy không
    running_projects = [p for p in projects.values() if p['status'] == 'running']
    print(f"🔍 Current running projects: {len(running_projects)}")
    for p in running_projects:
        print(f"   - Project {p['id'][:8]}... (status: {p['status']})")
    
    # Đảm bảo chỉ có 1 project chạy tại một thời điểm
    if len(running_projects) == 0:
        # Không có project nào đang chạy, chạy ngay
        project['status'] = 'running'
        project['queue_position'] = 0
        print(f"🚀 Starting project {project_id} immediately")
        thread = threading.Thread(target=run_pipeline_async, args=(project_id, url, project_dir, config))
        thread.daemon = True
        thread.start()
    else:
        # Có project đang chạy, thêm vào queue
        print(f"⚠️ Found {len(running_projects)} running projects, adding to queue")
        
        # Thêm project mới vào queue (chỉ thêm vào danh sách, không dùng queue.Queue)
        project['status'] = 'queued'
        
        # Tính queue position dựa trên số project đang queued
        queued_projects = [p for p in projects.values() if p['status'] == 'queued']
        project['queue_position'] = len(queued_projects)
        
        print(f"📋 Project {project_id} added to queue (position: {project['queue_position']})")
        print(f"   Currently running: {running_projects[0]['id'][:8]}...")
    
    return jsonify(project)

def run_pipeline_async(project_id, url, workdir, config):
    try:
        project = projects[project_id]
        
        # Đảm bảo config có đầy đủ thông tin
        full_config = DEFAULT_CONFIG.copy()
        full_config.update(config)
        
        # Cập nhật trạng thái
        project['status'] = 'running'
        project['current_step'] = 'download'
        project['steps']['download']['status'] = 'running'
        project['start_time'] = time.time()  # Ghi lại thời gian bắt đầu
        
        print(f"🚀 Starting pipeline for project {project_id}")
        
        # 1. Download
        input_mp4 = workdir / "input.mp4"
        try:
            download_with_ytdlp(url, input_mp4)
            project['steps']['download']['status'] = 'completed'
            project['steps']['download']['progress'] = 100
            project['progress'] = 10
        except Exception as e:
            project['steps']['download']['status'] = 'error'
            project['steps']['download']['progress'] = 0
            project['steps']['download']['error'] = str(e)
            project['status'] = 'error'
            
            # Cung cấp thông tin lỗi chi tiết hơn
            error_msg = str(e)
            if "HTTP Error 403" in error_msg:
                project['error'] = f"Lỗi tải video: Video không thể truy cập (403 Forbidden). Có thể video đã bị xóa, private, hoặc có hạn chế địa lý. Hãy thử URL khác."
            elif "Requested format is not available" in error_msg:
                project['error'] = f"Lỗi tải video: Định dạng video không khả dụng. Hãy thử URL khác."
            elif "fragment 1 not found" in error_msg:
                project['error'] = f"Lỗi tải video: Video có vấn đề về định dạng. Hãy thử URL khác."
            else:
                project['error'] = f"Lỗi tải video: {error_msg}"
            return
        
        # 2. Slow down
        project['current_step'] = 'slow'
        project['steps']['slow']['status'] = 'running'
        slow_mp4 = workdir / "slow.mp4"
        slow_down_video(input_mp4, slow_mp4)
        project['steps']['slow']['status'] = 'completed'
        project['steps']['slow']['progress'] = 100
        project['progress'] = 20
        
        # 3. STT
        if full_config.get('assemblyai_api_key') and full_config['assemblyai_api_key'].strip():
            project['current_step'] = 'stt'
            project['steps']['stt']['status'] = 'running'
            stt_wav = workdir / "stt.wav"
            subs_srt_raw = workdir / "subs_raw.srt"
            extract_audio_for_stt(slow_mp4, stt_wav)
            try:
                # Sử dụng phương pháp STT dựa trên cấu hình
                stt_method = full_config.get('stt_method', 'utterances')
                if stt_method == 'utterances':
                    from pipeline import stt_assemblyai
                    stt_assemblyai(stt_wav, subs_srt_raw, full_config['assemblyai_api_key'], language_code=full_config['stt_language'], config=full_config)
                elif stt_method == 'json':
                    from pipeline import stt_assemblyai
                    stt_assemblyai(stt_wav, subs_srt_raw, full_config['assemblyai_api_key'], language_code=full_config['stt_language'], config=full_config)
                else:  # srt
                    from pipeline import stt_assemblyai_legacy
                    stt_assemblyai_legacy(stt_wav, subs_srt_raw, full_config['assemblyai_api_key'], language_code=full_config['stt_language'], config=full_config)
                
                project['steps']['stt']['status'] = 'completed'
                project['steps']['stt']['progress'] = 100
            except Exception as e:
                print(f"AssemblyAI STT failed: {e}")
                # Fallback to empty SRT
                with open(subs_srt_raw, 'w', encoding='utf-8') as f:
                    f.write("1\n00:00:00,000 --> 00:00:05,000\n[Audio processing failed]\n\n")
                project['steps']['stt']['status'] = 'error'
                project['steps']['stt']['progress'] = 100
                project['steps']['stt']['error'] = str(e)
            project['progress'] = 25
        else:
            # Skip STT if no API key, create empty SRT
            subs_srt_raw = workdir / "subs_raw.srt"
            with open(subs_srt_raw, 'w', encoding='utf-8') as f:
                f.write("1\n00:00:00,000 --> 00:00:05,000\n[No audio detected]\n\n")
            project['steps']['stt']['status'] = 'skipped'
            project['steps']['stt']['progress'] = 100
            project['progress'] = 25

        # 4. Copy SRT (skip merge step)
        subs_srt = workdir / "subs.srt"
        subs_srt_raw.rename(subs_srt)  # Sử dụng SRT gốc thay vì merge
        project['progress'] = 30
        
        # 5. Translate
        project['current_step'] = 'translate'
        project['steps']['translate']['status'] = 'running'
        subs_translated_srt = workdir / "subs_vi.srt"
        
        if full_config['ai_provider'] == 'gemini':
            # Sử dụng Gemini với retry logic và key management
            max_retries = 3  # 3 lần retry, mỗi lần thử tất cả keys
            last_error = None
            
            # Thử tất cả keys trước khi báo lỗi
            backup_keys = full_config.get('gemini_backup_keys', [])
            user_key = full_config.get('gemini_api_key', '').strip()
            all_keys = [user_key] + backup_keys if user_key else backup_keys
            
            translation_success = False
            for retry_attempt in range(max_retries):
                for key_index, current_gemini_key in enumerate(all_keys):
                    if not current_gemini_key:
                        continue
                        
                    try:
                        print(f"🔄 Translation attempt {retry_attempt + 1}/{max_retries} with Gemini key #{key_index + 1}")
                        
                        translate_srt_ai(subs_srt, subs_translated_srt, model=full_config['gemini_model'], api_key=current_gemini_key, provider='gemini', config=full_config)
                        
                        project['steps']['translate']['status'] = 'completed'
                        project['steps']['translate']['progress'] = 100
                        project['progress'] = 40
                        print(f"✅ Translation completed successfully with key #{key_index + 1}")
                        translation_success = True
                        break  # Thoát khỏi vòng lặp key nếu thành công
                        
                    except Exception as e:
                        last_error = e
                        print(f"❌ Translation failed with key #{key_index + 1}: {e}")
                        
                        # Chờ một chút trước khi thử key tiếp theo
                        if key_index < len(all_keys) - 1:
                            time.sleep(1)
                
                # Nếu translation thành công, thoát khỏi vòng lặp retry
                if translation_success:
                    break
                
                # Chờ lâu hơn trước khi retry toàn bộ
                if retry_attempt < max_retries - 1:
                    print(f"🔄 Retrying all keys (attempt {retry_attempt + 2}/{max_retries})")
                    time.sleep(3)
            
            # Nếu tất cả retry đều thất bại
            if not translation_success:
                project['steps']['translate']['status'] = 'error'
                project['steps']['translate']['error'] = str(last_error)
                project['status'] = 'error'
                project['error'] = f"Translation error: {str(last_error)}"
                return
                
        elif full_config['ai_provider'] == 'deepseek':
            translate_srt_ai(subs_srt, subs_translated_srt, model=full_config['deepseek_model'], api_key=full_config['deepseek_api_key'], provider='deepseek', config=full_config)
            project['steps']['translate']['status'] = 'completed'
            project['steps']['translate']['progress'] = 100
            project['progress'] = 40
        
        # 6. TTS
        project['current_step'] = 'tts'
        project['steps']['tts']['status'] = 'running'
        tts_wav = workdir / "tts.wav"
        subs_translated_srt = workdir / "subs_vi.srt"
        
        try:
            # Chọn TTS provider dựa trên cấu hình
            if full_config.get('tts_provider', 'fpt') == 'fpt':
                print("Using FPT AI TTS...")
                from pipeline import srt_to_aligned_audio_fpt_ai_with_failover
                # Không truyền proxies để tránh lỗi
                srt_to_aligned_audio_fpt_ai_with_failover(
                    subs_translated_srt, tts_wav, 
                    full_config,  # Pass full config for key management
                    full_config['fpt_voice'],
                    full_config.get('fpt_speed', ''),
                    full_config.get('fpt_format', 'mp3'),
                    speech_speed=full_config.get('fpt_speech_speed', '0.8')
                )
            else:
                # ElevenLabs đã bị loại bỏ, chỉ sử dụng FPT AI
                raise RuntimeError("ElevenLabs TTS đã bị loại bỏ. Chỉ sử dụng FPT AI.")
                
            project['steps']['tts']['status'] = 'completed'
            project['steps']['tts']['progress'] = 100
            project['progress'] = 50
        except Exception as e:
            print(f"TTS failed: {e}")
            project['steps']['tts']['status'] = 'error'
            project['steps']['tts']['progress'] = 100
            project['steps']['tts']['error'] = str(e)
            project['status'] = 'error'
            project['error'] = f"TTS error: {str(e)}"
            return
        
        # 7. Replace audio (thêm âm thanh tiếng Việt vào video slow)
        project['current_step'] = 'replace_audio'
        project['steps']['replace_audio']['status'] = 'running'
        final_video = workdir / "final_video.mp4"
        replace_audio(slow_mp4, tts_wav, final_video)
        project['steps']['replace_audio']['status'] = 'completed'
        project['steps']['replace_audio']['progress'] = 100
        project['progress'] = 60
        
        # 8. Speed up (tăng tốc video có âm thanh tiếng Việt)
        project['current_step'] = 'speed_up'
        project['steps']['speed_up']['status'] = 'running'
        fast_video = workdir / "fast_video.mp4"
        speed_up_130(final_video, fast_video)
        project['steps']['speed_up']['status'] = 'completed'
        project['steps']['speed_up']['progress'] = 100
        project['progress'] = 70
        
        # 9. Silence Removal (optional) - cắt khoảng lặng cuối cùng (sau khi tăng tốc)
        project['current_step'] = 'silence_removal'
        project['steps']['silence_removal']['status'] = 'running'
        
        if full_config.get('enable_silence_removal', False):
            silence_removed_video = workdir / "silence_removed.mp4"
            from pipeline import remove_silence_ffmpeg_video_audio
            remove_silence_ffmpeg_video_audio(
                fast_video, silence_removed_video,  # Sử dụng fast_video (đã tăng tốc)
                threshold=full_config.get('silence_threshold', -50.0),
                min_duration=full_config.get('min_silence_duration', 0.4),
                max_duration=full_config.get('max_silence_duration', 2.0),
                padding=full_config.get('silence_padding', 0.1)
            )
            final_output = silence_removed_video  # Use processed video as final output
        else:
            final_output = fast_video  # Use speed-up video as final output
        
        project['steps']['silence_removal']['status'] = 'completed'
        project['steps']['silence_removal']['progress'] = 100
        project['progress'] = 80
        
        # 8. Music (optional) - Skip for now as we need to handle file uploads
        # if data.get('music_path'):
        #     project['current_step'] = 'music'
        #     project['steps']['music']['status'] = 'running'
        #     final_with_music = workdir / "final_with_music.mp4"
        #     add_background_music(fast_video, Path(data['music_path']), final_with_music)
        #     project['steps']['music']['status'] = 'completed'
        #     project['steps']['music']['progress'] = 100
        #     project['progress'] = 80
        
        # 9. Overlay (optional) - Skip for now as we need to handle file uploads
        # if data.get('overlay_path'):
        #     project['current_step'] = 'overlay'
        #     project['steps']['overlay']['status'] = 'running'
        #     final_output = workdir / "final_output.mp4"
        #     overlay_template(fast_video, Path(data['overlay_path']), final_output)
        #     project['steps']['overlay']['status'] = 'completed'
        #     project['steps']['overlay']['progress'] = 100
        #     project['progress'] = 90
        
        # Hoàn thành
        project['status'] = 'completed'
        project['progress'] = 100
        project['output_file'] = str(final_output)
        
        print(f"✅ Project {project_id} completed successfully!")
        
        # Kích hoạt dự án tiếp theo trong queue
        print(f"🔄 Checking queue for next project...")
        check_and_start_next_project()
        
    except Exception as e:
        print(f"❌ Pipeline error for project {project_id}: {e}")
        
        # Kiểm tra xem project có tồn tại không
        if project_id in projects:
            project = projects[project_id]
            project['status'] = 'error'
            vietnamese_error = get_vietnamese_error_message(str(e))
            project['error'] = vietnamese_error
            print(f"Vietnamese error message: {vietnamese_error}")
        else:
            print(f"Project {project_id} not found when handling pipeline error: {e}")
        
        # Kích hoạt dự án tiếp theo trong queue ngay cả khi dự án hiện tại bị lỗi
        print(f"🔄 Project {project_id} failed, starting next project in queue...")
        check_and_start_next_project()

@app.route('/api/retry/<project_id>/<step_name>', methods=['POST'])
def retry_step(project_id, step_name):
    if project_id not in projects:
        return jsonify({'error': 'Project not found'}), 404
    
    project = projects[project_id]
    
    if step_name not in project['steps']:
        return jsonify({'error': 'Invalid step name'}), 400
    
    # Định nghĩa thứ tự các bước
    step_order = ['download', 'slow', 'stt', 'translate', 'tts', 'replace_audio', 'speed_up', 'silence_removal']
    
    try:
        start_index = step_order.index(step_name)
    except ValueError:
        return jsonify({'error': 'Invalid step name'}), 400
    
    # Cho phép retry từ bất kỳ bước nào, kể cả khi project đã completed hoặc error
    print(f"🔄 Retry requested for project {project_id} from step '{step_name}' (current status: {project['status']})")
    
    # DỪNG tiến trình hiện tại nếu đang chạy
    if project['status'] == 'running':
        print(f"🛑 Stopping current pipeline for project {project_id}")
        project['status'] = 'stopped'
        # Đánh dấu tất cả các bước đang chạy thành pending
        for step_name_inner, step_data in project['steps'].items():
            if step_data['status'] == 'running':
                step_data['status'] = 'pending'
                step_data['progress'] = 0
                step_data['error'] = None  # Clear any previous errors
    
    # Reset chỉ các bước từ bước hiện tại trở đi (giữ lại kết quả các bước trước)
    for i in range(start_index, len(step_order)):
        reset_step = step_order[i]
        project['steps'][reset_step]['status'] = 'pending'
        project['steps'][reset_step]['progress'] = 0
        project['steps'][reset_step]['error'] = None
    
    # Tính lại progress dựa trên các bước đã hoàn thành
    completed_steps = sum(1 for step in project['steps'].values() if step['status'] == 'completed')
    total_steps = len(project['steps'])
    project['progress'] = int((completed_steps / total_steps) * 100)
    
    # Reset trạng thái dự án
    project['status'] = 'running'
    project['current_step'] = step_name
    project['error'] = None
    project['output_file'] = None
    
    print(f"🔄 Starting retry from step '{step_name}' for project {project_id}")
    
    # Chạy lại pipeline từ bước được chọn
    thread = threading.Thread(target=run_pipeline_from_step, args=(project_id, step_name))
    thread.daemon = True
    thread.start()
    
    return jsonify({'status': 'success', 'message': f'Retrying pipeline from step: {step_name}'})

def run_pipeline_from_step(project_id, start_step, config=None):
    """Chạy pipeline từ một bước cụ thể, sử dụng tài nguyên từ các bước trước đó"""
    try:
        project = projects[project_id]
        workdir = Path(f"projects/{project_id}")
        
        # Đảm bảo config có đầy đủ thông tin
        if config is None:
            config = DEFAULT_CONFIG.copy()
        else:
            full_config = DEFAULT_CONFIG.copy()
            full_config.update(config)
            config = full_config
        
        print(f"🔄 Running pipeline from step: {start_step} for project {project_id}")
        
        # Danh sách các bước theo thứ tự
        step_order = ['download', 'slow', 'stt', 'translate', 'tts', 'replace_audio', 'silence_removal', 'speed_up', 'music', 'overlay']
        
        try:
            start_index = step_order.index(start_step)
        except ValueError:
            print(f"❌ Invalid step name: {start_step}")
            project['status'] = 'error'
            project['error'] = f'Invalid step name: {start_step}'
            return
        
        # Kiểm tra và tạo các file cần thiết từ các bước trước đó
        print(f"🔍 Checking required files from previous steps...")
        
        # Mapping các file cần thiết cho từng bước
        required_files = {
            'slow': ['input.mp4'],
            'stt': ['slow.mp4'],
            'translate': ['subs_raw.srt'],
            'tts': ['subs_vi.srt'],
            'replace_audio': ['slow.mp4', 'tts.wav'],
            'silence_removal': ['final_video.mp4'],
            'speed_up': ['silence_removed.mp4'],
            'music': ['fast_video.mp4'],
            'overlay': ['final_video.mp4']
        }
        
        # Kiểm tra file cần thiết cho bước hiện tại
        if start_step in required_files:
            missing_files = []
            for file_name in required_files[start_step]:
                file_path = workdir / file_name
                if not file_path.exists():
                    missing_files.append(file_name)
            
            if missing_files:
                error_msg = f"Missing required files for step '{start_step}': {', '.join(missing_files)}"
                print(f"❌ {error_msg}")
                project['status'] = 'error'
                project['error'] = error_msg
                check_and_start_next_project()
                return
        
        # Chạy từ bước bắt đầu đến cuối
        for i in range(start_index, len(step_order)):
            step = step_order[i]
            
            # Kiểm tra xem project có còn tồn tại không
            if project_id not in projects:
                print(f"❌ Project {project_id} no longer exists, stopping pipeline")
                return
            
            # Kiểm tra xem project có bị dừng không
            if project['status'] == 'stopped':
                print(f"🛑 Project {project_id} was stopped, ending pipeline")
                return
            
            # Cập nhật bước hiện tại
            project['current_step'] = step
            project['steps'][step]['status'] = 'running'
            
            print(f"🔄 Running step: {step}")
            
            try:
                # Chạy bước hiện tại
                run_single_step(project_id, step, workdir, config)
                
                # Cập nhật trạng thái thành công
                project['steps'][step]['status'] = 'completed'
                project['steps'][step]['progress'] = 100
                
                # Tính progress tổng thể
                completed_steps = len([s for s in project['steps'].values() if s['status'] == 'completed'])
                total_steps = len(project['steps'])
                project['progress'] = int((completed_steps / total_steps) * 100)
                
            except Exception as e:
                # Cập nhật trạng thái lỗi
                project['steps'][step]['status'] = 'error'
                project['steps'][step]['progress'] = 0
                project['steps'][step]['error'] = str(e)
                project['status'] = 'error'
                project['error'] = str(e)
                
                vietnamese_error = get_vietnamese_error_message(str(e))
                print(f"❌ Error in step {step}: {vietnamese_error}")
                
                # Kích hoạt dự án tiếp theo trong queue
                check_and_start_next_project()
                return
        
        # Hoàn thành tất cả các bước
        project['status'] = 'completed'
        project['progress'] = 100
        
        # Tìm file output cuối cùng
        final_output = None
        for output_file in ['final_video.mp4', 'fast_video.mp4', 'silence_removed.mp4', 'slow.mp4']:
            if (workdir / output_file).exists():
                final_output = workdir / output_file
                break
        
        if final_output:
            project['output_file'] = str(final_output)
        
        print(f"✅ Project {project_id} completed from step {start_step}")
        
        # Kích hoạt dự án tiếp theo trong queue
        check_and_start_next_project()
        
    except Exception as e:
        print(f"❌ Pipeline error for project {project_id}: {e}")
        
        # Kiểm tra xem project có tồn tại không
        if project_id in projects:
            project = projects[project_id]
            project['status'] = 'error'
            vietnamese_error = get_vietnamese_error_message(str(e))
            project['error'] = vietnamese_error
            print(f"Vietnamese error message: {vietnamese_error}")
        else:
            print(f"Project {project_id} not found when handling pipeline error: {e}")
        
        # Kích hoạt dự án tiếp theo trong queue ngay cả khi dự án hiện tại bị lỗi
        print(f"🔄 Project {project_id} failed, starting next project in queue...")
        check_and_start_next_project()


def run_single_step(project_id, step_name, workdir=None, config=None):
    """Chạy lại một step cụ thể"""
    try:
        project = projects[project_id]
        
        # Kiểm tra nếu dự án đã bị dừng
        if project['status'] == 'stopped':
            print(f"Project {project_id} is stopped, skipping step {step_name}")
            return
        
        # Đảm bảo config có đầy đủ thông tin
        if config is None:
            config = DEFAULT_CONFIG.copy()
        else:
            full_config = DEFAULT_CONFIG.copy()
            full_config.update(config)
            config = full_config
            
        if workdir is None:
            workdir = Path(f"projects/{project_id}")
        
        # Cập nhật trạng thái
        project['current_step'] = step_name
        project['steps'][step_name]['status'] = 'running'
        project['status'] = 'running'
        
        if step_name == 'download':
            # Download lại video
            input_mp4 = workdir / "input.mp4"
            download_with_ytdlp(project['url'], input_mp4)
            project['steps']['download']['status'] = 'completed'
            project['steps']['download']['progress'] = 100
            project['progress'] = 10
            
        elif step_name == 'slow':
            # Giảm tốc độ video
            input_mp4 = workdir / "input.mp4"
            if not input_mp4.exists():
                raise RuntimeError("File input.mp4 không tồn tại. Hãy chạy bước 'download' trước.")
            
            slow_mp4 = workdir / "slow.mp4"
            slow_down_video(input_mp4, slow_mp4)
            project['steps']['slow']['status'] = 'completed'
            project['steps']['slow']['progress'] = 100
            project['progress'] = 20
            
        elif step_name == 'stt':
            # Speech-to-Text - sử dụng file slow.mp4 đã có
            slow_mp4 = workdir / "slow.mp4"
            if not slow_mp4.exists():
                raise RuntimeError("File slow.mp4 không tồn tại. Hãy chạy bước 'slow' trước.")
            
            stt_wav = workdir / "stt.wav"
            subs_srt_raw = workdir / "subs_raw.srt"
            extract_audio_for_stt(slow_mp4, stt_wav)
            try:
                stt_assemblyai(stt_wav, subs_srt_raw, config['assemblyai_api_key'], language_code=config['stt_language'])
                project['steps']['stt']['status'] = 'completed'
                project['steps']['stt']['progress'] = 100
            except Exception as e:
                print(f"AssemblyAI STT failed: {e}")
                with open(subs_srt_raw, 'w', encoding='utf-8') as f:
                    f.write("1\n00:00:00,000 --> 00:00:05,000\n[Audio processing failed]\n\n")
                project['steps']['stt']['status'] = 'error'
                project['steps']['stt']['progress'] = 100
                project['steps']['stt']['error'] = str(e)
                raise e  # Re-raise để xử lý trong exception handler
            project['progress'] = 25
            

            
        elif step_name == 'translate':
            # Dịch thuật - sử dụng file subs.srt đã có
            subs_srt = workdir / "subs.srt"
            if not subs_srt.exists():
                raise RuntimeError("File subs.srt không tồn tại. Hãy chạy bước 'stt' trước.")
            
            subs_translated_srt = workdir / "subs_vi.srt"
            
            # Sử dụng Gemini với retry logic và key management
            max_retries = 3  # 3 lần retry, mỗi lần thử tất cả keys
            last_error = None
            
            # Thử tất cả keys trước khi báo lỗi
            backup_keys = config.get('gemini_backup_keys', [])
            user_key = config.get('gemini_api_key', '').strip()
            all_keys = [user_key] + backup_keys if user_key else backup_keys
            
            translation_success = False
            for retry_attempt in range(max_retries):
                for key_index, current_gemini_key in enumerate(all_keys):
                    if not current_gemini_key:
                        continue
                        
                    try:
                        print(f"🔄 Translation attempt {retry_attempt + 1}/{max_retries} with Gemini key #{key_index + 1}")
                        
                        # Chỉ sử dụng Gemini cho AI translation
                        translate_srt_ai(subs_srt, subs_translated_srt, model=config['gemini_model'], api_key=current_gemini_key, provider='gemini', config=config)
                        
                        project['steps']['translate']['status'] = 'completed'
                        project['steps']['translate']['progress'] = 100
                        project['progress'] = 40
                        print(f"✅ Translation completed successfully with key #{key_index + 1}")
                        translation_success = True
                        break  # Thoát khỏi vòng lặp key nếu thành công
                        
                    except Exception as e:
                        last_error = e
                        print(f"❌ Translation failed with key #{key_index + 1}: {e}")
                        
                        # Chờ một chút trước khi thử key tiếp theo
                        if key_index < len(all_keys) - 1:
                            time.sleep(1)
                
                # Nếu translation thành công, thoát khỏi vòng lặp retry
                if translation_success:
                    break
                
                # Chờ lâu hơn trước khi retry toàn bộ
                if retry_attempt < max_retries - 1:
                    print(f"🔄 Retrying all keys (attempt {retry_attempt + 2}/{max_retries})")
                    time.sleep(3)
            
            # Kiểm tra nếu translation đã thành công
            if project['steps']['translate']['status'] == 'completed':
                print(f"✅ Translation step completed successfully")
            else:
                # Nếu tất cả retry đều thất bại
                project['steps']['translate']['status'] = 'error'
                project['steps']['translate']['error'] = str(last_error)
                raise last_error
            
        elif step_name == 'tts':
            # Text-to-Speech - sử dụng file subs_vi.srt đã có
            subs_translated_srt = workdir / "subs_vi.srt"
            if not subs_translated_srt.exists():
                raise RuntimeError("File subs_vi.srt không tồn tại. Hãy chạy bước 'translate' trước.")
            
            tts_wav = workdir / "tts.wav"
            
            try:
                # Chọn TTS provider dựa trên cấu hình
                # Chỉ sử dụng FPT AI cho TTS với key management
                from pipeline import srt_to_aligned_audio_fpt_ai_with_failover
                current_key = get_current_fpt_key(config)
                if not current_key:
                    raise RuntimeError("No FPT AI API key available")
                
                srt_to_aligned_audio_fpt_ai_with_failover(
                    subs_translated_srt, tts_wav,
                    config,  # Pass full config for key management
                    config['fpt_voice'],
                    config.get('fpt_speed', '-1'),
                    config.get('fpt_format', 'mp3'),
                    speech_speed=config.get('fpt_speech_speed', '0.8')
                )
                project['steps']['tts']['status'] = 'completed'
                project['steps']['tts']['progress'] = 100
                project['progress'] = 50
            except Exception as e:
                print(f"TTS retry failed: {e}")
                project['steps']['tts']['status'] = 'error'
                project['steps']['tts']['error'] = str(e)
                raise e
            
        elif step_name == 'replace_audio':
            # Thay thế audio - sử dụng file slow.mp4 và tts.wav đã có
            slow_mp4 = workdir / "slow.mp4"
            if not slow_mp4.exists():
                raise RuntimeError("File slow.mp4 không tồn tại. Hãy chạy bước 'slow' trước.")
            
            tts_wav = workdir / "tts.wav"
            if not tts_wav.exists():
                raise RuntimeError("File tts.wav không tồn tại. Hãy chạy bước 'tts' trước.")
            
            final_video = workdir / "final_video.mp4"
            replace_audio(slow_mp4, tts_wav, final_video)
            project['steps']['replace_audio']['status'] = 'completed'
            project['steps']['replace_audio']['progress'] = 100
            project['progress'] = 60
            
        elif step_name == 'speed_up':
            # Tăng tốc độ (video có âm thanh tiếng Việt)
            final_video = workdir / "final_video.mp4"
            if not final_video.exists():
                raise RuntimeError("File final_video.mp4 không tồn tại. Hãy chạy bước 'replace_audio' trước.")
            
            fast_video = workdir / "fast_video.mp4"
            speed_up_130(final_video, fast_video)
            project['steps']['speed_up']['status'] = 'completed'
            project['steps']['speed_up']['progress'] = 100
            project['progress'] = 70
            
        elif step_name == 'silence_removal':
            # Cắt khoảng lặng cuối cùng (tùy chọn)
            fast_video = workdir / "fast_video.mp4"
            if not fast_video.exists():
                raise RuntimeError("File fast_video.mp4 không tồn tại. Hãy chạy bước 'speed_up' trước.")
            
            if config.get('enable_silence_removal', False):
                print(f"🔇 Silence removal enabled, processing video...")
                silence_removed_video = workdir / "silence_removed.mp4"
                from pipeline import remove_silence_ffmpeg_video_audio
                remove_silence_ffmpeg_video_audio(
                    fast_video, silence_removed_video,
                    threshold=config.get('silence_threshold', -50.0),
                    min_duration=config.get('min_silence_duration', 0.4),
                    max_duration=config.get('max_silence_duration', 2.0),
                    padding=config.get('silence_padding', 0.1)
                )
                final_output = silence_removed_video
                print(f"✅ Silence removal completed: {silence_removed_video}")
            else:
                print(f"⏭️ Silence removal disabled, skipping...")
                final_output = fast_video
            
            project['steps']['silence_removal']['status'] = 'completed'
            project['steps']['silence_removal']['progress'] = 100
            project['progress'] = 80
            
        # Cập nhật trạng thái tổng thể
        if all(step['status'] == 'completed' for step in project['steps'].values()):
            project['status'] = 'completed'
            project['progress'] = 100
            # Xác định output file cuối cùng
            if config.get('enable_silence_removal', False):
                project['output_file'] = str(workdir / "silence_removed.mp4")
            else:
                project['output_file'] = str(workdir / "fast_video.mp4")
            print(f"✅ All steps completed for project {project_id}")
                    
    except Exception as e:
        # Kiểm tra xem project có tồn tại không
        if project_id in projects:
            project = projects[project_id]
            vietnamese_error = get_vietnamese_error_message(str(e))
            project['steps'][step_name]['status'] = 'error'
            project['steps'][step_name]['error'] = vietnamese_error
            project['error'] = vietnamese_error
            print(f"Step {step_name} error: {e}")
            print(f"Vietnamese message: {vietnamese_error}")
        else:
            print(f"Project {project_id} not found when handling error for step {step_name}: {e}")

@app.route('/api/download/<project_id>')
def download_result(project_id):
    if project_id not in projects:
        return jsonify({'error': 'Project not found'}), 404
    
    project = projects[project_id]
    if project['status'] != 'completed':
        return jsonify({'error': 'Project not completed'}), 400
    
    output_file = Path(project['output_file'])
    if not output_file.exists():
        return jsonify({'error': 'Output file not found'}), 404
    
    return send_file(output_file, as_attachment=True)

@app.route('/api/stop/<project_id>', methods=['POST'])
def stop_project(project_id):
    """Dừng một project đang chạy"""
    if project_id not in projects:
        return jsonify({'error': 'Project not found'}), 404
    
    project = projects[project_id]
    
    if project['status'] != 'running':
        return jsonify({'error': 'Project is not running'}), 400
    
    print(f"🛑 Stopping project {project_id}...")
    
    # Đánh dấu project là stopped
    project['status'] = 'stopped'
    project['error'] = 'Project stopped by user'
    
    return jsonify({'status': 'success', 'message': f'Project {project_id} stopped successfully'})

@app.route('/api/restart/<project_id>', methods=['POST'])
def restart_project(project_id):
    """Restart một project từ đầu"""
    if project_id not in projects:
        return jsonify({'error': 'Project not found'}), 404
    
    project = projects[project_id]
    
    print(f"🔄 Restarting project {project_id} from beginning...")
    
    # Reset tất cả các bước về pending
    for step_name, step_data in project['steps'].items():
        step_data['status'] = 'pending'
        step_data['progress'] = 0
        step_data['error'] = None
    
    # Reset trạng thái project
    project['status'] = 'queued'  # Đặt về queue để chờ chạy
    project['current_step'] = 'download'
    project['progress'] = 0
    project['error'] = None
    project['output_file'] = None
    project['start_time'] = None
    
    # Xóa các file cũ nếu có
    project_dir = Path(f"projects/{project_id}")
    if project_dir.exists():
        try:
            # Xóa các file đã tạo trước đó
            for file_pattern in ['input.mp4', 'slow.mp4', 'stt.wav', 'subs_raw.srt', 'subs.srt', 
                               'subs_vi.srt', 'tts.wav', 'final_video.mp4', 'fast_video.mp4', 
                               'silence_removed.mp4']:
                for file_path in project_dir.glob(file_pattern):
                    try:
                        file_path.unlink()
                        print(f"🗑️ Deleted old file: {file_path}")
                    except:
                        pass
        except Exception as e:
            print(f"⚠️ Error cleaning old files: {e}")
    
    # Kiểm tra xem có project nào đang chạy không
    running_projects = [p for p in projects.values() if p['status'] == 'running']
    
    if len(running_projects) == 0:
        # Không có project nào đang chạy, chạy ngay
        project['status'] = 'running'
        project['queue_position'] = 0
        print(f"🚀 Starting restarted project {project_id} immediately")
        
        # Sử dụng DEFAULT_CONFIG
        config = DEFAULT_CONFIG.copy()
        
        thread = threading.Thread(target=run_pipeline_async, args=(project_id, project['url'], project_dir, config))
        thread.daemon = True
        thread.start()
    else:
        # Có project đang chạy, thêm vào queue
        queued_projects = [p for p in projects.values() if p['status'] == 'queued']
        project['queue_position'] = len(queued_projects)
        print(f"📋 Restarted project {project_id} added to queue (position: {project['queue_position']})")
    
    return jsonify({'status': 'success', 'message': f'Project {project_id} restarted successfully'})

@app.route('/api/restart-from-step/<project_id>/<step_name>', methods=['POST'])
def restart_from_step(project_id, step_name):
    """Restart một project từ một bước cụ thể, sử dụng tài nguyên từ các bước trước đó"""
    if project_id not in projects:
        return jsonify({'error': 'Project not found'}), 404
    
    project = projects[project_id]
    
    # Danh sách các bước theo thứ tự
    step_order = ['download', 'slow', 'stt', 'translate', 'tts', 'replace_audio', 'silence_removal', 'speed_up', 'music', 'overlay']
    
    if step_name not in step_order:
        return jsonify({'error': f'Invalid step: {step_name}'}), 400
    
    print(f"🔄 Restarting project {project_id} from step: {step_name}")
    
    # Nếu project đang chạy, dừng nó trước
    if project['status'] == 'running':
        project['status'] = 'stopped'
        project['error'] = 'Project stopped to restart from step'
    
    # Reset tất cả các bước từ step_name trở đi về pending
    step_index = step_order.index(step_name)
    for i in range(step_index, len(step_order)):
        step = step_order[i]
        if step in project['steps']:
            project['steps'][step]['status'] = 'pending'
            project['steps'][step]['progress'] = 0
            project['steps'][step]['error'] = None
    
    # Giữ nguyên các bước trước đó (completed)
    for i in range(0, step_index):
        step = step_order[i]
        if step in project['steps']:
            project['steps'][step]['status'] = 'completed'
            project['steps'][step]['progress'] = 100
            project['steps'][step]['error'] = None
    
    # Cập nhật trạng thái project
    project['status'] = 'queued'
    project['current_step'] = step_name
    project['error'] = None
    project['output_file'] = None
    project['start_time'] = None
    
    # Tính lại progress dựa trên số bước đã hoàn thành
    completed_steps = len([s for s in project['steps'].values() if s['status'] == 'completed'])
    total_steps = len(project['steps'])
    project['progress'] = int((completed_steps / total_steps) * 100)
    
    # Kiểm tra xem có project nào đang chạy không
    running_projects = [p for p in projects.values() if p['status'] == 'running']
    
    if len(running_projects) == 0:
        # Không có project nào đang chạy, chạy ngay
        project['status'] = 'running'
        project['queue_position'] = 0
        print(f"🚀 Starting project {project_id} from step {step_name} immediately")
        
        # Sử dụng DEFAULT_CONFIG
        config = DEFAULT_CONFIG.copy()
        
        thread = threading.Thread(target=run_pipeline_from_step, args=(project_id, step_name, config))
        thread.daemon = True
        thread.start()
    else:
        # Có project đang chạy, thêm vào queue
        queued_projects = [p for p in projects.values() if p['status'] == 'queued']
        project['queue_position'] = len(queued_projects)
        print(f"📋 Project {project_id} restarted from step {step_name} added to queue (position: {project['queue_position']})")
    
    return jsonify({
        'status': 'success', 
        'message': f'Project {project_id} will restart from step: {step_name}',
        'restart_step': step_name,
        'completed_steps': [s for s in step_order[:step_index]],
        'pending_steps': [s for s in step_order[step_index:]]
    })

@app.route('/api/delete/<project_id>', methods=['DELETE'])
def delete_project(project_id):
    if project_id not in projects:
        return jsonify({'error': 'Project not found'}), 404
    
    project = projects[project_id]
    
    # Xóa folder dự án
    project_dir = Path(f"projects/{project_id}")
    if project_dir.exists():
        try:
            shutil.rmtree(project_dir)
            print(f"🗑️ Deleted project folder: {project_dir}")
        except Exception as e:
            print(f"⚠️ Error deleting project folder: {e}")
    
    # Xóa khỏi danh sách projects
    del projects[project_id]
    
    # Xóa khỏi queue nếu đang trong queue (không cần thiết nữa vì không dùng queue.Queue)
    print(f"🗑️ Project {project_id} removed from projects list")
    
    return jsonify({'status': 'success', 'message': 'Project deleted successfully'})

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    filename = secure_filename(file.filename)
    upload_dir = Path('uploads')
    upload_dir.mkdir(exist_ok=True)
    
    file_path = upload_dir / filename
    file.save(file_path)
    
    return jsonify({'file_path': str(file_path)})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)


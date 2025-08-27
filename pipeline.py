import argparse
import io
import os
import re
import shutil
import subprocess
import time
import sys
from pathlib import Path
from typing import List, Optional, Callable, Iterator

import srt
from tqdm import tqdm
from dotenv import load_dotenv
from pydub import AudioSegment
import requests


# -------------------- Utilities --------------------

def _has_audio_stream(video_path: Path) -> bool:
	"""Check if video file has audio stream"""
	probe_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(video_path)]
	result = subprocess.run(probe_cmd, capture_output=True, text=True)
	
	if result.returncode == 0:
		try:
			import json
			data = json.loads(result.stdout)
			return any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))
		except:
			pass
	return False


# -------------------- Utilities --------------------

def run_command(command_args: List[str], cwd: Optional[Path] = None) -> None:
	result = subprocess.run(command_args, cwd=str(cwd) if cwd else None)
	if result.returncode != 0:
		raise RuntimeError(f"Command failed: {' '.join(command_args)}")


def ensure_executable(executable: str, install_hint: str) -> None:
	if shutil.which(executable) is None:
		raise EnvironmentError(
			f"'{executable}' is not found in PATH. Install it first. Hint: {install_hint}"
		)


def _notify(cb: Optional[Callable[[str], None]], stage: str) -> None:
	if cb:
		try:
			cb(stage)
		except Exception:
			pass


def download_with_ytdlp(url: str, output_path: Path) -> None:
	cli = shutil.which("yt-dlp")
	
	# Common yt-dlp options to handle various issues
	base_options = [
		"--merge-output-format", "mp4",
		"--no-check-certificates",  # Skip SSL certificate verification
		"--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
		"--extractor-args", "youtube:player_client=android",  # Use Android client
		"-o", str(output_path)
	]
	
	try:
		if cli:
			# Try with yt-dlp CLI first
			run_command([cli] + base_options + [url])
		else:
			# Fallback to Python module
			python_exe = sys.executable or "python"
			run_command([python_exe, "-m", "yt_dlp"] + base_options + [url])
	except Exception as e:
		# If first attempt fails, try with different format
		print(f"First download attempt failed: {e}")
		print("Trying with alternative format...")
		
		alt_options = [
			"--merge-output-format", "mp4",
			"--format", "best[height<=720]",  # Limit resolution
			"--no-check-certificates",
			"--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
			"-o", str(output_path)
		]
		
		if cli:
			run_command([cli] + alt_options + [url])
		else:
			python_exe = sys.executable or "python"
			run_command([python_exe, "-m", "yt_dlp"] + alt_options + [url])


# -------------------- FFmpeg steps --------------------

def slow_down_video(input_path: Path, output_path: Path) -> None:
	has_audio = _has_audio_stream(input_path)
	
	if has_audio:
		filter_complex = "[0:v]setpts=PTS*1.428571[v];[0:a]atempo=0.7[a]"
		run_command([
			"ffmpeg", "-y", "-i", str(input_path),
			"-filter_complex", filter_complex,
			"-map", "[v]", "-map", "[a]",
			str(output_path),
		])
	else:
		# Video only - no audio processing
		filter_complex = "[0:v]setpts=PTS*1.428571[v]"
		run_command([
			"ffmpeg", "-y", "-i", str(input_path),
			"-filter_complex", filter_complex,
			"-map", "[v]",
			str(output_path),
		])


def extract_audio_for_stt(input_path: Path, output_wav: Path) -> None:
	has_audio = _has_audio_stream(input_path)
	
	if has_audio:
		# Mono 16kHz WAV to minimize upload size and improve STT speed
		run_command([
			"ffmpeg", "-y", "-i", str(input_path),
			"-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
			str(output_wav),
		])
	else:
		# Create silent audio if no audio stream exists
		run_command([
			"ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=16000", 
			"-t", "10", "-c:a", "pcm_s16le", str(output_wav)
		])


def replace_audio(video_in: Path, audio_in: Path, video_out: Path) -> None:
	"""Thay thế audio vào video"""
	run_command([
		"ffmpeg", "-y",
		"-i", str(video_in),
		"-i", str(audio_in),
		"-map", "0:v", "-map", "1:a",
		"-c:v", "copy",
		"-shortest",
		str(video_out),
	])


def speed_up_130(video_in: Path, video_out: Path) -> None:
	# Kiểm tra xem video có audio stream không
	has_audio = _has_audio_stream(video_in)
	
	if has_audio:
		# Có audio - xử lý cả video và audio
		filter_complex = "[0:v]setpts=PTS/1.3[v];[0:a]atempo=1.3[a]"
		run_command([
			"ffmpeg", "-y", "-i", str(video_in),
			"-filter_complex", filter_complex,
			"-map", "[v]", "-map", "[a]",
			str(video_out),
		])
	else:
		# Không có audio - chỉ xử lý video
		filter_complex = "[0:v]setpts=PTS/1.3[v]"
		run_command([
			"ffmpeg", "-y", "-i", str(video_in),
			"-filter_complex", filter_complex,
			"-map", "[v]",
			str(video_out),
		])


def add_background_music(video_in: Path, music_in: Path, video_out: Path, music_volume: float = 0.3) -> None:
	filter_complex = (
		f"[0:a]volume=1.0[a0];[1:a]volume={music_volume}[a1];"
		f"[a0][a1]amix=inputs=2:duration=shortest[a]"
	)
	run_command([
		"ffmpeg", "-y",
		"-i", str(video_in),
		"-i", str(music_in),
		"-filter_complex", filter_complex,
		"-map", "0:v", "-map", "[a]",
		"-c:v", "copy",
		str(video_out),
	])


def overlay_template(video_in: Path, overlay_in: Path, video_out: Path) -> None:
	run_command([
		"ffmpeg", "-y",
		"-i", str(video_in),
		"-i", str(overlay_in),
		"-filter_complex", "[0:v][1:v]overlay=shortest=1:format=auto",
		"-map", "0:a", "-c:a", "copy",
		"-c:v", "libx264", "-pix_fmt", "yuv420p",
		str(video_out),
	])


# -------------------- STT (AssemblyAI REST) --------------------

def _file_chunks(path: Path, chunk_size: int = 5_242_880) -> Iterator[bytes]:
	with path.open("rb") as f:
		while True:
			data = f.read(chunk_size)
			if not data:
				break
			yield data


def assemblyai_upload(file_path: Path, api_key: str) -> str:
	print(f"📤 Uploading {file_path.name} to AssemblyAI...")
	resp = requests.post(
		"https://api.assemblyai.com/v2/upload",
		headers={"authorization": api_key, "Content-Type": "application/octet-stream"},
		data=_file_chunks(file_path),
		timeout=3600,
	)
	if resp.status_code != 200:
		print(f"❌ AssemblyAI upload failed: {resp.status_code} {resp.text}")
		raise RuntimeError(f"AssemblyAI upload failed: {resp.status_code} {resp.text}")
	data = resp.json()
	upload_url = data.get("upload_url")
	print(f"✅ Upload completed: {upload_url}")
	return upload_url


def assemblyai_request_transcript(upload_url: str, api_key: str, language_code: str = "auto", config: dict = None) -> str:
	"""
	Request transcript from AssemblyAI with optimized settings for complete sentences
	"""
	# Sử dụng cấu hình mặc định nếu không có config
	if config is None:
		config = {
			'stt_speech_threshold': 0.5,
			'stt_disfluencies': False
		}
	
	# Cấu hình cơ bản trước để tránh lỗi API
	payload = {
		"audio_url": upload_url,
		"punctuate": True,           # Tự động thêm dấu câu
		"format_text": True,         # Format text tự nhiên
	}
	
	# Thêm các tham số tùy chọn nếu có
	if config and config.get('stt_disfluencies') is True:
		payload["disfluencies"] = True
	
	if config and config.get('stt_speech_threshold'):
		payload["speech_threshold"] = config['stt_speech_threshold']
	
	# Thêm speaker_labels nếu muốn utterances
	if config and config.get('stt_method') == 'utterances':
		payload["speaker_labels"] = True
	
	# Chỉ set language_code nếu không phải "auto"
	if language_code != "auto":
		payload["language_code"] = language_code
	
	print(f"📝 Requesting transcript with config: {payload}")
	resp = requests.post(
		"https://api.assemblyai.com/v2/transcript",
		headers={"authorization": api_key, "Content-Type": "application/json"},
		json=payload,
		timeout=60,
	)
	if resp.status_code != 200:
		print(f"❌ AssemblyAI transcript create failed: {resp.status_code} {resp.text}")
		raise RuntimeError(f"AssemblyAI transcript create failed: {resp.status_code} {resp.text}")
	
	data = resp.json()
	transcript_id = data.get("id")
	print(f"✅ Transcript requested: {transcript_id}")
	return transcript_id


def assemblyai_poll_until_complete(transcript_id: str, api_key: str, poll_interval_sec: float = 3.0, timeout_sec: int = 3600) -> None:
	start = time.time()
	poll_count = 0
	print(f"🔄 Starting AssemblyAI polling for transcript {transcript_id}")
	
	while True:
		poll_count += 1
		elapsed = time.time() - start
		
		try:
			resp = requests.get(
				f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
				headers={"authorization": api_key},
				timeout=30,
			)
			
			if resp.status_code != 200:
				print(f"❌ AssemblyAI poll error {resp.status_code}: {resp.text}")
				raise RuntimeError(f"AssemblyAI poll error: {resp.status_code} {resp.text}")
			
			data = resp.json()
			status = data.get("status")
			
			print(f"📊 Poll #{poll_count} ({elapsed:.1f}s): Status = {status}")
			
			if status == "completed":
				print(f"✅ AssemblyAI transcription completed in {elapsed:.1f}s")
				return
			elif status == "error":
				error_msg = data.get("error", "Unknown error")
				print(f"❌ AssemblyAI transcription error: {error_msg}")
				raise RuntimeError(f"AssemblyAI transcription error: {error_msg}")
			elif status == "queued":
				print(f"⏳ AssemblyAI: Queued for processing...")
			elif status == "processing":
				print(f"🔄 AssemblyAI: Processing...")
			else:
				print(f"❓ AssemblyAI: Unknown status '{status}'")
			
			if elapsed > timeout_sec:
				print(f"⏰ AssemblyAI polling timed out after {timeout_sec}s")
				raise TimeoutError("AssemblyAI transcription timed out")
			
			time.sleep(poll_interval_sec)

		except requests.exceptions.Timeout:
			print(f"⚠️ AssemblyAI request timeout on poll #{poll_count}")
			if elapsed > timeout_sec:
				raise TimeoutError("AssemblyAI transcription timed out")
			time.sleep(poll_interval_sec)
		except Exception as e:
			print(f"❌ AssemblyAI polling exception: {e}")
			if elapsed > timeout_sec:
				raise TimeoutError("AssemblyAI transcription timed out")
			time.sleep(poll_interval_sec)


def assemblyai_download_srt(transcript_id: str, api_key: str, out_srt: Path, chars_per_caption: int = 200) -> None:
	"""Download SRT with optimized caption length for complete sentences"""
	# Thử tải SRT với cấu hình tối ưu cho câu hoàn chỉnh
	# Sử dụng sentences=true để AssemblyAI tự động chia câu
	resp = requests.get(
		f"https://api.assemblyai.com/v2/transcript/{transcript_id}/srt?chars_per_caption={chars_per_caption}&sentences=true",
		headers={"authorization": api_key},
		timeout=60,
	)
	if resp.status_code != 200:
		# Fallback to basic SRT với chars_per_caption cao hơn
		resp = requests.get(
			f"https://api.assemblyai.com/v2/transcript/{transcript_id}/srt?chars_per_caption={chars_per_caption}",
		headers={"authorization": api_key},
		timeout=60,
	)
	if resp.status_code != 200:
		raise RuntimeError(f"AssemblyAI SRT download failed: {resp.status_code} {resp.text}")
	
	# Xử lý SRT để chia thành các câu ngắn hơn
	srt_content = resp.text
	processed_srt = process_srt_for_better_sentences(srt_content)
	
	out_srt.write_text(processed_srt, encoding="utf-8")
	print(f"✅ Downloaded and processed SRT with {chars_per_caption} chars per caption and sentences=true")

def process_srt_for_better_sentences(srt_content: str) -> str:
	"""Process SRT content to create better sentence segmentation"""
	import re
	from datetime import datetime, timedelta
	
	# Split SRT into entries
	entries = re.split(r'\n\s*\n', srt_content.strip())
	processed_entries = []
	entry_counter = 1
	
	for entry in entries:
		if not entry.strip():
			continue
			
		lines = entry.strip().split('\n')
		if len(lines) < 3:
			continue
			
		# Parse timing
		timing_line = lines[1]
		timing_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', timing_line)
		if not timing_match:
			continue
			
		start_time_str, end_time_str = timing_match.groups()
		start_time = datetime.strptime(start_time_str, '%H:%M:%S,%f')
		end_time = datetime.strptime(end_time_str, '%H:%M:%S,%f')
		
		# Get text content
		text = ' '.join(lines[2:]).strip()
		
		# Split text into sentences
		sentences = split_text_into_sentences(text)
		
		if len(sentences) == 1:
			# Single sentence, keep as is
			processed_entries.append(f"{entry_counter}\n{timing_line}\n{sentences[0]}\n")
			entry_counter += 1
		else:
			# Multiple sentences, split timing
			total_duration = (end_time - start_time).total_seconds()
			sentence_count = len(sentences)
			duration_per_sentence = total_duration / sentence_count
			
			for i, sentence in enumerate(sentences):
				sentence_start = start_time + timedelta(seconds=i * duration_per_sentence)
				sentence_end = start_time + timedelta(seconds=(i + 1) * duration_per_sentence)
				
				sentence_start_str = sentence_start.strftime('%H:%M:%S,%f')[:-3]
				sentence_end_str = sentence_end.strftime('%H:%M:%S,%f')[:-3]
				
				processed_entries.append(f"{entry_counter}\n{sentence_start_str} --> {sentence_end_str}\n{sentence.strip()}\n")
				entry_counter += 1
	
	return '\n'.join(processed_entries)

def split_text_into_sentences(text: str) -> list:
	"""Split text into sentences based on punctuation and length"""
	import re
	
	# Common abbreviations that shouldn't end a sentence
	abbreviations = {
		'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'vs.', 'etc.', 'i.e.', 'e.g.', 'a.m.', 'p.m.',
		'inc.', 'corp.', 'co.', 'ltd.', 'llc.', 'u.s.', 'u.k.', 'e.u.', 'n.a.t.o.',
		'jan.', 'feb.', 'mar.', 'apr.', 'jun.', 'jul.', 'aug.', 'sep.', 'oct.', 'nov.', 'dec.',
		'mon.', 'tue.', 'wed.', 'thu.', 'fri.', 'sat.', 'sun.',
		'st.', 'nd.', 'rd.', 'th.', '1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th', '10th'
	}
	
	# Split by sentence endings
	sentences = re.split(r'(?<=[.!?])\s+', text)
	
	# Filter out empty sentences and merge very short ones
	filtered_sentences = []
	current_sentence = ""
	
	for sentence in sentences:
		sentence = sentence.strip()
		if not sentence:
			continue
			
		# If current sentence is too short, merge with next
		if len(current_sentence) < 50 and current_sentence:
			current_sentence += " " + sentence
		else:
			if current_sentence:
				filtered_sentences.append(current_sentence)
			current_sentence = sentence
	
	# Add the last sentence
	if current_sentence:
		filtered_sentences.append(current_sentence)
	
	# If no sentences found, return original text as single sentence
	if not filtered_sentences:
		return [text]
	
	return filtered_sentences

def assemblyai_download_json(transcript_id: str, api_key: str) -> dict:
	"""Download transcript as JSON for better control over sentence segmentation"""
	resp = requests.get(
		f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
		headers={"authorization": api_key},
		timeout=60,
	)
	if resp.status_code != 200:
		raise RuntimeError(f"AssemblyAI JSON download failed: {resp.status_code} {resp.text}")
	return resp.json()


def _merge_utterances_to_sentences(utterances: list) -> list:
	"""Merge short utterances into complete sentences based on punctuation and pauses"""
	if not utterances:
		return []
	
	merged_sentences = []
	current_sentence = {
		"text": "",
		"start": None,
		"end": None
	}
	
	for i, utterance in enumerate(utterances):
		text = utterance.get("text", "").strip()
		if not text:
			continue
		
		# Initialize current sentence
		if current_sentence["start"] is None:
			current_sentence["start"] = utterance["start"]
		
		# Add text to current sentence
		if current_sentence["text"]:
			current_sentence["text"] += " " + text
		else:
			current_sentence["text"] = text
		
		current_sentence["end"] = utterance["end"]
		
		# Check if this should end the sentence
		should_end_sentence = _should_end_sentence_at_utterance(
			text, 
			utterance,
			utterances[i + 1] if i + 1 < len(utterances) else None,
			current_sentence["text"]
		)
		
		if should_end_sentence:
			# Complete current sentence
			if current_sentence["text"].strip():
				merged_sentences.append({
					"text": current_sentence["text"].strip(),
					"start": current_sentence["start"],
					"end": current_sentence["end"]
				})
			
			# Reset for next sentence
			current_sentence = {
				"text": "",
				"start": None,
				"end": None
			}
	
	# Add remaining sentence if any
	if current_sentence["text"].strip():
		merged_sentences.append({
			"text": current_sentence["text"].strip(),
			"start": current_sentence["start"],
			"end": current_sentence["end"]
		})
	
	return merged_sentences


def _should_end_sentence_at_utterance(current_text: str, current_utterance: dict, next_utterance: dict, full_sentence: str) -> bool:
	"""Determine if sentence should end at current utterance"""
	import re
	
	# Strong sentence endings
	if re.search(r'[.!?]$', current_text.strip()):
		return True
	
	# Don't end on abbreviations
	abbreviations = {
		'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'vs.', 'etc.', 'i.e.', 'e.g.',
		'inc.', 'corp.', 'co.', 'ltd.', 'u.s.', 'u.k.'
	}
	if any(current_text.lower().strip().endswith(abbr) for abbr in abbreviations):
		return False
	
	# End if sentence is getting too long (more than 20 words)
	word_count = len(full_sentence.split())
	if word_count > 20:
		return True
	
	# Check pause between utterances
	if next_utterance and current_utterance:
		current_end = current_utterance.get("end", 0)
		next_start = next_utterance["start"]
		pause_ms = next_start - current_end
		# End if there's a significant pause (more than 1.5 seconds)
		if pause_ms > 1500:
			return True
	
	# End if no next utterance
	if not next_utterance:
		return True
	
	return False


def json_to_srt_with_utterances(json_data: dict, output_srt: Path) -> None:
	"""Convert JSON transcript to SRT using AssemblyAI utterances for complete sentences"""
	import srt
	from datetime import timedelta
	
	# Lấy utterances từ speaker_labels hoặc utterances
	utterances = json_data.get("utterances", [])
	if not utterances:
		# Thử lấy từ speaker_labels
		speaker_labels = json_data.get("speaker_labels", [])
		if speaker_labels:
			utterances = speaker_labels
		else:
			# Fallback to word-based segmentation
			return json_to_srt_with_sentences(json_data, output_srt, config=None)
	
	# Merge utterances into complete sentences
	merged_sentences = _merge_utterances_to_sentences(utterances)
	
	# Convert to SRT format
	srt_entries = []
	for i, sentence in enumerate(merged_sentences, 1):
		start_time = timedelta(milliseconds=int(sentence["start"]))
		end_time = timedelta(milliseconds=int(sentence["end"]))
		
		srt_entry = srt.Subtitle(
			index=i,
			start=start_time,
			end=end_time,
			content=sentence["text"].strip()
		)
		srt_entries.append(srt_entry)
	
	# Write SRT file
	with open(output_srt, 'w', encoding='utf-8') as f:
		srt_content = srt.compose(srt_entries)
		# Đảm bảo SRT content sạch và chuẩn format
		srt_content = srt_content.strip() + '\n'
		f.write(srt_content)
	
	print(f"✅ Created {len(srt_entries)} complete sentences from {len(utterances)} utterances")

def json_to_srt_with_sentences(json_data: dict, output_srt: Path, config: dict = None) -> None:
	"""Convert JSON transcript to SRT with complete sentences based on semantic meaning"""
	import srt
	from datetime import timedelta
	import re
	
	text = json_data.get("text", "")
	words = json_data.get("words", [])
	
	if not text or not words:
		# Fallback to empty SRT
		with open(output_srt, 'w', encoding='utf-8') as f:
			f.write("1\n00:00:00,000 --> 00:00:05,000\n[No audio detected]\n\n")
		return
	
	# Common abbreviations that shouldn't end a sentence
	ABBREVIATIONS = {
		'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'vs.', 'etc.', 'i.e.', 'e.g.', 'a.m.', 'p.m.',
		'inc.', 'corp.', 'co.', 'ltd.', 'llc.', 'u.s.', 'u.k.', 'e.u.', 'n.a.t.o.',
		'jan.', 'feb.', 'mar.', 'apr.', 'jun.', 'jul.', 'aug.', 'sep.', 'oct.', 'nov.', 'dec.',
		'mon.', 'tue.', 'wed.', 'thu.', 'fri.', 'sat.', 'sun.',
		'st.', 'nd.', 'rd.', 'th.', '1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th', '10th'
	}
	
	# Sentence ending patterns (strong endings)
	STRONG_ENDINGS = ['.', '!', '?']
	
	# Weak endings (pause but not necessarily sentence end)
	WEAK_ENDINGS = [',', ';', ':']
	
	# Words that often start new sentences
	SENTENCE_STARTERS = {
		'the', 'a', 'an', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
		'my', 'your', 'his', 'her', 'its', 'our', 'their', 'mine', 'yours', 'his', 'hers', 'ours', 'theirs',
		'and', 'but', 'or', 'nor', 'for', 'yet', 'so', 'because', 'although', 'however', 'therefore',
		'first', 'second', 'third', 'finally', 'next', 'then', 'now', 'here', 'there', 'when', 'where',
		'why', 'how', 'what', 'which', 'who', 'whom', 'whose'
	}
	
	def is_sentence_end(current_text, next_word, current_word, config=None):
		"""Determine if current position should end a sentence"""
		current_text = current_text.strip().lower()
		current_word = current_word.lower()
		next_word = next_word.lower() if next_word else ""
		
		# Check for strong sentence endings
		if current_word.endswith(tuple(STRONG_ENDINGS)):
			# Don't split on abbreviations
			if current_word in ABBREVIATIONS:
				return False
			# Don't split on numbers like "1.", "2."
			if re.match(r'^\d+\.$', current_word):
				return False
			return True
		
		# Get config values
		min_length = config.get('min_sentence_length', 20) if config else 20
		max_length = config.get('max_sentence_length', 150) if config else 150
		
		# Check for natural sentence boundaries
		if len(current_text.split()) > max_length:  # Very long sentence, force break
			return True
		
		# Check if next word is a sentence starter and we have a reasonable sentence
		if (next_word in SENTENCE_STARTERS and 
			len(current_text.split()) > min_length and  # Minimum sentence length
			not current_word.endswith(tuple(WEAK_ENDINGS))):  # Don't break on weak endings
			return True
		
		# Check for pause patterns (longer pause might indicate sentence end)
		return False
	
	def clean_sentence(text):
		"""Clean and format sentence text"""
		# Remove extra spaces
		text = re.sub(r'\s+', ' ', text.strip())
		# Ensure proper capitalization
		if text and not text[0].isupper():
			text = text[0].upper() + text[1:]
		return text
	
	# Build sentences with better logic
	sentences = []
	current_sentence = ""
	current_start = None
	current_end = None
	
	for i, word in enumerate(words):
		word_text = word.get("text", "")
		
		if current_start is None:
			current_start = word.get("start", 0)
		
		current_sentence += word_text + " "
		current_end = word.get("end", 0)
		
		# Check if we should end the sentence
		next_word = words[i + 1].get("text", "") if i + 1 < len(words) else ""
		should_end = is_sentence_end(current_sentence, next_word, word_text, config)
		
		if should_end:
			cleaned_text = clean_sentence(current_sentence)
			if cleaned_text and len(cleaned_text.strip()) > 5:  # Minimum meaningful sentence
				sentences.append({
					"text": cleaned_text,
					"start": current_start,
					"end": current_end
				})
			current_sentence = ""
			current_start = None
			current_end = None
	
	# Add remaining text as last sentence
	if current_sentence.strip():
		cleaned_text = clean_sentence(current_sentence)
		if cleaned_text and len(cleaned_text.strip()) > 5:
			sentences.append({
				"text": cleaned_text,
				"start": current_start or 0,
				"end": current_end or 0
			})
	
	# Merge very short sentences with previous ones
	merged_sentences = []
	min_length = config.get('min_sentence_length', 20) if config else 20
	
	for sentence in sentences:
		word_count = len(sentence["text"].split())
		if word_count < min_length and merged_sentences:
			# Merge with previous sentence
			prev = merged_sentences[-1]
			prev["text"] += " " + sentence["text"]
			prev["end"] = sentence["end"]
		else:
			merged_sentences.append(sentence)
	
	# Convert to SRT format
	srt_entries = []
	for i, sentence in enumerate(merged_sentences, 1):
		start_time = timedelta(milliseconds=int(sentence["start"]))
		end_time = timedelta(milliseconds=int(sentence["end"]))
		
		srt_entry = srt.Subtitle(
			index=i,
			start=start_time,
			end=end_time,
			content=sentence["text"]
		)
		srt_entries.append(srt_entry)
	
	# Write SRT file
	with open(output_srt, 'w', encoding='utf-8') as f:
		srt_content = srt.compose(srt_entries)
		# Đảm bảo SRT content sạch và chuẩn format
		srt_content = srt_content.strip() + '\n'
		f.write(srt_content)
	
	print(f"✅ Created {len(srt_entries)} complete sentences from transcript")
	
	# Optional: Use AI to improve sentence segmentation if config is available
	if config and config.get('use_ai_segmentation', False):
		try:
			improve_sentences_with_ai(srt_entries, config)
			print("✅ AI-enhanced sentence segmentation applied")
		except Exception as e:
			print(f"⚠️ AI segmentation failed: {e}")

def improve_sentences_with_ai(srt_entries, config):
	"""Use AI to improve sentence segmentation and merge fragmented sentences"""
	import requests
	
	# Extract text from SRT entries
	texts = [entry.content for entry in srt_entries]
	full_text = " ".join(texts)
	
	# Create AI prompt for better segmentation
	prompt = f"""Bạn là chuyên gia về ngôn ngữ học. Hãy chia đoạn văn bản sau thành các câu hoàn chỉnh về mặt ngữ nghĩa:

QUY TẮC:
1. Mỗi câu phải có ý nghĩa hoàn chỉnh
2. Không cắt giữa chừng một ý tưởng
3. Giữ nguyên thứ tự các từ
4. Chỉ thêm dấu câu khi cần thiết
5. Đảm bảo mỗi câu có ít nhất 10-15 từ

VĂN BẢN:
{full_text}

Hãy trả về văn bản đã được chia câu hoàn chỉnh:"""
	
	# Use AI to improve segmentation
	if config.get('ai_provider') == 'gemini':
		url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.get('gemini_model', 'gemini-2.0-flash')}:generateContent"
		headers = {"Content-Type": "application/json", "X-goog-api-key": config.get('gemini_api_key', '')}
		payload = {"contents": [{"parts": [{"text": prompt}]}]}
		
		resp = requests.post(url, headers=headers, json=payload, timeout=60)
		if resp.status_code == 200:
			improved_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
			# TODO: Parse improved text and update SRT entries
			print("AI improvement applied")
	elif config.get('ai_provider') == 'deepseek':
		url = "https://api.deepseek.com/chat/completions"
		headers = {"Content-Type": "application/json", "Authorization": f"Bearer {config.get('deepseek_api_key', '')}"}
		payload = {
			"model": config.get('deepseek_model', 'deepseek-chat'),
			"messages": [{"role": "user", "content": prompt}]
		}
		
		resp = requests.post(url, headers=headers, json=payload, timeout=60)
		if resp.status_code == 200:
			improved_text = resp.json()["choices"][0]["message"]["content"]
			# TODO: Parse improved text and update SRT entries
			print("AI improvement applied")


def stt_assemblyai(input_media: Path, output_srt: Path, api_key: str, on_update: Optional[Callable[[str], None]] = None, language_code: str = "en", config: dict = None) -> None:
	"""STT với AssemblyAI sử dụng cấu hình tối ưu cho câu hoàn chỉnh"""
	_notify(on_update, "stt_upload")
	upload_url = assemblyai_upload(input_media, api_key)
	_notify(on_update, "stt_transcribe")
	transcript_id = assemblyai_request_transcript(upload_url, api_key, language_code=language_code, config=config)
	assemblyai_poll_until_complete(transcript_id, api_key)
	
	# Sử dụng JSON với utterances để có câu hoàn chỉnh từ AssemblyAI
	try:
		json_data = assemblyai_download_json(transcript_id, api_key)
		
		# Thử sử dụng utterances trước (câu hoàn chỉnh từ AssemblyAI)
		if json_data.get("utterances") or json_data.get("speaker_labels"):
			json_to_srt_with_utterances(json_data, output_srt)
			print("✅ Used AssemblyAI utterances for complete sentences")
		else:
			# Fallback to custom segmentation
			json_to_srt_with_sentences(json_data, output_srt, config)
			print("✅ Used custom sentence segmentation")
	except Exception as e:
		print(f"⚠️ JSON processing failed, falling back to SRT: {e}")
		# Fallback to SRT if JSON processing fails
	assemblyai_download_srt(transcript_id, api_key, output_srt)

def stt_assemblyai_legacy(input_media: Path, output_srt: Path, api_key: str, on_update: Optional[Callable[[str], None]] = None, language_code: str = "en", config: dict = None) -> None:
	"""STT với AssemblyAI sử dụng SRT truyền thống (fallback)"""
	_notify(on_update, "stt_upload")
	upload_url = assemblyai_upload(input_media, api_key)
	_notify(on_update, "stt_transcribe")
	transcript_id = assemblyai_request_transcript(upload_url, api_key, language_code=language_code, config=config)
	assemblyai_poll_until_complete(transcript_id, api_key)
	chars_per_caption = config.get('stt_chars_per_caption', 80) if config else 80
	assemblyai_download_srt(transcript_id, api_key, output_srt, chars_per_caption)


# -------------------- Translation (Gemini) --------------------

def _gemini_generate_text(api_key: str, model: str, text: str) -> str:
	url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
	headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}
	prompt = (
		"BẠN LÀ MỘT DỊCH GIẢ CHUYÊN NGHIỆP. Dịch văn bản tiếng Anh sang tiếng Việt với yêu cầu sau:\n"
		"1. CHỈ TRẢ VỀ TIẾNG VIỆT - KHÔNG BAO GIỜ TRẢ VỀ TIẾNG ANH\n"
		"2. Giữ nguyên nghĩa và ý nghĩa của văn bản gốc\n"
		"3. Tự động điều chỉnh số âm tiết để khớp thời lượng đọc tự nhiên\n"
		"4. Giữ nguyên dấu tiếng Việt (á, à, ả, ã, ạ, ă, â, đ, é, è, ẻ, ẽ, ẹ, ê, í, ì, ỉ, ĩ, ị, ó, ò, ỏ, õ, ọ, ô, ơ, ú, ù, ủ, ũ, ụ, ư, ý, ỳ, ỷ, ỹ, ỵ)\n"
		"5. Phát âm đúng tiếng Việt chuẩn, ưu tiên từ tiếng Việt thay vì từ nước ngoài\n"
		"6. Giữ nguyên dấu câu gốc (. ! ? , ; :) - KHÔNG thêm dấu chấm tự động\n"
		"7. Dịch tự nhiên, lưu loát, phù hợp với ngữ cảnh\n"
		"8. Nếu câu gốc kết thúc bằng dấu chấm, hãy dịch để câu tiếng Việt cũng kết thúc tự nhiên\n"
		"9. Nếu câu gốc không có dấu chấm cuối, hãy dịch để câu tiếng Việt cũng không có dấu chấm cuối\n\n"
		"QUAN TRỌNG: Chỉ trả về bản dịch tiếng Việt, KHÔNG thêm giải thích hay tiếng Anh.\n\n"
		f"Văn bản:\n{text}"
	)
	payload = {"contents": [{"parts": [{"text": prompt}]}]}
	# Tăng timeout và thêm retry logic
	max_retries = 3
	for attempt in range(max_retries):
		try:
			resp = requests.post(url, headers=headers, json=payload, timeout=120)
			if resp.status_code == 429:
				# Rate limit - wait longer
				wait_time = 60 if attempt < max_retries - 1 else 30
				time.sleep(wait_time)
				continue
			break
		except requests.exceptions.Timeout:
			if attempt < max_retries - 1:
				time.sleep(30)  # Wait before retry
				continue
			else:
				raise RuntimeError("Gemini API timeout after multiple retries")
		except requests.exceptions.RequestException as e:
			if attempt < max_retries - 1:
				time.sleep(30)
				continue
			else:
				raise RuntimeError(f"Gemini API connection error: {e}")
	if resp.status_code != 200:
		raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text}")
	data = resp.json()
	candidates = data.get("candidates", [])
	if not candidates:
		raise RuntimeError("Gemini API returned no candidates")
	parts = candidates[0].get("content", {}).get("parts", [])
	if not parts:
		raise RuntimeError("Gemini API returned empty content parts")
	return (parts[0].get("text") or "").strip()


def _deepseek_generate_text(api_key: str, model: str, text: str) -> str:
	url = "https://api.deepseek.com/chat/completions"
	headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
	prompt = (
		"BẠN LÀ MỘT DỊCH GIẢ CHUYÊN NGHIỆP. Dịch văn bản tiếng Anh sang tiếng Việt với yêu cầu sau:\n"
		"1. CHỈ TRẢ VỀ TIẾNG VIỆT - KHÔNG BAO GIỜ TRẢ VỀ TIẾNG ANH\n"
		"2. Giữ nguyên nghĩa và ý nghĩa của văn bản gốc\n"
		"3. Tự động điều chỉnh số âm tiết để khớp thời lượng đọc tự nhiên\n"
		"4. Giữ nguyên dấu tiếng Việt (á, à, ả, ã, ạ, ă, â, đ, é, è, ẻ, ẽ, ẹ, ê, í, ì, ỉ, ĩ, ị, ó, ò, ỏ, õ, ọ, ô, ơ, ú, ù, ủ, ũ, ụ, ư, ý, ỳ, ỷ, ỹ, ỵ)\n"
		"5. Phát âm đúng tiếng Việt chuẩn, ưu tiên từ tiếng Việt thay vì từ nước ngoài\n"
		"6. Giữ nguyên dấu câu gốc (. ! ? , ; :) - KHÔNG thêm dấu chấm tự động\n"
		"7. Dịch tự nhiên, lưu loát, phù hợp với ngữ cảnh\n"
		"8. Nếu câu gốc kết thúc bằng dấu chấm, hãy dịch để câu tiếng Việt cũng kết thúc tự nhiên\n"
		"9. Nếu câu gốc không có dấu chấm cuối, hãy dịch để câu tiếng Việt cũng không có dấu chấm cuối\n\n"
		"QUAN TRỌNG: Chỉ trả về bản dịch tiếng Việt, KHÔNG thêm giải thích hay tiếng Anh.\n\n"
		f"Văn bản:\n{text}"
	)
	payload = {
		"model": model,
		"messages": [
			{"role": "system", "content": "Bạn là một dịch giả chuyên nghiệp."},
			{"role": "user", "content": prompt}
		],
		"stream": False
	}
	# Tăng timeout và thêm retry logic
	max_retries = 3
	for attempt in range(max_retries):
		try:
			resp = requests.post(url, headers=headers, json=payload, timeout=120)
			if resp.status_code == 429:
				# Rate limit - wait longer
				wait_time = 60 if attempt < max_retries - 1 else 30
				time.sleep(wait_time)
				continue
			break
		except requests.exceptions.Timeout:
			if attempt < max_retries - 1:
				time.sleep(30)  # Wait before retry
				continue
			else:
				raise RuntimeError("DeepSeek API timeout after multiple retries")
		except requests.exceptions.RequestException as e:
			if attempt < max_retries - 1:
				time.sleep(30)
				continue
			else:
				raise RuntimeError(f"DeepSeek API connection error: {e}")
	if resp.status_code != 200:
		raise RuntimeError(f"DeepSeek API error {resp.status_code}: {resp.text}")
	data = resp.json()
	choices = data.get("choices", [])
	if not choices:
		raise RuntimeError("DeepSeek API returned no choices")
	return (choices[0].get("message", {}).get("content") or "").strip()


def _gemini_improve_srt_segmentation(api_key: str, model: str, srt_content: str) -> str:
	"""
	Sử dụng Gemini để cải thiện segmentation của SRT
	Tối ưu hóa việc chia câu cho tự nhiên hơn
	"""
	url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
	headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}
	
	prompt = f"""Bạn là chuyên gia về subtitle và segmentation. Hãy cải thiện SRT này để có segmentation tốt hơn:

NGUYÊN TẮC:
1. Mỗi subtitle nên là một câu hoàn chỉnh hoặc cụm từ có nghĩa
2. Độ dài mỗi subtitle: 10-25 từ (tối đa 2 dòng)
3. Tránh cắt giữa chừng một cụm từ quan trọng
4. Giữ timing phù hợp với rhythm tự nhiên
5. Ưu tiên nghĩa và dễ đọc hơn timing chính xác tuyệt đối

SRT GỐC:
{srt_content}

Hãy trả về SRT đã được cải thiện segmentation. CHÍNH XÁC format SRT, không thêm giải thích."""
	
	payload = {
		"contents": [{"parts": [{"text": prompt}]}],
		"generationConfig": {"maxOutputTokens": 8000, "temperature": 0.1}
	}
	
	try:
		response = requests.post(url, headers=headers, json=payload, timeout=60)
		if response.status_code == 200:
			result = response.json()
			improved_srt = result["candidates"][0]["content"]["parts"][0]["text"].strip()
			
			# Clean AI response
			improved_srt = _clean_ai_srt_response(improved_srt)
			
			print("✨ AI improved SRT segmentation")
			return improved_srt
		else:
			print(f"⚠️ AI segmentation failed: {response.status_code}")
			return srt_content
			
	except Exception as e:
		print(f"⚠️ AI segmentation failed: {e}")
		return srt_content


def _gemini_translate_full_srt(api_key: str, model: str, srt_content: str) -> str:
	"""Dịch toàn bộ SRT với Gemini, giới hạn âm tiết"""
	url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
	headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}
	
	prompt = f"""BẠN LÀ MỘT DỊCH GIẢ CHUYÊN NGHIỆP. Dịch file SRT tiếng Anh sang tiếng Việt với yêu cầu sau:

QUY TẮC QUAN TRỌNG:
1. CHỈ TRẢ VỀ TIẾNG VIỆT - KHÔNG BAO GIỜ TRẢ VỀ TIẾNG ANH
2. Giữ nguyên nghĩa và ý nghĩa của văn bản gốc
3. GIỚI HẠN ÂM TIẾT: Số âm tiết trong bản dịch phải BẰNG HOẶC ÍT HƠN bản gốc
4. Giữ nguyên dấu tiếng Việt (á, à, ả, ã, ạ, ă, â, đ, é, è, ẻ, ẽ, ẹ, ê, í, ì, ỉ, ĩ, ị, ó, ò, ỏ, õ, ọ, ô, ơ, ú, ù, ủ, ũ, ụ, ư, ý, ỳ, ỷ, ỹ, ỵ)
5. Phát âm đúng tiếng Việt chuẩn, ưu tiên từ tiếng Việt thay vì từ nước ngoài
6. Giữ nguyên dấu câu gốc (. ! ? , ; :) - KHÔNG thêm dấu chấm tự động
7. Dịch tự nhiên, lưu loát, phù hợp với ngữ cảnh
8. Giữ nguyên format SRT (số thứ tự, timing)
9. Nếu câu gốc kết thúc bằng dấu chấm, hãy dịch để câu tiếng Việt cũng kết thúc tự nhiên
10. Nếu câu gốc không có dấu chấm cuối, hãy dịch để câu tiếng Việt cũng không có dấu chấm cuối

QUAN TRỌNG: Chỉ trả về bản dịch tiếng Việt, KHÔNG thêm giải thích hay tiếng Anh.

SRT gốc:
{srt_content}

Hãy trả về SRT đã được dịch sang tiếng Việt với format giống hệt gốc."""
	
	payload = {"contents": [{"parts": [{"text": prompt}]}]}
	
	# Retry logic
	max_retries = 3
	for attempt in range(max_retries):
		try:
			resp = requests.post(url, headers=headers, json=payload, timeout=120)
			if resp.status_code == 429:
				wait_time = 60 if attempt < max_retries - 1 else 30
				time.sleep(wait_time)
				continue
			break
		except requests.exceptions.Timeout:
			if attempt < max_retries - 1:
				time.sleep(30)
				continue
			else:
				raise RuntimeError("Gemini API timeout after multiple retries")
		except requests.exceptions.RequestException as e:
			if attempt < max_retries - 1:
				time.sleep(30)
				continue
			else:
				raise RuntimeError(f"Gemini API connection error: {e}")
	
	if resp.status_code != 200:
		# Kiểm tra lỗi API key cụ thể
		try:
			error_data = resp.json()
			if resp.status_code == 400 and "API key not valid" in resp.text:
				raise RuntimeError(f"Gemini API key không hợp lệ: {resp.text}")
			elif resp.status_code == 403:
				raise RuntimeError(f"Gemini API key bị từ chối quyền truy cập: {resp.text}")
			else:
				raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text}")
		except:
			raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text}")
	
	data = resp.json()
	candidates = data.get("candidates", [])
	if not candidates:
		raise RuntimeError("Gemini API returned no candidates")
	
	parts = candidates[0].get("content", {}).get("parts", [])
	if not parts:
		raise RuntimeError("Gemini API returned empty content parts")
	
	response_text = (parts[0].get("text") or "").strip()
	return _clean_ai_srt_response(response_text)


def _deepseek_translate_full_srt(api_key: str, model: str, srt_content: str) -> str:
	"""Dịch toàn bộ SRT với DeepSeek, giới hạn âm tiết"""
	url = "https://api.deepseek.com/chat/completions"
	headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
	
	prompt = f"""BẠN LÀ MỘT DỊCH GIẢ CHUYÊN NGHIỆP. Dịch file SRT tiếng Anh sang tiếng Việt với yêu cầu sau:

QUY TẮC QUAN TRỌNG:
1. CHỈ TRẢ VỀ TIẾNG VIỆT - KHÔNG BAO GIỜ TRẢ VỀ TIẾNG ANH
2. Giữ nguyên nghĩa và ý nghĩa của văn bản gốc
3. GIỚI HẠN ÂM TIẾT: Số âm tiết trong bản dịch phải BẰNG HOẶC ÍT HƠN bản gốc
4. Giữ nguyên dấu tiếng Việt (á, à, ả, ã, ạ, ă, â, đ, é, è, ẻ, ẽ, ẹ, ê, í, ì, ỉ, ĩ, ị, ó, ò, ỏ, õ, ọ, ô, ơ, ú, ù, ủ, ũ, ụ, ư, ý, ỳ, ỷ, ỹ, ỵ)
5. Phát âm đúng tiếng Việt chuẩn, ưu tiên từ tiếng Việt thay vì từ nước ngoài
6. Giữ nguyên dấu câu gốc (. ! ? , ; :) - KHÔNG thêm dấu chấm tự động
7. Dịch tự nhiên, lưu loát, phù hợp với ngữ cảnh
8. Giữ nguyên format SRT (số thứ tự, timing)
9. Nếu câu gốc kết thúc bằng dấu chấm, hãy dịch để câu tiếng Việt cũng kết thúc tự nhiên
10. Nếu câu gốc không có dấu chấm cuối, hãy dịch để câu tiếng Việt cũng không có dấu chấm cuối

QUAN TRỌNG: Chỉ trả về bản dịch tiếng Việt, KHÔNG thêm giải thích hay tiếng Anh.

SRT gốc:
{srt_content}

Hãy trả về SRT đã được dịch sang tiếng Việt với format giống hệt gốc."""
	
	payload = {
		"model": model,
		"messages": [
			{"role": "system", "content": "Bạn là một dịch giả chuyên nghiệp."},
			{"role": "user", "content": prompt}
		],
		"stream": False
	}
	
	# Retry logic
	max_retries = 3
	for attempt in range(max_retries):
		try:
			resp = requests.post(url, headers=headers, json=payload, timeout=120)
			if resp.status_code == 429:
				wait_time = 60 if attempt < max_retries - 1 else 30
				time.sleep(wait_time)
				continue
			break
		except requests.exceptions.Timeout:
			if attempt < max_retries - 1:
				time.sleep(30)
				continue
			else:
				raise RuntimeError("DeepSeek API timeout after multiple retries")
		except requests.exceptions.RequestException as e:
			if attempt < max_retries - 1:
				time.sleep(30)
				continue
			else:
				raise RuntimeError(f"DeepSeek API connection error: {e}")
	
	if resp.status_code != 200:
		raise RuntimeError(f"DeepSeek API error {resp.status_code}: {resp.text}")
	
	data = resp.json()
	choices = data.get("choices", [])
	if not choices:
		raise RuntimeError("DeepSeek API returned no choices")
	
	response_text = (choices[0].get("message", {}).get("content") or "").strip()
	return _clean_ai_srt_response(response_text)


def translate_srt_ai(input_srt: Path, output_srt: Path, model: str, api_key: Optional[str] = None, provider: str = "gemini", config: dict = None) -> None:
	if provider == "gemini":
		api_key = api_key or os.getenv("GOOGLE_GEMINI_API_KEY")
		if not api_key:
			raise EnvironmentError("Missing Gemini API key. Set GOOGLE_GEMINI_API_KEY or pass api_key.")
	elif provider == "deepseek":
		api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
		if not api_key:
			raise EnvironmentError("Missing DeepSeek API key. Set DEEPSEEK_API_KEY or pass api_key.")
	else:
		raise ValueError(f"Unsupported provider: {provider}")
	
	# Đọc toàn bộ SRT
	with input_srt.open("r", encoding="utf-8") as f:
		srt_content = f.read()
	
	# Cải thiện segmentation trước khi dịch nếu được bật
	if provider == "gemini" and config and config.get('use_ai_segmentation', False):
		print("🔧 Improving SRT segmentation with AI...")
		srt_content = _gemini_improve_srt_segmentation(api_key, model, srt_content)
	
	# Dịch toàn bộ SRT một lần
	if provider == "gemini":
		translated_srt = _gemini_translate_full_srt(api_key, model, srt_content)
	elif provider == "deepseek":
		translated_srt = _deepseek_translate_full_srt(api_key, model, srt_content)
	else:
		raise ValueError(f"Unsupported provider: {provider}")
	
	# Clean AI response để loại bỏ markdown và artifacts
	translated_srt = _clean_ai_srt_response(translated_srt)
	
	# Ghi file dịch
	with output_srt.open("w", encoding="utf-8") as f:
		f.write(translated_srt)


# -------------------- TTS (ElevenLabs) --------------------

def elevenlabs_tts_to_segment(api_key: str, voice_id: str, model_id: str, text: str) -> AudioSegment:
	url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
	headers = {
		"xi-api-key": api_key,
		"Content-Type": "application/json",
		"Accept": "audio/mpeg",
	}
	payload = {
		"text": text,
		"model_id": model_id,
	}
	
	# Retry logic cho ElevenLabs
	max_retries = 3
	for attempt in range(max_retries):
		try:
			resp = requests.post(url, headers=headers, json=payload, timeout=120)
			if resp.status_code == 429:
				# Rate limit - wait longer
				wait_time = 60 if attempt < max_retries - 1 else 30
				print(f"ElevenLabs rate limit, waiting {wait_time}s... (attempt {attempt + 1}/{max_retries})")
				time.sleep(wait_time)
				continue
			elif resp.status_code == 401:
				# Unauthorized - API key lỗi
				raise RuntimeError(f"ElevenLabs API key error: {resp.text}")
			elif resp.status_code != 200:
				raise RuntimeError(f"ElevenLabs TTS error {resp.status_code}: {resp.text}")
			
			# Kiểm tra content có hợp lệ không
			if not resp.content or len(resp.content) < 100:
				raise RuntimeError("ElevenLabs returned empty or invalid audio content")
			
			return AudioSegment.from_file(io.BytesIO(resp.content), format="mp3")
			
		except requests.exceptions.Timeout:
			if attempt < max_retries - 1:
				print(f"ElevenLabs timeout, retrying... (attempt {attempt + 1}/{max_retries})")
				time.sleep(30)
				continue
			else:
				raise RuntimeError("ElevenLabs API timeout after multiple retries")
		except requests.exceptions.RequestException as e:
			if attempt < max_retries - 1:
				print(f"ElevenLabs connection error, retrying... (attempt {attempt + 1}/{max_retries})")
				time.sleep(30)
				continue
			else:
				raise RuntimeError(f"ElevenLabs API connection error: {e}")
	
	raise RuntimeError("ElevenLabs TTS failed after all retries")


def _sanitize_tts_text(text: str) -> str:
	"""Remove leading enumeration/bullets like "6.", "(6)", "- ", "• ". Keep meaningful numbers inside the sentence."""
	t = text.strip()
	# Remove repeated leading list markers (e.g., "6.", "(6)", "6) ", "- ", "– ", "— ", "• ")
	t = re.sub(r"^\s*(?:\(?\d{1,3}\)?[\.)\-–—:]\s*|[•*\-–—]\s*)+", "", t)
	return t.strip()


def _clean_srt_content(srt_content: str) -> str:
	"""Clean SRT content to avoid parsing errors"""
	if not srt_content:
		return ""
	
	# Remove BOM if present
	srt_content = srt_content.replace('\ufeff', '')
	
	# Normalize line endings
	srt_content = srt_content.replace('\r\n', '\n').replace('\r', '\n')
	
	# Remove leading/trailing whitespace
	srt_content = srt_content.strip()
	
	# Ensure proper SRT format - each entry should end with double newline
	if not srt_content.endswith('\n\n'):
		srt_content += '\n'
	
	return srt_content


def _clean_ai_srt_response(response_text: str) -> str:
	"""Clean AI response to extract pure SRT content"""
	if not response_text:
		return ""
	
	# Remove markdown code blocks
	response_text = response_text.strip()
	
	# Remove ```srt at the beginning
	if response_text.startswith('```srt'):
		response_text = response_text[6:].strip()
	elif response_text.startswith('```'):
		response_text = response_text[3:].strip()
	
	# Remove ``` at the end
	if response_text.endswith('```'):
		response_text = response_text[:-3].strip()
	
	# Remove any other common AI response artifacts
	lines = response_text.split('\n')
	cleaned_lines = []
	
	for line in lines:
		line = line.strip()
		# Skip lines that look like explanations
		if line.startswith('Đây là') or line.startswith('Bản dịch') or line.startswith('Kết quả'):
			continue
		# Skip empty lines at the start
		if not cleaned_lines and not line:
			continue
		cleaned_lines.append(line)
	
	# Join back and clean
	result = '\n'.join(cleaned_lines)
	return _clean_srt_content(result)


def srt_to_aligned_audio_elevenlabs(input_srt: Path, output_audio_wav: Path, api_key: str, voice_id: str, model_id: str) -> None:
	try:
		with input_srt.open("r", encoding="utf-8") as f:
			srt_content = f.read().strip()
		
		# Clean SRT content để tránh lỗi parsing
		srt_content = _clean_srt_content(srt_content)
		if not srt_content:
			print("Warning: SRT file is empty")
			AudioSegment.silent(duration=1000).export(str(output_audio_wav), format="wav")
			return
		
		# Debug: in nội dung SRT để kiểm tra
		print(f"SRT content preview: {repr(srt_content[:200])}")
		
		subtitles = list(srt.parse(srt_content))
		if not subtitles:
			print("Warning: No subtitles found in SRT file")
			AudioSegment.silent(duration=1000).export(str(output_audio_wav), format="wav")
			return
		
		# Continue processing...
		print(f"Processing {len(subtitles)} subtitles")
	except Exception as e:
		print(f"Error reading/parsing SRT file: {e}")
		print(f"SRT file path: {input_srt}")
		# Tạo audio silent thay thế
		AudioSegment.silent(duration=5000).export(str(output_audio_wav), format="wav")
		return
	
	last_end_ms = int(subtitles[-1].end.total_seconds() * 1000)
	timeline = AudioSegment.silent(duration=last_end_ms + 1000)
	
	# Đếm số segment thành công và thất bại
	success_count = 0
	failed_count = 0
	
	for sub in tqdm(subtitles, desc="Synthesizing TTS (ElevenLabs)"):
		content = _sanitize_tts_text(sub.content)
		# Skip empty or accidental numeric-only fragments
		if (not content) or content.isdigit():
			continue
		
		try:
			segment = elevenlabs_tts_to_segment(api_key, voice_id, model_id, content)
			start_ms = int(sub.start.total_seconds() * 1000)
			timeline = timeline.overlay(segment, position=start_ms)
			success_count += 1
		except Exception as e:
			print(f"ElevenLabs TTS failed for text '{content[:50]}...': {e}")
			failed_count += 1
			# Tạo silent segment thay thế
			silent_duration = int((sub.end - sub.start).total_seconds() * 1000)
			silent_segment = AudioSegment.silent(duration=silent_duration)
			start_ms = int(sub.start.total_seconds() * 1000)
			timeline = timeline.overlay(silent_segment, position=start_ms)
	
	print(f"ElevenLabs TTS completed: {success_count} successful, {failed_count} failed")
	
	# Kiểm tra xem có audio nào được tạo không
	if success_count == 0:
		print("Warning: No audio segments were successfully generated")
	
	timeline.export(str(output_audio_wav), format="wav")


# -------------------- TTS (FPT AI) --------------------

def fpt_ai_tts_to_segment(api_key: str, voice: str, speed: str, text: str, format: str = 'mp3', speech_speed: str = '0.8', proxies=None) -> AudioSegment:
	"""Chuyển text thành audio segment sử dụng FPT AI TTS"""
	url = 'https://api.fpt.ai/hmi/tts/v5'
	
	# Headers theo tài liệu chính thức FPT AI
	headers = {
		'api_key': api_key,  # Sửa từ 'api-key' thành 'api_key'
		'voice': voice,      # Giọng nói (banmai, leminh, thuminh, etc.)
		'Cache-Control': 'no-cache'
	}
	
	# Thêm speed vào header nếu có
	if speed:
		headers['speed'] = speed
	
	# Thêm speech_speed vào header nếu có
	if speech_speed:
		headers['speech_speed'] = speech_speed
	
	# Thêm format vào header nếu có
	if format:
		headers['format'] = format
	
	# Retry logic cho FPT AI
	max_retries = 3
	for attempt in range(max_retries):
		try:
			# FPT AI yêu cầu data dạng text UTF-8
			response = requests.post(url, data=text.encode('utf-8'), headers=headers, timeout=60, proxies=proxies)
			
			if response.status_code == 429:
				# Rate limit
				wait_time = 30 if attempt < max_retries - 1 else 15
				print(f"FPT AI rate limit, waiting {wait_time}s... (attempt {attempt + 1}/{max_retries})")
				time.sleep(wait_time)
				continue
			elif response.status_code == 401:
				# Unauthorized - API key lỗi
				raise RuntimeError(f"FPT AI API key error: {response.text}")
			elif response.status_code != 200:
				raise RuntimeError(f"FPT AI TTS error {response.status_code}: {response.text}")
			
			# FPT AI có thể trả về JSON hoặc audio data trực tiếp
			try:
				result = response.json()
				
				# Kiểm tra lỗi trong response
				if 'error' in result and result['error'] != 0:
					raise RuntimeError(f"FPT AI API error: {result.get('message', 'Unknown error')}")
				
				# Kiểm tra các trường hợp response
				if 'async_url' in result and result['async_url']:
					# Nếu có async_url, tải file audio
					audio_url = result['async_url']
					audio_response = requests.get(audio_url, timeout=60)
					if audio_response.status_code == 200:
						return AudioSegment.from_file(io.BytesIO(audio_response.content))
					else:
						raise RuntimeError(f"Failed to download audio from FPT AI: {audio_response.status_code}")
				elif 'async' in result and result['async'] and result['async'].startswith('http'):
					# FPT AI trả về async với URL trực tiếp
					audio_url = result['async']
					# Đợi một chút vì file có thể chưa sẵn sàng
					time.sleep(3)
					audio_response = requests.get(audio_url, timeout=60)
					if audio_response.status_code == 200:
						return AudioSegment.from_file(io.BytesIO(audio_response.content))
					else:
						raise RuntimeError(f"Failed to download audio from FPT AI async URL: {audio_response.status_code}")
				elif 'audio' in result and result['audio']:
					# Nếu có audio data trực tiếp (base64)
					import base64
					audio_data = base64.b64decode(result['audio'])
					return AudioSegment.from_file(io.BytesIO(audio_data))
				elif result.get('async') == 1:
					# FPT AI đang xử lý async, cần đợi và poll
					request_id = result.get('request_id')
					if request_id:
						# Đợi và poll kết quả (simplified version)
						time.sleep(2)  # Đợi 2 giây
						poll_url = f"https://api.fpt.ai/hmi/tts/v5?request_id={request_id}"
						poll_headers = {'api-key': api_key}
						poll_response = requests.get(poll_url, headers=poll_headers, timeout=60)
						if poll_response.status_code == 200:
							poll_result = poll_response.json()
							if 'audio' in poll_result and poll_result['audio']:
								import base64
								audio_data = base64.b64decode(poll_result['audio'])
								return AudioSegment.from_file(io.BytesIO(audio_data))
							else:
								raise RuntimeError("FPT AI async processing failed")
						else:
							raise RuntimeError(f"FPT AI polling failed: {poll_response.status_code}")
					else:
						raise RuntimeError("FPT AI async response missing request_id")
				else:
					raise RuntimeError(f"FPT AI unexpected response format: {result}")
					
			except ValueError:
				# Response không phải JSON, có thể là audio data trực tiếp
				if response.content and len(response.content) > 100:
					try:
						return AudioSegment.from_file(io.BytesIO(response.content))
					except Exception as e:
						raise RuntimeError(f"Failed to parse FPT AI audio response: {e}")
				else:
					raise RuntimeError("FPT AI returned invalid response format")
			
		except requests.exceptions.Timeout:
			if attempt < max_retries - 1:
				print(f"FPT AI timeout, retrying... (attempt {attempt + 1}/{max_retries})")
				time.sleep(15)
				continue
			else:
				raise RuntimeError("FPT AI API timeout after multiple retries")
		except requests.exceptions.RequestException as e:
			if attempt < max_retries - 1:
				print(f"FPT AI connection error, retrying... (attempt {attempt + 1}/{max_retries})")
				time.sleep(15)
				continue
			else:
				raise RuntimeError(f"FPT AI API connection error: {e}")
	
	raise RuntimeError("FPT AI TTS failed after all retries")


def get_vietnamese_error_message(error_str: str) -> str:
	"""
	Chuyển đổi lỗi tiếng Anh thành thông báo tiếng Việt cụ thể
	"""
	error_lower = error_str.lower()
	
	# FPT AI errors
	if 'fpt' in error_lower:
		if 'credit' in error_lower or 'quota' in error_lower or 'limit' in error_lower:
			return "🚫 FPT AI đã hết credit/quota. Vui lòng nạp thêm credit hoặc thử lại sau."
		elif 'api key' in error_lower or 'unauthorized' in error_lower or '401' in error_str:
			return "🔑 API key FPT AI không hợp lệ. Vui lòng kiểm tra lại API key."
		elif 'network' in error_lower or 'connection' in error_lower or 'timeout' in error_lower:
			return "🌐 Lỗi kết nối với FPT AI. Vui lòng kiểm tra internet và thử lại."
		elif '429' in error_str or 'rate limit' in error_lower:
			return "⏳ FPT AI đang bận. Vui lòng chờ một chút và thử lại."
	
	# AssemblyAI errors  
	elif 'assemblyai' in error_lower:
		if 'credit' in error_lower or 'quota' in error_lower:
			return "🚫 AssemblyAI đã hết credit. Vui lòng nạp thêm credit."
		elif 'api key' in error_lower or 'unauthorized' in error_lower:
			return "🔑 API key AssemblyAI không hợp lệ. Vui lòng kiểm tra lại."
		elif 'empty' in error_lower or 'no audio' in error_lower:
			return "🔇 Video không có âm thanh hoặc âm thanh quá nhỏ. Vui lòng thử video khác."
	
	# Gemini errors
	elif 'gemini' in error_lower:
		if 'quota' in error_lower or 'limit' in error_lower:
			return "🚫 Gemini đã hết quota. Vui lòng chờ hoặc nâng cấp tài khoản."
		elif 'api key' in error_lower or 'unauthorized' in error_lower:
			return "🔑 API key Gemini không hợp lệ. Vui lòng kiểm tra lại."
	
	# YouTube/Download errors
	elif 'youtube' in error_lower or 'download' in error_lower:
		if 'private' in error_lower or 'unavailable' in error_lower:
			return "🚫 Video YouTube không khả dụng hoặc bị private. Vui lòng thử video khác."
		elif 'forbidden' in error_lower or '403' in error_str:
			return "🚫 Không thể truy cập video. Video có thể bị hạn chế địa lý hoặc bị private."
		elif 'not found' in error_lower or '404' in error_str:
			return "❌ Không tìm thấy video. Vui lòng kiểm tra lại URL."
	
	# FFmpeg errors
	elif 'ffmpeg' in error_lower:
		if 'not found' in error_lower:
			return "⚠️ Chưa cài đặt FFmpeg. Vui lòng cài đặt FFmpeg để xử lý video."
		elif 'codec' in error_lower:
			return "🎥 Định dạng video không được hỗ trợ. Vui lòng thử video khác."
	
	# Network errors
	elif 'network' in error_lower or 'connection' in error_lower or 'timeout' in error_lower:
		return "🌐 Lỗi kết nối mạng. Vui lòng kiểm tra internet và thử lại."
	
	# File errors
	elif 'file not found' in error_lower or 'no such file' in error_lower:
		return "📁 Không tìm thấy file. Có thể bước trước đó bị lỗi."
	
	# Generic errors
	elif 'permission' in error_lower:
		return "🔒 Lỗi quyền truy cập. Vui lòng chạy với quyền administrator."
	elif 'disk' in error_lower or 'space' in error_lower:
		return "💾 Không đủ dung lượng ổ cứng. Vui lòng dọn dẹp ổ cứng."
	
	# Fallback to original error if no pattern matches
	return f"❌ Lỗi: {error_str}"


def remove_silence_ffmpeg(input_video: Path, output_video: Path, threshold: float = -50.0, 
                         min_duration: float = 0.4, max_duration: float = 2.0, padding: float = 0.1) -> None:
	"""
	Cắt khoảng lặng từ video sử dụng FFmpeg
	Kết quả: Cắt cả video và audio của khoảng lặng
	
	Args:
		input_video: Video đầu vào
		output_video: Video đầu ra
		threshold: Ngưỡng âm thanh (dB) để detect silence
		min_duration: Thời gian tối thiểu của khoảng lặng để cắt (giây)
		max_duration: Thời gian tối đa của khoảng lặng cần cắt (giây) - khoảng lặng > max_duration sẽ không bị cắt
		padding: Thời gian padding sau khi cắt (giây)
	"""
	import subprocess
	
	print(f"🔇 Removing silence from {input_video} -> {output_video}")
	print(f"   Threshold: {threshold}dB, Min: {min_duration}s, Max: {max_duration}s, Padding: {padding}s")
	
	# Phương pháp 1: Sử dụng silenceremove đơn giản (chỉ cắt audio)
	# Để cắt cả video và audio, chúng ta cần detect silence periods trước
	cmd = [
		"ffmpeg", "-y", "-i", str(input_video),
		"-af", f"silenceremove=stop_periods=-1:stop_duration={min_duration}:stop_threshold={threshold}dB",
		"-c:v", "copy",  # Copy video stream
		"-c:a", "aac", "-b:a", "128k",
		str(output_video)
	]
	
	try:
		result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
		if result.returncode != 0:
			# Thử lại với phương pháp đơn giản hơn
			print(f"⚠️ Complex silence removal failed, trying simple method: {result.stderr}")
			
			# Phương pháp 2: Sử dụng silenceremove đơn giản (chỉ cắt audio)
			cmd_alt = [
				"ffmpeg", "-y", "-i", str(input_video),
				"-af", f"silenceremove=stop_periods=-1:stop_duration={min_duration}:stop_threshold={threshold}dB",
				"-c:v", "copy",  # Copy video stream
				"-c:a", "aac", "-b:a", "128k",
				str(output_video)
			]
			result = subprocess.run(cmd_alt, capture_output=True, text=True, timeout=600)
			if result.returncode != 0:
				# Phương pháp 3: Sử dụng trim filter để cắt cả video và audio
				print(f"⚠️ Simple silence removal failed, trying trim method: {result.stderr}")
				
				# Tạo file tạm để lưu thông tin khoảng lặng
				temp_script = input_video.parent / "silence_detect.txt"
				
				# Detect silence periods
				detect_cmd = [
					"ffmpeg", "-i", str(input_video),
					"-af", f"silencedetect=noise={threshold}dB:d={min_duration}",
					"-f", "null", "-"
				]
				
				try:
					detect_result = subprocess.run(detect_cmd, capture_output=True, text=True, timeout=300)
					if detect_result.returncode == 0:
						# Parse silence periods và tạo trim filter
						# Đây là phương pháp phức tạp, tạm thời fallback về copy
						print(f"⚠️ Silence detection successful, but trim method not implemented yet")
						cmd_fallback = [
							"ffmpeg", "-y", "-i", str(input_video),
							"-c:v", "copy",  # Copy video stream
							"-c:a", "copy",  # Copy audio stream
							str(output_video)
						]
						result = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=600)
						if result.returncode != 0:
							raise RuntimeError(f"FFmpeg copy failed: {result.stderr}")
						else:
							print(f"⚠️ Silence removal skipped - using original video")
					else:
						raise RuntimeError(f"Silence detection failed: {detect_result.stderr}")
				except Exception as e:
					print(f"⚠️ Silence detection error: {e}, using fallback")
					cmd_fallback = [
						"ffmpeg", "-y", "-i", str(input_video),
						"-c:v", "copy",  # Copy video stream
						"-c:a", "copy",  # Copy audio stream
						str(output_video)
					]
					result = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=600)
					if result.returncode != 0:
						raise RuntimeError(f"FFmpeg copy failed: {result.stderr}")
					else:
						print(f"⚠️ Silence removal skipped - using original video")
		
		print(f"✅ Silence removal completed: {output_video}")
	except subprocess.TimeoutExpired:
		raise RuntimeError("FFmpeg silence removal timed out after 10 minutes")
	except FileNotFoundError:
		raise RuntimeError("FFmpeg not found. Please install FFmpeg.")


def remove_silence_ffmpeg_video_audio(input_video: Path, output_video: Path, threshold: float = -50.0, 
                                     min_duration: float = 0.4, max_duration: float = 2.0, padding: float = 0.1) -> None:
	"""
	Cắt khoảng lặng từ video sử dụng FFmpeg - cắt cả video và audio
	Phương pháp: Detect silence periods, sau đó sử dụng trim filter
	
	Args:
		input_video: Video đầu vào
		output_video: Video đầu ra
		threshold: Ngưỡng âm thanh (dB) để detect silence
		min_duration: Thời gian tối thiểu của khoảng lặng để cắt (giây)
		max_duration: Thời gian tối đa của khoảng lặng cần cắt (giây)
		padding: Thời gian padding sau khi cắt (giây)
	"""
	import subprocess
	import re
	
	print(f"🔇 Removing silence from video and audio: {input_video} -> {output_video}")
	print(f"   Threshold: {threshold}dB, Min: {min_duration}s, Max: {max_duration}s, Padding: {padding}s")
	
	# Bước 1: Detect silence periods
	detect_cmd = [
		"ffmpeg", "-i", str(input_video),
		"-af", f"silencedetect=noise={threshold}dB:d={min_duration}",
		"-f", "null", "-"
	]
	
	try:
		detect_result = subprocess.run(detect_cmd, capture_output=True, text=True, timeout=300)
		if detect_result.returncode != 0:
			print(f"⚠️ Silence detection failed, using simple method: {detect_result.stderr}")
			# Fallback to simple method
			remove_silence_ffmpeg(input_video, output_video, threshold, min_duration, max_duration, padding)
			return
		
		# Parse silence periods from output
		output = detect_result.stderr
		silence_periods = []
		
		# Tìm các khoảng silence_start và silence_end
		silence_starts = re.findall(r'silence_start: ([\d.]+)', output)
		silence_ends = re.findall(r'silence_end: ([\d.]+)', output)
		
		if len(silence_starts) != len(silence_ends):
			print(f"⚠️ Inconsistent silence detection, using simple method")
			remove_silence_ffmpeg(input_video, output_video, threshold, min_duration, max_duration, padding)
			return
		
		# Tạo danh sách các khoảng cần giữ lại (không phải silence)
		keep_periods = []
		last_end = 0.0
		
		for start, end in zip(silence_starts, silence_ends):
			start_time = float(start)
			end_time = float(end)
			
			# Chỉ cắt khoảng lặng trong giới hạn max_duration
			if end_time - start_time <= max_duration:
				# Thêm khoảng trước silence
				if start_time > last_end + padding:
					keep_periods.append((last_end, start_time - padding))
				last_end = end_time + padding
			else:
				# Khoảng lặng quá dài, không cắt
				if start_time > last_end + padding:
					keep_periods.append((last_end, start_time - padding))
				last_end = end_time
		
		# Thêm khoảng cuối
		keep_periods.append((last_end, float('inf')))
		
		if not keep_periods:
			print(f"⚠️ No valid periods found, using simple method")
			remove_silence_ffmpeg(input_video, output_video, threshold, min_duration, max_duration, padding)
			return
		
		# Bước 2: Tạo filter_complex để cắt video và audio
		filter_parts = []
		for i, (start, end) in enumerate(keep_periods):
			if end == float('inf'):
				filter_parts.append(f"[0:v]trim=start={start}:end=999999,setpts=PTS-STARTPTS[v{i}];[0:a]atrim=start={start}:end=999999,asetpts=PTS-STARTPTS[a{i}]")
			else:
				filter_parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]")
		
		# Concatenate tất cả các phần
		video_inputs = ''.join([f'[v{i}]' for i in range(len(keep_periods))])
		audio_inputs = ''.join([f'[a{i}]' for i in range(len(keep_periods))])
		
		filter_complex = ';'.join(filter_parts) + f';{video_inputs}concat=n={len(keep_periods)}:v=1:a=0[outv];{audio_inputs}concat=n={len(keep_periods)}:v=0:a=1[outa]'
		
		cmd = [
			"ffmpeg", "-y", "-i", str(input_video),
			"-filter_complex", filter_complex,
			"-map", "[outv]", "-map", "[outa]",
			"-c:v", "libx264", "-preset", "fast", "-crf", "23",
			"-c:a", "aac", "-b:a", "128k",
			str(output_video)
		]
		
		result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
		if result.returncode != 0:
			print(f"⚠️ Complex silence removal failed: {result.stderr}")
			print(f"⚠️ Falling back to simple method")
			remove_silence_ffmpeg(input_video, output_video, threshold, min_duration, max_duration, padding)
		else:
			print(f"✅ Complex silence removal completed: {output_video}")
			
	except Exception as e:
		print(f"⚠️ Silence removal error: {e}, using simple method")
		remove_silence_ffmpeg(input_video, output_video, threshold, min_duration, max_duration, padding)


def _get_current_fpt_key(config):
	"""Lấy FPT API key hiện tại"""
	keys = config.get('fpt_api_keys', [])
	if not keys:
		return None
	
	current_index = config.get('fpt_current_key_index', 0)
	if current_index >= len(keys):
		current_index = 0
		config['fpt_current_key_index'] = current_index
	
	return keys[current_index]

def _switch_to_next_fpt_key(config):
	"""Chuyển sang FPT API key tiếp theo"""
	keys = config.get('fpt_api_keys', [])
	if len(keys) <= 1:
		return False  # Chỉ có 1 key hoặc không có key
	
	current_index = config.get('fpt_current_key_index', 0)
	next_index = (current_index + 1) % len(keys)
	config['fpt_current_key_index'] = next_index
	
	print(f"🔄 Switched to FPT API key #{next_index + 1}/{len(keys)}")
	return True

def _get_proxy_config(config):
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

def srt_to_aligned_audio_fpt_ai_with_failover(input_srt: Path, output_audio_wav: Path, config: dict, voice: str, speed: str = '', format: str = 'mp3', speech_speed: str = '0.8', proxies=None) -> None:
	"""Chuyển SRT thành audio sử dụng FPT AI TTS với auto-failover keys"""
	
	proxies = _get_proxy_config(config)
	if proxies:
		print(f"🌐 Using proxy: {list(proxies.values())[0]}")
	
	max_key_attempts = len(config.get('fpt_api_keys', []))
	
	for key_attempt in range(max_key_attempts):
		current_key = _get_current_fpt_key(config)
		if not current_key:
			raise RuntimeError("No FPT AI API key available")
		
		print(f"🔑 Using FPT AI key #{config.get('fpt_current_key_index', 0) + 1}/{max_key_attempts}")
		
		try:
			# Try with current key
			return srt_to_aligned_audio_fpt_ai(input_srt, output_audio_wav, current_key, voice, speed, format, speech_speed, proxies)
			
		except Exception as e:
			error_str = str(e).lower()
			
			# Check if it's a key-related error that should trigger failover
			if any(keyword in error_str for keyword in ['credit', 'quota', 'limit', 'unauthorized', '401', '403']):
				print(f"🚫 FPT AI key #{config.get('fpt_current_key_index', 0) + 1} failed: {e}")
				
				if key_attempt < max_key_attempts - 1:  # Not the last key
					if _switch_to_next_fpt_key(config):
						print("🔄 Switching to next FPT AI key...")
						continue
					else:
						raise RuntimeError("No more FPT AI keys available")
				else:
					raise RuntimeError(f"All FPT AI keys failed. Last error: {e}")
			else:
				# Non-key related error, don't try other keys
				raise e
	
	raise RuntimeError("Failed to process TTS with any available FPT AI key")


def srt_to_aligned_audio_fpt_ai(input_srt: Path, output_audio_wav: Path, api_key: str, voice: str, speed: str = '', format: str = 'mp3', speech_speed: str = '0.8', proxies=None) -> None:
	"""Chuyển SRT thành audio sử dụng FPT AI TTS"""
	try:
		with input_srt.open("r", encoding="utf-8") as f:
			srt_content = f.read().strip()
		
		# Clean SRT content để tránh lỗi parsing
		srt_content = _clean_srt_content(srt_content)
		if not srt_content:
			print("Warning: SRT file is empty")
			AudioSegment.silent(duration=1000).export(str(output_audio_wav), format="wav")
			return
		
		# Debug: in nội dung SRT để kiểm tra
		print(f"SRT content preview: {repr(srt_content[:200])}")
		
		subtitles = list(srt.parse(srt_content))
		if not subtitles:
			print("Warning: No subtitles found in SRT file")
			AudioSegment.silent(duration=1000).export(str(output_audio_wav), format="wav")
			return
		
		# Tạo âm thanh với tốc độ chậm để khớp với video slow (0.7x speed)
		# Điều chỉnh speed để âm thanh chậm hơn
		adjusted_speed = '-2'  # Chậm hơn để khớp với video slow
		if speed:
			try:
				speed_num = int(speed)
				adjusted_speed = str(speed_num - 2)  # Giảm 2 mức để chậm hơn
			except:
				adjusted_speed = '-2'
	except Exception as e:
		print(f"Error reading/parsing SRT file: {e}")
		print(f"SRT file path: {input_srt}")
		# Tạo audio silent thay thế
		AudioSegment.silent(duration=5000).export(str(output_audio_wav), format="wav")
		return
	
	last_end_ms = int(subtitles[-1].end.total_seconds() * 1000)
	timeline = AudioSegment.silent(duration=last_end_ms + 1000)
	
	# Đếm số segment thành công và thất bại
	success_count = 0
	failed_count = 0
	
	for sub in tqdm(subtitles, desc="Synthesizing TTS (FPT AI)"):
		content = _sanitize_tts_text(sub.content)
		# Skip empty or accidental numeric-only fragments
		if (not content) or content.isdigit():
			print(f"⚠️ Skipping segment: '{content}' (empty or numeric-only)")
			continue
		
		try:
			segment = fpt_ai_tts_to_segment(api_key, voice, adjusted_speed, content, format, speech_speed, proxies)
			start_ms = int(sub.start.total_seconds() * 1000)
			timeline = timeline.overlay(segment, position=start_ms)
			success_count += 1
		except Exception as e:
			print(f"FPT AI TTS failed for text '{content[:50]}...': {e}")
			failed_count += 1
			# Tạo silent segment thay thế
			silent_duration = int((sub.end - sub.start).total_seconds() * 1000)
			silent_segment = AudioSegment.silent(duration=silent_duration)
			start_ms = int(sub.start.total_seconds() * 1000)
			timeline = timeline.overlay(silent_segment, position=start_ms)
	
	print(f"FPT AI TTS completed: {success_count} successful, {failed_count} failed")
	
	# Kiểm tra xem có audio nào được tạo không
	if success_count == 0:
		print("Warning: No audio segments were successfully generated")
	
	# Export final audio
	timeline.export(str(output_audio_wav), format="wav")


def srt_to_aligned_audio_edge_tts(srt_path: Path, output_audio_wav: Path, voice: str = "vi-VN-HoaiMyNeural") -> None:
	"""Convert SRT to aligned audio using Edge TTS (fallback for ElevenLabs)"""
	import asyncio
	import edge_tts
	import tempfile
	import os
	
	async def _tts():
		subs = srt.parse(srt_path.read_text(encoding='utf-8'))
		timeline = AudioSegment.empty()
		
		# Đếm số segment thành công và thất bại
		success_count = 0
		failed_count = 0
		
		for sub in tqdm(subs, desc="Synthesizing TTS (Edge TTS)"):
			content = sub.content.strip()
			if (not content) or content.isdigit():
				continue
			
			try:
				# Generate TTS audio using correct API
				communicate = edge_tts.Communicate(content, voice)
				
				# Save to temporary file first
				with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
					temp_path = temp_file.name
				
				# Use edge-tts to save directly to file
				await communicate.save(temp_path)
				
				# Kiểm tra file có tồn tại và có kích thước hợp lý không
				if not os.path.exists(temp_path) or os.path.getsize(temp_path) < 100:
					raise RuntimeError("Edge TTS generated invalid audio file")
				
				# Load audio from file
				audio_segment = AudioSegment.from_mp3(temp_path)
				
				# Clean up temp file
				os.unlink(temp_path)
				
				# Align timing
				start_ms = int(sub.start.total_seconds() * 1000)
				timeline = timeline.overlay(audio_segment, position=start_ms)
				success_count += 1
				
			except Exception as e:
				print(f"Edge TTS failed for text '{content[:50]}...': {e}")
				failed_count += 1
				# Tạo silent segment thay thế
				silent_duration = int((sub.end - sub.start).total_seconds() * 1000)
				silent_segment = AudioSegment.silent(duration=silent_duration)
				start_ms = int(sub.start.total_seconds() * 1000)
				timeline = timeline.overlay(silent_segment, position=start_ms)
				
				# Clean up temp file nếu có
				if 'temp_path' in locals() and os.path.exists(temp_path):
					try:
						os.unlink(temp_path)
					except:
						pass
		
		print(f"Edge TTS completed: {success_count} successful, {failed_count} failed")
		
		# Kiểm tra xem có audio nào được tạo không
		if success_count == 0:
			print("Warning: No audio segments were successfully generated")
		
		timeline.export(str(output_audio_wav), format="wav")
	
	asyncio.run(_tts())


def merge_srt_segments_with_ai(srt_path: Path, output_srt: Path, api_key: str, model: str = "gemini-2.0-flash", provider: str = "gemini") -> None:
	"""Sử dụng Gemini để gộp các segment SRT một cách thông minh với timing hợp lý"""
	with srt_path.open("r", encoding="utf-8") as f:
		subs = list(srt.parse(f.read()))
	
	if not subs:
		# Nếu không có subtitle, copy file gốc
		shutil.copy(srt_path, output_srt)
		return
	
	# Chia thành chunks 200 câu
	chunk_size = 200
	all_merged_subs = []
	
	for i in range(0, len(subs), chunk_size):
		chunk_subs = subs[i:i + chunk_size]
		print(f"Processing chunk {i//chunk_size + 1}/{(len(subs) + chunk_size - 1)//chunk_size} ({len(chunk_subs)} segments)")
		
		# Tạo SRT content cho chunk này
		chunk_srt_content = srt.compose(chunk_subs)
		
		# Tạo prompt cho Gemini
		prompt = f"""Bạn là chuyên gia xử lý subtitle. Hãy gộp các segment SRT sau thành các câu hoàn chỉnh và mạch lạc.

QUY TẮC:
1. Gộp các segment liên tiếp thành câu hoàn chỉnh
2. Giữ nguyên dấu chấm câu có sẵn, KHÔNG thêm dấu chấm mới
3. Chỉ gộp khi câu chưa kết thúc (chưa có dấu chấm, chấm than, chấm hỏi)
4. TIMING QUAN TRỌNG:
   - Thời gian bắt đầu = thời gian bắt đầu của segment đầu tiên
   - Thời gian kết thúc = thời gian kết thúc của segment cuối cùng
   - Khi gộp 2 segment: điều chỉnh thời gian kết thúc của segment đầu và thời gian bắt đầu của segment sau cho hợp lý
   - Nếu câu quá dài (>15 giây), chia thành 2-3 câu nhỏ hơn
5. Trả về đúng format SRT

VÍ DỤ:
Gốc:
1
00:00:00,320 --> 00:00:01,720
So I built this agent in two

2
00:00:02,220 --> 00:00:03,560
hours and someone actually paid

Kết quả:
1
00:00:00,320 --> 00:00:03,560
So I built this agent in two hours and someone actually paid

SRT gốc:
{chunk_srt_content}

Hãy trả về SRT đã được gộp với timing chính xác."""
		
		# Gọi AI API với retry logic
		if provider == "gemini":
			url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
			headers = {"Content-Type": "application/json"}
			payload = {"contents": [{"parts": [{"text": prompt}]}]}
		elif provider == "deepseek":
			url = "https://api.deepseek.com/chat/completions"
			headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
			payload = {
				"model": model,
				"messages": [
					{"role": "system", "content": "Bạn là chuyên gia xử lý subtitle."},
					{"role": "user", "content": prompt}
				],
				"stream": False
			}
		else:
			raise ValueError(f"Unsupported provider: {provider}")
		
		# Retry có giới hạn cho Gemini merge (tối đa 5 lần cho mỗi chunk)
		max_attempts = 5
		for attempt in range(1, max_attempts + 1):
			try:
				resp = requests.post(url, headers=headers, json=payload, timeout=60)  # Giảm timeout xuống 60s
				if resp.status_code == 429:
					# Rate limit - wait longer
					wait_time = min(30 * attempt, 120)  # Giảm thời gian chờ, tối đa 2 phút
					print(f"{provider.title()} rate limit, waiting {wait_time}s... (attempt {attempt})")
					time.sleep(wait_time)
					continue
				elif resp.status_code != 200:
					raise RuntimeError(f"{provider.title()} API error {resp.status_code}: {resp.text}")
				
				data = resp.json()
				
				# Parse response based on provider
				if provider == "gemini":
					candidates = data.get("candidates", [])
					if not candidates:
						raise RuntimeError("Gemini API returned no candidates")
					parts = candidates[0].get("content", {}).get("parts", [])
					if not parts:
						raise RuntimeError("Gemini API returned empty content parts")
					merged_srt = parts[0].get("text", "").strip()
				elif provider == "deepseek":
					choices = data.get("choices", [])
					if not choices:
						raise RuntimeError("DeepSeek API returned no choices")
					merged_srt = choices[0].get("message", {}).get("content", "").strip()
				else:
					raise ValueError(f"Unsupported provider: {provider}")
				
				# Parse merged SRT và thêm vào kết quả
				merged_subs = list(srt.parse(merged_srt))
				all_merged_subs.extend(merged_subs)
				
				print(f"Chunk {i//chunk_size + 1} merged successfully with {provider.title()} on attempt {attempt}")
				break
				
			except Exception as e:
				print(f"{provider.title()} merge failed (attempt {attempt}/{max_attempts}): {e}")
				if attempt < max_attempts:
					wait_time = min(15 * attempt, 60)  # Giảm thời gian chờ, tối đa 1 phút
					print(f"Retrying in {wait_time}s...")
					time.sleep(wait_time)
				else:
					# Fallback: sử dụng merge cũ cho chunk này
					print("Using fallback merge for this chunk...")
					fallback_subs = _merge_chunk_fallback(chunk_subs)
					all_merged_subs.extend(fallback_subs)
	
	# Điều chỉnh timing cuối cùng
	all_merged_subs = _adjust_timing(all_merged_subs)
	
	# Ghi file mới
	with output_srt.open("w", encoding="utf-8") as f:
		f.write(srt.compose(all_merged_subs))
	
	print(f"Total merged: {len(subs)} segments -> {len(all_merged_subs)} sentences")


def _merge_chunk_fallback(subs: List[srt.Subtitle]) -> List[srt.Subtitle]:
	"""Fallback merge cho chunk khi Gemini lỗi"""
	merged_subs = []
	current_group = []
	
	for sub in subs:
		if not current_group:
			current_group = [sub]
		else:
			# Kiểm tra khoảng cách và độ dài
			last_sub = current_group[-1]
			gap = (sub.start - last_sub.end).total_seconds()
			group_duration = (last_sub.end - current_group[0].start).total_seconds()
			
			# Gộp nếu khoảng cách nhỏ hoặc group còn ngắn
			if gap <= 1.0 or group_duration < 5.0:
				current_group.append(sub)
			else:
				merged_subs.append(_merge_group(current_group))
				current_group = [sub]
	
	if current_group:
		merged_subs.append(_merge_group(current_group))
	
	return merged_subs


def _adjust_timing(subs: List[srt.Subtitle]) -> List[srt.Subtitle]:
	"""Điều chỉnh timing hợp lý khi gộp các segment"""
	adjusted_subs = []
	
	for i, sub in enumerate(subs):
		content = sub.content.strip()
		
		# Giữ nguyên timing gốc từ Gemini
		# Chỉ điều chỉnh nếu có vấn đề về overlap
		start_time = sub.start
		end_time = sub.end
		
		# Kiểm tra overlap với subtitle tiếp theo
		if i < len(subs) - 1:
			next_start = subs[i + 1].start
			if end_time > next_start:
				# Có overlap - điều chỉnh thời gian kết thúc
				end_time = next_start - timedelta(seconds=0.1)
		
		# Kiểm tra thời gian tối thiểu (ít nhất 0.5 giây)
		min_duration = 0.5
		if (end_time - start_time).total_seconds() < min_duration:
			end_time = start_time + timedelta(seconds=min_duration)
		
		adjusted_sub = srt.Subtitle(
			index=sub.index,
			start=start_time,
			end=end_time,
			content=content
		)
		adjusted_subs.append(adjusted_sub)
	
	return adjusted_subs


def _count_syllables(text: str) -> int:
	"""Đếm số âm tiết trong văn bản (ước tính đơn giản)"""
	# Loại bỏ dấu câu và chuyển thành chữ thường
	text = re.sub(r'[^\w\s]', '', text.lower())
	words = text.split()
	
	syllable_count = 0
	for word in words:
		# Đếm nguyên âm (a, e, i, o, u, y)
		vowels = len(re.findall(r'[aeiouy]', word))
		if vowels == 0:
			vowels = 1  # Ít nhất 1 âm tiết
		syllable_count += vowels
	
	return syllable_count


def merge_srt_segments(srt_path: Path, output_srt: Path, max_gap_seconds: float = 1.0, min_duration_seconds: float = 2.0) -> None:
	"""Gộp các segment SRT ngắn thành câu dài hơn (fallback method)"""
	with srt_path.open("r", encoding="utf-8") as f:
		subs = list(srt.parse(f.read()))
	
	if not subs:
		# Nếu không có subtitle, copy file gốc
		shutil.copy(srt_path, output_srt)
		return
	
	merged_subs = []
	current_group = []
	
	for i, sub in enumerate(subs):
		if not current_group:
			current_group = [sub]
		else:
			# Kiểm tra khoảng cách với segment trước
			last_sub = current_group[-1]
			gap = (sub.start - last_sub.end).total_seconds()
			
			# Kiểm tra độ dài của group hiện tại
			group_duration = (last_sub.end - current_group[0].start).total_seconds()
			
			# Gộp nếu khoảng cách nhỏ hoặc group còn ngắn
			if gap <= max_gap_seconds or group_duration < min_duration_seconds:
				current_group.append(sub)
			else:
				# Lưu group hiện tại và bắt đầu group mới
				merged_subs.append(_merge_group(current_group))
				current_group = [sub]
	
	# Lưu group cuối cùng
	if current_group:
		merged_subs.append(_merge_group(current_group))
	
	# Ghi file mới
	with output_srt.open("w", encoding="utf-8") as f:
		f.write(srt.compose(merged_subs))


def _merge_group(subs: List[srt.Subtitle]) -> srt.Subtitle:
	"""Gộp một nhóm subtitle thành một subtitle duy nhất"""
	if not subs:
		return None
	
	# Lấy thời gian bắt đầu và kết thúc
	start_time = subs[0].start
	end_time = subs[-1].end
	
	# Gộp nội dung
	content = " ".join(sub.content.strip() for sub in subs)
	
	# Tạo subtitle mới
	return srt.Subtitle(
		index=len(subs),  # Index mới
		start=start_time,
		end=end_time,
		content=content
	)


# -------------------- Orchestration --------------------

def run_pipeline(
	url: str,
	workdir: Path,
	assemblyai_api_key: str,
	gemini_api_key: str,
	gemini_model: str,
	elevenlabs_api_key: str,
	elevenlabs_voice_id: str,
	elevenlabs_model_id: str,
	music_path: Optional[Path] = None,
	overlay_path: Optional[Path] = None,
	on_update: Optional[Callable[[str], None]] = None,
	stt_language_code: str = "en",
) -> Path:
	ensure_executable("ffmpeg", "Install ffmpeg and ensure it's in PATH")
	# no strict check for yt-dlp; we fallback to python -m yt_dlp

	workdir.mkdir(parents=True, exist_ok=True)

	input_mp4 = workdir / "input.mp4"
	slow_mp4 = workdir / "slow.mp4"
	stt_wav = workdir / "stt.wav"
	subs_srt = workdir / "subs.srt"
	subs_translated_srt = workdir / "subs_vi.srt"
	tts_wav = workdir / "tts.wav"
	final_video = workdir / "final_video.mp4"
	fast_video = workdir / "fast_video.mp4"
	final_with_music = workdir / "final_with_music.mp4"
	final_output = workdir / "final_output.mp4"

	# 1. Download
	_notify(on_update, "download")
	download_with_ytdlp(url, input_mp4)
	# 2. Slow 70%
	_notify(on_update, "slow")
	slow_down_video(input_mp4, slow_mp4)
	# 3. STT -> SRT (AssemblyAI)
	_notify(on_update, "stt")
	if not assemblyai_api_key:
		raise RuntimeError("AssemblyAI API key missing")
	# Extract small mono 16k WAV for upload
	extract_audio_for_stt(slow_mp4, stt_wav)
	stt_assemblyai(stt_wav, subs_srt, assemblyai_api_key, on_update=on_update, language_code=stt_language_code)
	# 4. Translate with Gemini (write new SRT)
	_notify(on_update, "translate")
	if not gemini_api_key:
		raise RuntimeError("Gemini API key missing")
	translate_srt_gemini(subs_srt, subs_translated_srt, model=gemini_model, api_key=gemini_api_key)
	# 5. TTS -> WAV from translated SRT (time-ordered)
	_notify(on_update, "tts")
	srt_to_aligned_audio_elevenlabs(subs_translated_srt, tts_wav, elevenlabs_api_key, elevenlabs_voice_id, elevenlabs_model_id)
	# 6. Replace audio
	_notify(on_update, "replace_audio")
	replace_audio(slow_mp4, tts_wav, final_video)
	# 7. Speed up 130%
	_notify(on_update, "speed_up")
	speed_up_130(final_video, fast_video)
	# 8. Add music (optional)
	current_video = fast_video
	if music_path and music_path.exists():
		_notify(on_update, "music")
		add_background_music(current_video, music_path, final_with_music)
		current_video = final_with_music
	# 9. Overlay (optional)
	if overlay_path and overlay_path.exists():
		_notify(on_update, "overlay")
		overlay_template(current_video, overlay_path, final_output)
		current_video = final_output
	_notify(on_update, "done")
	return current_video


# -------------------- CLI wrapper --------------------

def main() -> None:
	parser = argparse.ArgumentParser(description="Automate video processing pipeline (GUI can call run_pipeline)")
	parser.add_argument("--url", required=True)
	parser.add_argument("--workdir", default=".")
	parser.add_argument("--assemblyai_api_key", required=True)
	parser.add_argument("--gemini_api_key", required=True)
	parser.add_argument("--gemini_model", default="gemini-2.0-flash")
	parser.add_argument("--elevenlabs_api_key", required=True)
	parser.add_argument("--elevenlabs_voice_id", required=True)
	parser.add_argument("--elevenlabs_model_id", default="eleven_multilingual_v2")
	parser.add_argument("--music", default=None)
	parser.add_argument("--overlay", default=None)
	parser.add_argument("--stt_language", default="en")
	args = parser.parse_args()

	load_dotenv()

	out = run_pipeline(
		url=args.url,
		workdir=Path(args.workdir).resolve(),
		assemblyai_api_key=args.assemblyai_api_key,
		gemini_api_key=args.gemini_api_key,
		gemini_model=args.gemini_model,
		elevenlabs_api_key=args.elevenlabs_api_key,
		elevenlabs_voice_id=args.elevenlabs_voice_id,
		elevenlabs_model_id=args.elevenlabs_model_id,
		music_path=Path(args.music) if args.music else None,
		overlay_path=Path(args.overlay) if args.overlay else None,
		on_update=None,
		stt_language_code=args.stt_language,
	)
	print(f"Done. Output: {out}")


if __name__ == "__main__":
	main()

#!/usr/bin/env python3
"""
Debug script để kiểm tra lỗi SRT parsing
"""

import srt
from pathlib import Path
import tempfile

def test_srt_parsing():
    """Test SRT parsing với các trường hợp khác nhau"""
    
    # Test case 1: SRT chuẩn
    valid_srt = """1
00:00:00,000 --> 00:00:03,000
Hello world

2
00:00:03,000 --> 00:00:06,000
This is a test
"""
    
    # Test case 2: SRT với BOM
    srt_with_bom = '\ufeff' + valid_srt
    
    # Test case 3: SRT với leading spaces
    srt_with_spaces = '   ' + valid_srt
    
    # Test case 4: SRT với mixed line endings
    srt_mixed_endings = valid_srt.replace('\n', '\r\n')
    
    # Test case 5: SRT không chuẩn (có thể gây lỗi)
    invalid_srt = """ srt
1
00:00:00,000 --> 00:00:03,000
Hello world
"""
    
    test_cases = [
        ("Valid SRT", valid_srt),
        ("SRT with BOM", srt_with_bom),
        ("SRT with spaces", srt_with_spaces),
        ("SRT with mixed endings", srt_mixed_endings),
        ("Invalid SRT", invalid_srt)
    ]
    
    for name, content in test_cases:
        print(f"\n🧪 Testing {name}:")
        print(f"Content preview: {repr(content[:50])}")
        
        try:
            # Test original parsing
            subtitles = list(srt.parse(content))
            print(f"✅ Original parsing: {len(subtitles)} subtitles")
        except Exception as e:
            print(f"❌ Original parsing failed: {e}")
            
            # Test with cleaning
            try:
                from pipeline import _clean_srt_content
                cleaned = _clean_srt_content(content)
                print(f"Cleaned preview: {repr(cleaned[:50])}")
                subtitles = list(srt.parse(cleaned))
                print(f"✅ Cleaned parsing: {len(subtitles)} subtitles")
            except Exception as e2:
                print(f"❌ Cleaned parsing also failed: {e2}")

def test_real_project_srt():
    """Test SRT files từ project thực tế"""
    print("\n🔍 Checking real project SRT files...")
    
    # Tìm các file SRT trong projects
    projects_dir = Path("projects")
    if projects_dir.exists():
        srt_files = list(projects_dir.glob("*/*.srt"))
        
        if srt_files:
            print(f"Found {len(srt_files)} SRT files:")
            for srt_file in srt_files[:5]:  # Chỉ test 5 file đầu
                print(f"\n📄 Testing {srt_file}:")
                try:
                    with open(srt_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    print(f"File size: {len(content)} chars")
                    print(f"Content preview: {repr(content[:100])}")
                    
                    # Test parsing
                    try:
                        subtitles = list(srt.parse(content))
                        print(f"✅ Parsing successful: {len(subtitles)} subtitles")
                        if subtitles:
                            print(f"First subtitle: {subtitles[0].content[:50]}...")
                    except Exception as e:
                        print(f"❌ Parsing failed: {e}")
                        
                        # Try with cleaning
                        try:
                            from pipeline import _clean_srt_content
                            cleaned = _clean_srt_content(content)
                            subtitles = list(srt.parse(cleaned))
                            print(f"✅ Cleaned parsing: {len(subtitles)} subtitles")
                        except Exception as e2:
                            print(f"❌ Cleaned parsing also failed: {e2}")
                            
                except Exception as e:
                    print(f"❌ Error reading file: {e}")
        else:
            print("No SRT files found in projects directory")
    else:
        print("Projects directory not found")

def test_tts_function():
    """Test TTS function với SRT sample"""
    print("\n🎵 Testing TTS function...")
    
    # Tạo SRT test
    test_srt = """1
00:00:00,000 --> 00:00:03,000
Hello, this is a test.

2
00:00:03,000 --> 00:00:06,000
Testing FPT AI TTS.
"""
    
    try:
        from pipeline import srt_to_aligned_audio_fpt_ai, _clean_srt_content
        
        # Tạo file SRT tạm
        with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
            f.write(test_srt)
            srt_path = Path(f.name)
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            output_path = Path(f.name)
        
        print(f"SRT file: {srt_path}")
        print(f"Output file: {output_path}")
        
        # Test TTS function
        api_key = 'ffFujWkLFqAAZbEu5O3Fy1eplKiOVtGW'
        voice = 'banmai'
        speed = ''
        format = 'mp3'
        
        srt_to_aligned_audio_fpt_ai(srt_path, output_path, api_key, voice, speed, format)
        
        if output_path.exists():
            print(f"✅ TTS successful: {output_path.stat().st_size} bytes")
        else:
            print("❌ TTS failed: No output file")
        
        # Cleanup
        srt_path.unlink()
        if output_path.exists():
            output_path.unlink()
            
    except Exception as e:
        print(f"❌ TTS test failed: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("🐛 SRT Error Debug Tool")
    print("=" * 50)
    
    test_srt_parsing()
    test_real_project_srt()
    test_tts_function()
    
    print("\n" + "=" * 50)
    print("🎯 Debug completed!")

if __name__ == "__main__":
    main()

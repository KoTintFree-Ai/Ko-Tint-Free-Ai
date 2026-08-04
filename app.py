import streamlit as st
import os
import base64
import time
import json
import tempfile
import urllib.request
import requests
import asyncio
import edge_tts
import subprocess
import numpy as np
from PIL import Image, ImageOps
import re
import shutil

# --- CONFIGURATION ---
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MODELS_TO_TRY = ["gemini-1.5-flash", "gemini-3.5-flash", "gemini-2.0-flash-exp", "gemini-1.5-flash-8b"]

st.set_page_config(
    page_title="Movie Recap AI Pro V5.0", 
    page_icon="🎬", 
    layout="centered",
    initial_sidebar_state="expanded"
)

# --- HIDE BRANDING ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            .stDeployButton {display:none;}
            #stDecoration {display:none;}
            [data-testid="stSidebarNav"] {display: none;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# Session State Persistence
if 'myanmar_text' not in st.session_state: st.session_state.myanmar_text = None
if 'audio_data' not in st.session_state: st.session_state.audio_data = None
if 'srt_data' not in st.session_state: st.session_state.srt_data = None
if 'video_data' not in st.session_state: st.session_state.video_data = None
if 'processing_done' not in st.session_state: st.session_state.processing_done = False
if 'base_frame' not in st.session_state: st.session_state.base_frame = None
if 'last_uploaded' not in st.session_state: st.session_state.last_uploaded = None

st.title("🎬 Movie Recap AI Pro V5.0")
st.markdown("English Video → Myanmar Movie Recap (Final Render Fix)")

# --- SIDEBAR SETTINGS ---
with st.sidebar:
    st.header("⚙️ Settings")
    st.subheader("🔑 Gemini API Keys")
    key1 = st.text_input("API Key 1", type="password")
    key2 = st.text_input("API Key 2", type="password")
    key3 = st.text_input("API Key 3", type="password")
    key4 = st.text_input("API Key 4", type="password")
    key5 = st.text_input("API Key 5", type="password")
    api_keys = [k for k in [key1, key2, key3, key4, key5] if k]
    
    st.markdown("---")
    st.subheader("🎬 Pro Editing Features")
    mirror_video = st.checkbox("Mirror Video (Reverse)", value=True)
    scale_video = st.checkbox("Scale Video (106%)", value=True)
    blur_subtitles = st.checkbox("Blur Original Subtitles", value=True)
    
    if 'blur_y_pos' not in st.session_state: st.session_state.blur_y_pos = 85.0
    if 'blur_h_size' not in st.session_state: st.session_state.blur_h_size = 10.0
    
    blur_y_pos = st.slider("Blur Y Position (%)", 0.0, 100.0, st.session_state.blur_y_pos) if blur_subtitles else 85.0
    blur_h_size = st.slider("Blur Height (%)", 0.5, 30.0, st.session_state.blur_h_size, step=0.1) if blur_subtitles else 10.0
    
    # Sync slider back to session state
    st.session_state.blur_y_pos = blur_y_pos
    st.session_state.blur_h_size = blur_h_size
    burn_myanmar_subs = st.checkbox("Burn Myanmar Subtitles", value=True)
    
    auto_detect_btn = st.button("✨ Auto Detect Subtitle Area")
    show_preview = st.checkbox("👀 Live Preview Blur Area", value=True)
    
    st.markdown("---")
    st.subheader("⏱️ Duration Control")
    enable_target = st.toggle("Enable Target Duration", value=False)
    total_target_sec = 0
    if enable_target:
        col_m, col_s = st.columns(2)
        with col_m:
            target_min = st.number_input("Min", min_value=0, max_value=60, value=1)
        with col_s:
            target_sec = st.number_input("Sec", min_value=0, max_value=59, value=30)
        total_target_sec = (target_min * 60) + target_sec
    
    st.markdown("---")
    st.subheader("🔊 Voice Settings")
    voice_choice = st.selectbox("Select Voice", ["Thiha (Male)", "Nilar (Female)"], index=0)
    voice_id = "my-MM-ThihaNeural" if "Thiha" in voice_choice else "my-MM-NilarNeural"
    speed = st.slider("Base Speed", 1, 100, 55)
    pitch = st.slider("Pitch", 1, 100, 50)
    
    if st.button("🧹 Clear All Data"):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

# --- UTILITIES ---
def is_ffmpeg_installed():
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

def get_duration(file_path):
    if not file_path or not os.path.exists(file_path): return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        return float(result.stdout.strip())
    except: return None

def extract_audio(video_path):
    audio_path = tempfile.mktemp(suffix='.mp3')
    try:
        subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "libmp3lame", "-q:a", "4", audio_path], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return audio_path
    except: return None

def format_srt_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

async def generate_audio_and_srt_v44(text, audio_path, v_id, s, p, target_duration=0):
    rate = f"+{int((s-50)*2)}%" if s>=50 else f"{int((s-50)*2)}%"
    p_hz = f"+{int((p-50)*2)}Hz" if p>=50 else f"{int((p-50)*2)}Hz"
    communicate = edge_tts.Communicate(text, v_id, rate=rate, pitch=p_hz)
    temp_audio = tempfile.mktemp(suffix='.mp3')
    word_boundaries = []
    with open(temp_audio, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio": f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_boundaries.append({"start": chunk["offset"] / 10000000, "duration": chunk["duration"] / 10000000, "text": chunk["text"]})
    
    actual_duration = get_duration(temp_audio)
    speed_multiplier = 1.0
    if target_duration > 0 and actual_duration:
        speed_multiplier = actual_duration / target_duration
        speed_multiplier = max(0.5, min(2.0, speed_multiplier))
        subprocess.run(["ffmpeg", "-y", "-i", temp_audio, "-filter:a", f"atempo={speed_multiplier}", audio_path], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        shutil.copy(temp_audio, audio_path)

    srt_lines = []
    counter = 1
    current_sentence = []
    actual_dur = get_duration(audio_path)
    if word_boundaries:
        start_time = word_boundaries[0]["start"] / speed_multiplier
        for i, wb in enumerate(word_boundaries):
            current_sentence.append(wb["text"])
            end_time = (wb["start"] + wb["duration"]) / speed_multiplier
            is_last = (i == len(word_boundaries) - 1)
            has_marker = any(m in wb["text"] for m in ["။", "!", "?", " "])
            line_too_long = len("".join(current_sentence)) > 45
            if is_last or has_marker or line_too_long:
                sentence_text = "".join(current_sentence).strip()
                if sentence_text:
                    srt_lines.append(str(counter))
                    srt_lines.append(f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}")
                    srt_lines.append(sentence_text)
                    srt_lines.append("")
                    counter += 1
                if not is_last:
                    current_sentence = []
                    start_time = word_boundaries[i+1]["start"] / speed_multiplier
    
    # Fallback: If no word boundaries or SRT lines generated, create one single block
    if not srt_lines and text and actual_dur:
        srt_lines.append("1")
        srt_lines.append(f"00:00:00,000 --> {format_srt_time(actual_dur)}")
        srt_lines.append(text[:100] + ("..." if len(text) > 100 else ""))
        srt_lines.append("")

    if os.path.exists(temp_audio): os.remove(temp_audio)
    return "\n".join(srt_lines), actual_dur

def auto_detect_subtitle_y(video_path):
    """Detects the likely Y position and height of subtitles in the video."""
    try:
        # Extract a frame at 10% of the video to avoid intros
        duration = get_duration(video_path)
        sample_time = duration * 0.1 if duration else 5
        temp_frame = tempfile.mktemp(suffix='.jpg')
        
        cmd = ["ffmpeg", "-y", "-ss", str(sample_time), "-i", video_path, "-frames:v", "1", temp_frame]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if not os.path.exists(temp_frame): return 85, 10
        
        img = Image.open(temp_frame).convert('L') # Grayscale
        width, height = img.size
        # Focus on the bottom 40% of the image
        bottom_part = img.crop((0, int(height * 0.6), width, height))
        arr = np.array(bottom_part)
        
        # Calculate row-wise variance to find text areas (text has high contrast/variance)
        row_variance = np.var(arr, axis=1)
        # Find rows where variance is above a higher threshold for tighter detection
        threshold = np.mean(row_variance) * 2.0
        text_rows = np.where(row_variance > threshold)[0]
        
        if len(text_rows) > 0:
            y_start_in_crop = text_rows[0]
            y_end_in_crop = text_rows[-1]
            
            # Convert back to full image percentage
            actual_y_start = int(height * 0.6) + y_start_in_crop
            actual_y_end = int(height * 0.6) + y_end_in_crop
            
            # Add minimal padding for a tighter fit
            padding = 5
            final_y = max(0, actual_y_start - padding)
            final_h = min(height, (actual_y_end - actual_y_start) + (padding * 2))
            
            os.remove(temp_frame)
            return (final_y / height) * 100, (final_h / height) * 100
            
        os.remove(temp_frame)
    except Exception as e:
        st.error(f"Auto Detect Error: {e}")
    return 85, 10 # Default fallback

def get_blur_filter(mirror, scale, blur, blur_y, blur_h, burn_subs=False, srt_path=None):
    v_filters = []
    if mirror: v_filters.append("hflip")
    if scale: v_filters.append("scale=1.06*iw:-1,crop=iw/1.06:ih/1.06")
    
    if blur:
        y_start = blur_y / 100.0
        h_ratio = blur_h / 100.0
        base_v = ",".join(v_filters) if v_filters else "null"
        fc = f"[0:v]{base_v},split[m][b];[b]crop=iw:ih*{h_ratio}:0:ih*{y_start},boxblur=15:5[blurred];[m][blurred]overlay=0:main_h*{y_start}"
        if burn_subs and srt_path:
            rel_srt = os.path.relpath(srt_path)
            srt_esc = rel_srt.replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")
            # Add font support for Myanmar characters
            font_dir = os.getcwd().replace("\\", "/").replace(":", "\\:")
            fc += f",subtitles='{srt_esc}':fontsdir='{font_dir}':force_style='FontName=Pyidaungsu,FontSize=12,PrimaryColour=&H00FFFF,OutlineColour=&H000000,BorderStyle=3,Alignment=2,MarginV=10'[v]"
        else:
            fc += "[v]"
    else:
        fc = "[0:v]" + ("," + ",".join(v_filters) if v_filters else "")
        if burn_subs and srt_path:
            rel_srt = os.path.relpath(srt_path)
            srt_esc = rel_srt.replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")
            # Add font support for Myanmar characters
            font_dir = os.getcwd().replace("\\", "/").replace(":", "\\:")
            fc += f",subtitles='{srt_esc}':fontsdir='{font_dir}':force_style='FontName=Pyidaungsu,FontSize=12,PrimaryColour=&H00FFFF,OutlineColour=&H000000,BorderStyle=3,Alignment=2,MarginV=10'[v]"
        else:
            fc += "[v]"
    return fc

def render_pro_video_v44(video_path, audio_path, srt_path, mirror, scale, blur, burn_subs, blur_y=85, blur_h=10):
    output_video = tempfile.mktemp(suffix='.mp4')
    try:
        # Check if SRT exists if burning is requested
        if burn_subs:
            if not os.path.exists(srt_path) or os.path.getsize(srt_path) == 0:
                st.warning("⚠️ SRT file is missing or empty. Subtitles will not be burned.")
                burn_subs = False

        fc = get_blur_filter(mirror, scale, blur, blur_y, blur_h, burn_subs, srt_path)

        cmd = [
            "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
            "-filter_complex", fc,
            "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-c:a", "aac", "-shortest", output_video
        ]
        
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return output_video
    except Exception as e:
        st.error(f"Render Error: {str(e)}")
        if hasattr(e, 'stderr'): st.code(e.stderr)
        return None

def gemini_generate_auto(contents, keys):
    for key in keys:
        for model in MODELS_TO_TRY:
            try:
                url = f"{GEMINI_BASE_URL}/{model}:generateContent?key={key}"
                payload = {"contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}}
                response = requests.post(url, json=payload, timeout=300)
                if response.status_code == 429: break
                response.raise_for_status()
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            except: continue
    raise Exception("All API keys failed.")

def translate_content(audio_path, target_sec, keys):
    duration_prompt = f"- TARGET DURATION: Approx {target_sec} seconds." if target_sec > 0 else ""
    prompt = f"Translate the English content into Myanmar Recap Style. {duration_prompt} - Dramatic tone. Write ENTIRELY in Myanmar language."
    with open(audio_path, 'rb') as f: file_data = base64.b64encode(f.read()).decode('utf-8')
    contents = [{"role": "user", "parts": [{"text": prompt}, {"inline_data": {"mime_type": "audio/mp3", "data": file_data}}]}]
    return gemini_generate_auto(contents, keys)

# --- MAIN UI ---
uploaded_file = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if uploaded_file is not None:
    # Handle new file upload
    file_id = uploaded_file.name + str(uploaded_file.size)
    if st.session_state.last_uploaded != file_id:
        st.session_state.last_uploaded = file_id
        st.session_state.base_frame = None
        # Save temporarily to extract frame
        suffix = "." + uploaded_file.name.split(".")[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tfile:
            tfile.write(uploaded_file.getvalue())
            temp_path = os.path.abspath(tfile.name)
        
        if suffix.lower() in [".mp4", ".mov", ".avi"]:
            base_img = tempfile.mktemp(suffix='.jpg')
            # Extract frame at 5s or 10%
            duration = get_duration(temp_path)
            sample_t = duration * 0.1 if duration else 5
            subprocess.run(["ffmpeg", "-y", "-ss", str(sample_t), "-i", temp_path, "-frames:v", "1", base_img], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if os.path.exists(base_img):
                with open(base_img, "rb") as f: st.session_state.base_frame = f.read()
                os.remove(base_img)
        os.remove(temp_path)

    # Temporary path for current processing
    suffix = "." + uploaded_file.name.split(".")[-1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tfile:
        tfile.write(uploaded_file.getvalue())
        temp_preview_path = os.path.abspath(tfile.name)

    if auto_detect_btn:
        with st.spinner("🔍 Detecting Subtitles..."):
            det_y, det_h = auto_detect_subtitle_y(temp_preview_path)
            st.session_state.blur_y_pos = float(det_y)
            st.session_state.blur_h_size = float(det_h)
            st.success(f"✅ Detected! Y: {det_y:.1f}%, Height: {det_h:.1f}%")
            st.rerun()

    if show_preview and st.session_state.base_frame:
        st.subheader("🖼️ Blur Area Preview (Real-time)")
        # Apply current blur settings to base_frame
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as bfile:
            bfile.write(st.session_state.base_frame)
            bpath = os.path.abspath(bfile.name)
        
        preview_out = tempfile.mktemp(suffix='.jpg')
        fc = get_blur_filter(mirror_video, scale_video, blur_subtitles, blur_y_pos, blur_h_size)
        # Simplify filter for single image (remove [0:v] and [v])
        fc_simple = fc.replace("[0:v]", "").replace("[v]", "")
        
        try:
            subprocess.run(["ffmpeg", "-y", "-i", bpath, "-vf", fc_simple, preview_out], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if os.path.exists(preview_out):
                st.image(preview_out, caption=f"Live Preview: Y={blur_y_pos:.1f}%, H={blur_h_size:.1f}%")
                os.remove(preview_out)
        except Exception as e:
            st.error(f"Preview Error: {e}")
        finally:
            if os.path.exists(bpath): os.remove(bpath)
        
    if not api_keys: st.warning("⚠️ Sidebar တွင် API Key ထည့်ပေးပါ")
    else:
        if st.button("🚀 Start Pro Processing & Render Video"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            try:
                status_text.text("📊 အဆင့် ၁: ဖိုင်ကို စစ်ဆေးနေပါသည်... (10%)")
                progress_bar.progress(10)
                suffix = "." + uploaded_file.name.split(".")[-1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tfile:
                    tfile.write(uploaded_file.read())
                    temp_path = os.path.abspath(tfile.name)
                
                audio_for_gemini = extract_audio(temp_path) if suffix.lower() in [".mp4", ".mov", ".avi"] else temp_path
                progress_bar.progress(20)
                
                status_text.text("⏳ အဆင့် ၂: ဘာသာပြန်နေပါသည်... (40%)")
                progress_bar.progress(40)
                st.session_state.myanmar_text = translate_content(audio_for_gemini, total_target_sec, api_keys)
                
                status_text.text("🔊 အဆင့် ၃: အသံဖိုင်နှင့် Subtitle ထုတ်ပေးနေပါသည်... (70%)")
                progress_bar.progress(70)
                audio_output = os.path.abspath("temp_audio.mp3")
                st.session_state.srt_data, final_dur = asyncio.run(generate_audio_and_srt_v44(st.session_state.myanmar_text, audio_output, voice_id, speed, pitch, total_target_sec))
                
                if os.path.exists(audio_output):
                    with open(audio_output, "rb") as f: st.session_state.audio_data = f.read()
                
                if suffix.lower() in [".mp4", ".mov", ".avi"]:
                    status_text.text("🎬 အဆင့် ၄: ဗီဒီယိုကို တည်းဖြတ်နေပါသည် (Rendering)... (90%)")
                    progress_bar.progress(90)
                    # Write SRT to a fixed path in current directory to avoid /tmp/ access issues
                    srt_temp_path = os.path.abspath("temp_subtitle.srt")
                    with open(srt_temp_path, "w", encoding="utf-8") as srt_f:
                        srt_f.write(st.session_state.srt_data)
                    
                    final_video_path = render_pro_video_v44(temp_path, audio_output, srt_temp_path, mirror_video, scale_video, blur_subtitles, burn_myanmar_subs, blur_y_pos, blur_h_size)
                    if final_video_path and os.path.exists(final_video_path):
                        with open(final_video_path, "rb") as f: st.session_state.video_data = f.read()
                        os.remove(final_video_path)
                    if os.path.exists(srt_temp_path): os.remove(srt_temp_path)

                progress_bar.progress(100)
                status_text.text("✅ အားလုံး ပြီးစီးပါပြီ!")
                st.session_state.processing_done = True
                st.balloons()
                
                if os.path.exists(temp_path): os.remove(temp_path)
                if audio_for_gemini != temp_path and os.path.exists(audio_for_gemini): os.remove(audio_for_gemini)
                if os.path.exists(audio_output): os.remove(audio_output)
            except Exception as e: st.error(f"❌ အမှားအယွင်း: {str(e)}")

if st.session_state.processing_done:
    st.markdown("---")
    if st.session_state.video_data:
        st.subheader("🎥 Edited Final Video")
        st.video(st.session_state.video_data)
        st.download_button("📥 Download Edited Video", st.session_state.video_data, file_name="recap_final.mp4", mime="video/mp4")
    
    st.subheader("📥 Downloads")
    col1, col2 = st.columns(2)
    with col1:
        if st.session_state.audio_data:
            st.audio(st.session_state.audio_data, format="audio/mp3")
            st.download_button("📥 Download Audio", st.session_state.audio_data, file_name="recap_audio.mp3", mime="audio/mp3")
    with col2:
        if st.session_state.srt_data:
            st.download_button("📥 Download SRT", st.session_state.srt_data, file_name="recap_subtitle.srt", mime="text/plain")

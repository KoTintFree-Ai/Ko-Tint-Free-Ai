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
    page_title="Movie Recap AI Pro V6.2", 
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

# Default values for sliders in session state
if 'blur_y_pos' not in st.session_state: st.session_state.blur_y_pos = 85.0
if 'blur_h_size' not in st.session_state: st.session_state.blur_h_size = 10.0
if 'sub_y_pos' not in st.session_state: st.session_state.sub_y_pos = 85.0
if 'font_size' not in st.session_state: st.session_state.font_size = 15

st.title("🎬 Movie Recap AI Pro V6.2")
st.markdown("English Video → Myanmar Movie Recap (Enhanced Preview)")

# --- HELPER: +/- BUTTONS ---
def plus_minus_control(label, key, min_val, max_val, step=1.0):
    st.write(f"**{label}**")
    col1, col2, col3 = st.columns([1, 3, 1])
    
    def update_val(delta):
        st.session_state[key] = float(np.clip(st.session_state[key] + delta, min_val, max_val))

    with col1:
        st.button("➖", key=f"btn_minus_{key}", on_click=update_val, args=(-step,))
    with col2:
        # Use key directly so the slider is bound to the session state variable
        st.slider(label, min_val, max_val, key=key, step=step, label_visibility="collapsed")
    with col3:
        st.button("➕", key=f"btn_plus_{key}", on_click=update_val, args=(step,))
    return st.session_state[key]

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
    
    st.markdown("---")
    blur_subtitles = st.checkbox("Blur Original Subtitles", value=True)
    if blur_subtitles:
        blur_y_pos = plus_minus_control("Blur Y Position (%)", "blur_y_pos", 0.0, 100.0, 0.5)
        blur_h_size = plus_minus_control("Blur Height (%)", "blur_h_size", 0.5, 30.0, 0.1)
    else:
        blur_y_pos, blur_h_size = 85.0, 10.0
    
    st.markdown("---")
    burn_myanmar_subs = st.checkbox("Burn Myanmar Subtitles", value=True)
    if burn_myanmar_subs:
        font_size = plus_minus_control("Myanmar Font Size", "font_size", 5, 50, 1)
        sub_y_pos = plus_minus_control("Subtitle Y Position (%)", "sub_y_pos", 0.0, 100.0, 0.5)
    else:
        font_size, sub_y_pos = 15, 85.0
    
    st.markdown("---")
    auto_detect_btn = st.button("✨ Auto Detect Subtitle Area")
    show_preview = st.checkbox("👀 Live Preview (Blur & Sub)", value=True)
    
    st.markdown("---")
    # Font Diagnostic
    if not os.path.exists("Pyidaungsu.ttf"):
        st.error("❌ Pyidaungsu.ttf missing!")
    else:
        st.success("✅ Pyidaungsu.ttf found!")
    
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
    audio_path = tempfile.mktemp(suffix=".mp3")
    try:
        subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "libmp3lame", "-q:a", "4", audio_path], check=True, capture_output=True)
        return audio_path
    except: return None

async def generate_audio_and_srt_v44(srt_text, audio_path, v_id, s, p, target_duration=0):
    rate = f"+{int((s-50)*2)}%" if s>=50 else f"{int((s-50)*2)}%"
    p_hz = f"+{int((p-50)*2)}Hz" if p>=50 else f"{int((p-50)*2)}Hz"

    srt_segments = []
    current_segment = {}
    for line in srt_text.splitlines():
        line = line.strip()
        if not line:
            if current_segment and 'text' in current_segment: srt_segments.append(current_segment)
            current_segment = {}
        elif line.isdigit(): current_segment['index'] = int(line)
        elif '-->' in line:
            start_str, end_str = line.split(' --> ')
            start_time = sum(float(x) * 60 ** i for i, x in enumerate(reversed(start_str.replace(',', '.').split(':'))))
            end_time = sum(float(x) * 60 ** i for i, x in enumerate(reversed(end_str.replace(',', '.').split(':'))))
            current_segment['start'], current_segment['end'], current_segment['duration'] = start_time, end_time, end_time - start_time
        else:
            if 'text' not in current_segment: current_segment['text'] = []
            current_segment['text'].append(line)
    if current_segment and 'text' in current_segment: srt_segments.append(current_segment)

    final_audio_parts = []
    for i, segment in enumerate(srt_segments):
        tts_text = re.sub(r'^\d+\s*', '', " ".join(segment['text'])).strip()
        segment_duration = segment['duration']
        temp_segment_audio = tempfile.mktemp(suffix=".mp3")
        communicate = edge_tts.Communicate(tts_text, v_id, rate=rate, pitch=p_hz)
        with open(temp_segment_audio, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio": f.write(chunk["data"])
        
        actual_tts_duration = get_duration(temp_segment_audio)
        if actual_tts_duration and actual_tts_duration > segment_duration:
            speed_factor = min(2.0, actual_tts_duration / segment_duration)
            sped_up_audio = tempfile.mktemp(suffix=".mp3")
            subprocess.run(["ffmpeg", "-y", "-i", temp_segment_audio, "-filter:a", f"atempo={speed_factor}", sped_up_audio], check=True, capture_output=True)
            os.remove(temp_segment_audio); temp_segment_audio = sped_up_audio
            actual_tts_duration = get_duration(temp_segment_audio)

        if actual_tts_duration and actual_tts_duration < segment_duration:
            silence_duration = segment_duration - actual_tts_duration
            silent_audio = tempfile.mktemp(suffix=".mp3")
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono", "-t", str(silence_duration), "-c:a", "libmp3lame", "-q:a", "4", silent_audio], check=True, capture_output=True)
            combined_audio = tempfile.mktemp(suffix=".mp3")
            subprocess.run(["ffmpeg", "-y", "-i", temp_segment_audio, "-i", silent_audio, "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[out]", "-map", "[out]", combined_audio], check=True, capture_output=True)
            os.remove(temp_segment_audio); os.remove(silent_audio); temp_segment_audio = combined_audio
        final_audio_parts.append(temp_segment_audio)

    if final_audio_parts:
        concat_list_path = tempfile.mktemp(suffix=".txt")
        with open(concat_list_path, "w") as f: f.write("\n".join([f"file '{p}'" for p in final_audio_parts]))
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", audio_path], check=True, capture_output=True)
        os.remove(concat_list_path)
        for p in final_audio_parts: os.remove(p)
    return srt_text, get_duration(audio_path)

def auto_detect_subtitle_y(video_path):
    try:
        duration = get_duration(video_path)
        sample_time = duration * 0.1 if duration else 5
        temp_frame = tempfile.mktemp(suffix=".jpg")
        subprocess.run(["ffmpeg", "-y", "-ss", str(sample_time), "-i", video_path, "-frames:v", "1", temp_frame], check=True, capture_output=True)
        if not os.path.exists(temp_frame): return 85, 10
        img = Image.open(temp_frame).convert('L')
        width, height = img.size
        bottom_part = img.crop((0, int(height * 0.6), width, height))
        arr = np.array(bottom_part)
        row_variance = np.var(arr, axis=1)
        threshold = np.mean(row_variance) * 2.0
        text_rows = np.where(row_variance > threshold)[0]
        if len(text_rows) > 0:
            actual_y_start, actual_y_end = int(height * 0.6) + text_rows[0], int(height * 0.6) + text_rows[-1]
            padding = 5
            final_y, final_h = max(0, actual_y_start - padding), min(height, (actual_y_end - actual_y_start) + (padding * 2))
            os.remove(temp_frame)
            return (final_y / height) * 100, (final_h / height) * 100
        os.remove(temp_frame)
    except: pass
    return 85, 10

def get_blur_filter(mirror, scale, blur, blur_y, blur_h, burn_subs=False, srt_path=None, f_size=15, sub_y=85):
    v_filters = []
    if mirror: v_filters.append("hflip")
    if scale: v_filters.append("scale=1.06*iw:-1,crop=iw/1.06:ih/1.06")
    
    if blur:
        y_start, h_ratio = blur_y / 100.0, blur_h / 100.0
        base_v = ",".join(v_filters) if v_filters else "null"
        fc = f"[0:v]{base_v},split[m][b];[b]crop=iw:ih*{h_ratio}:0:ih*{y_start},boxblur=15:5[blurred];[m][blurred]overlay=0:main_h*{y_start}"
    else:
        # If no filters, use null to avoid invalid filter complex
        base_v = ",".join(v_filters) if v_filters else "null"
        fc = f"[0:v]{base_v}"

    if burn_subs and srt_path:
        srt_esc = os.path.relpath(srt_path).replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")
        font_dir = os.getcwd().replace("\\", "/").replace(":", "\\:")
        margin_v = max(5, int(100 - sub_y))
        fc += f",subtitles='{srt_esc}':fontsdir='{font_dir}':force_style='FontName=Pyidaungsu,FontSize={f_size},PrimaryColour=&H00FFFF,OutlineColour=&H000000,BorderStyle=3,Alignment=2,MarginL=10,MarginR=10,MarginV={margin_v}'"
    
    if not fc.endswith("[v]"): fc += "[v]"
    return fc

def render_pro_video_v44(video_path, audio_path, srt_path, mirror, scale, blur, burn_subs, blur_y=85, blur_h=10, f_size=15, sub_y=85):
    output_video = tempfile.mktemp(suffix=".mp4")
    fc = get_blur_filter(mirror, scale, blur, blur_y, blur_h, burn_subs, srt_path, f_size, sub_y)
    cmd = ["ffmpeg", "-y", "-i", video_path, "-i", audio_path, "-filter_complex", fc, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-c:a", "aac", "-b:a", "128k", "-shortest", "-threads", "0", output_video]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    return output_video if result.returncode == 0 else None

def translate_content(audio_path, target_sec, keys):
    duration_prompt = f"- TARGET DURATION: Approx {target_sec} seconds." if target_sec > 0 else ""
    prompt = f"Listen to this English audio and translate it into a Myanmar Movie Recap style. {duration_prompt} - Dramatic tone. IMPORTANT: Output ONLY in valid SRT format. Use Myanmar language."
    with open(audio_path, 'rb') as f: file_data = base64.b64encode(f.read()).decode('utf-8')
    contents = [{"role": "user", "parts": [{"text": prompt}, {"inline_data": {"mime_type": "audio/mp3", "data": file_data}}]}]
    for key in keys:
        for model in MODELS_TO_TRY:
            try:
                url = f"{GEMINI_BASE_URL}/{model}:generateContent?key={key}"
                res = requests.post(url, json={"contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}}, timeout=300)
                if res.status_code == 429: break
                return res.json()['candidates'][0]['content']['parts'][0]['text']
            except: continue
    raise Exception("All API keys failed.")

# --- MAIN UI ---
uploaded_file = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if uploaded_file:
    file_id = uploaded_file.name + str(uploaded_file.size)
    if st.session_state.last_uploaded != file_id:
        st.session_state.last_uploaded = file_id
        suffix = "." + uploaded_file.name.split(".")[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tfile:
            tfile.write(uploaded_file.getvalue())
            temp_path = tfile.name
        if suffix.lower() in [".mp4", ".mov", ".avi"]:
            base_img = tempfile.mktemp(suffix=".jpg")
            dur = get_duration(temp_path)
            subprocess.run(["ffmpeg", "-y", "-ss", str(dur * 0.1 if dur else 5), "-i", temp_path, "-frames:v", "1", base_img], capture_output=True)
            if os.path.exists(base_img):
                with open(base_img, "rb") as f: st.session_state.base_frame = f.read()
                os.remove(base_img)
        os.remove(temp_path)

    if auto_detect_btn:
        with tempfile.NamedTemporaryFile(delete=False, suffix="." + uploaded_file.name.split(".")[-1]) as tfile:
            tfile.write(uploaded_file.getvalue()); temp_preview_path = tfile.name
        det_y, det_h = auto_detect_subtitle_y(temp_preview_path)
        st.session_state.blur_y_pos, st.session_state.blur_h_size = float(det_y), float(det_h)
        os.remove(temp_preview_path); st.rerun()

    if show_preview and st.session_state.base_frame:
        st.subheader("🖼️ Real-time Preview (Blur & Subtitle)")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as bfile:
            bfile.write(st.session_state.base_frame); bpath = bfile.name
        
        # Sample SRT for preview
        sample_srt = "1\n00:00:00,000 --> 00:00:10,000\nမြန်မာစာ စမ်းသပ်ကြည့်ရှုခြင်း"
        srt_preview_path = os.path.abspath("preview.srt")
        with open(srt_preview_path, "w", encoding="utf-8") as f: f.write(sample_srt)
        
        preview_out = tempfile.mktemp(suffix=".jpg")
        fc = get_blur_filter(mirror_video, scale_video, blur_subtitles, st.session_state.blur_y_pos, st.session_state.blur_h_size, burn_myanmar_subs, srt_preview_path, st.session_state.font_size, st.session_state.sub_y_pos)
        fc_simple = fc.replace("[0:v]", "").replace("[v]", "").strip(",")
        if not fc_simple: fc_simple = "null"
        
        try:
            subprocess.run(["ffmpeg", "-y", "-i", bpath, "-vf", fc_simple, preview_out], check=True, capture_output=True)
            if os.path.exists(preview_out):
                st.image(preview_out, caption="Preview Area")
                os.remove(preview_out)
        except Exception as e: st.error(f"Preview Error: {e}")
        finally:
            if os.path.exists(bpath): os.remove(bpath)
            if os.path.exists(srt_preview_path): os.remove(srt_preview_path)

    if not api_keys: st.warning("⚠️ Sidebar တွင် API Key ထည့်ပေးပါ")
    elif st.button("🚀 Start Pro Processing & Render Video"):
        progress_bar = st.progress(0); status_text = st.empty()
        try:
            status_text.text("📊 အဆင့် ၁: ဖိုင်ကို စစ်ဆေးနေပါသည်... (10%)")
            progress_bar.progress(10)
            suffix = "." + uploaded_file.name.split(".")[-1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tfile:
                tfile.write(uploaded_file.read()); temp_path = tfile.name
            audio_for_gemini = extract_audio(temp_path) if suffix.lower() in [".mp4", ".mov", ".avi"] else temp_path
            
            status_text.text("⏳ အဆင့် ၂: ဘာသာပြန်နေပါသည်... (40%)")
            progress_bar.progress(40)
            st.session_state.myanmar_text = translate_content(audio_for_gemini, total_target_sec, api_keys)
            
            status_text.text("🔊 အဆင့် ၃: အသံဖိုင်နှင့် Subtitle ထုတ်ပေးနေပါသည်... (70%)")
            progress_bar.progress(70)
            audio_output = os.path.abspath("temp_audio.mp3")
            st.session_state.srt_data, _ = asyncio.run(generate_audio_and_srt_v44(st.session_state.myanmar_text, audio_output, voice_id, speed, pitch, total_target_sec))
            if os.path.exists(audio_output):
                with open(audio_output, "rb") as f: st.session_state.audio_data = f.read()
            
            if suffix.lower() in [".mp4", ".mov", ".avi"]:
                status_text.text("🎬 အဆင့် ၄: ဗီဒီယိုကို တည်းဖြတ်နေပါသည် (Rendering)... (90%)")
                progress_bar.progress(90)
                srt_temp_path = os.path.abspath("temp_subtitle.srt")
                with open(srt_temp_path, "w", encoding="utf-8") as f: f.write(st.session_state.srt_data)
                final_v = render_pro_video_v44(temp_path, audio_output, srt_temp_path, mirror_video, scale_video, blur_subtitles, burn_myanmar_subs, st.session_state.blur_y_pos, st.session_state.blur_h_size, st.session_state.font_size, st.session_state.sub_y_pos)
                if final_v:
                    with open(final_v, "rb") as f: st.session_state.video_data = f.read()
                    os.remove(final_v)
                if os.path.exists(srt_temp_path): os.remove(srt_temp_path)

            progress_bar.progress(100); status_text.text("✅ အားလုံး ပြီးစီးပါပြီ!"); st.session_state.processing_done = True; st.balloons()
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

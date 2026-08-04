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
import re
import shutil

# --- CONFIGURATION ---
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MODELS_TO_TRY = ["gemini-1.5-flash", "gemini-3.5-flash", "gemini-2.0-flash-exp", "gemini-1.5-flash-8b"]

st.set_page_config(
    page_title="Movie Recap AI Pro V4.4", 
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

st.title("🎬 Movie Recap AI Pro V4.4")
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
    burn_myanmar_subs = st.checkbox("Burn Myanmar Subtitles", value=True)
    
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

def render_pro_video_v44(video_path, audio_path, srt_path, mirror, scale, blur, burn_subs):
    output_video = tempfile.mktemp(suffix='.mp4')
    try:
        # Check if SRT exists if burning is requested
        if burn_subs:
            if not os.path.exists(srt_path) or os.path.getsize(srt_path) == 0:
                st.warning("⚠️ SRT file is missing or empty. Subtitles will not be burned.")
                burn_subs = False

        # Construct Filter String carefully
        v_filters = []
        if mirror: v_filters.append("hflip")
        if scale: v_filters.append("scale=1.06*iw:-1,crop=iw/1.06:ih/1.06")
        
        # Complex Filter Construction
        if blur:
            base_v = ",".join(v_filters) if v_filters else "null"
            fc = f"[0:v]{base_v},split[m][b];[b]crop=iw:ih*0.2:0:ih*0.8,boxblur=20:10[blurred];[m][blurred]overlay=0:main_h*0.8"
            if burn_subs:
                # Use relative path and escape for FFmpeg subtitles filter
                rel_srt = os.path.relpath(srt_path)
                srt_esc = rel_srt.replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")
                fc += f",subtitles='{srt_esc}':force_style='FontSize=12,PrimaryColour=&H00FFFF,OutlineColour=&H000000,BorderStyle=3,Alignment=2,MarginV=10'[v]"
            else:
                fc += "[v]"
        else:
            fc = "[0:v]" + ("," + ",".join(v_filters) if v_filters else "")
            if burn_subs:
                # Use relative path and escape for FFmpeg subtitles filter
                rel_srt = os.path.relpath(srt_path)
                srt_esc = rel_srt.replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")
                fc += f",subtitles='{srt_esc}':force_style='FontSize=12,PrimaryColour=&H00FFFF,OutlineColour=&H000000,BorderStyle=3,Alignment=2,MarginV=10'[v]"
            else:
                fc += "[v]"

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
                    
                    final_video_path = render_pro_video_v44(temp_path, audio_output, srt_temp_path, mirror_video, scale_video, blur_subtitles, burn_myanmar_subs)
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

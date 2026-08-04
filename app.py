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

st.set_page_config(page_title="Movie Recap AI Pro", page_icon="🎬", layout="centered")

# --- HIDE STREAMLIT BRANDING & GITHUB LINKS ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .stDeployButton {display:none;}
            #stDecoration {display:none;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# Session State Persistence
if 'myanmar_text' not in st.session_state: st.session_state.myanmar_text = None
if 'audio_data' not in st.session_state: st.session_state.audio_data = None
if 'srt_data' not in st.session_state: st.session_state.srt_data = None
if 'processing_done' not in st.session_state: st.session_state.processing_done = False

# Version Tag (Internal use)
st.title("🎬 Movie Recap AI Pro")
st.markdown("English Video/Audio → Myanmar Movie Recap Style")

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
    st.subheader("⏱️ Duration Control")
    enable_target = st.toggle("Enable Target Duration", value=False)
    
    total_target_sec = 0
    if enable_target:
        col_m, col_s = st.columns(2)
        with col_m:
            target_min = st.number_input("Minutes", min_value=0, max_value=60, value=1)
        with col_s:
            target_sec = st.number_input("Seconds", min_value=0, max_value=59, value=30)
        total_target_sec = (target_min * 60) + target_sec
    
    st.markdown("---")
    st.subheader("🔊 Voice Settings")
    voice_choice = st.selectbox("Select Voice", ["Thiha (Male)", "Nilar (Female)"], index=0)
    voice_id = "my-MM-ThihaNeural" if "Thiha" in voice_choice else "my-MM-NilarNeural"
    
    speed = st.slider("Base Speed", 1, 100, 55)
    pitch = st.slider("Pitch", 1, 100, 50)
    
    if st.button("🧹 Clear All Data"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# --- UTILITIES ---
def is_ffmpeg_installed():
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

def get_duration(file_path):
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        duration_str = result.stdout.strip()
        if duration_str:
            return float(duration_str)
        return None
    except:
        return None

def extract_audio(video_path):
    audio_path = tempfile.mktemp(suffix='.mp3')
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path, 
            "-vn", "-acodec", "libmp3lame", "-q:a", "4", 
            audio_path
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return audio_path
    except:
        return None

def speed_to_edge_rate(speed):
    val = int((speed - 50) * 2)
    return f"+{val}%" if val >= 0 else f"{val}%"

def pitch_to_edge_hz(pitch):
    val = int((pitch - 50) * 2)
    return f"+{val}Hz" if val >= 0 else f"{val}Hz"

def format_srt_time(seconds):
    if seconds is None: seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def translate_error_to_myanmar(error_msg):
    error_msg = str(error_msg).lower()
    if not is_ffmpeg_installed():
        return "❌ စနစ်ပိုင်းဆိုင်ရာ အမှားအယွင်းရှိနေပါသည်။ (FFmpeg not found)"
    if "429" in error_msg or "quota" in error_msg:
        return "❌ Gemini API အသုံးပြုမှု ကန့်သတ်ချက် ပြည့်သွားပါပြီ။ နောက်ထပ် API Key တစ်ခုကို စမ်းကြည့်ပါ။"
    elif "413" in error_msg or "payload too large" in error_msg:
        return "❌ ဖိုင်ဆိုဒ် အရမ်းကြီးနေပါသည်။"
    else:
        return f"❌ အမှားအယွင်းတစ်ခု ဖြစ်ပွားခဲ့ပါသည်: {error_msg}"

async def generate_audio_and_srt_v38(text, audio_path, v_id, s, p, target_duration=0):
    rate = speed_to_edge_rate(s)
    p_hz = pitch_to_edge_hz(p)
    communicate = edge_tts.Communicate(text, v_id, rate=rate, pitch=p_hz)
    
    temp_audio = tempfile.mktemp(suffix='.mp3')
    word_boundaries = []
    try:
        with open(temp_audio, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    word_boundaries.append({
                        "start": chunk["offset"] / 10000000,
                        "duration": chunk["duration"] / 10000000,
                        "text": chunk["text"]
                    })
    except Exception as e:
        if os.path.exists(temp_audio): os.remove(temp_audio)
        raise e
    
    actual_duration = get_duration(temp_audio)
    if actual_duration is None or actual_duration == 0:
        if os.path.exists(temp_audio): os.remove(temp_audio)
        raise Exception("အသံဖိုင်မှ ကြာချိန်ကို ရှာမတွေ့ပါဘူး။")

    speed_multiplier = 1.0
    if target_duration > 0:
        speed_multiplier = actual_duration / target_duration
        speed_multiplier = max(0.5, min(2.0, speed_multiplier))
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", temp_audio, 
                "-filter:a", f"atempo={speed_multiplier}", 
                audio_path
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except:
            shutil.copy(temp_audio, audio_path)
            speed_multiplier = 1.0
    else:
        shutil.copy(temp_audio, audio_path)

    final_dur = get_duration(audio_path) or actual_duration

    srt_lines = []
    counter = 1
    current_sentence = []
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
                    
    if os.path.exists(temp_audio): os.remove(temp_audio)
    return "\n".join(srt_lines), final_dur

def gemini_generate_auto(contents, keys):
    last_error = ""
    for key in keys:
        for model in MODELS_TO_TRY:
            try:
                url = f"{GEMINI_BASE_URL}/{model}:generateContent?key={key}"
                payload = {"contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}}
                response = requests.post(url, json=payload, timeout=300)
                if response.status_code == 429: break 
                if response.status_code == 404: continue 
                response.raise_for_status()
                result = response.json()
                return result['candidates'][0]['content']['parts'][0]['text']
            except Exception as e:
                last_error = str(e)
                continue
    raise Exception(last_error)

def translate_content(audio_path, target_sec, keys):
    duration_prompt = f"- TARGET DURATION: Approx {target_sec} seconds." if target_sec > 0 else ""
    prompt = f"""You are a professional movie recap expert and Myanmar translator. 
Listen to this English audio and translate it into Myanmar language in the dramatic storytelling style of "Thiha Voice".
{duration_prompt}
- Dramatic tone.
- Use phrases like "ဆိုပြီး...", "ဒီမှာတော့...".
Write ENTIRELY in Myanmar language."""
    with open(audio_path, 'rb') as f:
        file_data = base64.b64encode(f.read()).decode('utf-8')
    contents = [{"role": "user", "parts": [{"text": prompt}, {"inline_data": {"mime_type": "audio/mp3", "data": file_data}}]}]
    return gemini_generate_auto(contents, keys)

# --- MAIN UI ---
uploaded_file = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if uploaded_file is not None:
    if not api_keys:
        st.warning("⚠️ Sidebar တွင် API Key ထည့်ပေးပါ")
    else:
        if st.button("🚀 Start Processing"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            try:
                status_text.text("📊 အဆင့် ၁: ဖိုင်ကို စစ်ဆေးနေပါသည်... (10%)")
                progress_bar.progress(10)
                suffix = "." + uploaded_file.name.split(".")[-1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tfile:
                    tfile.write(uploaded_file.read())
                    temp_path = tfile.name
                
                if suffix.lower() in [".mp4", ".mov", ".avi"]:
                    audio_for_gemini = extract_audio(temp_path)
                else:
                    audio_for_gemini = temp_path
                
                if not audio_for_gemini: raise Exception("Error extracting audio.")
                progress_bar.progress(20)
                
                status_text.text("⏳ အဆင့် ၂: ဘာသာပြန်နေပါသည်... (40%)")
                progress_bar.progress(40)
                st.session_state.myanmar_text = translate_content(audio_for_gemini, total_target_sec, api_keys)
                
                status_text.text("🔊 အဆင့် ၃: အသံဖိုင်နှင့် Subtitle ထုတ်ပေးနေပါသည်... (80%)")
                progress_bar.progress(80)
                audio_output = tempfile.mktemp(suffix='.mp3')
                st.session_state.srt_data, final_dur = asyncio.run(
                    generate_audio_and_srt_v38(st.session_state.myanmar_text, audio_output, voice_id, speed, pitch, total_target_sec)
                )
                if os.path.exists(audio_output):
                    with open(audio_output, "rb") as f:
                        st.session_state.audio_data = f.read()
                
                progress_bar.progress(100)
                status_text.text(f"✅ ပြီးစီးပါပြီ! ({int(final_dur if final_dur else 0)}s)")
                st.session_state.processing_done = True
                st.balloons()
                
                if os.path.exists(temp_path): os.remove(temp_path)
                if audio_for_gemini != temp_path and os.path.exists(audio_for_gemini): os.remove(audio_for_gemini)
                if os.path.exists(audio_output): os.remove(audio_output)
            except Exception as e:
                st.error(translate_error_to_myanmar(e))

# Display results
if st.session_state.processing_done:
    st.markdown("---")
    st.subheader("🇲🇲 Myanmar Recap Result")
    st.write(st.session_state.myanmar_text)
    st.subheader("📥 Downloads")
    col1, col2 = st.columns(2)
    with col1:
        if st.session_state.audio_data:
            st.audio(st.session_state.audio_data, format="audio/mp3")
            st.download_button("📥 Download Audio", st.session_state.audio_data, file_name="recap_audio.mp3", mime="audio/mp3")
    with col2:
        if st.session_state.srt_data:
            st.download_button("📥 Download SRT (CapCut)", st.session_state.srt_data, file_name="recap_subtitle.srt", mime="text/plain")

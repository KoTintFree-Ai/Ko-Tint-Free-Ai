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

# --- CONFIGURATION ---
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MODELS_TO_TRY = ["gemini-3.5-flash", "gemini-1.5-flash", "gemini-2.0-flash-exp", "gemini-1.5-flash-8b"]

st.set_page_config(page_title="🎬 Movie Recap AI Ultimate V3.0", page_icon="🎬", layout="centered")

# Session State Persistence
if 'myanmar_text' not in st.session_state: st.session_state.myanmar_text = None
if 'audio_data' not in st.session_state: st.session_state.audio_data = None
if 'srt_data' not in st.session_state: st.session_state.srt_data = None
if 'processing_done' not in st.session_state: st.session_state.processing_done = False

# Version Tag
st.caption("🚀 Version 3.0 - Ultimate Duration Control & Word-Level Sync")
st.title("🎬 Movie Recap AI Ultimate")
st.markdown("English Video/Audio → Myanmar Movie Recap Style + Precise SRT")

# --- SIDEBAR SETTINGS ---
with st.sidebar:
    st.header("⚙️ Settings")
    st.subheader("🔑 Gemini API Keys (5 slots)")
    key1 = st.text_input("API Key 1", type="password")
    key2 = st.text_input("API Key 2", type="password")
    key3 = st.text_input("API Key 3", type="password")
    key4 = st.text_input("API Key 4", type="password")
    key5 = st.text_input("API Key 5", type="password")
    api_keys = [k for k in [key1, key2, key3, key4, key5] if k]
    
    st.markdown("---")
    st.subheader("⏱️ Target Duration")
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
    
    speed = st.slider("Speed", 1, 100, 55)
    pitch = st.slider("Pitch", 1, 100, 50)
    
    if st.button("🧹 Clear All Data"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# --- UTILITIES ---
def get_duration(file_path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        return float(result.stdout)
    except: return None

def speed_to_edge_rate(speed):
    val = int((speed - 50) * 2)
    return f"+{val}%" if val >= 0 else f"{val}%"

def pitch_to_edge_hz(pitch):
    val = int((pitch - 50) * 2)
    return f"+{val}Hz" if val >= 0 else f"{val}Hz"

def format_srt_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

# HIGH-PRECISION Word-Level SRT Sync
async def generate_audio_and_srt_ultimate(text, audio_path, v_id, s, p):
    rate = speed_to_edge_rate(s)
    p_hz = pitch_to_edge_hz(p)
    communicate = edge_tts.Communicate(text, v_id, rate=rate, pitch=p_hz)
    
    word_boundaries = []
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_boundaries.append({
                    "start": chunk["offset"] / 10000000,
                    "duration": chunk["duration"] / 10000000,
                    "text": chunk["text"]
                })
    
    if not word_boundaries:
        return ""

    srt_lines = []
    counter = 1
    current_sentence = []
    start_time = word_boundaries[0]["start"]
    
    for i, wb in enumerate(word_boundaries):
        current_sentence.append(wb["text"])
        end_time = wb["start"] + wb["duration"]
        
        # Smart Splitting Logic
        is_last = (i == len(word_boundaries) - 1)
        # Split on Myanmar punctuation or if a line gets too long
        has_marker = any(m in wb["text"] for m in ["။", "!", "?", " "])
        line_too_long = len("".join(current_sentence)) > 45
        
        # Check for natural pauses (gap > 0.4s)
        large_gap = False
        if not is_last:
            large_gap = (word_boundaries[i+1]["start"] - end_time) > 0.4

        if is_last or has_marker or line_too_long or large_gap:
            sentence_text = "".join(current_sentence).strip()
            if sentence_text:
                srt_lines.append(str(counter))
                srt_lines.append(f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}")
                srt_lines.append(sentence_text)
                srt_lines.append("")
                counter += 1
            
            if not is_last:
                current_sentence = []
                start_time = word_boundaries[i+1]["start"]
                
    return "\n".join(srt_lines)

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
    raise Exception(f"All keys and models failed. Last error: {last_error}")

def translate_with_duration(file_path, file_type, target_sec, keys):
    mime_type = "audio/mp3" if file_type == "audio" else "video/mp4"
    prompt = f"""You are a professional movie recap expert and Myanmar translator. 
Translate the content into Myanmar language in the dramatic storytelling style of "Thiha Voice".
- TARGET DURATION: The recap script should take approximately {target_sec} seconds to read aloud.
- Dramatic tone (voice ကြမ်းကြမ်း၊ ဆွဲဆွဲငင်ငင်).
- Use phrases like "ဆိုပြီး...", "ဒီမှာတော့...".
Write ENTIRELY in Myanmar language."""
    with open(file_path, 'rb') as f:
        file_data = base64.b64encode(f.read()).decode('utf-8')
    contents = [{"role": "user", "parts": [{"text": prompt}, {"inline_data": {"mime_type": mime_type, "data": file_data}}]}]
    return gemini_generate_auto(contents, keys)

def smooth_progress(bar, text_element, start_val, end_val, label, speed=0.03):
    for i in range(start_val, end_val + 1):
        bar.progress(i)
        text_element.text(f"⏳ {label} ({i}%)")
        time.sleep(speed)

# --- MAIN UI ---
uploaded_file = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if uploaded_file is not None:
    if not api_keys:
        st.warning("⚠️ Sidebar မှာ အနည်းဆုံး API Key တစ်ခု ထည့်ပေးပါ")
    else:
        if st.button("🚀 Start Processing"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            try:
                # 1. Prep (1-10%)
                smooth_progress(progress_bar, status_text, 0, 10, "ဖိုင်ကို စစ်ဆေးနေပါတယ်...")
                suffix = "." + uploaded_file.name.split(".")[-1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tfile:
                    tfile.write(uploaded_file.read())
                    temp_path = tfile.name
                
                # 2. Translation with Duration (11-50%)
                status_text.text(f"⏳ Gemini AI ဖြင့် {total_target_sec} စကန့်စာ ဘာသာပြန်နေပါတယ်... (11%)")
                ftype = "video" if suffix.lower() in [".mp4", ".mov", ".avi"] else "audio"
                st.session_state.myanmar_text = translate_with_duration(temp_path, ftype, total_target_sec, api_keys)
                smooth_progress(progress_bar, status_text, 11, 50, "Gemini AI ဖြင့် ဘာသာပြန်နေပါတယ်...")
                
                # 3. Audio & SRT Sync (51-100%)
                status_text.text("⏳ အသံဖိုင်နှင့် Subtitle ကို အတိအကျ ညှိပြီး ထုတ်ပေးနေပါတယ်... (51%)")
                audio_output = tempfile.mktemp(suffix='.mp3')
                
                # Using the ULTIMATE Word-Level Sync
                st.session_state.srt_data = asyncio.run(generate_audio_and_srt_ultimate(st.session_state.myanmar_text, audio_output, voice_id, speed, pitch))
                
                if os.path.exists(audio_output):
                    with open(audio_output, "rb") as f:
                        st.session_state.audio_data = f.read()
                
                smooth_progress(progress_bar, status_text, 51, 100, "အသံဖိုင်နှင့် Subtitle ကို အတိအကျ ညှိပြီး ထုတ်ပေးနေပါတယ်...")
                
                st.session_state.processing_done = True
                status_text.text("✅ အားလုံး ပြီးစီးပါပြီ! (100%)")
                st.balloons()
                
                if os.path.exists(temp_path): os.remove(temp_path)
                if os.path.exists(audio_output): os.remove(audio_output)
                
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

# Display results from session state
if st.session_state.processing_done:
    st.markdown("---")
    st.subheader("🇲🇲 Myanmar Recap Result")
    st.write(st.session_state.myanmar_text)
    
    st.subheader("📥 Downloads")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.session_state.audio_data:
            st.info("🔊 Myanmar Audio Ready")
            st.audio(st.session_state.audio_data, format="audio/mp3")
            st.download_button("📥 Download Audio", st.session_state.audio_data, file_name="recap_audio.mp3", mime="audio/mp3")
    
    with col2:
        if st.session_state.srt_data:
            st.info("📝 Ultimate Sync SRT Ready")
            st.download_button("📥 Download SRT (CapCut)", st.session_state.srt_data, file_name="recap_subtitle.srt", mime="text/plain")

st.markdown("---")
st.caption("Developed for Myanmar Movie Recap Creators | Version 3.0 Ultimate")

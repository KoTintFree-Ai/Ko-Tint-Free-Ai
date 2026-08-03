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

st.set_page_config(page_title="🎬 Movie Recap AI Pro V2.7", page_icon="🎬", layout="centered")

# Session State Persistence
if 'myanmar_text' not in st.session_state: st.session_state.myanmar_text = None
if 'audio_data' not in st.session_state: st.session_state.audio_data = None
if 'srt_data' not in st.session_state: st.session_state.srt_data = None
if 'processing_done' not in st.session_state: st.session_state.processing_done = False

# Version Tag
st.caption("🚀 Version 2.7 - Original Bot Timing Logic (Exact Match)")
st.title("🎬 Movie Recap AI Pro")
st.markdown("English Video/Audio → Myanmar Movie Recap Style (Thiha Voice) + Exact SRT")

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
    
    st.success(f"🎯 Primary Model: {MODELS_TO_TRY[0]}")
    
    st.subheader("🔊 Voice Settings")
    voice_choice = st.selectbox("Select Voice", ["Thiha (Male)", "Nilar (Female)"], index=0)
    voice_id = "my-MM-ThihaNeural" if "Thiha" in voice_choice else "my-MM-NilarNeural"
    
    speed = st.slider("Speed", 1, 100, 55)
    pitch = st.slider("Pitch", 1, 100, 50)
    
    if st.button("🧹 Clear All Data"):
        st.session_state.myanmar_text = None
        st.session_state.audio_data = None
        st.session_state.srt_data = None
        st.session_state.processing_done = False
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

# --- ORIGINAL BOT SRT LOGIC (EXACT COPY) ---
def generate_srt_bot_logic(text, audio_duration=None):
    clean_text = text.strip()
    if not clean_text: return ""
    
    # EXACT SPLITTING FROM BOT
    sentence_endings = ['။', '. ', '! ', '? ', '\n']
    sentences = [clean_text]
    for ending in sentence_endings:
        new_s = []
        for s in sentences:
            parts = s.split(ending)
            new_s.extend(parts)
        sentences = new_s
    
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences: sentences = [clean_text]
    
    srt_lines = []
    current_time = 0.5  # Bot initial delay
    
    if audio_duration and audio_duration > 0:
        total_chars = sum(len(s) for s in sentences)
        # Available time after removing initial delay and small gaps (0.1s) between sentences
        available_time = audio_duration - 0.5 - (len(sentences) * 0.1)
        if available_time < 0: available_time = audio_duration
        
        for i, sentence in enumerate(sentences):
            char_ratio = len(sentence) / total_chars
            duration = available_time * char_ratio
            
            start_time = current_time
            end_time = current_time + duration
            current_time = end_time + 0.1 # Bot small gap
            
            srt_lines.extend([str(i + 1), f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}", sentence, ""])
    else:
        # Fallback to estimated timing from Bot
        for i, sentence in enumerate(sentences):
            duration = max(2.0, len(sentence) / 15.0) 
            start_time = current_time
            end_time = current_time + duration
            current_time = end_time + 0.3
            srt_lines.extend([str(i + 1), f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}", sentence, ""])
            
    return "\n".join(srt_lines)

async def _generate_audio(text, output_path, v_id, s, p):
    rate = speed_to_edge_rate(s)
    p_hz = pitch_to_edge_hz(p)
    communicate = edge_tts.Communicate(text, v_id, rate=rate, pitch=p_hz)
    await communicate.save(output_path)

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

def transcribe_and_translate(file_path, file_type, duration_sec, keys):
    mime_type = "audio/mp3" if file_type == "audio" else "video/mp4"
    duration_info = f"\n- TARGET LENGTH: {int(duration_sec)} seconds recap style." if duration_sec else ""
    prompt = f"""You are a professional movie recap expert and Myanmar translator. 
Translate the content into Myanmar language in the dramatic storytelling style of "Thiha Voice".
- NO extra content.
- Dramatic tone (voice ကြမ်းကြမ်း၊ ဆွဲဆွဲငင်ငင်).
- Use phrases like "ဆိုပြီး...", "ဒီမှာတော့...".{duration_info}
Write ENTIRELY in Myanmar language in paragraphs."""
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
                # Step 1: Prep (1-15%)
                smooth_progress(progress_bar, status_text, 0, 15, "ဖိုင်ကို စစ်ဆေးနေပါတယ်...")
                suffix = "." + uploaded_file.name.split(".")[-1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tfile:
                    tfile.write(uploaded_file.read())
                    temp_path = tfile.name
                duration = get_duration(temp_path)
                
                # Step 2: AI (16-60%)
                status_text.text(f"⏳ Gemini AI ဖြင့် ဘာသာပြန်နေပါတယ်... (16%)")
                ftype = "video" if suffix.lower() in [".mp4", ".mov", ".avi"] else "audio"
                st.session_state.myanmar_text = transcribe_and_translate(temp_path, ftype, duration, api_keys)
                smooth_progress(progress_bar, status_text, 16, 60, "Gemini AI ဖြင့် ဘာသာပြန်နေပါတယ်...")
                
                # Step 3: Audio Generation (61-90%)
                status_text.text("⏳ အသံဖိုင် ဖန်တီးနေပါတယ်... (61%)")
                audio_output = tempfile.mktemp(suffix='.mp3')
                asyncio.run(_generate_audio(st.session_state.myanmar_text, audio_output, voice_id, speed, pitch))
                if os.path.exists(audio_output):
                    with open(audio_output, "rb") as f:
                        st.session_state.audio_data = f.read()
                smooth_progress(progress_bar, status_text, 61, 90, "အသံဖိုင် ဖန်တီးနေပါတယ်...")
                
                # Step 4: SRT Generation (91-100%)
                status_text.text("⏳ Subtitle (SRT) ဖိုင်ကို Bot Logic ဖြင့် တွက်ချက်နေပါတယ်... (91%)")
                audio_dur = get_duration(audio_output) if os.path.exists(audio_output) else None
                st.session_state.srt_data = generate_srt_bot_logic(st.session_state.myanmar_text, audio_duration=audio_dur)
                smooth_progress(progress_bar, status_text, 91, 100, "Subtitle ဖိုင် ဖန်တီးနေပါတယ်...")
                
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
            st.info("📝 SRT Subtitle Ready")
            st.download_button("📥 Download SRT (CapCut)", st.session_state.srt_data, file_name="recap_subtitle.srt", mime="text/plain")

st.markdown("---")
st.caption("Developed for Myanmar Movie Recap Creators | Version 2.7 (Original Bot Logic)")

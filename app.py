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
# Keeping gemini-3.5-flash at the top as requested
MODELS_TO_TRY = ["gemini-3.5-flash", "gemini-1.5-flash", "gemini-2.0-flash-exp", "gemini-1.5-flash-8b"]

st.set_page_config(page_title="🎬 Movie Recap AI Pro V2.9", page_icon="🎬", layout="centered")

# Session State Persistence
if 'myanmar_text' not in st.session_state: st.session_state.myanmar_text = None
if 'audio_data' not in st.session_state: st.session_state.audio_data = None
if 'srt_data' not in st.session_state: st.session_state.srt_data = None
if 'processing_done' not in st.session_state: st.session_state.processing_done = False

# Version Tag
st.caption("🚀 Version 2.9 - Gemini Audio-to-SRT Sync")
st.title("🎬 Movie Recap AI Pro")
st.markdown("English Video/Audio → Myanmar Movie Recap Style + Gemini-Synced SRT")

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
    
    st.success(f"🎯 Current Model: {MODELS_TO_TRY[0]}")
    
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

def gemini_generate_auto(contents, keys):
    last_error = ""
    for key in keys:
        for model in MODELS_TO_TRY:
            try:
                url = f"{GEMINI_BASE_URL}/{model}:generateContent?key={key}"
                payload = {"contents": contents, "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8192}}
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

# STEP 1: TRANSLATION (AS BEFORE)
def translate_content(file_path, file_type, duration_sec, keys):
    mime_type = "audio/mp3" if file_type == "audio" else "video/mp4"
    prompt = f"""You are a professional movie recap expert and Myanmar translator. 
Translate the content into Myanmar language in the dramatic storytelling style of "Thiha Voice".
- Dramatic tone (voice ကြမ်းကြမ်း၊ ဆွဲဆွဲငင်ငင်).
- Use phrases like "ဆိုပြီး...", "ဒီမှာတော့...".
Write ENTIRELY in Myanmar language."""
    with open(file_path, 'rb') as f:
        file_data = base64.b64encode(f.read()).decode('utf-8')
    contents = [{"role": "user", "parts": [{"text": prompt}, {"inline_data": {"mime_type": mime_type, "data": file_data}}]}]
    return gemini_generate_auto(contents, keys)

# STEP 3: SRT GENERATION FROM PRODUCED AUDIO
def generate_srt_from_audio(audio_path, script_text, keys):
    with open(audio_path, 'rb') as f:
        audio_data = base64.b64encode(f.read()).decode('utf-8')
    
    prompt = f"""You are an expert SRT subtitle creator. 
I am providing you with a Myanmar audio file that was just generated.
Listen to this audio and generate a perfectly timed SRT file based on what is spoken.
- Use the provided script as a reference for the text.
- Timestamps must be exactly aligned with the audio.
- Format: SRT (00:00:00,000 --> 00:00:00,000).

SCRIPT:
{script_text}

Output ONLY the SRT content."""

    contents = [{"role": "user", "parts": [{"text": prompt}, {"inline_data": {"mime_type": "audio/mp3", "data": audio_data}}]}]
    return gemini_generate_auto(contents, keys)

async def _generate_audio(text, output_path, v_id, s, p):
    rate = speed_to_edge_rate(s)
    p_hz = pitch_to_edge_hz(p)
    communicate = edge_tts.Communicate(text, v_id, rate=rate, pitch=p_hz)
    await communicate.save(output_path)

def smooth_progress(bar, text_element, start_val, end_val, label, speed=0.02):
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
                # 1. File Preparation (1-10%)
                smooth_progress(progress_bar, status_text, 0, 10, "ဖိုင်ကို စစ်ဆေးနေပါတယ်...")
                suffix = "." + uploaded_file.name.split(".")[-1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tfile:
                    tfile.write(uploaded_file.read())
                    temp_path = tfile.name
                duration = get_duration(temp_path)
                
                # 2. Translation (11-45%)
                status_text.text("⏳ Gemini AI ဖြင့် ဘာသာပြန်နေပါတယ်... (11%)")
                ftype = "video" if suffix.lower() in [".mp4", ".mov", ".avi"] else "audio"
                st.session_state.myanmar_text = translate_content(temp_path, ftype, duration, api_keys)
                smooth_progress(progress_bar, status_text, 11, 45, "Gemini AI ဖြင့် ဘာသာပြန်နေပါတယ်...")
                
                # 3. Audio Generation (46-75%)
                status_text.text("⏳ အသံဖိုင် (TTS) ထုတ်နေပါတယ်... (46%)")
                audio_output = tempfile.mktemp(suffix='.mp3')
                asyncio.run(_generate_audio(st.session_state.myanmar_text, audio_output, voice_id, speed, pitch))
                if os.path.exists(audio_output):
                    with open(audio_output, "rb") as f:
                        st.session_state.audio_data = f.read()
                smooth_progress(progress_bar, status_text, 46, 75, "အသံဖိုင် (TTS) ထုတ်နေပါတယ်...")
                
                # 4. SRT Generation from Audio (76-100%)
                status_text.text("⏳ ထုတ်ထားသော အသံဖိုင်မှ Subtitle ကို Gemini ဖြင့် ညှိနေပါတယ်... (76%)")
                st.session_state.srt_data = generate_srt_from_audio(audio_output, st.session_state.myanmar_text, api_keys)
                smooth_progress(progress_bar, status_text, 76, 100, "Subtitle ကို Gemini ဖြင့် ညှိနေပါတယ်...")
                
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
            st.info("📝 Gemini-Synced SRT Ready")
            st.download_button("📥 Download SRT (CapCut)", st.session_state.srt_data, file_name="recap_subtitle.srt", mime="text/plain")

st.markdown("---")
st.caption("Developed for Myanmar Movie Recap Creators | Version 2.9 (Audio-to-SRT)")

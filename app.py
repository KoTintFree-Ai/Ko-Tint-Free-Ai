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

# --- CONFIGURATION ---
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.5-flash"

st.set_page_config(page_title="🎬 Movie Recap AI", page_icon="🎬", layout="centered")

st.title("🎬 Movie Recap AI Translator")
st.markdown("English Video/Audio ကို Myanmar Movie Recap Style (Thiha Voice) ပြောင်းလဲပေးမည့် Website")

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
    
    model_name = st.text_input("Model Name", value=DEFAULT_MODEL)
    
    st.subheader("🔊 Voice Settings")
    voice_choice = st.selectbox("Select Voice", ["Thiha (Male)", "Nilar (Female)"], index=0)
    voice_id = "my-MM-ThihaNeural" if "Thiha" in voice_choice else "my-MM-NilarNeural"
    
    speed = st.slider("Speed", 1, 100, 55)
    pitch = st.slider("Pitch", 1, 100, 50)

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

async def _generate_audio(text, output_path, v_id, s, p):
    rate = speed_to_edge_rate(s)
    p_hz = pitch_to_edge_hz(p)
    communicate = edge_tts.Communicate(text, v_id, rate=rate, pitch=p_hz)
    await communicate.save(output_path)

def gemini_generate_with_rotation(contents, keys, model):
    last_error = ""
    for i, key in enumerate(keys):
        try:
            url = f"{GEMINI_BASE_URL}/{model}:generateContent?key={key}"
            payload = {"contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}}
            response = requests.post(url, json=payload, timeout=300)
            
            if response.status_code == 429:
                st.warning(f"⚠️ Key {i+1} is rate limited. Trying next key...")
                continue
                
            response.raise_for_status()
            result = response.json()
            return result['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            last_error = str(e)
            st.warning(f"⚠️ Key {i+1} failed: {last_error}. Trying next key...")
            continue
    
    raise Exception(f"All API Keys failed. Last error: {last_error}")

def transcribe_and_translate(file_path, file_type, duration_sec, keys, model):
    mime_type = "audio/mp3" if file_type == "audio" else "video/mp4"
    duration_info = f"\n- TARGET LENGTH: {int(duration_sec)} seconds recap style." if duration_sec else ""
    
    prompt = f"""You are a professional movie recap expert and Myanmar translator. 
Translate the content into Myanmar language in the dramatic storytelling style of "Thiha Voice".
- NO extra content.
- Dramatic tone (voice ကြမ်းကြမ်း၊ ဆွဲဆွဲငင်ငင်).
- Use phrases like "ဆိုပြီး...", "ဒီမှာတော့...".{duration_info}
Write ENTIRELY in Myanmar language."""

    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    
    if file_size_mb < 19:
        with open(file_path, 'rb') as f:
            file_data = base64.b64encode(f.read()).decode('utf-8')
        contents = [{"role": "user", "parts": [{"text": prompt}, {"inline_data": {"mime_type": mime_type, "data": file_data}}]}]
        return gemini_generate_with_rotation(contents, keys, model)
    else:
        return "⚠️ File size > 20MB is not supported in this version. Please use smaller files."

# --- MAIN UI ---
uploaded_file = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if uploaded_file is not None:
    if not api_keys:
        st.warning("⚠️ Sidebar မှာ အနည်းဆုံး API Key တစ်ခု ထည့်ပေးပါ")
    else:
        if st.button("🚀 Start Processing"):
            with st.status("🔄 အလုပ်လုပ်နေပါတယ်... ခဏစောင့်ပေးပါ", expanded=True) as status:
                try:
                    # Save uploaded file to temp
                    suffix = "." + uploaded_file.name.split(".")[-1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tfile:
                        tfile.write(uploaded_file.read())
                        temp_path = tfile.name
                    
                    st.write("📊 File Duration စစ်ဆေးနေပါတယ်...")
                    duration = get_duration(temp_path)
                    
                    st.write("🤖 Gemini AI နဲ့ ဘာသာပြန်နေပါတယ်...")
                    ftype = "video" if suffix.lower() in [".mp4", ".mov", ".avi"] else "audio"
                    myanmar_text = transcribe_and_translate(temp_path, ftype, duration, api_keys, model_name)
                    
                    st.subheader("🇲🇲 Myanmar Recap Text")
                    st.write(myanmar_text)
                    
                    st.write("🔊 အသံဖိုင် ဖန်တီးနေပါတယ်...")
                    audio_output = tempfile.mktemp(suffix='.mp3')
                    asyncio.run(_generate_audio(myanmar_text, audio_output, voice_id, speed, pitch))
                    
                    if os.path.exists(audio_output) and os.path.getsize(audio_output) > 0:
                        st.subheader("🔊 Myanmar Audio")
                        st.audio(audio_output)
                        
                        with open(audio_output, "rb") as f:
                            st.download_button("📥 Download Audio", f, file_name="recap_audio.mp3")
                    else:
                        st.error("❌ အသံဖိုင် ဖန်တီးရာတွင် အမှားအယွင်းရှိခဲ့ပါသည်။")
                    
                    status.update(label="✅ အားလုံး ပြီးစီးပါပြီ!", state="complete")
                    st.balloons()
                    
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
                finally:
                    # Cleanup
                    if 'temp_path' in locals() and os.path.exists(temp_path): os.remove(temp_path)
                    if 'audio_output' in locals() and os.path.exists(audio_output): os.remove(audio_output)

st.markdown("---")
st.caption("Developed for Myanmar Movie Recap Creators | Powered by Gemini & Edge TTS")

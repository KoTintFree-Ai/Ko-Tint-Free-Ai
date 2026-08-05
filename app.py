import streamlit as st
import os
import asyncio
import edge_tts
import tempfile
import numpy as np
from PIL import Image, ImageFont
import time
import subprocess
import psutil
import gc

# --- CONFIGURATION ---
st.set_page_config(
    page_title="စိုင်းမြန်မာ အသံပြောင်းစနစ် Pro",
    page_icon="🎙️",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Get the directory where this script is located (for font file path)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(SCRIPT_DIR, "Pyidaungsu.ttf")

# --- Voice Definitions ---
VOICES = {
    "ကိုစိုင်းစိုင်း ယောက်ျားလေး": "my-MM-ThihaNeural",
    "ကိုနေတိုး ယောက်ျားလေး": "th-TH-PremwadeeNeural",
    "ကိုမြင့်မြတ် ယောက်ျားလေး": "my-MM-ThihaNeural",
    "ကိုဒေါင်း ယောက်ျားလေး": "th-TH-PremwadeeNeural",
    "ကိုလူမင်း ယောက်ျားလေး": "my-MM-ThihaNeural",
    "မရွှေမှုံရတီ မိန်းကလေး": "th-TH-AcharaNeural",
    "မဖွေးဖွေး မိန်းကလေး": "my-MM-NilarNeural",
    "ကိုအောင်ရဲလင်း ယောက်ျားလေး": "th-TH-AcharaNeural",
    "မဝတ်မှုံရွှေရည် မိန်းကလေး": "my-MM-NilarNeural",
    "မသက်မွန်မြင့် မိန်းကလေး": "th-TH-AcharaNeural",
    "မအိန္ဒြာကျော်ဇင် မိန်းကလေး": "my-MM-NilarNeural",
    "ကိုပြေတီဦး ယောက်ျားလေး": "th-TH-PremwadeeNeural",
}

# Additional voice styles
VOICE_STYLES = {
    "မသင်ဇာဝင့်ကျော် မိန်းကလေး": {"voice": "th-TH-AcharaNeural", "rate": "+15%", "pitch": "+5Hz"},
    "ကျားကြီး ၂": {"voice": "th-TH-PremwadeeNeural", "rate": "-30%", "pitch": "-20Hz"},
    "ပေါင်းစပ် ၃၀": {"voice": "my-MM-ThihaNeural", "rate": "+30%", "pitch": "+30Hz"},
    "ကိုပိုင်တံခွန် ယောက်ျားလေး": {"voice": "my-MM-ThihaNeural", "rate": "-10%", "pitch": "-3Hz"},
    "ကျားကြီး ၃": {"voice": "my-MM-ThihaNeural", "rate": "-35%", "pitch": "-25Hz"},
    "ပေါင်းစပ် ၅၀": {"voice": "my-MM-ThihaNeural", "rate": "+50%", "pitch": "+50Hz"},
    "ပုံမှန်အသံ": {"voice": "my-MM-ThihaNeural", "rate": "0%", "pitch": "0Hz"},
    "နီလာ ချွဲသံ": {"voice": "my-MM-NilarNeural", "rate": "+5%", "pitch": "+10Hz"},
    "အသံသေး ၂၀": {"voice": "my-MM-NilarNeural", "rate": "+20%", "pitch": "+20Hz"},
    "ကျားကြီး ၁": {"voice": "my-MM-ThihaNeural", "rate": "-25%", "pitch": "-15Hz"},
    "ပေါင်းစပ် ၁၅": {"voice": "my-MM-ThihaNeural", "rate": "+15%", "pitch": "+15Hz"},
    "အသံသေး ၅၀": {"voice": "my-MM-NilarNeural", "rate": "+50%", "pitch": "+50Hz"},
}

# Emotion styles
EMOTIONS = {
    "စိတ်လှုပ်ရှား 🤩": {"rate": "+25%", "pitch": "+10Hz"},
    "ပျော်ရွှင် 😊": {"rate": "+15%", "pitch": "+8Hz"},
    "ရွဲ့ပြော 🙄": {"rate": "+10%", "pitch": "+15Hz"},
    "တည်ငြိမ် 😌": {"rate": "-10%", "pitch": "-5Hz"},
    "လေးနက် 😠": {"rate": "-20%", "pitch": "-12Hz"},
    "ဒေါသထွက် 🤬": {"rate": "+20%", "pitch": "+12Hz"},
    "သတင်း 💼": {"rate": "+5%", "pitch": "0Hz"},
    "တီးတိုး 🤫": {"rate": "-30%", "pitch": "-8Hz"},
    "ကြောက်လန့် 😨": {"rate": "+30%", "pitch": "+20Hz"},
    "ဇာတ်ကြောင်း 📖": {"rate": "-5%", "pitch": "-3Hz"},
    "ဝမ်းနည်း 😢": {"rate": "-15%", "pitch": "-10Hz"},
}

# Sample text for voice preview
PREVIEW_TEXT = "မင်္ဂလာပါ။ ကျွန်တော်တို့ စိုင်းမြန်မာ TTS Pro ကို မိတ်ဆက်ပေးပါတယ်။"

# --- CSS Styling ---
st.markdown("""
<style>
    /* Main container */
    .main .block-container {
        max-width: 900px;
        padding: 1rem;
    }
    
    /* Hide default Streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display:none;}
    header {visibility: hidden;}
    
    /* Custom buttons */
    .voice-btn {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        border-radius: 8px;
        border: 2px solid #e0e0e0;
        background: white;
        cursor: pointer;
        transition: all 0.2s;
        width: 100%;
        text-align: left;
    }
    .voice-btn:hover {
        border-color: #7c3aed;
        background: #f5f3ff;
    }
    .voice-btn.selected {
        border-color: #7c3aed;
        background: #ede9fe;
    }
    .voice-btn .play-icon {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: #7c3aed;
        color: white;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
        flex-shrink: 0;
    }
    
    /* Emotion buttons */
    .emotion-btn {
        padding: 8px 12px;
        border-radius: 20px;
        border: 2px solid #e0e0e0;
        background: white;
        cursor: pointer;
        transition: all 0.2s;
        font-size: 14px;
    }
    .emotion-btn:hover {
        border-color: #06b6d4;
        background: #ecfeff;
    }
    .emotion-btn.selected {
        border-color: #06b6d4;
        background: #cffafe;
    }
    
    /* Style buttons */
    .style-btn {
        padding: 8px 12px;
        border-radius: 20px;
        border: 2px solid #e0e0e0;
        background: white;
        cursor: pointer;
        transition: all 0.2s;
        font-size: 14px;
    }
    .style-btn:hover {
        border-color: #f59e0b;
        background: #fef3c7;
    }
    .style-btn.selected {
        border-color: #f59e0b;
        background: #fde68a;
    }
    
    /* Generate button */
    .gen-btn {
        width: 100%;
        padding: 16px;
        font-size: 20px;
        font-weight: bold;
        border-radius: 12px;
        border: none;
        background: linear-gradient(135deg, #7c3aed, #06b6d4);
        color: white;
        cursor: pointer;
        transition: all 0.3s;
    }
    .gen-btn:hover {
        transform: scale(1.02);
        box-shadow: 0 4px 15px rgba(124, 58, 237, 0.4);
    }
    
    /* Text area */
    .custom-textarea textarea {
        min-height: 200px;
        font-size: 18px;
        padding: 16px;
        border-radius: 12px;
        border: 2px solid #e0e0e0;
    }
    
    /* Warning box */
    .warning-box {
        background: linear-gradient(135deg, #fef3c7, #fde68a);
        border: 2px solid #f59e0b;
        border-radius: 12px;
        padding: 16px;
        margin: 16px 0;
    }
    
    /* Telegram button */
    .telegram-btn {
        width: 100%;
        padding: 14px;
        border-radius: 30px;
        border: none;
        background: linear-gradient(135deg, #ec4899, #8b5cf6);
        color: white;
        font-size: 18px;
        font-weight: bold;
        cursor: pointer;
        text-align: center;
        text-decoration: none;
        display: block;
        margin: 12px 0;
    }
    
    /* Section title */
    .section-title {
        font-size: 18px;
        font-weight: bold;
        color: #1e293b;
        margin: 20px 0 12px 0;
        padding-bottom: 8px;
        border-bottom: 2px solid #e2e8f0;
    }
    
    /* Voice sample box */
    .voice-sample {
        border: 2px solid #fbbf24;
        border-radius: 8px;
        padding: 6px 12px;
        font-size: 12px;
        color: #92400e;
        text-align: center;
        margin-top: 4px;
    }
    
    /* Theme toggle */
    .theme-toggle {
        text-align: center;
        margin: 10px 0;
    }
    .theme-toggle a {
        display: inline-block;
        padding: 8px 20px;
        border-radius: 20px;
        background: #e2e8f0;
        color: #475569;
        text-decoration: none;
        font-size: 14px;
        cursor: pointer;
    }
</style>
""", unsafe_allow_html=True)

# --- Session State Initialization ---
def init_state():
    keys = ['selected_voice', 'selected_style', 'selected_emotion', 'audio_path', 'processing']
    for k in keys:
        if k not in st.session_state:
            st.session_state[k] = None
    if 'speed_val' not in st.session_state:
        st.session_state.speed_val = 0
    if 'pitch_val' not in st.session_state:
        st.session_state.pitch_val = 0
    if 'admin_logged_in' not in st.session_state:
        st.session_state.admin_logged_in = False
    if 'theme' not in st.session_state:
        st.session_state.theme = "light"

init_state()

# --- Helper Functions ---
def get_rate(speed_val, style_rate="0%"):
    """Calculate rate based on speed slider and style"""
    if style_rate and style_rate != "0%":
        base = int(style_rate.replace("%", "").replace("+", ""))
        return f"+{base + speed_val}%"
    return f"+{speed_val}%"

def get_pitch(pitch_val, style_pitch="0Hz"):
    """Calculate pitch based on pitch slider and style"""
    if style_pitch and style_pitch != "0Hz":
        base = int(style_pitch.replace("Hz", "").replace("+", "").replace("-", ""))
        if "-" in style_pitch:
            base = -base
        return f"+{base + pitch_val}Hz"
    return f"+{pitch_val}Hz"

async def generate_tts(text, voice, rate, pitch):
    """Generate TTS audio using Edge TTS"""
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    temp_file = tempfile.mktemp(suffix=".mp3")
    await communicate.save(temp_file)
    return temp_file

async def generate_tts_segments(text, voice, rate, pitch):
    """Generate TTS audio with multiple segments concatenated"""
    # Split text into segments by sentences
    import re
    parts = re.split(r'([။၊.!?;])', text)
    segments = []
    for i in range(0, len(parts)-1, 2):
        seg = (parts[i] + parts[i+1]).strip()
        if seg:
            segments.append(seg)
    if len(parts) % 2 != 0 and parts[-1].strip():
        segments.append(parts[-1].strip())
    
    if not segments:
        segments = [text]
    
    temp_files = []
    for seg in segments:
        if not seg.strip():
            continue
        temp_file = tempfile.mktemp(suffix=".mp3")
        try:
            communicate = edge_tts.Communicate(seg.strip(), voice, rate=rate, pitch=pitch)
            await communicate.save(temp_file)
            temp_files.append(temp_file)
        except Exception:
            continue
    
    if not temp_files:
        raise Exception("အသံဖိုင် ထုတ်လုပ်ခြင်း မအောင်မြင်ပါ။")
    
    # Concatenate all segments
    output_file = tempfile.mktemp(suffix=".mp3")
    list_file = tempfile.mktemp(suffix=".txt")
    with open(list_file, "w", encoding='utf-8') as f:
        for tf in temp_files:
            f.write(f"file '{os.path.abspath(tf)}'\n")
    
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", output_file],
        capture_output=True
    )
    
    # Cleanup temp files
    for tf in temp_files:
        if os.path.exists(tf):
            os.remove(tf)
    if os.path.exists(list_file):
        os.remove(list_file)
    
    return output_file

async def play_voice_preview(voice_id):
    """Generate a short preview audio for voice selection"""
    temp_file = tempfile.mktemp(suffix=".mp3")
    communicate = edge_tts.Communicate(PREVIEW_TEXT, voice_id, rate="+0%", pitch="+0Hz")
    await communicate.save(temp_file)
    return temp_file

def get_audio_duration(filepath):
    """Get audio file duration in seconds"""
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", filepath]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except:
        return 0

# --- RAM Monitor ---
def get_ram_usage():
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    return mem_info.rss / (1024 * 1024)  # MB

# --- UI Layout ---

# Header with Logo
col_logo, col_title = st.columns([1, 3])
with col_logo:
    st.markdown("""
    <div style="text-align: center;">
        <div style="width: 120px; height: 120px; border-radius: 50%; background: linear-gradient(135deg, #ec4899, #8b5cf6, #06b6d4); display: flex; align-items: center; justify-content: center; margin: 0 auto;">
            <span style="color: white; font-size: 48px; font-weight: bold;">Sai<br>Myanmar</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
with col_title:
    st.markdown("")
    st.markdown("")
    st.markdown("""
    <h1 style="text-align: center; color: #1e293b; margin-top: 20px;">စိုင်းမြန်မာ အသံပြောင်းစနစ် Pro</h1>
    """, unsafe_allow_html=True)

# Telegram Channel Button
st.markdown("""
<div style="text-align: center; margin: 10px 0;">
    <a href="https://t.me/saimyanmar" target="_blank" style="display: inline-block; padding: 10px 30px; border-radius: 25px; background: linear-gradient(135deg, #ec4899, #8b5cf6); color: white; text-decoration: none; font-size: 16px; font-weight: bold;">
        📢 စိုင်းမြန်မာ TELEGRAM CHANNEL ကို ဝင်ကြည့်ပါ
    </a>
</div>
""", unsafe_allow_html=True)

# Warning Box
st.markdown("""
<div class="warning-box">
    <p style="text-align: center; color: #92400e; margin: 0; font-weight: bold;">
        ⚠️ အရေးကြီး: အသိပေးချက် ⚠️
    </p>
    <p style="color: #78350f; margin: 8px 0 0 0; text-align: center;">
        ကျေးဇူးတင်၏ <b>Saimyanmar TTS Pro</b> ကို အသုံးပြုသော အရပ်ရပ်လူတိုင်း Server အသုံးပြုခွင့် ရရှိပါသည်။
        သို့သော် Server အသုံးပြုမှု အမြဲတမ်းရရှိရန် Telegram Channel ကို Join ထားပါ။
    </p>
</div>
""", unsafe_allow_html=True)

# Telegram Group Button
st.markdown("""
<div style="text-align: center;">
    <a href="https://t.me/saimyanmarttspromax" target="_blank" style="display: inline-block; padding: 14px 40px; border-radius: 30px; background: linear-gradient(135deg, #ec4899, #8b5cf6); color: white; text-decoration: none; font-size: 18px; font-weight: bold;">
        👉 Telegram Group သို့ ယခုပဲ ဝင်ထားပါ 👈
    </a>
</div>
""", unsafe_allow_html=True)

st.markdown("<hr>", unsafe_allow_html=True)

# --- Voice Selection ---
st.markdown('<p class="section-title">🎙️ အသံရွေးချယ်ပါ</p>', unsafe_allow_html=True)

# Main voices grid
voice_cols = st.columns(2)
selected_voice_name = st.session_state.selected_voice or list(VOICES.keys())[0]

for i, (voice_name, voice_id) in enumerate(VOICES.items()):
    col_idx = i % 2
    with voice_cols[col_idx]:
        is_selected = (selected_voice_name == voice_name)
        border_color = "#7c3aed" if is_selected else "#e0e0e0"
        bg_color = "#ede9fe" if is_selected else "white"
        
        st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 8px; 
                    border: 2px solid {border_color}; background: {bg_color}; cursor: pointer;">
            <div style="width: 32px; height: 32px; border-radius: 50%; background: #7c3aed; 
                        color: white; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                ▶
            </div>
            <div>
                <div style="font-weight: bold; font-size: 14px;">{voice_name.split(' ')[0]}</div>
                <div style="font-size: 12px; color: #64748b;">{voice_name.split(' ')[1] if len(voice_name.split(' ')) > 1 else ''}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button(voice_name, key=f"voice_{i}", use_container_width=True):
            st.session_state.selected_voice = voice_name
            st.rerun()

# --- Additional Voice Styles ---
st.markdown('<p class="section-title">🔊 အသံပုံစံများ</p>', unsafe_allow_html=True)

style_cols = st.columns(4)
selected_style = st.session_state.selected_style

for i, (style_name, style_info) in enumerate(VOICE_STYLES.items()):
    col_idx = i % 4
    with style_cols[col_idx]:
        is_selected = (selected_style == style_name)
        bg = "#fde68a" if is_selected else "white"
        border = "#f59e0b" if is_selected else "#e0e0e0"
        
        if st.button(style_name, key=f"style_{i}", use_container_width=True):
            if st.session_state.selected_style == style_name:
                st.session_state.selected_style = None
            else:
                st.session_state.selected_style = style_name
            st.rerun()

# --- Emotion Selection ---
st.markdown('<p class="section-title">🎭 စိတ်ခံစားမှု ရွေးချယ်ပါ</p>', unsafe_allow_html=True)

emotion_cols = st.columns(4)
selected_emotion = st.session_state.selected_emotion

for i, (emotion_name, emotion_info) in enumerate(EMOTIONS.items()):
    col_idx = i % 4
    with emotion_cols[col_idx]:
        is_selected = (selected_emotion == emotion_name)
        bg = "#cffafe" if is_selected else "white"
        border = "#06b6d4" if is_selected else "#e0e0e0"
        
        if st.button(emotion_name, key=f"emotion_{i}", use_container_width=True):
            if st.session_state.selected_emotion == emotion_name:
                st.session_state.selected_emotion = None
            else:
                st.session_state.selected_emotion = emotion_name
            st.rerun()

st.markdown("<hr>", unsafe_allow_html=True)

# --- Speed and Pitch Controls ---
st.markdown('<p class="section-title">⚡ အသံနှုန်း ညှိရန်</p>', unsafe_allow_html=True)

speed_col, pitch_col = st.columns(2)

with speed_col:
    st.markdown("**အသံနှုန်း (Speed)**")
    speed_val = st.slider("speed", -50, 50, 0, key="speed_slider", label_visibility="collapsed")
    st.session_state.speed_val = speed_val
    st.write(f"တန်ဖိုး: {speed_val}")

with pitch_col:
    st.markdown("**Pitch (အသံနိမ့်/မြင့်)**")
    pitch_val = st.slider("pitch", -50, 50, 0, key="pitch_slider", label_visibility="collapsed")
    st.session_state.pitch_val = pitch_val
    st.write(f"တန်ဖိုး: {pitch_val}")

st.markdown("<hr>", unsafe_allow_html=True)

# --- Text Input ---
st.markdown('<p class="section-title">📝 စာသားရိုက်ထည့်ပါ</p>', unsafe_allow_html=True)

text_input = st.text_area(
    "ဤနေရာတွင် မြန်မာစာများ ရိုက်ထည့်ပါ သို့မဟုတ် ကူးထည့်ပါ...",
    height=200,
    key="tts_text",
    placeholder="ဤနေရာတွင် မြန်မာစာများ ရိုက်ထည့်ပါ သို့မဟုတ် ကူးထည့်ပါ..."
)

# Clear and Paste buttons
clear_col, paste_col = st.columns(2)
with clear_col:
    if st.button("🗑️ ဖျက်မည်", use_container_width=True):
        st.session_state.tts_text = ""
        st.rerun()
with paste_col:
    if st.button("📋 ကူးထည့်မည်", use_container_width=True):
        st.info("Clipboard မှ ကူးထည့်ရန် Ctrl+V နှိပ်ပါ")

st.markdown("<hr>", unsafe_allow_html=True)

# --- Generate Button ---
if st.button("🔊 အသံထုတ်ယူမည်", type="primary", use_container_width=True):
    if not text_input or text_input.strip() == "":
        st.error("❌ စာသား အရင်ရိုက်ထည့်ပါ။")
    else:
        try:
            with st.spinner("🔊 အသံဖိုင် ထုတ်လုပ်နေပါသည်..."):
                # Determine voice and parameters
                voice_name = st.session_state.selected_voice or list(VOICES.keys())[0]
                base_voice = VOICES.get(voice_name, "my-MM-ThihaNeural")
                
                rate = f"+{st.session_state.speed_val}%"
                pitch = f"+{st.session_state.pitch_val}Hz"
                
                # Apply style overrides
                if st.session_state.selected_style:
                    style_info = VOICE_STYLES.get(st.session_state.selected_style)
                    if style_info:
                        base_voice = style_info["voice"]
                        if style_info["rate"] != "0%":
                            base_rate_val = int(style_info["rate"].replace("%", "").replace("+", ""))
                            rate = f"+{base_rate_val + st.session_state.speed_val}%"
                        if style_info["pitch"] != "0Hz":
                            base_pitch_val = int(style_info["pitch"].replace("Hz", "").replace("+", "").replace("-", ""))
                            if "-" in style_info["pitch"]:
                                base_pitch_val = -base_pitch_val
                            pitch = f"+{base_pitch_val + st.session_state.pitch_val}Hz"
                
                # Apply emotion overrides
                if st.session_state.selected_emotion:
                    emotion_info = EMOTIONS.get(st.session_state.selected_emotion)
                    if emotion_info:
                        emo_rate = int(emotion_info["rate"].replace("%", "").replace("+", ""))
                        emo_pitch = int(emotion_info["pitch"].replace("Hz", "").replace("+", ""))
                        # Combine with existing values
                        current_rate = int(rate.replace("%", "").replace("+", ""))
                        current_pitch = int(pitch.replace("Hz", "").replace("+", ""))
                        rate = f"+{current_rate + emo_rate}%"
                        pitch = f"+{current_pitch + emo_pitch}Hz"
                
                # Generate audio
                audio_path = asyncio.run(generate_tts_segments(
                    text_input, base_voice, rate, pitch
                ))
                
                st.session_state.audio_path = audio_path
                st.session_state.processing = True
                st.success("✅ အသံဖိုင် ထုတ်လုပ်ပြီးပါပြီ!")
                st.rerun()
                
        except Exception as e:
            st.error(f"❌ အမှားအယွင်း: {str(e)}")

# --- Audio Player ---
if st.session_state.audio_path and os.path.exists(st.session_state.audio_path):
    st.markdown("---")
    st.markdown('<p class="section-title">🎵 ထုတ်လုပ်ပြီးသော အသံဖိုင်</p>', unsafe_allow_html=True)
    
    st.audio(st.session_state.audio_path)
    
    # Duration info
    dur = get_audio_duration(st.session_state.audio_path)
    st.info(f"⏱️ အသံကြာချိန်: {dur:.1f} စက္ကန့်")
    
    # Download button
    with open(st.session_state.audio_path, "rb") as f:
        st.download_button(
            "📥 အသံဖိုင်ကို သိမ်းဆည်းရန်",
            f,
            "saimyanmar_tts.mp3",
            "audio/mp3"
        )

# --- RAM Monitor (Bottom) ---
st.markdown("---")
ram_used = get_ram_usage()
ram_limit = 1024
ram_pct = min(ram_used / ram_limit, 1.0)

ram_col1, ram_col2 = st.columns([3, 1])
ram_col1.progress(ram_pct)
ram_col2.write(f"RAM: {ram_used:.0f}/{ram_limit}MB")

if ram_used > 800:
    st.warning("⚠️ RAM သုံးစွဲမှု များနေပါသည်။")

# --- Admin Password Section ---
st.markdown("<hr>", unsafe_allow_html=True)
st.markdown("### 🔐 Admin လျှို့ဝှက်ခန်း")
st.markdown("အသုံးပြုသူ အရေအတွက်ကို ကြည့်ရန် Password ထည့်ပါ။")

admin_password = st.text_input("Password", type="password", key="admin_pass", label_visibility="visible")

if admin_password == "kozin3694":
    st.success("✅ Admin ဝင်ရောက်ပြီးပါပြီ")
    st.session_state.admin_logged_in = True
    
    if st.session_state.admin_logged_in:
        st.info(f"📊 လက်ရှိ RAM အသုံးပြုမှု: {get_ram_usage():.0f}MB")
        
        if st.button("🧹 RAM ရှင်းထုတ်ရန်"):
            st.cache_data.clear()
            gc.collect()
            st.success("RAM ရှင်းလင်းပြီးပါပြီ")
            st.rerun()
        
        if st.button("🗑️ Data အားလုံးဖျက်ရန်"):
            preserve = ['admin_logged_in']
            for k in list(st.session_state.keys()):
                if k not in preserve:
                    del st.session_state[k]
            st.cache_data.clear()
            gc.collect()
            st.rerun()

# --- Footer ---
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #64748b; padding: 20px 0;">
    <p>Created with ❤️ by SaiMyanmar TTS Pro</p>
    <p>📢 <a href="https://t.me/saimyanmarttspromax" target="_blank">Telegram Channel</a> | 
       <a href="https://t.me/saimyanmarttspromax" target="_blank">Join Group</a></p>
</div>
""", unsafe_allow_html=True)

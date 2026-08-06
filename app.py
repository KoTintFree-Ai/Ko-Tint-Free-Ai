import streamlit as st
import os
import base64
import time
import tempfile
import requests
import asyncio
import edge_tts
import subprocess
import re
import json
import shutil
import numpy as np

# --- CONFIGURATION ---
API_VERSIONS = ["v1beta", "v1"]
DEFAULT_MODELS = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-pro"]

# Advanced Networking: Force IPv4 for better stability on Streamlit Cloud
import socket
orig_getaddrinfo = socket.getaddrinfo
def filtered_getaddrinfo(*args, **kwargs):
    res = orig_getaddrinfo(*args, **kwargs)
    return [r for r in res if r[0] == socket.AF_INET]
socket.getaddrinfo = filtered_getaddrinfo

# Standard Headers
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(
    page_title="Movie Recap AI",
    page_icon="🎬",
    layout="centered",
    initial_sidebar_state="expanded"
)

# --- CSS ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display:none;}
    [data-testid="stSidebarNav"] {display: none;}
    .stButton>button {width: 100%;}
    </style>
    """, unsafe_allow_html=True)

# --- Session State Initialization ---
def init_state():
    # Define keys and their default values
    defaults = {
        'audio_path': None,
        'srt_data': None,
        'plain_text': None,
        'word_count': 0,
        'last_uploaded': None,
        'processing_done': False,
        'valid_keys_info': {},
        'active_key': None,
        'bulk_msg': "",
        'test_results': [],
        'v_speed': 55,
        'v_pitch': 50,
        'target_min': 2,
        'target_sec': 30,
        'bulk_key_input': ""
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
            
    # Initialize keys 1-5
    for i in range(1, 6):
        key_name = f'key_{i}'
        if key_name not in st.session_state:
            st.session_state[key_name] = ""

# --- PERSISTENT KEY STORAGE ---
KEYS_FILE = os.path.join(SCRIPT_DIR, "saved_keys.json")

def save_keys_to_file():
    keys_data = {f'key_{i}': st.session_state[f'key_{i}'] for i in range(1, 6) if st.session_state[f'key_{i}']}
    if keys_data:
        try:
            with open(KEYS_FILE, 'w') as f:
                json.dump(keys_data, f)
        except: pass

def load_keys_from_file():
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, 'r') as f:
                keys_data = json.load(f)
            for k, v in keys_data.items():
                if k in st.session_state and not st.session_state[k]:
                    st.session_state[k] = v
        except: pass

init_state()
load_keys_from_file()

# --- HELPER: SLIDER WITH PLUS/MINUS ---
def plus_minus_slider(label, key, min_val, max_val, step=1):
    st.write(f"**{label}**")
    def on_btn(delta):
        st.session_state[key] = int(np.clip(st.session_state[key] + delta, min_val, max_val))
    
    col1, col2, col3 = st.columns([1, 4, 1])
    with col1: st.button("➖", key=f"btn_min_{key}", on_click=on_btn, args=(-step,))
    with col2: st.slider(label, min_val, max_val, step=step, key=key, label_visibility="collapsed")
    with col3: st.button("➕", key=f"btn_pls_{key}", on_click=on_btn, args=(step,))
    return st.session_state[key]

# --- UTILITIES ---
def get_dur(p):
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", p]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return float(r.stdout.strip())
    except: return 0

def fmt_srt(s):
    m = int((s % 1) * 1000)
    return f"{time.strftime('%H:%M:%S', time.gmtime(s))},{m:03d}"

def clean_text_for_tts(text):
    """Extremely aggressive cleaning to remove ALL numbers and SRT metadata."""
    # 1. Remove markdown code blocks
    text = re.sub(r'```srt?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```', '', text).strip()
    # 2. Remove SRT timestamps
    text = re.sub(r'\d{1,2}:\d{1,2}:\d{1,2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{1,2}:\d{1,2}[,.]\d{1,3}', ' ', text)
    # 3. Remove ALL digits (English 0-9 and Myanmar ၀-၉)
    text = re.sub(r'[0-9\u1040-\u1049]+', ' ', text)
    # 4. Remove standalone symbols and labels
    text = re.sub(r'(?i)^(narration|recap|script|translation|speaker|intro|outro|scene):', ' ', text, flags=re.MULTILINE)
    # 5. Remove common filler phrases
    fillers = ["ပရိတ်သတ်ကြီးရေ", "မင်္ဂလာပါ", "ကြိုဆိုပါတယ်", "နိဒါန်း", "နိဂုံး", "ဇာတ်လမ်းအစ", "ဇာတ်လမ်းအဆုံး"]
    for f in fillers: text = text.replace(f, " ")
    # 6. Final cleanup
    text = re.sub(r'[။၊\.!?;:,\(\)\[\]\{\}\*]+', ' ', text)
    return " ".join(text.split()).strip()

async def gen_audio_srt(raw_text, out_p, vid, spd, ptc, target=0):
    rate = f"+{int((spd-55)*2)}%" if spd>=55 else f"{int((spd-55)*2)}%"
    pitch = f"+{int((ptc-50)*2)}Hz" if ptc>=50 else f"{int((ptc-50)*2)}Hz"
    clean_narration = clean_text_for_tts(raw_text)
    if not clean_narration: raise Exception("ဘာသာပြန်စာသား မတွေ့ရှိပါ။")

    chunks = []
    current_chunk = ""
    for word in clean_narration.split():
        if len(current_chunk) + len(word) < 150: current_chunk += word + " "
        else:
            chunks.append(current_chunk.strip())
            current_chunk = word + " "
    if current_chunk: chunks.append(current_chunk.strip())

    temp_files = []; cur_t = 0.0; srt_blocks = []
    for txt in chunks:
        p = tempfile.mktemp(suffix=".mp3")
        try:
            communicate = edge_tts.Communicate(txt, vid, rate=rate, pitch=pitch)
            await communicate.save(p)
            d = get_dur(p)
            if d > 0:
                srt_blocks.append(f"{len(srt_blocks)+1}\n{fmt_srt(cur_t)} --> {fmt_srt(cur_t+d)}\n{txt[:30]}...\n\n")
                temp_files.append(p); cur_t += d
        except: continue

    if not temp_files: raise Exception("အသံဖိုင် ထုတ်လုပ်ခြင်း မအောင်မြင်ပါ။")
    raw_mp3 = tempfile.mktemp(suffix=".mp3")
    l_p = tempfile.mktemp(suffix=".txt")
    with open(l_p, "w", encoding='utf-8') as f:
        f.write("\n".join([f"file '{os.path.abspath(p)}'" for p in temp_files]))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", l_p, "-c", "copy", raw_mp3], capture_output=True)
    
    total_dur = get_dur(raw_mp3)
    if target > 0 and total_dur > 0:
        factor = np.clip(total_dur / target, 0.7, 2.0)
        subprocess.run(["ffmpeg", "-y", "-i", raw_mp3, "-filter:a", f"atempo={factor}", out_p], capture_output=True)
    else: shutil.copy(raw_mp3, out_p)
    
    if os.path.exists(raw_mp3): os.remove(raw_mp3)
    return "".join(srt_blocks), get_dur(out_p), clean_narration

# --- SIDEBAR ---
with st.sidebar:
    st.subheader("🔑 Gemini API Keys")
    
    # Render key inputs using session state values
    for i in range(1, 6):
        if i == 1 or st.session_state.get('show_more_keys'):
            st.session_state[f'key_{i}'] = st.text_input(f"Key {i}", type="password", value=st.session_state[f'key_{i}'])
    
    if st.button("🔽 ကျန် Keys များ ဖော်ပြရန်/ဝှက်ရန်"):
        st.session_state['show_more_keys'] = not st.session_state.get('show_more_keys', False)
        st.rerun()

    st.markdown("---")
    bulk_input = st.text_area("Key များအားလုံးကို Paste ချပါ", height=80, key="bulk_key_widget")
    
    if st.button("📋 Auto-Fill Keys"):
        if bulk_input:
            found = list(dict.fromkeys(re.findall(r'(AIza[0-9A-Za-z-_]{30,}|AQ\.[0-9A-Za-z-_]{30,})', bulk_input)))
            for i, k in enumerate(found[:5]):
                st.session_state[f'key_{i+1}'] = k
            save_keys_to_file()
            # The widget itself is cleared by not providing a value or clearing state
            st.rerun()

    st.markdown("---")
    st.subheader("🔊 အသံ ဆက်တင်များ")
    v_choice = st.selectbox("အသံရွေးချယ်ပါ", ["သီဟ (အမျိုးသားသံ)", "နီလာ (အမျိုးသမီးသံ)"])
    v_id = "my-MM-ThihaNeural" if "သီဟ" in v_choice else "my-MM-NilarNeural"
    v_speed = plus_minus_slider("အသံနှုန်း", "v_speed", 1, 100, 1)
    v_pitch = plus_minus_slider("Pitch", "v_pitch", 1, 100, 1)

    st.markdown("---")
    st.subheader("⏱️ အချိန် ထိန်းချုပ်ရန်")
    fit_dur = st.toggle("သတ်မှတ်အချိန်အတွင်း အပြီးပြောရန်", value=st.session_state.target_sec > 0)
    target_sec = 0
    if fit_dur:
        tm = plus_minus_slider("မိနစ်", "target_min", 0, 60, 1)
        ts = plus_minus_slider("စက္ကန့်", "target_sec", 0, 59, 1)
        target_sec = (tm * 60) + ts

# --- MAIN AREA ---
st.title("🎬 Movie Recap AI")
up = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if up:
    tp = os.path.join(tempfile.gettempdir(), f"input_{hash(up.name)}." + up.name.split(".")[-1])
    with open(tp, "wb") as f: f.write(up.getbuffer())

    api_keys = [st.session_state[f'key_{i}'] for i in range(1, 6) if st.session_state[f'key_{i}'].strip()]
    if not api_keys: st.warning("⚠️ Sidebar တွင် API Key ထည့်ပေးပါ")
    elif st.button("🚀 စတင်လုပ်ဆောင်ရန်"):
        prg = st.progress(0); stt = st.empty()
        try:
            stt.text("📊 အဆင့် ၁: အသံဖိုင်ကို ပြင်ဆင်နေပါသည်...")
            prg.progress(10)
            ag = tempfile.mktemp(suffix=".mp3")
            subprocess.run(["ffmpeg", "-y", "-i", tp, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], capture_output=True)

            stt.text("⏳ အဆင့် ၂: ဘာသာပြန်နေပါသည်...")
            prg.progress(30)
            prm = "Provide a dramatic Myanmar Movie Recap. RULES: No fillers, no numbers, no labels. Output SRT format only."
            with open(ag, 'rb') as f: b64 = base64.b64encode(f.read()).decode()
            cont = [{"role":"user","parts":[{"text":prm},{"inline_data":{"mime_type":"audio/mpeg","data":b64}}]}]

            srt_res = None
            for k in api_keys:
                try:
                    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={k}", json={"contents":cont}, timeout=180)
                    if r.status_code == 200:
                        srt_res = r.json()['candidates'][0]['content']['parts'][0]['text']
                        if srt_res: break
                except: continue
            
            if not srt_res: raise Exception("ဘာသာပြန်ခြင်း မအောင်မြင်ပါ။")

            stt.text("🔊 အဆင့် ၃: အသံဖိုင် ထုတ်လုပ်နေပါသည်...")
            prg.progress(60)
            ao = os.path.join(tempfile.gettempdir(), f"audio_{int(time.time())}.mp3")
            st.session_state.srt_data, _, st.session_state.plain_text = asyncio.run(gen_audio_srt(srt_res, ao, v_id, v_speed, v_pitch, target_sec if fit_dur else 0))
            st.session_state.word_count = len(re.findall(r'[\u1000-\u102A\u103F\u1040-\u1049][\u102B-\u103E\u1037\u1038\u1039\u103A]*', st.session_state.plain_text))
            st.session_state.audio_path = ao
            prg.progress(100); stt.text("✅ ပြီးဆုံးပါပြီ!"); st.balloons()
            st.session_state.processing_done = True
        except Exception as e: st.error(f"❌ အမှား: {str(e)}")

if st.session_state.get('processing_done'):
    st.markdown("---")
    if st.session_state.audio_path:
        st.audio(st.session_state.audio_path)
        with open(st.session_state.audio_path, "rb") as f: st.download_button("📥 MP3 ဒေါင်းလုဒ်", f, "recap.mp3", "audio/mp3")
    st.metric("မြန်မာစာလုံးရေ", f"{st.session_state.word_count}")
    with st.expander("📝 စာသားသက်သက် ကြည့်ရန်", expanded=True):
        st.text_area("Plain Text", st.session_state.plain_text, height=300)
    if st.button("🔄 ပြန်လုပ်ရန်"):
        st.session_state.processing_done = False; st.rerun()

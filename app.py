import streamlit as st
import os
import base64
import time
import tempfile
import requests
import asyncio
import edge_tts
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import re
import shutil
import psutil
import gc

# --- CONFIGURATION ---
API_VERSIONS = ["v1beta", "v1"]
DEFAULT_MODELS = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-pro"]

# Advanced Networking: Force IPv4 for better stability on Streamlit Cloud
import socket
import urllib3
orig_getaddrinfo = socket.getaddrinfo
def filtered_getaddrinfo(*args, **kwargs):
    res = orig_getaddrinfo(*args, **kwargs)
    return [r for r in res if r[0] == socket.AF_INET]
socket.getaddrinfo = filtered_getaddrinfo

# Standard Headers to mimic a browser
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# Get the directory where this script is located (for font file path)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(SCRIPT_DIR, "Pyidaungsu.ttf")

st.set_page_config(
    page_title="Movie Recap AI Pro V8.2",
    page_icon="🎬",
    layout="centered",
    initial_sidebar_state="expanded"
)

# --- CSS: CUSTOM STYLING ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display:none;}
    [data-testid="stSidebarNav"] {display: none;}
    .stButton>button {width: 100%;}
    </style>
    """, unsafe_allow_html=True)

# Session State Initialization
def init_state():
    keys = ['myanmar_text', 'audio_path', 'srt_data', 'video_path', 'base_frame', 'last_uploaded', 'processing_done', 'valid_keys_info', 'active_key', 'valid_grok_info', 'active_grok_key', 'bulk_msg', 'test_results']
    for k in keys:
        if k not in st.session_state: st.session_state[k] = None
    for i in range(1, 6):
        if f'key_{i}' not in st.session_state: st.session_state[f'key_{i}'] = ""
        if f'grok_key_{i}' not in st.session_state: st.session_state[f'grok_key_{i}'] = ""
    
    if st.session_state.processing_done is None: st.session_state.processing_done = False
    if st.session_state.bulk_msg is None: st.session_state.bulk_msg = ""
    if st.session_state.test_results is None: st.session_state.test_results = []
    if st.session_state.valid_keys_info is None: st.session_state.valid_keys_info = {}
    if st.session_state.valid_grok_info is None: st.session_state.valid_grok_info = {}
    if 'do_test_keys' not in st.session_state: st.session_state.do_test_keys = False
    if 'blur_y_pos' not in st.session_state: st.session_state.blur_y_pos = 85
    if 'blur_h_size' not in st.session_state: st.session_state.blur_h_size = 6
    if 'sub_y_pos' not in st.session_state: st.session_state.sub_y_pos = 85
    if 'font_size' not in st.session_state: st.session_state.font_size = 22
    if 'target_min' not in st.session_state: st.session_state.target_min = 2
    if 'target_sec' not in st.session_state: st.session_state.target_sec = 30

def auto_fill_callback():
    if 'bulk_key_input' in st.session_state and st.session_state.bulk_key_input:
        text = st.session_state.bulk_key_input
        
        # Enhanced Regex: Capture Gemini (AIza... or AQ...) and Grok (gsk_...)
        # Handle cases where keys might be followed by Burmese punctuation or other separators
        gemini_found = re.findall(r'(AIza[0-9A-Za-z-_]{30,}|AQ\.[0-9A-Za-z-_]{30,})', text)
        grok_found = re.findall(r'(gsk_[0-9A-Za-z]{30,})', text)
        
        # Clean up any trailing punctuation that might be caught
        gemini_found = [k.strip().strip('။၊.()[]{}<>:;*') for k in gemini_found]
        grok_found = [k.strip().strip('။၊.()[]{}<>:;*') for k in grok_found]
        
        gemini_found = list(dict.fromkeys(gemini_found))
        grok_found = list(dict.fromkeys(grok_found))
        
        msg = []
        if gemini_found:
            for i in range(min(5, len(gemini_found))):
                st.session_state[f'key_{i+1}'] = gemini_found[i]
                st.session_state[f'w_key_{i+1}'] = gemini_found[i]
            msg.append(f"✅ Gemini Keys {len(gemini_found[:5])} ခု")
        
        if grok_found:
            for i in range(min(5, len(grok_found))):
                st.session_state[f'grok_key_{i+1}'] = grok_found[i]
                st.session_state[f'w_grok_key_{i+1}'] = grok_found[i]
            msg.append(f"✅ Grok Keys {len(grok_found[:5])} ခု")
        
        if msg:
            st.session_state.bulk_msg = " ဖြည့်ပြီးပါပြီ: " + ", ".join(msg)
        else:
            st.session_state.bulk_msg = "⚠️ API Key ရှာမတွေ့ပါ။ (AIza..., AQ... သို့မဟုတ် gsk_...)"
        
        st.session_state.bulk_key_input = ""
        # Save keys immediately after auto-fill
        save_keys_to_file()

# --- PERSISTENT KEY STORAGE ---
KEYS_FILE = os.path.join(SCRIPT_DIR, "saved_keys.json")

def save_keys_to_file():
    """Save API keys to a JSON file for persistence across page refreshes."""
    keys_data = {}
    for i in range(1, 6):
        k = st.session_state.get(f'key_{i}', "")
        gk = st.session_state.get(f'grok_key_{i}', "")
        if k: keys_data[f'key_{i}'] = k
        if gk: keys_data[f'grok_key_{i}'] = gk
    if keys_data:
        try:
            with open(KEYS_FILE, 'w') as f:
                json.dump(keys_data, f)
        except Exception:
            pass

def load_keys_from_file():
    """Load API keys from file if session state is empty."""
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, 'r') as f:
                keys_data = json.load(f)
            for k, v in keys_data.items():
                if k in st.session_state and not st.session_state.get(k):
                    st.session_state[k] = v
                # Also set the widget keys so text inputs show the values
                if k == 'key_1': st.session_state['w_key_1'] = v
                if k == 'key_2': st.session_state['w_key_2'] = v
                if k == 'key_3': st.session_state['w_key_3'] = v
                if k == 'key_4': st.session_state['w_key_4'] = v
                if k == 'key_5': st.session_state['w_key_5'] = v
                if k == 'grok_key_1': st.session_state['w_grok_key_1'] = v
                if k == 'grok_key_2': st.session_state['w_grok_key_2'] = v
                if k == 'grok_key_3': st.session_state['w_grok_key_3'] = v
                if k == 'grok_key_4': st.session_state['w_grok_key_4'] = v
                if k == 'grok_key_5': st.session_state['w_grok_key_5'] = v
        except Exception:
            pass

# Need json import for key persistence
import json

init_state()

# Load saved keys from file if not already in session state
load_keys_from_file()

st.title("🎬 Movie Recap AI Pro V8.2")
st.markdown("အင်္ဂလိပ် ဗီဒီယိုမှ မြန်မာ Movie Recap ပြုလုပ်ပေးသော AI (Auto Blur & Sync)")

# --- HELPER: SLIDER WITH PLUS/MINUS (V7.4) ---
def plus_minus_slider(label, key, min_val, max_val, step=1):
    st.write(f"**{label}**")
    if key not in st.session_state: st.session_state[key] = min_val
    
    def on_btn(delta):
        st.session_state[key] = int(np.clip(st.session_state[key] + delta, min_val, max_val))
    
    col1, col2, col3 = st.columns([1, 4, 1])
    with col1: st.button("➖", key=f"btn_min_{key}", on_click=on_btn, args=(-step,))
    with col2: st.slider(label, min_val, max_val, step=step, key=key, label_visibility="collapsed")
    with col3: st.button("➕", key=f"btn_pls_{key}", on_click=on_btn, args=(step,))
    return st.session_state[key]

# --- ERROR TRANSLATOR ---
def translate_error(err_msg, status_code=None):
    err_msg = str(err_msg).lower()
    if "api_key_invalid" in err_msg or "invalid api key" in err_msg or status_code == 403:
        return "API Key မမှန်ကန်ပါ။ (Key ကို သေချာပြန်စစ်ပြီး ကူးထည့်ပေးပါ)"
    if "quota" in err_msg or "429" in err_msg or status_code == 429:
        return "API Key အသုံးပြုမှု ပမာဏ ပြည့်သွားပါပြီ။ (ခဏစောင့်ပါ သို့မဟုတ် Key အသစ်ပြောင်းသုံးပါ)"
    if "location" in err_msg or "not supported" in err_msg:
        return "သင်၏ ဒေသ (Region) တွင် ဤ API ကို ပိတ်ထားပါသည်။ (VPN သုံးရန် လိုအပ်ပါသည်)"
    if "404" in err_msg or status_code == 404:
        return "API URL သို့မဟုတ် Model အမည်ကို ရှာမတွေ့ပါ။ (URL လွဲချော်နေပါသည်)"
    if "safety" in err_msg or "blocked" in err_msg:
        return "မူပိုင်ခွင့် သို့မဟုတ် လုံခြုံရေး စည်းကမ်းချက်များကြောင့် Google မှ ဘာသာပြန်ရန် ငြင်းဆိုလိုက်ပါသည်။"
    return f"အမှားအယွင်းတစ်ခု ဖြစ်ပေါ်နေပါသည်။ ({err_msg})"

# --- GEMINI VISION AUTO DETECT SUBTITLE AREA ---
def auto_detect_subtitle_area(frame_bytes, api_keys=None, grok_keys=None):
    """Use AI Vision to accurately detect subtitle text area in video frame.
    Priority: Gemini Vision (real vision) > NumPy fallback > Groq (text-only, unreliable for vision).
    Groq API vision models are DEPRECATED, so Groq is NOT used for subtitle detection.
    Groq is reserved for translation only."""
    
    # === PRIORITY 1: Gemini Vision (best - can actually see the image) ===
    if api_keys:
        try:
            for k in api_keys:
                info = st.session_state.valid_keys_info.get(k)
                versions = [info['version']] if info else API_VERSIONS
                models = info['models'] if info else DEFAULT_MODELS
                models = sorted(models, key=lambda x: 0 if 'flash' in x.lower() else 1)
                
                for ver in versions:
                    for m in models:
                        if 'flash' not in m.lower() and 'pro' not in m.lower():
                            continue
                        try:
                            b64 = base64.b64encode(frame_bytes).decode()
                            prompt = """ULTRA-TIGHT SUBTITLE DETECTION - EXTREME MODE

You are a pixel-level subtitle detector. Your job is to find the ABSOLUTE MINIMUM bounding box that covers ONLY the subtitle text characters - NOT the background, NOT any padding, NOT any spacing.

WHAT TO DETECT:
- Look for subtitle/caption text overlaid ON TOP of the video
- This is text that appears at the bottom of the video (usually white/yellow colored)
- It is NOT part of the original video content (not scene text, not credits, not watermark)

ULTRA-TIGHT MEASUREMENT RULES:
1. Find the EXACT top pixel of the FIRST text character (not the background box above it)
2. Find the EXACT bottom pixel of the LAST text character (not the background box below it)
3. The HEIGHT must cover ONLY from top-of-first-letter to bottom-of-last-letter
4. ZERO padding above or below the text - if you add even 1 pixel of empty space, it is WRONG
5. If the text has a dark/black background box behind it, IGNORE the box - measure ONLY the letters

CALCULATION:
- Y_PERCENTAGE = (top pixel of first letter / image height) x 100
- HEIGHT_PERCENTAGE = ((bottom pixel - top pixel) / image height) x 100

EXAMPLES (for 1920x1080 video):
- Letters from pixel 870 to 905: Y=80.6, H=3.2
- Letters from pixel 950 to 978: Y=88.0, H=2.6
- Letters from pixel 940 to 970: Y=87.0, H=2.8

WRONG EXAMPLES (too big):
- Including dark background box: WRONG
- Adding 2-3 pixels padding above text: WRONG
- Height more than 5% of image: PROBABLY WRONG

FINAL INSTRUCTION:
Reply with EXACTLY two numbers: Y_PERCENTAGE HEIGHT_PERCENTAGE
The HEIGHT should be between 1.5 and 5.0 (for standard subtitles)
If no subtitle is visible, reply: 85 10

REMEMBER: TIGHTEST possible. Only touch the text pixels. Zero padding."""
                            
                            cont = [{"role":"user","parts":[
                                {"text": prompt},
                                {"inline_data":{"mime_type":"image/jpeg","data":b64}}
                            ]}]
                            
                            url = f"https://generativelanguage.googleapis.com/{ver}/models/{m}:generateContent?key={k}"
                            r = requests.post(url, json={"contents": cont, "generationConfig": {"temperature": 0.1}}, timeout=30)
                            
                            if r.status_code == 200:
                                data = r.json()
                                if 'candidates' in data and data['candidates'][0]['content']['parts']:
                                    result = data['candidates'][0]['content']['parts'][0]['text'].strip()
                                    parts = result.split()
                                    if len(parts) >= 2:
                                        blur_y = float(parts[0])
                                        blur_h = float(parts[1])
                                        # Aggressive Shrink Logic: Reduce detected height by 30% to ensure ultra-tightness
                                        shrink = blur_h * 0.30
                                        blur_y = blur_y + (shrink / 2)
                                        blur_h = blur_h - shrink
                                        
                                        blur_y = np.clip(blur_y, 50, 98)
                                        blur_h = np.clip(blur_h, 1.2, 8.0)
                                        st.session_state.active_key = k
                                        return blur_y, blur_h
                            elif r.status_code == 404:
                                continue  # try next model
                            else:
                                continue
                        except Exception:
                            continue
                    # If flash model succeeded, break
                    break
                # If any key succeeded, break
                if st.session_state.active_key:
                    break
        except Exception as e:
            st.warning(f"Gemini Vision error: {str(e)}")
    
    # Fallback: NumPy-based detection (simplified)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as bf:
            bf.write(frame_bytes); tf = bf.name
        img = Image.open(tf).convert('L')
        w, h = img.size
        arr = np.array(img)
        
        # Edge detection on bottom 60% (more generous)
        bottom_start = int(h * 0.40)
        bottom_arr = arr[bottom_start:, :]
        
        # Use horizontal gradient for edge detection
        diff = np.abs(bottom_arr[:, 1:] - bottom_arr[:, :-1])
        row_edge = np.sum(diff, axis=1)
        
        # Filter out pure black rows
        row_brightness = np.mean(bottom_arr, axis=1)
        is_active = row_brightness > 15
        
        # Score = edges * active
        score = row_edge * is_active.astype(float)
        
        if np.max(score) > 5:
            text_rows = np.where(score > np.percentile(score[score > 0], 50) if np.any(score > 0) else 10)[0]
            if len(text_rows) >= 2:
                # Extreme-tight padding for fallback
                blur_y = float((bottom_start + text_rows[0] + 1.5) / h * 100)
                blur_h = float((text_rows[-1] - text_rows[0] - 1) / h * 100)
                blur_y = np.clip(blur_y, 50, 98)
                blur_h = np.clip(blur_h, 1.0, 7.0)
                os.remove(tf)
                return blur_y, blur_h
        
        os.remove(tf)
    except Exception as e:
        st.warning(f"Fallback detect error: {str(e)}")
    
    return 78.0, 8.0

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ ဆက်တင်များ")
    
    # RAM Monitor
    st.subheader("🖥️ RAM စောင့်ကြည့်ရန်")
    def get_ram_usage():
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        return mem_info.rss / (1024 * 1024)  # MB

    ram_used = get_ram_usage()
    ram_limit = 1024 
    ram_pct = min(ram_used / ram_limit, 1.0)
    
    col_r1, col_r2 = st.columns([2, 1])
    col_r1.progress(ram_pct)
    col_r2.write(f"{ram_used:.0f}/{ram_limit}MB")
    
    if ram_used > 800:
        st.warning("⚠️ RAM သုံးစွဲမှု များနေပါသည်။ (Limit: 1024MB)")
    if ram_used > 950:
        st.error("🚨 RAM ပြည့်ခါနီးနေပါပြီ! App Crash ဖြစ်နိုင်ပါသည်။")
    
    if st.button("🧹 RAM ရှင်းထုတ်ရန်"):
        # Explicitly preserve keys in session state before clearing cache
        keys_to_keep = {f'key_{i}': st.session_state.get(f'key_{i}', "") for i in range(1, 6)}
        for i in range(1, 6):
            keys_to_keep[f'grok_key_{i}'] = st.session_state.get(f'grok_key_{i}', "")
        keys_to_keep['valid_keys_info'] = st.session_state.get('valid_keys_info', {})
        keys_to_keep['active_key'] = st.session_state.get('active_key', None)
        keys_to_keep['valid_grok_info'] = st.session_state.get('valid_grok_info', {})
        keys_to_keep['active_grok_key'] = st.session_state.get('active_grok_key', None)
        
        st.cache_data.clear()
        
        # Restore preserved keys
        for k, v in keys_to_keep.items():
            st.session_state[k] = v
            
        gc.collect()
        st.success("RAM ရှင်းလင်းပြီးပါပြီ (Keys များကို ထိန်းသိမ်းထားပါသည်)")
    
    if st.button("🗑️ Data အားလုံးဖျက်ရန် (Keys မပါ)"):
        preserve = [f'key_{i}' for i in range(1, 6)] + [f'grok_key_{i}' for i in range(1, 6)] + ['valid_keys_info', 'active_key', 'valid_grok_info', 'active_grok_key', 'target_min', 'target_sec', 'blur_y_pos', 'blur_h_size', 'sub_y_pos', 'font_size', 'v_speed', 'v_pitch']
        for k in list(st.session_state.keys()):
            if k not in preserve:
                del st.session_state[k]
        st.cache_data.clear()
        gc.collect()
        st.rerun()
    
    st.markdown("---")
    st.subheader("🪄 Smart Auto-Fill Keys")
    st.text_area("Key များအားလုံးကို ဤနေရာတွင် Paste ချပါ", placeholder="ဥပမာ- ၁။ AIza... ၂။ gsk_... စသည်ဖြင့် အပိုစာသားများပါလျှင်လည်း ရပါသည်", height=100, key="bulk_key_input")
    st.button("🪄 Auto-Fill (အလိုအလျောက် ဖြည့်ရန်)", on_click=auto_fill_callback)
    
    if st.session_state.bulk_msg:
        if "✅" in st.session_state.bulk_msg: st.success(st.session_state.bulk_msg)
        else: st.warning(st.session_state.bulk_msg)
        st.session_state.bulk_msg = ""

    st.markdown("---")
    st.subheader("🔑 Gemini API Keys (၅ ခုအထိ)")
    if st.session_state.active_key:
        st.success("🟢 API Key အလုပ်လုပ်နေပါသည်")
    
    # API Key inputs with ultra-reliable persistence logic
    # Sync function that works both on change and as a fallback
    def sync_keys_to_state():
        for i in range(1, 6):
            wk = f"w_key_{i}"
            wgk = f"w_grok_key_{i}"
            if wk in st.session_state and st.session_state[wk]:
                st.session_state[f"key_{i}"] = st.session_state[wk]
            if wgk in st.session_state and st.session_state[wgk]:
                st.session_state[f"grok_key_{i}"] = st.session_state[wgk]

    # Gemini Section
    st.text_input("API Key 1", type="password", value=st.session_state.key_1, key="w_key_1", on_change=sync_keys_to_state)
    show_more_keys = st.toggle("🔽 ကျန် API Keys များ ဖော်ပြရန်", value=False, key="show_more_keys_toggle")
    if show_more_keys:
        for i in range(2, 6):
            st.text_input(f"API Key {i}", type="password", value=st.session_state.get(f"key_{i}", ""), key=f"w_key_{i}", on_change=sync_keys_to_state)
    
    # Force sync and collect
    sync_keys_to_state()
    api_keys = [st.session_state.get(f'key_{i}', "").strip() for i in range(1, 6) if st.session_state.get(f'key_{i}', "").strip()]
    
    # Auto-save keys to file whenever they change
    save_keys_to_file()
    
    st.markdown("---")
    st.subheader("🔑 Groq API Keys (၅ ခုအထိ)")
    if st.session_state.active_grok_key:
        st.success("🟢 Grok API အလုပ်လုပ်နေပါသည်")
    
    # Grok Section
    st.text_input("Grok Key 1", type="password", value=st.session_state.grok_key_1, key="w_grok_key_1", on_change=sync_keys_to_state)
    show_more_grok = st.toggle("🔽 ကျန် Grok Keys များ ဖော်ပြရန်", value=False, key="show_more_grok_toggle")
    if show_more_grok:
        for i in range(2, 6):
            st.text_input(f"Grok Key {i}", type="password", value=st.session_state.get(f"grok_key_{i}", ""), key=f"w_grok_key_{i}", on_change=sync_keys_to_state)
    
    sync_keys_to_state()
    grok_keys = [st.session_state.get(f'grok_key_{i}', "").strip() for i in range(1, 6) if st.session_state.get(f'grok_key_{i}', "").strip()]
    
    if st.button("🔌 Keys အားလုံး စမ်းသပ်ရန်"):
        if not api_keys and not grok_keys:
            st.error("API Key အရင်ထည့်ပေးပါ။")
        else:
            st.session_state.test_results = []
            st.session_state.valid_keys_info = {}
            st.session_state.valid_grok_info = {}
            
            with st.spinner("Keys များကို စစ်ဆေးနေသည်..."):
                # Test Gemini Keys
                for i, k in enumerate(api_keys):
                    success = False
                    error_detail = "မမှန်ကန်ပါ။"
                    for ver in API_VERSIONS:
                        try:
                            url = f"https://generativelanguage.googleapis.com/{ver}/models?key={k}"
                            r = requests.get(url, headers=HTTP_HEADERS, timeout=25)
                            if r.status_code == 200:
                                data = r.json()
                                models = [m['name'].split('/')[-1] for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
                                st.session_state.valid_keys_info[k] = {"version": ver, "models": models}
                                if not st.session_state.active_key: st.session_state.active_key = k
                                st.session_state.test_results.append(f"✅ Gemini Key {i+1} အောင်မြင်ပါသည်။")
                                success = True
                                break
                            elif r.status_code == 403:
                                error_detail = "မမှန်ကန်ပါ။ (Forbidden/Invalid Key)"
                                break
                            elif r.status_code == 429:
                                error_detail = "အသုံးပြုမှု များနေပါသည်။ (Rate Limit)"
                                break
                            else:
                                error_detail = f"အမှားရှိနေပါသည်။ (Status: {r.status_code})"
                        except requests.exceptions.ConnectionError as ce:
                            error_detail = f"ဆက်သွယ်မှု မအောင်မြင်ပါ။ (Connection Error: {str(ce)[:40]})"
                        except Exception as e:
                            error_detail = f"ဆက်သွယ်မှု မအောင်မြင်ပါ။ ({str(e)[:40]})"
                    if not success:
                        st.session_state.test_results.append(f"❌ Gemini Key {i+1} {error_detail}")
                
                # Test Groq Keys
                for i, gk in enumerate(grok_keys):
                    gk = gk.strip()
                    if not gk: continue
                    
                    success = False
                    error_detail = ""
                    # Retry logic (2 attempts)
                    for attempt in range(2):
                        try:
                            url = "https://api.groq.com/openai/v1/models"
                            headers = {
                                "Authorization": f"Bearer {gk}",
                                "Content-Type": "application/json"
                            }
                            r = requests.get(url, headers=headers, timeout=30)
                            if r.status_code == 200:
                                data = r.json()
                                models = [m['id'] for m in data.get('data', [])]
                                st.session_state.valid_grok_info[gk] = {"models": models}
                                if not st.session_state.active_grok_key: st.session_state.active_grok_key = gk
                                st.session_state.test_results.append(f"✅ Groq Key {i+1} အောင်မြင်ပါသည်။")
                                success = True
                                break
                            elif r.status_code == 401:
                                error_detail = "မမှန်ကန်ပါ။ (Unauthorized)"
                                break
                            elif r.status_code == 429:
                                error_detail = "အသုံးပြုမှု များနေပါသည်။ (Rate Limit)"
                                break
                            else:
                                error_detail = f"အမှားရှိနေပါသည်။ (Status: {r.status_code})"
                                break
                        except requests.exceptions.ConnectionError as ce:
                            error_detail = f"ဆက်သွယ်မှု မအောင်မြင်ပါ။ (Network Error: {str(ce)[:40]})"
                            time.sleep(1)
                        except requests.exceptions.Timeout:
                            error_detail = "ဆက်သွယ်မှု အချိန်ကျော်လွန်သွားပါသည်။ (Timeout)"
                            time.sleep(1)
                        except Exception as e:
                            error_detail = f"ဆက်သွယ်မှု မအောင်မြင်ပါ။ ({str(e)[:40]})"
                            break
                    
                    if not success:
                        st.session_state.test_results.append(f"❌ Grok Key {i+1} {error_detail}")
            st.rerun()

    # Persistent display of test results
    if st.session_state.test_results:
        st.markdown("---")
        st.subheader("📋 Key စစ်ဆေးမှု ရလဒ်များ")
        for res in st.session_state.test_results:
            if "✅" in res: st.success(res)
            else: st.error(res)
        if st.button("🗑️ ရလဒ်များ ရှင်းလင်းရန်"):
            st.session_state.test_results = []
            st.rerun()

    st.markdown("---")
    st.subheader("🎬 ဗီဒီယို ပုံစံညှိရန်")
    mirror_v = st.checkbox("ဗီဒီယို Mirror လှန်ရန်", value=True, key="mirror_check")
    scale_v = st.checkbox("ဗီဒီယို Scale 106% ချဲ့ရန်", value=True, key="scale_check")

    st.markdown("---")
    st.subheader("🤖 မူရင်းစာတန်းထိုး ဝါးရန် (Blur)")
    
    # Auto Detect toggle
    use_auto = st.toggle("🤖 AI အလိုအလျောက် ရှာဖွေရန်", value=True, key="blur_auto_toggle")
    
    blur_s = st.checkbox("မူရင်းစာတန်းထိုး ဝါးရန် (Blur Enable)", value=True, key="blur_enable_check", 
                         help="AI Auto Detect Mode ဗီဒီယိုတင်ပြီး \"စတင်လုပ်ဆောင်ရန်\" နှိပ်ပါက AI က မူရင်းစာတန်းထိုး နေရာကို အလိုအလျောက် ရှာဖွေပြီး ဝါးပေးပါမည်။\n\n🔒 Manual ညှိရန် လိုချင်ပါက AI Auto Detect ကို OFF ဖွင့်ပါ")
    
    if blur_s:
        if use_auto:
            # AUTO MODE — hide manual settings
            st.info("🤖 **AI Auto Detect Mode**\nAI က မူရင်းစာတန်းထိုး နေရာကို အလိုအလျောက် ရှာဖွေပြီး ဝါးပေးပါမည်။")
            use_manual = False
        else:
            # AUTO OFF — show manual toggle and sliders
            use_manual = st.toggle("✏️ Manual ညှိရန်", value=False, key="blur_manual_toggle")
            if use_manual:
                st.info("✏️ **Manual Mode** — အောက်ပါ slider များဖြင့် ညှိပါ")
                b_y = plus_minus_slider("ဝါးမည့်နေရာ (Y %)", "blur_y_pos", 0, 100, 1)
                b_h = plus_minus_slider("ဝါးမည့်အကျယ် (H %)", "blur_h_size", 1, 30, 1)
            else:
                st.info("⚙️ **Default Mode** — Y: 85%, H: 6%")
                st.session_state.blur_y_pos = 85
                st.session_state.blur_h_size = 6
    else:
        st.session_state.blur_y_pos = 85
        st.session_state.blur_h_size = 6

    st.markdown("---")
    st.subheader("📝 မြန်မာစာတန်းထိုး")
    
    burn_s = st.checkbox("မြန်မာစာတန်းထိုး ထည့်ရန်", value=True, key="burn_enable_check")
    
    if burn_s:
        if use_auto:
            # AUTO MODE — hide manual settings
            burn_manual = False
            st.info("📍 **Auto Mode** — စာတန်းထိုးကို Blur နေရာပေါ်တွင် အလိုအလျောက် တင်ပေးပါမည်။")
            st.session_state.font_size = 22
            # sub_y_pos will be calculated relative to blur area in auto mode
        else:
            # AUTO OFF — show manual toggle
            burn_manual = st.toggle("✏️ Manual ညှိရန်", value=False, key="subtitle_manual_toggle")
            if burn_manual:
                f_s = plus_minus_slider("စာလုံးအရွယ်အစား", "font_size", 5, 100, 1)
                s_y = plus_minus_slider("စာတန်းထိုးနေရာ (Y %)", "sub_y_pos", 0, 100, 1)
            else:
                st.info("📍 Default: ဗီဒီယိုအောက်ခြေ အလယ်တည့်တည့် (Y: 85%, Font: 22)")
                st.session_state.font_size = 22
                st.session_state.sub_y_pos = 85
    else:
        st.session_state.sub_y_pos = 85

    st.markdown("---")
    show_prev = st.checkbox("👀 ပုံစံ ကြိုတင်ကြည့်ရန်", value=True, key="preview_check")

    st.markdown("---")
    st.subheader("⏱️ အချိန် ထိန်းချုပ်ရန်")
    fit_dur = st.toggle("သတ်မှတ်အချိန်အတွင်း အပြီးပြောရန်", value=True, key="fit_duration_toggle")
    target_sec = 0
    if fit_dur:
        tm = plus_minus_slider("မိနစ်", "target_min", 0, 60, 1)
        ts = plus_minus_slider("စက္ကန့်", "target_sec", 0, 59, 1)
        target_sec = (tm * 60) + ts
        st.info(f"သတ်မှတ်ထားသော အချိန်: {tm} မိနစ် {ts} စက္ကန့်")
    else:
        target_sec = 0

    st.markdown("---")
    st.subheader("🔊 အသံ ဆက်တင်များ")
    v_choice = st.selectbox("အသံရွေးချယ်ပါ", ["သီဟ (အမျိုးသားသံ)", "နီလာ (အမျိုးသမီးသံ)"])
    v_id = "my-MM-ThihaNeural" if "သီဟ" in v_choice else "my-MM-NilarNeural"
    
    # Initialize voice settings if not present
    if 'v_speed' not in st.session_state: st.session_state.v_speed = 55
    if 'v_pitch' not in st.session_state: st.session_state.v_pitch = 50
    
    v_speed = plus_minus_slider("အသံနှုန်း", "v_speed", 1, 100, 1)
    v_pitch = plus_minus_slider("Pitch", "v_pitch", 1, 100, 1)

# --- UTILITIES ---
def create_subtitle_image(text, font_size):
    """Render Myanmar text onto a small transparent image (Optimized for Memory)"""
    font = None
    try:
        font = ImageFont.truetype(FONT_PATH, font_size, layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        try:
            font = ImageFont.truetype(FONT_PATH, font_size, layout_engine=ImageFont.Layout.BASIC)
        except Exception:
            try:
                font = ImageFont.truetype(FONT_PATH, font_size)
            except Exception:
                font = ImageFont.load_default()

    temp_draw = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    lines = text.split('\n')
    line_bboxes = [temp_draw.textbbox((0, 0), line, font=font) for line in lines]
    
    max_w = max([b[2] - b[0] for b in line_bboxes]) + 20
    line_h = max([b[3] - b[1] for b in line_bboxes]) + 10
    total_h = line_h * len(lines) + 10

    img = Image.new('RGBA', (int(max_w), int(total_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    current_y = 5
    for i, line in enumerate(lines):
        bbox = line_bboxes[i]
        w = bbox[2] - bbox[0]
        x = (max_w - w) // 2
        for offset in [(-2,-2), (2,-2), (-2,2), (2,2)]:
            draw.text((x+offset[0], current_y+offset[1]), line, font=font, fill=(0,0,0,255))
        draw.text((x, current_y), line, font=font, fill=(255, 255, 0, 255))
        current_y += line_h

    return img, max_w, total_h

def normalize_myanmar(text):
    if not text: return text
    import unicodedata
    return unicodedata.normalize('NFC', text)

def wrap_text(text, max_len=25):
    if not text: return text
    text = normalize_myanmar(text)
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    import re
    cluster_pattern = r'[\u1000-\u102A\u103F\u1040-\u1049][\u102B-\u103E\u1037\u1038\u1039\u103A]*'
    clusters = re.findall(cluster_pattern + r'|[^\u1000-\u1049]', text)
    lines = []
    cur_line = ""
    cur_len = 0
    for c in clusters:
        if c == " ":
            if cur_len >= max_len:
                lines.append(cur_line.strip())
                cur_line = ""
                cur_len = 0
            else:
                cur_line += c
                cur_len += 1
            continue
        if cur_len + 1 > max_len and cur_line:
            lines.append(cur_line.strip())
            cur_line = c
            cur_len = 1
        else:
            cur_line += c
            cur_len += 1
    if cur_line:
        lines.append(cur_line.strip())
    return "\n".join(lines[:3])

def get_dur(p):
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", p]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return float(r.stdout.strip())
    except: return 0

def fmt_srt(s):
    m = int((s % 1) * 1000)
    return f"{time.strftime('%H:%M:%S', time.gmtime(s))},{m:03d}"

def parse_srt_text(text):
    text = re.sub(r'```srt?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```', '', text).strip()
    text = re.sub(r'\d{1,2}:\d{1,2}:\d{1,2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{1,2}:\d{1,2}[,.]\d{1,3}', '', text)
    text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[\d{1,2}:\d{1,2}:\d{1,2}\.\d{1,3}\s*-->\s*\d{1,2}:\d{1,2}:\d{1,2}\.\d{1,3}\]', '', text)
    text = re.sub(r'\(\d{1,2}:\d{1,2}:\d{1,2}\.\d{1,3}\s*-->\s*\d{1,2}:\d{1,2}:\d{1,2}\.\d{1,3}\)', '', text)
    
    lines = text.split('\n')
    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line: continue
        if re.match(r'^\d+$', line): continue
        if re.match(r'^\(?\d+[\.\)]\s*$', line): continue
        if re.match(r'^\d{1,2}:\d{1,2}:\d{1,2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{1,2}:\d{1,2}[,.]\d{1,3}$', line): continue
        if re.match(r'^\[\d{1,2}:\d{1,2}:\d{1,2}\.\d{1,3}\s*-->\s*\d{1,2}:\d{1,2}:\d{1,2}\.\d{1,3}\]$', line): continue
        if re.match(r'^\(\d{1,2}:\d{1,2}:\d{1,2}\.\d{1,3}\s*-->\s*\d{1,2}:\d{1,2}:\d{1,2}\.\d{1,3}\)$', line): continue
        if re.match(r'(?i)^(here is|narration|recap|script|translation):', line): continue
        clean_lines.append(line)
    
    full_content = ' '.join(clean_lines)
    full_content = re.sub(r'\s+', ' ', full_content).strip()
    
    segments = []
    parts = re.split(r'([။၊.!?;])', full_content)
    for i in range(0, len(parts)-1, 2):
        seg = (parts[i] + parts[i+1]).strip()
        if seg: segments.append(seg)
    if len(parts) % 2 != 0 and parts[-1].strip():
        segments.append(parts[-1].strip())
        
    return [s for s in segments if s]

async def gen_audio_srt(text, out_p, vid, spd, ptc, target=0):
    rate = f"+{int((spd-50)*2)}%" if spd>=50 else f"{int((spd-50)*2)}%"
    pitch = f"+{int((ptc-50)*2)}Hz" if ptc>=50 else f"{int((ptc-50)*2)}Hz"
    segments = parse_srt_text(text)
    if not segments: segments = [text]
    
    temp_files = []
    cur_t = 0.0
    srt_blocks = []
    
    for idx, txt in enumerate(segments):
        clean_txt = txt.strip()
        if not clean_txt: continue
        p = tempfile.mktemp(suffix=".mp3")
        try:
            communicate = edge_tts.Communicate(clean_txt, vid, rate=rate, pitch=pitch)
            await communicate.save(p)
            d = get_dur(p)
            if d > 0:
                srt_blocks.append(f"{len(srt_blocks)+1}\n{fmt_srt(cur_t)} --> {fmt_srt(cur_t+d)}\n{wrap_text(clean_txt)}\n\n")
                temp_files.append(p)
                cur_t += d
        except: continue
        
    if not temp_files: raise Exception("အသံဖိုင် ထုတ်လုပ်ခြင်း မအောင်မြင်ပါ။")
    
    raw = tempfile.mktemp(suffix=".mp3")
    l_p = tempfile.mktemp(suffix=".txt")
    with open(l_p, "w", encoding='utf-8') as f:
        f.write("\n".join([f"file '{os.path.abspath(p)}'" for p in temp_files]))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", l_p, "-c", "copy", raw], capture_output=True)
    
    total = get_dur(raw)
    
    if target > 0 and total > 0:
        factor = total / target
        factor = np.clip(factor, 0.7, 2.0)
        
        if abs(factor - 1.0) > 0.01:
            subprocess.run(["ffmpeg", "-y", "-i", raw, "-filter:a", f"atempo={factor}", out_p], capture_output=True)
        else:
            shutil.copy(raw, out_p)
            
        final_srt = []
        for line in "".join(srt_blocks).splitlines(keepends=True):
            if "-->" in line:
                try:
                    s, e = line.split(" --> ")
                    s = re.sub(r'[\[\]\(\)]', '', s).strip()
                    e = re.sub(r'[\[\]\(\)]', '', e).strip()
                    s_s = sum(float(x)*60**i for i,x in enumerate(reversed(s.replace(",",".").split(":")))) / factor
                    e_s = sum(float(x)*60**i for i,x in enumerate(reversed(e.replace(",",".").split(":")))) / factor
                    final_srt.append(f"{fmt_srt(s_s)} --> {fmt_srt(e_s)}\n")
                except:
                    final_srt.append(line)
            else:
                final_srt.append(line)
        res_srt = "".join(final_srt)
    else:
        shutil.copy(raw, out_p)
        res_srt = "".join(srt_blocks)
        
    for p in temp_files: 
        if os.path.exists(p): os.remove(p)
    if os.path.exists(l_p): os.remove(l_p)
    if os.path.exists(raw): os.remove(raw)
    
    return res_srt, get_dur(out_p)

def get_filter(mir, scl, blr, by_px, bh_px, brn, sp, fs, sx, sy):
    """Build ffmpeg filter chain.
    
    When scale/crop is enabled, the video is scaled by 1.06 then cropped back.
    The blur coordinates are in the original frame space, but after scale/crop
    the frame content has shifted (zoomed in), so blur coords must be adjusted.
    
    Scale 1.06x then crop back: content appears zoomed in by ~3% on each side.
    So blur position shifts: by_adj = by_px / 1.06 + offset_from_zoom
    
    For simplicity: use expressions that reference iw/ih (post-scale dimensions).
    When scale=1.06*iw:-1,crop=iw/1.06:ih/1.06, the cropped frame is same size as original.
    But content is shifted. We need to use scale-adjusted coords for blur.
    
    Best approach: apply blur on the PRE-scale frame, then scale everything together.
    """
    # Step 1: Mirror on original
    mir_str = "hflip," if mir else ""
    
    if blr:
        # Apply blur on original frame FIRST (coords match original frame)
        fc = f"[0:v]{mir_str}split[orig_main][orig_blur];"
        fc += f"[orig_blur]crop=iw:{bh_px}:0:{by_px},boxblur=luma_radius=10:chroma_radius=4:alpha_radius=1[blurred];"
        fc += f"[orig_main][blurred]overlay=0:{by_px}[blurred_frame];"
        # Now apply scale/crop to the already-blurred frame
        if scl:
            fc += f"[blurred_frame]scale=1.06*iw:-1,crop=iw/1.06:ih/1.06[main];"
        else:
            fc += f"[blurred_frame]null[main];"
    else:
        # No blur - just apply mirror+scale directly
        parts = []
        if mir: parts.append("hflip")
        if scl: parts.append("scale=1.06*iw:-1,crop=iw/1.06:ih/1.06")
        base_str = ",".join(parts) if parts else "null"
        fc = f"[0:v]{base_str}[main];"
    
    # Step 4: Overlay subtitle if needed (overlay goes on [main] which is post-scale)
    if brn and sp and os.path.exists(sp):
        fc += f"[main][1:v]overlay={sx}:{sy}[v]"
    else:
        fc += f"[main]null[v0]"
    
    return fc

# --- MAIN UI ---
up = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if up:
    fid = up.name + str(up.size)
    if st.session_state.last_uploaded != fid:
        st.session_state.last_uploaded = fid
        tp = os.path.join(tempfile.gettempdir(), f"input_{fid}." + up.name.split(".")[-1])
        if not os.path.exists(tp):
            with open(tp, "wb") as f:
                f.write(up.getvalue())
        if up.name.lower().endswith((".mp4", ".mov", ".avi")):
            d = get_dur(tp)
            bi = tempfile.mktemp(suffix=".jpg")
            subprocess.run(["ffmpeg", "-y", "-ss", str(d*0.2), "-i", tp, "-frames:v", "1", bi], capture_output=True)
            if os.path.exists(bi):
                with open(bi, "rb") as f: st.session_state.base_frame = f.read()
                os.remove(bi)

    # Auto-detect subtitle area when auto mode is enabled and manual is off
    if use_auto and not use_manual and st.session_state.base_frame and blur_s:
        detected_y, detected_h = auto_detect_subtitle_area(st.session_state.base_frame, api_keys if api_keys else None)
        st.session_state.blur_y_pos = detected_y
        st.session_state.blur_h_size = detected_h

    if show_prev and st.session_state.base_frame:
        st.subheader("🖼️ Layout Preview")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as bf:
            bf.write(st.session_state.base_frame); bp = bf.name
        with Image.open(bp) as base_img:
            w, h = base_img.size
            sub_img, sw, sh = create_subtitle_image("မြန်မာစာ ယူနီကုတ်\nစမ်းသပ်ကြည့်ရှုခြင်း", st.session_state.font_size)
            sub_p = tempfile.mktemp(suffix=".png")
            sub_img.save(sub_p)
        po = tempfile.mktemp(suffix=".jpg")
        
        x_p = (w - sw) // 2
        by_px = int(h * (st.session_state.blur_y_pos / 100))
        bh_px = int(h * (st.session_state.blur_h_size / 100))
        
        if use_auto and blur_s:
            # Center subtitle inside blur area
            y_p = by_px + (bh_px - sh) // 2
        else:
            y_p = int(h * (st.session_state.sub_y_pos / 100)) - (sh // 2)
        
        fc = get_filter(mirror_v, scale_v, blur_s, by_px, bh_px, burn_s, sub_p, st.session_state.font_size, x_p, y_p)
        
        # Preview uses simpler filter: append null to ensure [v] output
        if fc.endswith('[v]'):
            filter_str = fc
        elif fc.endswith('[v0]'):
            filter_str = fc + ";[v0]null[v]"
        else:
            filter_str = fc + ";null[v]"
        
        filter_script_p = tempfile.mktemp(suffix=".txt")
        with open(filter_script_p, "w", encoding="utf-8") as f: f.write(filter_str)
        inputs = ["-i", bp, "-i", sub_p] if burn_s else ["-i", bp]
        if len(filter_str) < 2000:
            cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", filter_str, "-map", "[v]", po]
        else:
            cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex_script", filter_script_p, "-map", "[v]", po]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            st.warning(f"Preview render error: {res.stderr[-200:]}")
        if os.path.exists(filter_script_p): os.remove(filter_script_p)
        if os.path.exists(po):
            with Image.open(po) as img_prev:
                st.image(img_prev)
            os.remove(po)
        if os.path.exists(bp): os.remove(bp)
        if os.path.exists(sub_p): os.remove(sub_p)

    if not api_keys: st.warning("⚠️ Sidebar တွင် Gemini API Key ထည့်ပေးပါ")
    elif st.button("🚀 စတင်လုပ်ဆောင်ရန်"):
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            st.error("❌ FFmpeg မရရှိပါ။ packages.txt ဖိုင်တွင် ffmpeg ပါရှိကြောင်း သေချာပါစေ။")
        else:
            prg = st.progress(0); stt = st.empty()
            try:
                for k in ['video_path', 'audio_path', 'srt_data']: st.session_state[k] = None
                
                # === STEP 1: Audio Compression ===
                stt.text("📊 အဆင့် ၁: အသံဖိုင်ကို အမြန်ဆုံးဖြစ်အောင် ချုံ့နေပါသည်...")
                prg.progress(10)
                tp = os.path.join(tempfile.gettempdir(), f"input_{fid}." + up.name.split(".")[-1])
                ag = tempfile.mktemp(suffix=".mp3")
                if up.name.lower().endswith((".mp4", ".mov", ".avi")):
                    subprocess.run(["ffmpeg", "-y", "-i", tp, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], capture_output=True)
                else:
                    subprocess.run(["ffmpeg", "-y", "-i", tp, "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], capture_output=True)

                # === STEP 2: AI Translation ===
                stt.text("⏳ အဆင့် ၂: ဘာသာပြန်နေပါသည် (Gemini API)...")
                prg.progress(30)
                target_words = int(target_sec * 3.8)
                prm = f"""Listen to this audio and translate it into a HIGH-ENERGY Myanmar Movie Recap style narration.
TARGET DURATION: {target_sec} seconds.
REQUIRED SCRIPT LENGTH: You MUST write exactly around {target_words} Myanmar words to fill the {target_sec} seconds timeframe perfectly.

STRICT CONTENT RULES:
1. NO FILLER PHRASES: Do NOT use phrases like "Hello audience" (ပရိတ်သတ်ကြီးရေ), "Welcome back", or generic greetings.
2. FOCUS ON SCENES: Describe ONLY what is happening in the movie. Focus on character actions, emotions, and plot points.
3. TIMING SYNC: Ensure the narration follows the exact sequence of events in the source audio. Do not jump ahead or lag behind.
4. NO HALLUCINATION: Do not add external information not present in the movie context.

MOVIE RECAP STYLE RULES:
1. The tone must be dramatic, fast-paced, and extremely engaging.
2. Use natural, conversational Myanmar language.
3. Keep the narration DENSE and CONTINUOUS. Describe every scene, action, and character emotion in detail to fill the time.
4. There should be ALMOST NO SILENCE. If the source audio is shorter than {target_sec} seconds, you MUST EXPAND the story with more descriptive details to reach the required length.
5. Use Standard Myanmar Unicode.

FORMATTING RULES:
1. Output ONLY valid SRT subtitle format.
2. Each subtitle block should be a natural phrase (approx 15 words).
3. The timestamps in your SRT output MUST span the entire range from 00:00:00,000 to {fmt_srt(target_sec)}.
4. DO NOT include any preamble or conclusion. Just the SRT blocks."""
                
                with open(ag, 'rb') as f: b64 = base64.b64encode(f.read()).decode()
                cont = [{"role":"user","parts":[{"text":prm},{"inline_data":{"mime_type":"audio/mpeg","data":b64}}]}]

                srt_res = None
                errors = []
                
                with st.status("🌐 AI API နှင့် ဆက်သွယ်ပြီး ဘာသာပြန်နေပါသည်...", expanded=True) as status:
                    # Try Groq First if available
                    if grok_keys:
                        for gk_idx, gk in enumerate(grok_keys):
                            status.write(f"🔑 Groq Key {gk_idx+1} ကို အသုံးပြုနေပါသည်...")
                            info = st.session_state.valid_grok_info.get(gk)
                            g_models = info.get("models", []) if info else []
                            # Use text-only models (Groq vision models are deprecated)
                            t_models = [m for m in g_models if "vision" not in m.lower()]
                            # Prefer powerful models
                            preferred = [m for m in t_models if "70b" in m.lower()]
                            fallback = [m for m in t_models if "8b" in m.lower()]
                            other = [m for m in t_models if "70b" not in m.lower() and "8b" not in m.lower()]
                            ordered = preferred + fallback + other
                            if not ordered: ordered = ["llama-3.3-70b-versatile"]
                            
                            for gm in ordered:
                                try:
                                    status.write(f"🤖 Groq Model: {gm} ဖြင့် ဘာသာပြန်နေပါသည်...")
                                    url = "https://api.groq.com/openai/v1/chat/completions"
                                    headers = {"Authorization": f"Bearer {gk}", "Content-Type": "application/json"}
                                    payload = {
                                        "model": gm,
                                        "messages": [{"role": "user", "content": prm}],
                                        "temperature": 0.7
                                    }
                                    
                                    r = requests.post(url, json=payload, headers=headers, timeout=180)
                                    if r.status_code == 200:
                                        srt_res = r.json()['choices'][0]['message']['content'].strip()
                                        if srt_res:
                                            st.session_state.active_grok_key = gk
                                            status.update(label="✅ Groq ဖြင့် ဘာသာပြန်ခြင်း ပြီးမြောက်ပါပြီ!", state="complete")
                                            with st.expander("📝 Narration Preview (Groq)", expanded=True):
                                                st.text_area("Narration Content", srt_res, height=200)
                                            break
                                except Exception:
                                    continue
                            if srt_res: break

                    # Fallback to Gemini
                    if not srt_res:
                        for k_idx, k in enumerate(api_keys):
                            status.write(f"🔑 Gemini Key {k_idx+1} ကို အသုံးပြုနေပါသည်...")
                            info = st.session_state.valid_keys_info.get(k)
                            versions = [info['version']] if info else API_VERSIONS
                            models = info['models'] if info else DEFAULT_MODELS
                            models = sorted(models, key=lambda x: 0 if 'flash' in x.lower() else 1)
                            
                            for ver in versions:
                                for m in models:
                                    try:
                                        status.write(f"🤖 Gemini Model: {m} ဖြင့် ဘာသာပြန်နေပါသည်...")
                                        url = f"https://generativelanguage.googleapis.com/{ver}/models/{m}:generateContent?key={k}"
                                        r = requests.post(url, json={"contents":cont}, timeout=180)
                                        if r.status_code == 200:
                                            data = r.json()
                                            if 'candidates' in data and data['candidates'][0]['content']['parts']:
                                                srt_res = data['candidates'][0]['content']['parts'][0]['text']
                                                if srt_res:
                                                    st.session_state.active_key = k
                                                    status.update(label="✅ Gemini ဖြင့် ဘာသာပြန်ခြင်း ပြီးမြောက်ပါပြီ!", state="complete")
                                                    with st.expander("📝 Narration Preview (Gemini)", expanded=True):
                                                        st.text_area("Narration Content", srt_res, height=200)
                                                    break
                                        else:
                                            try: msg = r.json().get('error', {}).get('message', r.text)
                                            except: msg = r.text
                                            errors.append(f"{m}: {translate_error(msg, r.status_code)}")
                                    except Exception as e:
                                        errors.append(f"{m}: {translate_error(str(e))}")
                                if srt_res: break
                            if srt_res: break

                if not srt_res:
                    st.error("❌ Gemini ဘာသာပြန်ခြင်း မအောင်မြင်ပါ")
                    for e in errors: st.info(e)
                    raise Exception("ဘာသာပြန်ခြင်း မလုပ်ဆောင်နိုင်ပါ။")

                # === STEP 3: TTS Audio Generation ===
                stt.text("🔊 အဆင့် ၃: အသံဖိုင်နှင့် Timing ညှိနေပါသည်...")
                prg.progress(60)
                ao_name = f"audio_{fid}_{int(time.time())}.mp3"
                ao = os.path.join(tempfile.gettempdir(), ao_name)
                
                with st.status("🔊 အသံဖိုင်များကို တစ်ခုချင်းစီ ထုတ်လုပ်နေပါသည်...", expanded=False) as status:
                    st.session_state.srt_data, audio_final_dur = asyncio.run(gen_audio_srt(srt_res, ao, v_id, v_speed, v_pitch, target_sec if fit_dur else 0))
                    status.update(label="✅ အသံဖိုင်အားလုံး ပေါင်းစပ်ပြီးပါပြီ!", state="complete")
                st.session_state.audio_path = ao
                audio_final_dur = get_dur(ao)

                # === STEP 4: Video Rendering ===
                if up.name.lower().endswith((".mp4", ".mov", ".avi")):
                    stt.text("🎬 အဆင့် ၄: ဗီဒီယိုကို တည်းဖြတ်နေပါသည် (Rendering)...")
                    prg.progress(80)
                    
                    # Run auto-detect AGAIN during processing (in case frame changed)
                    if use_auto and not use_manual and st.session_state.base_frame and blur_s:
                        stt.text("🤖 AI Auto Detect: မူရင်းစာတန်းထိုး နေရာ ရှာဖွေနေပါသည်...")
                        detected_y, detected_h = auto_detect_subtitle_area(st.session_state.base_frame, api_keys if api_keys else None)
                        st.session_state.blur_y_pos = detected_y
                        st.session_state.blur_h_size = detected_h
                        stt.text(f"🤖 AI Auto Detect: Y={detected_y:.1f}%, H={detected_h:.1f}%")
                    
                    stt.text("🎬 စာတန်းထိုးများကို ပုံဖော်နေပါသည်...")
                    sub_dir = tempfile.mkdtemp()
                    cmd_dim = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", tp]
                    v_dim = subprocess.run(cmd_dim, capture_output=True, text=True).stdout.strip().split('x')
                    vw, vh = int(v_dim[0]), int(v_dim[1])

                    segments = []
                    blocks = re.split(r'\n\s*\n', st.session_state.srt_data)
                    for block in blocks:
                        lines = block.strip().split('\n')
                        if len(lines) >= 3:
                            times = lines[1].split(' --> ')
                            start = sum(float(x)*60**i for i,x in enumerate(reversed(times[0].replace(',','.').split(':'))))
                            end = sum(float(x)*60**i for i,x in enumerate(reversed(times[1].replace(',','.').split(':'))))
                            text = "\n".join(lines[2:])
                            segments.append({'start': start, 'end': end, 'text': text})

                    # Calculate blur positions and subtitle position BEFORE overlay loop
                    by_px_r = int(vh * (st.session_state.blur_y_pos / 100))
                    bh_px_r = int(vh * (st.session_state.blur_h_size / 100))
                    sub_gap = 5  # small gap between subtitle and blur area
                    sub_y_px = by_px_r - sub_gap  # subtitle sits above blur area
                    
                    overlay_filters = []
                    temp_imgs = []
                    for i, seg in enumerate(segments):
                        simg, sw, sh = create_subtitle_image(seg['text'], st.session_state.font_size)
                        spath = os.path.join(sub_dir, f"sub_{i}.png")
                        simg.save(spath)
                        temp_imgs.append(spath)
                        
                        x_pos = (vw - sw) // 2
                        # Place subtitle on blur area if auto mode
                        if use_auto and blur_s:
                            y_pos = by_px_r + (bh_px_r - sh) // 2
                        elif blur_s:
                            y_pos = sub_y_px - sh
                        else:
                            y_pos = int(vh * (st.session_state.sub_y_pos / 100)) - (sh // 2)
                        
                        safe_spath = spath.replace("'", "'\\''").replace(":", "\\:")
                        # Use unique label names to avoid chaining issues
                        in_label = f"vin{i}"
                        out_label = f"vout{i}"
                        overlay_filters.append(f"movie=filename='{safe_spath}'[s{i}];[{in_label}][s{i}]overlay={x_pos}:{y_pos}:enable='between(t,{seg['start']},{seg['end']})'[{out_label}]")

                    # by_px_r and bh_px_r already calculated above
                    
                    # Get video duration for speed calculation
                    video_duration = get_dur(tp)
                    
                    # === VIDEO-AUDIO SPEED SYNC ===
                    video_speed_factor = 1.0
                    if fit_dur and target_sec > 0 and video_duration > 0:
                        video_speed_factor = video_duration / target_sec
                        video_speed_factor = np.clip(video_speed_factor, 0.5, 2.0)
                        stt.text(f"🎬 Video Speed Factor: {video_speed_factor:.2f}x (Video: {video_duration:.1f}s → Target: {target_sec}s)")
                    
                    # Build filter with optional speed adjustment
                    if abs(video_speed_factor - 1.0) > 0.01:
                        speed_filter = f"setpts=1/{video_speed_factor}*PTS"
                        base_filter_with_speed = f"[0:v]{speed_filter}[speedup]"
                    else:
                        base_filter_with_speed = "[0:v]"
                    
                    fcf = get_filter(mirror_v, scale_v, blur_s, by_px_r, bh_px_r, False, None, 0, 0, 0)
                    if abs(video_speed_factor - 1.0) > 0.01:
                        full_filter = base_filter_with_speed + ";" + fcf.replace("[0:v]", "[speedup]")
                    else:
                        full_filter = fcf
                    
                    # Chain overlay filters properly using unique labels
                    if overlay_filters:
                        # First overlay input is [v0] (output from get_filter)
                        first_overlay = overlay_filters[0].replace("vin0", "v0")
                        full_filter += ";" + first_overlay
                        # Subsequent overlays chain from previous output
                        for i in range(1, len(overlay_filters)):
                            current_filt = overlay_filters[i].replace(f"vin{i}", f"vout{i-1}")
                            full_filter += ";" + current_filt
                        # Final label: rename last output to [v]
                        last_idx = len(overlay_filters) - 1
                        full_filter = full_filter.replace(f"vout{last_idx}", "v")
                    else:
                        # No overlays, ensure we have [v] output
                        full_filter += ";[v0]null[v]"

                    filter_script = tempfile.mktemp(suffix=".txt")
                    with open(filter_script, "w", encoding="utf-8") as f:
                        f.write(full_filter)

                    fv_name = f"final_{fid}_{int(time.time())}.mp4"
                    fv = os.path.join(tempfile.gettempdir(), fv_name)

                    final_audio_dur = audio_final_dur
                    
                    # Build FFmpeg command with proper audio-video sync
                    if abs(video_speed_factor - 1.0) > 0.01:
                        adjusted_video_dur = video_duration / video_speed_factor
                        
                        if final_audio_dur > adjusted_video_dur + 0.5:
                            audio_speed_factor = final_audio_dur / adjusted_video_dur
                            audio_speed_factor = np.clip(audio_speed_factor, 0.5, 2.0)
                            
                            ao_sped = tempfile.mktemp(suffix=".mp3")
                            subprocess.run(["ffmpeg", "-y", "-i", ao, "-filter:a", f"atempo={audio_speed_factor}", ao_sped], capture_output=True)
                            cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", tp, "-i", ao_sped, "-filter_complex_script", filter_script, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "aac", "-b:a", "192k", "-shortest", fv]
                            if os.path.exists(ao_sped):
                                st.session_state.audio_path = ao_sped
                        else:
                            cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", tp, "-i", ao, "-filter_complex_script", filter_script, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "aac", "-b:a", "192k", "-t", str(adjusted_video_dur), fv]
                    else:
                        if video_duration < final_audio_dur - 0.5:
                            cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", tp, "-i", ao, "-filter_complex_script", filter_script, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "aac", "-b:a", "192k", "-shortest", fv]
                        else:
                            cmd = ["ffmpeg", "-y", "-i", tp, "-i", ao, "-filter_complex_script", filter_script, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "aac", "-b:a", "192k", "-t", str(final_audio_dur), fv]
                    
                    res = subprocess.run(cmd, capture_output=True, text=True)

                    if res.returncode != 0:
                        if len(full_filter) < 5000:
                            cmd = ["ffmpeg", "-y", "-i", tp, "-i", ao, "-filter_complex", full_filter, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "aac", "-b:a", "192k", "-shortest", fv]
                            res = subprocess.run(cmd, capture_output=True, text=True)

                    if os.path.exists(filter_script): os.remove(filter_script)
                    shutil.rmtree(sub_dir)

                    if res.returncode == 0:
                        st.session_state.video_path = fv
                    else:
                        raise Exception(f"Render Error: {res.stderr}")

                prg.progress(100); stt.text("✅ အောင်မြင်စွာ ပြီးဆုံးပါပြီ!"); st.balloons()
                st.session_state.processing_done = True
                if os.path.exists(ag): os.remove(ag)
            except Exception as e:
                st.error(f"❌ အမှားအယွင်း: {str(e)}")
                st.session_state.processing_done = False

if st.session_state.processing_done:
    st.markdown("---")
    if st.session_state.video_path and os.path.exists(st.session_state.video_path):
        st.subheader("🎥 တည်းဖြတ်ပြီး ဗီဒီယို")
        st.video(st.session_state.video_path)
        with open(st.session_state.video_path, "rb") as f:
            st.download_button("📥 ဗီဒီယိုကို သိမ်းဆည်းရန်", f, "recap_final.mp4", "video/mp4")
    c1, c2 = st.columns(2)
    with c1:
        if st.session_state.audio_path and os.path.exists(st.session_state.audio_path):
            st.audio(st.session_state.audio_path)
            with open(st.session_state.audio_path, "rb") as f:
                st.download_button("📥 အသံဖိုင်ကို သိမ်းဆည်းရန်", f, "recap_audio.mp3", "audio/mp3")
    with c2:
        if st.session_state.srt_data:
            st.download_button("📥 စာတန်းထိုး (SRT) ကို သိမ်းဆည်းရန်", st.session_state.srt_data, "recap.srt", "text/plain")

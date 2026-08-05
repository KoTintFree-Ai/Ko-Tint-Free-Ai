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
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# --- CONFIGURATION ---
API_VERSIONS = ["v1beta", "v1"]
DEFAULT_MODELS = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-pro"]

# Initialize OpenAI client for Gemini API
@st.cache_resource
def get_gemini_client(api_key):
    return OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_API_BASE"))


# Get the directory where this script is located (for font file path)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(SCRIPT_DIR, "Pyidaungsu.ttf")

st.set_page_config(
    page_title="All-in-One AI Platform",
    page_icon="✨",
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
    keys = ["myanmar_text", "audio_path", "srt_data", "video_path", "base_frame", "last_uploaded", "processing_done", "valid_keys_info", "active_key"]
    for k in keys:
        if k not in st.session_state: st.session_state[k] = None
    for i in range(1, 6):
        if f"key_{i}" not in st.session_state: st.session_state[f"key_{i}"] = os.getenv(f"GEMINI_API_KEY_{i}", "")
    if st.session_state.processing_done is None: st.session_state.processing_done = False
    if st.session_state.valid_keys_info is None: st.session_state.valid_keys_info = {}
    if "do_test_keys" not in st.session_state: st.session_state.do_test_keys = False
    if "blur_y_pos" not in st.session_state: st.session_state.blur_y_pos = 85
    if "blur_h_size" not in st.session_state: st.session_state.blur_h_size = 10
    if "sub_y_pos" not in st.session_state: st.session_state.sub_y_pos = 85
    if "font_size" not in st.session_state: st.session_state.font_size = 22
    if "target_min" not in st.session_state: st.session_state.target_min = 2
    if "target_sec" not in st.session_state: st.session_state.target_sec = 30
    if "v_speed" not in st.session_state: st.session_state.v_speed = 55
    if "v_pitch" not in st.session_state: st.session_state.v_pitch = 50

init_state()

st.title("✨ All-in-One AI Platform")
st.markdown("မြန်မာစာ Text-to-Speech, Movie Recap နှင့် အခြား AI Tools များ")

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

# --- UTILITIES ---
def create_subtitle_image(text, font_size):
    """Render Myanmar text onto a small transparent image (Optimized for Memory)"""
    # Load font
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

    # Calculate dimensions
    temp_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = text.split("\n")
    line_bboxes = [temp_draw.textbbox((0, 0), line, font=font) for line in lines]
    
    max_w = max([b[2] - b[0] for b in line_bboxes]) + 20
    line_h = max([b[3] - b[1] for b in line_bboxes]) + 10
    total_h = line_h * len(lines) + 10

    img = Image.new("RGBA", (int(max_w), int(total_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    current_y = 5
    for i, line in enumerate(lines):
        bbox = line_bboxes[i]
        w = bbox[2] - bbox[0]
        x = (max_w - w) // 2
        # Outline for readability
        for offset in [(-2,-2), (2,-2), (-2,2), (2,2)]:
            draw.text((x+offset[0], current_y+offset[1]), line, font=font, fill=(0,0,0,255))
        # Main text (Yellow)
        draw.text((x, current_y), line, font=font, fill=(255, 255, 0, 255))
        current_y += line_h

    return img, max_w, total_h

def normalize_myanmar(text):
    if not text: return text
    import unicodedata
    return unicodedata.normalize("NFC", text)

def wrap_text(text, max_len=25):
    if not text: return text
    text = normalize_myanmar(text)
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    import re
    cluster_pattern = r"[\u1000-\u102A\u103F\u1040-\u1049][\u102B-\u103E\u1037\u1038\u1039\u103A]*"
    clusters = re.findall(cluster_pattern + r"|[^\u1000-\u1049]", text)
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
    return f"{time.strftime("%H:%M:%S", time.gmtime(s))},{m:03d}"

def parse_srt_text(text):
    # Remove markdown code blocks
    text = re.sub(r"```srt?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text).strip()
    
    # Aggressive SRT cleaning
    # Remove timestamps like 00:00:00,000 --> 00:00:05,000
    # Aggressively remove any timestamp-like patterns and SRT index numbers
    text = re.sub(r"\d{1,2}:\d{1,2}:\d{1,2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{1,2}:\d{1,2}[,.]\d{1,3}", "", text)
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[\d{1,2}:\d{1,2}:\d{1,2}\.\d{3}\s*-->\s*\d{1,2}:\d{1,2}:\d{1,2}\.\d{3}\]", "", text)
    text = re.sub(r"\(\d{1,2}:\d{1,2}:\d{1,2}\.\d{3}\s*-->\s*\d{1,2}:\d{1,2}:\d{1,2}\.\d{3}\)", "", text)
    
    lines = text.split("\n")
    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line: continue
        # Skip lines that are just numbers (SRT indices)
        if re.fullmatch(r"\d+", line): continue
        clean_lines.append(line)
    return "\n".join(clean_lines)

def get_filter(mir, scl, blr, by_px, bh_px, brn, sp, fs, sx, sy):
    """
    Construct FFmpeg filter string using absolute pixel coordinates.
    by_px: Blur Y start in pixels
    bh_px: Blur height in pixels
    sx, sy: Subtitle overlay coordinates in pixels
    """
    base_parts = []
    if mir: base_parts.append("hflip")
    # If scaled, we still need to calculate coordinates based on the output size of this base_str
    if scl: base_parts.append("scale=1.06*iw:-1,crop=iw/1.06:ih/1.06")
    base_str = ",".join(base_parts) if base_parts else "null"

    if not blr:
        fc = f"[0:v]{base_str}[main]"
        if brn and sp and os.path.exists(sp):
            fc += f";[main][1:v]overlay={sx}:{sy}[v]"
        else:
            fc += ";[main]null[v]"
        return fc
    else:
        # Calculate a safe blur radius. FFmpeg boxblur radius must be <= min(w,h)/2 for luma
        # and even smaller for chroma planes (usually min(w,h)/4 for yuv420p).
        # We use a safe radius that works even for small blur areas.
        safe_r = min(15, max(1, bh_px // 4))
        
        # Important: Since we scaled/cropped in base_str, we must use pixel coordinates
        # because 'H' and 'ih' inside the filter now refer to the new (cropped) dimensions.
        fc = f"[0:v]{base_str}[preblur];"
        fc += f"[preblur]split[main][to_blur];"
        fc += f"[to_blur]crop=iw:{bh_px}:0:{by_px},boxblur={safe_r}[blurred];"
        fc += f"[main][blurred]overlay=0:{by_px}[postblur]"
        if brn and sp and os.path.exists(sp):
            fc += f";[postblur][1:v]overlay={sx}:{sy}[v]"
        else:
            fc += ";[postblur]null[v]"
        return fc

# --- MAIN UI ---

# Sidebar content (moved from original app.py)
with st.sidebar:
    st.header("⚙️ ဆက်တင်များ")
    
    # RAM Monitor
    st.subheader("🖥️ RAM စောင့်ကြည့်ရန်")
    def get_ram_usage():
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        return mem_info.rss / (1024 * 1024)  # MB

    ram_used = get_ram_usage()
    # Streamlit Cloud free tier limit is usually 1GB (1024MB)
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
        st.cache_data.clear()
        gc.collect()
        st.success("RAM ရှင်းလင်းပြီးပါပြီ")
        # No rerun here to avoid potential input loss
    
    if st.button("🗑️ Data အားလုံးဖျက်ရန် (Keys မပါ)"):
        # List of keys to preserve
        preserve = [f"key_{i}" for i in range(1, 6)] + ["valid_keys_info", "active_key", "target_min", "target_sec", "blur_y_pos", "blur_h_size", "sub_y_pos", "font_size", "v_speed", "v_pitch"]
        for k in list(st.session_state.keys()):
            if k not in preserve:
                del st.session_state[k]
        st.cache_data.clear()
        gc.collect()
        st.rerun()
    
    st.markdown("---")
    st.subheader("🔑 Gemini API Keys (၅ ခုအထိ)")
    if st.session_state.active_key:
        st.success("🟢 API Key အလုပ်လုပ်နေပါသည်")
    
    api_keys_input = []
    for i in range(1, 6):
        api_keys_input.append(st.text_input(f"API Key {i}", type="password", key=f"key_{i}"))
    api_keys = [k for k in api_keys_input if k]

    if st.button("🔌 Keys အားလုံး စမ်းသပ်ရန်"):
        if not api_keys:
            st.error("API Key အရင်ထည့်ပေးပါ။")
        else:
            st.session_state.valid_keys_info = {}
            with st.spinner("Keys များကို စစ်ဆေးနေသည်..."):
                for i, k in enumerate(api_keys):
                    for ver in API_VERSIONS:
                        try:
                            url = f"https://generativelanguage.googleapis.com/{ver}/models?key={k}"
                            r = requests.get(url, timeout=15)
                            if r.status_code == 200:
                                data = r.json()
                                models = [m["name"].split("/")[-1] for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
                                st.session_state.valid_keys_info[k] = {"version": ver, "models": models}
                                if not st.session_state.active_key: st.session_state.active_key = k
                                st.success(f"✅ Key {i+1} အောင်မြင်ပါသည်။")
                                break
                        except: continue
            st.rerun()

    st.markdown("---")
    st.subheader("🎬 ဗီဒီယို ပုံစံညှိရန်")
    mirror_v = st.checkbox("ဗီဒီယို Mirror လှန်ရန်", value=True)
    scale_v = st.checkbox("ဗီဒီယို Scale 106% ချဲ့ရန်", value=True)

    st.markdown("---")
    blur_s = st.checkbox("မူရင်းစာတန်းထိုး ဝါးရန် (Blur)", value=True)
    if blur_s:
        b_y = plus_minus_slider("ဝါးမည့်နေရာ (Y %)", "blur_y_pos", 0, 100, 1)
        b_h = plus_minus_slider("ဝါးမည့်အကျယ် (H %)", "blur_h_size", 1, 30, 1)
    else:
        st.session_state.blur_y_pos = 85
        st.session_state.blur_h_size = 10

    st.markdown("---")
    burn_s = st.checkbox("မြန်မာစာတန်းထိုး ထည့်ရန်", value=True)
    if burn_s:
        f_s = plus_minus_slider("စာလုံးအရွယ်အစား", "font_size", 5, 100, 1)
        s_y = plus_minus_slider("စာတန်းထိုးနေရာ (Y %)", "sub_y_pos", 0, 100, 1)
    else:
        st.session_state.sub_y_pos = 85

    st.markdown("---")
    if st.button("✨ နေရာ အလိုအလျောက် ရှာရန်"):
        st.session_state.do_detect = True
    show_prev = st.checkbox("👀 ပုံစံ ကြိုတင်ကြည့်ရန်", value=True)

    st.markdown("---")
    st.subheader("⏱️ အချိန် ထိန်းချုပ်ရန်")
    fit_dur = st.toggle("သတ်မှတ်အချိန်အတွင်း အပြီးပြောရန်", value=True)
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
    if "v_speed" not in st.session_state: st.session_state.v_speed = 55
    if "v_pitch" not in st.session_state: st.session_state.v_pitch = 50
    
    v_speed = plus_minus_slider("အသံနှုန်း", "v_speed", 1, 100, 1)
    v_pitch = plus_minus_slider("Pitch", "v_pitch", 1, 100, 1)

# --- MAIN CONTENT ---

# Tabs for different functionalities
tab1, tab2, tab3 = st.tabs(["🎬 Movie Recap", "🗣️ Text-to-Speech", "🤖 AI Chat"]) 

with tab1:
    st.header("🎬 Movie Recap AI Pro")
    st.markdown("အင်္ဂလိပ် ဗီဒီယိုမှ မြန်မာ Movie Recap ပြုလုပ်ပေးသော AI")

    uploaded_file = st.file_uploader("ဗီဒီယိုဖိုင် တင်ပါ (MP4, MOV, MKV)", type=["mp4", "mov", "mkv"])

    if uploaded_file:
        st.session_state.video_path = os.path.join(SCRIPT_DIR, uploaded_file.name)
        with open(st.session_state.video_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"'{uploaded_file.name}' ကို လက်ခံရရှိပါပြီ။")

        # Extract base frame for preview
        if st.session_state.base_frame is None or st.session_state.last_uploaded != uploaded_file.name:
            with st.spinner("ဗီဒီယိုမှ ပုံထုတ်ယူနေသည်..."):
                try:
                    base_frame_path = tempfile.mktemp(suffix=".jpg")
                    cmd = ["ffmpeg", "-i", st.session_state.video_path, "-ss", "00:00:01", "-vframes", "1", base_frame_path]
                    result = subprocess.run(cmd, capture_output=True, check=True)
                    if result.returncode == 0 and os.path.exists(base_frame_path):
                        with open(base_frame_path, "rb") as f:
                            st.session_state.base_frame = f.read()
                        st.session_state.last_uploaded = uploaded_file.name
                        st.success("✅ ဗီဒီယိုမှ ပုံထုတ်ယူခြင်း အောင်မြင်ပါသည်။")
                    else:
                        st.error(f"❌ ဗီဒီယိုမှ ပုံထုတ်ယူရာတွင် အမှားအယွင်းရှိပါသည်။ (FFmpeg Error: {result.stderr.decode()})")
                except subprocess.CalledProcessError as e:
                    st.error(f"❌ ဗီဒီယိုမှ ပုံထုတ်ယူရာတွင် အမှားအယွင်းရှိပါသည်။ (FFmpeg Error: {e.stderr.decode()})")
                except Exception as e:
                    st.error(f"❌ ဗီဒီယိုမှ ပုံထုတ်ယူရာတွင် အမှားအယွင်းရှိပါသည်။ ({e})")
                finally:
                    if os.path.exists(base_frame_path): os.remove(base_frame_path)

        if st.session_state.base_frame and show_prev:
            st.subheader("👀 Layout Preview")
            bp = None
            sub_p = None
            po = None
            filter_script_p = None
            try:
                # Save base frame to temp file
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as bf:
                    bf.write(st.session_state.base_frame)
                    bp = bf.name
                
                with Image.open(bp) as base_img:
                    w, h = base_img.size

                # Calculate subtitle image and position
                temp_text = "မြန်မာစာတန်းထိုးနမူနာ"
                sub_img, sw, sh = create_subtitle_image(temp_text, st.session_state.font_size)
                sub_p = tempfile.mktemp(suffix=".png")
                sub_img.save(sub_p)

                x_p = (w - sw) // 2
                y_p = int(h * (st.session_state.sub_y_pos / 100)) - (sh // 2)

                # Calculate blur position and height in pixels
                by_px = int(h * (st.session_state.blur_y_pos / 100))
                bh_px = int(h * (st.session_state.blur_h_size / 100))

                # Generate FFmpeg filter complex
                fc = get_filter(mirror_v, scale_v, blur_s, by_px, bh_px, burn_s, sub_p, st.session_state.font_size, x_p, y_p)
                
                # Write filter complex to a script file
                filter_script_p = tempfile.mktemp(suffix=".txt")
                with open(filter_script_p, "w", encoding="utf-8") as f:
                    f.write(fc)

                po = tempfile.mktemp(suffix=".jpg")
                inputs = ["-i", bp]
                if burn_s and sub_p and os.path.exists(sub_p): inputs.append("-i"); inputs.append(sub_p)

                cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex_script", filter_script_p, "-map", "[v]", po]
                preview_result = subprocess.run(cmd, capture_output=True)
                if preview_result.returncode != 0:
                    st.error(f"❌ Layout Preview ပုံဖော်ရာတွင် အမှားအယွင်းရှိပါသည်။ (FFmpeg Error: {preview_result.stderr.decode()})")
                
                if os.path.exists(filter_script_p): os.remove(filter_script_p)
                if os.path.exists(po):
                    with Image.open(po) as img_prev:
                        st.image(img_prev)
                    os.remove(po)
            except Exception as e:
                st.error(f"❌ Layout Preview ပုံဖော်ရာတွင် အမှားအယွင်းရှိပါသည်။ ({e})")
            finally:
                if bp and os.path.exists(bp): os.remove(bp)
                if sub_p and os.path.exists(sub_p): os.remove(sub_p)
                if po and os.path.exists(po): os.remove(po)
                if filter_script_p and os.path.exists(filter_script_p): os.remove(filter_script_p)

    if not api_keys: st.warning("⚠️ Sidebar တွင် Gemini API Key ထည့်ပေးပါ")
    elif st.button("🚀 စတင်လုပ်ဆောင်ရန်"):
        # Check if ffmpeg is available
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            st.error("FFmpeg ကို ရှာမတွေ့ပါ။ (System တွင် FFmpeg ထည့်သွင်းထားရန် လိုအပ်ပါသည်)")
            st.stop()

        if st.session_state.video_path is None:
            st.error("ဗီဒီယိုဖိုင် အရင်တင်ပေးပါ။")
            st.stop()

        if st.session_state.active_key is None:
            st.error("အသုံးပြုနိုင်သော API Key မရှိပါ။ (Keys များကို စမ်းသပ်ပေးပါ)")
            st.stop()

        st.session_state.processing_done = False
        st.session_state.myanmar_text = None
        st.session_state.audio_path = None
        st.session_state.srt_data = None

        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            # Step 1: Transcribe and Translate
            status_text.write("1/4: ဗီဒီယိုကို စာသားအဖြစ် ပြောင်းလဲနေသည်...")
            progress_bar.progress(25)
            # Placeholder for actual transcription/translation logic
            # This part needs to be implemented using Gemini API
            # For now, we'll assume English text is available from transcription
            # and use Gemini to summarize and translate.
            
            # First, extract audio from video (assuming video is uploaded)
            audio_extract_path = tempfile.mktemp(suffix=".mp3")
            cmd_extract_audio = ["ffmpeg", "-y", "-i", st.session_state.video_path, "-vn", "-acodec", "libmp3lame", "-q:a", "2", audio_extract_path]
            subprocess.run(cmd_extract_audio, capture_output=True, check=True)

            # Placeholder for actual Speech-to-Text (English)
            # In a real scenario, you would use a Speech-to-Text API here (e.g., Google Speech-to-Text, OpenAI Whisper)
            # For demonstration, we'll use a dummy English text.
            english_transcript = "This is a sample English transcript from the video. The AI will now summarize and translate this into Myanmar for the movie recap."

            # Use Gemini to summarize and translate
            client = get_gemini_client(st.session_state.active_key)
            model_name = "gemini-1.5-flash" # Or choose a model from st.session_state.valid_keys_info[st.session_state.active_key]["models"]

            prompt = f"Summarize the following English movie transcript into a concise movie recap in Myanmar language. Also, generate SRT formatted subtitles for the Myanmar recap. The recap should be around {st.session_state.target_min} minutes and {st.session_state.target_sec} seconds long if possible.\n\nEnglish Transcript: {english_transcript}\n\nOutput Format:\nSummary: [Myanmar Summary]\nSRT:\n[SRT formatted subtitles with timestamps]"

            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2048 # Adjust as needed
            )
            gemini_output = response.choices[0].message.content

            # Parse Gemini output
            summary_match = re.search(r"Summary: (.*?)SRT:", gemini_output, re.DOTALL)
            srt_match = re.search(r"SRT:\n(.*)", gemini_output, re.DOTALL)

            if summary_match and srt_match:
                st.session_state.myanmar_text = summary_match.group(1).strip()
                st.session_state.srt_data = srt_match.group(1).strip()
            else:
                st.error("Gemini API မှ ပြန်ကြားချက်ကို ပုံစံတကျ ခွဲထုတ်၍ မရပါ။")
                st.session_state.myanmar_text = "Gemini မှ ပြန်ကြားချက်ကို ခွဲထုတ်၍ မရပါ။"
                st.session_state.srt_data = ""

            if os.path.exists(audio_extract_path): os.remove(audio_extract_path)

            # Step 2: Text-to-Speech
            status_text.write("2/4: မြန်မာစာသားကို အသံအဖြစ် ပြောင်းလဲနေသည်...")
            progress_bar.progress(50)
            audio_output_path = tempfile.mktemp(suffix=".mp3")
            
            # Convert speed and pitch to edge-tts format
            # speed: +{x}% or -{x}% (default 0) -> 1 to 100 maps to -50% to +50%
            # pitch: +{x}Hz or -{x}Hz (default 0) -> 1 to 100 maps to -50Hz to +50Hz (approx)
            # Edge-TTS default speed is 1.0, pitch is 0.0
            # Let's map 55 to 0%, 1 to -50%, 100 to +50%
            tts_speed_percent = int(np.clip((st.session_state.v_speed - 55) / 45 * 50, -50, 50)) # -50 to +50
            tts_pitch_hz = int(np.clip((st.session_state.v_pitch - 50) / 50 * 50, -50, 50)) # -50 to +50

            communicate = edge_tts.Communicate(st.session_state.myanmar_text, v_id, rate=f"{{tts_speed_percent}}%", pitch=f"{{tts_pitch_hz}}Hz")
            asyncio.run(communicate.save(audio_output_path))
            st.session_state.audio_path = audio_output_path

            # Step 3: Combine Video, Audio, and Subtitles
            status_text.write("3/4: ဗီဒီယို၊ အသံနှင့် စာတန်းထိုးများ ပေါင်းစပ်နေသည်...")
            progress_bar.progress(75)

            final_video_path = tempfile.mktemp(suffix=".mp4")
            srt_file_path = tempfile.mktemp(suffix=".srt")
            with open(srt_file_path, "w", encoding="utf-8") as f: f.write(st.session_state.srt_data)

            video_duration = get_dur(st.session_state.video_path)
            audio_duration = get_dur(st.session_state.audio_path)

            # Calculate video speed factor
            speed_factor = 1.0
            if target_sec > 0:
                speed_factor = video_duration / target_sec
                speed_factor = np.clip(speed_factor, 0.5, 2.0) # Limit speed adjustment
            
            # FFmpeg command to combine video, audio, and burn subtitles
            # Adjust video speed using setpts filter
            # Adjust audio duration using atempo filter (if needed, though edge-tts handles duration)
            
            # Base video input
            ffmpeg_cmd = ["ffmpeg", "-y", "-i", st.session_state.video_path]
            
            # Audio input
            ffmpeg_cmd.extend(["-i", st.session_state.audio_path])

            # Filter complex for video and audio
            filter_complex = []
            video_filters = []
            audio_filters = []

            # Video speed adjustment
            if abs(speed_factor - 1.0) > 0.01:
                video_filters.append(f"setpts=PTS/{speed_factor}")
            
            # Mirror and Scale
            if mirror_v: video_filters.append("hflip")
            if scale_v: video_filters.append("scale=1.06*iw:-1,crop=iw/1.06:ih/1.06")

            # Subtitle burning
            if burn_s:
                # Use ass filter for better font rendering and styling
                video_filters.append(f"subtitles={srt_file_path}:force_style=\'Fontname=Pyidaungsu,FontSize={st.session_state.font_size},PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0\' ")
            
            # Blur original subtitle area
            if blur_s:
                # Get video dimensions for pixel calculation
                probe_cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", st.session_state.video_path]
                probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
                width, height = map(int, probe_result.stdout.strip().split("x"))

                by_px = int(height * (st.session_state.blur_y_pos / 100))
                bh_px = int(height * (st.session_state.blur_h_size / 100))
                safe_r = min(15, max(1, bh_px // 4))

                # Apply blur before other video filters if possible, or create a separate stream
                # For simplicity, apply after scaling/mirroring for now
                video_filters.append(f"split[main][to_blur];[to_blur]crop=iw:{bh_px}:0:{by_px},boxblur={safe_r}[blurred];[main][blurred]overlay=0:{by_px}")

            if video_filters: filter_complex.append(f"[0:v]{','.join(video_filters)}[v]")
            else: filter_complex.append("[0:v]copy[v]") # No video filters, just copy

            # Audio stream (from input 1, which is the generated audio)
            audio_filters.append(f"[1:a]atempo=1.0[a]") # No speed adjustment needed for audio if TTS already matched duration

            ffmpeg_cmd.extend(["-filter_complex", ";".join(filter_complex + audio_filters)])
            ffmpeg_cmd.extend(["-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", "-shortest", final_video_path])

            final_result = subprocess.run(ffmpeg_cmd, capture_output=True)
            if final_result.returncode != 0:
                st.error(f"❌ ဗီဒီယိုပေါင်းစပ်ရာတွင် အမှားအယွင်းရှိပါသည်။ (FFmpeg Error: {final_result.stderr.decode()})")
            else:
                st.session_state.video_path = final_video_path
                st.session_state.processing_done = True
                st.success("✅ ဗီဒီယို ပြုလုပ်ခြင်း ပြီးစီးပါပြီ။")

        except Exception as e:
            st.error(f"❌ လုပ်ဆောင်နေစဉ် အမှားအယွင်း ဖြစ်ပေါ်ပါသည်။ ({e})")
        finally:
            progress_bar.empty()
            status_text.empty()
            if os.path.exists(audio_output_path): os.remove(audio_output_path)
            if os.path.exists(srt_file_path): os.remove(srt_file_path)

    if st.session_state.processing_done and st.session_state.video_path and os.path.exists(st.session_state.video_path):
        st.subheader("🎉 ရလဒ်ဗီဒီယို")
        st.video(st.session_state.video_path)
        with open(st.session_state.video_path, "rb") as file:
            st.download_button(
                label="ဗီဒီယို ဒေါင်းလုဒ်ဆွဲရန်",
                data=file,
                file_name="movie_recap_final.mp4",
                mime="video/mp4"
            )

with tab2:
    st.header("🗣️ Text-to-Speech (TTS)")
    st.markdown("မြန်မာစာသားကို သဘာဝကျသော အသံအဖြစ် ပြောင်းလဲပါ။")

    tts_text = st.text_area("ဤနေရာတွင် မြန်မာစာသား ရိုက်ထည့်ပါ", height=200, key="tts_input_text")
    tts_voice_choice = st.selectbox("အသံရွေးချယ်ပါ", ["သီဟ (အမျိုးသားသံ)", "နီလာ (အမျိုးသမီးသံ)"], key="tts_voice_choice")
    tts_voice_id = "my-MM-ThihaNeural" if "သီဟ" in tts_voice_choice else "my-MM-NilarNeural"

    tts_speed = plus_minus_slider("အသံနှုန်း", "tts_v_speed", 1, 100, 1)
    tts_pitch = plus_minus_slider("Pitch", "tts_v_pitch", 1, 100, 1)

    if st.button("🔊 အသံထုတ်လုပ်ရန်", key="generate_tts_btn"):
        if not tts_text:
            st.error("အသံထုတ်လုပ်ရန် စာသားထည့်ပေးပါ။")
        else:
            with st.spinner("အသံထုတ်လုပ်နေသည်..."):
                try:
                    tts_output_path = tempfile.mktemp(suffix=".mp3")
                    tts_speed_percent = int((tts_speed - 55) / 45 * 50)
                    tts_pitch_hz = int((tts_pitch - 50) / 50 * 50)

                    communicate = edge_tts.Communicate(tts_text, tts_voice_id, rate=f"{{tts_speed_percent}}%", pitch=f"{{tts_pitch_hz}}Hz")
                    asyncio.run(communicate.save(tts_output_path))
                    
                    st.audio(tts_output_path, format="audio/mp3")
                    with open(tts_output_path, "rb") as file:
                        st.download_button(
                            label="အသံဖိုင် ဒေါင်းလုဒ်ဆွဲရန်",
                            data=file,
                            file_name="myanmar_tts.mp3",
                            mime="audio/mp3"
                        )
                except Exception as e:
                    st.error(f"❌ အသံထုတ်လုပ်ရာတွင် အမှားအယွင်းရှိပါသည်။ ({e})")
                finally:
                    if os.path.exists(tts_output_path): os.remove(tts_output_path)

with tab3:
    st.header("🤖 AI Chat")
    st.markdown("Gemini AI နှင့် စကားပြောပါ။")

    if "messages" not in st.session_state: st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("မေးခွန်းတစ်ခု မေးပါ..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""
            client = get_gemini_client(st.session_state.active_key)
            model_name = "gemini-1.5-flash" # Or choose a model from st.session_state.valid_keys_info[st.session_state.active_key]["models"]

            try:
                # Prepare messages for Gemini API
                gemini_messages = []
                for msg in st.session_state.messages:
                    gemini_messages.append({"role": "user" if msg["role"] == "user" else "model", "content": msg["content"]})

                response = client.chat.completions.create(
                    model=model_name,
                    messages=gemini_messages,
                    stream=True # Enable streaming for chat
                )

                for chunk in response:
                    if chunk.choices[0].delta.content is not None:
                        full_response += chunk.choices[0].delta.content
                        message_placeholder.markdown(full_response + "▌")
                message_placeholder.markdown(full_response)
            except Exception as e:
                st.error(f"❌ Gemini AI Chat မှ ပြန်ကြားရာတွင် အမှားအယွင်းရှိပါသည်။ ({e})")
                full_response = ""
        st.session_state.messages.append({"role": "assistant", "content": full_response})


with st.expander("🔐 Admin Panel"):
    admin_password = st.text_input("Admin Password", type="password", key="admin_password")
    if admin_password == os.getenv("ADMIN_PASSWORD", "admin123"):
        st.success("Welcome, Admin!")
        st.subheader("📊 User Statistics (Placeholder)")
        st.write("Total Users: 100")
        st.write("Active Users Today: 25")
        st.write("Total Movie Recaps Generated: 500")
        st.write("Total TTS Conversions: 1000")
        
        st.subheader("⚙️ System Settings (Placeholder)")
        new_admin_password = st.text_input("Change Admin Password", type="password", key="new_admin_password")
        if st.button("Update Admin Password", key="update_admin_password_btn"):
            if new_admin_password:
                # In a real application, you would securely store this password (e.g., hashed)
                # For this example, we'll just print a message.
                st.info("Admin password updated (in a real app, this would be saved securely).")
            else:
                st.warning("Please enter a new password.")
    else:
        st.warning("Incorrect password.")

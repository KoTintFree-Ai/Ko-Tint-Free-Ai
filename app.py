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

# Get the directory where this script is located (for font file path)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(SCRIPT_DIR, "Pyidaungsu.ttf")

st.set_page_config(
    page_title="Movie Recap AI Pro V6.2",
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
    keys = ['myanmar_text', 'audio_path', 'srt_data', 'video_path', 'base_frame', 'last_uploaded', 'processing_done', 'valid_keys_info', 'active_key']
    for k in keys:
        if k not in st.session_state: st.session_state[k] = None
    for i in range(1, 6):
        if f'key_{i}' not in st.session_state: st.session_state[f'key_{i}'] = ""
    if st.session_state.processing_done is None: st.session_state.processing_done = False
    if st.session_state.valid_keys_info is None: st.session_state.valid_keys_info = {}
    if 'do_test_keys' not in st.session_state: st.session_state.do_test_keys = False
    if 'blur_y_pos' not in st.session_state: st.session_state.blur_y_pos = 85.0
    if 'blur_h_size' not in st.session_state: st.session_state.blur_h_size = 10.0
    if 'sub_y_pos' not in st.session_state: st.session_state.sub_y_pos = 85.0
    if 'font_size' not in st.session_state: st.session_state.font_size = 22

init_state()

st.title("🎬 Movie Recap AI Pro V6.2")
st.markdown("အင်္ဂလိပ် ဗီဒီယိုမှ မြန်မာ Movie Recap ပြုလုပ်ပေးသော AI (Unicode & Wrap Fix)")

# --- HELPER: CONTROL WITH BUTTONS, SLIDER & TEXT INPUT (STABLE VERSION) ---
def plus_minus_control(label, key, min_val, max_val, step=1.0):
    st.write(f"**{label}**")
    
    if key not in st.session_state:
        st.session_state[key] = float(min_val)
        
    # Format value for display (remove .0 if it exists)
    def fmt_val(v):
        return str(int(v)) if float(v) == int(v) else str(round(v, 1))

    # Synchronization callbacks
    def on_slider_change():
        st.session_state[key] = st.session_state[f"sld_{key}"]
        st.session_state[f"txt_{key}"] = fmt_val(st.session_state[key])

    def on_text_change():
        try:
            new_val = float(st.session_state[f"txt_{key}"])
            st.session_state[key] = float(np.clip(new_val, min_val, max_val))
            st.session_state[f"sld_{key}"] = st.session_state[key]
            st.session_state[f"txt_{key}"] = fmt_val(st.session_state[key])
        except:
            st.session_state[f"txt_{key}"] = fmt_val(st.session_state[key])

    def on_btn_click(delta):
        st.session_state[key] = float(np.clip(st.session_state[key] + delta, min_val, max_val))
        st.session_state[f"sld_{key}"] = st.session_state[key]
        st.session_state[f"txt_{key}"] = fmt_val(st.session_state[key])

    # Sync widget states with master state
    if f"sld_{key}" not in st.session_state or st.session_state[f"sld_{key}"] != st.session_state[key]:
        st.session_state[f"sld_{key}"] = st.session_state[key]
    if f"txt_{key}" not in st.session_state or st.session_state[f"txt_{key}"] != fmt_val(st.session_state[key]):
        st.session_state[f"txt_{key}"] = fmt_val(st.session_state[key])

    col1, col2, col3 = st.columns([1, 4, 1])
    with col1:
        st.button("➖", key=f"btn_min_{key}", on_click=on_btn_click, args=(-step,))
    with col2:
        st.slider(label, float(min_val), float(max_val), step=float(step), 
                  key=f"sld_{key}", on_change=on_slider_change, label_visibility="collapsed")
    with col3:
        st.button("➕", key=f"btn_pls_{key}", on_click=on_btn_click, args=(step,))
        
    col_l, col_i = st.columns([3, 1])
    with col_l: st.caption("နံပါတ် အတိအကျ ရိုက်ရန် (Enter နှိပ်ပါ)")
    with col_i:
        st.text_input(label, key=f"txt_{key}", on_change=on_text_change, label_visibility="collapsed")
        
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
        st.rerun()
    
    st.markdown("---")
    st.subheader("🔑 Gemini API Keys (၅ ခုအထိ)")
    
    # Improved API Key Status Indicator
    if st.session_state.active_key:
        active_idx = 0
        if st.session_state.active_key == st.session_state.get('key_1'): active_idx = 1
        elif st.session_state.active_key == st.session_state.get('key_2'): active_idx = 2
        elif st.session_state.active_key == st.session_state.get('key_3'): active_idx = 3
        elif st.session_state.active_key == st.session_state.get('key_4'): active_idx = 4
        elif st.session_state.active_key == st.session_state.get('key_5'): active_idx = 5
        
        if active_idx > 0:
            st.success(f"🟢 လက်ရှိအသုံးပြုနေသော Key: API Key {active_idx}")
    else:
        st.info("💡 Key ထည့်ပြီး စတင်လုပ်ဆောင်ပါ")

    # Bulk Paste Area
    with st.expander("📋 Key အများအပြား တစ်ခါတည်းထည့်ရန်"):
        bulk_text = st.text_area("ဒီနေရာမှာ Key များကို တစ်ကြောင်းချင်းစီ Paste ချလိုက်ပါ", height=100)
        if st.button("📥 အားလုံးထဲသို့ ဖြည့်သွင်းရန်"):
            keys = [k.strip() for k in bulk_text.replace(',', '\n').split('\n') if k.strip()]
            for i in range(5):
                st.session_state[f"key_{i+1}"] = keys[i] if i < len(keys) else ""
            st.rerun()
            
    k1 = st.text_input("API Key 1", type="password", key="key_1")
    k2 = st.text_input("API Key 2", type="password", key="key_2")
    k3 = st.text_input("API Key 3", type="password", key="key_3")
    k4 = st.text_input("API Key 4", type="password", key="key_4")
    k5 = st.text_input("API Key 5", type="password", key="key_5")
    api_keys = [k for k in [k1, k2, k3, k4, k5] if k]

    col_key1, col_key2 = st.columns(2)
    with col_key1:
        if st.button("🔌 စမ်းသပ်ရန်"):
            st.session_state.do_test_keys = True
    with col_key2:
        if st.button("🗑️ အားလုံးဖျက်ရန်"):
            for i in range(5): st.session_state[f"key_{i+1}"] = ""
            st.session_state.active_key = None
            st.rerun()

    if st.session_state.do_test_keys:
        if not api_keys:
            st.error("API Key အရင်ထည့်ပေးပါ။")
            st.session_state.do_test_keys = False
        else:
            st.session_state.valid_keys_info = {}
            for i, k in enumerate(api_keys):
                st.write(f"--- Key {i+1} ကို စစ်ဆေးနေသည် ---")
                success = False
                for ver in API_VERSIONS:
                    url = f"https://generativelanguage.googleapis.com/{ver}/models?key={k}"
                    try:
                        r = requests.get(url, timeout=15)
                        if r.status_code == 200:
                            models_data = r.json().get('models', [])
                            available_models = [m['name'].split('/')[-1] for m in models_data if 'generateContent' in m.get('supportedGenerationMethods', [])]
                            if available_models:
                                st.success(f"✅ Key {i+1} အလုပ်လုပ်ပါသည်။ (Version: {ver})")
                                st.session_state.valid_keys_info[k] = {"version": ver, "models": available_models}
                                success = True
                                break
                    except: pass
                if success: 
                    st.info(f"Key {i+1} ကို စိတ်ချစွာ အသုံးပြုနိုင်ပါသည်။")
                    if not st.session_state.active_key:
                        st.session_state.active_key = k
            st.session_state.do_test_keys = False
            st.rerun()

    st.markdown("---")
    st.subheader("🎬 ဗီဒီယို ပုံစံညှိရန်")
    mirror_v = st.checkbox("ဗီဒီယို Mirror လှန်ရန်", value=True)
    scale_v = st.checkbox("ဗီဒီယို Scale 106% ချဲ့ရန်", value=True)

    st.markdown("---")
    blur_s = st.checkbox("မူရင်းစာတန်းထိုး ဝါးရန် (Blur)", value=True)
    if blur_s:
        b_y = plus_minus_control("ဝါးမည့်နေရာ (Y %)", "blur_y_pos", 0, 100, 1)
        b_h = plus_minus_control("ဝါးမည့်အကျယ် (H %)", "blur_h_size", 1, 30, 1)

    st.markdown("---")
    burn_s = st.checkbox("မြန်မာစာတန်းထိုး ထည့်ရန်", value=True)
    if burn_s:
        f_s = plus_minus_control("စာလုံးအရွယ်အစား", "font_size", 5, 100, 1)
        s_y = plus_minus_control("စာတန်းထိုးနေရာ (Y %)", "sub_y_pos", 0, 100, 1)

    st.markdown("---")
    if st.button("✨ နေရာ အလိုအလျောက် ရှာရန်"):
        st.session_state.do_detect = True
    show_prev = st.checkbox("👀 ပုံစံ ကြိုတင်ကြည့်ရန်", value=True)

    st.markdown("---")
    st.subheader("⏱️ အချိန် ထိန်းချုပ်ရန်")
    fit_dur = st.toggle("သတ်မှတ်အချိန်အတွင်း အပြီးပြောရန်", value=True)
    target_sec = 0
    if fit_dur:
        c1, c2 = st.columns(2)
        with c1: tm = st.number_input("မိနစ်", 0, 60, 2)
        with c2: ts = st.number_input("စက္ကန့်", 0, 59, 30)
        target_sec = (tm * 60) + ts

    st.markdown("---")
    st.subheader("🔊 အသံ ဆက်တင်များ")
    v_choice = st.selectbox("အသံရွေးချယ်ပါ", ["သီဟ (အမျိုးသားသံ)", "နီလာ (အမျိုးသမီးသံ)"])
    v_id = "my-MM-ThihaNeural" if "သီဟ" in v_choice else "my-MM-NilarNeural"
    v_speed = st.slider("အသံနှုန်း", 1, 100, 55)
    v_pitch = st.slider("Pitch", 1, 100, 50)

    if st.button("🧹 အားလုံးဖျက်ရန်"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

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
    text = text.strip()
    blocks = re.split(r'\n\s*\n', text)
    segments = []
    for block in blocks:
        lines = block.strip().split('\n')
        found_srt = False
        for i, line in enumerate(lines):
            if '-->' in line:
                subtitle_text = ' '.join(lines[i+1:]).strip()
                if subtitle_text:
                    segments.append(subtitle_text)
                found_srt = True
                break
        if not found_srt and len(lines) > 0:
            text_content = '\n'.join(lines)
            text_content = re.sub(r'^\d+\s*\n', '', text_content).strip()
            if text_content and not re.match(r'^[\d:,.\s\->]+$', text_content):
                segments.append(text_content)
    return [s.strip() for s in segments if s.strip()]

async def gen_audio_srt(text, out_p, vid, spd, ptc, target=0):
    rate = f"+{int((spd-50)*2)}%" if spd>=50 else f"{int((spd-50)*2)}%"
    pitch = f"+{int((ptc-50)*2)}Hz" if ptc>=50 else f"{int((ptc-50)*2)}Hz"
    segments = parse_srt_text(text)
    if not segments: segments = [text]
    
    temp_files = []
    cur_t = 0.0
    srt_blocks = []
    
    # Process segments in larger chunks for natural flow
    for idx, txt in enumerate(segments):
        clean_txt = re.sub(r'^\d+\s*', '', txt).strip()
        if not clean_txt: continue
        import unicodedata
        clean_txt = unicodedata.normalize('NFC', clean_txt)
        
        p = tempfile.mktemp(suffix=".mp3")
        try:
            # Generate audio for the full segment to maintain natural intonation
            communicate = edge_tts.Communicate(clean_txt, vid, rate=rate, pitch=pitch)
            await communicate.save(p)
            
            # Trim silence from the start and end of the generated audio to prevent "choppiness"
            p_trimmed = tempfile.mktemp(suffix=".mp3")
            subprocess.run(["ffmpeg", "-y", "-i", p, "-af", "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-50dB:detection=peak,silenceremove=stop_periods=1:stop_silence=0.1:stop_threshold=-50dB:detection=peak", p_trimmed], capture_output=True)
            
            d = get_dur(p_trimmed)
            if d > 0:
                # Use a slightly longer wrap length for more natural reading flow
                wrapped_txt = wrap_text(clean_txt, max_len=25)
                srt_blocks.append(f"{len(srt_blocks)+1}\n{fmt_srt(cur_t)} --> {fmt_srt(cur_t+d)}\n{wrapped_txt}\n\n")
                temp_files.append(p_trimmed)
                cur_t += d # Minimal gap for natural flow
                
                # Cleanup original untrimmed file
                if os.path.exists(p): os.remove(p)
        except: continue
        
    if not temp_files: raise Exception("အသံဖိုင် ထုတ်လုပ်ခြင်း မအောင်မြင်ပါ။")
    
    raw = tempfile.mktemp(suffix=".mp3")
    l_p = tempfile.mktemp(suffix=".txt")
    with open(l_p, "w", encoding='utf-8') as f: f.write("\n".join([f"file '{p}'" for p in temp_files]))
    
    # Concat with a small crossfade or just tight coupling
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", l_p, "-c", "copy", raw], capture_output=True)
    
    total = get_dur(raw)
    if target > 0 and total > 0:
        factor = total / target
        # Expand factor range for better fitting, but still keep it somewhat natural
        factor = np.clip(factor, 0.5, 2.0)
        
        # Use high-quality time stretching and exact duration trimming/padding
        # atempo filter adjusts speed, then we use -t to ensure exact target duration
        subprocess.run(["ffmpeg", "-y", "-i", raw, "-filter:a", f"atempo={factor}", "-t", str(target), out_p], capture_output=True)
        
        # Re-calculate factor based on actual applied duration for SRT sync
        actual_factor = total / target
        
        final_srt = []
        for line in "".join(srt_blocks).splitlines(keepends=True):
            if "-->" in line:
                s, e = line.split(" --> ")
                s_s = sum(float(x)*60**i for i,x in enumerate(reversed(s.replace(",",".").split(":")))) / actual_factor
                e_s = sum(float(x)*60**i for i,x in enumerate(reversed(e.replace(",",".").split(":")))) / actual_factor
                # Ensure timings don't exceed target
                s_s = min(s_s, target)
                e_s = min(e_s, target)
                final_srt.append(f"{fmt_srt(s_s)} --> {fmt_srt(e_s)}\n")
            else: final_srt.append(line)
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
        # Important: Since we scaled/cropped in base_str, we must use pixel coordinates
        # because 'H' and 'ih' inside the filter now refer to the new (cropped) dimensions.
        fc = f"[0:v]{base_str}[preblur];"
        fc += f"[preblur]split[main][to_blur];"
        fc += f"[to_blur]crop=iw:{bh_px}:0:{by_px},boxblur=15[blurred];"
        fc += f"[main][blurred]overlay=0:{by_px}[postblur]"
        if brn and sp and os.path.exists(sp):
            fc += f";[postblur][1:v]overlay={sx}:{sy}[v]"
        else:
            fc += ";[postblur]null[v]"
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

    if st.session_state.get("do_detect"):
        tp = os.path.join(tempfile.gettempdir(), f"input_{fid}." + up.name.split(".")[-1])
        try:
            d = get_dur(tp); tf = tempfile.mktemp(suffix=".jpg")
            subprocess.run(["ffmpeg", "-y", "-ss", str(d*0.1), "-i", tp, "-frames:v", "1", tf], capture_output=True)
            img = Image.open(tf).convert('L'); w, h = img.size
            arr = np.array(img.crop((0, int(h*0.6), w, h)))
            var = np.var(arr, axis=1); rows = np.where(var > np.mean(var)*2)[0]
            if len(rows) > 0:
                st.session_state.blur_y_pos = float(((int(h*0.6) + rows[0] - 5) / h) * 100)
                st.session_state.blur_h_size = float(((rows[-1] - rows[0] + 10) / h) * 100)
            os.remove(tf)
        except: pass
        st.session_state.do_detect = False; st.rerun()

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
        
        # Calculate preview overlay position
        x_p = (w - sw) // 2
        y_p = int(h * (st.session_state.sub_y_pos / 100)) - (sh // 2)
        
        # Calculate absolute pixel coordinates for blur
        by_px = int(h * (st.session_state.blur_y_pos / 100))
        bh_px = int(h * (st.session_state.blur_h_size / 100))
        
        # Pass calculated pixel coordinates directly to get_filter
        fc = get_filter(mirror_v, scale_v, blur_s, by_px, bh_px, burn_s, sub_p, st.session_state.font_size, x_p, y_p)
        
        filter_script_p = tempfile.mktemp(suffix=".txt")
        filter_str = fc
        with open(filter_script_p, "w", encoding="utf-8") as f: f.write(filter_str)
        inputs = ["-i", bp, "-i", sub_p] if burn_s else ["-i", bp]
        if len(filter_str) < 2000:
            cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", filter_str, "-map", "[v]", po]
        else:
            cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex_script", filter_script_p, "-map", "[v]", po]
        subprocess.run(cmd, capture_output=True)
        if os.path.exists(filter_script_p): os.remove(filter_script_p)
        if os.path.exists(po):
            # Read image into memory before deleting to ensure it shows correctly in Streamlit
            with Image.open(po) as img_prev:
                st.image(img_prev)
            os.remove(po)
        if os.path.exists(bp): os.remove(bp)
        if os.path.exists(sub_p): os.remove(sub_p)

    if not api_keys: st.warning("⚠️ Sidebar တွင် Gemini API Key ထည့်ပေးပါ")
    elif st.button("🚀 စတင်လုပ်ဆောင်ရန်"):
        # Check if ffmpeg is available
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            st.error("❌ FFmpeg မရရှိပါ။ packages.txt ဖိုင်တွင် ffmpeg ပါရှိကြောင်း သေချာပါစေ။")
            st.info("GitHub repo မှာ packages.txt ဖိုင်ကို အောက်ပါအတိုင်း ထားပါ:\n```\nffmpeg\nlibraqm-dev\nlibharfbuzz-dev\nlibfribidi-dev\n```")
        else:
            prg = st.progress(0); stt = st.empty()
            try:
                if st.session_state.video_path and os.path.exists(st.session_state.video_path):
                    try: os.remove(st.session_state.video_path)
                    except: pass
                if st.session_state.audio_path and os.path.exists(st.session_state.audio_path):
                    try: os.remove(st.session_state.audio_path)
                    except: pass

                stt.text("📊 အဆင့် ၁: အသံဖိုင်ကို ပြင်ဆင်နေပါသည်...")
                prg.progress(10)
                tp = os.path.join(tempfile.gettempdir(), f"input_{fid}." + up.name.split(".")[-1])
                ag = tempfile.mktemp(suffix=".mp3")
                if up.name.lower().endswith((".mp4", ".mov", ".avi")):
                    subprocess.run(["ffmpeg", "-y", "-i", tp, "-vn", "-acodec", "libmp3lame", "-q:a", "4", ag], capture_output=True)
                else: shutil.copy(tp, ag)

                stt.text("⏳ အဆင့် ၂: ဘာသာပြန်နေပါသည် (Gemini)...")
                prg.progress(30)
                prm = f"""Listen to this audio and translate it into a Myanmar Movie Recap style narration.
Target duration: {target_sec} seconds.
Output ONLY valid SRT subtitle format with proper timing.

IMPORTANT RULES FOR MYANMAR LANGUAGE:
1. Use Standard Myanmar Unicode.
2. Ensure correct spelling for movie recap terms.
3. Keep the narration natural, dramatic, and conversational (Recap Style).
4. Use smooth sentence transitions. Avoid extremely short, choppy sentences.
5. For foreign names, use common Myanmar phonetic transcriptions.

FORMATTING RULES:
1. Each subtitle block should contain a complete thought or a natural phrase (approx 10-15 words).
2. Use proper SRT format: index, timestamp, subtitle text, blank line.
3. Ensure the total duration of the narration matches the target duration of {target_sec} seconds closely.
4. Do NOT include any text outside the SRT format."""
                with open(ag, 'rb') as f: b64 = base64.b64encode(f.read()).decode()
                cont = [{"role":"user","parts":[{"text":prm},{"inline_data":{"mime_type":"audio/mpeg","data":b64}}]}]

                srt_res = None
                errors = []
                for k in api_keys:
                    info = st.session_state.valid_keys_info.get(k)
                    versions = [info['version']] if info else API_VERSIONS
                    models = info['models'] if info else DEFAULT_MODELS
                    for ver in versions:
                        for m in models:
                            try:
                                url = f"https://generativelanguage.googleapis.com/{ver}/models/{m}:generateContent?key={k}"
                                r = requests.post(url, json={"contents":cont}, timeout=300)
                                if r.status_code == 200:
                                    data = r.json()
                                    if 'candidates' in data and data['candidates'][0]['content']['parts']:
                                        srt_res = data['candidates'][0]['content']['parts'][0]['text']
                                        if srt_res:
                                            st.session_state.active_key = k
                                            break
                                    else: errors.append(f"Key {api_keys.index(k)+1} - {m}: အဖြေမထွက်ပါ။")
                                else:
                                    try: msg = r.json().get('error', {}).get('message', r.text)
                                    except: msg = r.text
                                    errors.append(f"Key {api_keys.index(k)+1} - {m}: {translate_error(msg, r.status_code)}")
                            except Exception as e: errors.append(f"Key {api_keys.index(k)+1} - {m}: {translate_error(str(e))}")
                        if srt_res: break
                    if srt_res: break

                if not srt_res:
                    st.error("❌ Gemini ဘာသာပြန်ခြင်း မအောင်မြင်ပါ")
                    for e in errors: st.info(e)
                    raise Exception("ဘာသာပြန်ခြင်း မလုပ်ဆောင်နိုင်ပါ။")

                stt.text("🔊 အဆင့် ၃: အသံဖိုင်နှင့် Timing ညှိနေပါသည်...")
                prg.progress(60)
                ao_name = f"audio_{fid}_{int(time.time())}.mp3"
                ao = os.path.join(tempfile.gettempdir(), ao_name)
                st.session_state.srt_data, _ = asyncio.run(gen_audio_srt(srt_res, ao, v_id, v_speed, v_pitch, target_sec if fit_dur else 0))
                st.session_state.audio_path = ao

                if up.name.lower().endswith((".mp4", ".mov", ".avi")):
                    stt.text("🎬 အဆင့် ၄: ဗီဒီယိုကို တည်းဖြတ်နေပါသည် (Rendering)...")
                    prg.progress(80)
                    stt.text("🎬 အဆင့် ၄: စာတန်းထိုးများကို ပုံဖော်နေပါသည်...")
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

                    overlay_filters = []
                    temp_imgs = []
                    for i, seg in enumerate(segments):
                        simg, sw, sh = create_subtitle_image(seg['text'], st.session_state.font_size)
                        spath = os.path.join(sub_dir, f"sub_{i}.png")
                        simg.save(spath)
                        temp_imgs.append(spath)
                        
                        # Calculate center position
                        x_pos = (vw - sw) // 2
                        y_pos = int(vh * (st.session_state.sub_y_pos / 100)) - (sh // 2)
                        
                        safe_spath = spath.replace('\\', '/').replace(':', '\\\\').replace("'", "'\\\\\''")
                        overlay_filters.append(f"movie='{safe_spath}'[s{i}];[v][s{i}]overlay={x_pos}:{y_pos}:enable='between(t,{seg['start']},{seg['end']})'[v]")

                    # Calculate absolute pixel coordinates for blur during rendering
                    by_px_r = int(vh * (st.session_state.blur_y_pos / 100))
                    bh_px_r = int(vh * (st.session_state.blur_h_size / 100))
                    
                    # For rendering, the base filter (mirror, scale, blur) comes first
                    fcf = get_filter(mirror_v, scale_v, blur_s, by_px_r, bh_px_r, False, None, 0, 0, 0)
                    full_filter = fcf.replace("[v]", "[v0]")
                    for i, filt in enumerate(overlay_filters):
                        current_filt = filt.replace("[v]", f"[v{i}]", 1).replace("[v]", f"[v{i+1}]")
                        full_filter += ";" + current_filt
                    full_filter += f";[v{len(overlay_filters)}]null[v]"

                    filter_script = tempfile.mktemp(suffix=".txt")
                    with open(filter_script, "w", encoding="utf-8") as f:
                        f.write(full_filter)

                    fv_name = f"final_{fid}_{int(time.time())}.mp4"
                    fv = os.path.join(tempfile.gettempdir(), fv_name)

                    # Determine final duration
                    final_duration = target_sec if fit_dur else get_dur(ao)
                    
                    # Use -stream_loop -1 to loop input video if it's shorter than audio
                    # Use -t to cut exactly at the final duration
                    cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", tp, "-i", ao, "-filter_complex_script", filter_script, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "aac", "-b:a", "192k", "-t", str(final_duration), fv]
                    res = subprocess.run(cmd, capture_output=True, text=True)

                    if res.returncode != 0:
                        if len(full_filter) < 5000:
                            cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", tp, "-i", ao, "-filter_complex", full_filter, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "aac", "-b:a", "192k", "-t", str(final_duration), fv]
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

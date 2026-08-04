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

# --- CONFIGURATION ---
API_VERSIONS = ["v1beta", "v1"]
DEFAULT_MODELS = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-pro"]

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
    keys = ['myanmar_text', 'audio_data', 'srt_data', 'video_data', 'base_frame', 'last_uploaded', 'processing_done', 'valid_keys_info']
    for k in keys:
        if k not in st.session_state: st.session_state[k] = None
    if st.session_state.processing_done is None: st.session_state.processing_done = False
    if st.session_state.valid_keys_info is None: st.session_state.valid_keys_info = {}
    if 'blur_y_pos' not in st.session_state: st.session_state.blur_y_pos = 85.0
    if 'blur_h_size' not in st.session_state: st.session_state.blur_h_size = 10.0
    if 'sub_y_pos' not in st.session_state: st.session_state.sub_y_pos = 85.0
    if 'font_size' not in st.session_state: st.session_state.font_size = 22

init_state()

st.title("🎬 Movie Recap AI Pro V6.2")
st.markdown("အင်္ဂလိပ် ဗီဒီယိုမှ မြန်မာ Movie Recap ပြုလုပ်ပေးသော AI (Unicode & Wrap Fix)")

# --- HELPER: +/- BUTTONS ---
def plus_minus_control(label, key, min_val, max_val, step=1.0):
    st.write(f"**{label}**")
    col1, col2, col3 = st.columns([1, 3, 1])
    def update_val(delta):
        st.session_state[key] = float(np.clip(st.session_state[key] + delta, min_val, max_val))
    with col1: st.button("➖", key=f"minus_{key}", on_click=update_val, args=(-step,))
    with col2: st.slider(label, min_val, max_val, key=key, step=step, label_visibility="collapsed")
    with col3: st.button("➕", key=f"plus_{key}", on_click=update_val, args=(step,))
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
    st.subheader("🔑 Gemini API Keys (၅ ခုအထိ)")
    k1 = st.text_input("API Key 1", type="password", key="key_1")
    k2 = st.text_input("API Key 2", type="password", key="key_2")
    k3 = st.text_input("API Key 3", type="password", key="key_3")
    k4 = st.text_input("API Key 4", type="password", key="key_4")
    k5 = st.text_input("API Key 5", type="password", key="key_5")
    api_keys = [k for k in [k1, k2, k3, k4, k5] if k]
    
    if st.button("🔌 API ချိတ်ဆက်မှု စမ်းသပ်ရန်"):
        if not api_keys:
            st.error("API Key အရင်ထည့်ပေးပါ။")
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
                if success: st.info(f"Key {i+1} ကို စိတ်ချစွာ အသုံးပြုနိုင်ပါသည်။")

    st.markdown("---")
    st.subheader("🎬 ဗီဒီယို ပုံစံညှိရန်")
    mirror_v = st.checkbox("ဗီဒီယို Mirror လှန်ရန်", value=True)
    scale_v = st.checkbox("ဗီဒီယို Scale 106% ချဲ့ရန်", value=True)
    
    st.markdown("---")
    blur_s = st.checkbox("မူရင်းစာတန်းထိုး ဝါးရန် (Blur)", value=True)
    if blur_s:
        b_y = plus_minus_control("ဝါးမည့်နေရာ (Y %)", "blur_y_pos", 0.0, 100.0, 0.5)
        b_h = plus_minus_control("ဝါးမည့်အကျယ် (H %)", "blur_h_size", 0.5, 30.0, 0.1)
    
    st.markdown("---")
    burn_s = st.checkbox("မြန်မာစာတန်းထိုး ထည့်ရန်", value=True)
    if burn_s:
        f_s = plus_minus_control("စာလုံးအရွယ်အစား", "font_size", 5, 100, 1)
        s_y = plus_minus_control("စာတန်းထိုးနေရာ (Y %)", "sub_y_pos", 0.0, 100.0, 0.5)
    
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
def create_subtitle_image(text, width, height, font_size, y_pos_pct):
    """Render Myanmar text onto a transparent image using Pillow for perfect Unicode shaping"""
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("Pyidaungsu.ttf", font_size)
    except:
        font = ImageFont.load_default()
        
    # Split text into lines
    lines = text.split('\n')
    
    # Calculate total height of all lines
    line_heights = [draw.textbbox((0, 0), line, font=font)[3] for line in lines]
    total_text_height = sum(line_heights) + (len(lines) - 1) * 10
    
    # Starting Y position
    current_y = int(height * (y_pos_pct / 100)) - (total_text_height // 2)
    
    for line in lines:
        # Calculate X to center text
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        x = (width - w) // 2
        
        # Draw shadow/outline for readability
        for offset in [(-2,-2), (2,-2), (-2,2), (2,2)]:
            draw.text((x+offset[0], current_y+offset[1]), line, font=font, fill=(0,0,0,200))
            
        # Draw main text (Yellow)
        draw.text((x, current_y), line, font=font, fill=(255, 255, 0, 255))
        current_y += bbox[3] + 10
        
    return img

def normalize_myanmar(text):
    """Normalize and reorder Myanmar characters to standard Unicode order for better rendering"""
    if not text: return text
    import re
    # Standard Unicode Order: Consonant + Medials (ျ ြ ွ ှ) + Vowels (ေ ိ ီ ု ူ ေ ဲ) + Marks (် ံ ့ း)
    # This is a simplified reordering to ensure common medials and vowels are in order
    # Medials: 103B, 103C, 103D, 103E
    # Vowels: 102B-1032, 1036
    # Marks: 1037-103A
    
    # Remove any potential Zawgyi characters if they leaked in (rare for Gemini but safe)
    # For now, we focus on Unicode reordering
    def reorder_cluster(m):
        cluster = m.group(0)
        # Separate base and marks
        base = cluster[0]
        marks = list(cluster[1:])
        # Define weights for sorting marks to standard order
        order = {
            '\u103B': 1, '\u103C': 2, '\u103D': 3, '\u103E': 4, # Medials
            '\u1031': 5, # Pre-base vowel (rendered before, but stored after medials)
            '\u102F': 6, '\u1030': 7, # Below vowels
            '\u102D': 8, '\u102E': 9, '\u1032': 10, # Above vowels
            '\u102B': 11, '\u102C': 12, # Right vowels
            '\u1036': 13, '\u1037': 14, '\u1038': 15, '\u1039': 16, '\u103A': 17 # Marks
        }
        marks.sort(key=lambda x: order.get(x, 100))
        return base + "".join(marks)

    cluster_pattern = r'[\u1000-\u102A\u103F\u1040-\u1049][\u102B-\u103E]*'
    return re.sub(cluster_pattern, reorder_cluster, text)

def wrap_text(text, max_len=30):
    """Intelligently wrap Myanmar text to prevent long lines without breaking clusters"""
    if not text: return text
    
    # First normalize the text
    text = normalize_myanmar(text)
    
    if len(text) <= max_len:
        return text
    
    import re
    cluster_pattern = r'[\u1000-\u102A\u103F\u1040-\u1049][\u102B-\u103E]*'
    clusters = re.findall(cluster_pattern + r'|[^\u1000-\u103E]', text)
    
    lines = []
    cur_line = ""
    cur_len = 0
    
    for c in clusters:
        # If cluster is a space, handle separately
        if c == " ":
            if cur_len >= max_len:
                lines.append(cur_line)
                cur_line = ""
                cur_len = 0
            else:
                cur_line += c
                cur_len += 1
            continue
            
        if cur_len + len(c) > max_len and cur_line:
            lines.append(cur_line)
            cur_line = c
            cur_len = len(c)
        else:
            cur_line += c
            cur_len += len(c)
            
    if cur_line:
        lines.append(cur_line)
    
    return "\n".join(lines)

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
    """Parse SRT or plain text and extract subtitle segments"""
    # Remove any leading/trailing whitespace
    text = text.strip()
    
    # Try to parse as SRT format first
    blocks = re.split(r'\n\s*\n', text)
    segments = []
    
    for block in blocks:
        lines = block.strip().split('\n')
        
        # Look for SRT format (has --> marker)
        found_srt = False
        for i, line in enumerate(lines):
            if '-->' in line:
                # Collect all lines after the timestamp as subtitle text
                subtitle_text = ' '.join(lines[i+1:]).strip()
                if subtitle_text:
                    segments.append(subtitle_text)
                found_srt = True
                break
        
        # If not SRT format, treat the whole block as text (skip if it's just a number)
        if not found_srt and len(lines) > 0:
            # Remove leading numbers (SRT index)
            text_content = '\n'.join(lines)
            text_content = re.sub(r'^\d+\s*\n', '', text_content).strip()
            if text_content and not re.match(r'^[\d:,.\s\->]+$', text_content):
                segments.append(text_content)
    
    # Filter out empty segments
    return [s.strip() for s in segments if s.strip()]

async def gen_audio_srt(text, out_p, vid, spd, ptc, target=0):
    rate = f"+{int((spd-50)*2)}%" if spd>=50 else f"{int((spd-50)*2)}%"
    pitch = f"+{int((ptc-50)*2)}Hz" if ptc>=50 else f"{int((ptc-50)*2)}Hz"
    segments = parse_srt_text(text)
    if not segments: segments = [text]
    temp_files = []
    cur_t = 0.0
    srt_blocks = []
    for idx, txt in enumerate(segments):
        clean_txt = re.sub(r'^\d+\s*', '', txt).strip()
        if not clean_txt: continue
        
        # Basic Myanmar Unicode Normalization (Optional but helpful for some shapers)
        # Ensure medials and vowels are in a predictable order
        import unicodedata
        clean_txt = unicodedata.normalize('NFC', clean_txt)
        
        # Wrap long lines for SRT (max 30 chars per line)
        wrapped_txt = wrap_text(clean_txt, max_len=30)
        p = tempfile.mktemp(suffix=".mp3")
        try:
            communicate = edge_tts.Communicate(clean_txt, vid, rate=rate, pitch=pitch)
            await communicate.save(p)
            d = get_dur(p)
            if d > 0:
                srt_blocks.append(f"{len(temp_files)+1}\n{fmt_srt(cur_t)} --> {fmt_srt(cur_t+d)}\n{wrapped_txt}\n\n")
                temp_files.append(p)
                cur_t += d + 0.1
        except: continue
    if not temp_files: raise Exception("အသံဖိုင် ထုတ်လုပ်ခြင်း မအောင်မြင်ပါ။")
    raw = tempfile.mktemp(suffix=".mp3")
    l_p = tempfile.mktemp(suffix=".txt")
    with open(l_p, "w", encoding='utf-8') as f: f.write("\n".join([f"file '{p}'" for p in temp_files]))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", l_p, "-c", "copy", raw], capture_output=True)
    total = get_dur(raw)
    if target > 0 and total > 0:
        factor = total / target
        factor = np.clip(factor, 0.7, 1.5)
        subprocess.run(["ffmpeg", "-y", "-i", raw, "-filter:a", f"atempo={factor}", out_p], capture_output=True)
        final_srt = []
        for line in "".join(srt_blocks).splitlines(keepends=True):
            if "-->" in line:
                s, e = line.split(" --> ")
                s_s = sum(float(x)*60**i for i,x in enumerate(reversed(s.replace(",",".").split(":")))) / factor
                e_s = sum(float(x)*60**i for i,x in enumerate(reversed(e.replace(",",".").split(":")))) / factor
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

def get_filter(mir, scl, blr, by, bh, brn, sp, fs, sy):
    # Base chain for hflip and scale
    base_parts = []
    if mir: base_parts.append("hflip")
    if scl: base_parts.append("scale=1.06*iw:-1,crop=iw/1.06:ih/1.06")
    base_str = ",".join(base_parts) if base_parts else "null"
    
    if not blr:
        # Simple case: no blur
        res = f"[0:v]{base_str}"
        if brn and sp and os.path.exists(sp):
            # Use Python-rendered subtitle overlay instead of subtitles filter
            res += f",overlay=0:0"
        return res + "[v]"
    else:
        # Complex case: region blur
        y_p = by / 100
        h_p = bh / 100
        filter_complex = f"[0:v]{base_str}[preblur];"
        filter_complex += f"[preblur]split[main][to_blur];"
        filter_complex += f"[to_blur]crop=iw:ih*{h_p}:0:ih*{y_p},boxblur=15[blurred];"
        filter_complex += f"[main][blurred]overlay=0:H*{y_p}[postblur]"
        
        res = "[postblur]"
        if brn and sp and os.path.exists(sp):
            # Overlay Python-rendered subtitle stream
            res = "[postblur][1:v]overlay=0:0"
        
        return filter_complex + ";" + res + "[v]"

# --- MAIN UI ---
up = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if up:
    fid = up.name + str(up.size)
    if st.session_state.last_uploaded != fid:
        st.session_state.last_uploaded = fid
        with tempfile.NamedTemporaryFile(delete=False, suffix="."+up.name.split(".")[-1]) as t:
            t.write(up.getvalue()); tp = t.name
        if up.name.lower().endswith((".mp4", ".mov", ".avi")):
            d = get_dur(tp)
            bi = tempfile.mktemp(suffix=".jpg")
            subprocess.run(["ffmpeg", "-y", "-ss", str(d*0.2), "-i", tp, "-frames:v", "1", bi], capture_output=True)
            if os.path.exists(bi):
                with open(bi, "rb") as f: st.session_state.base_frame = f.read()
                os.remove(bi)
        os.remove(tp)

    if st.session_state.get("do_detect"):
        with tempfile.NamedTemporaryFile(delete=False, suffix="."+up.name.split(".")[-1]) as t:
            t.write(up.getvalue()); tp = t.name
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
        if os.path.exists(tp): os.remove(tp)
        st.session_state.do_detect = False; st.rerun()

    if show_prev and st.session_state.base_frame:
        st.subheader("🖼️ Layout Preview")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as bf: 
            bf.write(st.session_state.base_frame); bp = bf.name
        
        # 1. Generate transparent subtitle image
        with Image.open(bp) as base_img:
            w, h = base_img.size
            sub_img = create_subtitle_image("မြန်မာစာ ယူနီကုတ်\nစမ်းသပ်ကြည့်ရှုခြင်း", w, h, st.session_state.font_size, st.session_state.sub_y_pos)
            sub_p = tempfile.mktemp(suffix=".png")
            sub_img.save(sub_p)
            
        po = tempfile.mktemp(suffix=".jpg")
        fc = get_filter(mirror_v, scale_v, blur_s, st.session_state.blur_y_pos, st.session_state.blur_h_size, burn_s, sub_p, st.session_state.font_size, st.session_state.sub_y_pos)
        
        # If burn_s is enabled, we need two inputs for overlay
        if burn_s:
            cmd = ["ffmpeg", "-y", "-i", bp, "-i", sub_p, "-filter_complex", fc, "-map", "[v]", po]
        else:
            cmd = ["ffmpeg", "-y", "-i", bp, "-filter_complex", fc.replace("[postblur][1:v]overlay=0:0", "[postblur]"), "-map", "[v]", po]
            
        subprocess.run(cmd, capture_output=True)
        if os.path.exists(po): st.image(po); os.remove(po)
        if os.path.exists(bp): os.remove(bp)
        if os.path.exists(sub_p): os.remove(sub_p)

    if not api_keys: st.warning("⚠️ Sidebar တွင် Gemini API Key ထည့်ပေးပါ")
    elif st.button("🚀 စတင်လုပ်ဆောင်ရန်"):
        prg = st.progress(0); stt = st.empty()
        try:
            stt.text("📊 အဆင့် ၁: အသံဖိုင်ကို ပြင်ဆင်နေပါသည်...")
            prg.progress(10)
            with tempfile.NamedTemporaryFile(delete=False, suffix="."+up.name.split(".")[-1]) as t:
                t.write(up.read()); tp = t.name
            ag = tempfile.mktemp(suffix=".mp3")
            if up.name.lower().endswith((".mp4", ".mov", ".avi")):
                subprocess.run(["ffmpeg", "-y", "-i", tp, "-vn", "-acodec", "libmp3lame", "-q:a", "4", ag], capture_output=True)
            else: shutil.copy(tp, ag)
            
            stt.text("⏳ အဆင့် ၂: ဘာသာပြန်နေပါသည် (Gemini)...")
            prg.progress(30)
            # Improved instruction for better SRT formatting with shorter lines
            prm = f"""Listen to this audio and translate it into a Myanmar Movie Recap style narration.
Target duration: {target_sec} seconds.
Output ONLY valid SRT subtitle format with proper timing.

IMPORTANT RULES FOR MYANMAR LANGUAGE:
1. Use Standard Myanmar Unicode.
2. Ensure correct spelling for movie recap terms (e.g., use 'ပြိုလဲ' for collapse/fall, NOT 'ပျိုလဲ').
3. Keep the narration natural, dramatic, and conversational (Recap Style).
4. For foreign names, use common Myanmar phonetic transcriptions.

FORMATTING RULES:
1. Each subtitle line must be SHORT (maximum 8-10 words per line).
2. Break long sentences into multiple lines within the same subtitle block.
3. Use proper SRT format: index, timestamp, subtitle text, blank line.
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
                                    if srt_res: break
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
            ao = os.path.abspath("final_audio.mp3")
            st.session_state.srt_data, _ = asyncio.run(gen_audio_srt(srt_res, ao, v_id, v_speed, v_pitch, target_sec if fit_dur else 0))
            with open(ao, "rb") as f: st.session_state.audio_data = f.read()
            
            if up.name.lower().endswith((".mp4", ".mov", ".avi")):
                stt.text("🎬 အဆင့် ၄: ဗီဒီယိုကို တည်းဖြတ်နေပါသည် (Rendering)...")
                prg.progress(80)
                
                # 1. Create a transparent subtitle video using Python rendering
                stt.text("🎬 အဆင့် ၄: စာတန်းထိုးများကို ပုံဖော်နေပါသည်...")
                sub_dir = tempfile.mkdtemp()
                
                # Get video dimensions
                cmd_dim = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", tp]
                v_dim = subprocess.run(cmd_dim, capture_output=True, text=True).stdout.strip().split('x')
                vw, vh = int(v_dim[0]), int(v_dim[1])
                
                # Parse SRT and generate frames
                segments = []
                import re
                blocks = re.split(r'\n\s*\n', st.session_state.srt_data)
                for block in blocks:
                    lines = block.strip().split('\n')
                    if len(lines) >= 3:
                        times = lines[1].split(' --> ')
                        start = sum(float(x)*60**i for i,x in enumerate(reversed(times[0].replace(',','.').split(':'))))
                        end = sum(float(x)*60**i for i,x in enumerate(reversed(times[1].replace(',','.').split(':'))))
                        text = "\n".join(lines[2:])
                        segments.append({'start': start, 'end': end, 'text': text})
                
                # Create a temporary subtitle video
                sub_vid = tempfile.mktemp(suffix=".mp4")
                # We'll use a complex filter to overlay at specific times
                overlay_filters = []
                temp_imgs = []
                for i, seg in enumerate(segments):
                    simg = create_subtitle_image(seg['text'], vw, vh, st.session_state.font_size, st.session_state.sub_y_pos)
                    spath = os.path.join(sub_dir, f"sub_{i}.png")
                    simg.save(spath)
                    temp_imgs.append(spath)
                    overlay_filters.append(f"movie={spath.replace('\\','/').replace(':','\\\\')}[s{i}];[v][s{i}]overlay=0:0:enable='between(t,{seg['start']},{seg['end']})'[v]")
                
                fcf = get_filter(mirror_v, scale_v, blur_s, st.session_state.blur_y_pos, st.session_state.blur_h_size, False, None, 0, 0)
                fcf = fcf.replace("[v]", "[v_base]")
                
                # Combine all
                full_filter = fcf + ";[v_base]null[v]"
                for filt in overlay_filters:
                    full_filter = full_filter.replace("[v]", f"[v_pre{i}]")
                    full_filter += ";" + filt.replace("[v]", f"[v_pre{i}]").replace("[v]", "[v]")
                
                fv = tempfile.mktemp(suffix=".mp4")
                cmd = ["ffmpeg", "-y", "-i", tp, "-i", ao, "-filter_complex", full_filter, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-c:a", "aac", "-b:a", "192k", "-shortest", fv]
                res = subprocess.run(cmd, capture_output=True, text=True)
                
                if res.returncode == 0:
                    with open(fv, "rb") as f: st.session_state.video_data = f.read()
                else: st.error(f"Render Error: {res.stderr}")
                
                # Cleanup
                if os.path.exists(fv): os.remove(fv)
                shutil.rmtree(sub_dir)

            prg.progress(100); stt.text("✅ အောင်မြင်စွာ ပြီးဆုံးပါပြီ!"); st.balloons()
            st.session_state.processing_done = True
            if os.path.exists(tp): os.remove(tp)
            if os.path.exists(ao): os.remove(ao)
            if os.path.exists(ag): os.remove(ag)
        except Exception as e: st.error(f"❌ အမှားအယွင်း: {str(e)}")

if st.session_state.processing_done:
    st.markdown("---")
    if st.session_state.video_data:
        st.subheader("🎥 တည်းဖြတ်ပြီး ဗီဒီယို")
        st.video(st.session_state.video_data)
        st.download_button("📥 ဗီဒီယိုကို သိမ်းဆည်းရန်", st.session_state.video_data, "recap_final.mp4", "video/mp4")
    c1, c2 = st.columns(2)
    with c1:
        if st.session_state.audio_data:
            st.audio(st.session_state.audio_data)
            st.download_button("📥 အသံဖိုင်ကို သိမ်းဆည်းရန်", st.session_state.audio_data, "recap_audio.mp3", "audio/mp3")
    with c2:
        if st.session_state.srt_data:
            st.download_button("📥 စာတန်းထိုး (SRT) ကို သိမ်းဆည်းရန်", st.session_state.srt_data, "recap.srt", "text/plain")

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
from PIL import Image
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
def wrap_text(text, max_len=30):
    """Intelligently wrap Myanmar text to prevent long lines"""
    if len(text) <= max_len:
        return text
    
    # Split by spaces first
    words = text.split(' ')
    lines = []
    cur_line = ""
    
    for w in words:
        test_line = cur_line + (" " if cur_line else "") + w
        if len(test_line) <= max_len:
            cur_line = test_line
        else:
            if cur_line:
                lines.append(cur_line)
            cur_line = w
    
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
            if text_content and not re.match(r'^[\d:,.\s-->]+$', text_content):
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
    vf = []
    if mir: vf.append("hflip")
    if scl: vf.append("scale=1.06*iw:-1,crop=iw/1.06:ih/1.06")
    base = ",".join(vf) if vf else "null"
    if blr:
        y, h = by/100, bh/100
        fc = f"[0:v]{base},split[m][b];[b]crop=iw:ih*{h}:0:ih*{y},boxblur=20:10[blurred];[m][blurred]overlay=0:main_h*{y}"
    else:
        fc = f"[0:v]{base}"
    if brn and sp and os.path.exists(sp):
        se = os.path.abspath(sp).replace("\\","/").replace(":","\\:").replace("'","'\\''")
        mv = int((100 - sy) * 10)
        # Professional Unicode styling with Pyidaungsu - use fontfile instead of fontdir
        font_path = os.path.abspath("Pyidaungsu.ttf").replace("\\","/").replace(":","\\:").replace("'","'\\''")
        fc += f",subtitles='{se}':fontfile='{font_path}':force_style='FontSize={fs},PrimaryColour=&H0000FFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0,Alignment=2,MarginV={mv}'"
    if not fc.endswith("[v]"): fc += "[v]"
    return fc

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
        ps = os.path.abspath("preview.srt")
        with open(ps, "w", encoding="utf-8") as f: 
            f.write("1\n00:00:00,000 --> 00:00:10,000\nမြန်မာစာ ယူနီကုတ်\nစမ်းသပ်ကြည့်ရှုခြင်း")
        po = tempfile.mktemp(suffix=".jpg")
        fc = get_filter(mirror_v, scale_v, blur_s, st.session_state.blur_y_pos, st.session_state.blur_h_size, burn_s, ps, st.session_state.font_size, st.session_state.sub_y_pos)
        fcs = fc.replace("[0:v]", "").replace("[v]", "").strip(",")
        subprocess.run(["ffmpeg", "-y", "-i", bp, "-vf", fcs if fcs else "null", po], capture_output=True)
        if os.path.exists(po): st.image(po); os.remove(po)
        if os.path.exists(bp): os.remove(bp)
        if os.path.exists(ps): os.remove(ps)

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
IMPORTANT RULES:
1. Each subtitle line must be SHORT (maximum 8-10 words per line)
2. Break long sentences into multiple lines within the same subtitle block
3. Use proper SRT format: index, timestamp, subtitle text, blank line
4. Keep Myanmar language natural and conversational
5. Do NOT include any text outside the SRT format"""
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
                stmp = os.path.abspath("final.srt")
                with open(stmp, "w", encoding="utf-8") as f: f.write(st.session_state.srt_data)
                fv = tempfile.mktemp(suffix=".mp4")
                fcf = get_filter(mirror_v, scale_v, blur_s, st.session_state.blur_y_pos, st.session_state.blur_h_size, burn_s, stmp, st.session_state.font_size, st.session_state.sub_y_pos)
                cmd = ["ffmpeg", "-y", "-i", tp, "-i", ao, "-filter_complex", fcf, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-c:a", "aac", "-b:a", "192k", "-shortest", fv]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    with open(fv, "rb") as f: st.session_state.video_data = f.read()
                else: st.error(f"Render Error: {res.stderr}")
                if os.path.exists(fv): os.remove(fv)
                if os.path.exists(stmp): os.remove(stmp)

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

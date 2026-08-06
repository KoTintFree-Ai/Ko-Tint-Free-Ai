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

# Myanmar TTS Voices (Thiha & Nila)
MYANMAR_VOICES = {
    "သီဟ (Thiha) - ယောက်ျားအသံ": "my-MM",
    "နီလာ (Nila) - အမျိုးသမီးအသံ": "my-MM"
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(SCRIPT_DIR, "Pyidaungsu.ttf")

st.set_page_config(
    page_title="Movie Recap AI Pro V12 - Stable",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display:none;}
    [data-testid="stSidebarNav"] {display: none;}
    .stButton>button {width: 100%;}
    </style>
    """, unsafe_allow_html=True)

# Session State Initialization - WITHOUT direct assignment
def init_state():
    if 'step1_translation' not in st.session_state:
        st.session_state.step1_translation = None
    if 'step2_audio_path' not in st.session_state:
        st.session_state.step2_audio_path = None
    if 'step2_srt' not in st.session_state:
        st.session_state.step2_srt = None
    if 'step3_final_srt' not in st.session_state:
        st.session_state.step3_final_srt = None
    if 'valid_keys_info' not in st.session_state:
        st.session_state.valid_keys_info = {}
    if 'active_key' not in st.session_state:
        st.session_state.active_key = None
    
    for i in range(1, 6):
        if f'key_{i}' not in st.session_state:
            st.session_state[f'key_{i}'] = ""

init_state()

st.title("🎬 Movie Recap AI Pro V12 - Stable")
st.markdown("အင်္ဂလိပ် ဗီဒီယိုမှ မြန်မာ Movie Recap ပြုလုပ်ပေးသော AI (Manual Steps + Auto-Merge + Auto-Blur)")

# --- HELPER FUNCTIONS ---
def get_dur(p):
    """Get duration of audio/video file in seconds"""
    try:
        r = subprocess.run(["ffmpeg", "-i", p], capture_output=True, text=True)
        for line in r.stderr.split('\n'):
            if 'Duration' in line:
                t = line.split('Duration')[1].split(',')[0].strip()
                h, m, s = map(float, t.split(':'))
                return h*3600 + m*60 + s
    except: pass
    return 0

def fmt_srt(seconds):
    """Format seconds to SRT timestamp format"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')

def wrap_text(text, max_width=50):
    """Wrap text for SRT display"""
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        if len(' '.join(current_line + [word])) <= max_width:
            current_line.append(word)
        else:
            if current_line: lines.append(' '.join(current_line))
            current_line = [word]
    if current_line: lines.append(' '.join(current_line))
    return '\n'.join(lines)

def translate_error(err_msg, status_code=None):
    """Translate error messages to Myanmar"""
    err_msg = str(err_msg).lower()
    if "api_key_invalid" in err_msg or "invalid api key" in err_msg or status_code == 403:
        return "API Key မမှန်ကန်ပါ။"
    if "quota" in err_msg or "429" in err_msg or status_code == 429:
        return "API Key အသုံးပြုမှု ပမာဏ ပြည့်သွားပါပြီ။"
    if "location" in err_msg or "not supported" in err_msg:
        return "သင်၏ ဒေသတွင် ဤ API ကို ပိတ်ထားပါသည်။"
    if "404" in err_msg or status_code == 404:
        return "API URL သို့မဟုတ် Model အမည်ကို ရှာမတွေ့ပါ။"
    if "safety" in err_msg or "blocked" in err_msg:
        return "မူပိုင်ခွင့်/လုံခြုံရေး စည်းကမ်းချက်များကြောင့် ငြင်းဆိုလိုက်ပါသည်။"
    return f"အမှားအယွင်း: {err_msg}"

def parse_srt_text(text):
    """Parse SRT-formatted text into segments"""
    parts = re.split(r'\n\s*\n', text.strip())
    segments = []
    for part in parts:
        lines = part.strip().split('\n')
        if len(lines) >= 3:
            text_lines = lines[2:]
            seg = ' '.join(text_lines).strip()
        else:
            seg = part.strip()
        if seg: segments.append(seg)
    return [s for s in segments if s]

async def gen_audio_srt(text, out_p, vid, spd, ptc, target=0):
    """Generate audio and SRT from text"""
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

def auto_detect_subtitle_area(frame_bytes):
    """Auto-detect subtitle area using NumPy-based detection"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as bf:
            bf.write(frame_bytes)
            tf = bf.name
        img = Image.open(tf).convert('L')
        w, h = img.size
        arr = np.array(img)
        
        bottom_start = int(h * 0.40)
        bottom_arr = arr[bottom_start:, :]
        
        diff = np.abs(bottom_arr[:, 1:] - bottom_arr[:, :-1])
        row_edge = np.sum(diff, axis=1)
        row_brightness = np.mean(bottom_arr, axis=1)
        is_active = row_brightness > 15
        score = row_edge * is_active.astype(float)
        
        if np.max(score) > 5:
            text_rows = np.where(score > np.percentile(score[score > 0], 50) if np.any(score > 0) else 10)[0]
            if len(text_rows) >= 2:
                blur_y = float((bottom_start + text_rows[0] + 1.5) / h * 100)
                blur_h = float((text_rows[-1] - text_rows[0] - 1) / h * 100)
                blur_y = np.clip(blur_y, 50, 98)
                blur_h = np.clip(blur_h, 1.0, 7.0)
                os.remove(tf)
                return blur_y, blur_h
        
        os.remove(tf)
    except:
        pass
    
    return 78.0, 8.0

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ ဆက်တင်များ")
    
    # RAM Monitor
    st.subheader("🖥️ RAM စောင့်ကြည့်ရန်")
    def get_ram_usage():
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        return mem_info.rss / (1024 * 1024)

    ram_used = get_ram_usage()
    ram_limit = 1024 
    ram_pct = min(ram_used / ram_limit, 1.0)
    
    col_r1, col_r2 = st.columns([2, 1])
    col_r1.progress(ram_pct)
    col_r2.write(f"{ram_used:.0f}/{ram_limit}MB")
    
    if ram_used > 800:
        st.warning("⚠️ RAM သုံးစွဲမှု များနေပါသည်။")
    
    if st.button("🧹 RAM ရှင်းထုတ်ရန်"):
        st.cache_data.clear()
        gc.collect()
        st.success("RAM ရှင်းလင်းပြီးပါပြီ")
    
    st.markdown("---")
    st.subheader("🔑 Gemini API Keys")
    
    k1 = st.text_input("API Key 1", type="password", key="key_1")
    show_more_keys = st.toggle("ကျန် Keys များ", value=False, key="show_more_keys_toggle")
    if show_more_keys:
        k2 = st.text_input("API Key 2", type="password", key="key_2")
        k3 = st.text_input("API Key 3", type="password", key="key_3")
        k4 = st.text_input("API Key 4", type="password", key="key_4")
        k5 = st.text_input("API Key 5", type="password", key="key_5")
    else:
        k2 = st.session_state.get("key_2", "")
        k3 = st.session_state.get("key_3", "")
        k4 = st.session_state.get("key_4", "")
        k5 = st.session_state.get("key_5", "")
    api_keys = [k for k in [k1, k2, k3, k4, k5] if k]

    if st.button("🔌 Keys စမ်းသပ်ရန်"):
        if not api_keys:
            st.error("API Key ထည့်ပေးပါ။")
        else:
            st.session_state.valid_keys_info = {}
            with st.spinner("စစ်ဆေးနေသည်..."):
                for i, k in enumerate(api_keys):
                    for ver in API_VERSIONS:
                        try:
                            url = f"https://generativelanguage.googleapis.com/{ver}/models?key={k}"
                            r = requests.get(url, timeout=15)
                            if r.status_code == 200:
                                data = r.json()
                                models = [m['name'].split('/')[-1] for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
                                st.session_state.valid_keys_info[k] = {"version": ver, "models": models}
                                st.success(f"✅ Key {i+1} အောင်မြင်ပါတယ်")
                                break
                        except: continue
            
            # စာသားသေချာမြင်ရအောင် ၃ စက္ကန့် စောင့်ဆိုင်းခြင်း
            time.sleep(3)
            st.rerun()

    st.markdown("---")
    st.subheader("🎙️ အသံ ဆက်တင်များ")
    voice_choice = st.selectbox("အသံ ရွေးချယ်ပါ", list(MYANMAR_VOICES.keys()), key="voice_select_widget")
    v_speed = st.slider("အမြန်နှုန်း", 0, 100, 50, key="speed_slider_widget")
    v_pitch = st.slider("အမြင့်မြတ်မှု", 0, 100, 50, key="pitch_slider_widget")
    
    st.markdown("---")
    st.subheader("🎬 ဗီဒီယို ဆက်တင်များ")
    blur_y_pos = st.slider("Blur Y အနေအထား (%)", 50, 98, 85, key="blur_y_widget")
    blur_h_size = st.slider("Blur အမြင့် (%)", 1, 20, 10, key="blur_h_widget")
    sub_y_pos = st.slider("စာတန်း Y အနေအထား (%)", 50, 98, 85, key="sub_y_widget")
    font_size = st.slider("စာလုံးအရွယ်အစား", 12, 40, 22, key="font_size_widget")

# --- MAIN CONTENT ---
tab1, tab2, tab3, tab4 = st.tabs(["📹 Step 1", "🔊 Step 2", "📝 Step 3", "🎬 Step 4"])

# ============ STEP 1: VIDEO TO TRANSLATION ============
with tab1:
    st.header("Step 1️⃣: ဗီဒီယို → မြန်မာစာ")
    
    up1 = st.file_uploader("ဗီဒီယို/အော်ဒီယို ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"], key="step1_upload")
    target_sec = st.number_input("အတိုင်းအတာ (စက္ကန့်)", 10, 300, 60, key="target_duration_input")
    
    if up1 and not api_keys:
        st.error("⚠️ API Key ထည့်ပေးပါ")
    elif up1 and st.button("🚀 Step 1 စတင်"):
        fid = up1.name + str(up1.size)
        tp = os.path.join(tempfile.gettempdir(), f"input_{fid}." + up1.name.split(".")[-1])
        if not os.path.exists(tp):
            with open(tp, "wb") as f:
                f.write(up1.getvalue())
        
        prg = st.progress(0)
        stt = st.empty()
        
        try:
            stt.text("📊 အသံဖိုင်ချုံ့နေပါသည်...")
            prg.progress(20)
            
            ag = tempfile.mktemp(suffix=".mp3")
            if up1.name.lower().endswith((".mp4", ".mov", ".avi")):
                subprocess.run(["ffmpeg", "-y", "-i", tp, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], capture_output=True)
            else:
                subprocess.run(["ffmpeg", "-y", "-i", tp, "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], capture_output=True)
            
            stt.text("⏳ Gemini ဖြင့် ဘာသာပြန်နေပါသည်...")
            prg.progress(50)
            
            target_words = int(target_sec * 3.8)
            prm = f"""Listen to this audio and translate it into a HIGH-ENERGY Myanmar Movie Recap style narration.
TARGET DURATION: {target_sec} seconds.
REQUIRED SCRIPT LENGTH: You MUST write exactly around {target_words} Myanmar words.

STRICT RULES:
1. NO FILLER PHRASES
2. FOCUS ON SCENES: Describe ONLY what is happening
3. TIMING SYNC: Follow the exact sequence
4. NO HALLUCINATION
5. Use Standard Myanmar Unicode

OUTPUT FORMAT: SRT subtitle format with timestamps from 00:00:00,000 to {fmt_srt(target_sec)}
Each subtitle block should be a natural phrase (approx 15 words).
DO NOT include any preamble or conclusion. Just the SRT blocks."""
            
            with open(ag, 'rb') as f: b64 = base64.b64encode(f.read()).decode()
            cont = [{"role":"user","parts":[{"text":prm},{"inline_data":{"mime_type":"audio/mpeg","data":b64}}]}]
            
            srt_res = None
            
            for k_idx, k in enumerate(api_keys):
                info = st.session_state.valid_keys_info.get(k)
                versions = [info['version']] if info else API_VERSIONS
                models = info['models'] if info else DEFAULT_MODELS
                models = sorted(models, key=lambda x: 0 if 'flash' in x.lower() else 1)
                
                for ver in versions:
                    for m in models:
                        try:
                            url = f"https://generativelanguage.googleapis.com/{ver}/models/{m}:generateContent?key={k}"
                            r = requests.post(url, json={"contents":cont}, timeout=180)
                            if r.status_code == 200:
                                data = r.json()
                                if 'candidates' in data and data['candidates'][0]['content']['parts']:
                                    srt_res = data['candidates'][0]['content']['parts'][0]['text']
                                    if srt_res:
                                        st.session_state.active_key = k
                                        break
                        except: continue
                    if srt_res: break
                if srt_res: break
            
            if not srt_res:
                st.error("❌ ဘာသာပြန်ခြင်း မအောင်မြင်ပါ")
            else:
                st.session_state.step1_translation = srt_res
                prg.progress(100)
                stt.text("✅ Step 1 ပြီးမြောက်!")
                
                with st.expander("📝 ရလာတဲ့ စာသားများ", expanded=True):
                    st.text_area("Translation Output", srt_res, height=250, disabled=False)
                    st.info("💡 အဲ့ စာသားကို copy ကူးပြီး Step 2 ထဲ ကူးထည့်ပါ။")
        
        except Exception as e:
            st.error(f"❌ အမှားအယွင်း: {str(e)}")

# ============ STEP 2: TEXT TO AUDIO ============
with tab2:
    st.header("Step 2️⃣: မြန်မာစာ → အသံ")
    
    step2_text = st.text_area("Step 1 မှ စာသားကို ကူးထည့်ပါ", height=300, key="step2_text_input_widget")
    step2_target = st.number_input("အတိုင်းအတာ (စက္ကန့်)", 10, 300, 60, key="step2_duration_input")
    
    if step2_text and st.button("🎙️ Step 2 စတင်"):
        prg = st.progress(0)
        stt = st.empty()
        
        try:
            stt.text("🔊 အသံထုတ်နေပါသည်...")
            prg.progress(30)
            
            ao_name = f"audio_{int(time.time())}.mp3"
            ao = os.path.join(tempfile.gettempdir(), ao_name)
            
            voice_locale = MYANMAR_VOICES[voice_choice]
            srt_data, audio_dur = asyncio.run(gen_audio_srt(step2_text, ao, voice_locale, v_speed, v_pitch, step2_target))
            
            st.session_state.step2_audio_path = ao
            st.session_state.step2_srt = srt_data
            
            prg.progress(100)
            stt.text("✅ Step 2 ပြီးမြောက်!")
            
            st.success(f"✅ အသံထုတ်ပြီး (အတိုင်းအတာ: {audio_dur:.2f} စက္ကန့်)")
            
            with st.expander("📝 ထုတ်ပေးထားသော SRT", expanded=True):
                st.text_area("SRT Output", srt_data, height=250, disabled=False)
            
            with open(ao, 'rb') as f:
                st.download_button("⬇️ အသံဖိုင် ဒေါင်းလုဒ်", f, file_name=ao_name)
        
        except Exception as e:
            st.error(f"❌ အမှားအယွင်း: {str(e)}")

# ============ STEP 3: AUDIO TO SRT ============
with tab3:
    st.header("Step 3️⃣: အသံ → SRT")
    
    step3_srt = st.text_area("Step 2 မှ SRT ကို ကူးထည့်ပါ", height=300, key="step3_srt_input_widget")
    
    if step3_srt and st.button("✏️ Step 3 စတင်"):
        try:
            st.session_state.step3_final_srt = step3_srt
            st.success("✅ SRT သိမ်းဆည်းပြီး!")
            
            with st.expander("📝 နောက်ဆုံး SRT", expanded=True):
                st.text_area("Final SRT", step3_srt, height=250, disabled=False)
            
            st.download_button("⬇️ SRT ဖိုင် ဒေါင်းလုဒ်", step3_srt, file_name="output.srt")
        
        except Exception as e:
            st.error(f"❌ အမှားအယွင်း: {str(e)}")

# ============ STEP 4: MERGE VIDEO + AUDIO + SRT ============
with tab4:
    st.header("Step 4️⃣: ဗီဒီယို + အသံ + SRT ပေါင်းစပ်ခြင်း")
    st.markdown("အဆင့် ၁-၃ မှ ရလာတဲ့ အရာများကို အလိုအလျောက် ပေါင်းစပ်ပြီး Auto-blur နဲ့ စာတန်းထိုးပါ။")
    
    col1, col2 = st.columns(2)
    
    with col1:
        up4_video = st.file_uploader("ဗီဒီယို ဖိုင်", type=["mp4", "mov", "avi"], key="step4_video_widget")
    
    with col2:
        up4_audio = st.file_uploader("အသံ ဖိုင်", type=["mp3", "wav", "m4a"], key="step4_audio_widget")
    
    step4_srt = st.text_area("SRT ကုဒ်", height=200, key="step4_srt_input_widget")
    
    use_auto_blur = st.checkbox("Auto-Blur အသုံးပြုမည်", value=True, key="auto_blur_check_widget")
    use_auto_sub = st.checkbox("Auto-Subtitle အသုံးပြုမည်", value=True, key="auto_sub_check_widget")
    
    if up4_video and up4_audio and step4_srt and st.button("🎬 Step 4 စတင်"):
        prg = st.progress(0)
        stt = st.empty()
        
        try:
            stt.text("📹 ဗီဒီယို နှင့် အသံ ပေါင်းစပ်နေပါသည်...")
            prg.progress(20)
            
            video_path = os.path.join(tempfile.gettempdir(), f"video_{int(time.time())}.mp4")
            audio_path = os.path.join(tempfile.gettempdir(), f"audio_{int(time.time())}.mp3")
            srt_path = os.path.join(tempfile.gettempdir(), f"subs_{int(time.time())}.srt")
            
            with open(video_path, 'wb') as f:
                f.write(up4_video.getvalue())
            with open(audio_path, 'wb') as f:
                f.write(up4_audio.getvalue())
            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write(step4_srt)
            
            # Extract frame for auto-blur detection
            if use_auto_blur:
                stt.text("🎯 Subtitle နေရာ auto-detect နေပါသည်...")
                prg.progress(30)
                bi = tempfile.mktemp(suffix=".jpg")
                d = get_dur(video_path)
                subprocess.run(["ffmpeg", "-y", "-ss", str(d*0.2), "-i", video_path, "-frames:v", "1", bi], capture_output=True)
                if os.path.exists(bi):
                    with open(bi, 'rb') as f:
                        frame_bytes = f.read()
                    detected_blur_y, detected_blur_h = auto_detect_subtitle_area(frame_bytes)
                    os.remove(bi)
                else:
                    detected_blur_y = blur_y_pos
                    detected_blur_h = blur_h_size
            else:
                detected_blur_y = blur_y_pos
                detected_blur_h = blur_h_size
            
            stt.text("🎬 ဗီဒီယို နှင့် အသံ ပေါင်းစပ်နေပါသည်...")
            prg.progress(50)
            
            merged_av = os.path.join(tempfile.gettempdir(), f"merged_{int(time.time())}.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
                "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
                merged_av
            ], capture_output=True)
            
            stt.text("📝 Subtitle နဲ့ Blur ထည့်သွင်းနေပါသည်...")
            prg.progress(75)
            
            # Build filter complex for blur + subtitle
            if use_auto_blur and use_auto_sub:
                by_px = int(1080 * (detected_blur_y / 100))
                bh_px = int(1080 * (detected_blur_h / 100))
                
                filter_str = f"[0:v]boxblur=luma_radius=10:chroma_radius=4:alpha_radius=1,crop=iw:{bh_px}:0:{by_px},boxblur=luma_radius=10:chroma_radius=4:alpha_radius=1[blurred];[0:v][blurred]overlay=0:{by_px}[v];[v]subtitles={srt_path}:force_style='FontName=Pyidaungsu,FontSize={font_size},PrimaryColour=&H00FFFFFF&'[out]"
                
                output_path = os.path.join(tempfile.gettempdir(), f"final_{int(time.time())}.mp4")
                subprocess.run([
                    "ffmpeg", "-y", "-i", merged_av, "-vf", filter_str,
                    "-c:a", "copy", output_path
                ], capture_output=True)
            elif use_auto_sub:
                output_path = os.path.join(tempfile.gettempdir(), f"final_{int(time.time())}.mp4")
                subprocess.run([
                    "ffmpeg", "-y", "-i", merged_av, "-vf",
                    f"subtitles={srt_path}:force_style='FontName=Pyidaungsu,FontSize={font_size},PrimaryColour=&H00FFFFFF&'",
                    "-c:a", "copy", output_path
                ], capture_output=True)
            else:
                output_path = merged_av
            
            prg.progress(100)
            stt.text("✅ Step 4 ပြီးမြောက်!")
            
            st.success("✅ ဗီဒီယို ပေါင်းစပ်ပြီးပါပြီ!")
            
            with open(output_path, 'rb') as f:
                st.download_button("⬇️ နောက်ဆုံး ဗီဒီယို ဒေါင်းလုဒ်", f, file_name="final_output.mp4")
            
            # Cleanup
            for p in [video_path, audio_path, srt_path, merged_av, output_path]:
                if os.path.exists(p): 
                    try: os.remove(p)
                    except: pass
        
        except Exception as e:
            st.error(f"❌ အမှားအယွင်း: {str(e)}")

st.markdown("---")
st.markdown("🎬 **Movie Recap AI Pro V12** - Manual Steps + Auto-Merge + Auto-Blur | သီဟ/နီလာ အသံ | Powered by Gemini AI")

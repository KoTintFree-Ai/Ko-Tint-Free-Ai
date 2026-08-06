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

# Myanmar TTS Voices
MYANMAR_VOICES = {
    "သီဟ (Thiha) - ယောက်ျားအသံ": "my-MM-ThihaNeural",
    "နီလာ (Nila) - အမျိုးသမီးအသံ": "my-MM-NilaNeural"
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(SCRIPT_DIR, "Pyidaungsu.ttf")

st.set_page_config(
    page_title="Movie Recap AI V18 - Original Logic",
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

# Session State Initialization
def init_state():
    if 'step1_text' not in st.session_state: st.session_state.step1_text = ""
    if 'step2_audio' not in st.session_state: st.session_state.step2_audio = None
    if 'step2_srt' not in st.session_state: st.session_state.step2_srt = ""
    if 'valid_keys_info' not in st.session_state: st.session_state.valid_keys_info = {}
    if 'active_key' not in st.session_state: st.session_state.active_key = None
    
    for i in range(1, 6):
        if f'key_{i}' not in st.session_state: st.session_state[f'key_{i}'] = ""

init_state()

st.title("🎬 Movie Recap AI V18 - Original Logic")
st.markdown("အင်္ဂလိပ် ဗီဒီယို → မြန်မာစာ (Plain Text) → အသံ → SRT → ဗီဒီယို (Auto Blur)")

# --- HELPER FUNCTIONS ---
def get_dur(p):
    try:
        r = subprocess.run(["ffmpeg", "-i", p], capture_output=True, text=True, timeout=10)
        for line in r.stderr.split('\n'):
            if 'Duration' in line:
                t = line.split('Duration')[1].split(',')[0].strip()
                h, m, s = map(float, t.split(':'))
                return h*3600 + m*60 + s
    except: pass
    return 0

def fmt_srt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')

def wrap_text(text, max_width=45):
    words = text.split()
    lines = []; cur = []
    for w in words:
        if len(' '.join(cur + [w])) <= max_width: cur.append(w)
        else:
            if cur: lines.append(' '.join(cur))
            cur = [w]
    if cur: lines.append(' '.join(cur))
    return '\n'.join(lines)

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ ဆက်တင်များ")
    
    # API Keys Section (Original Logic)
    st.subheader("🔑 Gemini API Keys")
    k1 = st.text_input("API Key 1", type="password", key="key_1")
    show_more = st.toggle("🔽 ကျန် API Keys များ", value=False)
    if show_more:
        k2 = st.text_input("API Key 2", type="password", key="key_2")
        k3 = st.text_input("API Key 3", type="password", key="key_3")
        k4 = st.text_input("API Key 4", type="password", key="key_4")
        k5 = st.text_input("API Key 5", type="password", key="key_5")
    else:
        k2 = st.session_state.key_2; k3 = st.session_state.key_3; k4 = st.session_state.key_4; k5 = st.session_state.key_5
    
    api_keys = [k for k in [k1, k2, k3, k4, k5] if k]

    if st.button("🔌 Keys အားလုံး စမ်းသပ်ရန်"):
        if not api_keys:
            st.error("API Key အရင်ထည့်ပေးပါ။")
        else:
            st.session_state.valid_keys_info = {}
            st.session_state.active_key = None
            with st.spinner("Keys များကို စစ်ဆေးနေသည်..."):
                for i, k in enumerate(api_keys):
                    success = False
                    for ver in API_VERSIONS:
                        try:
                            # ORIGINAL AUTH LOGIC: Using ?key= parameter
                            url = f"https://generativelanguage.googleapis.com/{ver}/models?key={k}"
                            r = requests.get(url, timeout=15)
                            if r.status_code == 200:
                                data = r.json()
                                models = [m['name'].split('/')[-1] for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
                                st.session_state.valid_keys_info[k] = {"version": ver, "models": models}
                                if not st.session_state.active_key: st.session_state.active_key = k
                                st.success(f"✅ Key {i+1} အောင်မြင်ပါသည်။")
                                success = True
                                break
                        except: continue
                    if not success:
                        st.error(f"❌ Key {i+1} မမှန်ကန်ပါ။")
            st.rerun()

    if st.session_state.active_key:
        st.success("🟢 API Key အဆင်သင့်ဖြစ်ပါသည်")

    st.markdown("---")
    st.subheader("🎙️ အသံ ဆက်တင်")
    voice_choice = st.selectbox("အသံရွေးချယ်ရန်", list(MYANMAR_VOICES.keys()))
    v_speed = st.slider("အမြန်နှုန်း", 0, 100, 50)
    v_pitch = st.slider("အသံ အနိမ့်အမြင့်", 0, 100, 50)
    
    st.markdown("---")
    st.subheader("🎬 ဗီဒီယို ဆက်တင်")
    blur_y = st.slider("Blur Position Y (%)", 50, 98, 85)
    blur_h = st.slider("Blur Height (%)", 1, 20, 10)
    font_sz = st.slider("စာလုံးအရွယ်အစား", 12, 40, 22)

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["📹 Step 1: Translation", "🔊 Step 2: Audio", "📝 Step 3: SRT", "🎬 Step 4: Merge"])

# ============ STEP 1 ============
with tab1:
    st.header("Step 1️⃣: ဗီဒီယို → မြန်မာစာ (Plain Text)")
    up1 = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင်", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"], key="up1")
    
    if up1 and st.button("🚀 ဘာသာပြန်စတင်ရန်"):
        if not st.session_state.active_key:
            st.error("⚠️ Sidebar တွင် API Key ကို အရင်စမ်းသပ်ပါ။")
        else:
            prg = st.progress(0); stt = st.empty()
            try:
                stt.text("📊 အသံဖိုင်ကို ချုံ့နေပါသည်...")
                tp = os.path.join(tempfile.gettempdir(), f"input_s1.{up1.name.split('.')[-1]}")
                with open(tp, "wb") as f: f.write(up1.getvalue())
                
                ag = tempfile.mktemp(suffix=".mp3")
                subprocess.run(["ffmpeg", "-y", "-i", tp, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], capture_output=True)
                
                stt.text("⏳ Gemini ဖြင့် ဘာသာပြန်နေပါသည်...")
                prg.progress(40)
                
                prm = """Listen to this audio and translate it into a HIGH-ENERGY Myanmar Movie Recap style narration.
                Output ONLY plain text in Myanmar language. 
                Do NOT include timestamps, introduction, greetings, or any extra text. 
                Just the story narration. Use Standard Myanmar Unicode.
                Split sentences with Myanmar sentence marker (။)."""
                
                with open(ag, 'rb') as f: b64 = base64.b64encode(f.read()).decode()
                cont = [{"role":"user","parts":[{"text":prm},{"inline_data":{"mime_type":"audio/mpeg","data":b64}}]}]
                
                srt_res = None
                keys_to_try = [st.session_state.active_key] + [k for k in api_keys if k != st.session_state.active_key]
                
                for k in keys_to_try:
                    info = st.session_state.valid_keys_info.get(k)
                    versions = [info['version']] if info else API_VERSIONS
                    models = info['models'] if info else DEFAULT_MODELS
                    
                    for ver in versions:
                        for m in models:
                            try:
                                url = f"https://generativelanguage.googleapis.com/{ver}/models/{m}:generateContent?key={k}"
                                r = requests.post(url, json={"contents":cont}, timeout=180)
                                if r.status_code == 200:
                                    data = r.json()
                                    if 'candidates' in data and data['candidates'][0]['content']['parts']:
                                        srt_res = data['candidates'][0]['content']['parts'][0]['text']
                                        if srt_res: break
                            except: continue
                        if srt_res: break
                    if srt_res: break
                
                if srt_res:
                    st.session_state.step1_text = srt_res
                    prg.progress(100); stt.text("✅ ဘာသာပြန်ခြင်း ပြီးမြောက်ပါပြီ!")
                    st.success("ဘာသာပြန်စာသား ရရှိပါပြီ။ Step 2 သို့ ဆက်သွားပါ။")
                else:
                    st.error("❌ ဘာသာပြန်ခြင်း မအောင်မြင်ပါ။")
            except Exception as e:
                st.error(f"❌ အမှား: {str(e)}")

    st.text_area("ရလာသော မြန်မာစာသား", value=st.session_state.step1_text, height=300, key="s1_txt_area")

# ============ STEP 2 ============
with tab2:
    st.header("Step 2️⃣: စာသား → အသံ + SRT")
    s2_input = st.text_area("ဘာသာပြန်စာသားကို ဤနေရာတွင် ထည့်ပါ (သို့မဟုတ် Step 1 မှ auto ရယူပါ)", value=st.session_state.step1_text, height=250)
    target_dur = st.number_input("အသံအရှည်ကို ချိန်ညှိရန် (စက္ကန့်) - ၀ ထားပါက မူရင်းအတိုင်း ထွက်ပါမည်", 0, 600, 0)
    
    if st.button("🎙️ အသံထုတ်လုပ်ရန်"):
        if not s2_input.strip():
            st.error("စာသားထည့်ပေးပါ။")
        else:
            prg = st.progress(0); stt = st.empty()
            try:
                stt.text("🔊 အသံဖိုင် ထုတ်လုပ်နေပါသည်...")
                ao = os.path.join(tempfile.gettempdir(), f"audio_{int(time.time())}.mp3")
                
                rate = f"+{int((v_speed-50)*2)}%" if v_speed>=50 else f"{int((v_speed-50)*2)}%"
                pitch = f"+{int((v_pitch-50)*2)}Hz" if v_pitch>=50 else f"{int((v_pitch-50)*2)}Hz"
                voice = MYANMAR_VOICES[voice_choice]
                
                # Split by sentence marker
                segments = [s.strip() for s in re.split(r'[။\n]+', s2_input) if s.strip()]
                if not segments: segments = [s2_input]
                
                temp_files = []; cur_t = 0.0; srt_blocks = []
                
                async def gen_all():
                    nonlocal cur_t
                    for idx, txt in enumerate(segments):
                        p = tempfile.mktemp(suffix=".mp3")
                        communicate = edge_tts.Communicate(txt, voice, rate=rate, pitch=pitch)
                        await communicate.save(p)
                        d = get_dur(p)
                        if d > 0:
                            srt_blocks.append(f"{len(srt_blocks)+1}\n{fmt_srt(cur_t)} --> {fmt_srt(cur_t+d)}\n{wrap_text(txt)}\n\n")
                            temp_files.append(p)
                            cur_t += d
                
                asyncio.run(gen_all())
                
                if not temp_files: raise Exception("အသံထုတ်မရပါ။")
                
                l_p = tempfile.mktemp(suffix=".txt")
                with open(l_p, "w", encoding='utf-8') as f:
                    f.write("\n".join([f"file '{os.path.abspath(p)}'" for p in temp_files]))
                
                raw_ao = tempfile.mktemp(suffix=".mp3")
                subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", l_p, "-c", "copy", raw_ao], capture_output=True)
                
                # Duration Adjustment
                actual_dur = get_dur(raw_ao)
                if target_dur > 0 and actual_dur > 0:
                    factor = actual_dur / target_dur
                    factor = np.clip(factor, 0.5, 2.0)
                    subprocess.run(["ffmpeg", "-y", "-i", raw_ao, "-filter:a", f"atempo={factor}", ao], capture_output=True)
                    # Adjust SRT timestamps
                    adjusted_srt = []
                    for line in "".join(srt_blocks).splitlines(keepends=True):
                        if "-->" in line:
                            s, e = line.split(" --> ")
                            s_s = sum(float(x)*60**i for i,x in enumerate(reversed(s.replace(",",".").split(":")))) / factor
                            e_s = sum(float(x)*60**i for i,x in enumerate(reversed(e.replace(",",".").split(":")))) / factor
                            adjusted_srt.append(f"{fmt_srt(s_s)} --> {fmt_srt(e_s)}\n")
                        else: adjusted_srt.append(line)
                    st.session_state.step2_srt = "".join(adjusted_srt)
                else:
                    shutil.copy(raw_ao, ao)
                    st.session_state.step2_srt = "".join(srt_blocks)
                
                st.session_state.step2_audio = ao
                prg.progress(100); stt.text("✅ အသံထုတ်လုပ်ပြီးပါပြီ!")
                st.audio(ao)
            except Exception as e:
                st.error(f"❌ အမှား: {str(e)}")

# ============ STEP 3 ============
with tab3:
    st.header("Step 3️⃣: SRT စာတန်းဖိုင် စစ်ဆေးရန်")
    s3_srt = st.text_area("SRT Content", value=st.session_state.step2_srt, height=400)
    if st.button("✅ SRT အတည်ပြုရန်"):
        st.session_state.step2_srt = s3_srt
        st.success("SRT ကို အတည်ပြုပြီးပါပြီ။ Step 4 သို့ ဆက်သွားပါ။")

# ============ STEP 4 ============
with tab4:
    st.header("Step 4️⃣: ဗီဒီယို ပေါင်းစပ်ခြင်း (Auto Blur)")
    col1, col2 = st.columns(2)
    with col1: up4_v = st.file_uploader("မူရင်း ဗီဒီယိုဖိုင်", type=["mp4", "mov", "avi"])
    with col2: up4_a = st.file_uploader("အသံဖိုင် (Step 2 မှ ရလာသည်ကို သုံးနိုင်သည်)", type=["mp3", "wav", "m4a"])
    
    s4_srt = st.text_area("SRT စာတန်းဖိုင်", value=st.session_state.step2_srt, height=150)
    
    if st.button("🎬 ဗီဒီယို ပေါင်းစပ်ထုတ်လုပ်ရန်"):
        if not up4_v or not (up4_a or st.session_state.step2_audio) or not s4_srt:
            st.error("လိုအပ်သော ဖိုင်များအားလုံး ထည့်ပေးပါ။")
        else:
            prg = st.progress(0); stt = st.empty()
            try:
                stt.text("📹 ဗီဒီယို ပေါင်းစပ်နေပါသည်...")
                v_p = os.path.join(tempfile.gettempdir(), f"v4_{int(time.time())}.mp4")
                with open(v_p, "wb") as f: f.write(up4_v.getvalue())
                
                a_p = os.path.join(tempfile.gettempdir(), f"a4_{int(time.time())}.mp3")
                if up4_a:
                    with open(a_p, "wb") as f: f.write(up4_a.getvalue())
                else:
                    shutil.copy(st.session_state.step2_audio, a_p)
                
                srt_p = os.path.join(tempfile.gettempdir(), f"s4_{int(time.time())}.srt")
                with open(srt_p, "w", encoding='utf-8') as f: f.write(s4_srt)
                
                # FFmpeg Filter Logic (BoxBlur + Subtitles)
                res = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", v_p], capture_output=True, text=True)
                vw, vh = map(int, res.stdout.strip().split(','))
                
                by_px = int(vh * (blur_y / 100))
                bh_px = int(vh * (blur_h / 100))
                
                filter_str = (
                    f"[0:v]split[main][to_blur];"
                    f"[to_blur]crop=iw:{bh_px}:0:{by_px},boxblur=10[blurred];"
                    f"[main][blurred]overlay=0:{by_px}[v_blur];"
                    f"[v_blur]subtitles='{srt_p}':force_style='FontName=Pyidaungsu,FontSize={font_sz},PrimaryColour=&H00FFFFFF&'"
                )
                
                out_v = os.path.join(tempfile.gettempdir(), f"final_{int(time.time())}.mp4")
                cmd = [
                    "ffmpeg", "-y", "-i", v_p, "-i", a_p,
                    "-filter_complex", filter_str,
                    "-c:a", "aac", "-map", "1:a", out_v
                ]
                
                subprocess.run(cmd, capture_output=True)
                
                if os.path.exists(out_v):
                    prg.progress(100); stt.text("✅ ဗီဒီယို ပေါင်းစပ်ပြီးပါပြီ!")
                    with open(out_v, "rb") as f:
                        st.download_button("⬇️ ဒေါင်းလုဒ်ရယူရန်", f, file_name="movie_recap_final.mp4")
                else:
                    st.error("❌ ဗီဒီယို ထုတ်လုပ်ခြင်း မအောင်မြင်ပါ။")
            except Exception as e:
                st.error(f"❌ အမှား: {str(e)}")

st.markdown("---")
st.markdown("🎬 **Movie Recap AI V18** | မူရင်း API Logic အသုံးပြုထားပါသည်")

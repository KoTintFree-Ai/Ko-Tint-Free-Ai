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
import shutil
import psutil
import gc

# --- CONFIGURATION ---
API_VERSIONS = ["v1beta", "v1"]
DEFAULT_MODELS = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-pro"]

st.set_page_config(
    page_title="Myanmar AI Audio & SRT Generator",
    page_icon="🎙️",
    layout="centered"
)

# --- CSS: CUSTOM STYLING ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display:none;}
    .stButton>button {width: 100%;}
    </style>
    """, unsafe_allow_html=True)

# Session State Initialization
def init_state():
    keys = ['audio_path', 'srt_data', 'last_uploaded', 'processing_done', 'valid_keys_info', 'active_key']
    for k in keys:
        if k not in st.session_state: st.session_state[k] = None
    for i in range(1, 6):
        if f'key_{i}' not in st.session_state: st.session_state[f'key_{i}'] = ""
    if st.session_state.processing_done is None: st.session_state.processing_done = False
    if st.session_state.valid_keys_info is None: st.session_state.valid_keys_info = {}
    if 'target_sec' not in st.session_state: st.session_state.target_sec = 150

init_state()

st.title("🎙️ Myanmar AI Audio & SRT Generator")
st.markdown("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုမှ မြန်မာဘာသာပြန် အသံဖိုင်နှင့် စာတန်း (SRT) ထုတ်ပေးသောစနစ်")

# --- ERROR TRANSLATOR ---
def translate_error(err_msg, status_code=None):
    err_msg = str(err_msg).lower()
    if "api_key_invalid" in err_msg or "invalid api key" in err_msg or status_code == 403:
        return "API Key မမှန်ကန်ပါ။"
    if "quota" in err_msg or "429" in err_msg or status_code == 429:
        return "API Key အသုံးပြုမှု ပမာဏ ပြည့်သွားပါပြီ။"
    if "location" in err_msg or "not supported" in err_msg:
        return "သင်၏ ဒေသတွင် ဤ API ကို ပိတ်ထားပါသည်။ (VPN လိုအပ်နိုင်ပါသည်)"
    return f"အမှားအယွင်းတစ်ခု ဖြစ်ပေါ်နေပါသည်။ ({err_msg})"

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ ဆက်တင်များ")
    
    # RAM Monitor
    process = psutil.Process(os.getpid())
    ram_used = process.memory_info().rss / (1024 * 1024)
    st.write(f"🖥️ RAM: {ram_used:.0f}/1024MB")
    
    if st.button("🧹 RAM ရှင်းထုတ်ရန်"):
        st.cache_data.clear()
        gc.collect()
        st.success("RAM ရှင်းလင်းပြီးပါပြီ")
    
    st.markdown("---")
    st.subheader("🔑 Gemini API Keys")
    k1 = st.text_input("API Key 1", type="password", key="key_1")
    show_more = st.toggle("ကျန် Keys များ ဖော်ပြရန်", value=False)
    if show_more:
        for i in range(2, 6):
            st.text_input(f"API Key {i}", type="password", key=f"key_{i}")
    
    api_keys = [st.session_state.get(f"key_{i}") for i in range(1, 6) if st.session_state.get(f"key_{i}")]

    if st.button("🔌 Keys စစ်ဆေးရန်"):
        if not api_keys:
            st.error("API Key အရင်ထည့်ပါ။")
        else:
            st.session_state.valid_keys_info = {}
            with st.spinner("စစ်ဆေးနေသည်..."):
                for k in api_keys:
                    for ver in API_VERSIONS:
                        try:
                            url = f"https://generativelanguage.googleapis.com/{ver}/models?key={k}"
                            r = requests.get(url, timeout=10)
                            if r.status_code == 200:
                                data = r.json()
                                models = [m['name'].split('/')[-1] for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
                                st.session_state.valid_keys_info[k] = {"version": ver, "models": models}
                                break
                        except: continue
            st.success("Keys စစ်ဆေးပြီးပါပြီ")

# --- UTILS ---
def get_dur(p):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", p], capture_output=True, text=True)
        return float(r.stdout.strip())
    except: return 0.0

def fmt_srt(seconds):
    td = time.strftime('%H:%M:%S', time.gmtime(seconds))
    ms = int((seconds % 1) * 1000)
    return f"{td},{ms:03d}"

def wrap_text(text, max_w=40):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_w: cur += (w + " ")
        else: lines.append(cur.strip()); cur = w + " "
    if cur: lines.append(cur.strip())
    return "\n".join(lines)

def parse_srt_text(text):
    text = re.sub(r'\d+\n\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}\n', '', text)
    parts = re.split(r'\n\s*\n', text)
    return [p.strip() for p in parts if p.strip()]

async def gen_audio_srt(text, out_p, voice, target_sec):
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
            communicate = edge_tts.Communicate(clean_txt, voice)
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
    factor = total / target_sec if target_sec > 0 else 1.0
    factor = max(0.7, min(2.0, factor))
    
    if abs(factor - 1.0) > 0.01:
        subprocess.run(["ffmpeg", "-y", "-i", raw, "-filter:a", f"atempo={factor}", out_p], capture_output=True)
    else:
        shutil.copy(raw, out_p)
        
    final_srt = []
    for line in "".join(srt_blocks).splitlines(keepends=True):
        if "-->" in line:
            try:
                s, e = line.split(" --> ")
                s_s = sum(float(x)*60**i for i,x in enumerate(reversed(s.replace(",",".").split(":")))) / factor
                e_s = sum(float(x)*60**i for i,x in enumerate(reversed(e.replace(",",".").split(":")))) / factor
                final_srt.append(f"{fmt_srt(s_s)} --> {fmt_srt(e_s)}\n")
            except: final_srt.append(line)
        else: final_srt.append(line)
    
    for p in temp_files: 
        if os.path.exists(p): os.remove(p)
    if os.path.exists(l_p): os.remove(l_p)
    if os.path.exists(raw): os.remove(raw)
    
    return "".join(final_srt)

# --- MAIN UI ---
up = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if up:
    col1, col2 = st.columns(2)
    with col1:
        voice_opt = st.selectbox("အသံရွေးချယ်ပါ", ["နီလာ (Female)", "သီဟ (Male)"])
        v_id = "my-MM-NilarNeural" if "နီလာ" in voice_opt else "my-MM-ThihaNeural"
    with col2:
        target_sec = st.number_input("အသံဖိုင် ကြာချိန် (စက္ကန့်)", min_value=10, max_value=600, value=150)

    if not api_keys:
        st.warning("⚠️ Sidebar တွင် Gemini API Key ထည့်ပေးပါ")
    elif st.button("🚀 စတင်လုပ်ဆောင်ရန်"):
        prg = st.progress(0)
        stt = st.empty()
        try:
            # Save input
            tp = os.path.join(tempfile.gettempdir(), f"input_{up.name}")
            with open(tp, "wb") as f: f.write(up.getvalue())
            
            # Step 1: Extract/Compress Audio
            stt.text("📊 အသံဖိုင်ကို ပြင်ဆင်နေပါသည်...")
            prg.progress(20)
            ag = tempfile.mktemp(suffix=".mp3")
            subprocess.run(["ffmpeg", "-y", "-i", tp, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], capture_output=True)

            # Step 2: AI Translation
            stt.text("⏳ ဘာသာပြန်နေပါသည် (Gemini API)...")
            prg.progress(40)
            
            with open(ag, 'rb') as f: b64 = base64.b64encode(f.read()).decode()
            prm = f"Listen to this audio and translate it into a Myanmar Movie Recap style narration script in SRT format. Target duration: {target_sec} seconds. Output ONLY the SRT content."
            cont = [{"role":"user","parts":[{"text":prm},{"inline_data":{"mime_type":"audio/mpeg","data":b64}}]}]
            
            srt_res = None
            for k, info in st.session_state.valid_keys_info.items():
                ver = info['version']
                for m in info['models']:
                    if 'flash' in m or 'pro' in m:
                        url = f"https://generativelanguage.googleapis.com/{ver}/models/{m}:generateContent?key={k}"
                        r = requests.post(url, json={"contents":cont}, timeout=120)
                        if r.status_code == 200:
                            srt_res = r.json()['candidates'][0]['content']['parts'][0]['text']
                            break
                if srt_res: break
            
            if not srt_res:
                # Try with all keys if check didn't run or failed
                for k in api_keys:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={k}"
                    r = requests.post(url, json={"contents":cont}, timeout=120)
                    if r.status_code == 200:
                        srt_res = r.json()['candidates'][0]['content']['parts'][0]['text']
                        break

            if not srt_res: raise Exception("ဘာသာပြန်ခြင်း မအောင်မြင်ပါ။ API Key သို့မဟုတ် Internet ကို စစ်ဆေးပါ။")

            # Step 3: TTS
            stt.text("🔊 အသံဖိုင် ထုတ်လုပ်နေပါသည်...")
            prg.progress(70)
            ao = os.path.join(tempfile.gettempdir(), f"output_{int(time.time())}.mp3")
            st.session_state.srt_data = asyncio.run(gen_audio_srt(srt_res, ao, v_id, target_sec))
            
            with open(ao, "rb") as f: st.session_state.audio_path = f.read()
            st.session_state.processing_done = True
            prg.progress(100)
            stt.success("✅ အားလုံး ပြီးစီးပါပြီ!")
            
        except Exception as e:
            st.error(f"Error: {str(e)}")

    if st.session_state.processing_done:
        st.markdown("---")
        st.subheader("📥 ရလဒ်များကို ရယူရန်")
        
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            if st.session_state.audio_path:
                st.download_button("🎵 အသံဖိုင် (MP3) ဒေါင်းလုဒ်လုပ်ရန်", st.session_state.audio_path, "narration.mp3", "audio/mp3")
        with col_dl2:
            if st.session_state.srt_data:
                st.download_button("📄 စာတန်းဖိုင် (SRT) ဒေါင်းလုဒ်လုပ်ရန်", st.session_state.srt_data, "narration.srt", "text/plain")
        
        with st.expander("📝 စာသားများကို ကြည့်ရန်"):
            st.text_area("SRT Content", st.session_state.srt_data, height=300)

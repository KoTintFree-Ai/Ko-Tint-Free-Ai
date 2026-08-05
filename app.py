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
import re
import shutil
import psutil
import gc

# --- CONFIGURATION ---
API_VERSIONS = ["v1beta", "v1"]
DEFAULT_MODELS = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-pro"]

st.set_page_config(
    page_title="Movie Recap AI Audio Pro V8.2",
    page_icon="🎙️",
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
    keys = ['myanmar_text', 'audio_path', 'srt_data', 'last_uploaded', 'processing_done', 'valid_keys_info', 'active_key']
    for k in keys:
        if k not in st.session_state: st.session_state[k] = None
    for i in range(1, 6):
        if f'key_{i}' not in st.session_state: st.session_state[f'key_{i}'] = ""
    if st.session_state.processing_done is None: st.session_state.processing_done = False
    if st.session_state.valid_keys_info is None: st.session_state.valid_keys_info = {}
    if 'v_speed' not in st.session_state: st.session_state.v_speed = 55
    if 'v_pitch' not in st.session_state: st.session_state.v_pitch = 50
    if 'target_min' not in st.session_state: st.session_state.target_min = 2
    if 'target_sec' not in st.session_state: st.session_state.target_sec = 30

init_state()

st.title("🎙️ Movie Recap AI Audio Pro V8.2")
st.markdown("အင်္ဂလိပ် ဗီဒီယိုမှ မြန်မာ Movie Recap အသံဖိုင်နှင့် SRT ထုတ်ပေးသော AI")

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
    
    if st.button("🧹 RAM ရှင်းထုတ်ရန်"):
        keys_to_keep = {f'key_{i}': st.session_state.get(f'key_{i}', "") for i in range(1, 6)}
        keys_to_keep['valid_keys_info'] = st.session_state.get('valid_keys_info', {})
        keys_to_keep['active_key'] = st.session_state.get('active_key', None)
        st.cache_data.clear()
        for k, v in keys_to_keep.items(): st.session_state[k] = v
        gc.collect()
        st.success("RAM ရှင်းလင်းပြီးပါပြီ (Keys များကို ထိန်းသိမ်းထားပါသည်)")
    
    st.markdown("---")
    st.subheader("🔑 Gemini API Keys (၅ ခုအထိ)")
    
    # Auto Key Extractor Logic
    def auto_parse_keys():
        val = st.session_state.key_1
        found = re.findall(r'AIzaSy[a-zA-Z0-9_-]{33}', val)
        if len(found) > 1:
            for i, k in enumerate(found[:5]):
                st.session_state[f'key_{i+1}'] = k
            st.success(f"✅ Keys {len(found[:5])} ခုကို အလိုအလျောက် ခွဲထုတ်ပြီးပါပြီ။")

    st.text_input("API Key 1", type="password", key="key_1", on_change=auto_parse_keys)
    
    show_more_keys = st.toggle("🔽 ကျန် API Keys များ ဖော်ပြရန်", value=False, key="show_more_keys_toggle")
    if show_more_keys:
        st.text_input("API Key 2", type="password", key="key_2")
        st.text_input("API Key 3", type="password", key="key_3")
        st.text_input("API Key 4", type="password", key="key_4")
        st.text_input("API Key 5", type="password", key="key_5")
    else:
        # Important: maintain state when hidden
        pass
    
    # Collect keys for testing
    api_keys = [st.session_state[f'key_{i}'] for i in range(1, 6) if st.session_state[f'key_{i}']]

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
                                models = [m['name'].split('/')[-1] for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
                                st.session_state.valid_keys_info[k] = {"version": ver, "models": models}
                                if not st.session_state.active_key: st.session_state.active_key = k
                                st.success(f"✅ Key {i+1} အောင်မြင်ပါသည်။")
                                break
                        except: continue
            st.rerun()

    st.markdown("---")
    st.subheader("⏱️ အချိန် ထိန်းချုပ်ရန်")
    tm = plus_minus_slider("မိနစ်", "target_min", 0, 60, 1)
    ts = plus_minus_slider("စက္ကန့်", "target_sec", 0, 59, 1)
    target_sec = (tm * 60) + ts
    st.info(f"သတ်မှတ်ထားသော အချိန်: {tm} မိနစ် {ts} စက္ကန့်")

    st.markdown("---")
    st.subheader("🔊 အသံ ဆက်တင်များ")
    v_choice = st.selectbox("အသံရွေးချယ်ပါ", ["သီဟ (အမျိုးသားသံ)", "နီလာ (အမျိုးသမီးသံ)"])
    v_id = "my-MM-ThihaNeural" if "သီဟ" in v_choice else "my-MM-NilarNeural"
    
    v_speed = plus_minus_slider("အသံနှုန်း", "v_speed", 1, 100, 1)
    v_pitch = plus_minus_slider("Pitch", "v_pitch", 1, 100, 1)

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
                except: final_srt.append(line)
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

# --- MAIN UI ---
up = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if up:
    fid = up.name + str(up.size)
    if st.session_state.last_uploaded != fid:
        st.session_state.last_uploaded = fid
        tp = os.path.join(tempfile.gettempdir(), f"input_{fid}." + up.name.split(".")[-1])
        with open(tp, "wb") as f: f.write(up.getvalue())

    if not api_keys:
        st.warning("⚠️ Sidebar တွင် Gemini API Key ထည့်ပေးပါ")
    elif st.button("🚀 စတင်လုပ်ဆောင်ရန်"):
        prg = st.progress(0); stt = st.empty()
        try:
            for k in ['audio_path', 'srt_data']: st.session_state[k] = None
            
            # === STEP 1: Audio Compression ===
            stt.text("📊 အဆင့် ၁: အသံဖိုင်ကို ပြင်ဆင်နေပါသည်...")
            prg.progress(10)
            tp = os.path.join(tempfile.gettempdir(), f"input_{fid}." + up.name.split(".")[-1])
            ag = tempfile.mktemp(suffix=".mp3")
            subprocess.run(["ffmpeg", "-y", "-i", tp, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], capture_output=True)

            # === STEP 2: AI Translation (Original Prompt) ===
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
            
            with st.status("🌐 Gemini API နှင့် ဆက်သွယ်ပြီး ဘာသာပြန်နေပါသည်...", expanded=True) as status:
                for k_idx, k in enumerate(api_keys):
                    status.write(f"🔑 Key {k_idx+1} ကို အသုံးပြုနေပါသည်...")
                    info = st.session_state.valid_keys_info.get(k)
                    versions = [info['version']] if info else API_VERSIONS
                    models = info['models'] if info else DEFAULT_MODELS
                    models = sorted(models, key=lambda x: 0 if 'flash' in x.lower() else 1)
                    
                    for ver in versions:
                        for m in models:
                            try:
                                status.write(f"🤖 Model: {m} ဖြင့် ဘာသာပြန်နေပါသည်...")
                                url = f"https://generativelanguage.googleapis.com/{ver}/models/{m}:generateContent?key={k}"
                                r = requests.post(url, json={"contents":cont}, timeout=180)
                                if r.status_code == 200:
                                    data = r.json()
                                    if 'candidates' in data and data['candidates'][0]['content']['parts']:
                                        srt_res = data['candidates'][0]['content']['parts'][0]['text']
                                        if srt_res:
                                            st.session_state.active_key = k
                                            status.update(label="✅ ဘာသာပြန်ခြင်း ပြီးမြောက်ပါပြီ!", state="complete")
                                            break
                                else:
                                    msg = r.json().get('error', {}).get('message', r.text)
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
            ao = os.path.join(tempfile.gettempdir(), f"output_{int(time.time())}.mp3")
            st.session_state.srt_data, _ = asyncio.run(gen_audio_srt(srt_res, ao, v_id, st.session_state.v_speed, st.session_state.v_pitch, target_sec))
            
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

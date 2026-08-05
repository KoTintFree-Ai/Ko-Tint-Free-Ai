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

# --- Session State ---
def init_state():
    keys = ['audio_path', 'srt_data', 'last_uploaded', 'processing_done',
            'valid_keys_info', 'active_key', 'bulk_msg', 'test_results']
    for k in keys:
        if k not in st.session_state: st.session_state[k] = None
    for i in range(1, 6):
        if f'key_{i}' not in st.session_state: st.session_state[f'key_{i}'] = ""

    if st.session_state.processing_done is None: st.session_state.processing_done = False
    if st.session_state.bulk_msg is None: st.session_state.bulk_msg = ""
    if st.session_state.test_results is None: st.session_state.test_results = []
    if st.session_state.valid_keys_info is None: st.session_state.valid_keys_info = {}
    if 'v_speed' not in st.session_state: st.session_state.v_speed = 55
    if 'v_pitch' not in st.session_state: st.session_state.v_pitch = 50
    if 'target_min' not in st.session_state: st.session_state.target_min = 2
    if 'target_sec' not in st.session_state: st.session_state.target_sec = 30

# --- PERSISTENT KEY STORAGE ---
KEYS_FILE = os.path.join(SCRIPT_DIR, "saved_keys.json")

def save_keys_to_file():
    keys_data = {}
    for i in range(1, 6):
        k = st.session_state.get(f'key_{i}', "")
        if k: keys_data[f'key_{i}'] = k
    if keys_data:
        try:
            with open(KEYS_FILE, 'w') as f:
                json.dump(keys_data, f)
        except Exception:
            pass

def load_keys_from_file():
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, 'r') as f:
                keys_data = json.load(f)
            for k, v in keys_data.items():
                if k in st.session_state and not st.session_state.get(k):
                    st.session_state[k] = v
                # Also set the widget values if they are in session state
                wk = f"w_{k}"
                if wk not in st.session_state:
                    st.session_state[wk] = v
        except Exception:
            pass

init_state()
load_keys_from_file()

# --- HELPER: SLIDER WITH PLUS/MINUS ---
def plus_minus_slider(label, key, min_val, max_val, step=1):
    import numpy as np
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
        return "API URL သို့မဟုတ် Model အမည်ကို ရှာမတွေ့ပါ။"
    if "safety" in err_msg or "blocked" in err_msg:
        return "မူပိုင်ခွင့် သို့မဟုတ် လုံခြုံရေး စည်းကမ်းချက်များကြောင့် Google မှ ဘာသာပြန်ရန် ငြင်းဆိုလိုက်ပါသည်။"
    return f"အမှားအယွင်းတစ်ခု ဖြစ်ပေါ်နေပါသည်။ ({err_msg})"

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
    import numpy as np
    rate = f"+{int((spd-55)*2)}%" if spd>=55 else f"{int((spd-55)*2)}%"
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
            import shutil
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
        import shutil
        shutil.copy(raw, out_p)
        res_srt = "".join(srt_blocks)

    if os.path.exists(raw): os.remove(raw)

    return res_srt, get_dur(out_p)

# --- TITLE ---
st.title("🎬 Movie Recap AI")
st.markdown("အင်္ဂလိပ် ဗီဒီယို/အသံဖိုင်မှ မြန်မာ Movie Recap ဘာသာပြန်အသံ + SRT ထုတ်ပေးသော AI")

# --- SIDEBAR ---
with st.sidebar:
    st.subheader("🔑 Gemini API Keys (၅ ခုအထိ)")
    if st.session_state.active_key:
        st.success("🟢 Gemini API အလုပ်လုပ်နေပါသည်")

    # Key inputs
    st.text_input("Key 1", type="password", value=st.session_state.get('key_1', ''), key="w_key_1")
    show_more = st.toggle("🔽 ကျန် Keys များ ဖော်ပြရန်", value=False, key="show_more_keys")
    if show_more:
        for i in range(2, 6):
            st.text_input(f"Key {i}", type="password", value=st.session_state.get(f'key_{i}', ''), key=f"w_key_{i}")

    # Sync widget keys to session state
    def sync_keys():
        for i in range(1, 6):
            wk = f"w_key_{i}"
            if st.session_state.get(wk):
                st.session_state[f"key_{i}"] = st.session_state[wk]
        save_keys_to_file()

    sync_keys()
    api_keys = [st.session_state.get(f'key_{i}', '').strip() for i in range(1, 6) if st.session_state.get(f'key_{i}', '').strip()]

    # Bulk paste
    st.markdown("---")
    st.text_area("Key များအားလုံးကို ဤနေရာတွင် Paste ချပါ", placeholder="ဥပမာ- ၁။ AIza... ၂။ AQ... စသည်ဖြင့်", height=80, key="bulk_key_input")

    def auto_fill():
        if st.session_state.bulk_key_input:
            text = st.session_state.bulk_key_input
            gemini_found = re.findall(r'(AIza[0-9A-Za-z-_]{30,}|AQ\.[0-9A-Za-z-_]{30,})', text)
            gemini_found = [k.strip().strip('။၊.()[]{}<>:;*') for k in gemini_found]
            gemini_found = list(dict.fromkeys(gemini_found))

            msg = []
            if gemini_found:
                for i in range(min(5, len(gemini_found))):
                    st.session_state[f'key_{i+1}'] = gemini_found[i]
                    st.session_state[f'w_key_{i+1}'] = gemini_found[i]
                msg.append(f"✅ Gemini Keys {len(found[:5])} ခု")

            st.session_state.bulk_msg = " ဖြည့်ပြီးပါပြီ: " + ", ".join(msg) if msg else "⚠️ API Key ရှာမတွေ့ပါ။"
            st.session_state.bulk_key_input = ""
            save_keys_to_file()
            st.rerun()

    st.button("📋 Key များ Auto-Fill", on_click=auto_fill)
    if st.session_state.bulk_msg:
        st.info(st.session_state.bulk_msg)

    # Test Keys
    st.markdown("---")
    if st.button("🔌 Keys စမ်းသပ်ရန်"):
        if not api_keys:
            st.error("API Key အရင်ထည့်ပေးပါ။")
        else:
            st.session_state.test_results = []
            with st.spinner("Keys များကို စစ်ဆေးနေသည်..."):
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

    # Voice & Settings
    st.markdown("---")
    st.subheader("🔊 အသံ ဆက်တင်များ")
    v_choice = st.selectbox("အသံရွေးချယ်ပါ", ["သီဟ (အမျိုးသားသံ)", "နီလာ (အမျိုးသမီးသံ)"])
    v_id = "my-MM-ThihaNeural" if "သီဟ" in v_choice else "my-MM-NilarNeural"

    v_speed = plus_minus_slider("အသံနှုန်း", "v_speed", 1, 100, 1)
    v_pitch = plus_minus_slider("Pitch", "v_pitch", 1, 100, 1)

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

# --- MAIN AREA ---
up = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if up:
    fid = hash(up.name)
    tp = os.path.join(tempfile.gettempdir(), f"input_{fid}." + up.name.split(".")[-1])
    if not os.path.exists(tp) or st.session_state.get('last_uploaded') != fid:
        with open(tp, "wb") as f: f.write(up.getbuffer())
        st.session_state.last_uploaded = fid

    if not api_keys:
        st.warning("⚠️ Sidebar တွင် Gemini API Key ထည့်ပေးပါ")
    elif st.button("🚀 စတင်လုပ်ဆောင်ရန်"):
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            st.error("❌ FFmpeg မရရှိပါ။")
        else:
            prg = st.progress(0)
            stt = st.empty()
            try:
                for k in ['audio_path', 'srt_data']:
                    st.session_state[k] = None

                # === STEP 1: Audio Compression ===
                stt.text("📊 အဆင့် ၁: အသံဖိုင်ကို အမြန်ဆုံးဖြစ်အောင် ချုံ့နေပါသည်...")
                prg.progress(10)
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

                with open(ag, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode()
                cont = [{"role":"user","parts":[{"text":prm},{"inline_data":{"mime_type":"audio/mpeg","data":b64}}]}]

                srt_res = None
                errors = []

                with st.status("🌐 AI API နှင့် ဆက်သွယ်ပြီး ဘာသာပြန်နေပါသည်...", expanded=True) as status:
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
                                        try:
                                            msg = r.json().get('error', {}).get('message', r.text)
                                        except:
                                            msg = r.text
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
                    st.session_state.srt_data, audio_final_dur = asyncio.run(
                        gen_audio_srt(srt_res, ao, v_id, st.session_state.v_speed, st.session_state.v_pitch, target_sec if fit_dur else 0)
                    )
                    status.update(label="✅ အသံဖိုင်အားလုံး ပေါင်းစပ်ပြီးပါပြီ!", state="complete")
                st.session_state.audio_path = ao
                prg.progress(100)
                stt.text("✅ အောင်မြင်စွာ ပြီးဆုံးပါပြီ!")
                st.balloons()
                st.session_state.processing_done = True

                if os.path.exists(ag): os.remove(ag)

            except Exception as e:
                st.error(f"❌ အမှားအယွင်း: {str(e)}")
                st.session_state.processing_done = False

# --- DOWNLOAD SECTION ---
if st.session_state.processing_done:
    st.markdown("---")
    st.subheader("📥 Download")

    if st.session_state.audio_path and os.path.exists(st.session_state.audio_path):
        st.audio(st.session_state.audio_path)
        with open(st.session_state.audio_path, "rb") as f:
            st.download_button("📥 အသံဖိုင်ကို သိမ်းဆည်းရန် (MP3)", f, "recap_audio.mp3", "audio/mp3")

    if st.session_state.srt_data:
        st.download_button("📥 စာတန်းထိုး (SRT) ကို သိမ်းဆည်းရန်", st.session_state.srt_data, "recap.srt", "text/plain")

    if st.button("🔄 ပြန်လုပ်ရန်"):
        st.session_state.processing_done = False
        st.session_state.audio_path = None
        st.session_state.srt_data = None
        st.rerun()

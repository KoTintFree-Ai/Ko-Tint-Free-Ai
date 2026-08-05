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
import shutil
import numpy as np

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
    keys = ['audio_path', 'srt_data', 'plain_text', 'word_count', 'last_uploaded', 'processing_done',
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
                wk = f"w_{k}"
                if wk not in st.session_state:
                    st.session_state[wk] = v
        except Exception:
            pass

init_state()
load_keys_from_file()

# --- HELPER: SLIDER WITH PLUS/MINUS ---
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

def get_plain_text(srt_text):
    """Aggressively clean SRT to get ONLY the narration text and remove ALL numbers."""
    # 1. Remove markdown code blocks
    text = re.sub(r'```srt?', '', srt_text, flags=re.IGNORECASE)
    text = re.sub(r'```', '', text).strip()
    
    # 2. Remove SRT timestamps
    text = re.sub(r'\d{1,2}:\d{1,2}:\d{1,2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{1,2}:\d{1,2}[,.]\d{1,3}', '', text)
    
    # 3. Split by lines to process each line
    lines = text.split('\n')
    clean_lines = []
    for line in lines:
        l = line.strip()
        if not l: continue
        
        # 4. Remove standalone numbers (SRT index)
        if re.match(r'^\d+$', l): continue
        
        # 5. Remove numbers at the beginning of sentences (e.g., "1.", "၁။", "(2)")
        l = re.sub(r'^[\(\[]?\d+[\.\)\]။၊\s]*', '', l)
        l = re.sub(r'^[\(\[]?[\u1040-\u1049]+[\.\)\]။၊\s]*', '', l)
        
        # 6. Remove common AI/Recap filler labels
        l = re.sub(r'(?i)^(narration|recap|script|translation|speaker|here is|intro|outro|scene \d+):', '', l)
        
        if l.strip():
            clean_lines.append(l.strip())
            
    return ' '.join(clean_lines)

def count_myanmar_words(text):
    if not text: return 0
    cluster_pattern = r'[\u1000-\u102A\u103F\u1040-\u1049][\u102B-\u103E\u1037\u1038\u1039\u103A]*'
    clusters = re.findall(cluster_pattern, text)
    return len(clusters)

def parse_srt_text(text):
    """Clean and split SRT text into segments for TTS, ensuring NO numbers or fillers are included."""
    clean_full_text = get_plain_text(text)
    
    # Split into segments based on Myanmar punctuation
    segments = []
    parts = re.split(r'([။၊.!?;])', clean_full_text)
    for i in range(0, len(parts)-1, 2):
        seg = (parts[i] + parts[i+1]).strip()
        if seg: segments.append(seg)
    if len(parts) % 2 != 0 and parts[-1].strip():
        segments.append(parts[-1].strip())

    return [s for s in segments if s]

async def gen_audio_srt(text, out_p, vid, spd, ptc, target=0):
    rate = f"+{int((spd-55)*2)}%" if spd>=55 else f"{int((spd-55)*2)}%"
    pitch = f"+{int((ptc-50)*2)}Hz" if ptc>=50 else f"{int((ptc-50)*2)}Hz"
    
    segments = parse_srt_text(text)
    if not segments: segments = [get_plain_text(text)]

    temp_files = []
    cur_t = 0.0
    srt_blocks = []

    for idx, txt in enumerate(segments):
        clean_txt = txt.strip()
        if not clean_txt: continue
        
        # Final safety check: remove any leading numbers/symbols
        clean_txt = re.sub(r'^[\d\u1040-\u1049\.\)\]။၊\s]+', '', clean_txt)
        
        if not clean_txt.strip(): continue
        
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
                    s_s = sum(float(x)*60**i for i,x in enumerate(reversed(s.replace(",",".").split(":")))) / factor
                    e_s = sum(float(x)*60**i for i,x in enumerate(reversed(e.replace(",",".").split(":")))) / factor
                    final_srt.append(f"{fmt_srt(s_s)} --> {fmt_srt(e_s)}\n")
                except: final_srt.append(line)
            else: final_srt.append(line)
        res_srt = "".join(final_srt)
    else:
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

    st.text_input("Key 1", type="password", value=st.session_state.get('key_1', ''), key="w_key_1")
    show_more = st.toggle("🔽 ကျန် Keys များ ဖော်ပြရန်", value=False, key="show_more_keys")
    if show_more:
        for i in range(2, 6):
            st.text_input(f"Key {i}", type="password", value=st.session_state.get(f'key_{i}', ''), key=f"w_key_{i}")

    def sync_keys():
        for i in range(1, 6):
            wk = f"w_key_{i}"
            if st.session_state.get(wk):
                st.session_state[f"key_{i}"] = st.session_state[wk]
        save_keys_to_file()

    sync_keys()
    api_keys = [st.session_state.get(f'key_{i}', '').strip() for i in range(1, 6) if st.session_state.get(f'key_{i}', '').strip()]

    st.markdown("---")
    st.text_area("Key များအားလုံးကို ဤနေရာတွင် Paste ချပါ", placeholder="ဥပမာ- AIza...", height=80, key="bulk_key_input")

    def auto_fill():
        if st.session_state.bulk_key_input:
            text = st.session_state.bulk_key_input
            found = re.findall(r'(AIza[0-9A-Za-z-_]{30,}|AQ\.[0-9A-Za-z-_]{30,})', text)
            found = list(dict.fromkeys([k.strip().strip('။၊.()[]{}<>:;*') for k in found]))
            if found:
                for i in range(min(5, len(found))):
                    st.session_state[f'key_{i+1}'] = found[i]
                    st.session_state[f'w_key_{i+1}'] = found[i]
            st.session_state.bulk_key_input = ""
            save_keys_to_file()
            st.rerun()

    st.button("📋 Key များ Auto-Fill", on_click=auto_fill)

    st.markdown("---")
    if st.button("🔌 Keys စမ်းသပ်ရန်"):
        if not api_keys: st.error("API Key အရင်ထည့်ပေးပါ။")
        else:
            st.session_state.test_results = []
            with st.spinner("Keys များကို စစ်ဆေးနေသည်..."):
                for i, k in enumerate(api_keys):
                    success = False
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
                                success = True; break
                        except: continue
                    if not success: st.session_state.test_results.append(f"❌ Gemini Key {i+1} မမှန်ကန်ပါ။")
            st.rerun()

    if st.session_state.test_results:
        for res in st.session_state.test_results:
            if "✅" in res: st.success(res)
            else: st.error(res)
        if st.button("🗑️ ရလဒ်များ ရှင်းလင်းရန်"):
            st.session_state.test_results = []; st.rerun()

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

# --- MAIN AREA ---
up = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"])

if up:
    fid = hash(up.name)
    tp = os.path.join(tempfile.gettempdir(), f"input_{fid}." + up.name.split(".")[-1])
    if not os.path.exists(tp) or st.session_state.get('last_uploaded') != fid:
        with open(tp, "wb") as f: f.write(up.getbuffer())
        st.session_state.last_uploaded = fid

    if not api_keys: st.warning("⚠️ Sidebar တွင် Gemini API Key ထည့်ပေးပါ")
    elif st.button("🚀 စတင်လုပ်ဆောင်ရန်"):
        if not shutil.which("ffmpeg"): st.error("❌ FFmpeg မရရှိပါ။")
        else:
            prg = st.progress(0); stt = st.empty()
            try:
                for k in ['audio_path', 'srt_data', 'plain_text', 'word_count']: st.session_state[k] = None
                
                stt.text("📊 အဆင့် ၁: အသံဖိုင်ကို ပြင်ဆင်နေပါသည်...")
                prg.progress(10)
                ag = tempfile.mktemp(suffix=".mp3")
                subprocess.run(["ffmpeg", "-y", "-i", tp, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], capture_output=True)

                stt.text("⏳ အဆင့် ၂: ဘာသာပြန်နေပါသည် (Gemini API)...")
                prg.progress(30)
                prm = f"""Listen to this audio and provide a HIGH-ENERGY Myanmar Movie Recap narration.
STRICT RULES:
1. NO FILLERS: Do NOT use "Hello audience", "Welcome back", "Recap by...", or any greetings.
2. NO INTRO/OUTRO: Start directly with the movie scenes. End immediately when the recap is done.
3. NO LABELS: Do NOT include labels like "Narration:", "Scene 1:", or timestamps in the text.
4. NO NUMBERS: Do NOT use numbering like 1., 2., 3. or ၁။၊ ၂။၊ ၃။.
5. PURE CONTENT: Only describe the character actions, emotions, and plot events shown in the audio.
6. SRT FORMAT: Output ONLY in valid SRT format.
7. DURATION: Ensure the narration timing matches the source audio naturally.
8. Standard Myanmar Unicode ONLY."""

                with open(ag, 'rb') as f: b64 = base64.b64encode(f.read()).decode()
                cont = [{"role":"user","parts":[{"text":prm},{"inline_data":{"mime_type":"audio/mpeg","data":b64}}]}]

                srt_res = None
                with st.status("🌐 AI API နှင့် ဆက်သွယ်နေပါသည်...", expanded=True) as status:
                    for k in api_keys:
                        info = st.session_state.valid_keys_info.get(k)
                        versions = [info['version']] if info else API_VERSIONS
                        models = sorted(info['models'] if info else DEFAULT_MODELS, key=lambda x: 0 if 'flash' in x.lower() else 1)
                        for ver in versions:
                            for m in models:
                                try:
                                    r = requests.post(f"https://generativelanguage.googleapis.com/{ver}/models/{m}:generateContent?key={k}", json={"contents":cont}, timeout=180)
                                    if r.status_code == 200:
                                        data = r.json()
                                        if 'candidates' in data and data['candidates'][0]['content']['parts']:
                                            srt_res = data['candidates'][0]['content']['parts'][0]['text']
                                            if srt_res: st.session_state.active_key = k; break
                                except: continue
                            if srt_res: break
                        if srt_res: break

                if not srt_res: raise Exception("ဘာသာပြန်ခြင်း မအောင်မြင်ပါ။ API Keys သို့မဟုတ် Network ကို စစ်ဆေးပါ။")

                stt.text("🔊 အဆင့် ၃: အသံဖိုင် ထုတ်လုပ်နေပါသည်...")
                prg.progress(60)
                ao = os.path.join(tempfile.gettempdir(), f"audio_{int(time.time())}.mp3")
                st.session_state.srt_data, _ = asyncio.run(gen_audio_srt(srt_res, ao, v_id, st.session_state.v_speed, st.session_state.v_pitch, target_sec if fit_dur else 0))
                st.session_state.plain_text = get_plain_text(srt_res)
                st.session_state.word_count = count_myanmar_words(st.session_state.plain_text)
                st.session_state.audio_path = ao
                prg.progress(100); stt.text("✅ အောင်မြင်စွာ ပြီးဆုံးပါပြီ!"); st.balloons()
                st.session_state.processing_done = True
                if os.path.exists(ag): os.remove(ag)
            except Exception as e: st.error(f"❌ အမှားအယွင်း: {str(e)}"); st.session_state.processing_done = False

if st.session_state.processing_done:
    st.markdown("---"); st.subheader("📥 Download & Results")
    col1, col2 = st.columns([2, 1])
    with col1:
        if st.session_state.audio_path:
            st.audio(st.session_state.audio_path)
            with open(st.session_state.audio_path, "rb") as f: st.download_button("📥 MP3 ဒေါင်းလုဒ်", f, "recap_audio.mp3", "audio/mp3")
    with col2:
        if st.session_state.word_count is not None: st.metric("မြန်မာစာလုံးရေ", f"{st.session_state.word_count}")
    if st.session_state.srt_data: st.download_button("📥 SRT ဒေါင်းလုဒ်", st.session_state.srt_data, "recap.srt", "text/plain")
    if st.session_state.plain_text:
        with st.expander("📝 စာသားသက်သက် ကြည့်ရန် (Plain Text)", expanded=True):
            st.text_area("Plain Text Content", st.session_state.plain_text, height=300)
            st.download_button("📥 TXT ဒေါင်းလုဒ်", st.session_state.plain_text, "recap_text.txt", "text/plain")
    if st.button("🔄 ပြန်လုပ်ရန်"):
        st.session_state.processing_done = False; st.rerun()

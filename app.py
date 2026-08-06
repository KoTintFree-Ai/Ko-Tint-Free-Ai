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
    "နီလာ (Nila) - အမျိုးသမီးအသံ": "my-MM"  # Note: Edge TTS uses same locale, but we'll differentiate via pitch
}

# Get the directory where this script is located (for font file path)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(SCRIPT_DIR, "Pyidaungsu.ttf")

st.set_page_config(
    page_title="Movie Recap AI Pro V10.0 - Auto Flow",
    page_icon="🎬",
    layout="wide",
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
    keys = ['step1_video', 'step1_translation', 'step2_audio', 'step2_srt', 'step3_final_srt', 'step4_output', 'valid_keys_info', 'active_key', 'auto_flow_data']
    for k in keys:
        if k not in st.session_state: st.session_state[k] = None
    for i in range(1, 6):
        if f'key_{i}' not in st.session_state: st.session_state[f'key_{i}'] = ""
    if st.session_state.valid_keys_info is None: st.session_state.valid_keys_info = {}
    if 'v_speed' not in st.session_state: st.session_state.v_speed = 50
    if 'v_pitch' not in st.session_state: st.session_state.v_pitch = 50
    if 'v_voice' not in st.session_state: st.session_state.v_voice = "သီဟ (Thiha) - ယောက်ျားအသံ"
    if 'auto_flow_data' not in st.session_state: st.session_state.auto_flow_data = {}

init_state()

st.title("🎬 Movie Recap AI Pro V10.0 - Auto Flow")
st.markdown("အင်္ဂလိပ် ဗီဒီယိုမှ မြန်မာ Movie Recap ပြုလုပ်ပေးသော AI (Thiha/Nila အသံ + Auto-Flow)")

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
    if len(parts) % 2 != 0 and parts[-1].strip():
        segments.append(parts[-1].strip())
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
    if ram_used > 950:
        st.error("🚨 RAM ပြည့်ခါနီးနေပါပြီ!")
    
    if st.button("🧹 RAM ရှင်းထုတ်ရန်"):
        keys_to_keep = {f'key_{i}': st.session_state.get(f'key_{i}', "") for i in range(1, 6)}
        keys_to_keep['valid_keys_info'] = st.session_state.get('valid_keys_info', {})
        keys_to_keep['active_key'] = st.session_state.get('active_key', None)
        st.cache_data.clear()
        for k, v in keys_to_keep.items():
            st.session_state[k] = v
        gc.collect()
        st.success("RAM ရှင်းလင်းပြီးပါပြီ")
    
    st.markdown("---")
    st.subheader("🔑 Gemini API Keys (၅ ခုအထိ)")
    if st.session_state.active_key:
        st.success("🟢 API Key အလုပ်လုပ်နေပါသည်")
    
    k1 = st.text_input("API Key 1", type="password", key="key_1")
    show_more_keys = st.toggle("🔽 ကျန် API Keys များ ဖော်ပြရန်", value=False, key="show_more_keys_toggle")
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
    st.subheader("🎙️ အသံ ဆက်တင်များ")
    st.session_state.v_voice = st.selectbox("အသံ ရွေးချယ်ပါ", list(MYANMAR_VOICES.keys()), key="voice_select")
    st.session_state.v_speed = st.slider("အသံ အမြန်နှုန်း", 0, 100, 50, key="speed_slider")
    st.session_state.v_pitch = st.slider("အသံ အမြင့်မြတ်မှု", 0, 100, 50, key="pitch_slider")

# --- MAIN CONTENT ---
st.header("🎬 Auto-Flow: ဗီဒီယို → မြန်မာစာ → အသံ → SRT → ဗီဒီယို")
st.markdown("ဗီဒီယိုတင်ပြီး အဆင့် ၁-၄ အားလုံးကို အလိုအလျောက် လုပ်ဆောင်ပေးပါ။")

# ============ AUTO FLOW ============
col1, col2 = st.columns([2, 1])

with col1:
    up_video = st.file_uploader("ဗီဒီယို သို့မဟုတ် အော်ဒီယိုဖိုင် ရွေးချယ်ပါ", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"], key="auto_upload")

with col2:
    target_sec = st.number_input("ပန်းချီ အတိုင်းအတာ (စက္ကန့်)", 10, 300, 60, key="auto_target_duration")

if up_video and not api_keys:
    st.error("⚠️ Sidebar တွင် Gemini API Key ထည့်ပေးပါ")
elif up_video and st.button("🚀 Auto-Flow စတင်လုပ်ဆောင်ရန် (Step 1-4)"):
    fid = up_video.name + str(up_video.size)
    tp = os.path.join(tempfile.gettempdir(), f"input_{fid}." + up_video.name.split(".")[-1])
    if not os.path.exists(tp):
        with open(tp, "wb") as f:
            f.write(up_video.getvalue())
    
    prg = st.progress(0)
    stt = st.empty()
    
    try:
        # ========== STEP 1: AUDIO COMPRESSION & TRANSLATION ==========
        stt.text("📊 Step 1/4: အသံဖိုင်ကို ချုံ့ပြီး Gemini ဖြင့် ဘာသာပြန်နေပါသည်...")
        prg.progress(5)
        
        ag = tempfile.mktemp(suffix=".mp3")
        if up_video.name.lower().endswith((".mp4", ".mov", ".avi")):
            subprocess.run(["ffmpeg", "-y", "-i", tp, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], capture_output=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-i", tp, "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], capture_output=True)
        
        # AI Translation
        target_words = int(target_sec * 3.8)
        prm = f"""Listen to this audio and translate it into a HIGH-ENERGY Myanmar Movie Recap style narration.
TARGET DURATION: {target_sec} seconds.
REQUIRED SCRIPT LENGTH: You MUST write exactly around {target_words} Myanmar words to fill the {target_sec} seconds timeframe perfectly.

STRICT RULES:
1. NO FILLER PHRASES
2. FOCUS ON SCENES: Describe ONLY what is happening in the movie
3. TIMING SYNC: Follow the exact sequence of events
4. NO HALLUCINATION: Do not add external information
5. Use Standard Myanmar Unicode

OUTPUT FORMAT: SRT subtitle format with timestamps spanning from 00:00:00,000 to {fmt_srt(target_sec)}"""
        
        with open(ag, 'rb') as f: b64 = base64.b64encode(f.read()).decode()
        cont = [{"role":"user","parts":[{"text":prm},{"inline_data":{"mime_type":"audio/mpeg","data":b64}}]}]
        
        srt_res = None
        errors = []
        
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
                        else:
                            try: msg = r.json().get('error', {}).get('message', r.text)
                            except: msg = r.text
                            errors.append(f"{m}: {translate_error(msg, r.status_code)}")
                    except Exception as e:
                        errors.append(f"{m}: {translate_error(str(e))}")
                if srt_res: break
            if srt_res: break
        
        if not srt_res:
            st.error("❌ Step 1 မအောင်မြင်ပါ - Gemini ဘာသာပြန်ခြင်း ပျက်ကွက်ခဲ့သည်")
            for e in errors: st.info(e)
            raise Exception("ဘာသာပြန်ခြင်း မလုပ်ဆောင်နိုင်ပါ။")
        
        st.session_state.step1_translation = srt_res
        prg.progress(25)
        
        # ========== STEP 2: TTS AUDIO GENERATION ==========
        stt.text("🔊 Step 2/4: အသံဖိုင် ထုတ်လုပ်နေပါသည်...")
        prg.progress(40)
        
        ao_name = f"audio_{fid}_{int(time.time())}.mp3"
        ao = os.path.join(tempfile.gettempdir(), ao_name)
        
        # Get voice locale
        voice_locale = MYANMAR_VOICES[st.session_state.v_voice]
        
        srt_data, audio_dur = asyncio.run(gen_audio_srt(srt_res, ao, voice_locale, st.session_state.v_speed, st.session_state.v_pitch, target_sec))
        
        st.session_state.step2_audio = ao
        st.session_state.step2_srt = srt_data
        prg.progress(60)
        
        # ========== STEP 3: FINAL SRT ==========
        stt.text("📝 Step 3/4: SRT ဖိုင် အဆင်သင့်လုပ်နေပါသည်...")
        prg.progress(75)
        
        st.session_state.step3_final_srt = srt_data
        prg.progress(85)
        
        # ========== STEP 4: MERGE VIDEO + AUDIO + SRT ==========
        stt.text("🎬 Step 4/4: ဗီဒီယို + အသံ + SRT ပေါင်းစပ်နေပါသည်...")
        prg.progress(90)
        
        # Save video file
        video_path = os.path.join(tempfile.gettempdir(), f"video_{fid}.mp4")
        if not os.path.exists(video_path):
            # Convert to mp4 if needed
            if up_video.name.lower().endswith((".mp4", ".mov", ".avi")):
                subprocess.run(["ffmpeg", "-y", "-i", tp, "-c:v", "libx264", "-c:a", "aac", video_path], capture_output=True)
            else:
                st.warning("⚠️ အော်ဒီယိုဖိုင်သည် ဗီဒီယိုမဟုတ်ပါ။ ဗီဒီယိုဖိုင် အစားထိုးပြီး ထပ်မံစမ်းသပ်ပါ။")
                raise Exception("ဗီဒီယိုဖိုင် လိုအပ်သည်။")
        
        # Save SRT file
        srt_path = os.path.join(tempfile.gettempdir(), f"subs_{fid}.srt")
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(srt_data)
        
        # Merge video and audio
        merged_av = os.path.join(tempfile.gettempdir(), f"merged_{fid}.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path, "-i", ao,
            "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
            merged_av
        ], capture_output=True)
        
        # Add SRT to video
        output_path = os.path.join(tempfile.gettempdir(), f"final_{fid}.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-i", merged_av, "-vf",
            f"subtitles={srt_path}:force_style='FontName=Pyidaungsu,FontSize=20,PrimaryColour=&H00FFFFFF&'",
            "-c:a", "copy", output_path
        ], capture_output=True)
        
        prg.progress(100)
        stt.text("✅ Auto-Flow ပြီးမြောက်ပါပြီ!")
        
        # Display results
        st.success("✅ အဆင့် ၁-၄ အားလုံး ပြီးမြောက်ပါပြီ!")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.subheader("📝 Step 1: ဘာသာပြန်စာသား")
            with st.expander("ကြည့်ရှုပါ", expanded=False):
                st.text_area("Translation", srt_res, height=200, disabled=True)
        
        with col2:
            st.subheader("🔊 Step 2: အသံဖိုင်")
            with open(ao, 'rb') as f:
                st.download_button("⬇️ အသံ ဒາउनલোڈ်", f, file_name=ao_name)
        
        with col3:
            st.subheader("📝 Step 3: SRT ဖိုင်")
            st.download_button("⬇️ SRT ဒាउनલോഡ്", srt_data, file_name=f"output_{fid}.srt")
        
        st.subheader("🎬 Step 4: နောက်ဆုံး ဗီဒီယို")
        with open(output_path, 'rb') as f:
            st.download_button("⬇️ ဗီဒီယို ဒាउनલോഡ်", f, file_name=f"final_{fid}.mp4", key="final_video_download")
        
        # Cleanup
        for p in [ag, ao, video_path, srt_path, merged_av, output_path]:
            if os.path.exists(p): 
                try: os.remove(p)
                except: pass
    
    except Exception as e:
        st.error(f"❌ အမှားအယွင်း: {str(e)}")
        import traceback
        st.error(traceback.format_exc())

st.markdown("---")
st.markdown("🎬 **Movie Recap AI Pro V10.0** - Auto-Flow | သီဟ/နီလာ အသံ | Powered by Gemini AI & Edge TTS")

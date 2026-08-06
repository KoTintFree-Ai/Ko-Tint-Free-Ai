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
import psutil
import gc

# --- CONFIGURATION ---
API_VERSIONS = ["v1beta", "v1"]
DEFAULT_MODELS = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-pro"]

# Myanmar TTS Voices
MYANMAR_VOICES = {
    "သီဟ (Thiha) - ယောက်ျားအသံ": "my-MM",
    "နီလာ (Nila) - အမျိုးသမီးအသံ": "my-MM"
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(
    page_title="Movie Recap AI V14 - Simple & Stable",
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
    if 'step1_translation' not in st.session_state:
        st.session_state.step1_translation = None
    if 'step2_audio_path' not in st.session_state:
        st.session_state.step2_audio_path = None
    if 'step2_srt' not in st.session_state:
        st.session_state.step2_srt = None
    if 'valid_keys_info' not in st.session_state:
        st.session_state.valid_keys_info = {}
    
    for i in range(1, 6):
        if f'key_{i}' not in st.session_state:
            st.session_state[f'key_{i}'] = ""

init_state()

st.title("🎬 Movie Recap AI V14 - Simple & Stable")
st.markdown("ရိုးရှင်းတဲ့ အင်္ဂလိပ် ဗီဒီယို → မြန်မာစာ → အသံ → SRT → ဗီဒီယို")

# --- HELPER FUNCTIONS ---
def get_dur(p):
    """Get duration of audio/video file in seconds"""
    try:
        r = subprocess.run(["ffmpeg", "-i", p], capture_output=True, text=True, timeout=10)
        for line in r.stderr.split('\n'):
            if 'Duration' in line:
                t = line.split('Duration')[1].split(',')[0].strip()
                h, m, s = map(float, t.split(':'))
                return h*3600 + m*60 + s
    except:
        pass
    return 0

def fmt_srt(seconds):
    """Format seconds to SRT timestamp"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')

def wrap_text(text, max_width=50):
    """Wrap text for SRT"""
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        if len(' '.join(current_line + [word])) <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
    if current_line:
        lines.append(' '.join(current_line))
    return '\n'.join(lines)

async def gen_audio_from_text(text, out_p, voice_locale, speed, pitch):
    """Generate audio from text with robust error handling"""
    rate = f"+{int((speed-50)*2)}%" if speed >= 50 else f"{int((speed-50)*2)}%"
    pitch_str = f"+{int((pitch-50)*2)}Hz" if pitch >= 50 else f"{int((pitch-50)*2)}Hz"
    
    # Split text into sentences by Myanmar sentence markers
    sentences = re.split(r'[။\n]+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        sentences = [text.strip()]
    
    temp_files = []
    srt_blocks = []
    cur_t = 0.0
    
    for idx, sentence in enumerate(sentences):
        if not sentence:
            continue
        
        temp_audio = tempfile.mktemp(suffix=".mp3")
        try:
            communicate = edge_tts.Communicate(sentence, voice_locale, rate=rate, pitch=pitch_str)
            await communicate.save(temp_audio)
            
            duration = get_dur(temp_audio)
            if duration > 0:
                srt_blocks.append({
                    'index': len(srt_blocks) + 1,
                    'start': cur_t,
                    'end': cur_t + duration,
                    'text': wrap_text(sentence)
                })
                temp_files.append(temp_audio)
                cur_t += duration
        except Exception as e:
            st.warning(f"⚠️ စာကြောင်း {idx+1} အသံထုတ်မရ: {str(e)}")
            if os.path.exists(temp_audio):
                os.remove(temp_audio)
            continue
    
    if not temp_files:
        raise Exception("အသံဖိုင် ထုတ်လုပ်ခြင်း လုံးဝ မအောင်မြင်ပါ။ စာသားကို ကြည့်ပါ။")
    
    # Concatenate audio files
    concat_list = tempfile.mktemp(suffix=".txt")
    with open(concat_list, "w", encoding='utf-8') as f:
        for p in temp_files:
            f.write(f"file '{os.path.abspath(p)}'\n")
    
    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", 
            "-i", concat_list, "-c", "copy", out_p
        ], capture_output=True, timeout=60)
    except Exception as e:
        raise Exception(f"FFmpeg concatenation error: {str(e)}")
    finally:
        if os.path.exists(concat_list):
            os.remove(concat_list)
        for p in temp_files:
            if os.path.exists(p):
                os.remove(p)
    
    # Generate SRT
    srt_content = ""
    for block in srt_blocks:
        srt_content += f"{block['index']}\n"
        srt_content += f"{fmt_srt(block['start'])} --> {fmt_srt(block['end'])}\n"
        srt_content += f"{block['text']}\n\n"
    
    return srt_content, get_dur(out_p)

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ ဆက်တင်များ")
    
    # RAM Monitor
    st.subheader("🖥️ RAM စောင့်ကြည့်ရန်")
    ram_used = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    ram_limit = 1024
    ram_pct = min(ram_used / ram_limit, 1.0)
    
    col_r1, col_r2 = st.columns([2, 1])
    col_r1.progress(ram_pct)
    col_r2.write(f"{ram_used:.0f}MB")
    
    if st.button("🧹 RAM ရှင်းထုတ်"):
        st.cache_data.clear()
        gc.collect()
        st.success("✅ ရှင်းလင်းပြီး")
    
    st.markdown("---")
    st.subheader("🔑 API Keys")
    
    k1 = st.text_input("API Key 1", type="password", key="key_1")
    show_more = st.toggle("ကျန် Keys", value=False)
    if show_more:
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

    if st.button("🔌 Keys စမ်းသပ်"):
        if not api_keys:
            st.error("API Key ထည့်ပေးပါ")
        else:
            st.session_state.valid_keys_info = {}
            with st.spinner("စစ်ဆေးနေ..."):
                for i, k in enumerate(api_keys):
                    for ver in API_VERSIONS:
                        try:
                            url = f"https://generativelanguage.googleapis.com/{ver}/models?key={k}"
                            r = requests.get(url, timeout=15)
                            if r.status_code == 200:
                                data = r.json()
                                models = [m['name'].split('/')[-1] for m in data.get('models', []) 
                                         if 'generateContent' in m.get('supportedGenerationMethods', [])]
                                st.session_state.valid_keys_info[k] = {"version": ver, "models": models}
                                st.success(f"✅ Key {i+1}")
                                break
                        except:
                            pass
            st.rerun()

    st.markdown("---")
    st.subheader("🎙️ အသံ ဆက်တင်")
    voice_choice = st.selectbox("အသံ", list(MYANMAR_VOICES.keys()), key="voice_widget")
    v_speed = st.slider("အမြန်နှုန်း", 0, 100, 50, key="speed_widget")
    v_pitch = st.slider("အမြင့်မြတ်မှု", 0, 100, 50, key="pitch_widget")
    
    st.markdown("---")
    st.subheader("🎬 ဗီဒီယို ဆက်တင်")
    blur_y = st.slider("Blur Y (%)", 50, 98, 85, key="blur_y_widget")
    blur_h = st.slider("Blur H (%)", 1, 20, 10, key="blur_h_widget")
    font_sz = st.slider("စာလုံးအရွယ်", 12, 40, 22, key="font_widget")

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["📹 Step 1", "🔊 Step 2", "📝 Step 3", "🎬 Step 4"])

# ============ STEP 1 ============
with tab1:
    st.header("Step 1️⃣: ဗီဒီယို → မြန်မာစာ (Plain Text)")
    
    up1 = st.file_uploader("ဗီဒီယို/အော်ဒီယို", type=["mp4", "mov", "avi", "mp3", "wav", "m4a"], key="up1")
    target_sec = st.number_input("အတိုင်းအတာ (စက္ကန့်)", 10, 300, 60, key="target_sec")
    
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
            stt.text("📊 အသံချုံ့နေ...")
            prg.progress(20)
            
            ag = tempfile.mktemp(suffix=".mp3")
            if up1.name.lower().endswith((".mp4", ".mov", ".avi")):
                subprocess.run(["ffmpeg", "-y", "-i", tp, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], 
                             capture_output=True, timeout=60)
            else:
                subprocess.run(["ffmpeg", "-y", "-i", tp, "-ar", "16000", "-ac", "1", "-b:a", "32k", ag], 
                             capture_output=True, timeout=60)
            
            stt.text("⏳ Gemini ဖြင့် ဘာသာပြန်နေ...")
            prg.progress(50)
            
            target_words = int(target_sec * 3.8)
            prm = f"""ဒီ အော်ဒီယိုကို နားထောင်ပြီး မြန်မာစာသားအဖြစ် ဘာသာပြန်ပါ။

လိုအပ်ချက်များ:
1. ရိုးရှင်းတဲ့ မြန်မာစာသားသီးသန့် ပဲ ရေးပါ
2. အချိန်/timestamps တွေ မထည့်ပါ
3. နိဒါန်း၊ နှုတ်ဆက်တာ၊ အပိုစာသားတွေ လုံးဝ မထည့်ပါ
4. ဇာတ်လမ်းကိုပဲ တိုက်ရိုက် ဘာသာပြန်ပါ
5. အဆိုပါ အတိုင်းအတာ {target_sec} စက္ကန့်အတွက် {target_words} စကားလုံးခန့် ရေးပါ
6. စာကြောင်းတွေကို Myanmar sentence marker (။) ဖြင့် ခွဲပါ

ရလာဒ်: မြန်မာစာသားသီးသန့်"""
            
            with open(ag, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode()
            cont = [{"role":"user","parts":[{"text":prm},{"inline_data":{"mime_type":"audio/mpeg","data":b64}}]}]
            
            srt_res = None
            
            for k_idx, k in enumerate(api_keys):
                info = st.session_state.valid_keys_info.get(k, {})
                versions = [info.get('version')] if info.get('version') else API_VERSIONS
                models = info.get('models', DEFAULT_MODELS) if info else DEFAULT_MODELS
                models = sorted(models, key=lambda x: 0 if 'flash' in x.lower() else 1)
                
                for ver in versions:
                    for m in models:
                        try:
                            url = f"https://generativelanguage.googleapis.com/{ver}/models/{m}:generateContent?key={k}"
                            r = requests.post(url, json={"contents":cont}, timeout=180)
                            if r.status_code == 200:
                                data = r.json()
                                if 'candidates' in data and len(data['candidates']) > 0:
                                    if 'content' in data['candidates'][0] and 'parts' in data['candidates'][0]['content']:
                                        if len(data['candidates'][0]['content']['parts']) > 0:
                                            srt_res = data['candidates'][0]['content']['parts'][0].get('text', '')
                                            if srt_res:
                                                st.session_state.step1_translation = srt_res
                                                break
                        except Exception as e:
                            pass
                    if srt_res:
                        break
                if srt_res:
                    break
            
            if not srt_res:
                st.error("❌ ဘာသာပြန်ခြင်း မအောင်မြင်ပါ")
            else:
                prg.progress(100)
                stt.text("✅ Step 1 ပြီး!")
                
                with st.expander("📝 ရလာတဲ့ စာသား", expanded=True):
                    st.text_area("Output", srt_res, height=250, disabled=False, key="step1_output")
                    st.info("💡 Step 2 ကို ကူးထည့်ပါ")
        
        except Exception as e:
            st.error(f"❌ အမှား: {str(e)}")

# ============ STEP 2 ============
with tab2:
    st.header("Step 2️⃣: စာသား → အသံ + SRT")
    
    step2_text = st.text_area("Step 1 စာသားကို ကူးထည့်", height=300, key="step2_text")
    
    if step2_text and st.button("🎙️ Step 2 စတင်"):
        prg = st.progress(0)
        stt = st.empty()
        
        try:
            stt.text("🔊 အသံထုတ်နေ...")
            prg.progress(30)
            
            ao_name = f"audio_{int(time.time())}.mp3"
            ao = os.path.join(tempfile.gettempdir(), ao_name)
            
            voice_locale = MYANMAR_VOICES[voice_choice]
            srt_data, audio_dur = asyncio.run(gen_audio_from_text(step2_text, ao, voice_locale, v_speed, v_pitch))
            
            st.session_state.step2_audio_path = ao
            st.session_state.step2_srt = srt_data
            
            prg.progress(100)
            stt.text("✅ Step 2 ပြီး!")
            
            st.success(f"✅ အသံထုတ်ပြီး ({audio_dur:.2f} စက္ကန့်)")
            
            with st.expander("📝 SRT Output", expanded=True):
                st.text_area("SRT", srt_data, height=250, disabled=False, key="step2_srt_output")
            
            with open(ao, 'rb') as f:
                st.download_button("⬇️ အသံဖိုင်", f, file_name=ao_name)
        
        except Exception as e:
            st.error(f"❌ အမှား: {str(e)}")

# ============ STEP 3 ============
with tab3:
    st.header("Step 3️⃣: SRT စစ်ဆေး")
    
    step3_srt = st.text_area("SRT ကြည့်ရှု/ပြင်ဆင်", height=300, key="step3_srt")
    
    if step3_srt and st.button("✅ Step 3 အတည်"):
        st.session_state.step3_final_srt = step3_srt
        st.success("✅ သိမ်းဆည်းပြီး!")
        
        with st.expander("📝 Final SRT", expanded=True):
            st.text_area("Final", step3_srt, height=250, disabled=False, key="step3_final")
        
        st.download_button("⬇️ SRT ဖိုင်", step3_srt, file_name="output.srt")

# ============ STEP 4 ============
with tab4:
    st.header("Step 4️⃣: ဗီဒီယို ပေါင်းစပ်")
    
    col1, col2 = st.columns(2)
    with col1:
        up4_video = st.file_uploader("ဗီဒီယို", type=["mp4", "mov", "avi"], key="up4_video")
    with col2:
        up4_audio = st.file_uploader("အသံ", type=["mp3", "wav", "m4a"], key="up4_audio")
    
    step4_srt = st.text_area("SRT", height=200, key="step4_srt")
    
    use_blur = st.checkbox("Auto-Blur", value=True, key="use_blur")
    use_sub = st.checkbox("Subtitle", value=True, key="use_sub")
    
    if up4_video and up4_audio and step4_srt and st.button("🎬 Step 4 စတင်"):
        prg = st.progress(0)
        stt = st.empty()
        
        try:
            stt.text("📹 ပေါင်းစပ်နေ...")
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
            
            prg.progress(40)
            
            merged_av = os.path.join(tempfile.gettempdir(), f"merged_{int(time.time())}.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
                "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
                merged_av
            ], capture_output=True, timeout=120)
            
            prg.progress(70)
            
            if use_blur and use_sub:
                by_px = int(1080 * (blur_y / 100))
                bh_px = int(1080 * (blur_h / 100))
                
                filter_str = f"[0:v]boxblur=luma_radius=10:chroma_radius=4[blurred];[0:v][blurred]overlay=0:{by_px}:h={bh_px}[v];[v]subtitles={srt_path}:force_style='FontSize={font_sz},PrimaryColour=&H00FFFFFF&'[out]"
                
                output_path = os.path.join(tempfile.gettempdir(), f"final_{int(time.time())}.mp4")
                subprocess.run([
                    "ffmpeg", "-y", "-i", merged_av, "-vf", filter_str,
                    "-c:a", "copy", output_path
                ], capture_output=True, timeout=180)
            elif use_sub:
                output_path = os.path.join(tempfile.gettempdir(), f"final_{int(time.time())}.mp4")
                subprocess.run([
                    "ffmpeg", "-y", "-i", merged_av, "-vf",
                    f"subtitles={srt_path}:force_style='FontSize={font_sz},PrimaryColour=&H00FFFFFF&'",
                    "-c:a", "copy", output_path
                ], capture_output=True, timeout=180)
            else:
                output_path = merged_av
            
            prg.progress(100)
            stt.text("✅ Step 4 ပြီး!")
            
            st.success("✅ ပေါင်းစပ်ပြီး!")
            
            with open(output_path, 'rb') as f:
                st.download_button("⬇️ နောက်ဆုံး ဗီဒီယို", f, file_name="final_output.mp4")
            
            for p in [video_path, audio_path, srt_path, merged_av, output_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except:
                        pass
        
        except Exception as e:
            st.error(f"❌ အမှား: {str(e)}")

st.markdown("---")
st.markdown("🎬 **Movie Recap AI V14** - Simple & Stable | သီဟ/နီလာ | Powered by Gemini")

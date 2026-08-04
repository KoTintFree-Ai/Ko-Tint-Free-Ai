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
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MODELS_TO_TRY = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.0-flash-exp"]

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
    keys = ['myanmar_text', 'audio_data', 'srt_data', 'video_data', 'base_frame', 'last_uploaded', 'processing_done']
    for k in keys:
        if k not in st.session_state: st.session_state[k] = None
    if st.session_state.processing_done is None: st.session_state.processing_done = False
    if 'blur_y_pos' not in st.session_state: st.session_state.blur_y_pos = 85.0
    if 'blur_h_size' not in st.session_state: st.session_state.blur_h_size = 10.0
    if 'sub_y_pos' not in st.session_state: st.session_state.sub_y_pos = 85.0
    if 'font_size' not in st.session_state: st.session_state.font_size = 22

init_state()

st.title("🎬 Movie Recap AI Pro V6.2")
st.markdown("English Video → Myanmar Movie Recap (Professional Sync)")

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

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Settings")
    st.subheader("🔑 Gemini API Keys")
    k1 = st.text_input("API Key 1", type="password", key="key_1")
    k2 = st.text_input("API Key 2", type="password", key="key_2")
    k3 = st.text_input("API Key 3", type="password", key="key_3")
    k4 = st.text_input("API Key 4", type="password", key="key_4")
    k5 = st.text_input("API Key 5", type="password", key="key_5")
    api_keys = [k for k in [k1, k2, k3, k4, k5] if k]
    
    st.markdown("---")
    st.subheader("🎬 Video Layout")
    mirror_v = st.checkbox("Mirror Video", value=True)
    scale_v = st.checkbox("Scale Video (106%)", value=True)
    
    st.markdown("---")
    blur_s = st.checkbox("Blur Original Subtitles", value=True)
    if blur_s:
        b_y = plus_minus_control("Blur Y Position (%)", "blur_y_pos", 0.0, 100.0, 0.5)
        b_h = plus_minus_control("Blur Height (%)", "blur_h_size", 0.5, 30.0, 0.1)
    
    st.markdown("---")
    burn_s = st.checkbox("Burn Myanmar Subtitles", value=True)
    if burn_s:
        f_s = plus_minus_control("Myanmar Font Size", "font_size", 5, 100, 1)
        s_y = plus_minus_control("Subtitle Y Position (%)", "sub_y_pos", 0.0, 100.0, 0.5)
    
    st.markdown("---")
    if st.button("✨ Auto Detect Area"):
        st.session_state.do_detect = True
    show_prev = st.checkbox("👀 Live Preview", value=True)
    
    st.markdown("---")
    st.subheader("⏱️ Duration Control")
    fit_dur = st.toggle("Fit to Target Duration", value=True)
    target_sec = 0
    if fit_dur:
        c1, c2 = st.columns(2)
        with c1: tm = st.number_input("Min", 0, 60, 2)
        with c2: ts = st.number_input("Sec", 0, 59, 30)
        target_sec = (tm * 60) + ts
    
    st.markdown("---")
    st.subheader("🔊 Voice Settings")
    v_choice = st.selectbox("Select Voice", ["Thiha (Male)", "Nilar (Female)"])
    v_id = "my-MM-ThihaNeural" if "Thiha" in v_choice else "my-MM-NilarNeural"
    v_speed = st.slider("Base Speed", 1, 100, 55)
    v_pitch = st.slider("Pitch", 1, 100, 50)
    
    if st.button("🧹 Clear All Data"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

# --- CORE UTILITIES ---
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
    blocks = re.split(r'\n\s*\n', text.strip())
    segments = []
    for b in blocks:
        lines = b.strip().split('\n')
        if len(lines) >= 3:
            for i, l in enumerate(lines):
                if '-->' in l:
                    segments.append(" ".join(lines[i+1:]))
                    break
        elif len(lines) > 0:
            clean = re.sub(r'^\d+|^[\d:,.\s-->]+', '', b).strip()
            if clean: segments.append(clean)
    return [s for s in segments if s.strip()]

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
        p = tempfile.mktemp(suffix=".mp3")
        try:
            communicate = edge_tts.Communicate(clean_txt, vid, rate=rate, pitch=pitch)
            await communicate.save(p)
            d = get_dur(p)
            if d > 0:
                srt_blocks.append(f"{len(temp_files)+1}\n{fmt_srt(cur_t)} --> {fmt_srt(cur_t+d)}\n{clean_txt}\n\n")
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
        fc += f",subtitles='{se}':fontsdir='{os.getcwd()}':force_style='Fontname=Pyidaungsu,FontSize={fs},PrimaryColour=&H0000FFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0,Alignment=2,MarginV={mv}'"
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
            f.write("1\n00:00:00,000 --> 00:00:10,000\nမြန်မာစာ စမ်းသပ်ကြည့်ရှုခြင်း (Font Test)")
        po = tempfile.mktemp(suffix=".jpg")
        fc = get_filter(mirror_v, scale_v, blur_s, st.session_state.blur_y_pos, st.session_state.blur_h_size, burn_s, ps, st.session_state.font_size, st.session_state.sub_y_pos)
        fcs = fc.replace("[0:v]", "").replace("[v]", "").strip(",")
        subprocess.run(["ffmpeg", "-y", "-i", bp, "-vf", fcs if fcs else "null", po], capture_output=True)
        if os.path.exists(po): st.image(po); os.remove(po)
        if os.path.exists(bp): os.remove(bp)
        if os.path.exists(ps): os.remove(ps)

    if not api_keys: st.warning("⚠️ Sidebar တွင် Gemini API Key ထည့်ပေးပါ")
    elif st.button("🚀 Start Process"):
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
            prm = f"Listen to this audio and translate it into a Myanmar Movie Recap style. Target duration: {target_sec}s. Output ONLY valid SRT format. Use Myanmar language."
            with open(ag, 'rb') as f: b64 = base64.b64encode(f.read()).decode()
            cont = [{"role":"user","parts":[{"text":prm},{"inline_data":{"mime_type":"audio/mpeg","data":b64}}]}]
            srt_res = None
            errors = []
            for k in api_keys:
                for m in MODELS_TO_TRY:
                    try:
                        r = requests.post(f"{GEMINI_BASE_URL}/{m}:generateContent?key={k}", json={"contents":cont}, timeout=300)
                        if r.status_code == 200:
                            data = r.json()
                            if 'candidates' in data and data['candidates'][0]['content']['parts']:
                                srt_res = data['candidates'][0]['content']['parts'][0]['text']
                                if srt_res: break
                            else: errors.append(f"Model {m}: အကြောင်းအရာ လုံခြုံရေးကြောင့် ပိတ်ပင်ခံရခြင်း သို့မဟုတ် အဖြေမထွက်ခြင်း။")
                        elif r.status_code == 429:
                            errors.append(f"Model {m}: API Key Quota ပြည့်သွားပါပြီ။")
                        elif r.status_code == 403:
                            errors.append(f"Model {m}: API Key မမှန်ကန်ပါ။")
                        else:
                            errors.append(f"Model {m}: Error Code {r.status_code} ဖြစ်ပေါ်နေပါသည်။")
                    except Exception as e: errors.append(f"Model {m}: {str(e)}")
                if srt_res: break
            
            if not srt_res:
                st.error("❌ Gemini ဘာသာပြန်ခြင်း မအောင်မြင်ပါ")
                for e in errors: st.info(e)
                raise Exception("မည်သည့် Model မှ ဘာသာပြန်ခြင်း မလုပ်ဆောင်နိုင်ပါ။")
            
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

            prg.progress(100); stt.text("✅ အောင်မြင်စွာ ပြီးဆုံးပါပြီ!"); st.session_state.processing_done = True; st.balloons()
            if os.path.exists(tp): os.remove(tp)
            if os.path.exists(ao): os.remove(ao)
            if os.path.exists(ag): os.remove(ag)
        except Exception as e: st.error(f"❌ အမှားအယွင်း: {str(e)}")

if st.session_state.processing_done:
    st.markdown("---")
    if st.session_state.video_data:
        st.subheader("🎥 Final Video")
        st.video(st.session_state.video_data)
        st.download_button("📥 Download Video", st.session_state.video_data, "recap_final.mp4", "video/mp4")
    c1, c2 = st.columns(2)
    with c1:
        if st.session_state.audio_data:
            st.audio(st.session_state.audio_data)
            st.download_button("📥 Download Audio", st.session_state.audio_data, "recap_audio.mp3", "audio/mp3")
    with c2:
        if st.session_state.srt_data:
            st.download_button("📥 Download SRT", st.session_state.srt_data, "recap.srt", "text/plain")

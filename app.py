import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path

import httpx
import streamlit as st

try:
    import psutil
except Exception:
    psutil = None

import engine

APP_ROOT = Path(__file__).resolve().parent
WORK_ROOT = APP_ROOT / "streamlit_jobs"
WORK_ROOT.mkdir(exist_ok=True)
TEMP_ROOT = APP_ROOT / "temp"
TEMP_ROOT.mkdir(exist_ok=True)
USER_ID = 987654321

st.set_page_config(
    page_title="Ko Tint Free AI",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

TEXT = {
    "မြန်မာ": {
        "settings": "⚙️ ဆက်တင်များ",
        "language": "ဘာသာစကား",
        "theme": "အလင်း/အမှောင်",
        "dark": "အမှောင်",
        "light": "အလင်း",
        "keys": "Gemini API key များ (ကော်မာခံပြီး)",
        "groq": "Groq API key",
        "platform": "Video အရွယ်အစား",
        "resolution": "Resolution",
        "voice": "🎙️ အသံ",
        "speed": "⚡ အသံအမြန်နှုန်း",
        "subtitle": "📝 မြန်မာစာတန်းထိုး",
        "subtitle_pos": "📝 စာတန်းနေရာ",
        "subtitle_size": "📝 စာလုံးအရွယ်အစား",
        "subtitle_color": "🎨 စာတန်းအရောင်",
        "blur": "🌫️ Blur Mask",
        "blur_pos": "🌫️ Blur နေရာ",
        "blur_strength": "🌫️ Blur အား",
        "blur_height": "🌫️ Blur အမြင့်",
        "blur_width": "🌫️ Blur အကျယ်",
        "title": "🏷️ Video Title Overlay",
        "title_size": "🏷️ Title အမြင့် / စာလုံးအရွယ်",
        "title_width": "🏷️ Title အကျယ်",
        "bypass": "🛡️ Edit Bypass",
        "font": "🔤 မြန်မာ Font",
        "watermark": "💧 Watermark",
        "wm_text": "Watermark စာသား",
        "wm_pos": "Watermark နေရာ",
        "logo": "🖼️ ကိုယ်ပိုင် Logo",
        "bg_music": "🎵 Background Music ဖွင့်မည်",
        "bg_music_file": "Background Music ဖိုင်ထည့်ပါ",
        "bg_music_volume": "Background Music အသံအတိုးအကျယ်",
        "upload": "Video Upload လုပ်ပါ",
        "youtube": "သို့မဟုတ် YouTube URL ထည့်ပါ",
        "generate": "🚀 Recap ထုတ်မည်",
        "download": "⬇️ MP4 Download",
        "ready": "✅ Recap အောင်မြင်ပါပြီ",
        "monitor": "📊 System Monitor",
        "ram": "RAM အသုံးပြုမှု",
        "cpu": "CPU အသုံးပြုမှု",
        "network": "Internet speed",
        "refresh": "Monitor ပြန်စစ်မည်",
        "validate": "API key စစ်မည်",
        "validation_ready": "API key အလုပ်လုပ်ပါသည်",
        "validation_failed": "API key စစ်မရပါ",
        "minus": "လျှော့",
        "plus": "တိုး",
        "workflow": "လုပ်ငန်းစဉ်",
        "workflow_text": "1. Video Upload/URL ထည့်ပါ\n2. Voice နှင့် Subtitle ရွေးပါ\n3. Blur/Watermark/Logo ချိန်ပါ\n4. Recap ထုတ်ပြီး MP4 Download လုပ်ပါ",
        "missing_video": "Video သို့မဟုတ် YouTube URL ထည့်ပါ။",
        "missing_keys": "Gemini key နှင့် Groq key ထည့်ပါ။",
        "privacy": "API keys များကို GitHub ထဲ မသိမ်းပါ။ Job လုပ်ချိန်မှာသာ အသုံးပြုပါ။",
        "advanced": "အသေးစိတ် Video Controls",
        "calibration": "Preview Calibration",
        "calibration_help": "စာတန်းနှင့် blur နေရာကို slider ဖြင့် ကြိုတင်ချိန်ပါ။",
    },
    "English": {
        "settings": "⚙️ Settings",
        "language": "Language",
        "theme": "Appearance",
        "dark": "Dark",
        "light": "Light",
        "keys": "Gemini API keys (comma-separated)",
        "groq": "Groq API key",
        "platform": "Video aspect ratio",
        "resolution": "Resolution",
        "voice": "🎙️ Voice",
        "speed": "⚡ Voice speed",
        "subtitle": "📝 Burmese subtitles",
        "subtitle_pos": "📝 Subtitle position",
        "subtitle_size": "📝 Subtitle size",
        "subtitle_color": "🎨 Subtitle color",
        "blur": "🌫️ Blur mask",
        "blur_pos": "🌫️ Blur position",
        "blur_strength": "🌫️ Blur intensity",
        "blur_height": "🌫️ Blur height",
        "blur_width": "🌫️ Blur width",
        "title": "🏷️ Title overlay",
        "title_size": "🏷️ Title height / font size",
        "title_width": "🏷️ Title width",
        "bypass": "🛡️ Edit bypass",
        "font": "🔤 Myanmar font",
        "watermark": "💧 Watermark",
        "wm_text": "Watermark text",
        "wm_pos": "Watermark position",
        "logo": "🖼️ Custom logo",
        "bg_music": "🎵 Enable background music",
        "bg_music_file": "Upload background music",
        "bg_music_volume": "Background music volume",
        "upload": "Upload a video",
        "youtube": "Or paste a YouTube URL",
        "generate": "🚀 Generate recap",
        "download": "⬇️ Download MP4",
        "ready": "✅ Recap is ready",
        "monitor": "📊 System monitor",
        "ram": "RAM usage",
        "cpu": "CPU usage",
        "network": "Internet speed",
        "refresh": "Refresh monitor",
        "validate": "Validate API keys",
        "validation_ready": "API key is working",
        "validation_failed": "API key validation failed",
        "minus": "Decrease",
        "plus": "Increase",
        "workflow": "Workflow",
        "workflow_text": "1. Upload a video or URL\n2. Choose voice and subtitles\n3. Tune blur, watermark, and logo\n4. Generate and download MP4",
        "missing_video": "Upload a video or paste a YouTube URL.",
        "missing_keys": "Enter Gemini key(s) and a Groq key.",
        "privacy": "Keys are not written to GitHub. They are used only during processing.",
        "advanced": "Advanced video controls",
        "calibration": "Preview calibration",
        "calibration_help": "Use the sliders to position subtitles and blur before rendering.",
    },
}

if "ui_lang" not in st.session_state:
    st.session_state.ui_lang = "မြန်မာ"
if "theme" not in st.session_state:
    st.session_state.theme = "dark"
T = TEXT[st.session_state.ui_lang]

bg = "#0f172a" if st.session_state.theme == "dark" else "#f8fafc"
fg = "#f8fafc" if st.session_state.theme == "dark" else "#0f172a"
card = "rgba(30,41,59,.65)" if st.session_state.theme == "dark" else "#ffffff"
st.markdown(
    f"""
    <style>
    .stApp {{ background: {bg}; color: {fg}; }}
    .block-container {{ max-width: 1180px; padding-top: 1.5rem; }}
    .hero {{ padding: 1.4rem 1.6rem; border-radius: 20px; background: linear-gradient(135deg,#172554,#312e81); color: white; margin-bottom: 1.2rem; }}
    .hero h1 {{ margin: 0; font-size: 2.2rem; }}
    .hero p {{ margin: .45rem 0 0; color: #dbeafe; }}
    [data-testid="stFileUploader"] {{ background: {card}; border-radius: 14px; padding: .4rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)

def _nudge_state(key, delta, lower, upper):
    current = int(st.session_state.get(key, lower))
    st.session_state[key] = max(lower, min(upper, current + delta))


def _nudge_slider(label, key, lower, upper, default, step=1):
    # The slider deliberately has no explicit session-state key. Its persistent
    # value lives in key, so the buttons can safely update key and rerun.
    if key not in st.session_state:
        st.session_state[key] = default
    st.write(label)
    left, middle, right = st.columns([0.18, 0.64, 0.18])
    with left:
        if st.button("−", key=f"{key}_minus", help=T["minus"], use_container_width=True):
            _nudge_state(key, -step, lower, upper)
            st.rerun()
    with middle:
        value = st.slider(
            label, lower, upper, value=int(st.session_state[key]), step=step,
            label_visibility="collapsed"
        )
    with right:
        if st.button("+", key=f"{key}_plus", help=T["plus"], use_container_width=True):
            _nudge_state(key, step, lower, upper)
            st.rerun()
    st.session_state[key] = value
    return value


def _named_color(value):
    return {
        "yellow": "Yellow / အဝါ",
        "white": "White / အဖြူ",
        "#00E5FF": "Cyan / စိမ်းပြာ",
        "#39FF14": "Lime / စိမ်းစို",
        "#FF6EC7": "Pink / ပန်းရောင်",
    }.get(value, value)


@st.cache_data(ttl=30, show_spinner=False)
def _measure_network_speed():
    started = time.perf_counter()
    try:
        response = httpx.get("https://speed.cloudflare.com/__down?bytes=500000", timeout=8.0)
        elapsed = max(time.perf_counter() - started, 0.001)
        mbps = (len(response.content) * 8 / elapsed) / 1_000_000
        return f"{mbps:.1f} Mbps"
    except Exception:
        return "Unavailable"


def _validate_api_keys(gemini_text, groq_text):
    gemini_keys = [key.strip() for key in gemini_text.split(",") if key.strip()]
    groq = groq_text.strip()
    results = []
    for key in gemini_keys[:5]:
        try:
            r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key}, timeout=8.0)
            results.append(r.status_code == 200)
        except Exception:
            results.append(False)
    gemini_ok = bool(results) and any(results)
    try:
        groq_ok = bool(groq) and httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {groq}"},
            timeout=8.0,
        ).status_code == 200
    except Exception:
        groq_ok = False
    return gemini_ok, groq_ok


with st.sidebar:
    st.header(T["settings"])
    st.session_state.ui_lang = st.selectbox(T["language"], ["မြန်မာ", "English"], index=["မြန်မာ", "English"].index(st.session_state.ui_lang))
    T = TEXT[st.session_state.ui_lang]
    st.session_state.theme = st.radio(T["theme"], ["dark", "light"], format_func=lambda x: T["dark"] if x == "dark" else T["light"], horizontal=True, index=0 if st.session_state.theme == "dark" else 1)
    st.caption(T["privacy"])
    gemini_keys_text = st.text_input(T["keys"], value="", type="password", help="Separate multiple keys with commas.")
    groq_key = st.text_input(T["groq"], value="", type="password")

    platform_label = st.selectbox(T["platform"], ["YouTube / 16:9", "TikTok / 9:16", "Facebook / 9:16"])
    resolution_label = st.selectbox(T["resolution"], ["720p", "1080p"])
    voice_keys = list(engine.VOICE_MODES)
    def _voice_number_label(key):
        number = voice_keys.index(key) + 1
        raw_name = str(engine.VOICE_MODES[key].get("name", ""))
        # Keep only the parenthesized style text, e.g. 15 (Standard).
        suffix = raw_name[raw_name.find("("):].strip() if "(" in raw_name else ""
        return f"{number} {suffix}".strip()
    voice_key = st.selectbox(T["voice"], voice_keys, format_func=_voice_number_label, index=1 if len(voice_keys) > 1 else 0)
    speed_label = st.selectbox(T["speed"], list(engine.SPEED_MULTIPLIERS), index=0)

    with st.expander(T["advanced"], expanded=True):
        subtitle_enabled = st.toggle(T["subtitle"], value=True)
        sub_y_percent = _nudge_slider(T["subtitle_pos"], "sub_y_percent", 45, 88, 82)
        sub_font_size = _nudge_slider(T["subtitle_size"], "sub_font_size", 24, 60, 35)
        color_values = ["yellow", "white", "#00E5FF", "#39FF14", "#FF6EC7"]
        sub_color = st.selectbox(T["subtitle_color"], color_values, format_func=_named_color)
        blur_enabled = st.toggle(T["blur"], value=False)
        blur_y_percent = _nudge_slider(T["blur_pos"], "blur_y_percent", 45, 88, 82)
        blur_strength = _nudge_slider(T["blur_strength"], "blur_strength", 1, 20, 5)
        blur_height = _nudge_slider(T["blur_height"], "blur_height", 6, 24, 12)
        blur_width = _nudge_slider(T["blur_width"], "blur_width", 50, 100, 100)
        title_enabled = st.toggle(T["title"], value=True)
        title_size = _nudge_slider(T["title_size"], "title_size", 24, 64, 30)
        title_width = _nudge_slider(T["title_width"], "title_width", 45, 100, 65)
        bypass_enabled = st.toggle(T["bypass"], value=False)
        font_files = getattr(engine, "AVAILABLE_FONTS", [])
        font_labels = [str(idx + 1) for idx, _ in enumerate(font_files)]
        font_choice = st.selectbox(T["font"], font_labels or ["Default"])
        wm_text = st.text_input(T["wm_text"], value="Recap", max_chars=80)
        wm_pos_labels = {"bounce": "🔁 Bounce", "topleft": "↖️ Top left", "topright": "↗️ Top right", "bottom": "⬇️ Bottom center"}
        wm_pos = st.selectbox(T["wm_pos"], list(wm_pos_labels), format_func=lambda x: wm_pos_labels[x])
        logo_file = st.file_uploader(T["logo"], type=["png", "jpg", "jpeg"], key="logo_upload")
        bg_music_enabled = st.toggle(T["bg_music"], value=False, key="bg_music_enabled")
        bg_music_file = st.file_uploader(
            T["bg_music_file"], type=["mp3", "wav", "m4a", "aac", "ogg"], key="bg_music_upload"
        ) if bg_music_enabled else None
        bg_music_volume = st.slider(
            T["bg_music_volume"], min_value=0.0, max_value=1.0, value=0.15, step=0.05,
            key="bg_music_volume"
        ) if bg_music_enabled else 0.0
        st.caption(T["calibration_help"])

    if st.button(T["validate"], use_container_width=True):
        with st.spinner("Checking..." if st.session_state.ui_lang == "English" else "စစ်ဆေးနေပါသည်..."):
            gemini_ok, groq_ok = _validate_api_keys(gemini_keys_text, groq_key)
        if gemini_ok and groq_ok:
            st.success(T["validation_ready"])
        else:
            st.error(f"{T['validation_failed']}: Gemini={'OK' if gemini_ok else 'FAIL'}, Groq={'OK' if groq_ok else 'FAIL'}")

if "result_path" not in st.session_state:
    st.session_state.result_path = None
if "last_job" not in st.session_state:
    st.session_state.last_job = None

st.markdown('<div class="hero"><h1>🎬 Ko Tint Free AI</h1><p>AI Movie Recap · Burmese voiceover · Subtitle · Video export</p></div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([1.35, 1, 1])
with col1:
    uploaded = st.file_uploader(T["upload"], type=["mp4", "mov", "mkv", "webm", "avi"])
    youtube_url = st.text_input(T["youtube"])
    if uploaded is not None:
        upload_sig = (uploaded.name, int(getattr(uploaded, "size", 0)))
        if st.session_state.get("uploaded_sig") != upload_sig:
            st.session_state.uploaded_name = uploaded.name
            st.session_state.uploaded_bytes = uploaded.getvalue()
            st.session_state.uploaded_sig = upload_sig
            st.session_state.preview_frame_sig = None
    persisted_upload = bool(st.session_state.get("uploaded_bytes"))
    persisted_upload_name = st.session_state.get("uploaded_name", "source.mp4")
with col2:
    st.subheader(T["workflow"])
    st.markdown(T["workflow_text"])
with col3:
    st.subheader(T["monitor"])
    if psutil:
        ram = psutil.virtual_memory().percent
        cpu = psutil.cpu_percent(interval=0.15)
        st.metric(T["ram"], f"{ram:.0f}%")
        st.progress(int(ram) / 100)
        st.metric(T["cpu"], f"{cpu:.0f}%")
        st.progress(int(cpu) / 100)
        st.metric(T["network"], _measure_network_speed())
    else:
        st.caption("psutil is not installed")
    if st.button(T["refresh"], use_container_width=True):
        st.rerun()

def _platform_code(label: str) -> str:
    if label.startswith("TikTok"):
        return "tt"
    if label.startswith("Facebook"):
        return "fb"
    return "yt"


def _resolution_code(label: str) -> str:
    return "1080" if label.startswith("1080") else "720"


# Calibration preview: show the selected blur and subtitle positions before rendering.
if persisted_upload:
    preview_col, guide_col = st.columns([1.35, 1])
    with preview_col:
        st.subheader(f"🖼️ {T['calibration']}")
        preview_ext = Path(persisted_upload_name).suffix or ".mp4"
        preview_input = WORK_ROOT / f"calibration_source{preview_ext}"
        preview_frame = WORK_ROOT / "calibration_frame.png"
        preview_overlay = WORK_ROOT / "calibration_overlay.png"
        try:
            if not preview_input.exists() or st.session_state.get("preview_source_sig") != st.session_state.get("uploaded_sig"):
                preview_input.write_bytes(st.session_state.uploaded_bytes)
                st.session_state.preview_source_sig = st.session_state.get("uploaded_sig")
            dim_w, dim_h = engine.get_video_dimensions(_platform_code(platform_label), _resolution_code(resolution_label))
            frame_sig = (st.session_state.get("uploaded_sig"), dim_w, dim_h)
            if not preview_frame.exists() or st.session_state.get("preview_frame_sig") != frame_sig:
                engine.extract_preview_frame(str(preview_input), str(preview_frame), dim_w, dim_h, percent=0.3)
                st.session_state.preview_frame_sig = frame_sig
            try:
                engine.render_calibration_preview(
                    str(preview_frame), str(preview_overlay), blur_y_percent,
                    sub_y_percent, blur_enabled, sub_font_size,
                    title_text=("Preview Title" if title_enabled else ""),
                    title_size=title_size, title_width=title_width,
                    blur_height=blur_height, blur_width=blur_width,
                )
            except TypeError as preview_api_error:
                # Keep preview usable if Streamlit Cloud temporarily has an older engine.py.
                if "unexpected keyword argument" not in str(preview_api_error):
                    raise
                engine.render_calibration_preview(
                    str(preview_frame), str(preview_overlay), blur_y_percent,
                    sub_y_percent, blur_enabled, sub_font_size,
                )
            if preview_overlay.exists():
                st.image(str(preview_overlay), use_container_width=True)
                st.caption("⚪ Blur guide   🔤 Subtitle Preview text")
        except Exception as preview_error:
            st.warning(f"Preview unavailable: {preview_error}")
    with guide_col:
        st.info(T["calibration_help"])
        st.write(f"Subtitle: **{sub_y_percent}%** · **{sub_font_size}px**")
        st.write(f"Blur: **{'On' if blur_enabled else 'Off'}** · Y **{blur_y_percent}%** · height **{blur_height}%** · width **{blur_width}%** · strength **{blur_strength}**")
elif youtube_url.strip():
    st.info("📥 Download the YouTube source first to see its calibration preview." if st.session_state.ui_lang == "မြန်မာ" else "📥 The YouTube source must be downloaded before a calibration preview can be shown.")

start = st.button(T["generate"], type="primary", use_container_width=True)


async def _run_pipeline(input_video: str, audio_path: str, output_path: str, status_box, progress_bar, background_music_path=None, background_music_volume=0.0):
    async def progress(message: str):
        status_box.info(message)
        import re
        match = re.search(r"အဆင့်\s+(\d+)/7", message)
        if match:
            progress_bar.progress(min(int(match.group(1)) / 7, 0.99))

    engine.user_platform[USER_ID] = _platform_code(platform_label)
    engine.user_res[USER_ID] = _resolution_code(resolution_label)
    engine.user_sub_mode[USER_ID] = subtitle_enabled
    engine.user_blur_mode[USER_ID] = blur_enabled
    engine.user_blur_y[USER_ID] = blur_y_percent
    engine.user_blur_strength[USER_ID] = blur_strength
    engine.user_blur_height[USER_ID] = blur_height
    engine.user_blur_width[USER_ID] = blur_width
    engine.user_sub_y[USER_ID] = sub_y_percent
    engine.user_sub_size[USER_ID] = sub_font_size
    engine.user_title_mode[USER_ID] = title_enabled
    engine.user_title_size[USER_ID] = title_size
    engine.user_title_width[USER_ID] = title_width
    engine.user_bypass_mode[USER_ID] = bypass_enabled
    engine.user_sub_color[USER_ID] = sub_color
    engine.user_wm_text[USER_ID] = wm_text or "Recap"
    engine.user_wm_pos[USER_ID] = wm_pos
    if font_files and font_choice != "Default":
        selected_index = int(font_choice) - 1
        engine.user_font[USER_ID] = font_files[max(0, min(selected_index, len(font_files) - 1))]
    return await engine.advanced_sync_pipeline(
        audio_path=audio_path,
        gemini_keys_str=gemini_keys_text,
        groq_key=groq_key,
        input_video=input_video,
        output_video_path=output_path,
        voice_config=engine.VOICE_MODES[voice_key],
        user_speed_val=engine.SPEED_MULTIPLIERS[speed_label],
        user_id=USER_ID,
        progress_cb=progress,
        background_music_path=background_music_path,
        background_music_volume=background_music_volume,
    )


if start:
    if not persisted_upload and not youtube_url.strip():
        st.error(T["missing_video"])
        st.stop()
    if not gemini_keys_text.strip() or not groq_key.strip():
        st.error(T["missing_keys"])
        st.stop()

    job_dir = Path(tempfile.mkdtemp(prefix="recap_", dir=WORK_ROOT))
    input_path = job_dir / (persisted_upload_name if persisted_upload else "source.mp4")
    audio_path = job_dir / "source_audio.mp3"
    background_music_path = job_dir / "background_music"
    output_path = job_dir / "recap_output.mp4"
    status_box = st.empty()
    progress_bar = st.progress(0)
    try:
        if logo_file:
            (TEMP_ROOT / f"logo_{USER_ID}.png").write_bytes(logo_file.getbuffer())
        if persisted_upload:
            input_path.write_bytes(st.session_state.uploaded_bytes)
        else:
            status_box.info("⬇️ Downloading source video...")
            engine.download_youtube_video(youtube_url.strip(), str(input_path))
        status_box.info("🎧 Extracting source audio...")
        engine.extract_audio_ffmpeg(str(input_path), str(audio_path))
        bg_path_arg = None
        if bg_music_enabled and bg_music_file is not None:
            bg_suffix = Path(bg_music_file.name).suffix or ".mp3"
            background_music_path = background_music_path.with_suffix(bg_suffix)
            background_music_path.write_bytes(bg_music_file.getvalue())
            bg_path_arg = str(background_music_path)
        pipeline_result = asyncio.run(_run_pipeline(
            str(input_path), str(audio_path), str(output_path), status_box, progress_bar,
            background_music_path=bg_path_arg, background_music_volume=bg_music_volume
        ))
        if isinstance(pipeline_result, (tuple, list)) and len(pipeline_result) >= 3:
            st.session_state.generated_caption = pipeline_result[1] or ""
            st.session_state.generated_hashtags = pipeline_result[2] or ""
        else:
            st.session_state.generated_caption = ""
            st.session_state.generated_hashtags = ""
        progress_bar.progress(100)
        status_box.success(T["ready"])
        st.session_state.result_path = str(output_path)
        st.session_state.last_job = str(input_path.name)
    except Exception as exc:
        status_box.error(f"❌ {exc}")
        st.exception(exc)

if st.session_state.result_path and os.path.exists(st.session_state.result_path):
    st.divider()
    st.subheader(T["ready"])
    st.video(st.session_state.result_path)
    generated_caption = st.session_state.get("generated_caption", "")
    generated_hashtags = st.session_state.get("generated_hashtags", "")
    if generated_caption or generated_hashtags:
        st.subheader("📣 Caption & Hashtags" if st.session_state.ui_lang == "English" else "📣 Caption နှင့် Hashtags")
        telegram_caption = "\n\n".join(part for part in (generated_caption, generated_hashtags) if part)
        if telegram_caption:
            st.code(telegram_caption, language=None)
    with open(st.session_state.result_path, "rb") as f:
        st.download_button(T["download"], data=f, file_name="ko_tint_free_ai_recap.mp4", mime="video/mp4", type="primary")

st.caption("Ko Tint Free AI · Keep API keys private and do not commit them to GitHub.")

if __name__ == "__main__":
    pass

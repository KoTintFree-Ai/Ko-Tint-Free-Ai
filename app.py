from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import streamlit as st

import engine


APP_ROOT = Path(__file__).resolve().parent
WORK_ROOT = APP_ROOT / "streamlit_jobs"
WORK_ROOT.mkdir(exist_ok=True)
USER_ID = 987654321

st.set_page_config(
    page_title="Ko Tint Free AI",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main { background: #0f172a; }
    .block-container { max-width: 1180px; padding-top: 2rem; }
    .hero { padding: 1.4rem 1.6rem; border-radius: 20px; background: linear-gradient(135deg,#172554,#312e81); color: white; margin-bottom: 1.2rem; }
    .hero h1 { margin: 0; font-size: 2.2rem; }
    .hero p { margin: .45rem 0 0; color: #dbeafe; }
    [data-testid="stFileUploader"] { background: rgba(30,41,59,.55); border-radius: 14px; padding: .4rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="hero"><h1>🎬 Ko Tint Free AI</h1><p>AI Movie Recap · Burmese voiceover · Subtitle · Video export</p></div>',
    unsafe_allow_html=True,
)

if "result_path" not in st.session_state:
    st.session_state.result_path = None
if "last_job" not in st.session_state:
    st.session_state.last_job = None

with st.sidebar:
    st.header("⚙️ Settings")
    gemini_keys_text = st.text_area(
        "Gemini API keys",
        value="",
        type="password",
        help="Multiple keys may be separated by commas. Keys are used only for this session.",
        height=90,
    )
    groq_key = st.text_input("Groq API key", value="", type="password")
    platform_label = st.selectbox("Video platform / aspect ratio", ["YouTube / 16:9", "TikTok / 9:16", "Facebook / 9:16"])
    resolution_label = st.selectbox("Resolution", ["720p", "1080p"])
    voice_options = {key: value["name"] for key, value in engine.VOICE_MODES.items()}
    voice_key = st.selectbox("🎙️ Voice", list(voice_options), format_func=lambda key: voice_options[key], index=1)
    speed_label = st.selectbox("⚡ Voice speed", list(engine.SPEED_MULTIPLIERS), index=0)
    subtitle_enabled = st.toggle("📝 Burmese subtitles", value=True)
    blur_enabled = st.toggle("🌫️ Blur mask", value=False)
    title_enabled = st.toggle("🏷️ Title overlay", value=True)
    bypass_enabled = st.toggle("🛡️ Edit bypass", value=False)
    sub_color = st.selectbox("🎨 Subtitle color", ["yellow", "white", "#00E5FF", "#39FF14", "#FF6EC7"])
    font_files = getattr(engine, "AVAILABLE_FONTS", [])
    font_labels = [Path(path).name for path in font_files]
    font_choice = st.selectbox("🔤 Myanmar font", font_labels or ["Default"])
    st.caption("For fastest processing: 720p · subtitles off · blur off · speed 1.0x")

col1, col2 = st.columns([1.35, 1])
with col1:
    uploaded = st.file_uploader("Upload a video", type=["mp4", "mov", "mkv", "webm", "avi"])
    youtube_url = st.text_input("Or paste a YouTube URL (optional)")
with col2:
    st.info("Your API keys are not written to GitHub by this app. Enter them only when processing a job.")
    st.markdown("**Workflow**\n\n1. Upload or paste a video\n2. Choose voice and subtitle settings\n3. Click **Generate recap**\n4. Download the finished MP4")

start = st.button("🚀 Generate recap", type="primary", use_container_width=True)


def _platform_code(label: str) -> str:
    if label.startswith("TikTok") or label.startswith("Facebook"):
        return "tiktok"
    return "yt"


def _resolution_code(label: str) -> str:
    return "1080" if label.startswith("1080") else "720"


async def _run_pipeline(input_video: str, audio_path: str, output_path: str, status_box, progress_bar):
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
    engine.user_title_mode[USER_ID] = title_enabled
    engine.user_bypass_mode[USER_ID] = bypass_enabled
    engine.user_sub_color[USER_ID] = sub_color
    if font_files and font_choice != "Default":
        selected = next((p for p in font_files if Path(p).name == font_choice), font_files[0])
        engine.user_font[USER_ID] = selected
    await engine.advanced_sync_pipeline(
        audio_path=audio_path,
        gemini_keys_str=gemini_keys_text,
        groq_key=groq_key,
        input_video=input_video,
        output_video_path=output_path,
        voice_config=engine.VOICE_MODES[voice_key],
        user_speed_val=engine.SPEED_MULTIPLIERS[speed_label],
        user_id=USER_ID,
        progress_cb=progress,
    )


if start:
    if not uploaded and not youtube_url.strip():
        st.error("Please upload a video or paste a YouTube URL.")
        st.stop()
    if not gemini_keys_text.strip() or not groq_key.strip():
        st.error("Please enter Gemini key(s) and a Groq key in the sidebar.")
        st.stop()

    job_dir = Path(tempfile.mkdtemp(prefix="recap_", dir=WORK_ROOT))
    input_path = job_dir / (uploaded.name if uploaded else "source.mp4")
    audio_path = job_dir / "source_audio.mp3"
    output_path = job_dir / "recap_output.mp4"
    status_box = st.empty()
    progress_bar = st.progress(0)
    try:
        if uploaded:
            input_path.write_bytes(uploaded.getbuffer())
        else:
            status_box.info("⬇️ Downloading source video...")
            engine.download_youtube_video(youtube_url.strip(), str(input_path))
        status_box.info("🎧 Extracting source audio...")
        engine.extract_audio_ffmpeg(str(input_path), str(audio_path))
        asyncio.run(_run_pipeline(str(input_path), str(audio_path), str(output_path), status_box, progress_bar))
        progress_bar.progress(100)
        status_box.success("✅ Recap finished successfully.")
        st.session_state.result_path = str(output_path)
        st.session_state.last_job = str(input_path.name)
    except Exception as exc:
        status_box.error(f"❌ Processing failed: {exc}")
        st.exception(exc)

if st.session_state.result_path and os.path.exists(st.session_state.result_path):
    st.divider()
    st.subheader("✅ Your recap is ready")
    st.video(st.session_state.result_path)
    with open(st.session_state.result_path, "rb") as f:
        st.download_button(
            "⬇️ Download MP4",
            data=f,
            file_name="ko_tint_free_ai_recap.mp4",
            mime="video/mp4",
            type="primary",
        )

st.caption("Ko Tint Free AI · Keep API keys private and do not commit them to GitHub.")

# Needed by Streamlit Cloud / local execution.
if __name__ == "__main__":
    pass


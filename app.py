import asyncio
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import streamlit as st

try:
    import psutil
except Exception:
    psutil = None

import engine
import threading

# Backend file-based storage for settings persistence
import os as _os
_STORAGE_DIR = Path(os.path.join(tempfile.gettempdir(), "ko_tint_storage"))
_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_FILE = _STORAGE_DIR / "ko_tint_preferences.json"

def _save_to_backend_file(payload_dict):
    """Save preferences to a JSON file on the server (backend)."""
    try:
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload_dict, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def _load_from_backend_file():
    """Load preferences from a JSON file on the server (backend)."""
    try:
        if os.path.exists(STORAGE_FILE):
            with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    except Exception:
        return None


# Remove old localStorage component (not reliable on Streamlit Cloud)
LocalStorage = None

APP_ROOT = Path(__file__).resolve().parent
WORK_ROOT = APP_ROOT / "streamlit_jobs"
WORK_ROOT.mkdir(exist_ok=True)
PRESENCE_ROOT = WORK_ROOT / "presence"
PRESENCE_ROOT.mkdir(exist_ok=True)

# ===== Built-in Music (Auto-download from Incompetech) =====
# Music folder: APP_ROOT / "music"
# If music files don't exist locally, auto-download from Incompetech CDN
MUSIC_DIR = APP_ROOT / "music"
MUSIC_DIR.mkdir(exist_ok=True)

# Incompetech CDN URLs (royalty-free, CC BY 4.0)
_MUSIC_SOURCES = {
    "music_impact_prelude.mp3": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Impact%20Prelude.mp3",
    "music_dark_times.mp3": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Dark%20Times.mp3",
    "music_gymnopedie.mp3": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Gymnopedie%20No%201.mp3",
    "music_five_armies.mp3": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Five%20Armies.mp3",
    "music_ghost_dance.mp3": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Ghost%20Dance.mp3",
}

def _ensure_music_files():
    """Auto-download built-in music files from Incompetech if not present locally."""
    for fname, url in _MUSIC_SOURCES.items():
        fpath = MUSIC_DIR / fname
        if not fpath.exists() or fpath.stat().st_size < 100000:  # < 100KB = corrupt
            try:
                resp = httpx.get(url, timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200 and len(resp.content) > 100000:
                    fpath.write_bytes(resp.content)
            except Exception:
                pass  # Music unavailable - preset won't work but app still runs

# Run once at startup
_ensure_music_files()

st.set_page_config(
    page_title="Ko Tint Free AI",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Streamlit creates a separate session state per browser session. Use a stable
# per-session directory so two users never share previews, uploads, logos, or
# rendered output files.
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex
SESSION_ID = st.session_state.session_id
SESSION_ROOT = WORK_ROOT / SESSION_ID
SESSION_ROOT.mkdir(parents=True, exist_ok=True)
TEMP_ROOT = SESSION_ROOT / "temp"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
USER_ID = f"streamlit_{SESSION_ID}"
PREFERENCES_STORAGE_KEY = "ko_tint_free_ai_preferences_v1"


import httpx

def _update_online_status():
    """Track current user as online using Google Sheets (shared across instances)."""
    # Uses a public Google Apps Script web app as backend
    # This is a simple free approach that works across all Streamlit Cloud instances
    try:
        # Use a simple shared counter via a public API endpoint
        # We'll use a file-based approach with a shared timestamp file
        # For Streamlit Cloud, we use st.session_state + a shared key
        _timestamp = time.time()
        st.session_state["_last_active"] = _timestamp
        # Store in a shared location using st.cache_resource
        if "_online_users" not in st.session_state:
            st.session_state["_online_users"] = {}
        st.session_state["_online_users"][SESSION_ID] = _timestamp
        # Cleanup old entries (older than 60 seconds)
        now = time.time()
        st.session_state["_online_users"] = {
            k: v for k, v in st.session_state["_online_users"].items()
            if now - v < 60
        }
    except:
        pass

def _get_online_count():
    """Count users active in the last 60 seconds across all instances."""
    # Note: In Streamlit Cloud, each session is separate
    # So we can only track within a single session
    # For cross-instance tracking, you need a shared database (Supabase/Redis)
    
    # Fallback: return 1 (at least current user)
    # If we have cached online users from this instance
    if "_online_users" in st.session_state:
        now = time.time()
        active = {k: v for k, v in st.session_state["_online_users"].items() if now - v < 60}
        count = len(active)
        return max(1, count)
    return 1

_update_online_status()

def _cleanup_old_job_roots(max_age_hours=24):
    """Remove abandoned session/job folders while preserving the active session."""
    cutoff = time.time() - (max_age_hours * 3600)
    for child in WORK_ROOT.iterdir():
        if child.name == SESSION_ID or not child.is_dir():
            continue
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            pass


_cleanup_old_job_roots()

TEXT = {
    "မြန်မာ": {
        "settings": "⚙️ ဆက်တင်များ",
        "language": "ဘာသာစကား",
        "theme": "အလင်း/အမှောင်",
        "dark": "အမှောင်",
        "light": "အလင်း",
        "keys": "Gemini API key များ (ကော်မာခံပြီး)",
        "groq": "Groq API key",
        "remember_keys": "ဒီ Browser မှာ API keys မှတ်ထားမည်",
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
        "download_name": "Download ဖိုင်အမည်",
        "logo": "🖼️ ကိုယ်ပိုင် Logo",
        "bg_music": "🎵 Background Music ဖွင့်မည်",
        "bg_music_file": "Background Music ဖိုင်ထည့်ပါ",
        "bg_music_volume": "Background Music အသံအတိုးအကျယ်",
        "bg_music_preset": "🎶 Built-in Music",
        "bg_preset_none": "မရွေးရသေး (None)",
        "tip_bgm_presets": "Built-in royalty-free music (CC BY 4.0 - Kevin MacLeod)",
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
        "online_users": "👥 လက်ရှိအသုံးပြုသူ",
        "tip_lang": "ဘာသာစကားပြောင်းရန်",
        "tip_theme": "အလင်း/အမှောင် ပြောင်းရန်",
        "tip_keys": "Gemini API key များကို ကော်မာခံပြီး ၅ ခုခန့်ထည့်ပါ။",
        "tip_groq": "အသံဖမ်းယူရန် Groq API key ထည့်ပါ။",
        "tip_remember": "နောက်တစ်ခါပြန်ဝင်ရင် key ရိုက်စရာမလိုအောင် မှတ်ထားမည်။",
        "tip_fallback": "ကိုယ့် key တွေ limit ပြည့်ရင် shared key တွေကို အရန်သုံးမည်။",
        "tip_platform": "ဗီဒီယိုတင်မည့်နေရာအလိုက် အရွယ်အစားရွေးပါ။",
        "tip_voice": "နောက်ခံစကားပြောအသံကို ရွေးပါ။",
        "tip_speed": "စကားပြောအမြန်နှုန်းကို ချိန်ပါ။",
        "tip_subtitle": "မြန်မာစာတန်းထိုး ထည့်မထည့် ရွေးပါ။",
        "tip_sub_pos": "စာတန်းထိုးပြမည့် အမြင့်ကို ချိန်ပါ။",
        "tip_sub_size": "စာတန်းစာလုံး အရွယ်အစားကို ချိန်ပါ။",
        "tip_blur": "ဗီဒီယို၏ အပေါ်/အောက် အနားသတ်များကို Blur လုပ်ပါ။",
        "tip_title": "ဗီဒီယိုအပေါ်တွင် ခေါင်းစဉ်စာသား ထည့်ပါ။",
        "tip_wm": "ဗီဒီယိုတွင် ကိုယ်ပိုင်အမှတ်အသား (Watermark) ထည့်ပါ။",
        "tip_bgm": "နောက်ခံသီချင်း ထည့်သွင်းအသုံးပြုပါ။",
        "guide": "❓ အသုံးပြုပုံ လမ်းညွှန်",
        "guide_text": """
### **အဆင့်ဆင့် အသုံးပြုပုံ**
1.  **API Keys ထည့်သွင်းပါ**: ဘေးဘက် (Sidebar) ရှိ **API Keys** အကွက်တွင် Gemini Key (၅ ခုခန့်) နှင့် Groq Key (၁ ခု) ကို ထည့်ပါ။
2.  **Video ရွေးချယ်ပါ**: ဗီဒီယိုဖိုင်ကို တိုက်ရိုက်တင်ပါ (သို့မဟုတ်) YouTube URL ကို ထည့်ပါ။
3.  **စိတ်ကြိုက်ပြင်ဆင်ပါ**: အသံအမျိုးအစား၊ စာတန်းထိုးအရောင်နှင့် နေရာ၊ Blur Mask စသည်တို့ကို ချိန်ညှိပါ။
4.  **Recap ထုတ်လုပ်ပါ**: အောက်ခြေရှိ **🚀 Recap ထုတ်မည်** ခလုတ်ကို နှိပ်ပြီး ခဏစောင့်ပါ။
5.  **Download ရယူပါ**: အားလုံးပြီးပါက **⬇️ MP4 Download** ခလုတ်ဖြင့် ဗီဒီယိုကို သိမ်းဆည်းပါ။

---
### **အသုံးဝင်သော အကြံပြုချက်များ (Pro Tips)**
*   **Key Limit ကျော်ခြင်း**: Key များစွာကို ကော်မာ (,) ခံပြီး ထည့်ထားရင် Rendering ပိုမြန်ပါတယ်။
*   **Emergency Mode**: ကိုယ်ပိုင် key တွေ Limit ပြည့်သွားရင် **"အရေးပေါ် Secrets သုံးမည်"** ကို ဖွင့်သုံးနိုင်ပါတယ်။
*   **Settings မှတ်ထားရန်**: အောက်ဆုံးက **"Save All Settings Now"** ကို နှိပ်ထားရင် နောက်တစ်ခါ ပြန်ဝင်တဲ့အခါ ဘာမှပြန်ပြင်စရာ မလိုတော့ပါဘူး။
""",
    },
    "English": {
        "settings": "⚙️ Settings",
        "language": "Language",
        "theme": "Appearance",
        "dark": "Dark",
        "light": "Light",
        "keys": "Gemini API keys (comma-separated)",
        "groq": "Groq API key",
        "remember_keys": "Remember API keys on this browser",
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
        "download_name": "Download file name",
        "logo": "🖼️ Custom logo",
        "bg_music": "🎵 Enable background music",
        "bg_music_file": "Upload background music",
        "bg_music_volume": "Background music volume",
        "bg_music_preset": "🎶 Built-in Music Presets",
        "bg_preset_none": "None",
        "tip_bgm_presets": "Built-in royalty-free music (CC BY 4.0 - Kevin MacLeod)",
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
        "online_users": "👥 Online Users",
        "tip_lang": "Change UI language",
        "tip_theme": "Switch dark/light mode",
        "tip_keys": "Enter ~5 Gemini keys separated by commas.",
        "tip_groq": "Enter Groq key for transcription.",
        "tip_remember": "Save keys in browser for next visit.",
        "tip_fallback": "Use shared keys if yours hit limits.",
        "tip_platform": "Select target aspect ratio.",
        "tip_voice": "Select AI voiceover.",
        "tip_speed": "Adjust talking speed.",
        "tip_subtitle": "Enable or disable Burmese subtitles.",
        "tip_sub_pos": "Adjust vertical position of subtitles.",
        "tip_sub_size": "Adjust font size of subtitles.",
        "tip_blur": "Apply blur masks to top/bottom edges.",
        "tip_title": "Overlay a title text on the video.",
        "tip_wm": "Add a custom watermark text to the video.",
        "tip_bgm": "Enable and configure background music.",
        "guide": "❓ User Guide",
        "guide_text": """
### **Step-by-Step Guide**
1.  **Enter API Keys**: In the sidebar, enter Gemini keys (recommended 5) and Groq key (1).
2.  **Select Video**: Upload a file or paste a YouTube URL.
3.  **Customize**: Adjust voice, subtitle colors, positions, and blur masks.
4.  **Generate**: Click **🚀 Generate Recap** and wait for the process to finish.
5.  **Download**: Click **⬇️ Download MP4** to save your video.

---
### **Pro Tips**
*   **Speed Up**: Use multiple keys separated by commas for faster rendering.
*   **Emergency Mode**: Enable **"Emergency Secrets Fallback"** if your personal keys hit limits.
*   **Remember Settings**: Use **"Save All Settings Now"** to keep your preferences for the next visit.
""",
    },
}

if "ui_lang" not in st.session_state:
    st.session_state.ui_lang = "မြန်မာ"
if "theme" not in st.session_state:
    st.session_state.theme = "dark"
# Keep video preferences for this browser session. Each user gets a separate
# Streamlit session_state, so these values do not leak between users.
_REMEMBERED_DEFAULTS = {
    "platform_label": "YouTube / 16:9",
    "resolution_label": "720p",
    "voice_key": None,
    "speed_label": None,
    "subtitle_enabled": True,
    "sub_color": "yellow",
    "blur_enabled": False,
    "title_enabled": True,
    "bypass_enabled": False,
    "font_choice": "Default",
    "wm_text": "Recap",
    "wm_pos": "bounce",
    "bg_music_enabled": False,
    "bg_music_preset": "none",
    "bg_music_volume": 0.15,
    "download_name": "ko_tint_free_ai_recap",
    "remember_api_keys": False,
}
for _pref_key, _pref_value in _REMEMBERED_DEFAULTS.items():
    if _pref_key not in st.session_state and _pref_value is not None:
        st.session_state[_pref_key] = _pref_value

# 1. Browser-local storage (Persistence Logic)
PREFERENCE_KEYS = tuple(_REMEMBERED_DEFAULTS.keys()) + (
    "ui_lang", "theme", "sub_y_percent", "sub_font_size", "blur_y_percent",
    "blur_strength", "blur_height", "blur_width", "title_size", "title_width",
)

def _load_preferences_from_storage():
    """Load preferences from backend file storage."""
    _stored_pref = _load_from_backend_file()
    if not _stored_pref:
        return False
    if isinstance(_stored_pref, dict):
        for _pref_key in PREFERENCE_KEYS:
            if _pref_key in _stored_pref and _stored_pref[_pref_key] is not None:
                st.session_state[_pref_key] = _stored_pref[_pref_key]
        if st.session_state.get("remember_api_keys"):
            st.session_state["gemini_keys_input"] = str(_stored_pref.get("gemini_keys", ""))
            st.session_state["groq_key_input"] = str(_stored_pref.get("groq_key", ""))
        return True
    return False

# Auto-load on first run (Optimized to avoid excessive reruns)
if not st.session_state.get("_preferences_loaded", False):
    if _load_preferences_from_storage():
        st.session_state["_preferences_loaded"] = True
        st.rerun()
    else:
        # If no data yet, wait a bit for the component to initialize, but don't loop forever
        attempts = st.session_state.get("_preferences_load_attempts", 0)
        if attempts < 2: # Reduced attempts to 2 for better UX
            st.session_state["_preferences_load_attempts"] = attempts + 1
            time.sleep(0.3)
            st.rerun()
        else:
            st.session_state["_preferences_loaded"] = True

# 2. Load from Query Params (Deep Linking)
QUERY_PARAMS_KEYS = ("ui_lang", "theme", "platform_label", "resolution_label", "voice_key", "speed_label")
for qk in QUERY_PARAMS_KEYS:
    if qk in st.query_params:
        val = st.query_params[qk]
        if val.lower() == "true": val = True
        elif val.lower() == "false": val = False
        st.session_state[qk] = val


def _load_preferences_via_query():
    """Load preferences from backend file via query params (avoids widget write-after-creation error)."""
    _stored_pref = _load_from_backend_file()
    if not _stored_pref or not isinstance(_stored_pref, dict):
        return False
    
    # Encode all preference values into query params
    new_query_params = {}
    for _pk in PREFERENCE_KEYS:
        if _pk in _stored_pref and _stored_pref[_pk] is not None:
            val = _stored_pref[_pk]
            if isinstance(val, bool):
                new_query_params[_pk] = "true" if val else "false"
            else:
                new_query_params[_pk] = str(val)
    
    if not new_query_params:
        return False
    
    # Set query params and trigger a rerun - widgets will pick up values on next pass
    st.query_params.update(new_query_params)
    # Mark that we need to apply from query params
    st.session_state["_apply_from_query"] = True
    return True


def _apply_query_params_to_session():
    """Apply query params to session_state BEFORE widgets are created."""
    for qk in QUERY_PARAMS_KEYS:
        if qk in st.query_params:
            val = st.query_params[qk]
            if val.lower() == "true": val = True
            elif val.lower() == "false": val = False
            st.session_state[qk] = val


# 3. Apply saved preferences from query params (after Load button press)
if st.session_state.get("_apply_from_query", False):
    _apply_query_params_to_session()
    # Also apply extra keys not in QUERY_PARAMS_KEYS
    _stored = _load_from_backend_file()
    if isinstance(_stored, dict):
        for _pk in PREFERENCE_KEYS:
            if _pk in _stored and _stored[_pk] is not None and _pk not in QUERY_PARAMS_KEYS:
                st.session_state[_pk] = _stored[_pk]
    st.session_state.pop("_apply_from_query", None)
    st.rerun()


T = TEXT[st.session_state.ui_lang]


def _save_preferences():
    # 1. Save to backend file (server-side persistence)
    _payload = {}
    for _pk in PREFERENCE_KEYS:
        if _pk in st.session_state:
            _payload[_pk] = st.session_state[_pk]
    # Also save API keys if remember is enabled
    if st.session_state.get("remember_api_keys"):
        _payload["gemini_keys"] = st.session_state.get("gemini_keys_input", "")
        _payload["groq_key"] = st.session_state.get("groq_key_input", "")
    _save_to_backend_file(_payload)
    
    # 2. Save non-sensitive to Query Params (URL)
    new_query_params = {}
    for qk in QUERY_PARAMS_KEYS:
        if qk in st.session_state:
            new_query_params[qk] = str(st.session_state[qk])
    st.query_params.update(new_query_params)


def _on_pref_change():
    # Only save when a value actually changes via widget interaction
    _save_preferences()


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
    
    /* ===== RESPONSIVE DESIGN ===== */
    /* Desktop (1200px+) */
    @media (min-width: 1200px) {{
        [data-testid="stSidebar"] {{
            min-width: 320px !important;
            max-width: 350px !important;
        }}
    }}
    
    /* Tablet (768px - 1199px) */
    @media (max-width: 1199px) and (min-width: 768px) {{
        [data-testid="stSidebar"] {{
            min-width: 280px !important;
            max-width: 300px !important;
        }}
        .block-container {{ max-width: 100%; padding: 1rem; }}
        .hero h1 {{ font-size: 1.8rem; }}
    }}
    
    /* Mobile (< 768px) */
    @media (max-width: 767px) {{
        [data-testid="stSidebar"] {{
            min-width: 100vw !important;
            max-width: 100vw !important;
            width: 100vw !important;
        }}
        .block-container {{ 
            max-width: 100%; 
            padding: 0.5rem; 
        }}
        .hero {{ 
            padding: 1rem; 
            border-radius: 12px; 
            margin-bottom: 0.8rem;
        }}
        .hero h1 {{ font-size: 1.5rem; }}
        .hero p {{ font-size: 0.85rem; }}
        [data-testid="stFileUploader"] {{ border-radius: 10px; }}
        
        /* Make buttons and inputs touch-friendly on mobile */
        button[kind="primary"] {{ 
            min-height: 44px; 
            font-size: 1rem; 
        }}
        input[type="text"], input[type="password"], textarea {{ 
            font-size: 16px !important;
        }}
    }}
    
    /* Extra small screens (< 480px) */
    @media (max-width: 479px) {{
        .hero h1 {{ font-size: 1.3rem; }}
        .hero p {{ font-size: 0.75rem; }}
        .block-container {{ padding: 0.3rem; }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

def _safe_download_filename(name):
    cleaned = re.sub(r"[^\w .-]+", "", str(name or ""), flags=re.UNICODE).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.strip("._-")
    return (cleaned[:90] or "ko_tint_free_ai_recap") + ".mp4"


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
    if st.session_state[key] != value:
        st.session_state[key] = value
        _on_pref_change()
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
    st.header("Ko Tint Free AI")
    
    # Online User Counter
    online_count = _get_online_count()
    st.caption(f"{T['online_users']}: **{online_count}** 👤")
    
    st.session_state.ui_lang = st.selectbox(T["language"], ["မြန်မာ", "English"], index=["မြန်မာ", "English"].index(st.session_state.ui_lang), on_change=_on_pref_change, help=T["tip_lang"])
    T = TEXT[st.session_state.ui_lang]
    
    # Group 1: API Keys & Security
    with st.expander("🔑 API Keys & Security", expanded=True):
        st.caption(T["privacy"])
        remember_api_keys = st.checkbox(
            T["remember_keys"], key="remember_api_keys",
            on_change=_on_pref_change,
            help=T["tip_remember"],
        )
        gemini_keys_text = st.text_input(T["keys"], type="password", key="gemini_keys_input", on_change=_on_pref_change, help=T["tip_keys"])
        groq_key = st.text_input(T["groq"], type="password", key="groq_key_input", on_change=_on_pref_change, help=T["tip_groq"])
        
        # Hybrid Key Management: Merge Secrets and UI input
        secrets_gemini = st.secrets.get("GEMINI_KEYS", "")
        secrets_groq = st.secrets.get("GROQ_API_KEY", "")
        
        # Emergency Controls (Inside Security)
        st.divider()
        st.subheader("🚨 Emergency Fallback")
        emergency_fallback = st.toggle("အရေးပေါ် Secrets ကို အသုံးပြုမည်", value=False, help=T["tip_fallback"])
        if st.button("Reset All Cooldowns", use_container_width=True, help="Key များ အားလုံးကို Active ပြန်ဖြစ်အောင် လုပ်မည်။"):
            engine.reset_global_cooldowns()
            st.toast("🚨 Cooldowns reset successfully!", icon="🔥")

        # Tiered Key Logic
        primary_gemini = gemini_keys_text
        fallback_gemini = secrets_gemini if emergency_fallback else ""
        merged_groq = groq_key if groq_key.strip() else secrets_groq

        if primary_gemini or fallback_gemini:
            st.divider()
            st.caption("Key Status Monitor (" + ("Fallback Enabled" if emergency_fallback else "UI Only") + ")")
            try:
                st.table(engine.GeminiKeyPool(primary_gemini, fallback_gemini).get_status())
            except Exception:
                st.write("Key status monitor unavailable.")

        if st.button(T["validate"], use_container_width=True):
            with st.spinner("Checking..."):
                gemini_ok, groq_ok = _validate_api_keys(primary_gemini or fallback_gemini, merged_groq)
            if gemini_ok and groq_ok:
                st.success(T["validation_ready"])
            else:
                st.error(f"{T['validation_failed']}")

    # Group 2: General Settings
    with st.expander("⚙️ General Settings", expanded=True):
        st.session_state.theme = st.radio(T["theme"], ["dark", "light"], format_func=lambda x: T["dark"] if x == "dark" else T["light"], horizontal=True, index=0 if st.session_state.theme == "dark" else 1, on_change=_on_pref_change, help=T["tip_theme"])
        
        platform_options = ["YouTube / 16:9", "TikTok / 9:16", "Facebook / 9:16"]
        if st.session_state.get("platform_label") not in platform_options:
            st.session_state.platform_label = platform_options[0]
        platform_label = st.selectbox(T["platform"], platform_options, index=platform_options.index(st.session_state.platform_label) if st.session_state.platform_label in platform_options else 0, key="platform_label", on_change=_on_pref_change, help=T["tip_platform"])
        
        resolution_options = ["720p", "1080p"]
        if st.session_state.get("resolution_label") not in resolution_options:
            st.session_state.resolution_label = resolution_options[0]
        resolution_label = st.selectbox(T["resolution"], resolution_options, index=resolution_options.index(st.session_state.resolution_label) if st.session_state.resolution_label in resolution_options else 0, key="resolution_label", on_change=_on_pref_change)
        
        voice_keys = list(engine.VOICE_MODES)
        if voice_keys and st.session_state.get("voice_key") not in voice_keys:
            st.session_state.voice_key = voice_keys[1] if len(voice_keys) > 1 else voice_keys[0]
        
        def _voice_number_label(key):
            number = voice_keys.index(key) + 1
            raw_name = str(engine.VOICE_MODES[key].get("name", ""))
            suffix = raw_name[raw_name.find("("):].strip() if "(" in raw_name else ""
            return f"{number} {suffix}".strip()
            
        voice_key = st.selectbox(T["voice"], voice_keys, index=voice_keys.index(st.session_state.voice_key) if st.session_state.voice_key in voice_keys else 0, format_func=_voice_number_label, key="voice_key", on_change=_on_pref_change, help=T["tip_voice"])
        
        speed_options = list(engine.SPEED_MULTIPLIERS)
        if st.session_state.get("speed_label") not in speed_options:
            st.session_state.speed_label = speed_options[0]
        speed_label = st.selectbox(T["speed"], speed_options, index=speed_options.index(st.session_state.speed_label) if st.session_state.speed_label in speed_options else 0, key="speed_label", on_change=_on_pref_change, help=T["tip_speed"])

    # Group 3: Advanced Controls
    with st.expander(T["advanced"], expanded=False):
        subtitle_enabled = st.toggle(T["subtitle"], value=st.session_state.get("subtitle_enabled", False), key="subtitle_enabled", on_change=_on_pref_change, help=T["tip_subtitle"])
        sub_y_percent = _nudge_slider(T["subtitle_pos"], "sub_y_percent", 45, 88, 82)
        sub_font_size = _nudge_slider(T["subtitle_size"], "sub_font_size", 24, 60, 35)
        color_values = ["yellow", "white", "#00E5FF", "#39FF14", "#FF6EC7"]
        sub_color = st.selectbox(T["subtitle_color"], color_values, format_func=_named_color, index=color_values.index(st.session_state.sub_color) if st.session_state.sub_color in color_values else 0, key="sub_color", on_change=_on_pref_change)
        
        st.divider()
        blur_enabled = st.toggle(T["blur"], value=st.session_state.get("blur_enabled", False), key="blur_enabled", on_change=_on_pref_change, help=T["tip_blur"])
        blur_y_percent = _nudge_slider(T["blur_pos"], "blur_y_percent", 45, 88, 82)
        blur_strength = _nudge_slider(T["blur_strength"], "blur_strength", 1, 20, 5)
        blur_height = _nudge_slider(T["blur_height"], "blur_height", 6, 24, 12)
        blur_width = _nudge_slider(T["blur_width"], "blur_width", 50, 100, 100)
        
        st.divider()
        title_enabled = st.toggle(T["title"], key="title_enabled", on_change=_on_pref_change, help=T["tip_title"])
        title_size = _nudge_slider(T["title_size"], "title_size", 24, 64, 30)
        title_width = _nudge_slider(T["title_width"], "title_width", 45, 100, 65)
        
        st.divider()
        bypass_enabled = st.toggle(T["bypass"], value=st.session_state.get("bypass_enabled", False), key="bypass_enabled", on_change=_on_pref_change)
        font_files = getattr(engine, "AVAILABLE_FONTS", [])
        font_labels = [str(idx + 1) for idx, _ in enumerate(font_files)] or ["Default"]
        if st.session_state.get("font_choice") not in font_labels:
            st.session_state.font_choice = font_labels[0]
        font_choice = st.selectbox(T["font"], font_labels, index=font_labels.index(st.session_state.font_choice) if st.session_state.font_choice in font_labels else 0, key="font_choice", on_change=_on_pref_change)
        
        st.divider()
        wm_text = st.text_input(T["wm_text"], key="wm_text", max_chars=80, on_change=_on_pref_change, help=T["tip_wm"])
        wm_pos_labels = {"bounce": "🔁 Bounce", "topleft": "↖️ Top left", "topright": "↗️ Top right", "bottom": "⬇️ Bottom center"}
        if st.session_state.get("wm_pos") not in wm_pos_labels:
            st.session_state.wm_pos = "bounce"
        wm_pos = st.selectbox(T["wm_pos"], list(wm_pos_labels), format_func=lambda x: wm_pos_labels[x], index=list(wm_pos_labels).index(st.session_state.wm_pos) if st.session_state.wm_pos in list(wm_pos_labels) else 0, key="wm_pos", on_change=_on_pref_change)
        st.text_input(T["download_name"], key="download_name", max_chars=100, on_change=_on_pref_change, help="Letters, Burmese text, numbers, spaces, _ and - are allowed.")
        logo_file = st.file_uploader(T["logo"], type=["png", "jpg", "jpeg"], key="logo_upload")
        
        st.divider()
        bg_music_enabled = st.toggle(T["bg_music"], value=st.session_state.get("bg_music_enabled", False), key="bg_music_enabled", on_change=_on_pref_change, help=T["tip_bgm"])
        
        # Built-in music presets (royalty-free, CC BY 4.0)
        _music_presets = {
            "none": T["bg_preset_none"],
            "music_impact_prelude.mp3": "Impact Prelude - Cinematic",
            "music_dark_times.mp3": "Dark Times - Suspense",
            "music_gymnopedie.mp3": "Gymnopedie No 1 - Emotional",
            "music_five_armies.mp3": "Five Armies - Epic",
            "music_ghost_dance.mp3": "Ghost Dance - Horror",
        }
        
        if bg_music_enabled:
            # Preset selectbox
            preset_keys = list(_music_presets.keys())
            if st.session_state.get("bg_music_preset") not in preset_keys:
                st.session_state.bg_music_preset = "none"
            bg_music_preset = st.selectbox(
                T["bg_music_preset"],
                preset_keys,
                format_func=lambda x: _music_presets.get(x, x),
                index=preset_keys.index(st.session_state.bg_music_preset) if st.session_state.bg_music_preset in preset_keys else 0,
                key="bg_music_preset",
                on_change=_on_pref_change,
                help=T["tip_bgm_presets"]
            )
            
            bg_music_file = st.file_uploader(
                T["bg_music_file"], type=["mp3", "wav", "m4a", "aac", "ogg"], key="bg_music_upload"
            )
        else:
            bg_music_preset = "none"
            bg_music_file = None
        
        bg_music_volume = st.slider(
            T["bg_music_volume"], min_value=0.0, max_value=1.0, step=0.05,
            key="bg_music_volume", on_change=_on_pref_change
        ) if bg_music_enabled else 0.0
        st.caption(T["calibration_help"])

    # Manual Persistence Controls
    col_save, col_load = st.columns(2)
    with col_save:
        if st.button("💾 Save", use_container_width=True, help="ဆက်တင်များကို အခုချက်ချင်း သိမ်းဆည်းမည်။"):
            _save_preferences()
            st.toast("✅ Saved!", icon="💾")
            time.sleep(0.3)
            st.rerun()  # Rerun to ensure localStorage completes
    with col_load:
        if st.button("🔄 Load", use_container_width=True, help="Server မှ ဆက့်တင့်များကို ပြန့်လည့်ဆွဲတင့်မည့်။"):
            # Load from backend file using query params (avoids StreamlitAPIException)
            loaded = _load_preferences_via_query()
            if loaded:
                st.toast("✅ Settings Loaded!", icon="🔄")
                st.rerun()
            else:
                st.toast("❌ No settings found. Please Save first.", icon="⚠️")

# _save_preferences() # REMOVED: Saving should only happen on change, not on every rerun

if "result_path" not in st.session_state:
    st.session_state.result_path = None
if "last_job" not in st.session_state:
    st.session_state.last_job = None

st.markdown('<div class="hero"><h1>🎬 Ko Tint Free AI</h1><p>AI Movie Recap · Burmese voiceover · Subtitle · Video export</p></div>', unsafe_allow_html=True)

with st.expander(T["guide"], expanded=False):
    st.markdown(T["guide_text"])

col1, col2, col3 = st.columns([1.35, 1, 1])
with col1:
    uploaded = st.file_uploader(T["upload"], type=["mp4", "mov", "mkv", "webm", "avi"])
    youtube_url = st.text_input(T["youtube"])
    if uploaded is not None:
        upload_sig = (uploaded.name, int(getattr(uploaded, "size", 0)))
        if st.session_state.get("uploaded_sig") != upload_sig:
            upload_suffix = Path(uploaded.name).suffix or ".mp4"
            upload_path = SESSION_ROOT / f"uploaded_source{upload_suffix}"
            with open(upload_path, "wb") as upload_handle:
                upload_handle.write(uploaded.getbuffer())
            st.session_state.uploaded_name = uploaded.name
            st.session_state.uploaded_path = str(upload_path)
            st.session_state.uploaded_sig = upload_sig
            st.session_state.preview_frame_sig = None
            st.session_state.pop("uploaded_bytes", None)
    persisted_upload_path = Path(st.session_state.get("uploaded_path", ""))
    persisted_upload = persisted_upload_path.exists()
    persisted_upload_name = st.session_state.get("uploaded_name", persisted_upload_path.name or "source.mp4")
with col2:
    st.subheader(T["workflow"])
    st.markdown(T["workflow_text"])
with col3:
    st.subheader(T["monitor"])
    if psutil:
        ram = psutil.virtual_memory().percent
        # RAM only - show as a simple progress bar
        color = "🔴" if ram > 85 else "🟡" if ram > 70 else "🟢"
        st.markdown(f"**{color} RAM: {ram:.0f}%**")
        st.progress(int(ram) / 100)
        # RAM Clear button
        import gc
        gc.collect()  # Run garbage collector
        if st.button("🗑️ RAM ရှင့်း", use_container_width=True):
            gc.collect()
            st.toast("✅ RAM ရှင့်းပြီးပါပြီ!", icon="✅")
            st.rerun()
    else:
        st.caption("psutil is not installed")

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
        preview_input = SESSION_ROOT / f"calibration_source{preview_ext}"
        preview_frame = SESSION_ROOT / "calibration_frame.png"
        preview_overlay = SESSION_ROOT / "calibration_overlay.png"
        try:
            if not preview_input.exists() or st.session_state.get("preview_source_sig") != st.session_state.get("uploaded_sig"):
                shutil.copyfile(persisted_upload_path, preview_input)
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


def _friendly_processing_error(exc):
    text = str(exc or "").strip()
    lowered = text.lower()
    if "out of memory" in lowered or "cannot allocate" in lowered:
        return "RAM မလုံလောက်ပါ။ Video အရွယ်အစား/Resolution လျှော့ပြီး ပြန်စမ်းပါ။"
    if "ffmpeg" in lowered or "filter" in lowered:
        return "Video rendering မအောင်မြင်ပါ။ Resolution, Blur, Title setting ကို လျှော့ပြီး ပြန်စမ်းပါ။"
    if "yt_dlp" in lowered or "download" in lowered:
        return "URL video download မအောင်မြင်ပါ။ Public YouTube URL သေချာစစ်ပြီး MP4 upload နဲ့ ပြန်စမ်းပါ။"
    if "timeout" in lowered or "timed out" in lowered:
        return "Processing အချိန်ကုန်သွားပါပြီ။ Video တိုအောင် သို့မဟုတ် Resolution လျှော့ပြီး ပြန်စမ်းပါ။"
    return "Processing မအောင်မြင်ပါ။ Setting များစစ်ပြီး ပြန်စမ်းပါ။"


def _redacted_error(exc):
    text = str(exc or "")
    for secret in [gemini_keys_text, groq_key]:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text[-1600:] or "Unknown error"


async def _run_pipeline(input_video: str, audio_path: str, output_path: str, status_box, progress_bar, background_music_path=None, background_music_volume=0.0, work_dir=None):
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
        gemini_keys_str=primary_gemini,
        groq_key=merged_groq,
        input_video=input_video,
        output_video_path=output_path,
        voice_config=engine.VOICE_MODES[voice_key],
        user_speed_val=engine.SPEED_MULTIPLIERS[speed_label],
        user_id=USER_ID,
        progress_cb=progress,
        background_music_path=background_music_path,
        background_music_volume=background_music_volume,
        work_dir=work_dir,
        fallback_gemini_keys_str=fallback_gemini,
    )


if start:
    if not persisted_upload and not youtube_url.strip():
        st.error(T["missing_video"])
        st.stop()
    if not gemini_keys_text.strip() or not groq_key.strip():
        st.error(T["missing_keys"])
        st.stop()

    job_dir = Path(tempfile.mkdtemp(prefix="recap_", dir=SESSION_ROOT))
    input_path = job_dir / (persisted_upload_name if persisted_upload else "source.mp4")
    audio_path = job_dir / "source_audio.mp3"
    background_music_path = job_dir / "background_music"
    output_path = job_dir / "recap_output.mp4"
    status_box = st.empty()
    progress_bar = st.progress(0)
    try:
        queued_text = "⏳ Your recap is queued because another job is running..." if st.session_state.ui_lang == "English" else "⏳ အခြား video တစ်ခု လုပ်နေသောကြောင့် သင့် recap ကို queue ထဲ ထည့်ထားပါသည်..."
        started_text = "🎬 Processing started..." if st.session_state.ui_lang == "English" else "🎬 Processing စတင်နေပါသည်..."
        status_box.info(queued_text)
        with engine.web_job_slot():
            status_box.info(started_text)
            if logo_file:
                (TEMP_ROOT / f"logo_{USER_ID}.png").write_bytes(logo_file.getbuffer())
            if persisted_upload:
                shutil.copyfile(persisted_upload_path, input_path)
            else:
                status_box.info("⬇️ Downloading source video...")
                engine.download_youtube_video(youtube_url.strip(), str(input_path))
            status_box.info("🎧 Extracting source audio...")
            engine.extract_audio_ffmpeg(str(input_path), str(audio_path))
            bg_path_arg = None
            if bg_music_enabled:
                # Priority: uploaded file > built-in preset
                if bg_music_file is not None:
                    bg_suffix = Path(bg_music_file.name).suffix or ".mp3"
                    background_music_path = background_music_path.with_suffix(bg_suffix)
                    background_music_path.write_bytes(bg_music_file.getvalue())
                    bg_path_arg = str(background_music_path)
                elif bg_music_preset and bg_music_preset != "none":
                    # Look for built-in music in MUSIC_DIR
                    music_file = MUSIC_DIR / bg_music_preset
                    if music_file.exists():
                        # Copy to job dir for FFmpeg access
                        shutil.copyfile(str(music_file), str(background_music_path.with_suffix(".mp3")))
                        bg_path_arg = str(background_music_path.with_suffix(".mp3"))
                        st.session_state["_bg_preset_used"] = bg_music_preset
            pipeline_result = asyncio.run(_run_pipeline(
                str(input_path), str(audio_path), str(output_path), status_box, progress_bar,
                background_music_path=bg_path_arg, background_music_volume=bg_music_volume,
                work_dir=str(TEMP_ROOT)
            ))
        if isinstance(pipeline_result, (tuple, list)) and len(pipeline_result) >= 3:
            st.session_state.generated_caption = pipeline_result[1] or ""
            st.session_state.generated_hashtags = pipeline_result[2] or ""
        else:
            st.session_state.generated_caption = ""
            st.session_state.generated_hashtags = ""
        final_output = SESSION_ROOT / f"recap_{uuid.uuid4().hex}.mp4"
        shutil.move(str(output_path), str(final_output))
        progress_bar.progress(100)
        status_box.success(T["ready"])
        st.session_state.result_path = str(final_output)
        st.session_state.last_job = str(input_path.name)
    except Exception as exc:
        status_box.error(f"❌ {_friendly_processing_error(exc)}")
        with st.expander("Technical details" if st.session_state.ui_lang == "English" else "နည်းပညာအသေးစိတ်"):
            st.code(_redacted_error(exc), language="text")
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)

if st.session_state.result_path and os.path.exists(st.session_state.result_path):
    st.divider()
    st.subheader(T["ready"])
    st.video(st.session_state.result_path)
    generated_caption = st.session_state.get("generated_caption", "")
    generated_hashtags = st.session_state.get("generated_hashtags", "")
    
    # Auto-append music credit to caption
    _music_credit = ""
    if st.session_state.get("bg_music_enabled"):
        _preset = st.session_state.get("bg_music_preset", "none")
        _music_titles = {
            "music_impact_prelude.mp3": "Impact Prelude",
            "music_dark_times.mp3": "Dark Times",
            "music_gymnopedie.mp3": "Gymnopedie No 1",
            "music_five_armies.mp3": "Five Armies",
            "music_ghost_dance.mp3": "Ghost Dance",
        }
        if _preset in _music_titles:
            _song_name = _music_titles[_preset]
            _music_credit = f"🎵 Music: \"{_song_name}\" by Kevin MacLeod (incompetech.com) CC BY 4.0"
    
    if generated_caption or generated_hashtags or _music_credit:
        st.subheader("📣 Caption & Hashtags" if st.session_state.ui_lang == "English" else "📣 Caption နှင့် Hashtags")
        _parts = [p for p in (generated_caption, generated_hashtags, _music_credit) if p]
        telegram_caption = "\n\n".join(_parts)
        if telegram_caption:
            st.code(telegram_caption, language=None)
    with open(st.session_state.result_path, "rb") as f:
        st.download_button(
            T["download"], data=f,
            file_name=_safe_download_filename(st.session_state.get("download_name", "ko_tint_free_ai_recap")),
            mime="video/mp4", type="primary"
        )

st.caption("Ko Tint Free AI · Keep API keys private and do not commit them to GitHub.")

if __name__ == "__main__":
    pass

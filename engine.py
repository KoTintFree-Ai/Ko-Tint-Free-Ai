# =====================================================================
# AI MOVIE RECAP BOT - ENGINE v63.0 (MODERN PREMIUM CARD TB)
# =====================================================================

import os
import re
import time
import json
import asyncio
import logging
import threading
import subprocess
import sys
import base64
import glob
from concurrent.futures import ThreadPoolExecutor
import itertools
from contextlib import contextmanager

import httpx
import nest_asyncio
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.errors import MessageNotModifiedError
import edge_tts
import yt_dlp

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage, QPainter, QFont, QColor, QFontMetrics, QBrush, QPen, QPainterPath, QFontDatabase, QLinearGradient
from PyQt5.QtCore import Qt

_QT_APP = QApplication.instance() or QApplication(sys.argv)

nest_asyncio.apply()

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# Conservative defaults for two concurrent Streamlit users. Operators can raise
# these with environment variables when more CPU/RAM is available.
FFMPEG_THREADS = max(1, int(os.getenv("RECAP_FFMPEG_THREADS", "1")))
CHUNK_WORKERS = max(1, min(int(os.getenv("RECAP_CHUNK_WORKERS", "1")), 4))
TTS_WORKERS = max(1, min(int(os.getenv("RECAP_TTS_WORKERS", "3")), 5))
MAX_WEB_JOBS = max(1, int(os.getenv("RECAP_MAX_CONCURRENT_JOBS", "1")))
_WEB_JOB_SEMAPHORE = threading.BoundedSemaphore(MAX_WEB_JOBS)

@contextmanager
def web_job_slot():
    """Bound Streamlit jobs so concurrent users queue instead of exhausting RAM."""
    _WEB_JOB_SEMAPHORE.acquire()
    try:
        yield
    finally:
        _WEB_JOB_SEMAPHORE.release()

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

user_keys = {}
user_voices = {}
user_speeds = {}
user_stats = {}

# NEW FEATURES GLOBALS
user_platform = {}       
user_res = {}            
user_sub_mode = {}       
user_sub_color = {}      
user_title_mode = {}
user_title_size = {}
user_title_width = {}
user_blur_mode = {}
user_blur_y = {}         
user_blur_strength = {}
user_blur_height = {}
user_blur_width = {}
user_sub_y = {}
user_sub_size = {}       
user_pending_calib = {}  
user_wm_text = {}
user_wm_pos = {}
user_bypass_mode = {}    
user_font = {}           

SYSTEM_LOCKED = False
ADMIN_ID = API_ID
VALID_MODELS_CACHE = {}

user_queues = {}          
user_queue_active = {}    

os.makedirs("temp", exist_ok=True)

def ensure_work_dir(work_dir=None):
    """Return an isolated absolute work directory for one Streamlit session/job."""
    path = os.path.abspath(work_dir or "temp")
    os.makedirs(path, exist_ok=True)
    return path

# =====================================================================
# 🔤 CUSTOM FONT DETECTION & REGISTRATION
# =====================================================================
def _register_burmese_font(font_path):
    try:
        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                return families[0]
    except Exception as e:
        logging.warning(f"⚠️ Font registration failed: {e}")
    return "Arial"

AVAILABLE_FONTS = []
REGISTERED_FONTS = {}

# Search recursively so Colab can find fonts extracted under /content/Fonts.
_FONT_ROOTS = [
    os.getcwd(),
    os.path.dirname(os.path.abspath(__file__)),
    os.path.join(os.getcwd(), "Fonts"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "Fonts"),
]
for root in _FONT_ROOTS:
    if os.path.isdir(root):
        for ext in ("*.ttf", "*.otf", "*.TTF", "*.OTF"):
            AVAILABLE_FONTS.extend(glob.glob(os.path.join(root, "**", ext), recursive=True))

# Keep a stable, duplicate-free order and prefer a Myanmar Unicode font.
AVAILABLE_FONTS = list(dict.fromkeys(os.path.abspath(f) for f in AVAILABLE_FONTS if os.path.isfile(f)))
if not AVAILABLE_FONTS:
    _LOCAL_FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "font.ttf")
    if os.path.exists(_LOCAL_FONT):
        AVAILABLE_FONTS.append(_LOCAL_FONT)

for f in AVAILABLE_FONTS:
    fam = _register_burmese_font(f)
    REGISTERED_FONTS[f] = fam

_preferred_fonts = [
    f for f in AVAILABLE_FONTS
    if any(name in os.path.basename(f).lower() for name in ("notosansmyanmar", "pyidaungsu-2.5.3_regular", "pyidaungsu-1.8.3_regular", "myanmar_font"))
]
DEFAULT_FONT_FILE = _preferred_fonts[0] if _preferred_fonts else (AVAILABLE_FONTS[0] if AVAILABLE_FONTS else "Arial")
DEFAULT_FONT_FAMILY = REGISTERED_FONTS.get(DEFAULT_FONT_FILE, "Noto Sans Myanmar" if _preferred_fonts else "Arial")

def get_user_font_family(uid):
    ffile = user_font.get(uid, DEFAULT_FONT_FILE)
    return REGISTERED_FONTS.get(ffile, DEFAULT_FONT_FAMILY)


VOICE_MODES = {
    "v1":  {"name": "🎙️ ကိုစိုင်းစိုင်း",        "voice": "my-MM-ThihaNeural",                 "gender": "male",   "rate": "+18%", "pitch": "+0Hz"},
    "v2":  {"name": "🎙️ မဖွေးဖွေး",              "voice": "my-MM-NilarNeural",                 "gender": "female", "rate": "+18%", "pitch": "+0Hz"},
    "v3":  {"name": "🎙️ ကိုနေတိုး",              "voice": "it-IT-GiuseppeMultilingualNeural",  "gender": "male",   "rate": "+15%", "pitch": "+0Hz"},
    "v4":  {"name": "🎙️ ကိုအောင်ရဲလင်း",         "voice": "en-AU-WilliamMultilingualNeural",   "gender": "male",   "rate": "+15%", "pitch": "+0Hz"},
    "v5":  {"name": "🎙️ ကိုမြင့်မြတ်",           "voice": "en-US-AndrewMultilingualNeural",    "gender": "male",   "rate": "+15%", "pitch": "+0Hz"},
    "v6":  {"name": "🎙️ မဝတ်မှုံရွှေရည်",         "voice": "en-US-AvaMultilingualNeural",       "gender": "female", "rate": "+15%", "pitch": "+0Hz"},
    "v7":  {"name": "🎙️ ကိုဒေါင်း",              "voice": "en-US-BrianMultilingualNeural",     "gender": "male",   "rate": "+15%", "pitch": "+0Hz"},
    "v8":  {"name": "🎙️ မသက်မွန်မြင့်",          "voice": "en-US-EmmaMultilingualNeural",      "gender": "female", "rate": "+15%", "pitch": "+0Hz"},
    "v9":  {"name": "🎙️ ကိုလူမင်း",              "voice": "fr-FR-RemyMultilingualNeural",      "gender": "male",   "rate": "+15%", "pitch": "+0Hz"},
    "v10": {"name": "🎙️ မအိန္ဒြာကျော်ဇင်",        "voice": "fr-FR-VivienneMultilingualNeural",  "gender": "female", "rate": "+15%", "pitch": "+0Hz"},
    "v11": {"name": "🎙️ မရွှေမှုံရတီ",            "voice": "de-DE-SeraphinaMultilingualNeural", "gender": "female", "rate": "+15%", "pitch": "+0Hz"},
    "v12": {"name": "🎙️ ကိုပြေတီဦး",             "voice": "de-DE-FlorianMultilingualNeural",   "gender": "male",   "rate": "+15%", "pitch": "+0Hz"},
    "v13": {"name": "🎙️ မသင်ဇာဝင့်ကျော်",         "voice": "pt-BR-ThalitaMultilingualNeural",   "gender": "female", "rate": "+15%", "pitch": "+0Hz"},
    "v14": {"name": "🎙️ ကိုပိုင်တံခွန်",          "voice": "ko-KR-HyunsuMultilingualNeural",    "gender": "male",   "rate": "+15%", "pitch": "+0Hz"},
    "v15": {"name": "👩‍💼 Nilar (Standard)",       "voice": "my-MM-NilarNeural",                 "gender": "female", "rate": "+18%", "pitch": "+0Hz"},
    "v16": {"name": "⚡ Nilar (Fast Action)",     "voice": "my-MM-NilarNeural",                 "gender": "female", "rate": "+25%", "pitch": "+0Hz"},
    "v17": {"name": "🍃 Nilar (Soft Story)",       "voice": "my-MM-NilarNeural",                 "gender": "female", "rate": "+12%", "pitch": "-1Hz"},
    "v18": {"name": "✨ Nilar (High Engage)",      "voice": "my-MM-NilarNeural",                 "gender": "female", "rate": "+20%", "pitch": "+1Hz"},
    "v19": {"name": "🔮 Nilar (Suspense)",         "voice": "my-MM-NilarNeural",                 "gender": "female", "rate": "+15%", "pitch": "-2Hz"},
    "v20": {"name": "👨‍💼 Thiha (Standard)",       "voice": "my-MM-ThihaNeural",                 "gender": "male",   "rate": "+18%", "pitch": "+0Hz"},
    "v21": {"name": "🔥 Thiha (Fast Action)",     "voice": "my-MM-ThihaNeural",                 "gender": "male",   "rate": "+25%", "pitch": "+0Hz"},
    "v22": {"name": "💀 Thiha (Suspense)",         "voice": "my-MM-ThihaNeural",                 "gender": "male",   "rate": "+15%", "pitch": "-3Hz"},
    "v23": {"name": "💬 Thiha (Emotional)",        "voice": "my-MM-ThihaNeural",                 "gender": "male",   "rate": "+16%", "pitch": "+0Hz"},
    "v24": {"name": "📻 Thiha (Radio Style)",      "voice": "my-MM-ThihaNeural",                 "gender": "male",   "rate": "+20%", "pitch": "-1Hz"},
}

SPEED_RATES = {"1.0x": "+0%", "1.1x": "+15%", "1.2x": "+28%", "1.3x": "+40%", "1.4x": "+55%"}
SPEED_MULTIPLIERS = {"1.0x": 1.0, "1.1x": 1.1, "1.2x": 1.2, "1.3x": 1.3, "1.4x": 1.4}

MAIN_MENU_BUTTONS = [
    [Button.inline("📱 ဗီဒီယို ဆိုဒ်", b"menu_size"), Button.inline("📺 Resolution", b"menu_res")],
    [Button.inline("🎙️ အသံ ရွေးရန်", b"menu_voice"), Button.inline("⚡ Speed ရွေးရန်", b"menu_speed")],
    [Button.inline("📝 စာတန်းထိုး ဖွင့်/ပိတ်", b"menu_sub"), Button.inline("🔤 Font ရွေးရန်", b"menu_font")],
    [Button.inline("🏷️ Title ဖွင့်/ပိတ်", b"menu_title"), Button.inline("🎨 Sub Color", b"menu_subcolor")],
    [Button.inline("🌫️ Blur Mask", b"menu_blur"), Button.inline("🛡️ Edit Bypass", b"menu_bypass")],
    [Button.inline("💧 Watermark", b"menu_wm_pos"), Button.inline("🖼️ Logo ထည့်ရန်", b"menu_logo_help")]
]

SUB_COLOR_CHOICES = [("yellow", "အဝါရောင်"), ("white", "အဖြူရောင်"), ("#00E5FF", "စိမ်းပြာ (Cyan)"), ("#39FF14", "စိမ်းစို (Lime)"), ("#FF6EC7", "ပန်းရောင်")]

# =====================================================================
# 🌫️ BLUR MASK 
# =====================================================================
def get_blur_mask_filter(current_video_label="[0:v]", y_position_percent=82, border_thick=0, blur_strength=5, blur_height_percent=12, blur_width_percent=100):
    # Keep the blur band inside the frame and use even dimensions for FFmpeg filters.
    # Use a wider band so subtitles are fully covered, while keeping the crop
    # inside the frame even near the bottom edge.
    band_percent = max(2.0, min(float(blur_height_percent), 40.0))
    width_percent = max(25.0, min(float(blur_width_percent), 100.0))
    y_position_percent = max(0.0, min(float(y_position_percent), 100.0 - band_percent))
    blur_strength = max(1, min(int(blur_strength), 20))
    crop_y = f"trunc(ih*({y_position_percent}/100.0)/2)*2"
    band_h = f"trunc(ih*{band_percent/100.0}/2)*2"
    # The overlay Y coordinate is relative to the full original frame. Using
    # the blurred crop height (H) here kept the mask near the same position.
    overlay_y = f"trunc(main_h*({y_position_percent}/100.0)/2)*2"
    crop_x = f"trunc(iw*(1-{width_percent/100.0})/2/2)*2"
    crop_w = f"trunc(iw*{width_percent/100.0}/2)*2"
    # overlay expressions use main_w/main_h; iw/ih are not valid for the overlay x input.
    overlay_x = f"trunc(main_w*(1-{width_percent/100.0})/2/2)*2"
    filter_string = f"{current_video_label}split=2[orig_for_blur][blur_crop];"
    filter_string += f"[blur_crop]crop={crop_w}:{band_h}:{crop_x}:{crop_y},boxblur={blur_strength}:2[blurred_bot];"
    filter_string += f"[orig_for_blur][blurred_bot]overlay={overlay_x}:{overlay_y}[vid_sub_blurred]"
    return filter_string, "[vid_sub_blurred]"

# =====================================================================
# 📝 မြန်မာစာတန်းထိုး (PyQt5 PNG Render)
# =====================================================================
def parse_color_to_qt(color_str, alpha_str="1.0"):
    alpha = float(alpha_str)
    if "@" in color_str:
        parts = color_str.split("@")
        c_name = parts[0]
        alpha = float(parts[1])
    else: c_name = color_str
    color = QColor(c_name)
    color.setAlpha(int(alpha * 255))
    return color

def wrap_burmese_text(text, fm, max_w):
    lines = []
    for para in text.split('\n'):
        current_line = ""
        for char in para:
            if fm.horizontalAdvance(current_line + char) <= max_w:
                current_line += char
            else:
                last_space = current_line.rfind(' ')
                if last_space != -1 and last_space > len(current_line) * 0.6:
                    lines.append(current_line[:last_space].strip())
                    current_line = current_line[last_space+1:] + char
                else:
                    lines.append(current_line)
                    current_line = char
        if current_line: lines.append(current_line)
    return '\n'.join(lines)

def split_burmese_text_chronologically(text, start_t, end_t, max_chars=45):
    words = text.split()
    if len(words) < 3 and len(text) > max_chars:
        chunks = []
        cur = ""
        for char in text:
            cur += char
            if len(cur) >= max_chars and char in ['၊', '။', ' ', '\u104A', '\u104B']:
                chunks.append(cur.strip())
                cur = ""
        if cur: chunks.append(cur.strip())
        if not chunks: chunks = [text]
    else:
        chunks = []
        cur = ""
        for w in words:
            if len(cur) + len(w) > max_chars:
                chunks.append(cur.strip())
                cur = w + " "
            else: cur += w + " "
        if cur: chunks.append(cur.strip())

    duration = end_t - start_t
    if not chunks: return [{"start": start_t, "end": end_t, "text": text}]
    
    chunk_dur = duration / len(chunks)
    res = []
    for i, c in enumerate(chunks):
        if c: res.append({"start": start_t + i*chunk_dur, "end": start_t + (i+1)*chunk_dur, "text": c})
    return res

def create_text_image_full(text, font_size, text_color, outline_color, outline_width,
                            use_box, box_color, box_alpha, box_border,
                            width=1080, height=1920, align="bottom", margin_v=280, font_family="Arial", is_title=False, max_width_percent=100):
    width = int(width)
    height = int(height)
    margin_v = int(margin_v)

    img = QImage(width, height, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    if not text.strip(): return img
    painter = QPainter(img)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        font = QFont(font_family, int(font_size))
        font.setBold(True)
        painter.setFont(font)
        fm = QFontMetrics(font)

        text = text.replace("$$", "\n")
        usable_width = max(120, min(width - 60, int(width * max(0.25, min(float(max_width_percent), 100.0)) / 100.0)))
        text = wrap_burmese_text(text, fm, usable_width)
        lines = text.split('\n')

        max_line_w = int(max(fm.horizontalAdvance(line) for line in lines))
        total_h = int(len(lines) * fm.height())
        x = int((width - max_line_w) / 2)

        if align == "bottom": y = int(height - margin_v - total_h)
        elif align == "top": y = int(margin_v)
        else: y = int((height - total_h) / 2)
        
        if use_box:
            box_bg = parse_color_to_qt(box_color, box_alpha)
            painter.setBrush(QBrush(box_bg))
            painter.setPen(Qt.NoPen)
            pad_x = int(box_border)
            trim_top, trim_bottom = 10, 10
            box_y = y + trim_top
            box_h = total_h - trim_top - trim_bottom
            painter.drawRoundedRect(x - pad_x, box_y, max_line_w + pad_x*2, box_h, 12, 12)
            
        t_color = parse_color_to_qt(text_color)
        
        if is_title:
            gradient = QLinearGradient(0, 0, width, 0)
            gradient.setColorAt(0.0, QColor("#FF0055")) 
            gradient.setColorAt(0.5, QColor("#FFD700")) 
            gradient.setColorAt(1.0, QColor("#00E5FF")) 
            t_brush = QBrush(gradient)
        else:
            t_brush = QBrush(t_color)
            
        o_color = parse_color_to_qt(outline_color)
        o_width = int(outline_width)
        current_y = y + fm.ascent()
        for line in lines:
            line_w = int(fm.horizontalAdvance(line))
            line_x = x + int((max_line_w - line_w) / 2)
            path = QPainterPath()
            path.addText(float(line_x), float(current_y), font, line)
            path.setFillRule(Qt.WindingFill)

            if o_width > 0:
                painter.setPen(QPen(o_color, o_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)

            painter.setPen(Qt.NoPen)
            painter.setBrush(t_brush)
            painter.drawPath(path)
            current_y += int(fm.height())
    finally:
        if painter.isActive(): painter.end()
    return img

def generate_subtitle_overlay_filter(json_path, audio_length, job_dir, TW=1080, TH=1920, sub_y_percent=82, sub_color="yellow", font_fam="Arial", sub_font_size=35):
    with open(json_path, "r", encoding="utf-8") as f:
        segments = json.load(f)

    blank_path = os.path.join(job_dir, "blank_sub.png")
    blank_img = QImage(TW, TH, QImage.Format_ARGB32)
    blank_img.fill(Qt.transparent)
    blank_img.save(blank_path, "PNG")
    del blank_img

    subs_txt_path = os.path.join(job_dir, "subs_concat.txt")

    with open(subs_txt_path, "w", encoding="utf-8") as f:
        f.write("ffconcat version 1.0\n")
        current_time = 0.0
        abs_blank_path = os.path.abspath(blank_path).replace('\\', '/')

        for i, seg in enumerate(segments):
            txt = seg.get("text", "").strip()
            if not txt: continue

            start_t = float(seg["start"])
            end_t = float(seg["end"])

            if start_t > current_time:
                f.write(f"file '{abs_blank_path}'\n")
                f.write(f"duration {start_t - current_time:.3f}\n")
            sub_png_filename = f"sub_{i}.png"
            sub_abs_path = os.path.join(job_dir, sub_png_filename)

            sub_img = create_text_image_full(
                text=txt, font_size=sub_font_size, text_color=sub_color, outline_color="black", outline_width=3,
                use_box=True, box_color="black", box_alpha="0.50", box_border=22,
                width=TW, height=TH, align="top", margin_v=TH * (sub_y_percent / 100.0), font_family=font_fam, is_title=False
            )
            sub_img.save(sub_abs_path, "PNG")
            del sub_img
            
            abs_sub_path = os.path.abspath(sub_abs_path).replace('\\', '/')
            f.write(f"file '{abs_sub_path}'\n")
            f.write(f"duration {end_t - start_t:.3f}\n")
            current_time = end_t

        if current_time < audio_length:
            f.write(f"file '{abs_blank_path}'\n")
            f.write(f"duration {audio_length - current_time + 1.0:.3f}\n")
        f.write(f"file '{abs_blank_path}'\n")

    return subs_txt_path

# =====================================================================
# 🩺 HUGGING FACE HEALTH-CHECK & FFMPEG HELPERS
# =====================================================================
def run_health_check_server():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK - Telegram bot is running.")
        def log_message(self, format, *args): return
    port = int(os.environ.get("PORT", 7860))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

def run_ffmpeg(cmd, label="ffmpeg"):
    cmd = list(cmd)
    if cmd and os.path.basename(str(cmd[0])) == "ffmpeg" and "-threads" not in cmd:
        insert_at = 2 if len(cmd) > 1 and cmd[1] == "-y" else 1
        cmd[insert_at:insert_at] = ["-threads", str(FFMPEG_THREADS)]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "").strip()
        tail = tail[-800:] if len(tail) > 800 else tail
        raise RuntimeError(f"FFmpeg Error [{label}] (exit {result.returncode}):\n{tail}")
    return result

def extract_audio_ffmpeg(video_path, audio_path):
    cmd = ['ffmpeg', '-y', '-i', video_path, '-vn', '-acodec', 'libmp3lame', '-q:a', '2', audio_path]
    run_ffmpeg(cmd, label="extract_audio")

def is_youtube_link(url):
    return bool(re.search(r'(youtube\.com|youtu\.be)', url, re.IGNORECASE))

def download_youtube_video(url, output_path):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def get_media_duration(file_path):
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', file_path]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
    return float(json.loads(res.stdout)['format']['duration'])

def create_silent_audio(duration, output_path):
    cmd = ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-t', str(max(duration, 0.1)), '-q:a', '9', '-acodec', 'libmp3lame', output_path]
    run_ffmpeg(cmd, label="silent_audio")

def get_video_dimensions(platform, res):
    if platform == "tt": return (720, 1280) if res == "720" else (1080, 1920)
    elif platform == "fb": return (720, 720) if res == "720" else (1080, 1080)
    return (1280, 720) if res == "720" else (1920, 1080)

def extract_preview_frame(video_path, out_path, dim_w, dim_h, percent=0.3):
    dim_w = int(dim_w)
    dim_w = dim_w if dim_w % 2 == 0 else dim_w + 1
    dim_h = int(dim_h)
    dim_h = dim_h if dim_h % 2 == 0 else dim_h + 1
    
    try: dur = get_media_duration(video_path)
    except Exception: dur = 3.0
    ts = min(max(dur * percent, 0.3), max(dur - 0.3, 0.3))
    cmd = [
        'ffmpeg', '-y', '-ss', f"{ts:.2f}", '-i', video_path, '-frames:v', '1',
        '-vf', f"scale={dim_w}:{dim_h}:force_original_aspect_ratio=decrease,pad={dim_w}:{dim_h}:-1:-1:color=black",
        out_path
    ]
    run_ffmpeg(cmd, label="preview_frame")

def render_calibration_preview(frame_path, out_path, blur_y, sub_y, blur_on, sub_font_size=36, title_text="Preview Title", title_size=42, title_width=85, blur_height=12, blur_width=100):
    parts = []
    if blur_on:
        blur_h = max(2.0, min(float(blur_height), 40.0))
        blur_w = max(25.0, min(float(blur_width), 100.0))
        blur_x = (100.0 - blur_w) / 2.0
        parts.append(f"drawbox=x=iw*({blur_x}/100.0):y=ih*({blur_y}/100.0):w=iw*({blur_w}/100.0):h=ih*({blur_h}/100.0):color=white@0.55:t=fill")
    # Show a subtitle-like sample instead of a large red guide rectangle.
    preview_size = max(18, min(int(sub_font_size), 96))
    parts.append(
        f"drawtext=text='Subtitle Preview':fontcolor=white:fontsize={preview_size}:"
        f"borderw=2:bordercolor=red:x=(w-text_w)/2:y=h*({sub_y}/100.0)"
    )
    title_size = max(18, min(int(title_size), 96))
    title_width = max(25.0, min(float(title_width), 100.0))
    safe_title = str(title_text).replace("'", "\\\\'")
    parts.append(
        f"drawtext=text='{safe_title}':fontcolor=cyan:fontsize={title_size}:"
        f"borderw=3:bordercolor=black:x=(w-text_w)/2:y=h*0.08"
    )
    vf = ",".join(parts)
    cmd = ['ffmpeg', '-y', '-i', frame_path, '-vf', vf, out_path]
    run_ffmpeg(cmd, label="calibration_preview")

# =====================================================================
# 🖼️ TB THUMBNAIL GENERATOR (MODERN PREMIUM CARD STYLE)
# =====================================================================
def create_thumbnail(video_path, title_text, out_path, font_fam, w=1080, h=1920, work_dir=None, best_percent=0.5):
    """Creates a FULL-SCREEN thumbnail with no borders or inset cards."""
    work_dir = ensure_work_dir(work_dir)
    bg_path = os.path.join(work_dir, f"tb_bg_{int(time.time() * 1000)}.jpg")
    
    # Extract the best frame as the FULL BACKGROUND
    extract_preview_frame(video_path, bg_path, w, h, percent=best_percent)

    img = QImage(w, h, QImage.Format_ARGB32)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)

    # 1. Full Screen Background
    if os.path.exists(bg_path):
        bg_img = QImage(bg_path)
        painter.drawImage(0, 0, bg_img)
    else: 
        img.fill(Qt.black)

    # 2. Strong Bottom-up Gradient Overlay for text readability
    overlay_grad = QLinearGradient(0, h * 0.3, 0, h)
    overlay_grad.setColorAt(0.0, QColor(0, 0, 0, 0))    # Transparent top
    overlay_grad.setColorAt(0.6, QColor(0, 0, 0, 150))  # Semi-dark middle
    overlay_grad.setColorAt(1.0, QColor(0, 0, 0, 250))  # Very dark bottom for text
    painter.setBrush(QBrush(overlay_grad))
    painter.setPen(Qt.NoPen)
    painter.drawRect(0, 0, w, h)

    # 3. Bold & Punchy Title (White to Yellow Gradient)
    # Positioned near the bottom but with enough margin
    title_box_y = h - 600
    title_box_h = 500
    
    # Scale font size based on video width
    _font_size = int(65.0 * w / 1080.0) # Larger font for impact
    _font_size = max(32, min(_font_size, 110))
    
    # Auto-fit text
    while _font_size > 28:
        _test_font = QFont(font_fam, _font_size, QFont.Black)
        _test_metrics = QFontMetrics(_test_font)
        _max_w = w - 120
        _lines = []
        _words = title_text.strip().split()
        _cur = ""
        for _wd in _words:
            _t = (_cur + " " + _wd).strip()
            if _test_metrics.horizontalAdvance(_t) > _max_w and _cur:
                _lines.append(_cur)
                _cur = _wd
            else: _cur = _t
        if _cur: _lines.append(_cur)
        if (len(_lines) * _test_metrics.height() * 1.1) <= title_box_h: break
        _font_size -= 2
    
    painter.setFont(QFont(font_fam, _font_size, QFont.Black))
    
    # Thick Black Shadow for maximum readability
    offsets = [(-4,-4), (-4,4), (4,-4), (4,4), (-6,0), (6,0), (0,-6), (0,6), (8,8)]
    for ox, oy in offsets:
        painter.setPen(QColor(0, 0, 0, 255))
        painter.drawText(60 + ox, title_box_y + oy, w - 120, title_box_h, Qt.AlignCenter | Qt.TextWordWrap, title_text.strip())

    # Main Text Gradient
    text_grad = QLinearGradient(0, title_box_y, 0, title_box_y + title_box_h)
    text_grad.setColorAt(0.0, QColor("#FFFFFF"))
    text_grad.setColorAt(1.0, QColor("#FFD600")) # Vibrant Yellow
    painter.setPen(QPen(QBrush(text_grad), 0))
    painter.drawText(60, title_box_y, w - 120, title_box_h, Qt.AlignCenter | Qt.TextWordWrap, title_text.strip())

    # 4. "FULL STORY" Badge (Top Left)
    badge_w, badge_h = int(w * 0.28), int(h * 0.045)
    badge_x, badge_y = 50, 50
    painter.setBrush(QColor(220, 20, 60, 240)) # Deep Red
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(badge_x, badge_y, badge_w, badge_h, 12, 12)
    
    painter.setFont(QFont(font_fam, int(badge_h * 0.55), QFont.Bold))
    painter.setPen(QColor("white"))
    painter.drawText(badge_x, badge_y, badge_w, badge_h, Qt.AlignCenter, "FULL STORY")

    painter.end()
    img.save(out_path, "JPEG", 95)
    if os.path.exists(bg_path): os.remove(bg_path)

# =====================================================================
# AI TRANSLATION TIMELINE 
# =====================================================================
def build_complete_timeline(segments_data, total_duration, max_dur=15.0, max_gap=3.5):
    if not segments_data: return [{"start": 0.0, "end": total_duration, "text": "", "is_speech": False}]
    merged_speech = []
    curr_text = ""
    curr_start = float(segments_data[0]["start"])
    curr_end = float(segments_data[0]["end"])

    for i in range(1, len(segments_data)):
        seg = segments_data[i]
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        seg_text = seg["text"].strip()
        gap = seg_start - curr_end
        if gap > max_gap or (seg_end - curr_start) > max_dur:
            merged_speech.append({"start": curr_start, "end": curr_end, "text": curr_text or segments_data[i-1]["text"].strip(), "is_speech": True})
            curr_start = seg_start
            curr_end = seg_end
            curr_text = seg_text
        else:
            curr_text = (curr_text + " " + seg_text).strip() if curr_text else seg_text
            curr_end = seg_end
    merged_speech.append({"start": curr_start, "end": curr_end, "text": curr_text, "is_speech": True})
    full_timeline = []
    current_time = 0.0
    for seg in merged_speech:
        if seg["start"] > current_time + 0.1:
            full_timeline.append({"start": current_time, "end": seg["start"], "text": "", "is_speech": False})
        full_timeline.append(seg)
        current_time = seg["end"]
    if current_time < total_duration - 0.1:
        full_timeline.append({"start": current_time, "end": total_duration, "text": "", "is_speech": False})
    return full_timeline

# =====================================================================
# SMART GEMINI KEY POOL & DYNAMIC MODEL SELECTION
# =====================================================================
# Global cooldown registry to avoid collisions between concurrent users/sessions.
_GLOBAL_GEMINI_COOLDOWNS = {}
_GLOBAL_COOLDOWN_LOCK = threading.Lock()

class GeminiKeyPool:
    def __init__(self, primary_keys_str, fallback_keys_str=""):
        self.primary_keys = [k.strip() for k in re.split(r'[, ]+', str(primary_keys_str)) if k.strip()]
        self.fallback_keys = [k.strip() for k in re.split(r'[, ]+', str(fallback_keys_str)) if k.strip()]
        
        self.all_keys = self.primary_keys + self.fallback_keys
        if not self.all_keys: self.all_keys = ["NO_KEY_PROVIDED"]
        
        self.primary_pool = itertools.cycle(self.primary_keys) if self.primary_keys else None
        self.fallback_pool = itertools.cycle(self.fallback_keys) if self.fallback_keys else None
        
        self.cooldowns = _GLOBAL_GEMINI_COOLDOWNS
        self.last_error = None

    def _get_available(self, keys):
        now = time.time()
        return [k for k in keys if self.cooldowns.get(k, 0) <= now]

    def get_key(self):
        # 1. Try Primary Keys (UI Keys) first
        if self.primary_keys:
            avail_primary = [k for k in self.primary_keys if self.cooldowns.get(k, 0) <= time.time()]
            if avail_primary:
                for _ in range(len(self.primary_keys)):
                    k = next(self.primary_pool)
                    if k in avail_primary: return k
                return avail_primary[0]
        
        # 2. If no Primary keys are available, try Fallback Keys (Secrets)
        if self.fallback_keys:
            avail_fallback = [k for k in self.fallback_keys if self.cooldowns.get(k, 0) <= time.time()]
            if avail_fallback:
                for _ in range(len(self.fallback_keys)):
                    k = next(self.fallback_pool)
                    if k in avail_fallback: return k
                return avail_fallback[0]
        
        # 3. If everything is cooling down, return the one with the shortest remaining cooldown
        return min(self.all_keys, key=lambda k: self.cooldowns.get(k, 0))

    def mark_rate_limited(self, key, cooldown_seconds=45, reason=None):
        with _GLOBAL_COOLDOWN_LOCK:
            self.cooldowns[key] = time.time() + cooldown_seconds
        if reason: self.last_error = reason

    def mark_error(self, key, cooldown_seconds=8, reason=None):
        with _GLOBAL_COOLDOWN_LOCK:
            self.cooldowns[key] = time.time() + cooldown_seconds
        if reason: self.last_error = reason

    def mark_success(self, key):
        with _GLOBAL_COOLDOWN_LOCK:
            self.cooldowns.pop(key, None)

    def all_cooling_down(self):
        now = time.time()
        return all(self.cooldowns.get(k, 0) > now for k in self.all_keys)

    def seconds_until_next_available(self):
        now = time.time()
        remaining = [self.cooldowns.get(k, 0) - now for k in self.all_keys]
        return max(0.5, min(remaining)) if remaining else 0.5

    def get_status(self):
        """Return a list of status dicts for the UI to display."""
        now = time.time()
        status = []
        for k in self.all_keys:
            cd = self.cooldowns.get(k, 0)
            is_active = cd <= now
            remaining = max(0, cd - now)
            tier = "UI (Primary)" if k in self.primary_keys else "Secrets (Fallback)"
            status.append({
                "Key": k[:6] + "..." + k[-4:] if len(k) > 10 else "****",
                "Tier": tier,
                "Status": "✅ Active" if is_active else "⏳ Cooling Down",
                "Cooldown": f"{int(remaining)}s" if remaining > 0 else "-"
            })
        return status

def invalidate_model_cache(api_key):
    VALID_MODELS_CACHE.pop(api_key, None)

def reset_global_cooldowns():
    """Emergency reset of all key cooldowns."""
    with _GLOBAL_COOLDOWN_LOCK:
        _GLOBAL_GEMINI_COOLDOWNS.clear()
    logging.info("🚨 Emergency Reset: Global cooldowns cleared.")

async def get_working_gemini_url(api_key):
    if api_key in VALID_MODELS_CACHE:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{VALID_MODELS_CACHE[api_key]}:generateContent?key={api_key}"
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(list_url)
            if res.status_code == 200:
                models_data = res.json().get('models', [])
                available_models = [m['name'].replace('models/', '') for m in models_data if 'generateContent' in m.get('supportedGenerationMethods', [])]
                flash_models = [m for m in available_models if 'flash' in m.lower() and 'preview' not in m.lower() and 'exp' not in m.lower()]
                if not flash_models: flash_models = [m for m in available_models if 'flash' in m.lower()]
                if flash_models:
                    selected_model = sorted(flash_models, reverse=True)[0]
                    VALID_MODELS_CACHE[api_key] = selected_model
                    logging.info(f"✅ Auto-detected working model: {selected_model}")
                    return f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={api_key}"
                elif available_models:
                    selected_model = available_models[0]
                    VALID_MODELS_CACHE[api_key] = selected_model
                    return f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={api_key}"
    except Exception as e:
        logging.error(f"Failed to fetch model list dynamically: {e}")

    fallback_candidates = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.5-flash-lite", "gemini-3.6-flash"]
    test_prompt = {"contents": [{"parts": [{"text": "hi"}]}]}

    async with httpx.AsyncClient(timeout=10.0) as client:
        for model in fallback_candidates:
            test_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                res = await client.post(test_url, json=test_prompt)
                if res.status_code == 200:
                    VALID_MODELS_CACHE[api_key] = model
                    return test_url
            except Exception: continue

    VALID_MODELS_CACHE[api_key] = "gemini-2.5-flash"
    return f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

async def generate_title_hook_hashtags(story_text, gemini_pool):
    prompt = f"""
    [SYSTEM INSTRUCTION: You are a viral Content Creator. You are STRICTLY FORBIDDEN from using the words "ဇာတ်လမ်း" (Story) or "ရုပ်ရှင်" (Movie) in titles or thumbnail text.]
    Based on this movie recap summary, generate:
    1. CAPTION: A short, engaging social media summary (2 sentences).
    2. VIDEO_TITLE: A viral, punchy title. !!! STRICTLY FORBIDDEN: Do NOT use "ဇာတ်လမ်း" or "ရုပ်ရှင်" !!!
    3. HASHTAGS: Exactly 3 trending and highly effective hashtags.
    4. THUMBNAIL_TITLE: An extreme click-worthy title (MAX 4-5 words). !!! STRICTLY FORBIDDEN: Do NOT use "ဇာတ်လမ်း" or "ရုပ်ရှင်" !!!
    
    Story Summary:
    {story_text[:2500]}
    
    Output JSON format:
    {{
        "caption": "စိတ်ဝင်စားစရာကောင်းသော အကျဉ်းချုပ်",
        "video_title": "ဆွဲဆောင်မှုရှိသော ခေါင်းစဉ် (ဇာတ်လမ်း/ရုပ်ရှင် လုံးဝမပါရ)",
        "hashtags": "#Hashtag1 #Hashtag2 #Hashtag3",
        "thumbnail_title": "အလွန်တိုတောင်းသော Thumbnail စာသား"
    }}
    """
    attempts = len(gemini_pool.all_keys) * 3
    for _ in range(attempts):
        if gemini_pool.all_cooling_down():
            wait_s = gemini_pool.seconds_until_next_available()
            if wait_s > 90: continue
            await asyncio.sleep(wait_s)
        current_key = gemini_pool.get_key()
        url = await get_working_gemini_url(current_key)
        try:
            with httpx.Client(timeout=20.0) as client:
                res = client.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, headers={"Content-Type": "application/json"})
                if res.status_code == 200:
                    gemini_pool.mark_success(current_key)
                    raw = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    raw = re.sub(r'```json|```', '', raw).strip()
                    data = json.loads(raw)
                    cap = data.get("caption", "ဒီအဖြစ်အပျက်က သင့်ကို အံ့သြသွားစေပါလိမ့်မယ်။")
                    v_title = data.get("video_title", "🎬 စိတ်ဝင်စားဖွယ် အကျဉ်းချုပ်")
                    tags = data.get("hashtags", "#MovieRecap #Myanmar #AIStory")
                    t_title = data.get("thumbnail_title", v_title)
                    
                    # STRIKE TEAM: Force remove forbidden words from titles and hashtags
                    for forbidden in ["ဇာတ်လမ်း", "ရုပ်ရှင်"]:
                        v_title = v_title.replace(forbidden, "").replace("  ", " ").strip()
                        t_title = t_title.replace(forbidden, "").replace("  ", " ").strip()
                        tags = tags.replace(forbidden, "").replace("  ", " ").strip()
                    
                    return cap, v_title, tags, t_title
                elif res.status_code == 404:
                    invalidate_model_cache(current_key)
                    gemini_pool.mark_error(current_key, cooldown_seconds=2, reason=f"Model not found (404)")
                elif res.status_code == 429:
                    body_lower = res.text.lower()
                    if "per day" in body_lower or "perday" in body_lower or "daily" in body_lower:
                        gemini_pool.mark_rate_limited(current_key, cooldown_seconds=6*3600)
                    else: gemini_pool.mark_rate_limited(current_key, cooldown_seconds=45)
                else: gemini_pool.mark_error(current_key)
        except Exception:
            gemini_pool.mark_error(current_key)
            continue
    return "🎬 စိတ်ဝင်စားဖွယ် ရုပ်ရှင်အကျဉ်းချုပ်", "ဒီဇာတ်လမ်းလေးက သင့်ကို အံ့သြသွားစေပါလိမ့်မယ်။", "#MovieRecap #Myanmar #AIStory"

def _parse_rate_percent(rate_str):
    try: return float(str(rate_str).replace("%", "").replace("+", ""))
    except Exception: return 0.0

# =====================================================================
# CHUNK PROCESSING 
# =====================================================================
def process_single_chunk(args):
    idx, start_time, end_time, input_video, chunk_audio_path, is_speech, text, p_form, p_res, bypass_enabled, work_dir = args
    work_dir = ensure_work_dir(work_dir)
    chunk_video_path = os.path.join(work_dir, f"chunk_vid_{idx}_{int(time.time() * 1000)}.mp4")
    try:
        audio_dur = get_media_duration(chunk_audio_path)
        vid_dur = max(end_time - start_time, 0.1)

        raw_ratio = audio_dur / vid_dur
        speed_ratio = max(min(raw_ratio, 3.0), 0.35)

        tpad_filter = "tpad=stop_mode=clone," 

        if bypass_enabled:
            zoom_shield = "crop=iw*0.96:ih*0.96:iw*0.02:ih*0.02,hflip," if idx % 2 != 0 else "crop=iw*0.98:ih*0.98:iw*0.01:ih*0.01,hflip,"
            color_edit = "eq=contrast=1.06:brightness=0.03:saturation=1.16,"
        else:
            zoom_shield = "crop=iw*0.94:ih*0.94:iw*0.03:ih*0.03," if idx % 2 != 0 else ""
            color_edit = "eq=contrast=1.04:brightness=0.01:saturation=1.12,"

        dim_w, dim_h = get_video_dimensions(p_form, p_res)
        
        scale_pad = f"scale={dim_w}:{dim_h}:force_original_aspect_ratio=decrease,pad={dim_w}:{dim_h}:-1:-1:color=black,"

        filter_str = (
            f"[0:v]trim=start={start_time}:end={end_time},setpts=PTS-STARTPTS,"
            f"setpts={speed_ratio:.4f}*PTS,"
            f"{tpad_filter}"
            f"{zoom_shield}"
            f"{color_edit}"
            f"{scale_pad.strip(',')}[v];"
            f"[1:a]aresample=44100,volume=1.6,apad[a]" 
        )

        sync_cmd = [
            'ffmpeg', '-y',
            '-i', input_video,
            '-i', chunk_audio_path,
            '-filter_complex', filter_str,
            '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'ultrafast', '-r', '30',
            '-c:a', 'aac', '-ar', '44100', '-ac', '2',
            '-t', f"{audio_dur:.3f}", 
            chunk_video_path
        ]
        run_ffmpeg(sync_cmd, label=f"chunk_{idx}_sync")
        actual_dur = get_media_duration(chunk_video_path)
        return (idx, chunk_video_path, actual_dur)
    except Exception as e:
        logging.error(f"process_single_chunk idx={idx} failed: {e}")
        if os.path.exists(chunk_video_path): os.remove(chunk_video_path)
        return (idx, None, 0.0)

# =====================================================================
# ADVANCED SYNC PIPELINE (EMBEDS TB AS INTRO COVER)
# =====================================================================
async def select_best_thumbnail_frame(video_path, gemini_pool, work_dir, w=1080, h=1920):
    """Use Gemini to pick the most engaging frame from 5 candidates."""
    try:
        duration = get_media_duration(video_path)
        candidates = [0.1, 0.3, 0.5, 0.7, 0.9]
        frame_paths = []
        
        # Extract 5 small frames for Gemini to look at
        for i, p in enumerate(candidates):
            fpath = os.path.join(work_dir, f"candidate_frame_{i}.jpg")
            extract_preview_frame(video_path, fpath, 512, 512, percent=p) # Small size for speed
            if os.path.exists(fpath):
                frame_paths.append((i, fpath, p))

        if not frame_paths: return 0.5 # Fallback to middle

        # Prepare images for Gemini
        parts = [{"text": "You are a Movie Marketing Expert. Look at these 5 frames from a movie and pick the ONE that is most visually striking and engaging for a YouTube/TikTok thumbnail. Reply ONLY with the index number (0, 1, 2, 3, or 4)."}]
        for i, fpath, _ in frame_paths:
            with open(fpath, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": img_data}})

        current_key = gemini_pool.get_key()
        url = await get_working_gemini_url(current_key)
        
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(url, json={"contents": [{"parts": parts}]})
            if res.status_code == 200:
                raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                match = re.search(r'(\d)', raw_text)
                if match:
                    idx = int(match.group(1))
                    if 0 <= idx < len(frame_paths):
                        return frame_paths[idx][2]
    except Exception as e:
        logging.error(f"Gemini frame selection failed: {e}")
    return 0.5 # Fallback to middle

async def advanced_sync_pipeline(audio_path, gemini_keys_str, groq_key, input_video, output_video_path, voice_config, user_speed_val, user_id, progress_cb=None, background_music_path=None, background_music_volume=0.0, work_dir=None, fallback_gemini_keys_str=""):
    work_dir = ensure_work_dir(work_dir)
    clean_groq_key = str(groq_key).strip()
    gemini_pool = GeminiKeyPool(gemini_keys_str, fallback_gemini_keys_str)
    total_video_duration = get_media_duration(input_video)

    sub_enabled = user_sub_mode.get(user_id, False)
    p_form = user_platform.get(user_id, "yt")
    p_res = user_res.get(user_id, "720")
    bypass_enabled = user_bypass_mode.get(user_id, False)
    selected_font_fam = get_user_font_family(user_id)

    if progress_cb:
        await progress_cb("🎧 အဆင့် ၁/၇ — အသံဖိုင်ကို စစ်ဆေးပြီး စကားပြောစာသား ခွဲထုတ်နေပါသည်...")
    try:
        with open(audio_path, "rb") as f:
            files = {"file": (os.path.basename(audio_path), f.read(), "audio/mp3")}
            data = {"model": "whisper-large-v3", "response_format": "verbose_json"}
            headers = {"Authorization": f"Bearer {clean_groq_key}"}
            with httpx.Client(timeout=120.0) as client:
                res = client.post("https://api.groq.com/openai/v1/audio/transcriptions", headers=headers, data=data, files=files)
                if res.status_code != 200: raise Exception(f"Groq Error: {res.text}")
                raw_segments = res.json().get("segments", [])
    except Exception as e: raise Exception(f"Groq Transcription Error: {str(e)}")

    if not raw_segments: raise Exception("ဗီဒီယိုထဲတွင် ရှင်းလင်းသည့် စကားပြောသံ (Speech) မတွေ့ပါ။ (Groq Error)")

    timeline_data = build_complete_timeline(raw_segments, total_video_duration, max_dur=15.0, max_gap=3.5)
    if progress_cb:
        await progress_cb(f"📝 အဆင့် ၂/၇ — စာသား {len(timeline_data)} ပိုင်း ခွဲပြီး Gemini ဘာသာပြန်ရန် ပြင်ဆင်နေပါသည်...")
    translated_dict = {}
    speech_indices = [idx for idx, seg in enumerate(timeline_data) if seg["is_speech"]]
    batch_size = 10
    full_translated_text = ""
    gender_rule = "မိန်းကလေး narrator အသံ (Female Voiceover) ဖြင့် ဖတ်မည်ဖြစ်ပါသည်။" if voice_config.get("gender") == "female" else "ယောက်ျားလေး narrator အသံ (Male Voiceover) ဖြင့် ဖတ်မည်ဖြစ်ပါသည်။"

    for i in range(0, len(speech_indices), batch_size):
        if progress_cb:
            batch_no = (i // batch_size) + 1
            total_batches = (len(speech_indices) + batch_size - 1) // batch_size
            await progress_cb(f"🧠 အဆင့် ၃/၇ — Gemini ဖြင့် ဘာသာပြန်နေပါသည်... ({batch_no}/{total_batches})")
        chunk_indices = speech_indices[i:i+batch_size]
        original_segments_text = ""
        for idx in chunk_indices:
            original_segments_text += f"[{idx}] {timeline_data[idx]['text'].strip()}\n"

            prompt = f"""
    [SYSTEM INSTRUCTION: You are a fast, highly accurate Audio-to-Burmese Translator. Ignore background noise. Translate the text directly into smooth and natural Burmese. Do NOT add extra words, explanations, or expansions that are not in the original text.]
    
    [Recap အတွက် ဘာသာပြန်]
    အောက်ပါ နံပါတ်စဉ်တပ်ထားသော မူရင်းစာတန်းထိုးများကို AI Voiceover ဖြင့် အသံပြန်သွင်းရန် မြန်မာလို အချောမွေ့ဆုံး ဘာသာပြန်ပေးပါ။
    
    "{original_segments_text}"
    
    စည်းကမ်းချက်များ-
    ၁။ စာအုပ်သုံး (သည်၊ ၏) မသုံးဘဲ ရုပ်ရှင် Recap narrator တစ်ယောက်လို ပြေပြေပြစ်ပြစ် ပြောပြသလို စကားပြောဟန်ဖြင့် ဘာသာပြန်ပါ။
    ၂။ {gender_rule}
       ⚠️ "ဗျာ"၊ "ပေါ့ဗျာ"၊ "ရှင့်"၊ "လေ" ကဲ့သို့ sentence-ending particle များကို ၁၀ ကြောင်းလျှင် ၁ ကြောင်းထက် ပို၍ လုံးဝ မသုံးပါနှင့်။
    ၃။ မြန်မာလို အသံထွက် (Transliterate) အတိုင်းသာ ရေးပါ။ အင်္ဂလိပ်စာလုံး လုံးဝမပါစေရ။
    ၄။ စကားပြောများကိုသာ တိုက်ရိုက်ဘာသာပြန်ပါ။ မူရင်းစာသားတွင် မပါသော အပိုစကားလုံးများ၊ ချဲ့ထွင်ပြောဆိုချက်များနှင့် ရှင်းလင်းချက်များကို လုံးဝ (လုံးဝ) ထည့်မရေးပါနှင့်။
    ၅။ ⚠️ မူလစာကြောင်းများ၏ နံပါတ်စဉ်များ (ဥပမာ - [0], [1]) ကို မပျောက်စေဘဲ အတိအကျ ပြန်ထည့်ပေးပါ။ တစ်ကြောင်းမှ မကျန်စေရပါ။
    ၆။ (အရေးကြီးသည်) စာကြောင်းတစ်ကြောင်းလျှင် စကားလုံး ၁၅ လုံးမှ ၂၀ လုံးထက် မပိုစေရ။ (မြန်မာစာလုံးများကို Space ခြား၍ ရေးပေးပါ)
    """
        success = False
        max_retries = max(len(gemini_pool.all_keys) * 3, 6)

        for attempt in range(max_retries):
            if gemini_pool.all_cooling_down():
                wait_s = gemini_pool.seconds_until_next_available()
                if wait_s > 90: continue
                await asyncio.sleep(wait_s)
            current_key = gemini_pool.get_key()
            gemini_url = await get_working_gemini_url(current_key)
            try:
                with httpx.Client(timeout=30.0) as client:
                    res = client.post(gemini_url, json={"contents": [{"parts": [{"text": prompt}]}]}, headers={"Content-Type": "application/json"})
                    if res.status_code == 200:
                        gemini_pool.mark_success(current_key)
                        translated_raw = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                        matches = re.findall(r'\[\s*(\d+)\s*\][:\-\s]*([^\[]*)', translated_raw)
                        for m in matches:
                            translated_dict[int(m[0])] = m[1].strip()
                            full_translated_text += " " + m[1].strip()
                        success = True
                        break
                    elif res.status_code == 404:
                        invalidate_model_cache(current_key)
                        gemini_pool.mark_error(current_key, cooldown_seconds=2)
                    elif res.status_code == 429:
                        body_lower = res.text.lower()
                        if "per day" in body_lower or "perday" in body_lower or "daily" in body_lower:
                            gemini_pool.mark_rate_limited(current_key, cooldown_seconds=6*3600)
                        else: gemini_pool.mark_rate_limited(current_key, cooldown_seconds=45)
                    else: gemini_pool.mark_error(current_key)
            except Exception:
                gemini_pool.mark_error(current_key)
                continue

        if not success: raise Exception(f"Gemini API မအောင်မြင်ပါ။ Rate Limit ပြည့်နေနိုင်ပါသည်။")
        if len(speech_indices) > batch_size: time.sleep(0.6)

    if progress_cb:
        await progress_cb("🎙️ အဆင့် ၄/၇ — မြန်မာအသံဖိုင်များကို ထုတ်လုပ်နေပါသည်...")
    story_caption, story_title, story_hashtags, thumbnail_title = await generate_title_hook_hashtags(full_translated_text, gemini_pool)
    audio_files_map = {}
    tts_semaphore = asyncio.Semaphore(TTS_WORKERS)
    selected_rate = voice_config.get("rate", "+15%")

    async def generate_audio_chunk(idx, seg):
        path = os.path.join(work_dir, f"chunk_audio_{idx}_{int(time.time() * 1000)}.mp3")
        expected_duration = seg["end"] - seg["start"]

        if not seg["is_speech"] or idx not in translated_dict or not translated_dict[idx].strip():
            create_silent_audio(expected_duration, path)
            audio_files_map[idx] = path
            return

        clean_text = re.sub(r'[\[\]{}()<>~*#_]', '', translated_dict[idx]).strip()
        if len(clean_text) < 2:
            create_silent_audio(expected_duration, path)
            audio_files_map[idx] = path
            return

        max_tts_retries = 3
        async with tts_semaphore:
            rendered = False
            for attempt in range(max_tts_retries):
                try:
                    comm = edge_tts.Communicate(text=clean_text, voice=voice_config["voice"], rate=selected_rate, pitch=voice_config["pitch"])
                    await comm.save(path)
                    if os.path.exists(path) and os.path.getsize(path) > 500:
                        rendered = True
                        break
                except Exception: await asyncio.sleep(1.0)

            if not rendered:
                create_silent_audio(expected_duration, path)
                audio_files_map[idx] = path
                return

            audio_files_map[idx] = path

    audio_tasks = [generate_audio_chunk(idx, seg) for idx, seg in enumerate(timeline_data)]
    if audio_tasks: await asyncio.gather(*audio_tasks)
    if progress_cb:
        await progress_cb("🎬 အဆင့် ၅/၇ — အသံနှင့် ဗီဒီယိုကို sync လုပ်ပြီး render ပြုလုပ်နေပါသည်...")
    ffmpeg_args = []
    for idx, seg in enumerate(timeline_data):
        if idx in audio_files_map:
            translated_text = translated_dict.get(idx, "")
            ffmpeg_args.append((idx, float(seg["start"]), float(seg["end"]), input_video, audio_files_map[idx], seg["is_speech"], translated_text, p_form, p_res, bypass_enabled, work_dir))

    with ThreadPoolExecutor(max_workers=CHUNK_WORKERS) as executor:
        chunk_results = list(executor.map(process_single_chunk, ffmpeg_args))
    chunk_results.sort(key=lambda x: x[0])
    ffmpeg_inputs = [res[1] for res in chunk_results if res[1] is not None]
    chunk_durations = {res[0]: res[2] for res in chunk_results if res[1] is not None}

    if not ffmpeg_inputs: raise Exception("ဗီဒီယို Timeline ချိန်ညှိမှု မအောင်မြင်ပါ။")

    concat_list_path = os.path.join(work_dir, f"list_{int(time.time() * 1000)}.txt")
    with open(concat_list_path, "w", encoding="utf-8") as f_list:
        for vid in ffmpeg_inputs: f_list.write(f"file '{os.path.abspath(vid)}'\n")

    merge_temp = os.path.join(work_dir, f"merge_temp_{int(time.time() * 1000)}.mp4")
    run_ffmpeg(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list_path, '-c', 'copy', merge_temp], label="concat_merge")

    dim_w, dim_h = get_video_dimensions(p_form, p_res)
    sub_segments = []
    cursor = 0.0
    for idx, seg in enumerate(timeline_data):
        if idx not in chunk_durations: continue
        dur = chunk_durations[idx]
        seg_text = translated_dict.get(idx, "").strip()
        
        if sub_enabled and seg["is_speech"] and seg_text:
            split_segs = split_burmese_text_chronologically(seg_text, cursor, cursor + dur, max_chars=45)
            sub_segments.extend(split_segs)
        cursor += dur
    total_final_duration = cursor

    sub_y_percent = user_sub_y.get(user_id, 82)
    sub_font_size = user_sub_size.get(user_id, 35)
    sub_color = user_sub_color.get(user_id, "yellow")
    job_dir = os.path.join(work_dir, f"subjob_{user_id}_{int(time.time() * 1000)}")
    os.makedirs(job_dir, exist_ok=True)
    subs_concat_path = None
    if sub_segments:
        subs_json_path = os.path.join(job_dir, "subs.json")
        with open(subs_json_path, "w", encoding="utf-8") as f:
            json.dump(sub_segments, f, ensure_ascii=False)
        subs_concat_path = generate_subtitle_overlay_filter(subs_json_path, total_final_duration, job_dir, TW=dim_w, TH=dim_h, sub_y_percent=sub_y_percent, sub_color=sub_color, font_fam=selected_font_fam, sub_font_size=sub_font_size)

    title_path = None
    if user_title_mode.get(user_id, True) and story_title and story_title.strip():
        title_path = os.path.join(job_dir, f"title_{user_id}.png")
        title_size = max(18, min(int(user_title_size.get(user_id, 30)), 64))
        title_width = max(25, min(float(user_title_width.get(user_id, 65)), 100.0))
        title_img = create_text_image_full(
            text=story_title.strip(), font_size=title_size, text_color="#00E5FF", outline_color="black", outline_width=max(2, int(title_size * 0.12)),
            use_box=False, box_color="black", box_alpha="0.0", box_border=0,
            width=dim_w, height=dim_h, align="top", margin_v=dim_h * 0.08, font_family=selected_font_fam, is_title=True,
            max_width_percent=title_width
        )
        title_img.save(title_path, "PNG")

    blur_y_percent = user_blur_y.get(user_id, 82)
    blur_strength = user_blur_strength.get(user_id, 5)
    blur_height = user_blur_height.get(user_id, 12)
    blur_width = user_blur_width.get(user_id, 100)
    blur_filter_str = ""
    cur_label = "[0:v]"
    if user_blur_mode.get(user_id, False):
        blur_filter_str, cur_label = get_blur_mask_filter("[0:v]", y_position_percent=blur_y_percent, blur_strength=blur_strength, blur_height_percent=blur_height, blur_width_percent=blur_width)

    wm_text = user_wm_text.get(user_id, "Recap")
    wm_pos = user_wm_pos.get(user_id, "bounce")

    if wm_pos == "topleft": wm_filter = f"drawtext=text='{wm_text}':fontcolor=white@0.8:fontsize=36:x=20:y=20:box=1:boxcolor=black@0.4:boxborderw=5"
    elif wm_pos == "topright": wm_filter = f"drawtext=text='{wm_text}':fontcolor=white@0.8:fontsize=36:x=w-tw-20:y=20:box=1:boxcolor=black@0.4:boxborderw=5"
    elif wm_pos == "bottom": wm_filter = f"drawtext=text='{wm_text}':fontcolor=white@0.8:fontsize=36:x=(w-tw)/2:y=h-th-20:box=1:boxcolor=black@0.4:boxborderw=5"
    else: wm_filter = f"drawtext=text='{wm_text}':fontcolor=white@0.4:fontsize=36:x='20+(w-tw-40)*(0.5+0.5*sin(t/2.5))':y='20+(h-th-40)*(0.5+0.5*cos(t/3.5))':box=1:boxcolor=black@0.15:boxborderw=5"

    watermarked_temp = os.path.join(work_dir, f"watermarked_{int(time.time() * 1000)}.mp4")
    user_logo_path = os.path.join(work_dir, f"logo_{user_id}.png")

    inputs = ['-i', merge_temp]
    next_input_idx = 1
    subs_input_idx = None
    if subs_concat_path:
        inputs += ['-f', 'concat', '-safe', '0', '-i', subs_concat_path]
        subs_input_idx = next_input_idx
        next_input_idx += 1
    logo_input_idx = None
    if os.path.exists(user_logo_path):
        inputs += ['-i', user_logo_path]
        logo_input_idx = next_input_idx
        next_input_idx += 1
    title_input_idx = None
    if title_path and os.path.exists(title_path):
        inputs += ['-loop', '1', '-i', title_path]
        title_input_idx = next_input_idx
        next_input_idx += 1

    filter_parts = []
    if blur_filter_str:
        filter_parts.append(blur_filter_str)  

    if subs_input_idx is not None:
        filter_parts.append(f"{cur_label}[{subs_input_idx}:v]overlay=0:0[vid_with_subs]")
        cur_label = "[vid_with_subs]"

    if title_input_idx is not None:
        filter_parts.append(f"{cur_label}[{title_input_idx}:v]overlay=0:0[vid_with_title]")
        cur_label = "[vid_with_title]"

    filter_parts.append(f"{cur_label}{wm_filter}[vid_final]")
    cur_label = "[vid_final]"

    if logo_input_idx is not None:
        filter_parts.append(f"[{logo_input_idx}:v]scale=-1:80[logo]")
        filter_parts.append(f"{cur_label}[logo]overlay=W-w-20:20[vout]")
        cur_label = "[vout]"

    filter_complex = ";".join(filter_parts)
    extra_flags = ['-map_metadata', '-1', '-fflags', '+bitexact'] if bypass_enabled else []
    
    if progress_cb:
        await progress_cb("📝 အဆင့် ၆/၇ — Subtitle၊ watermark၊ title နှင့် video effects ထည့်နေပါသည်...")
    run_ffmpeg(
        ['ffmpeg', '-y'] + inputs + [
            '-filter_complex', filter_complex,
            '-map', cur_label, '-map', '0:a', '-shortest',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'ultrafast', '-c:a', 'copy'
        ] + extra_flags + [watermarked_temp], label="blur_subtitle_watermark"
    )

    speed_multiplier = SPEED_MULTIPLIERS.get(user_speed_val, 1.0)
    if abs(speed_multiplier - 1.0) > 0.001:
        video_pts_factor = 1.0 / speed_multiplier
        speed_cmd = [
            'ffmpeg', '-y', '-i', watermarked_temp,
            '-filter_complex', f"[0:v]setpts={video_pts_factor:.4f}*PTS[v];[0:a]atempo={speed_multiplier:.3f}[a]",
            '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'ultrafast',
            '-c:a', 'aac', '-ar', '44100', '-ac', '2',
            output_video_path
        ]
        run_ffmpeg(speed_cmd, label="final_speed_adjust")
        if os.path.exists(watermarked_temp): os.remove(watermarked_temp)
    else: os.replace(watermarked_temp, output_video_path)

    if progress_cb:
        await progress_cb("🎵 အဆင့် ၇/၇ — Thumbnail နှင့် background music ထည့်ပြီး အပြီးသတ်နေပါသည်...")
    
    # Use Gemini to pick the best frame for the thumbnail
    best_frame_percent = await select_best_thumbnail_frame(input_video, gemini_pool, work_dir, w=dim_w, h=dim_h)
    
    # 📌 TB Thumbnail ကိုဖန်တီးပြီး Video အစမှာ Cover အဖြစ် တွဲထည့်ခြင်း
    tb_img_path = os.path.join(work_dir, f"tb_embed_{int(time.time() * 1000)}.jpg")
    create_thumbnail(input_video, thumbnail_title, tb_img_path, font_fam=selected_font_fam, w=dim_w, h=dim_h, work_dir=work_dir, best_percent=best_frame_percent)
    
    tb_vid = os.path.join(work_dir, f"tb_vid_{int(time.time() * 1000)}.mp4")
    tb_audio = os.path.join(work_dir, f"tb_audio_{int(time.time() * 1000)}.mp3")
    create_silent_audio(1.0, tb_audio)
    
    cmd_tb = [
        'ffmpeg', '-y', '-loop', '1', '-t', '1.0', '-i', tb_img_path,
        '-i', tb_audio,
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'ultrafast', '-r', '30',
        '-c:a', 'aac', '-ar', '44100', '-ac', '2',
        tb_vid
    ]
    run_ffmpeg(cmd_tb, "create_tb_vid")
    
    concat_txt = os.path.join(work_dir, f"final_concat_{int(time.time() * 1000)}.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        f.write(f"file '{os.path.abspath(tb_vid)}'\n") 
        f.write(f"file '{os.path.abspath(output_video_path)}'\n")
        
    final_merged = os.path.join(work_dir, f"final_merged_{int(time.time() * 1000)}.mp4")
    run_ffmpeg(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_txt, '-c', 'copy', final_merged], "final_tb_concat")
    
    os.replace(final_merged, output_video_path)

    # 📌 Optional Background Music Mixing (BGM)
    # The web UI passes an explicit uploaded path; never scan the working
    # directory because that could accidentally mix the source/voice audio.
    if background_music_path and os.path.exists(background_music_path) and float(background_music_volume) > 0:
        bgm_mixed = os.path.join(work_dir, f"bgm_mixed_{int(time.time() * 1000)}.mp4")
        volume = max(0.0, min(float(background_music_volume), 1.0))
        cmd_bgm = [
            'ffmpeg', '-y', '-i', output_video_path,
            '-stream_loop', '-1', '-i', background_music_path,
            '-filter_complex', f'[1:a]volume={volume:.3f}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]',
            '-map', '0:v', '-map', '[a]',
            '-c:v', 'copy', '-c:a', 'aac', '-ar', '44100', '-ac', '2',
            '-shortest', bgm_mixed
        ]
        try:
            run_ffmpeg(cmd_bgm, "mix_background_music")
            if os.path.exists(bgm_mixed):
                os.replace(bgm_mixed, output_video_path)
        except Exception as e:
            logging.error(f"BGM Mixing failed: {e}")
    
    if os.path.exists(tb_vid): os.remove(tb_vid)
    if os.path.exists(tb_audio): os.remove(tb_audio)
    if os.path.exists(concat_txt): os.remove(concat_txt)

    for f in list(audio_files_map.values()) + ffmpeg_inputs + [merge_temp]:
        if os.path.exists(f): os.remove(f)
    if os.path.exists(concat_list_path): os.remove(concat_list_path)
    if os.path.isdir(job_dir):
        import shutil
        shutil.rmtree(job_dir, ignore_errors=True)

    return story_title, story_hook, story_hashtags, tb_img_path

# =====================================================================
# TELEGRAM BOT ARCHITECTURE (WITH MEMORY SESSION)
# =====================================================================
class _NoTelegramBot:
    def on(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator

    async def start(self, *args, **kwargs):
        raise RuntimeError("Telegram mode is disabled in the Streamlit web app.")

    async def run_until_disconnected(self):
        raise RuntimeError("Telegram mode is disabled in the Streamlit web app.")

bot = TelegramClient(MemorySession(), API_ID, API_HASH) if API_ID and API_HASH else _NoTelegramBot()

@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    user_id = event.sender_id
    sender = await event.get_sender()
    sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', '') or f"User_{user_id}"

    if user_id not in user_stats:
        user_stats[user_id] = {"name": sender_name, "count": 0, "last_active": time.strftime("%Y-%m-%d %H:%M:%S")}
    if user_id not in user_voices: user_voices[user_id] = "v1"
    if user_id not in user_speeds: user_speeds[user_id] = "1.1x"
    if user_id not in user_platform: user_platform[user_id] = "yt"
    if user_id not in user_res: user_res[user_id] = "720"
    if user_id not in user_font: user_font[user_id] = DEFAULT_FONT_FILE

    await event.respond(
        "🎬 **AI Movie Recap Bot (Ultimate Edition)**\n\n"
        "✨ အသံ (၂၄) မျိုး၊ Speed၊ Custom Watermark၊ Auto Blur Mask နှင့်\n"
        "✨ TikTok/YT Sizes၊ 720p/1080p Resolutions၊ မြန်မာစာတန်းထိုး (တစ်ကြောင်းတည်း) အစုံအလင် ပါဝင်ပါသည်။\n\n"
        "👇 အောက်ပါ Menu များမှတဆင့် စိတ်ကြိုက် ပြင်ဆင်နိုင်ပါသည်-",
        buttons=MAIN_MENU_BUTTONS
    )

@bot.on(events.CallbackQuery(pattern=b"menu_size"))
async def menu_size(event):
    buttons = [
        [Button.inline("📱 TikTok/Reels (9:16)", b"set_size_tt")],
        [Button.inline("🖥️ YouTube (16:9)", b"set_size_yt")],
        [Button.inline("🔲 Facebook (1:1)", b"set_size_fb")],
        [Button.inline("🔙 နောက်သို့", b"menu_back")]
    ]
    try: await event.edit("📱 ဗီဒီယိုထွက်ရှိမည့် Format Size ကို ရွေးချယ်ပါ-", buttons=buttons)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=r"set_size_"))
async def set_size(event):
    user_platform[event.sender_id] = event.data.decode('utf-8').split("_")[2]
    try: await event.edit(f"✅ Video Size ကို ပြောင်းလဲလိုက်ပါပြီ။", buttons=MAIN_MENU_BUTTONS)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_res"))
async def menu_res(event):
    buttons = [
        [Button.inline("HD 720p (Default)", b"set_res_720")],
        [Button.inline("FHD 1080p (High Quality)", b"set_res_1080")],
        [Button.inline("🔙 နောက်သို့", b"menu_back")]
    ]
    try: await event.edit("📺 ဗီဒီယို Resolution ကို ရွေးချယ်ပါ-", buttons=buttons)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=r"set_res_"))
async def set_res(event):
    user_res[event.sender_id] = event.data.decode('utf-8').split("_")[2]
    try: await event.edit(f"✅ Resolution ကို ပြောင်းလဲလိုက်ပါပြီ။", buttons=MAIN_MENU_BUTTONS)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_voice"))
async def menu_voice(event):
    buttons = []
    row = []
    for k, v in VOICE_MODES.items():
        row.append(Button.inline(v["name"], f"set_v_{k}".encode('utf-8')))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    buttons.append([Button.inline("🔙 နောက်သို့", b"menu_back")])
    try: await event.edit("👇 အသံပုံစံ (၂၄) မျိုး ကို ရွေးချယ်ပေးပါ-", buttons=buttons)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=r"set_v_"))
async def change_voice(event):
    voice_key = event.data.decode('utf-8').split("_")[2]
    user_voices[event.sender_id] = voice_key
    try: await event.edit(f"✅ အသံပုံစံ ပြောင်းလဲလိုက်ပါပြီ။", buttons=MAIN_MENU_BUTTONS)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_speed"))
async def menu_speed(event):
    buttons = [
        [Button.inline("1.0x (Normal)", b"set_speed_1.0x"), Button.inline("1.1x (Good)", b"set_speed_1.1x")],
        [Button.inline("1.2x (Fast)", b"set_speed_1.2x"), Button.inline("1.3x (Very Fast)", b"set_speed_1.3x")],
        [Button.inline("1.4x (Fastest)", b"set_speed_1.4x")],
        [Button.inline("🔙 နောက်သို့", b"menu_back")]
    ]
    try: await event.edit("⚡ **Audio Speed ရွေးချယ်ရန်**", buttons=buttons)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=r"set_speed_"))
async def change_speed(event):
    speed_val = event.data.decode('utf-8').split("_")[2]
    user_speeds[event.sender_id] = speed_val
    try: await event.edit(f"✅ အမြန်နှုန်း ပြောင်းလဲလိုက်ပါပြီ။", buttons=MAIN_MENU_BUTTONS)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_sub"))
async def toggle_sub(event):
    uid = event.sender_id
    user_sub_mode[uid] = not user_sub_mode.get(uid, False)
    status = "✅ ဖွင့်ထားသည်" if user_sub_mode[uid] else "❌ ပိတ်ထားသည်"
    try: await event.edit(f"📝 **စာတန်းထိုး:** {status}\n(၁၅-၂၀ လုံး အတိအကျ ညှိပေးထားသော စနစ်ဖြင့် ပေါ်ပေးပါမည်။)", buttons=MAIN_MENU_BUTTONS)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_blur"))
async def toggle_blur(event):
    uid = event.sender_id
    user_blur_mode[uid] = not user_blur_mode.get(uid, False)
    status = "✅ ဖွင့်ထားသည်" if user_blur_mode[uid] else "❌ ပိတ်ထားသည်"
    try:
        await event.edit(
            f"🌫️ **Auto Blur Mask:** {status}\n(ဖွင့်ထားပါက မူရင်း video အောက်ခြေရှိ စာတန်းဟောင်းများကို အလိုအလျောက် ဝါးဖျောက်ပေးပါမည်။)",
            buttons=MAIN_MENU_BUTTONS
        )
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_title"))
async def toggle_title(event):
    uid = event.sender_id
    user_title_mode[uid] = not user_title_mode.get(uid, True)
    status = "✅ ဖွင့်ထားသည်" if user_title_mode[uid] else "❌ ပိတ်ထားသည်"
    try:
        await event.edit(
            f"🏷️ **Video Title Overlay:** {status}\n(ဖွင့်ထားပါက AI ထုတ်ပေးတဲ့ Title ကို video ထိပ်မှာ တစ်ခါတည်း အမြဲကပ်ပြပေးပါမည်။)",
            buttons=MAIN_MENU_BUTTONS
        )
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_bypass"))
async def toggle_bypass(event):
    uid = event.sender_id
    user_bypass_mode[uid] = not user_bypass_mode.get(uid, False)
    status = "✅ ဖွင့်ထားသည်" if user_bypass_mode[uid] else "❌ ပိတ်ထားသည်"
    try:
        await event.edit(
            f"🛡️ **Edit Bypass (ဘယ်/ညာလှန်):** {status}\n"
            "(ဖွင့်ထားပါက ဗီဒီယို၏ Meta Data များဖျက်ခြင်း၊ အရောင်နှင့် Zoom ပြောင်းခြင်းအပြင် ဗီဒီယိုကို ဘယ်ညာလှန် (Horizontal Flip) ပါ အလိုအလျောက် လုပ်ဆောင်ပေးပါမည်။)",
            buttons=MAIN_MENU_BUTTONS
        )
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_subcolor"))
async def cycle_sub_color(event):
    uid = event.sender_id
    cur = user_sub_color.get(uid, "yellow")
    names = [c[0] for c in SUB_COLOR_CHOICES]
    try: idx = names.index(cur)
    except ValueError: idx = 0
    new_idx = (idx + 1) % len(names)
    user_sub_color[uid] = names[new_idx]
    label = SUB_COLOR_CHOICES[new_idx][1]
    try:
        await event.edit(f"🎨 **Subtitle Color:** {label}\n(နောက်ထပ် အရောင်ကြည့်ချင်ရင် ခလုတ်ကို ထပ်နှိပ်ပါ)", buttons=MAIN_MENU_BUTTONS)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_font"))
async def menu_font(event):
    buttons = []
    for f in AVAILABLE_FONTS:
        disp = os.path.basename(f)
        cb_data = f"set_font_{AVAILABLE_FONTS.index(f)}".encode('utf-8')
        buttons.append([Button.inline(f"🔤 {disp}", cb_data)])
    buttons.append([Button.inline("🔙 နောက်သို့", b"menu_back")])
    try: await event.edit("🔤 စာတန်းထိုးနှင့် Title အတွက် Font ရွေးချယ်ပါ-", buttons=buttons)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=r"set_font_"))
async def change_font(event):
    idx = int(event.data.decode('utf-8').split("_")[2])
    if 0 <= idx < len(AVAILABLE_FONTS):
        user_font[event.sender_id] = AVAILABLE_FONTS[idx]
    try: await event.edit(f"✅ Font ပြောင်းလဲလိုက်ပါပြီ။", buttons=MAIN_MENU_BUTTONS)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_wm_pos"))
async def menu_wm_pos(event):
    buttons = [
        [Button.inline("🔁 ပြေးနေသောစာသား (Bounce)", b"set_wm_pos_bounce")],
        [Button.inline("↖️ ဘယ်ဘက်အပေါ်", b"set_wm_pos_topleft"), Button.inline("↗️ ညာဘက်အပေါ်", b"set_wm_pos_topright")],
        [Button.inline("⬇️ အောက်ခြေအလယ်", b"set_wm_pos_bottom")],
        [Button.inline("🔙 နောက်သို့", b"menu_back")]
    ]
    try: await event.edit("💧 **Watermark နေရာ ရွေးချယ်ရန်**\n(စာသားပြောင်းလိုပါက `/setwm [စာသား]` ဟုရိုက်ထည့်ပါ)", buttons=buttons)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=r"set_wm_pos_"))
async def change_wm_pos(event):
    pos = event.data.decode('utf-8').replace("set_wm_pos_", "")
    user_wm_pos[event.sender_id] = pos
    try: await event.edit("✅ Watermark နေရာသတ်မှတ်မှု အောင်မြင်ပါပြီ။", buttons=MAIN_MENU_BUTTONS)
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_logo_help"))
async def menu_logo_help(event):
    msg = "🖼️ **ကိုယ်ပိုင် Logo (Watermark) ထည့်သွင်းနည်း**\n\nLogo ပုံကို ရွေးချယ်ပြီး **Caption တွင် `/setlogo` ဟု ရိုက်ထည့်ကာ** ပို့ပေးပါ။\n\nမှတ်ချက်: Logo ကို ပြန်ဖျက်လိုပါက `/removelogo` ဟု ရိုက်ထည့်ပါ။"
    try: await event.edit(msg, buttons=[[Button.inline("🔙 နောက်သို့", b"menu_back")]])
    except MessageNotModifiedError: pass

@bot.on(events.CallbackQuery(pattern=b"menu_back"))
async def menu_back(event):
    try: await event.edit("👇 စိတ်ကြိုက် ပြင်ဆင်ရန် အောက်ပါခလုတ်များကို အသုံးပြုပါ-", buttons=MAIN_MENU_BUTTONS)
    except MessageNotModifiedError: pass

@bot.on(events.NewMessage(pattern="/setwm"))
async def set_wm_text(event):
    text = event.text.replace("/setwm", "").strip()
    if text:
        user_wm_text[event.sender_id] = text
        await event.respond(f"✅ Watermark စာသားကို **{text}** သို့ ပြောင်းလဲလိုက်ပါပြီ။", buttons=MAIN_MENU_BUTTONS)

@bot.on(events.NewMessage(pattern="/setlogo"))
async def set_logo(event):
    if event.photo:
        await event.download_media(file=f"temp/logo_{event.sender_id}.png")
        await event.respond("✅ **Logo ပုံစံသစ်ကို အောင်မြင်စွာ မှတ်သားလိုက်ပါပြီ။**", buttons=MAIN_MENU_BUTTONS)
    else: await event.respond("⚠️ `/setlogo` ကို ပုံ (Photo) တစ်ပုံနှင့်အတူ Caption တွင်တွဲ၍ ပို့ပေးပါ။")

@bot.on(events.NewMessage(pattern="/removelogo"))
async def remove_logo(event):
    path = f"temp/logo_{event.sender_id}.png"
    if os.path.exists(path):
        os.remove(path)
        await event.respond("✅ ကိုယ်ပိုင် Logo ကို ပယ်ဖျက်လိုက်ပါပြီ။", buttons=MAIN_MENU_BUTTONS)
    else: await event.respond("⚠️ မှတ်သားထားသော Logo မရှိသေးပါ။")

# 📌 ADMIN ACCOUNT ထည့်သွင်းထားသည် 
@bot.on(events.NewMessage(pattern="/admin1999"))
async def admin_stats(event):
    sender = await event.get_sender()
    sender_username = getattr(sender, 'username', '') or ""
    if event.sender_id != ADMIN_ID:
        return
        
    if not user_stats:
        await event.respond("📊 လက်ရှိတွင် အသုံးပြုထားသော မှတ်တမ်း မရှိသေးပါ။")
        return
    total_users = len(user_stats)
    total_videos = sum(u["count"] for u in user_stats.values())
    msg = f"👑 **ADMIN DASHBOARD** 👑\n━━━━━━━━━━━━━━━━━━━━━━\n👥 စုစုပေါင်း အသုံးပြုသူ: **{total_users}** ဦး | 🎬 ထုတ်လုပ်မှု စုစုပေါင်း: **{total_videos}** ပုဒ်\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    sorted_stats = sorted(user_stats.items(), key=lambda x: x[1]["count"], reverse=True)
    for idx, (uid, data) in enumerate(sorted_stats[:30], 1):
        msg += f"**{idx}. {data['name']}** (ID: `{uid}`)\n   └ 🎬 ထုတ်လုပ်မှု: **{data['count']}** ပုဒ် | 🕒 နောက်ဆုံး: {data['last_active']}\n\n"
    await event.respond(msg)

@bot.on(events.NewMessage(pattern="/setkey"))
async def set_user_key(event):
    parts = event.text.split(maxsplit=2)
    if len(parts) < 3:
        await event.respond("⚠️ အသုံးပြုနည်း: `/setkey [AI_Key1,AI_Key2,...] [Groq_Key]`\n\nGemini key အများကြီးကို comma (,) ခံပြီး ထည့်ပေးလို့ရပါတယ်။")
        return
    gemini_keys_raw = [k.strip() for k in re.split(r'[, ]+', parts[1].strip()) if k.strip()]
    user_keys[event.sender_id] = {"gemini": parts[1].strip(), "groq": parts[2].strip()}

    for gk in gemini_keys_raw: VALID_MODELS_CACHE.pop(gk, None)

    bad_keys = [k for k in gemini_keys_raw if not k.startswith("AIzaSy")]
    msg = f"✅ API Keys Updated! (Gemini keys detected: {len(gemini_keys_raw)})"
    if bad_keys:
        preview = ", ".join(f"`{k[:8]}...`" for k in bad_keys[:3])
        msg += f"\n\n⚠️ **သတိပေးချက်**: Key {len(bad_keys)} ခု ({preview}) က Gemini key ပုံစံ (`AIzaSy...`) နဲ့ မတူပါ။ https://aistudio.google.com/apikey မှ ရယူထားသည့် Key ဟုတ်မဟုတ် စစ်ဆေးပါ။"
    await event.respond(msg)

@bot.on(events.NewMessage(pattern="/queue"))
async def queue_status(event):
    user_id = event.sender_id
    q = user_queues.get(user_id)
    pending = q.qsize() if q else 0
    active = user_queue_active.get(user_id, False)
    if active: await event.respond(f"🔁 လက်ရှိ Auto-Queue ဖြင့် ဆောင်ရွက်နေပါသည်။ တန်းစီနေသည့် အလုပ်: **{pending}** ခု")
    else: await event.respond("✅ လက်ရှိ Queue ထဲတွင် ဆောင်ရွက်နေသည့် အလုပ် မရှိပါ။")

# =====================================================================
# 🖼️ POSITION-CALIBRATION FLOW & AUTO-QUEUE WORKER
# =====================================================================
@bot.on(events.NewMessage)
async def handle_message(event):
    if event.text and event.text.startswith('/'): return

    url = event.text.strip() if event.text else ""
    is_yt = is_youtube_link(url)
    is_vid_file = bool(event.video or event.document)

    if not is_yt and not is_vid_file: return

    user_id = event.sender_id
    if user_id not in user_keys:
        await event.respond("🔑 ကျေးဇူးပြု၍ အရင်ဆုံး `/setkey` ဖြင့် Keys များ ထည့်ပေးပါ...")
        return

    await start_position_calibration(event, user_id, url, is_yt)

async def start_position_calibration(event, user_id, url, is_yt):
    status = await event.respond("📥 Preview အတွက် Video ကို ရယူနေပါသည်...")
    input_video = f"temp/calib_{user_id}_{int(time.time())}.mp4"
    try:
        if is_yt: download_youtube_video(url, input_video)
        else: await event.download_media(file=input_video)
    except Exception as e:
        try: await status.edit(f"❌ Video ရယူ၍မရပါ: {e}")
        except Exception: pass
        if os.path.exists(input_video): os.remove(input_video)
        return

    p_form = user_platform.get(user_id, "yt")
    p_res = user_res.get(user_id, "720")
    dim_w, dim_h = get_video_dimensions(p_form, p_res)

    raw_frame = f"temp/frame_{user_id}.jpg"
    try: extract_preview_frame(input_video, raw_frame, dim_w, dim_h, percent=0.3)
    except Exception as e:
        try: await status.edit(f"❌ Preview ပုံ ထုတ်၍မရပါ: {e}")
        except Exception: pass
        if os.path.exists(input_video): os.remove(input_video)
        return

    if user_id not in user_blur_y: user_blur_y[user_id] = 82
    if user_id not in user_sub_y: user_sub_y[user_id] = 82

    user_pending_calib[user_id] = {"input_video": input_video, "url": url, "is_yt": is_yt, "orig_event": event}

    try: await status.delete()
    except Exception: pass
    await send_calibration_preview(event.chat_id, user_id)

def _calib_buttons():
    return [
        [Button.inline("🌫️ Blur ⬆️", b"calib_blur_up"), Button.inline("🌫️ Blur ⬇️", b"calib_blur_down")],
        [Button.inline("📝 Sub ⬆️", b"calib_sub_up"), Button.inline("📝 Sub ⬇️", b"calib_sub_down")],
        [Button.inline("▶️ ဗီဒီယို စတင်ရန်", b"calib_confirm"), Button.inline("❌ ပယ်ဖျက်ရန်", b"calib_cancel")]
    ]

def _calib_caption(user_id):
    return (
        f"🌫️ Blur နေရာ: **{user_blur_y.get(user_id, 82)}%**  |  📝 Subtitle နေရာ: **{user_sub_y.get(user_id, 82)}%**\n"
        "အနီရောင် ဇုန် = Blur ၊ အဝါရောင် ဇုန် = Subtitle\n"
        "⬆️⬇️ ခလုတ်များဖြင့် နေရာချိန်ပြီး 'ဗီဒီယို စတင်ရန်' နှိပ်ပါ။"
    )

async def send_calibration_preview(chat_id, user_id):
    raw_frame = f"temp/frame_{user_id}.jpg"
    preview_path = f"temp/calib_preview_{user_id}.jpg"
    render_calibration_preview(raw_frame, preview_path, user_blur_y.get(user_id, 82), user_sub_y.get(user_id, 82), user_blur_mode.get(user_id, False))
    msg = await bot.send_file(chat_id, preview_path, caption=_calib_caption(user_id), buttons=_calib_buttons())
    calib = user_pending_calib.get(user_id)
    if calib: calib["msg_id"] = msg.id

async def update_calibration_preview(event):
    uid = event.sender_id
    if uid not in user_pending_calib:
        await event.answer("⚠️ Session သက်တမ်းကုန်သွားပါပြီ။ Video/Link ကို ပြန်ပို့ပေးပါ။", alert=True)
        return
    raw_frame = f"temp/frame_{uid}.jpg"
    preview_path = f"temp/calib_preview_{uid}.jpg"
    render_calibration_preview(raw_frame, preview_path, user_blur_y.get(uid, 82), user_sub_y.get(uid, 82), user_blur_mode.get(uid, False))
    try: await event.edit(file=preview_path, text=_calib_caption(uid), buttons=_calib_buttons())
    except MessageNotModifiedError: pass
    await event.answer()

@bot.on(events.CallbackQuery(pattern=b"calib_blur_up"))
async def calib_blur_up(event):
    uid = event.sender_id
    user_blur_y[uid] = max(20, user_blur_y.get(uid, 82) - 3)
    await update_calibration_preview(event)

@bot.on(events.CallbackQuery(pattern=b"calib_blur_down"))
async def calib_blur_down(event):
    uid = event.sender_id
    user_blur_y[uid] = min(88, user_blur_y.get(uid, 82) + 3)
    await update_calibration_preview(event)

@bot.on(events.CallbackQuery(pattern=b"calib_sub_up"))
async def calib_sub_up(event):
    uid = event.sender_id
    user_sub_y[uid] = max(10, user_sub_y.get(uid, 82) - 3)
    await update_calibration_preview(event)

@bot.on(events.CallbackQuery(pattern=b"calib_sub_down"))
async def calib_sub_down(event):
    uid = event.sender_id
    user_sub_y[uid] = min(90, user_sub_y.get(uid, 82) + 3)
    await update_calibration_preview(event)

@bot.on(events.CallbackQuery(pattern=b"calib_confirm"))
async def calib_confirm(event):
    uid = event.sender_id
    calib = user_pending_calib.pop(uid, None)
    if not calib:
        await event.answer("⚠️ Session သက်တမ်းကုန်သွားပါပြီ။ Video/Link ကို ပြန်ပို့ပေးပါ။", alert=True)
        return
    await event.answer("✅ Queue ထဲ ထည့်နေပါသည်...")
    try: await event.delete()
    except Exception: pass

    if uid not in user_queues: user_queues[uid] = asyncio.Queue()
    await user_queues[uid].put({"orig_event": calib["orig_event"], "input_video": calib["input_video"]})
    pending = user_queues[uid].qsize()

    if not user_queue_active.get(uid, False):
        user_queue_active[uid] = True
        asyncio.create_task(auto_recap_worker(uid))
    else:
        await calib["orig_event"].respond(f"📥 **Auto-Queue** ထဲသို့ ထည့်သွင်းလိုက်ပါပြီ (နောက်ထပ် **{pending}** ခု စောင့်ဆိုင်းနေပါသည်)။")

@bot.on(events.CallbackQuery(pattern=b"calib_cancel"))
async def calib_cancel(event):
    uid = event.sender_id
    calib = user_pending_calib.pop(uid, None)
    if calib and os.path.exists(calib["input_video"]): os.remove(calib["input_video"])
    frame_path = f"temp/frame_{uid}.jpg"
    if os.path.exists(frame_path): os.remove(frame_path)
    try: await event.edit(text="❌ ပယ်ဖျက်လိုက်ပါပြီ။", buttons=None)
    except MessageNotModifiedError: pass
    await event.answer()

async def process_recap_job(job_item, user_id):
    event = job_item["orig_event"]
    input_video = job_item["input_video"]
    sender = await event.get_sender()
    sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'username', '') or f"User_{user_id}"

    u_gemini = user_keys[user_id]["gemini"]
    u_groq = user_keys[user_id]["groq"]
    v_idx = user_voices.get(user_id, "v1")
    selected_voice_config = VOICE_MODES[v_idx]
    selected_speed = user_speeds.get(user_id, "1.1x")
    selected_font_fam = get_user_font_family(user_id)

    status = await event.respond("📥 စနစ်ကို စတင်နေပါသည်...")
    async def update_progress(message):
        try:
            await status.edit(message)
        except MessageNotModifiedError:
            pass
        except Exception as progress_error:
            logging.debug(f"Progress update failed: {progress_error}")
    output_video = f"temp/out_{user_id}_{int(time.time())}.mp4"
    extracted_audio_path = f"temp/extract_{user_id}_{int(time.time())}.mp3"

    try:
        extract_audio_ffmpeg(input_video, extracted_audio_path)

        try: await status.edit(f"⚡ [Auto-Queue Engine] ဘာသာစကားအားလုံးကို လျင်မြန်စွာ ညှိယူဖန်တီးနေပါသည်... (Speed: {selected_speed})")
        except MessageNotModifiedError: pass

        story_title, story_hook, story_hashtags, tb_path = await advanced_sync_pipeline(
            extracted_audio_path, u_gemini, u_groq, input_video, output_video, selected_voice_config, selected_speed, user_id, progress_cb=update_progress
        )

        if os.path.exists(extracted_audio_path): os.remove(extracted_audio_path)
        
        if os.path.exists(output_video):
            try: await status.edit("🚀 ဗီဒီယို ပြီးမြောက်ပါပြီ။ တင်ပို့နေပါသည်...")
            except MessageNotModifiedError: pass

            if user_id not in user_stats: user_stats[user_id] = {"name": sender_name, "count": 0, "last_active": ""}
            user_stats[user_id]["count"] += 1
            user_stats[user_id]["last_active"] = time.strftime("%Y-%m-%d %H:%M:%S")

            # 📌 VIDEO INFORMATION & STATS
            file_size_mb = os.path.getsize(output_video) / (1024 * 1024)
            actual_dur = get_media_duration(output_video)
            dur_mins = int(actual_dur // 60)
            dur_secs = int(actual_dur % 60)
            
            sub_status = "ဖွင့်ထားသည်" if user_sub_mode.get(user_id, False) else "ပိတ်ထားသည်"
            bypass_status = "ဖွင့်ထားသည်" if user_bypass_mode.get(user_id, False) else "ပိတ်ထားသည်"
            p_res_str = user_res.get(user_id, "720")
            p_form_str = user_platform.get(user_id, "yt").upper()
            
            caption_text = (
                f"🎬 **{story_title}**\n\n"
                f"💡 {story_hook}\n\n"
                f"{story_hashtags}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 **Video Information**\n"
                f"⏱️ ကြာချိန်: {dur_mins}m {dur_secs}s\n"
                f"💾 ဖိုင်ဆိုဒ်: {file_size_mb:.2f} MB\n"
                f"📺 Resolution: {p_res_str}p ({p_form_str})\n"
                f"🎙️ အသံ: {selected_voice_config['name']} (Speed: {selected_speed})\n"
                f"📝 စာတန်းထိုး: {sub_status}\n"
                f"🛡️ Edit Bypass: {bypass_status}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"✅ [Auto-Queue Master]"
            )

            await bot.send_file(event.chat_id, output_video, caption=caption_text)
            os.remove(output_video)

            if tb_path and os.path.exists(tb_path):
                await bot.send_file(event.chat_id, tb_path, caption="🖼️ **Thumbnail (TB) ပုံပါ**\n(ဗီဒီယိုအစတွင်လည်း တစ်ခါတည်း ထည့်သွင်းပေးထားပါသည်)")
                os.remove(tb_path)

        if os.path.exists(input_video): os.remove(input_video)
        try: await status.delete()
        except Exception: pass
    except Exception as e:
        try: await status.edit(f"❌ Error: {str(e)}")
        except Exception: await event.respond(f"❌ Error: {str(e)}")
        if os.path.exists(input_video): os.remove(input_video)
        if os.path.exists(extracted_audio_path): os.remove(extracted_audio_path)

async def auto_recap_worker(user_id):
    queue = user_queues[user_id]
    try:
        while not queue.empty():
            job_item = await queue.get()
            try: await process_recap_job(job_item, user_id)
            finally: queue.task_done()
    finally: user_queue_active[user_id] = False

async def main():
    threading.Thread(target=run_health_check_server, daemon=True).start()
    await bot.start(bot_token=BOT_TOKEN)
    logging.info("🤖 Bot started successfully.")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

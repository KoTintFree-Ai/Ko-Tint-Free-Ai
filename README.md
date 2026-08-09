# Ko Tint Free AI — Streamlit Movie Recap

This project converts an uploaded movie clip into a Burmese AI movie recap. It uses **Groq Whisper** for transcription, **Gemini** for Burmese translation and title generation, **edge-tts** for voiceover, **FFmpeg** for video assembly, and the bundled Myanmar Unicode fonts for subtitle rendering.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit user interface and session-safe job wrapper |
| `engine.py` | Adapted processing engine from the Telegram bot |
| `Fonts/` | Myanmar Unicode fonts used by PyQt subtitle rendering |
| `requirements.txt` | Python dependencies for Streamlit Cloud |
| `packages.txt` | System packages, including FFmpeg |

## Run locally

Install FFmpeg, create a virtual environment, install dependencies, and start Streamlit:

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL shown by Streamlit. Enter the Gemini and Groq keys in the sidebar at runtime. Do not put real keys in `app.py`, `engine.py`, GitHub, or a public README.

## Deploy to Streamlit Community Cloud

1. Upload the contents of this folder to the `KoTintFree-Ai/Ko-Tint-Free-Ai` repository.
2. Open [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, and select that repository.
3. Set the main file path to `app.py` and deploy.
4. In the deployed app, enter the Gemini key(s) and Groq key in the sidebar only when processing a video.

The repository is intentionally configured so Telegram credentials are read from environment variables rather than being required by the web app. The Streamlit version does not start a Telegram client.

## Notes

Processing is CPU- and network-intensive. Streamlit Community Cloud may time out or run out of memory for long videos. Start with short clips and 720p output. A persistent VM or container service is a better production target for long videos and queue-based processing.

Multiple Gemini keys can be entered as a comma-separated value. The application keeps them in memory for the current session and passes them to the existing key-pool logic. Rotate any keys that were previously posted in chat or committed to a repository.

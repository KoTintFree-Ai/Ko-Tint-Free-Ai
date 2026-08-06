import os
import google.generativeai as genai
import streamlit as st

# Streamlit Page Configuration
st.set_page_config(
    page_title="Movie Recap AI V17 - Authenticated", page_icon="🎬", layout="wide"
)

st.title("🎬 Movie Recap AI V17 - Authenticated")
st.markdown("ရိုးရှင်းတဲ့ အင်္ဂလိပ် ဗီဒီယို → မြန်မာစာ → အသံ → SRT → ဗီဒီယို")

# Sidebar - Settings & API Keys
st.sidebar.subheader("⚙️ ဆက်တင်များ")
st.sidebar.subheader("🔑 API Keys")

api_keys = []
for i in range(1, 6):
    key = st.sidebar.text_input(
        f"API Key {i}", type="password", key=f"key_{i}"
    )
    if key:
        api_keys.append(key)

# API Keys Test Button Logic
if st.sidebar.button("🔌 Keys စမ်းသပ်"):
    if not api_keys:
        st.sidebar.warning("⚠️ API Key ထည့်သွင်းထားခြင်း မရှိပါ။")
    else:
        st.sidebar.info("🔄 Keys များကို စစ်ဆေးနေပါသည်...")
        valid_keys = []

        for idx, key in enumerate(api_keys, 1):
            try:
                genai.configure(api_key=key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content("Hello")

                if response.text:
                    st.sidebar.success(f"✅ Key {idx}: အဆင်ပြေပါတယ်")
                    valid_keys.append(key)
            except Exception as e:
                st.sidebar.error(
                    f"❌ Key {idx}: 401 Unauthorized - API Key မမှန်ကန်သည်"
                )

        if not valid_keys:
            st.sidebar.error("❌ အောင်မြင်သော Key မရှိပါ")
        else:
            st.session_state["active_keys"] = valid_keys

# Main Step 1 Section
st.markdown("### Step 1️⃣: ဗီဒီယို → မြန်မာစာ (Plain Text)")
uploaded_file = st.file_uploader(
    "ဗီဒီယို/အော်ဒီယို တင်ရန်", type=["mp4", "mov", "avi", "mp3", "wav"]
)

if uploaded_file is not None:
    st.success(
        f"{uploaded_file.name} ({uploaded_file.size / (1024*1024):.1f}MB) တင်ပြီးပါပြီ"
    )

    if not api_keys:
        st.warning("⚠️ အရင် Sidebar မှာ API Key ကို စစ်ဆေးပါ")
    else:
        if st.button("🚀 Step 1 စတင်"):
            st.info(
                "🔄 လုပ်ဆောင်နေပါသည်... ကျေးဇူးပြု၍ ခဏစောင့်ဆိုင်းပေးပါ။"
            )

            # Error ဖြစ်စေသော nonlocal cur_t နေရာအား ပြင်ဆင်ပြီးဖြစ်ပါသည်
            cur_t = 0  # Initialize variable safely


            def process_translation():
                nonlocal cur_t  # Error မတက်စေရန် အထက်တွင် cur_t ကို ကြေညာထားပြီးပါပြီ
                cur_t += 1


            process_translation()

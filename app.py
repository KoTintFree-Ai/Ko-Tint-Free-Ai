# API Keys Test Button Logic (Updated)
if st.sidebar.button("🔌 Keys စမ်းသပ်"):
    if not api_keys:
        st.sidebar.warning("⚠️ API Key ထည့်သွင်းထားခြင်း မရှိပါ။")
    else:
        st.sidebar.info("🔄 Keys များကို စစ်ဆေးနေပါသည်...")
        valid_keys = []

        for idx, key in enumerate(api_keys, 1):
            try:
                # API Key ကို ရှင်းလင်းစွာ သတ်မှတ်ခြင်း
                genai.configure(api_key=key.strip())
                # ပိုမိုတည်ငြိမ်သော gemini-1.5-flash ကို အသုံးပြုခြင်း
                model = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content("Hi")

                if response:
                    st.sidebar.success(f"✅ Key {idx}: အဆင်ပြေပါတယ်")
                    valid_keys.append(key)
            except Exception as e:
                # အသေးစိတ် Error ကို ပြသပေးခြင်းဖြင့် အကြောင်းရင်းကို သိနိုင်မည်
                st.sidebar.error(f"❌ Key {idx}: အလုပ်မလုပ်ပါ ({str(e)})")

        if not valid_keys:
            st.sidebar.error("❌ အောင်မြင်သော Key မရှိပါ")
        else:
            st.session_state["active_keys"] = valid_keys

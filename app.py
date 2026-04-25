import streamlit as st
import os
import json
import threading
import time
import requests
import io
import base64
from dotenv import load_dotenv
from supabase import create_client, Client
import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
import instaloader

# --- CONFIGURATION ---
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Init Services
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')
L = instaloader.Instaloader()

# --- BACKGROUND API (Receiver for Extension) ---
app_api = Flask(__name__)
CORS(app_api)

@app_api.route('/api/save', methods=['POST'])
def save_from_extension():
    data = request.json
    # Data expected: {reelId, caption, pageUrl}
    with open("ext_buffer.json", "w") as f:
        json.dump(data, f)
    return jsonify({"status": "Chef received the ID!"})

def run_api():
    app_api.run(port=5001, debug=False, use_reloader=False)

if 'api_thread' not in st.session_state:
    threading.Thread(target=run_api, daemon=True).start()
    st.session_state.api_thread = True

# --- CORE LOGIC: THE EXTRACTOR ---
def process_reel_recipe(reel_id, caption, page_url):
    try:
        # 1. Fetch the actual video stream URL using the ID
        st.info(f"Connecting to Instagram for Reel: {reel_id}...")
        post = instaloader.Post.from_shortcode(L.context, reel_id)
        video_url = post.video_url
        
        # 2. Stream video bytes into RAM (No local file saved)
        video_resp = requests.get(video_url, stream=True)
        video_bytes = io.BytesIO(video_resp.content)
        
        # 3. Upload to Gemini File API
        st.info("Sending stream to Gemini AI...")
        genai_file = genai.upload_file(video_bytes, mime_type="video/mp4")
        
        # 4. Wait for AI to process the video
        while True:
            file_status = genai.get_file(genai_file.name)
            if file_status.state.name == "ACTIVE":
                break
            elif file_status.state.name == "FAILED":
                raise Exception("AI failed to process the video stream.")
            time.sleep(2)

        # 5. Multimodal Extraction
        st.success("AI is itemizing the recipe...")
        prompt = f"""
        Analyze this video and the caption: "{caption}".
        Itemize the recipe exactly:
        - Title of the dish
        - Ingredients list with measurements
        - Step-by-step cooking instructions
        - Health tags (e.g., High Protein, Vegan, etc.)
        """
        
        response = model.generate_content([prompt, genai_file])
        recipe_text = response.text
        
        # 6. Save to Supabase
        supabase.table("recipes").insert({
            "user_id": str(st.session_state.user.id),
            "title": caption[:50] if caption else f"Reel {reel_id}",
            "ingredients": "See instructions below", # Or split the AI response
            "instructions": recipe_text,            # This matches your column!
            "video_url": page_url
        }).execute()
        
        # Cleanup Gemini Cloud File
        genai.delete_file(genai_file.name)
        return recipe_text

    except Exception as e:
        return f"❌ Chef Error: {str(e)}"

# --- STREAMLIT UI ---
st.set_page_config(page_title="The Reel Chef", page_icon="🍳", layout="centered")

if 'user' not in st.session_state:
    st.title("🍳 The Reel Chef")
    st.subheader("Login to your Kitchen")
    e = st.text_input("Email")
    p = st.text_input("Password", type="password")
    if st.button("Log In"):
        try:
            res = supabase.auth.sign_in_with_password({"email": e, "password": p})
            st.session_state.user = res.user
            st.rerun()
        except:
            st.error("Authentication Failed.")
else:
    st.sidebar.title("🍳 The Reel Chef")
    choice = st.sidebar.radio("Go to:", ["Inbox", "My Cookbook"])

    if choice == "Inbox":
        st.header("📥 Extension Inbox")
        if os.path.exists("ext_buffer.json"):
            with open("ext_buffer.json", "r") as f:
                incoming = json.load(f)
            
            st.write(f"**Ready to process:** {incoming['pageUrl']}")
            
            if st.button("Itemize Recipe"):
                with st.spinner("Processing..."):
                    result = process_reel_recipe(
                        incoming['reelId'], 
                        incoming['caption'], 
                        incoming['pageUrl']
                    )
                    st.markdown("### 📝 Itemized Recipe")
                    st.markdown(result)
                    # Clear buffer after success
                    if "❌" not in result:
                        os.remove("ext_buffer.json")
        else:
            st.info("Nothing in the inbox. Use the Chrome Extension while watching a Reel!")

    elif choice == "My Cookbook":
        st.header("📖 My Saved Recipes")
        recipes = supabase.table("recipes").select("*").eq("user_id", st.session_state.user.id).execute()
        
        if not recipes.data:
            st.write("Your cookbook is empty.")
        
        for r in recipes.data:
            with st.expander(f"🍲 {r['title']}"):
                st.markdown(r['ingredients'])
                st.caption(f"Source: {r['video_url']}")
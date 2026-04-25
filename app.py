"""
TheReelChef: Seamless Link-to-Recipe Pipeline
============================================

Ideal user flow:
1. User browses Instagram reel
2. User clicks extension button → "Send to Recipe Library"
3. System processes reel link in background
4. Recipe appears in library automatically
5. User can explore and filter recipes

No recording, no waiting, no manual input required.
"""

import streamlit as st
import os
import json
import threading
import time
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
from anthropic import Anthropic
from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
from yt_dlp import YoutubeDL
import re

# --- CONFIGURATION ---
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

# Initialize services
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai.api_key = OPENAI_KEY
claude = Anthropic(api_key=ANTHROPIC_KEY)

# --- FLASK API (Background Processing) ---
app_api = Flask(__name__)
CORS(app_api)

# Queue for background processing
processing_queue = []
processing_lock = threading.Lock()


@app_api.route('/api/process-reel', methods=['POST'])
def process_reel_endpoint():
    """
    User sends Instagram reel link from extension
    We immediately return (no waiting)
    Processing happens in background
    """
    try:
        data = request.json
        reel_url = data.get('reel_url')
        user_id = data.get('user_id')
        
        if not reel_url or not user_id:
            return jsonify({"error": "Missing reel_url or user_id"}), 400
        
        # Add to processing queue
        with processing_lock:
            job = {
                "id": f"{user_id}_{int(time.time())}",
                "reel_url": reel_url,
                "user_id": user_id,
                "status": "queued",
                "created_at": datetime.now().isoformat()
            }
            processing_queue.append(job)
        
        return jsonify({
            "status": "queued",
            "message": "Your reel is being processed! Check your library in a moment.",
            "job_id": job["id"]
        }), 202  # 202 Accepted
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app_api.route('/api/job-status/<job_id>', methods=['GET'])
def get_job_status(job_id):
    """Check processing status"""
    with processing_lock:
        for job in processing_queue:
            if job["id"] == job_id:
                return jsonify(job), 200
    
    return jsonify({"status": "completed"}), 200


def background_processor():
    """
    Continuously processes reel links from queue
    Runs in separate thread
    """
    while True:
        try:
            with processing_lock:
                if not processing_queue:
                    time.sleep(2)
                    continue
                
                job = processing_queue[0]
            
            # Process the reel
            job["status"] = "downloading"
            success = process_reel_to_recipe(
                job["reel_url"],
                job["user_id"],
                job["id"]
            )
            
            if success:
                job["status"] = "completed"
            else:
                job["status"] = "failed"
            
            # Remove from queue
            with processing_lock:
                processing_queue.pop(0)
        
        except Exception as e:
            print(f"Background processor error: {str(e)}")
            time.sleep(5)


def extract_reel_id_from_url(url):
    """Extract Instagram reel ID from URL"""
    # Handle multiple Instagram URL formats
    patterns = [
        r'instagram\.com/reel/([A-Za-z0-9_-]+)',
        r'instagram\.com/p/([A-Za-z0-9_-]+)',
        r'/reel/([A-Za-z0-9_-]+)',
        r'/p/([A-Za-z0-9_-]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


def download_reel_audio(reel_url):
    """
    Download audio from Instagram reel using yt-dlp
    Returns: (success, audio_file_path)
    """
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }],
            'outtmpl': '/tmp/%(id)s',
            'quiet': True,
            'no_warnings': True,
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(reel_url, download=True)
            audio_file = f"/tmp/{info['id']}.wav"
            return True, audio_file
    
    except Exception as e:
        print(f"Download failed: {str(e)}")
        return False, None


def transcribe_reel_audio(audio_file_path):
    """Transcribe audio using Whisper"""
    try:
        with open(audio_file_path, 'rb') as audio_file:
            transcript = openai.Audio.transcribe(
                model="whisper-1",
                file=audio_file,
                language="en"
            )
        
        # Clean up
        os.remove(audio_file_path)
        
        return transcript["text"]
    
    except Exception as e:
        print(f"Transcription failed: {str(e)}")
        return None


def extract_recipe_from_transcript(transcript, reel_url):
    """Use Claude to structure the recipe"""
    try:
        message = claude.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": f"""
Transcribed cooking reel audio:
"{transcript}"

Source URL: {reel_url}

Extract a complete recipe and return ONLY valid JSON (no markdown):
{{
    "title": "Dish name",
    "description": "Brief description",
    "ingredients": [
        {{"item": "ingredient", "amount": "1.5", "unit": "cups"}}
    ],
    "instructions": [
        "Step by step instructions",
        "Be specific about timing and temperature"
    ],
    "cook_time_minutes": 20,
    "prep_time_minutes": 10,
    "serves": 4,
    "difficulty": "easy" | "medium" | "hard",
    "tags": ["quick", "vegetarian"],
    "tips": "Optional tips from the video"
}}

If transcription is unclear, make reasonable assumptions based on cooking knowledge.
Return ONLY the JSON object, nothing else.
"""
            }]
        )
        
        recipe_text = message.content[0].text
        # Clean up markdown if present
        recipe_text = recipe_text.replace('```json', '').replace('```', '')
        recipe = json.loads(recipe_text)
        return recipe
    
    except Exception as e:
        print(f"Recipe extraction failed: {str(e)}")
        return None


def process_reel_to_recipe(reel_url, user_id, job_id):
    """
    Main processing pipeline:
    Link → Download Audio → Transcribe → Extract Recipe → Save
    """
    try:
        # Step 1: Download audio
        success, audio_file = download_reel_audio(reel_url)
        if not success:
            return False
        
        # Step 2: Transcribe
        transcript = transcribe_reel_audio(audio_file)
        if not transcript:
            return False
        
        # Step 3: Extract recipe
        recipe = extract_recipe_from_transcript(transcript, reel_url)
        if not recipe:
            return False
        
        # Step 4: Save to Supabase
        supabase.table("recipes").insert({
            "user_id": user_id,
            "title": recipe.get("title", "Untitled"),
            "description": recipe.get("description", ""),
            "ingredients": json.dumps(recipe.get("ingredients", [])),
            "instructions": json.dumps(recipe.get("instructions", [])),
            "cook_time_minutes": recipe.get("cook_time_minutes", 0),
            "prep_time_minutes": recipe.get("prep_time_minutes", 0),
            "serves": recipe.get("serves", 4),
            "difficulty": recipe.get("difficulty", "medium"),
            "tags": recipe.get("tags", []),
            "tips": recipe.get("tips", ""),
            "source_reel_url": reel_url,
            "created_at": "now()"
        }).execute()
        
        return True
    
    except Exception as e:
        print(f"Processing failed: {str(e)}")
        return False


def run_api():
    """Run Flask API in background"""
    app_api.run(port=5001, debug=False, use_reloader=False, threaded=True)


# Start background threads on startup
if 'api_thread' not in st.session_state:
    threading.Thread(target=run_api, daemon=True).start()
    threading.Thread(target=background_processor, daemon=True).start()
    st.session_state.api_thread = True


# --- STREAMLIT UI ---

st.set_page_config(
    page_title="The Reel Chef",
    page_icon="🍳",
    layout="wide"
)

# Custom CSS for better UX
st.markdown("""
<style>
    .recipe-card {
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
        background: #f9f9f9;
    }
    
    .recipe-title {
        font-size: 18px;
        font-weight: bold;
        color: #333;
        margin-bottom: 8px;
    }
    
    .recipe-meta {
        display: flex;
        gap: 12px;
        font-size: 12px;
        color: #666;
        margin-bottom: 12px;
    }
    
    .filter-chip {
        display: inline-block;
        background: #e8f4f8;
        color: #0275d8;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        margin-right: 8px;
        margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)


# Authentication
if 'user' not in st.session_state:
    col1, col2 = st.columns([1, 3])
    
    with col1:
        st.title("🍳 Reel Chef")
        st.subheader("Log In")
        
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        
        if st.button("Sign In", use_container_width=True, type="primary"):
            try:
                res = supabase.auth.sign_in_with_password({
                    "email": email,
                    "password": password
                })
                st.session_state.user = res.user
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {str(e)}")
        
        st.divider()
        st.subheader("New User?")
        
        email_new = st.text_input("Create email", key="signup_email")
        password_new = st.text_input("Create password", type="password", key="signup_password")
        
        if st.button("Create Account", use_container_width=True):
            try:
                res = supabase.auth.sign_up({
                    "email": email_new,
                    "password": password_new
                })
                st.success("Account created! Please log in.")
            except Exception as e:
                st.error(f"Signup failed: {str(e)}")

else:
    # Main App
    st.title("🍳 The Reel Chef")
    st.caption(f"Logged in as: {st.session_state.user.email}")
    
    # Sidebar navigation
    page = st.sidebar.radio("Navigate", [
        "📚 My Recipes",
        "🔗 Share Reel",
        "⚙️ Settings"
    ], label_visibility="collapsed")

    if page == "🔗 Share Reel":
        st.header("Share an Instagram Reel")
        st.markdown("""
        Paste the link to any cooking reel, and we'll automatically extract the recipe!
        
        You can:
        - Copy the reel link from Instagram (click share → copy link)
        - Or paste the full Instagram URL directly
        """)
        
        reel_link = st.text_input(
            "Instagram Reel Link",
            placeholder="https://www.instagram.com/reel/...",
            help="Paste the complete Instagram reel URL"
        )
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            if st.button("📝 Process Reel", type="primary", use_container_width=True):
                if not reel_link.strip():
                    st.error("Please paste a reel link")
                elif "instagram.com" not in reel_link:
                    st.error("Please paste a valid Instagram URL")
                else:
                    # Send to backend for processing
                    with st.spinner("📤 Sending to background processor..."):
                        import requests
                        
                        try:
                            response = requests.post(
                                "http://localhost:5001/api/process-reel",
                                json={
                                    "reel_url": reel_link,
                                    "user_id": str(st.session_state.user.id)
                                }
                            )
                            
                            if response.status_code in [200, 202]:
                                st.success("✅ Reel queued for processing! It will appear in your library shortly.")
                                st.info("💡 You can close this tab or continue browsing. The recipe will be added automatically.")
                            else:
                                st.error(f"Error: {response.json().get('error', 'Unknown error')}")
                        
                        except Exception as e:
                            st.error(f"Connection error: {str(e)}")
        
        with col2:
            if st.button("ℹ️", help="How to share a reel"):
                st.info("""
                **How to get the link:**
                1. Open Instagram reel
                2. Click 3 dots (menu)
                3. Select "Copy link"
                4. Paste here
                """)
        
        st.divider()
        st.subheader("Processing Status")
        
        try:
            # Get processing queue status
            with processing_lock:
                if processing_queue:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Queue Position", len(processing_queue))
                    with col2:
                        job = processing_queue[0]
                        st.metric("Current Status", job["status"].capitalize())
                    
                    st.info(f"Estimated time: {len(processing_queue) * 30} seconds")
                else:
                    st.success("Queue is empty - new recipes process instantly!")
        except:
            pass

    elif page == "📚 My Recipes":
        st.header("My Recipe Library")
        
        # Search and filter
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            search_query = st.text_input("Search recipes", placeholder="pasta, chicken...")
        
        with col2:
            difficulty_filter = st.multiselect(
                "Difficulty",
                ["easy", "medium", "hard"],
                default=["easy", "medium", "hard"]
            )
        
        with col3:
            cook_time = st.slider("Max cook time (min)", 0, 120, 120)
        
        with col4:
            sort_by = st.radio("Sort", ["Newest", "A-Z", "Quickest"], horizontal=True)
        
        # Fetch recipes
        try:
            response = supabase.table("recipes").select("*").eq(
                "user_id",
                st.session_state.user.id
            ).execute()
            
            recipes = response.data if response.data else []
            
            # Apply filters
            filtered_recipes = []
            
            for recipe in recipes:
                # Text search
                if search_query:
                    search_lower = search_query.lower()
                    if search_lower not in recipe.get("title", "").lower() and \
                       search_lower not in recipe.get("description", "").lower():
                        continue
                
                # Difficulty filter
                if recipe.get("difficulty") not in difficulty_filter:
                    continue
                
                # Cook time filter
                if recipe.get("cook_time_minutes", 0) > cook_time:
                    continue
                
                filtered_recipes.append(recipe)
            
            # Sort
            if sort_by == "A-Z":
                filtered_recipes.sort(key=lambda x: x.get("title", "").lower())
            elif sort_by == "Quickest":
                filtered_recipes.sort(key=lambda x: x.get("cook_time_minutes", 999))
            else:  # Newest
                filtered_recipes.reverse()
            
            # Display
            if not filtered_recipes:
                st.info("📭 No recipes match your filters. Share a reel to get started!")
            else:
                st.caption(f"📚 {len(filtered_recipes)} recipe{'s' if len(filtered_recipes) != 1 else ''}")
                
                for recipe in filtered_recipes:
                    with st.expander(f"🍲 {recipe['title']}", expanded=False):
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            difficulty = recipe.get('difficulty', 'medium')
                            emoji = '🟢' if difficulty == 'easy' else '🟡' if difficulty == 'medium' else '🔴'
                            st.caption(f"{emoji} {difficulty.title()}")
                        
                        with col2:
                            st.caption(f"⏱️ {recipe.get('cook_time_minutes', '?')} min")
                        
                        with col3:
                            st.caption(f"👥 Serves {recipe.get('serves', 4)}")
                        
                        with col4:
                            if recipe.get('source_reel_url'):
                                st.markdown(f"[🔗 Original]('{recipe['source_reel_url']}')")
                        
                        if recipe.get('description'):
                            st.markdown(f"*{recipe['description']}*")
                        
                        col1, col2 = st.columns([2, 1])
                        
                        with col1:
                            st.markdown("**Ingredients:**")
                            try:
                                ingredients = json.loads(recipe.get('ingredients', '[]'))
                                for ing in ingredients:
                                    st.write(f"• {ing['amount']} {ing['unit']} {ing['item']}")
                            except:
                                st.write(recipe.get('ingredients', 'N/A'))
                        
                        with col2:
                            if recipe.get('tags'):
                                st.markdown("**Tags:**")
                                for tag in recipe['tags']:
                                    st.write(f"<span class='filter-chip'>{tag}</span>", unsafe_allow_html=True)
                        
                        st.markdown("**Instructions:**")
                        try:
                            instructions = json.loads(recipe.get('instructions', '[]'))
                            for i, step in enumerate(instructions, 1):
                                st.write(f"{i}. {step}")
                        except:
                            st.write(recipe.get('instructions', 'N/A'))
                        
                        if recipe.get('tips'):
                            st.info(f"💡 {recipe['tips']}")
                        
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            if st.button("📋 Copy", key=f"copy_{recipe['id']}"):
                                recipe_text = f"""
{recipe['title']}

Ingredients:
{json.dumps(json.loads(recipe.get('ingredients', '[]')), indent=2)}

Instructions:
{json.dumps(json.loads(recipe.get('instructions', '[]')), indent=2)}
"""
                                st.code(recipe_text)
                        
                        with col2:
                            if st.button("🗑️ Delete", key=f"delete_{recipe['id']}"):
                                supabase.table("recipes").delete().eq("id", recipe['id']).execute()
                                st.rerun()
                        
                        with col3:
                            if st.button("📤 Share", key=f"share_{recipe['id']}"):
                                st.write("Share feature coming soon!")
        
        except Exception as e:
            st.error(f"Error loading recipes: {str(e)}")

    elif page == "⚙️ Settings":
        st.header("Settings")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Account")
            if st.button("Sign Out"):
                del st.session_state.user
                st.rerun()
        
        with col2:
            st.subheader("Export")
            if st.button("Export All Recipes (JSON)"):
                response = supabase.table("recipes").select("*").eq(
                    "user_id",
                    st.session_state.user.id
                ).execute()
                
                export_data = json.dumps(response.data, indent=2, default=str)
                st.download_button(
                    "📥 Download",
                    export_data,
                    "my_recipes.json",
                    "application/json"
                )
        
        st.divider()
        st.subheader("About")
        st.write("Transform your favorite cooking reels into a searchable recipe library.")
        st.write("Every reel gets automatically processed and added to your collection.")
import streamlit as st
import os
from dotenv import load_dotenv
from supabase import create_client, Client
import google.generativeai as genai
import yt_dlp
import time

# 1. Load Secrets
load_dotenv()
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
gemini_key = os.getenv("GEMINI_API_KEY")

# 2. Initialize Connections
supabase: Client = create_client(url, key)
genai.configure(api_key=gemini_key)
model = genai.GenerativeModel('gemini-1.5-flash')

st.set_page_config(page_title="The Reel Chef", page_icon="🍳")

# 3. Simple Login Logic
if 'user' not in st.session_state:
    st.title("🍳 The Reel Chef")
    auth_mode = st.radio("Choose", ["Login", "Sign Up"])
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    
    if st.button("Enter Kitchen"):
        try:
            if auth_mode == "Sign Up":
                res = supabase.auth.sign_up({"email": email, "password": password})
                st.info("Check your email to confirm!")
            else:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.user = res.user
                st.rerun()
        except Exception as e:
            st.error(f"Auth Error: {e}")
    st.stop()

# 4. Main App Interface
st.sidebar.title("👨‍🍳 The Reel Chef")
menu = st.sidebar.selectbox("Menu", ["My Library", "Add New Reel", "Meal Planner", "Logout"])

if menu == "Logout":
    supabase.auth.sign_out()
    del st.session_state.user
    st.rerun()

elif menu == "Add New Reel":
    st.header("📥 Extract Recipe")
    video_url = st.text_input("Paste Reel or Short URL:")
    
    # NEW: Add a text area as a fallback
    manual_text = st.text_area("OR: Paste the caption/description here if the link fails:")
    
    if st.button("Analyze Recipe"):
        with st.spinner("Chef is processing..."):
            try:
                content_to_analyze = ""
                
                # Try to scrape the link first
                if video_url and not manual_text:
                    try:
                        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(video_url, download=False)
                            content_to_analyze = info.get('description', '')
                            title = info.get('title', 'New Recipe')
                    except:
                        st.error("Instagram blocked the link! Please copy-paste the caption into the box below.")
                        st.stop()
                
                # Use manual text if provided
                elif manual_text:
                    content_to_analyze = manual_text
                    title = "New Saved Recipe"
                
                if content_to_analyze:
                    prompt = f"Analyze this recipe content and create a structured card with Title, Labels (Vegan, etc), Ingredients, and Steps: {content_to_analyze}"
                    response = model.generate_content(prompt)
                    
                    # Save to Supabase
                    recipe_data = {
                        "user_id": st.session_state.user.id,
                        "title": title,
                        "ingredients": response.text,
                        "video_url": video_url if video_url else "Manual Entry"
                    }
                    supabase.table("recipes").insert(recipe_data).execute()
                    st.success("Recipe added!")
                    st.markdown(response.text)
            
            except Exception as e:
                st.error(f"Something went wrong: {e}")

elif menu == "My Library":
    st.header("📖 Your Cookbook")
    res = supabase.table("recipes").select("*").eq("user_id", st.session_state.user.id).execute()
    for r in res.data:
        with st.expander(r['title']):
            st.markdown(r['ingredients'])
            st.video(r['video_url'])

elif menu == "Meal Planner":
    st.header("🗓️ The Reel Chef: Planner")
    
    # Get all recipes you've saved
    res = supabase.table("recipes").select("*").eq("user_id", st.session_state.user.id).execute()
    recipes = res.data
    
    if not recipes:
        st.info("Your library is empty. Go add some reels first!")
    else:
        # Create a dictionary to map titles to their full data
        recipe_map = {r['title']: r for r in recipes}
        selected = st.multiselect("Select recipes for your grocery list:", list(recipe_map.keys()))
        
        if st.button("Generate Smart List"):
            # Combine ingredients for the AI to analyze
            combined_text = ""
            for title in selected:
                combined_text += f"\n- {title}: {recipe_map[title]['ingredients']}"
            
            with st.spinner("Calculating nutrition and costs..."):
                prompt = f"""
                You are a nutrition coach and budget expert. 
                Based on these selected recipes: {combined_text}
                
                1. Provide a CUMULATIVE shopping list (combine similar items).
                2. HEALTH CHECK: Suggest one ingredient to add to improve fiber/protein.
                3. SAVINGS: Point out if any ingredients can be bought in bulk.
                """
                ai_analysis = genai.GenerativeModel('gemini-1.5-flash').generate_content(prompt)
                st.markdown(ai_analysis.text)
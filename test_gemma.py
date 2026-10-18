import streamlit as st
from google import genai

client = genai.Client(
    api_key=st.secrets["gemma"]["api_key"]
)

response = client.models.generate_content(
    model=st.secrets["gemma"]["model"],
    contents="Reply with exactly: Gemma is working!"
)

print(response.text)
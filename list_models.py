import os
import google.generativeai as genai

os.environ["GEMINI_API_KEY"] = "AIzaSyDqns01kwTrg6pIIbD6n_S0WKaXrrvt9vk"
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

for m in genai.list_models():
  if 'generateContent' in m.supported_generation_methods:
    print(m.name)

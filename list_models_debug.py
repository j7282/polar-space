import os
import google.generativeai as genai

os.environ["GEMINI_API_KEY"] = "AIzaSyDqns01kwTrg6pIIbD6n_S0WKaXrrvt9vk"
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

try:
    models = list(genai.list_models())
    print(f"Found {len(models)} models.")
    for m in models:
        print(f" - {m.name}: {m.supported_generation_methods}")
except Exception as e:
    print(f"API Error: {e}")

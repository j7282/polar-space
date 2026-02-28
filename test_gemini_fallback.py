import os
import sys

# Setup environment for test
os.environ["GEMINI_API_KEY"] = "AIzaSyDqns01kwTrg6pIIbD6n_S0WKaXrrvt9vk"

import telethon_listener as tl

# 1. Create a messy dummy file
dummy_content = """
=============================
🔥 HOTMAIL HQ PRIVATE DUMP 🔥
=============================
Date: 2026-02-26
IP: 192.168.1.1
-----------------------------
usuario1@hotmail.com | password_secreta_1 | 200 OK
[test2@hotmail.com] -> [clave12345]
email: user3@hotmail.com password: mYpAsSwOrD!
Basura texto basura texto
"""

print("Testing Gemini fallback extraction logic...")

# 2. Test the extraction explicitly
extracted = tl.extract_with_gemini(dummy_content)
print("\n--- GEMINI EXTRACTION RESULT ---")
for cred in extracted:
    print(cred)
print("--------------------------------")

if len(extracted) == 3:
    print("✅ SUCCESS: Gemini correctly parsed the messy formats!")
else:
    print(f"❌ FAILED: Gemini found {len(extracted)} targets instead of 3.")

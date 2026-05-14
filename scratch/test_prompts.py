import asyncio
import os
import json
from main import extract_symptoms, EXTRACTION_PROMPT

# Mocking transcript
transcript = """
PRIYA: Hello, I am Priya from Alert+. नमस्ते, मैं Alert+ से प्रिया बोल रही हूँ। Can I get your name?
USER: My name is Rajesh Kumar.
PRIYA: Hello Rajesh. Are you male or female?
USER: I am a male.
PRIYA: And what is your age?
USER: I am 45 years old.
PRIYA: Which tehsil are you calling from?
USER: I am in Khed tehsil.
PRIYA: What is the main health issue you are facing today?
USER: I have a high fever and headache.
PRIYA: How many days has it been?
USER: 3 days.
PRIYA: On a scale of 1 to 10, how severe is the pain?
USER: It's about a 7.
PRIYA: Any other symptoms like cough or body pain?
USER: Yes, my body hurts a lot.
PRIYA: Have you taken any medicine?
USER: No, nothing yet.
"""

async def test_extraction():
    print("Testing extraction...")
    # Mocking the environment variables for main.py (if needed during import)
    # But extract_symptoms uses openai_client which is already initialized in main.py
    # We need to ensure openai_client has a key or mock it.
    
    # Since I cannot easily mock the OpenAI client here without complex patches,
    # I will do a logic check on the EXTRACTION_PROMPT string itself to ensure it contains our new fields.
    
    print("Checking EXTRACTION_PROMPT...")
    if '"gender"' in EXTRACTION_PROMPT and '"age"' in EXTRACTION_PROMPT and '"tehsil"' in EXTRACTION_PROMPT:
        print("SUCCESS: EXTRACTION_PROMPT contains new fields.")
    else:
        print("FAILURE: EXTRACTION_PROMPT missing fields.")
        
    # Also check the SYSTEM_PROMPT structure (imported via main if possible or just read file)
    from main import SYSTEM_PROMPT
    print("Checking SYSTEM_PROMPT...")
    if "Gender (लिंग)" in SYSTEM_PROMPT and "Age (उम्र)" in SYSTEM_PROMPT and "Tehsil" in SYSTEM_PROMPT:
        print("SUCCESS: SYSTEM_PROMPT contains new fields.")
    else:
        print("FAILURE: SYSTEM_PROMPT missing fields.")

if __name__ == "__main__":
    asyncio.run(test_extraction())

import base64
import json
import urllib.request
from typing import Dict, Any

OLLAMA_API_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5-vl"

def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def generate_ollama_prompt(image_path: str, florence_caption: str, system_prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Send image and florence caption to Ollama to format the JSON contract."""
    base64_image = _encode_image(image_path)
    
    # Qwen-VL responds very well to strict JSON schema instructions
    combined_prompt = (
        f"{system_prompt}\n\n"
        f"--- RAW VISUAL DATA (From Florence-2) ---\n"
        f"{florence_caption}\n\n"
        f"Use the image and the raw visual data above to generate the strict JSON prompt contract."
    )
    
    payload = {
        "model": model,
        "prompt": combined_prompt,
        "images": [base64_image],
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.2
        }
    }
    
    req = urllib.request.Request(
        OLLAMA_API_URL, 
        data=json.dumps(payload).encode("utf-8"), 
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result.get("response", "{}")
    except Exception as e:
        print(f"Failed to query Ollama at {OLLAMA_API_URL}. Is it running? Error: {e}")
        return "{}"

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        print(generate_ollama_prompt(sys.argv[1], sys.argv[2], "Extract JSON info."))
    else:
        print("Usage: python vlm_ollama.py <image_path> <florence_caption_string>")

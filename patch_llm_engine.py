import sys
import re

content = open("worker/llm_engine.py").read()

new_code = '''
def _call_openai_vision(text: str, media_path: str, sys_prompt: str) -> requests.Response:
    with open(media_path, "rb") as f:
        base64_image = base64.b64encode(f.read()).decode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }
    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{sys_prompt}\\n\\nТекст повідомлення: {text[:1000]}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }
    return requests.post(OPENAI_URL, headers=headers, json=data, timeout=20)

def _call_groq_text(text: str, sys_prompt: str, model: str = "llama-3.1-70b-versatile") -> requests.Response:
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"{sys_prompt} json:"},
            {"role": "user", "content": text[:1500]}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    return requests.post(GROQ_URL, headers=headers, json=data, timeout=10)

def _call_openai_text(text: str, sys_prompt: str) -> requests.Response:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }
    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": text[:1500]}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    return requests.post(OPENAI_URL, headers=headers, json=data, timeout=15)

def _route_text_llm(text: str, sys_prompt: str) -> dict:
    if not text:
        return {}
    
    resp = _call_groq_text(text, sys_prompt)
    if resp.status_code in (429, 503, 500) and OPENAI_API_KEY:
        logger.warning(f"Groq API returned {resp.status_code}. Switching to OpenAI fallback...")
        resp = _call_openai_text(text, sys_prompt)
    elif resp.status_code != 200:
        logger.warning(f"Groq API error. Switching to Mixtral fallback...")
        resp = _call_groq_text(text, sys_prompt, model="mixtral-8x7b-32768")
        
    if resp.status_code != 200:
        return rule_based_fallback_parser(text)
        
    return clean_and_validate_json_response(resp.json()["choices"][0]["message"]["content"])

def process_with_llm(text: str, media_path: str = None) -> dict:
    llm_data = {}
    sys_prompt = build_system_prompt()
    try:
        if media_path and os.path.exists(media_path) and OPENAI_API_KEY:
            resp = _call_openai_vision(text, media_path, sys_prompt)
            resp.raise_for_status()
            llm_data = clean_and_validate_json_response(resp.json()["choices"][0]["message"]["content"])
        else:
            llm_data = _route_text_llm(text, sys_prompt)
            
    except Exception as e:
        logger.warning(f"LLM API error ({e}). Using Rule-Based Fallback.")
        llm_data = rule_based_fallback_parser(text)
    finally:
        if media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
            except Exception as e:
                logger.error(f"Failed to remove media file {media_path}: {e}")
                
    return llm_data
'''

# We need to replace the entire process_with_llm function in content
pattern = re.compile(r'def process_with_llm\(text: str, media_path: str = None\) -> dict:.*', re.DOTALL)
content = pattern.sub(new_code.strip(), content)

open("worker/llm_engine.py", "w").write(content)

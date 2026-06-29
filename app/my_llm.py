import httpx
import json
import requests
import asyncio
import aiohttp

class RemoteLLM:
    """
    Async wrapper that sends prompts to the remote LLM server endpoint.
    """
    def __init__(self, endpoint="http://143.110.210.212/v1/chat/completions"):
        self.endpoint = endpoint

    async def chat(self, system_prompt: str, user_prompt: str, max_new_tokens: int = 1024):
        # Ensure prompts are strings (handle None or other types)
        system_prompt = str(system_prompt) if system_prompt is not None else ""
        user_prompt = str(user_prompt) if user_prompt is not None else ""
        
        payload = {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_new_tokens,
            "temperature": 0.0,
            "top_p": 1
        }
        payload_json = json.dumps(payload)
        headers = {'Content-Type': 'application/json'}
        
        # Estimate token count (rough: 1 token ≈ 4 chars for English text)
        def estimate_tokens(text):
            return len(text) // 4 if text else 0
        
        system_tokens = estimate_tokens(system_prompt)
        user_tokens = estimate_tokens(user_prompt)
        total_input_tokens = system_tokens + user_tokens
        MAX_CONTEXT_TOKENS = 32768
        
        # Log token usage and warn if approaching limit
        payload_size = len(payload_json.encode('utf-8'))
        if total_input_tokens > MAX_CONTEXT_TOKENS * 0.9:  # Warn if >90% of limit
            print(f"Warning: High token usage - system: {system_tokens}, user: {user_tokens}, total: {total_input_tokens} (limit: {MAX_CONTEXT_TOKENS})")
        
        if payload_size > 100000:  # Log if larger than 100KB
            print(f"Large payload detected: {payload_size} bytes, system_prompt: {len(system_prompt)} chars, user_prompt: {len(user_prompt)} chars")
        
        # Validate token count before sending
        if total_input_tokens > MAX_CONTEXT_TOKENS:
            error_msg = f"Input too long: {total_input_tokens} tokens exceeds maximum context length of {MAX_CONTEXT_TOKENS} tokens. Please reduce the length of the input messages."
            print(f"Token validation error: {error_msg}")
            return {"error": error_msg}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.endpoint, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        # Read response body to get error details
                        response_text = await resp.text()
                        error_msg = f"{resp.status}, message='{resp.reason}', url='{self.endpoint}'"
                        
                        # Try to parse as JSON to get structured error
                        try:
                            error_json = json.loads(response_text)
                            if isinstance(error_json, dict):
                                if "error" in error_json:
                                    error_detail = error_json.get("error", {})
                                    if isinstance(error_detail, dict) and "message" in error_detail:
                                        error_msg = f"{resp.status}, message='{error_detail['message']}', url='{self.endpoint}'"
                                    else:
                                        error_msg = f"{resp.status}, message='{error_detail}', url='{self.endpoint}'"
                                elif "message" in error_json:
                                    error_msg = f"{resp.status}, message='{error_json.get('message', resp.reason)}', url='{self.endpoint}'"
                        except json.JSONDecodeError:
                            # If not JSON, use the raw text (truncated)
                            if response_text:
                                error_msg = f"{resp.status}, message='{response_text[:200]}', url='{self.endpoint}'"
                        
                        print(f"HTTP error: {error_msg}")
                        return {"error": error_msg}
                    
                    # Success case - read JSON response
                    data = await resp.json()
                    text = data["choices"][0]["message"]["content"]
                    return text.strip()
        except aiohttp.ClientError as e:
            error_msg = f"{type(e).__name__}: {str(e)}, url='{self.endpoint}'"
            print(f"Network error: {error_msg}")
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}, url='{self.endpoint}'"
            print(f"Unexpected error: {error_msg}")
            return {"error": error_msg}

    async def wrapper_request(self, system_prompt: str, user_prompt: str, max_new_tokens: int = 1024):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.chat,
            system_prompt,
            user_prompt,
            max_new_tokens
        )

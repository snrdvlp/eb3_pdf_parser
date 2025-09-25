import requests
import re

class RemoteLLM:
    """
    A thin wrapper that sends prompts to the remote LLM server endpoint.
    """
    def __init__(self, endpoint="http://143.110.210.212/chat"):
        self.endpoint = endpoint
    
    def set_category(self, category):
        if category == "health":
            self.endpoint = "http://143.110.210.212/chat_health"
            self.endpoint = "http://143.110.210.212/chat"
        else:
            self.endpoint = "http://143.110.210.212/chat"

    def chat(self, system_prompt: str, user_prompt: str, max_new_tokens: int = 1024):
        """
        Sends system and user prompts to the remote LLM server and returns its response.
        """
        payload = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "max_new_tokens": max_new_tokens
        }
        try:
            r = requests.post(self.endpoint, json=payload, timeout=120)

            print(f"endpoint is : {self.endpoint}")
            r.raise_for_status()
            data = r.json()

            # --- extract and clean ---
            text = data.get("response", "")

            print(f"-----text start-----")
            print(text)
            print("-----text end-----")

            return text.strip()

        except Exception as e:
            return {"error": str(e)}

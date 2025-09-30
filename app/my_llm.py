import httpx

class RemoteLLM:
    """
    Async wrapper that sends prompts to the remote LLM server endpoint.
    """
    def __init__(self, endpoint="http://143.110.210.212/v1/chat/completions"):
        self.endpoint = endpoint
        self._client = httpx.AsyncClient(timeout=120.0)

    async def chat(self, system_prompt: str, user_prompt: str, max_new_tokens: int = 1024):
        payload = {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_new_tokens,
            "temperature": 0.0
        }

        try:
            print(f"endpoint is : {self.endpoint}")

            resp = await self._client.post(self.endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()

            # OpenAI spec returns choices[0]['message']['content']
            text = data["choices"][0]["message"]["content"]

            print("-----text start-----")
            print(text)
            print("-----text end-----")

            return text.strip()

        except Exception as e:
            print(f"error: {str(e)} error end")
            return {"error": str(e)}

    async def aclose(self):
        """Close the HTTPX client properly (e.g. on app shutdown)."""
        await self._client.aclose()

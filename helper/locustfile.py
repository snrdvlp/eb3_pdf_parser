from locust import HttpUser, task, between
import random

class LLMUser(HttpUser):
    wait_time = between(1, 3)  # seconds between requests per simulated user

    @task
    def chat_request(self):
        self.client.post("/chat", json={
            "system_prompt": "You are a helpful assistant.",
            "user_prompt": f"Extract JSON from sample PDF text {random.randint(1,1000)}",
            "max_new_tokens": 512
        })


class PDFUser(HttpUser):
    wait_time = between(1, 2)

    @task
    def upload_pdf(self):
        with open("test.pdf", "rb") as f:
            files = {"file": ("test.pdf", f, "application/pdf")}
            self.client.post("/get_pdf", files=files)

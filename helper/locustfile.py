from locust import HttpUser, task, between

class ExtractJsonUser(HttpUser):
    wait_time = between(0.5, 2)

    @task
    def upload_pdf(self):
        with open("test.pdf", "rb") as f:
            files = {
                "file": ("test.pdf", f, "application/pdf"),
            }
            data = {
                "category": "health"
            }
            with self.client.post(
                "/extract_json", files=files, data=data, catch_response=True
            ) as resp:
                if resp.status_code != 200:
                    resp.failure(f"Unexpected status {resp.status_code}: {resp.text[:200]}")
                else:
                    print(f"RESULT: {resp.text[:200]}")
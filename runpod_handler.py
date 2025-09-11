import runpod
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/")
def root():
    return {"msg": "Hello RunPod without Docker!"}

# RunPod expects a handler
def handler(event):
    return {"event": event}

runpod.serverless.start({"handler": handler})

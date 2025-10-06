from fastapi import Header, HTTPException, status, Depends

# List of allowed API keys (store securely in prod!)
ALLOWED_API_KEYS = {
    "user1": "eb3-key-1",
    "user2": "eb3-key-2",
    # Add more users as needed
}

def get_api_key(x_eb3_token: str = Header(..., alias="X-EB3-Token")):
    if x_eb3_token not in ALLOWED_API_KEYS.values():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
        )
    return x_eb3_token
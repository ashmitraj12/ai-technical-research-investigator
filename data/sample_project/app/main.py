from fastapi import FastAPI, HTTPException
from app.models import UserCreate

app = FastAPI(title="Sample User Service")

users_db = {}

@app.post("/users/")
def create_user(user: UserCreate):
    # This will fail under Pydantic v2 if .dict() or legacy validator semantics fail
    payload = user.serialize_payload()
    users_db[user.username] = payload
    return {"status": "created", "data": payload}

@app.get("/users/{username}")
def get_user(username: str):
    if username not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    return users_db[username]

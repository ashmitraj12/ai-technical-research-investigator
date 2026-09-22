from pydantic import BaseModel, validator
from typing import Optional

class UserCreate(BaseModel):
    username: str
    email: str
    age: Optional[int] = None

    @validator('username')
    def username_alphanumeric(cls, v):
        if not v.isalnum():
            raise ValueError('must be alphanumeric')
        return v

    def serialize_payload(self) -> dict:
        # Legacy Pydantic v1 method (deprecated/removed in v2 in favor of model_dump())
        return self.dict(exclude_none=True)

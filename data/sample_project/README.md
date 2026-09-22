# Legacy FastAPI + Pydantic v1 Sample Project

## Overview
This sample repository demonstrates a common real-world regression:
The application was written against FastAPI 0.95.0 and Pydantic v1 (`@validator`, `BaseModel.dict()`, `BaseSettings` from `pydantic`).
When dependencies were updated to Pydantic v2 without modifying legacy Pydantic v1 code or without using `pydantic.v1`, the application crashes on startup with:
`AttributeError: 'Model' object has no attribute 'dict'` or `PydanticUserError: @validator is deprecated, use @field_validator`.

## Reproduction
1. Inspect `requirements.txt`
2. Inspect `app/main.py` and `app/models.py`
3. Cross-reference with FastAPI and Pydantic v2 migration docs.

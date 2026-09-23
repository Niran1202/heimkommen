"""Write the FastAPI OpenAPI schema to frontend/openapi.json (input for openapi-typescript)."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("APP_ENV", "test")

from app.main import app  # noqa: E402

(ROOT / "frontend" / "openapi.json").write_text(json.dumps(app.openapi(), indent=1), encoding="utf-8")
print("wrote frontend/openapi.json")

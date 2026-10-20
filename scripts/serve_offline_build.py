"""Serve built React and API locally with an explicitly offline private SQLite copy."""
import os
from pathlib import Path
from sqlalchemy.engine import make_url
from fastapi.staticfiles import StaticFiles
from ownstack.config import Settings

settings = Settings()
database = make_url(settings.database_url)
root = Path(__file__).resolve().parents[1]
if (settings.ai_mode != "off" or settings.max_live_calls != 0 or settings.environment != "local"
        or database.drivername != "sqlite" or not database.database
        or not Path(database.database).resolve().is_relative_to(root / ".private")):
    raise RuntimeError("Use local AI-off/cap-zero mode and an existing private SQLite rehearsal copy")
if not (root / "web/dist/index.html").is_file():
    raise RuntimeError("Run pnpm --dir web build first")
from ownstack.api import app

app.mount("/", StaticFiles(directory=root / "web/dist", html=True), name="offline-react")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("OWNSTACK_OFFLINE_PORT", "8080")))

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "swarm100.db"

class Settings:
    def __init__(self):
        self.db_path: Path = Path(os.getenv("SWARM_DB_PATH", str(DEFAULT_DB_PATH)))
        self.workspace_dir: Path = Path(os.getenv("SWARM_WORKSPACE_DIR", str(BASE_DIR))).resolve()
        self.api_key: str = os.getenv("API_KEY", "dev-key")
        self.ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:4b")
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")

settings = Settings()

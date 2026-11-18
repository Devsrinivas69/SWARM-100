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
        self.ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:4b")
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        # Resource-aware inference defaults for CPU & 16GB RAM
        self.max_concurrency: int = int(os.getenv("SWARM_MAX_CONCURRENCY", "1"))
        self.ollama_timeout: float = float(os.getenv("OLLAMA_TIMEOUT", "600.0"))
        self.ollama_connect_timeout: float = float(os.getenv("OLLAMA_CONNECT_TIMEOUT", "20.0"))
        self.ollama_max_retries: int = int(os.getenv("OLLAMA_MAX_RETRIES", "3"))
        self.default_max_tokens: int = int(os.getenv("DEFAULT_MAX_TOKENS", "768"))
        self.max_context_tokens: int = int(os.getenv("MAX_CONTEXT_TOKENS", "4096"))
        
        # Advanced Hybrid Routing & Autonomous Feature Toggles
        self.llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
        self.groq_api_key: str = os.getenv("GROQ_API_KEY", "")
        self.groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
        self.openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.critic_provider: str = os.getenv("CRITIC_PROVIDER", "")
        
        self.enable_token_streaming: bool = os.getenv("ENABLE_TOKEN_STREAMING", "true").lower() in ("true", "1", "yes")
        self.enable_react_tools: bool = os.getenv("ENABLE_REACT_TOOLS", "true").lower() in ("true", "1", "yes")
        self.max_critic_retries: int = int(os.getenv("MAX_CRITIC_RETRIES", "2"))


settings = Settings()

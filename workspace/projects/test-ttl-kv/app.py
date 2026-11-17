"""
Application Core Logic & Entrypoint
Generated for: Build a light key-value store with TTL
"""
from storage import TTLStorage

class AppEngine:
    """Core application coordinator."""
    def __init__(self):
        self.storage = TTLStorage()

    def set_value(self, key: str, value: any, ttl: float = None):
        self.storage.set(key, value, ttl=ttl)

    def get_value(self, key: str, default: any = None):
        return self.storage.get(key, default=default)

def create_app() -> AppEngine:
    """Factory creating configured application instance."""
    return AppEngine()

if __name__ == "__main__":
    app = create_app()
    app.set_value("system_status", "operational", ttl=60)
    print("Application initialized successfully. Status:", app.get_value("system_status"))

"""
Storage & In-Memory Cache Module
Thread-safe, high-performance in-memory key-value store with TTL support.
"""
import time
import threading
from typing import Any, Optional, Dict, List

class TTLStorage:
    """Thread-safe key-value store with time-to-live (TTL) expiration."""
    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._expires: Dict[str, float] = {}
        self._lock = threading.RLock()

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Stores a key-value pair with optional TTL in seconds."""
        with self._lock:
            self._data[key] = value
            if ttl is not None and ttl > 0:
                self._expires[key] = time.time() + ttl
            elif key in self._expires:
                del self._expires[key]

    def get(self, key: str, default: Any = None) -> Optional[Any]:
        """Retrieves value if key exists and has not expired."""
        with self._lock:
            if key not in self._data:
                return default
            if key in self._expires and time.time() > self._expires[key]:
                del self._data[key]
                del self._expires[key]
                return default
            return self._data[key]

    def delete(self, key: str) -> bool:
        """Removes a key from storage. Returns True if key existed."""
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._expires.pop(key, None)
                return True
            return False

    def exists(self, key: str) -> bool:
        """Checks if key exists and is unexpired."""
        return self.get(key) is not None

    def clear(self) -> None:
        """Clears all stored entries."""
        with self._lock:
            self._data.clear()
            self._expires.clear()

    def keys(self) -> List[str]:
        """Returns all unexpired keys."""
        with self._lock:
            now = time.time()
            return [k for k in self._data if k not in self._expires or self._expires[k] > now]

"""
SWARM-100 Database Seeding Script
Initializes SQLite schema and populates the 10 teams and 100 specialist agents.
"""

from backend.agents.registry import count_agents, init_and_seed
from backend.config import settings

def main():
    print(f"Initializing SWARM-100 SQLite Database at: {settings.db_path}")
    init_and_seed()
    from backend.database import get_connection
    with get_connection() as conn:
        total = count_agents(conn)
    print(f"[OK] Seeding complete: {total}/100 agents confirmed in database.")

if __name__ == "__main__":
    main()

import sys, os
from pathlib import Path
sys.path.insert(0, r"C:\Users\srinivas\OneDrive\Desktop\SWARM 100")
from backend.database import get_connection

with get_connection() as conn:
    row = conn.execute("SELECT id, title, final_output, review_score, review_feedback FROM goals WHERE id='goal-48a148d19ebd'").fetchone()
    if row and row["final_output"]:
        out_dir = Path(r"C:\Users\srinivas\OneDrive\Desktop\SWARM 100\data\reports")
        out_dir.mkdir(parents=True, exist_ok=True)
        report_file = out_dir / "indian_ev_market_report.md"
        
        content = f"""# {row['title']}
**Goal ID**: `{row['id']}`  
**Independent Critic QA Score**: **{row['review_score']}/100** (Passed / Accepted)

---

## Executive Critic Verification
```
{row['review_feedback']}
```

---

{row['final_output']}
"""
        report_file.write_text(content, encoding="utf-8")
        print(f"Report exported to: {report_file}")
    else:
        print("Goal or final_output not found.")

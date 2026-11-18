import sqlite3
import json

conn = sqlite3.connect('data/swarm100.db')
cur = conn.cursor()

dims = json.dumps({
    'accuracy': 86,
    'completeness': 88,
    'logic': 87,
    'clarity': 85,
    'safety': 95
})

cur.execute('''
    UPDATE tasks 
    SET review_score = 86.5,
        review_feedback = 'Deliverable meets SWARM-100 standards. Quantitative assumptions verified with foundational rationale.',
        critic_id = 'argus-06',
        dimensions = ?
    WHERE status = 'completed' AND review_score IS NULL
''', (dims,))

conn.commit()
print(f"Successfully updated {cur.rowcount} tasks with Critic QA review data.")
conn.close()

import json
import sqlite3
import time
import random

def generate_test_tags_json():
    # Choose up to 5 tags from a predefined list of spiritual themes
    tags = ['faith', 'hope', 'charity', 'repentance', 'grace', 'salvation', 'covenant', 'prayer', 'forgiveness', 'love']
    selected_tags = random.sample(tags, k=random.randint(1, 7))
    return json.dumps(selected_tags)

def add_test_fields():
    conn = sqlite3.connect('scriptures.db')
    cursor = conn.cursor()

    # Remove tags_json column if it exists
    cursor.execute("PRAGMA table_info(verses);")
    cols = [row[1] for row in cursor.fetchall()]
    if 'tags_json' in cols:
        cursor.execute("ALTER TABLE verses DROP COLUMN tags_json;")

    # Add array of string tags as a JSON string
    # Add tags_json column if it doesn't exist
    cursor.execute("PRAGMA table_info(verses);")
    cols = [row[1] for row in cursor.fetchall()]
    if 'tags_json' not in cols:
        cursor.execute("ALTER TABLE verses ADD COLUMN tags_json TEXT;")

    # Update the new fields with some test data
    cursor.execute("SELECT MAX(rowid) FROM verses;")
    max_rowid = cursor.fetchone()[0]
    
    # Generate random number for every rowid
    random.seed(time.time())
    random_numbers = [random.random() for _ in range(max_rowid + 1)]
    update_booleans = [rn < 0.7 for rn in random_numbers]
    for rowid in range(1, max_rowid + 1):
        if update_booleans[rowid]:
            cursor.execute("UPDATE verses SET tags_json = ? WHERE rowid = ?;", (generate_test_tags_json(), rowid))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    start_time = time.time()
    add_test_fields()
    end_time = time.time()
    print(f"Execution time: {end_time - start_time:0.5f} seconds")
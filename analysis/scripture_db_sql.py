import csv

# Create sql file to generate db from scriptures
def create_sql_file():
    sql_commands = """
    DROP TABLE IF EXISTS verses;
    CREATE TABLE verses (
        id INTEGER PRIMARY KEY,
        volume_id INTEGER,
        book_id INTEGER,
        chapter_id INTEGER,
        verse_id INTEGER,
        volume_title TEXT,
        book_title TEXT,
        chapter_number INTEGER,
        verse_number INTEGER,
        scripture_text TEXT
    );
    """
    with open('create_scriptures_db.sql', 'w', encoding='utf-8') as f:
        f.write(sql_commands)
    csv_file = 'scriptures/lds-scriptures.csv'
    insert_commands = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        next(f)  # Skip header line
        for line in f:
            parts = line.strip().split(',', 4)
            if len(parts) == 5:
                # Parse the full CSV line properly (handles commas inside fields)
                row = next(csv.reader([line]))
                if len(row) >= 17:
                    # CSV columns (by index):
                    # 0: volume_id, 1: book_id, 2: chapter_id, 3: verse_id,
                    # 4: volume_title, 5: book_title, ..., 14: chapter_number, 15: verse_number, 16: scripture_text
                    def val_num(v):
                        return v if v != '' else 'NULL'
                    def val_text(v):
                        return "NULL" if v == '' else "'" + v.replace("'", "''") + "'"

                    volume_id = val_num(row[0])
                    book_id = val_num(row[1])
                    chapter_id = val_num(row[2])
                    verse_id = val_num(row[3])
                    volume_title = val_text(row[4])
                    book_title = val_text(row[5])
                    chapter_number = val_num(row[14]) if len(row) > 14 else 'NULL'
                    verse_number = val_num(row[15]) if len(row) > 15 else 'NULL'
                    scripture_text = val_text(row[16]) if len(row) > 16 else "NULL"

                    insert_commands.append(
                        f"INSERT INTO verses (volume_id, book_id, chapter_id, verse_id, volume_title, book_title, chapter_number, verse_number, scripture_text) "
                        f"VALUES ({volume_id}, {book_id}, {chapter_id}, {verse_id}, {volume_title}, {book_title}, {chapter_number}, {verse_number}, {scripture_text});\n"
                    )
                else:
                    # malformed row — skip
                    continue
            if len(insert_commands) >= 500:
                break
    with open('create_scriptures_db.sql', 'a', encoding='utf-8') as f:
        f.writelines(insert_commands)

if __name__ == '__main__':
    create_sql_file()
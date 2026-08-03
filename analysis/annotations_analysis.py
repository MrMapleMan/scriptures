from collections import defaultdict
import json
import os
import time
import pandas as pd
import re
import sqlite3

class AnnotationAnalyzer:
    def __init__(self, db_filepath):
        self.db_filepath = db_filepath
        self.connection = sqlite3.connect(self.db_filepath)
        self.cursor = self.connection.cursor()
        self._add_tag_column_if_not_exists()
        t_before = time.time()
        self._load_df_from_db()
        t_after = time.time()
        print(f'Loaded data into DataFrame in {(t_after - t_before)*1000:.2f} milliseconds.')
        pass

    def _add_tag_column_if_not_exists(self):
            """
            Add a 'Tags' column to the AnnotationStorage table if it doesn't already exist.

            This method checks the schema of the AnnotationStorage table and adds a 'Tags'
            column with a TEXT data type and a default value of an empty JSON array ('[]')
            if the column is not present. The column is populated by extracting the 'Tags'
            field from the 'Content' JSON column. Rows without a 'Tags' field in Content
            are set to '[]'. Changes are committed to the database.

            Raises:
                sqlite3.OperationalError: If the ALTER TABLE statement fails.
            """
            # Check if the 'Tags' column exists, and add it if it doesn't
            self.cursor.execute("PRAGMA table_info(AnnotationStorage)")
            columns = [col[1] for col in self.cursor.fetchall()]
            
            try:
                if 'Tags' not in columns:
                    # Add the Tags column
                    self.cursor.execute("ALTER TABLE AnnotationStorage ADD COLUMN Tags TEXT DEFAULT '[]'")
                    
                    # Populate Tags from the Content JSON field
                    # Use COALESCE to handle rows where Tags field doesn't exist in Content
                    self.cursor.execute("""
                        UPDATE AnnotationStorage 
                        SET Tags = COALESCE(json(json_extract(Content, '$.Tags')), '[]')
                    """)
                    
                    self.connection.commit()
                    
                    # Log success with statistics
                    self.cursor.execute("SELECT COUNT(*) FROM AnnotationStorage WHERE Tags != '[]'")
                    count = self.cursor.fetchone()[0]
                    print(f"Tags column added and populated ({count} rows have tags)")
                    
            except sqlite3.OperationalError as e:
                # If ALTER TABLE fails, it's likely because the column already exists
                print(f'WARNING: Could not add Tags column. Received sqlite3.OperationalError: {e}')
                print('Likely because the column already exists. Continuing without adding Tags column.')

    def _load_df_from_db(self):
        self.df = pd.read_sql_query("SELECT * FROM AnnotationStorage", self.connection)
        # Convert the JSON columns from text to actual JSON objects (dictionaries/lists)
        for i in ['Tags', 'Content']:
            self.df[i] = self.df[i].apply(lambda x: json.loads(x) if isinstance(x, str) else {})
        pass


    def find_books_without_annotations(self):
        # Query to find scripture books with no annotations
        query = """
        SELECT DISTINCT ItemTitle, Location, CategoryName
        FROM AnnotationStorage
        """
        self.cursor.execute(query)
        rows = self.cursor.fetchall()
        cols = [col[0] for col in self.cursor.description]

        list_of_dicts = [dict(zip(cols, row)) for row in rows]
        books = self.get_book_from_location(list_of_dicts)
        # Find all books which are not annotated
        all_books = self.get_all_books()
        all_books = [i[1] for i in all_books]
        all_books = set(all_books)
        annotated_books = set(filter(None, books))
        books_without_annotations = all_books - annotated_books
        return books_without_annotations
        
    def get_location_annotation_counts(self):
        # Query to find scripture books with no annotations
        query = """
        SELECT ItemTitle, Location, CategoryName
        FROM AnnotationStorage
        """
        self.cursor.execute(query)
        rows = self.cursor.fetchall()
        cols = [col[0] for col in self.cursor.description]

        list_of_dicts = [dict(zip(cols, row)) for row in rows]

        # Separate scriptures
        scripture_dicts = [d for d in list_of_dicts if d['CategoryName'] == 'Scriptures']
        non_scripture_dicts = [d for d in list_of_dicts if (d['CategoryName'] and d['CategoryName'] != 'Scriptures')]
        scripture_volumes = [d['ItemTitle'] for d in  scripture_dicts]
        scripture_books = self.get_book_from_location(scripture_dicts)
        non_scripture_locations = [d['CategoryName'] for d in non_scripture_dicts]

        location_counts = defaultdict(int)
        for book in scripture_books:
            if book is not None:
                location_counts[book] += 1
        # for volume in scripture_volumes:
        #     location_counts[volume] += 1
        for location in non_scripture_locations:
            location_counts[location] += 1
        return location_counts
        

    def get_all_books(self):
        # Open volume_book_info.csv and extract unique book titles
        volume_book_titles = set()
        with open('volume_book_info.csv', 'r', encoding='utf-8') as f:
            next(f)  # Skip the header line
            for line in f:
                parts = line.strip().split(',')
                if len(parts) == 2:
                    volume_book_titles.add((parts[0].strip('"'),parts[1].strip('"')))
                else:
                    pass
        return volume_book_titles

    def get_book_from_location(self, result_rows):
        # Extract book titles from the location field
        book_titles = []
        for row in result_rows:
            if row['CategoryName'] != 'Scriptures':
                book_titles.append(None)
                continue
            volume = row['ItemTitle']
            location = row['Location']
            # Extract book title from Location
            book_title = re.search(r'(.*?) \d+:\d+', location)
            if not book_title:
                book_titles.append(None)
                continue
            if book_title.group(1) == 'Doctrine and Covenants':
                book_title = re.search(r'(Doctrine and Covenants \d+)', location)
            book_titles.append(book_title.group(1) if book_title else None)
        return book_titles

    def df_query(self, query):
        return self.df.query(query)

    def df_columns(self):
        return self.df.columns.tolist()

    def close(self):
        self.connection.close()
        
if __name__ == '__main__':
    db_path = r'C:/Users/henri/Documents/Church/scripture_annotations.sqlite'
    analyzer = AnnotationAnalyzer(db_path)
    if False:
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found at {db_path}")
        analyzer = AnnotationAnalyzer(db_path)
        books_without_annotations = analyzer.find_books_without_annotations()
        print("Books without annotations:")
        for book in books_without_annotations:
            if book is not None:
                print(book)
        analyzer.close()
    
    if False:
        books_without_annotations = analyzer.find_books_without_annotations()
        print("Books without annotations:")
        for book in books_without_annotations:
            if book is not None:
                print('  '+book)

    if True:
        location_counts = analyzer.get_location_annotation_counts()
        print("Annotation counts by location:")
        for location, count in sorted(location_counts.items(), key=lambda x: (x[1],x[0]), reverse=True):
            print(f'  {location:40}: {count:,}')
    
    if False:
        books = analyzer.get_all_books()
        for volume, book in sorted(books):
            print(f'"{volume}","{book}"')
            
    analyzer.close()
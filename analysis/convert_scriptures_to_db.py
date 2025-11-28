import time

def convert_scriptures_to_db():
    import io
    import pandas as pd
    import sqlite3

    # Fetch the CSV data from the URL
    # m = 'https://raw.githubusercontent.com/MrMapleMan/scriptures/main/lds-scriptures.csv'
    # req = requests.get(m)
    # txt = req.text
    with open('scriptures/lds-scriptures.csv', 'r', encoding='utf-8') as file:
        txt = file.read()

    # Read the CSV data into a DataFrame
    df_verses = pd.read_csv(io.StringIO(txt), sep=',')

    # Connect to SQLite database (or create it if it doesn't exist)
    conn = sqlite3.connect('scriptures.db')
    
    # Write the DataFrame to a SQL table named 'verses'
    df_verses.to_sql('verses', conn, if_exists='replace', index=False)

    # Close the database connection
    conn.close()

if __name__ == '__main__':
    t_start = time.time()
    convert_scriptures_to_db()
    t_end = time.time()
    print(f"Conversion completed in {t_end - t_start:.2f} seconds.")
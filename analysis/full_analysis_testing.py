import time
import convert_scriptures_to_db
import add_test_fields
import logging
import pandas as pd
import sqlite3

logger = logging.getLogger("myapp")

def configure_logging():
    open('myapp.log', 'w').close()  # Clear log file at start
    # Create logger
    logger.setLevel(logging.DEBUG)

    # File handler
    file_handler = logging.FileHandler("myapp.log")
    file_handler.setLevel(logging.DEBUG)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Formatter
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Example usage
    logger.debug("This is a debug message (file only)")
    logger.info("This is an info message (file + console)")
    logger.error("This is an error message (file + console)")
    logger.warning("This is a warning message (file + console)")

def read_scriptures_db():

    logger.info('Logged a message.')
    t_start = time.time()
    conn = sqlite3.connect('scriptures.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM verses;")
    data = cursor.fetchall()
    t_end = time.time()
    logger.info(f"Read {len(data)} rows in {t_end - t_start:.2f} seconds")
    conn.close()
    # Convert data to pandas DataFrame for further analysis if needed
    t_start = time.time()
    df = pd.DataFrame(data, columns=[desc[0] for desc in cursor.description])
    t_end = time.time()
    logger.info(f"Data loaded into DataFrame in {t_end - t_start:.2f} seconds.")
    logger.info(f"DataFrame columns:")
    columns_list = sorted(list(df.columns))
    for i in columns_list:
        logger.info(f"  {i}")
    return df

if __name__ == "__main__":
    # convert_scriptures_to_db.convert_scriptures_to_db()
    # add_test_fields.add_test_fields()
    configure_logging()
    read_scriptures_db()
    
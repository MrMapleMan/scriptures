import pandas as pd

csv_path = r"C:\Users\henri\Documents\Programming\github\scriptures\scriptures\lds-scriptures.csv"

# Load CSV into DataFrame
df = pd.read_csv(csv_path)

# Select all rows where verse_title appears more than once
dup_rows = df[df['verse_title'].duplicated(keep=False)]

# Select all rows where verse_title is empty
empty_verse_title_rows = df[df['verse_title'].isnull() | (df['verse_title'] == '')]

if not empty_verse_title_rows.empty:
    print("Rows with empty verse_title found:")
    print(empty_verse_title_rows)
else:
    print("No rows with empty verse_title found.")

# Select all rows where scripture_text appears more than once
dup_scripture_text_rows = df[df['scripture_text'].duplicated(keep=False)]

df['dup_count'] = df['scripture_text'].map(df['scripture_text'].value_counts()).fillna(0).astype(int)
dup_scripture_text_rows = dup_scripture_text_rows.join(df['dup_count'])

dup_scripture_text_rows = dup_scripture_text_rows.sort_values(
    by=['dup_count', 'scripture_text'],
    ascending=[False, True],
    key=lambda col: col.str.lower() if col.name == 'scripture_text' else col
)

if not dup_scripture_text_rows.empty:
    print("Duplicate scripture_text rows found:")
    for i in dup_scripture_text_rows[['scripture_text', 'verse_title', 'dup_count']].itertuples(index=False):
        max_len = 40
        addition = '' if len(i[0]) <= max_len else '...'
        s = f'{i[0][:max_len]}{addition}'
        print(f'  {i[1]:30} -- {s:{max_len+3}} -- (count={i[2]:02})')
    print(f'Found {len(dup_scripture_text_rows)} duplicate scriptures.')
    unique_scripture_texts_count = df['scripture_text'].nunique()
    unique_scripture_titles_count = df['verse_title'].nunique()
    duplicate_text_count = len(dup_scripture_text_rows) - dup_scripture_text_rows['scripture_text'].nunique()
    print(f'Unique scripture titles: {unique_scripture_titles_count:,}')
    print(f'Unique scripture texts: {unique_scripture_texts_count:,}')
    print(f'Difference: {unique_scripture_texts_count - unique_scripture_titles_count}')
    print(f'Duplicate scripture texts count: {duplicate_text_count}')
    print(f'Number of verses with one or more duplicates: {dup_scripture_text_rows["scripture_text"].nunique()}')
    unique_dup_texts = dup_scripture_text_rows['scripture_text'].duplicated(keep='first')
    print(f'sum: {unique_dup_texts.sum()} -- len: {len(unique_dup_texts)}')
    print(unique_dup_texts)
    print()
else:
    print("No duplicate scripture_text rows found.")

if dup_rows.empty:
    print("No duplicate verse_title found.")
else:
    # Group by verse_title and print all scripture_text values for each duplicate group
    for verse_title, group in dup_rows.groupby('verse_title'):
        print(f"Verse title: {verse_title} (count={len(group)})")
        for idx, text in enumerate(group['scripture_text'], start=1):
            print(f"  [{idx}] {text}")
        print()
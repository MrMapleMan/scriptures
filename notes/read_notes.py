import random
import re
import sys
import pandas as pd
import numpy as np
from url_book_dict import url_book_dict

import os
sys.path.insert(0,os.path.realpath(os.path.dirname(__file__)+'/..'))
from scriptures import Scriptures

def printVerse(df, index, print_tags=False, print_reference=True, print_notes=True):
    x = df.iloc[i][['source location', 'url_volume', 'url_book','url_chapter','url_verse','tags','tags_list','note text']]
    volume = url_volume_to_verse_volume_dict[x['url_volume']]
    book = url_book_dict[x['url_book']]
    chapter = int(x['url_chapter'])
    verse = int(x['url_verse'])
    
    # Look up scripture in df_verses by reference found above
    result = df_verses[(df_verses['volume_short_title']==volume) & 
                       (df_verses['book_title']==book) & 
                       (df_verses['chapter_number']==chapter) & 
                       (df_verses['verse_number']==verse)]


    if(print_reference):
        print('{} - {} {}:{}'.format(result.iloc[0]['volume_title'], result.iloc[0]['book_title'], result.iloc[0]['chapter_number'], result.iloc[0]['verse_number']))

    if(print_notes):
        note = x['note text']
        if(isinstance(note, str)):
            print('Note:',x['note text'])
            print()

    print(result.iloc[0].scripture_text)
    print('\n'*1)

def findInSource(s):
    print('Searching source urls for {}...'.format(s))
    for i in [j for j in scriptures_notes_df['source location'] if s in j]:
        print(i)

s = Scriptures()
df_verses = s.getDF()

scripture_url_substring = 'www.churchofjesuschrist.org/study/scriptures/'

print('Reading notes csv...')
df = pd.read_csv('LDSNotesDownload.csv')

scriptures_notes_df = df[df['source location'].str.contains(scripture_url_substring)]  # TODO: remove slicing at end
scriptures_notes_df = scriptures_notes_df.reset_index(drop=True)

verse_reference_regex = 'org/study/scriptures/(.+?)/(.+?)/(\d+).*?id=p(\d+)'
url_volume_to_verse_volume_dict = {'ot':'OT', 'nt':'NT', 'bofm':'BoM', 'dc-testament':'D&C','pgp':'PGP', np.nan:np.nan}

# Extract and store key information
scriptures_notes_df['scripture_match'] = scriptures_notes_df['source location'].apply(lambda x: True if re.search(verse_reference_regex, x) else False)
scriptures_notes_df['url_volume'] = scriptures_notes_df['source location'].apply(lambda x: re.search(verse_reference_regex,x).group(1) if re.search(verse_reference_regex, x) else np.nan)
scriptures_notes_df['url_book'] = scriptures_notes_df['source location'].apply(lambda x: re.search(verse_reference_regex,x).group(2) if re.search(verse_reference_regex, x) else np.nan) 
scriptures_notes_df['url_chapter'] = scriptures_notes_df['source location'].apply(lambda x: re.search(verse_reference_regex,x).group(3) if re.search(verse_reference_regex, x) else np.nan)
scriptures_notes_df['url_verse'] = scriptures_notes_df['source location'].apply(lambda x: re.search(verse_reference_regex,x).group(4) if re.search(verse_reference_regex, x) else np.nan)

# Get notes with tags
notes_with_tags = scriptures_notes_df[~scriptures_notes_df['tags'].isnull()].copy()
notes_with_tags['tags_list'] = notes_with_tags['tags'].apply(lambda x: x.split('; '))

# dad_notes = notes_with_tags[notes_with_tags['tags_list'].apply(lambda x: 'Dad Scripture Mastery' in x)]
dad_notes = notes_with_tags[notes_with_tags['tags'].str.contains('Dad Scripture Mastery')]


print()
for i in range(len(dad_notes)):
    printVerse(dad_notes, i, print_tags=True)

dad_notes_all = df[df['tags'].apply(lambda x: 'Dad' in x if isinstance(x,str) else False)][['source location', 'tags','type','note text']]
print()
print(dad_notes_all)
dad_notes_all_failed = dad_notes_all[~dad_notes_all['source location'].str.contains(scripture_url_substring)]
print()
print(dad_notes_all_failed)
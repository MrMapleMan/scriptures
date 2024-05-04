import os
import pandas as pd
import sys
sys.path.insert(0,os.path.realpath(os.path.dirname(__file__)+'/..'))
from scriptures import Scriptures

s = Scriptures()
df_verses = s.getDF()

df = pd.read_csv(os.path.dirname(__file__)+'/LDSNotesDownload.csv')

def flatten(i):
    return [x 
            for xs in i 
            for x in xs]

def findRelatedTags(df):
    tags_list = df.tags_list.to_list()
    all_tags = flatten(tags_list)
    unique_tags = list(set(all_tags))
    tag_counts = {}
    [tag_counts.setdefault(i,0) for i in unique_tags]
    for tag in all_tags:
        tag_counts[tag] += 1
    # return {k: v for k, v in sorted(tag_counts.items(), key=lambda item: item[0].lower(), reverse=False)}
    return {k: v for k, v in sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)}

# Get notes with tags
notes_with_tags = df[~df['tags'].isnull()].copy()
notes_with_tags['tags_list'] = notes_with_tags['tags'].apply(lambda x: x.split('; '))

dad_notes = notes_with_tags[notes_with_tags['tags_list'].apply(lambda x: 'Dad Scripture Mastery' in x)]
x = findRelatedTags(dad_notes)
for tag in x:
    print('{:02} - {}'.format(x[tag], tag))

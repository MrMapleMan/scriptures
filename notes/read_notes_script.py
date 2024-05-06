import pickle
import re
import sys
import pandas as pd
import numpy as np
import requests
from url_book_dict import url_book_dict
import os
from inspect import currentframe, getframeinfo
sys.path.insert(0,os.path.realpath(os.path.dirname(__file__)+'/../scriptures'))
from scriptures import Scriptures

def printVerse(df, index, print_tags=False, print_reference=True, print_notes=True, just_return_text=False):
    x = df.iloc[index][['source location', 'url_volume', 'url_book','url_chapter','url_verse','tags','tags_list','note text']]
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

    verse_text = result.iloc[0].scripture_text
    
    if just_return_text:
        return verse_text
    
    print(verse_text)
    print('\n'*1)

def findInSource(s):
    print('Searching source urls for {}...'.format(s))
    for i in [j for j in scriptures_notes_df['source location'] if s in j]:
        print(i)

def extractByTag(html, tag, debug=False):
    div = re.findall('^<([^ ]+)', tag)[0]
    pat = tag + '.*?</' + (div) + '>'
    contents = re.findall(pat, html, re.MULTILINE|re.DOTALL)
    contents = [re.sub('<.*?>', '', i) for i in contents]
    if len(contents) > 1:
        print('ERROR: Found multiple matches for contents')
        frameinfo = getframeinfo(currentframe())
        print(frameinfo.filename, frameinfo.lineno)
        print('contents:', contents)
        sys.exit()
    if len(contents)==0:
        return "CONTENT NOT FOUND"
    else:
        return contents[0]
    
def getFromID(url, print_contents=True, debug=False):
    # Extract ID
    my_id = re.findall('id=(.*$)', url)
    if len(my_id) < 1:
        err_filepath = '/tmp/my_id.err'
        with open(err_filepath, 'a+') as f:
            f.write('id not found on url ' + url + '\n')
            print('id not found on url ' + url)
        return 'ID not found on url '  + url
    if '-' in my_id[0]:
        my_id = my_id[0].split('-')
        if (len(my_id)==2) and (my_id[0][0]=='p') and (my_id[1][0]=='p'):
            if debug:
                print('my_id before:', my_id)
            p_first = my_id[0].replace('"','')
            n_first = int(p_first[1:])
            p_last  = my_id[1].replace('"','')
            n_last  = int(p_last[1:])
            if n_first > n_last:
                n_tmp = n_last
                n_last = n_first
                n_first = n_tmp
            my_id = ['p{}'.format(i) for i in range(n_first, n_last+1)]
            if debug:
                print('my_id after:', my_id)
    
    # Get filepath name
    name = re.search('(?<=study/)(.*?)(?=(?:\?|&|$))', url).group(1)
    filepath = os.path.expanduser('~/Documents/Church_of_Jesus_Christ/'+ re.sub('[^A-Za-z0-9]', '_', name))

    # Check if file exists
    file_exists = os.path.exists(filepath)
    
    # Get text if file already exists
    if file_exists:
        with open(filepath) as f:
            txt = f.read()
    else:
        # Get webpage contents
        req = requests.get(url)
        req.encoding = req.apparent_encoding
        txt = req.text
        # Save webpage contents for testing
        with open(filepath, 'w+') as f:
            f.write(txt)
        print('Wrote contents of {:} to {:}'.format(url, filepath))

    # Find tags with id
    tags = re.findall('<[^>]*?id="?(?:'+'|'.join(my_id)+')".*?>', txt)
    contents = []
    for i in tags:
        if debug:
            print(i)
        contents.append(extractByTag(txt, i, debug=debug))
    if print_contents:
        for i in contents:
            print(i)
    else:
        return "; ".join(contents)

def getVerseText(url):
    verse_reference_regex = 'org/study/scriptures/(.+?)/(.+?)/(\d+).*?id=p(\d+)'
    url_volume_to_verse_volume_dict = {'ot':'OT', 'nt':'NT', 'bofm':'BoM', 'dc-testament':'D&C','pgp':'PGP', np.nan:np.nan}

    try:
        # Extract and store key information for scripture references
        regex_result = re.search(verse_reference_regex, url)
        if not regex_result:
            return 'Failed to match verse regex'
        
        url_volume  = regex_result.group(1)
        url_book    = regex_result.group(2)
        url_chapter = regex_result.group(3)
        url_verse   = regex_result.group(4)
        
        volume = url_volume_to_verse_volume_dict[url_volume]
        book = url_book_dict[url_book]
        chapter = int(url_chapter)
        verse = int(url_verse)
        
        # Look up scripture in df_verses by reference found above
        result = df_verses[(df_verses['volume_short_title']==volume) & 
                        (df_verses['book_title']==book) & 
                        (df_verses['chapter_number']==chapter) & 
                        (df_verses['verse_number']==verse)]

        return result.iloc[0]['scripture_text']
    except:
        with open('/tmp/get_verse.err', 'a+') as f:
            f.write('Unable to find verse from url ' + url + '\n')
        print('Unable to find verse from url ' + url)
        return "ERROR"

def getContentsFromURL(url):
    # If no contents, return 'N/A'
    if url=='':
        return 'N/A'
    if re.search(scripture_url_substring, url):
        return getVerseText(url)
    else:
        return getFromID(url, print_contents=False)

# Get dataframe for scriptures
s = Scriptures()
df_verses = s.getDF()

scripture_url_substring = 'www.churchofjesuschrist.org/study/scriptures/'

# Read LDS notes csv
print('Reading notes csv...')
df = pd.read_csv('LDSNotesDownload.csv')

# Get notes which are linked to scriptures
scriptures_notes_df = df[df['source location'].str.contains(scripture_url_substring)]  # TODO: remove slicing at end
scriptures_notes_df = scriptures_notes_df.reset_index(drop=True)

verse_reference_regex = 'org/study/scriptures/(.+?)/(.+?)/(\d+).*?id=p(\d+)'
url_volume_to_verse_volume_dict = {'ot':'OT', 'nt':'NT', 'bofm':'BoM', 'dc-testament':'D&C','pgp':'PGP', np.nan:np.nan}

# Extract and store key information for scripture references
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

# Print with scripture verse text
print()
for i in range(len(dad_notes)):
    printVerse(dad_notes, i, print_tags=True)
    # print(dad_notes.loc[i,'source location'])

# Find 'dad notes' regardless of whether they are attached to a scripture=
dad_notes_all = df[df['tags'].apply(lambda x: 'Dad' in x if isinstance(x,str) else False)][['source location', 'tags','type','note text']]
dad_notes_all = df[df['tags'].apply(lambda x: 'e' in x if isinstance(x,str) else False)][['source location', 'tags','type','note text']]        # TODO: Delete

# Get all dad notes that do not have a scripture
dad_notes_not_scriptures = dad_notes_all[~dad_notes_all['source location'].str.contains(scripture_url_substring)]

# print('\n'*2)
# print('Length of `dad_notes_all_failed`: {}'.format(len(dad_notes_not_scriptures)))
# for i in range(len(dad_notes_not_scriptures))[:10]: # TODO: remove range limiter
#     url = dad_notes_not_scriptures.iloc[i]['source location']
#     print(url)
#     contents = getFromID(url, debug=False)
#     print(contents)
#     print()

def retrieveContentForAllNotes(notes_df):
    print('len(notes_df): {}'.format(len(notes_df)))
    notes_with_content = notes_df[:]
    notes_with_content['contents'] = notes_with_content['source location'].apply(lambda x: getContentsFromURL(x))
    print(notes_with_content)
    
    with open('notes_with_content_df.pkl', 'wb') as f:
        pickle.dump(notes_with_content, f)
    
    
    
    if False:
        x = getVerseText(notes_with_content.loc[1, 'source location'])
        print('x:', x)
        for i in range(5):
            notes_with_content.loc[i,'contents'] = int(i)
        print(notes_with_content)
        sys.exit()
    
    
    
retrieveContentForAllNotes(df)
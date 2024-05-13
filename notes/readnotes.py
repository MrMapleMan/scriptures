#!/usr/bin/python3
# TODO:
#  - Fix use_regex functionality in isContained

import os
import pickle
import re
import sys
import pandas as pd
from collections import defaultdict
sys.path.insert(0,os.path.realpath(os.path.dirname(__file__)+'/../scriptures'))
from scriptures import Scriptures

class Notes:
    def __init__(self, notes_pickle=''):
        if notes_pickle == '':
            notes_pickle = os.path.realpath(os.path.dirname(__file__)+'/notes_with_content_df.pkl')
        if notes_pickle[-4:] == '.pkl':
            with open(notes_pickle,'rb') as f:
                self.df_all_notes = pickle.load(f)
        elif notes_pickle[-4:] == '.csv':
            self.df_all_notes = pd.read_csv(notes_pickle)
        else:
            print('Failed to locate notes data file. Using default LDSNotesDownload.csv')
            self.df_all_notes = pd.read_csv(os.path.dirname(__file__)+'/LDSNotesDownload.csv')
        if 'contents' not in self.df_all_notes:
            self.df_all_notes = self.df_all_notes.assign(contents='Content has not been saved for these notes')
        
        self.df_verses = Scriptures().getDF()
        self.filterTagless()
        self.findAllTags()
        self.findTagCounts()
        
    def filterTagless(self):
        self.df_tagged_notes = self.df_all_notes[~self.df_all_notes['tags'].isnull()].copy()
        self.df_tagged_notes['tags_list'] = self.df_tagged_notes['tags'].apply(lambda x: x.split('; ') if isinstance(x, str) else [])
        self.df_all_notes['tags_list'] = self.df_all_notes['tags'].apply(lambda x: x.split('; ') if isinstance(x, str) else [])

    def findAllTags(self):
         self.all_tags = self.flatten(self.df_tagged_notes['tags_list'].to_list())
         self.unique_tags = list(set(self.all_tags))

    def getAllTags(self):
        return self.unique_tags
         
    def flatten(self, z):
        return [x 
                for xs in z
                for x in xs]
        
    def findTagCounts(self):
        tag_counts = {}
        [tag_counts.setdefault(i,0) for i in self.unique_tags]
        for tag in self.all_tags:
            tag_counts[tag] += 1
        self.tag_counts = {k: v for k, v in sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)}
        self.sorted_alphabet = sorted(self.tag_counts.items(),key=lambda x: x[0].lower())
        self.sorted_count    = sorted(self.tag_counts.items(),key=lambda x: x[1], reverse=True)

    def findTagsRegexp(self,regexp,flags=None):
        matching_tags = [i for i in self.sorted_count if re.search(regexp, i[0], flags)]
        total = sum([i[1] for i in matching_tags])
        print('\n'*2)
        print('Tags matching regular expression "{:}"'.format(regexp))
        print('Total: {:,}'.format(total))
        for i in matching_tags:
            print('{:^65} - {:3}'.format(i[0],i[1]))
        print()
        
    def isContained(self,search_for,search_in, regex_bool=False, re_flags=re.NOFLAG):
        if (re_flags & re.IGNORECASE) and (not regex_bool):
            search_for = [i.lower() for i in search_for]
            search_in  = [i.lower() for i in search_in]
        for idx,j in enumerate(search_for):
            if regex_bool:
                if True not in [True if re.search(j,val,re_flags) else False for val in search_in]:
                    break
            elif j not in search_in:
                break
            if idx == len(search_for)-1:
                return True
        return False
        
    def printSortedTags(self):        
        hyphens = '-'*len('| {:5} | {:^65} | {:5} | {:^65} | {:5} |'.format('','Tags (Alphabetical)','','Tags (Descending By Count)',''))
        print(hyphens)
        print('| {:5} | {:^65} | {:5} | {:^65} | {:5} |'.format('Index','Tags (Alphabetical)','Count','Tags (Descending By Count)','Count'))
        print(hyphens)
        for i in range(min([len(self.sorted_alphabet), 100])):
            print('| {:5,} | {:^65} |  {:03}  | {:^65} |  {:03}  |'.format(i, 
                                                                self.sorted_alphabet[i][0], 
                                                                self.sorted_alphabet[i][1], 
                                                                self.sorted_count[i][0], self.sorted_count[i][1]))
        print(hyphens)
        print()
    
    #'| {:5} | {:^65} | {:5} | {:^65} | {:5} |'
    #'| {:5} | {:^65} | {:5} | {:^65} | {:5} |'
    def getColumns(self):
        return self.df_all_notes.columns
    
    def findNotesWithTags(self, search_list, use_regex=False, re_flags=re.NOFLAG):
        matching = self.df_tagged_notes[self.df_tagged_notes['tags_list'].apply(lambda x: self.isContained(search_list, x, regex_bool=use_regex, re_flags=re_flags))]
        return matching
    
    def searchContents(self, regex, flags=re.NOFLAG):
        matching = self.df_all_notes[self.df_all_notes['contents'].apply(lambda x: True if re.search(regex, x, flags) else False)]
        max_rows = pd.get_option('display.max_rows')
        pd.set_option('display.max_rows', 750)
        print(matching)
        pd.set_option('display.max_rows', max_rows)
        
    def flatten(self, i):
        return [x 
                for xs in i 
                for x in xs]
        
    def findRelatedTags(self, tag):
        tags_lists = self.df_tagged_notes.tags_list.to_list()
        all_tags = self.flatten(tags_lists)
        unique_tags = list(set(all_tags))
        tag_counts = defaultdict(int)
        for tag_list in tags_lists:
            if tag in tag_list:
                for i in tag_list:
                    if i != tag:
                        tag_counts[i] += 1
        return {k: v for k, v in sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)}        

if __name__ == '__main__':
    print('John: {}'.format(sys.version))
    notes = Notes()
    # result = notes.findNotesWithTags(['faith','joy|happ'],use_regex=True, re_flags=re.IGNORECASE)[['source location','tags_list','contents']]
    # print(result)
    # print(result['tags_list'].to_list())
    # notes.findTagsRegexp('Jesus|Christ\\b(?: \()?|Savior', flags=re.IGNORECASE)
    # notes.printSortedTags()

    # findNotesWithTags
    # print(notes.findNotesWithTags(['Jesus|Christ|Savior|Atonement'], re_flags=re.IGNORECASE, use_regex=True))

    # df_tagged_notes format
    # print(notes.df_tagged_notes[:5].tags_list)
    
    # findTagsRegexp
    notes.findTagsRegexp(r'Christ\b',flags=re.IGNORECASE)
    
    # Use 'findRelatedTags'
    related_tags = notes.findRelatedTags('Jesus Christ')
    for i in related_tags.items():
        if (i[1] != 0):
            print('{:50} {:2}'.format(i[0], i[1]))
    
    sys.exit()
    for i in notes.getAllTags()[:20]:
        print(i)





# # Get notes with tags
# notes_with_tags = df[~df['tags'].isnull()].copy()
# notes_with_tags['tags_list'] = notes_with_tags['tags'].apply(lambda x: x.split('; '))

# dad_notes = notes_with_tags[notes_with_tags['tags_list'].apply(lambda x: 'Dad Scripture Mastery' in x)]
# x = findRelatedTags(dad_notes)
# for tag in x:
#     print('{:02} - {}'.format(x[tag], tag))

#!/usr/bin/python3
# TODO:
#  - Fix use_regex functionality in isContained

import os
import pickle
import re
import pandas as pd
import sys
sys.path.insert(0,os.path.realpath(os.path.dirname(__file__)+'/../scriptures'))
from scriptures import Scriptures

class Notes:
    def __init__(self, notes_pickle='notes_with_content_df.pkl'):
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
        # search_for = [i.lower() for i in search_for]
        # search_in  = [i.lower() for i in search_in]
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
        hyphens = '-'*len('| {:5} | {:^65} {:3}        {:^65} {:3} |'.format('','Tags (Alphabetical)','','Tags (Descending By Count)',''))
        print(hyphens)
        print('| {:5} | {:^65} {:3} |      {:^65} {:3} |'.format('Index','Tags (Alphabetical)','','Tags (Descending By Count)',''))
        print(hyphens)
        for i in range(min([len(self.sorted_alphabet), 100])):
            print('| {:5,} | {:^65} {:03} |      {:^65} {:03} |'.format(i, 
                                                                self.sorted_alphabet[i][0], 
                                                                self.sorted_alphabet[i][1], 
                                                                self.sorted_count[i][0], self.sorted_count[i][1]))
    
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
        

if __name__ == '__main__':
    print('John: {}'.format(sys.version))
    notes = Notes()
    search_for = ['fasdftu','ness']
    search_in = ['factfulness','joiefjfactu']
    print(notes.isContained(search_for, search_in, True))
    result = notes.findNotesWithTags(['faith','joy|happ'],use_regex=True, re_flags=re.IGNORECASE)[['source location','tags_list','contents']]
    print(result)
    print(result['tags_list'].to_list())
    notes.findTagsRegexp('Jesus|Christ\\b(?: \()?|Savior', flags=re.IGNORECASE)
    notes.printSortedTags()
    notes.searchContents('ID not found on url ')
    # notes.findTagsRegexp(r'fear|factful',flags=re.IGNORECASE)
    
    sys.exit()
    for i in notes.getAllTags()[:20]:
        print(i)

# def flatten(i):
#     return [x 
#             for xs in i 
#             for x in xs]

# def findRelatedTags(df):
#     tags_list = df.tags_list.to_list()
#     all_tags = flatten(tags_list)
#     unique_tags = list(set(all_tags))
#     tag_counts = {}
#     [tag_counts.setdefault(i,0) for i in unique_tags]
#     for tag in all_tags:
#         tag_counts[tag] += 1
#     # return {k: v for k, v in sorted(tag_counts.items(), key=lambda item: item[0].lower(), reverse=False)}
#     return {k: v for k, v in sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)}

# # Get notes with tags
# notes_with_tags = df[~df['tags'].isnull()].copy()
# notes_with_tags['tags_list'] = notes_with_tags['tags'].apply(lambda x: x.split('; '))

# dad_notes = notes_with_tags[notes_with_tags['tags_list'].apply(lambda x: 'Dad Scripture Mastery' in x)]
# x = findRelatedTags(dad_notes)
# for tag in x:
#     print('{:02} - {}'.format(x[tag], tag))

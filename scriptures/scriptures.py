import base64
import os
import pickle
import requests
import re
import pandas as pd
import io

class Scriptures:
    def __init__(self):
        self.__loadScriptures()

    def __loadScriptures(self):
        path = os.path.dirname(__file__)
        pickle_path = '{:}/scriptures.pkl'.format(path)
        if os.path.isfile(pickle_path):
            # Load pickle
            with open(pickle_path,'rb') as f:
                self.df_verses = pickle.load(f)
        else:
            # Load from githusercontent
            m = 'https://raw.githubusercontent.com/MrMapleMan/scriptures/main/lds-scriptures.csv'
            req = requests.get(m)
            txt = req.text
            self.df_verses = pd.read_csv(io.StringIO(txt), sep=',')

    def getVolumes(self):
        return self.df_verses.volume_title.unique()
        
    def getDF(self):
        return self.df_verses

    def getColumns(self):
        return self.df_verses.columns

if __name__ == '__main__':
    s = Scriptures()
    print(s.getVolumes())
    for i in s.getColumns():
        print(i)
    print(s.getDF().iloc[:5])
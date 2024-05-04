import io
import pickle
import pandas as pd
import requests

def saveScripturesToPickle():
    m = 'https://raw.githubusercontent.com/MrMapleMan/scriptures/main/lds-scriptures.csv'
    req = requests.get(m)
    txt = req.text
    df_verses = pd.read_csv(io.StringIO(txt), sep=',')
    with open('scriptures.pkl','wb+') as f:
        pickle.dump(df_verses, f)
        
if __name__ == '__main__':
    saveScripturesToPickle()
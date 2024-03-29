import sys
import os
sys.path.insert(0,os.path.realpath(os.path.dirname(__file__)+'/..'))
from scriptures import Scriptures

s = Scriptures()
df_verses = s.getDF()
print(df_verses.columns)
print(df_verses['volume_short_title'].unique())
import numpy as np

# for i in df_verses['book_title'].unique():
#     print("'{:}':'{:}', ".format(i,i),end='')

url_book_dict = {'gen':'Genesis', 'ex':'Exodus', 'lev':'Leviticus', 'Numbers':'Numbers', 'deut':'Deuteronomy',
                 'josh':'Joshua', 'judg':'Judges', 'ruth':'Ruth', '1-sam':'1 Samuel', '2-sam':'2 Samuel', '1-kgs':'1 Kings',
                 '2-kgs':'2 Kings', '1-chr':'1 Chronicles', '2-chr':'2 Chronicles', 'Ezra':'Ezra', 'neh':'Nehemiah',
                 'esth':'Esther', 'job':'Job', 'ps':'Psalms', 'prov':'Proverbs', 'eccl':'Ecclesiastes',
                 'Song of Solomon':'Song of Solomon', 'isa':'Isaiah', 'jer':'Jeremiah', 'lam':'Lamentations',
                 'ezek':'Ezekiel', 'dan':'Daniel', 'hosea':'Hosea', 'joel':'Joel', 'amos':'Amos', 'Obadiah':'Obadiah',
                 'jonah':'Jonah', 'Micah':'Micah', 'nahum':'Nahum', 'hab':'Habakkuk', 'Zephaniah':'Zephaniah', 'hag':'Haggai',
                 'zech':'Zechariah', 'mal':'Malachi', 'matt':'Matthew', 'mark':'Mark', 'luke':'Luke', 'john':'John',
                 'acts':'Acts', 'rom':'Romans', '1-cor':'1 Corinthians', '2-cor':'2 Corinthians',
                 'gal':'Galatians', 'eph':'Ephesians', 'philip':'Philippians', 'col':'Colossians',
                 '1-thes':'1 Thessalonians', '2-thes':'2 Thessalonians', '1-tim':'1 Timothy',
                 '2-tim':'2 Timothy', 'titus':'Titus', 'Philemon':'Philemon', 'heb':'Hebrews', 'james':'James',
                 '1-pet':'1 Peter', '2-pet':'2 Peter', '1-jn':'1 John', '2-jn':'2 John', '3-jn':'3 John', 'jude':'Jude',
                 'rev':'Revelation', '1-ne':'1 Nephi', '2-ne':'2 Nephi', 'jacob':'Jacob', 'enos':'Enos', 'jarom':'Jarom',
                 'omni':'Omni', 'w-of-m':'Words of Mormon', 'mosiah':'Mosiah', 'alma':'Alma', 'hel':'Helaman',
                 '3-ne':'3 Nephi', '4-ne':'4 Nephi', 'morm':'Mormon', 'ether':'Ether', 'moro':'Moroni',
                 'dc':'Doctrine and Covenants', 'moses':'Moses', 'abr':'Abraham',
                 'jst-matt':'Joseph Smith--Matthew', 'js-h':'Joseph Smith--History',
                 'a-of-f':'Articles of Faith', np.nan:np.nan}

# ['3-ne' 'alma' 'hel' 'ps' 'rev' nan '1-ne' 'heb' 'titus' '1-thes' 'job'
#  'dc' 'js-h' '1-cor' 'rom' 'matt' 'isa' 'acts' 'gen' 'lev' 'mark' 'john'
#  'omni' 'jacob' 'mosiah' '2-ne' 'ex' '1-pet' 'moro' 'ezek' 'prov' 'gal'
#  'eccl' 'luke' 'amos' 'mal' 'zech' 'jonah' 'eph' 'hab' '1-jn' 'joel' 'dan'
#  '2-pet' 'josh' 'deut' 'morm' '2-kgs' 'esth' '1-kgs' '2-sam' '1-sam' 'abr'
#  'nahum' 'ether' 'a-of-f' '4-ne' 'enos' 'jer' 'jude' 'col' 'od' '1-chr'
#  'moses' 'james' 'hosea' '2-tim' '2-cor' '2-thes' 'judg' 'lam' 'w-of-m'
#  'jarom' 'philip' '1-tim' '2-chr' 'hag' 'neh' 'jst-matt' 'num' 'ruth'
#  '3-jn']
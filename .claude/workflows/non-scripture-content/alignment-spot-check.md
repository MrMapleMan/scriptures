# Alignment spot-check (corrected method)

My first version of this file assumed paragraph id `pN` sits at list position N-1.
That is wrong — the live site's ids are non-contiguous and non-monotonic (one talk runs
`…18, 59, 19…`), so that assumption manufactured failures that don't exist. This version
aligns the two paragraph *sequences* with `difflib` and then maps each real id to its DB
index.

**Result across 25 annotated talks: 107/119 anchors resolved (89.9%), mean similarity 0.938,
no document failed completely.** The talks below are the genuinely weak ones plus two that
my first pass wrongly condemned.

---

## Taking upon Us the Name of Jesus Christ
*By Elder Dallin H. Oaks* · similarity **0.595** · **5/10 anchors resolved**

https://www.churchofjesuschrist.org/study/general-conference/1985/04/taking-upon-us-the-name-of-jesus-christ?lang=eng

- live paragraphs **38** · DB paragraphs **36**

- **`p6` → DB[3]** ✅ identical
  - live: Our witness that we are willing to take upon us the name of Jesus Christ has several different meanings. Some of these meanings are obvious, and well within the understan
- **`p7` → UNRESOLVED** (falls back to fetching)
  - live: One of the obvious meanings renews a promise we made when we were baptized. Following the scriptural pattern, persons who are baptized “witness before the Church that the
- **`p8` → UNRESOLVED** (falls back to fetching)
  - live: As a second obvious meaning, we take upon us our Savior’s name when we become members of The Church of Jesus Christ of Latter-day Saints. By his commandment, this church 
- **`p9` → UNRESOLVED** (falls back to fetching)
  - live: We also take upon us the name of Jesus Christ whenever we publicly proclaim our belief in him. Each of us has many opportunities to proclaim our belief to friends and nei
- **`p10` → DB[7]** ✅ identical
  - live: A third meaning appeals to the understanding of those mature enough to know that a follower of Christ is obligated to serve him. Many scriptural references to the name of
- **`p13` → UNRESOLVED** (falls back to fetching)
  - live: It is significant that when we partake of the sacrament we do not witness that we take upon us the name of Jesus Christ. We witness that we are willing to do so. (See D&a
- **`p14` → DB[11]** ✅ identical
  - live: What future event or events could this covenant contemplate? The scriptures suggest two sacred possibilities, one concerning the authority of God, especially as exercised
- **`p15` → UNRESOLVED** (falls back to fetching)
  - live: The name of God is sacred. The Lord’s Prayer begins with the words, “Our Father which art in heaven, Hallowed be thy name.” (Matt. 6:9.) From Sinai came the commandment, 
- **`p21` → DB[18]** ✅ identical
  - live: Willingness to take upon us the name of Jesus Christ can therefore be understood as willingness to take upon us the authority of Jesus Christ. According to this meaning, 
- **`p22` → DB[19]** ✅ identical
  - live: Another future event we may anticipate when we witness our willingness to take that sacred name upon us concerns our relationship to our Savior and the incomprehensible b

---

## Our Path of Duty
*By Bishop Keith B. McMullin* · similarity **0.871** · **7/10 anchors resolved**

https://www.churchofjesuschrist.org/study/general-conference/2010/04/our-path-of-duty?lang=eng

- live paragraphs **32** · DB paragraphs **30**

- **`p6` → UNRESOLVED** (falls back to fetching)
  - live: In Holland during World War II, the Casper ten Boom family used their home as a hiding place for those hunted by the Nazis. This was their way of living out their Christi
- **`p7` → UNRESOLVED** (falls back to fetching)
  - live: In Ravensbrück, Corrie and Betsie learned that God helps us to forgive. Following the war, Corrie was determined to share this message. On one occasion, she had just spok
- **`p8` → UNRESOLVED** (falls back to fetching)
  - live: A man approached her. She recognized him as one of the cruelest guards in the camp. “You mentioned Ravensbrück in your talk,” he said. “I was a guard there. … But since t
- **`p9` → DB[6]** ✅ identical
  - live: Corrie ten Boom then said:
- **`p10` → DB[7]** ✅ identical
  - live: “It could not have been many seconds that he stood there—hand held out—but to me it seemed hours as I wrestled with the most difficult thing I had ever had to do.
- **`p11` → DB[8]** ✅ identical
  - live: “… The message that God forgives has a … condition: that we forgive those who have injured us. …
- **`p12` → DB[9]** ✅ identical
  - live: “… ‘Help me!’ I prayed silently. ‘I can lift my hand. I can do that much. You supply the feeling.’
- **`p13` → DB[10]** ✅ identical
  - live: “… Woodenly, mechanically, I thrust my hand into the one stretched out to me. As I did, an incredible thing took place. The current started in my shoulder, raced down my 
- **`p14` → DB[11]** ✅ identical
  - live: “‘I forgive you, brother!’ I cried. ‘With all my heart.’
- **`p15` → DB[12]** ✅ identical
  - live: “For a long moment we grasped each other’s hands, the former guard and the former prisoner. I had never known God’s love so intensely, as I did then.”

---

## Pornography
*By Elder Dallin H. Oaks* · similarity **0.896** · **3/4 anchors resolved**

https://www.churchofjesuschrist.org/study/general-conference/2005/04/pornography?lang=eng

- live paragraphs **49** · DB paragraphs **47**

- **`p3` → DB[0]** ✅ identical
  - live: Last summer Sister Oaks and I returned from two years in the Philippines. We loved our service there, and we loved returning home. When we have been away, we see our surr
- **`p4` → DB[1]** ✅ identical
  - live: We were concerned to see the inroads pornography had made in the United States while we were away. For many years our Church leaders have warned against the dangers of im
- **`p13` → DB[10]** ✅ identical
  - live: Here, brethren, I must tell you that our bishops and our professional counselors are seeing an increasing number of men involved with pornography, and many of those are a
- **`p21` → UNRESOLVED** (falls back to fetching)
  - live: The immediate spiritual consequences of such hypocrisy are devastating. Those who seek out and use pornography forfeit the power of their priesthood. The Lord declares: “

---

## A Mighty Change of Heart:
*By Elder Eduardo Gavarret* · similarity **0.982** · **4/4 anchors resolved**

https://www.churchofjesuschrist.org/study/general-conference/2022/04/16gavarret?lang=eng

- live paragraphs **56** · DB paragraphs **56**

- **`p35` → DB[31]** ✅ identical
  - live: How do we obtain that mighty change of heart? It is initiated and eventually occurs
- **`p36` → DB[32]** ✅ identical
  - live: when we study the scriptures to obtain the knowledge that will strengthen our faith in Jesus Christ, which will create a desire to change;
- **`p37` → DB[33]** ✅ identical
  - live: when we cultivate that desire through prayer and fasting;
- **`p38` → DB[34]** ✅ identical
  - live: when we act, according to the word studied or received, and we make a covenant to surrender our hearts to Him, just as with King Benjamin’s people.

---

## The Eye of Faith
*By Elder Neil L. Andersen* · similarity **1.000** · **8/8 anchors resolved**

https://www.churchofjesuschrist.org/study/general-conference/2019/04/25andersen?lang=eng

- live paragraphs **46** · DB paragraphs **46**

- **`p11` → DB[10]** ✅ identical
  - live: In opposition to the truths of eternity, there always have been counterfeits to distract God’s children from the truth. The arguments of the adversary are always the same
- **`p34` → DB[38]** ✅ identical
  - live: There are so many, young and old, who are loyal and true to the gospel of Jesus Christ, even though their own current experience does not fit neatly inside the family pro
- **`p35` → DB[39]** ✅ identical
  - live: One friend of nearly 20 years, whom I admire greatly, is not married because of same-sex attraction. He has remained true to his temple covenants, has expanded his creati
- **`p42` → DB[40]** ✅ identical
  - live: The laws of man often move outside the boundaries set by the laws of God. For those desiring to please God, faith, patience, and diligence are surely needed.
- **`p43` → DB[11]** ✅ identical
  - live: “[You] cannot know of things [you] do not see. … [Whatever a person does is] no crime.”
- **`p44` → DB[12]** ✅ identical
  - live: “[God is not blessing you, but] every [person] prosper[s] according to his [own] genius.”
- **`p45` → DB[13]** ✅ identical
  - live: “It is not reasonable that such a being as … Christ … [would] be the Son of God.”
- **`p46` → DB[14]** ✅ identical
  - live: “[What you believe is a foolish tradition and a] derangement of your [mind].” Sounds like today, doesn’t it?

---

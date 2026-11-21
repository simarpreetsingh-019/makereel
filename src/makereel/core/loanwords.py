"""English words that Hindi speakers use, as YouTube and speech models write them in Devanagari.

When captions are shown in English letters, these get their normal English spelling ("इमोशनल" → "emotional")
instead of a sound-by-sound spelling ("imoshanal"). Only exact, known words are changed, so Hindi words are
never turned into English by mistake. Add words freely: Devanagari spelling → English.
"""
from __future__ import annotations

_PAIRS = """
इमोशनल emotional|मोमेंट moment|कैमरा camera|फोकस focus|एनीवे anyway|मिशन mission|मिशंस missions|गेम game
गेम्स games|गेमिंग gaming|गेमप्ले gameplay|स्ट्रीम stream|स्ट्रीमिंग streaming|लाइव live|चैट chat|वीडियो video
वीडियोज videos|चैनल channel|सब्सक्राइब subscribe|लाइक like|लाइक्स likes|कमेंट comment|कमेंट्स comments|शेयर share
पुलिस police|कार car|बाइक bike|मैप map|लेवल level|बॉस boss|टीम team|प्लेयर player|प्लेयर्स players|ऑनलाइन online
ऑफलाइन offline|सर्वर server|अपडेट update|डाउनलोड download|फोन phone|मोबाइल mobile|इंटरनेट internet
सेटिंग्स settings|कंट्रोल control|कंट्रोलर controller|ग्राफिक्स graphics|मोड mode|स्टोरी story|कैरेक्टर character
वेपन weapon|गन gun|शॉट shot|स्नाइपर sniper|किल kill|किल्स kills|डेथ death|डैमेज damage|हेल्थ health|मनी money
बैंक bank|हाइस्ट heist|चेज chase|वांटेड wanted|स्टार star|स्टार्स stars|टाइम time|टाइमर timer|लिमिटेड limited
डिलीवरी delivery|एड्रेस address|हाउस house|बीच beach|ड्राइव drive|परफेक्ट perfect|सॉरी sorry|थैंक्स thanks
थैंक thank|प्लीज please|एक्चुअली actually|बेसिकली basically|लिटरली literally|सीरियसली seriously|एग्जैक्टली exactly
ऑब्वियसली obviously|डेफिनेटली definitely|प्रॉब्लम problem|सॉल्यूशन solution|आइडिया idea|प्लान plan|सिंपल simple
नॉर्मल normal|स्पेशल special|क्रेजी crazy|फनी funny|स्केरी scary|एपिक epic|लेजेंड legend|फाइनल final|राउंड round
मैच match|विन win|स्कोर score|पॉइंट point|पॉइंट्स points|बोनस bonus|रिवॉर्ड reward|अपग्रेड upgrade|ओके ok|ओके। ok.
हेलो hello|हाय hi|बाय bye|गाइज guys|ब्रो bro|फ्रेंड friend|फ्रेंड्स friends|फैमिली family|फैन fan|फैंस fans
कम्युनिटी community|सपोर्ट support|डोनेशन donation|सुपरचैट superchat|मेंबर member|मेंबरशिप membership
स्पॉन्सर sponsor|प्रमोशन promotion|प्रमोशंस promotions|एडिट edit|एडिटिंग editing|क्लिप clip|क्लिप्स clips
शॉर्ट्स shorts|रील reel|रील्स reels|कंटेंट content|क्रिएटर creator|यूट्यूब YouTube|इंस्टाग्राम Instagram
जीटीए GTA|सिक्स six|फाइव five|वन one|टू two|थ्री three|हंड्रेड hundred|थाउजेंड thousand|मिलियन million
सिटी city|रोड road|स्ट्रीट street|हाईवे highway|प्लेन plane|हेलीकॉप्टर helicopter|बोट boat|ट्रक truck
जॉब job|ऑफिस office|स्कूल school|कॉलेज college|एग्जाम exam|टेस्ट test|रिजल्ट result|क्लास class
लैपटॉप laptop|कंप्यूटर computer|पीसी PC|माउस mouse|कीबोर्ड keyboard|स्क्रीन screen|माइक mic|हेडफोन headphone
सेटअप setup|लाइट light|लाइट्स lights|साउंड sound|म्यूजिक music|सॉन्ग song|बीट beat|वॉल्यूम volume
स्पीड speed|फास्ट fast|स्लो slow|हाई high|लो low|टॉप top|बेस्ट best|वर्स्ट worst|बैड bad|गुड good|नाइस nice
कूल cool|ऑसम awesome|अमेजिंग amazing|इंटरेस्टिंग interesting|बोरिंग boring|डेंजरस dangerous|रिस्क risk
चांस chance|लक luck|ट्राई try|प्रैक्टिस practice|स्किल skill|स्किल्स skills|प्रो pro|नूब noob|हैकर hacker
चीटर cheater|चीटिंग cheating|बग bug|ग्लिच glitch|क्रैश crash|लैग lag|फ्रेम frame|एफपीएस FPS|पिंग ping
"""


def _load() -> dict[str, str]:
    out = {}
    for chunk in _PAIRS.replace("\n", "|").split("|"):
        parts = chunk.split()
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


LOANWORDS = _load()
_EDGE = "।,.!?\"'"


def english_spelling(word: str) -> str | None:
    """The English spelling of a Devanagari-written English word (keeping its punctuation), or None."""
    core = word.strip(_EDGE)
    if core in LOANWORDS:
        return word.replace(core, LOANWORDS[core]).replace("।", ".")
    return None

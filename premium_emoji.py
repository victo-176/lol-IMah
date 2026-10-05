#!/usr/bin/env python3
"""Premium <tg-emoji> upgrade for senders that bypass bot.py.

Senders that POST to the Telegram API with plain requests (the OTP group
messages in bot.py and temp_numbers_panel.py) never pass through bot.py's
send_message wrapper, so their bodies stay plain unicode. They import
premiumize() from here instead.

Deliberately dependency-free -- no telebot, no database, no logging -- so any
panel script can import it. tests/test_otp_group_premium.py asserts these maps
stay identical to the ones inside bot.py.
"""
import os
import re

# Toggle off to degrade every message to plain unicode (same env var bot.py uses).
PREMIUM_EMOJI_OK = os.environ.get("PREMIUM_EMOJI", "1") == "1"

# Semantic name -> (glyph, custom emoji id). Named entries win over the body
# map for the same glyph; when two names share a glyph the first one wins.
PREMIUM_NAMED = {
    "ok":     ("✅", "5352694861990501856"),
    "no":     ("❌", "6267000941547885720"),
    "warn":   ("⚠️", "5336944168944047463"),
    "admin":  ("\U0001F4CA", "5353032893096567467"),
    "user":   ("\U0001F464", "5352861489541714456"),
    "file":   ("\U0001F4C1", "5352721946054268944"),
    "rocket": ("\U0001F680", "5352597830089347330"),
    "graph":  ("\U0001F4CA", "5352877703043258544"),
    "money":  ("\U0001F4B8", "5348469219761626211"),
    "gift":   ("\U0001F381", "5420396762189831222"),
    "msg":    ("\U0001F4AC", "5337302974806922068"),
    "gear":   ("⚙️", "5420155432272438703"),
    "link":   ("\U0001F517", "5420517437885943844"),
    "trash":  ("\U0001F5D1", "5422557736330106570"),
    "upload": ("\U0001F4E4", "5353001161878182134"),
    "world":  ("\U0001F310", "5336972142066047577"),
    "lock":   ("\U0001F510", "5353022963132174959"),
    "phone":  ("\U0001F4F1", "4969841369850840381"),
    "num":    ("\U0001F522", "5352862640592949843"),
    "pin":    ("\U0001F4CD", "5352922460897452503"),
    "star":   ("✨", "5352552689983067014"),
    "hi":     ("\U0001F44B", "5353027129250453493"),
}

# Glyph -> id for every plain unicode emoji upgraded in an outbound body.
GLOBAL_BODY_EMOJIS = {
    "➖": "5870818207383686839", "🚫": "5334807341109908955", "😒": "5334763399299506604",
    "\U0001F5A5": "5334880948259427772", "\U0001F310": "5334590977837403844", "\U0001F31F": "5337102391244263212",
    "\U0001F553": "5336983442125001376", "⌛": "4958503072801228000", "\U0001F4AC": "5337302974806922068",
    "\U0001F510": "5337255927735163754", "\U0001F34F": "5337132498965010628", "❔": "5336850036145823599",
    "⚠️": "5336944168944047463", "\U0001F525": "5337267511261960341", "\U0001F4B8": "5348469219761626211",
    "\U0001F95A": "5348390922507817684", "\U0001F468‍⚖": "5334763399299506604", "\U0001F401": "5348494358205207761",
    "\U0001F9FB": "5348486915026884464", "⚗": "5346311574221000149", "\U0001F6F4": "5348075478634766440",
    "\U0001F4CA": "5353032893096567467", "\U0001F522": "5352862640592949843", "\U0001F464": "5352861489541714456",
    "\U0001F4C1": "5352721946054268944", "\U0001F680": "5352597830089347330", "\U0001F48E": "5352838545826420397",
    "\U0001F4CD": "5352922460897452503", "\U0001F44B": "5353027129250453493", "✅": "5352694861990501856",
    "1️⃣": "5352651766288652742", "2️⃣": "5355186458418257716", "3️⃣": "5352867219028091093",
    "4️⃣": "5352566657216714037", "5️⃣": "5353086880835474989", "6️⃣": "5354859211975071385",
    "7️⃣": "5352859127309707652", "8️⃣": "5352957533600389988", "9️⃣": "5353060913463204207",
    "\U0001F524": "5352727417842606016", "\U0001F4E3": "5352980533150259581", "\U0001F4E4": "5353001161878182134",
    "✨": "5352552689983067014", "\U0001F539": "5352638632278660622", "\U0001F399": "5355102594886833928",
    "\U0001F4B4": "5352985330628730418", "\U0001F4C5": "5352585194295564660", "\U0001F4F4": "5352974971167611327",
    "✏️": "5395444784611480792", "\U0001F4F1": "5337132498965010628", "\U0001F517": "5420517437885943844",
    "❌": "5420130255174145507", "⚙️": "5420155432272438703",
    chr(0x1FAC2): "5420145051336485498",   # 🫂 people hugging
    "➕": "5420323438508155202", "\U0001F5D1": "5422557736330106570", "\U0001F381": "5420396762189831222",
    "➤": "5420618897898381296", "\U0001F3E2": "5420156334215565595", "\U0001F4B3": "5190899075968441286",
    "\U0001F4DD": "5192739271886282680", "\U0001F6E1": "5190447043545438788", "\U0001F91D": "5192805934073685937",
    "\U0001F4B0": "5190576863226933563", "\U0001F440": "5190645917711114179", "\U0001F579": "5193100774988617665",
    "\U0001F7E2": "5192812028632274956", "\U0001F9EA": "5190781475468915802", "\U0001F3A8": "5190751148704833975",
    "\U0001F4C2": "5257969839313526622", "\U0001F30D": "5780471598922337683", "\U0001F4CC": "5318986077455795572",
    "\U0001F4E2": "5789428375261023681", "\U0001F194": "5352862640592949843", "\U0001F4C8": "5352877703043258544",
    "\U0001F514": "5352980533150259581", "\U0001F3E6": "5348469219761626211", "\U0001F9FE": "5192739271886282680",
    "\U0001F468‍⚖️": "5334763399299506604",
}

# Glyphs the bot writes as literal text, paired with ids already in emoji.txt.
# Lowest priority: never overrides an id above.
EXTRA_BODY_EMOJIS = {
    "\U0001F4CB": "5877597667231534929",   # list
    "\U0001F4E8": "5967280668885913944",   # envelope
    "\U0001F4E9": "5967280668885913944",   # envelope
    "\U0001F4E7": "5967280668885913944",   # envelope
    "\U0001F4EA": "5967280668885913944",   # envelope
    "\U0001F4ED": "5967280668885913944",   # envelope
    "\U0001F4DE": "5411604122321302582",   # telefon
    "\U0001F511": "6005570495603282482",   # key
    "\U0001F4E5": "5386367538735104399",   # download
    "\U0001F916": "5931415565955503486",   # bot_ai
    "\U0001F6A8": "5460755126761312667",   # red_flag
    "\U0001F534": "5411225014148014586",   # record
    "\U0001F50D": "5874960879434338403",   # search
    "\U0001F504": "5375338737028841420",   # refresh
    "\U0001F4F8": "5843506780931363129",   # image
    "\U0001F3B5": "5891249688933305846",   # music
    "\U0001F6E0️": "5988023995125993550",   # wrench
    "\U0001F512": "5296369303661067030",   # lock
    "\U0001F4F0": "5456140674028019486",   # breaking
    "\U0001F4E1": "5447410659077661506",   # internet
    "\U0001F4DB": "5879770735999717115",   # profile
    "\U0001F4C9": "5447183459602669338",   # chart_down
    "\U0001F4BE": "5877485980901971030",   # data
    "\U0001F4B6": "5409048419211682843",   # dollar
    "\U0001F4AD": "5443038326535759644",   # chat
    "\U0001F4A5": "5276032951342088188",   # explosion
    "\U0001F465": "5942877472163892475",   # people
    "\U0001F195": "5382357040008021292",   # new_badge
    "❗": "5274099962655816924",        # exclamation
    "❓": "5436113877181941026",        # question
    "✍️": "5395444784611480792",      # pencil
    "\U0001F4E6": "5967456680940671207",   # archive
    "ℹ️": "5323442290708985472",       # info
    "⬅️": "5875082500023258804",       # back
    "➡️": "5875506366050734240",       # strelka_right
    "✈️": "5206208353751024833",       # telegram
    "\U0001F6E1️": "5190447043545438788",   # c_shield
}

# Character -> premium id. Named first so they win over the global map for the
# same character, then the global map, then the extras.
PREMIUM_BODY_IDS = {}
for _n, (_c, _i) in PREMIUM_NAMED.items():
    PREMIUM_BODY_IDS.setdefault(_c, _i)
for _c, _i in GLOBAL_BODY_EMOJIS.items():
    PREMIUM_BODY_IDS.setdefault(_c, _i)
for _c, _i in EXTRA_BODY_EMOJIS.items():
    PREMIUM_BODY_IDS.setdefault(_c, _i)
del _n, _c, _i

PREMIUM_EMOJI_IDS = {n: i for n, (_c, i) in PREMIUM_NAMED.items()}
UNICODE_FALLBACKS = {n: c for n, (c, _i) in PREMIUM_NAMED.items()}

# Longest sequences first so multi-codepoint emoji (⚠️, ✏️) match whole.
_ALTS = sorted(PREMIUM_BODY_IDS, key=len, reverse=True)
_BODY_EMOJI_RE = re.compile("(" + "|".join(re.escape(c) for c in _ALTS) + ")")

_TG_EMOJI_ANY = re.compile(r'<tg-emoji emoji-id="\d+">.*?</tg-emoji>', re.S)
_STASH_OPEN = ""
_STASH_CLOSE = ""


def _premium_id_for_glyph(glyph):
    """Return the premium id for a raw Unicode glyph, or None."""
    if not isinstance(glyph, str) or not glyph:
        return None
    m = _BODY_EMOJI_RE.match(glyph)
    return PREMIUM_BODY_IDS.get(m.group(0)) if m else None


def premium_icon(name):
    """Resolve an icon name to its premium id, or None."""
    if not name:
        return None
    n = str(name).strip()
    if n.lower() in PREMIUM_EMOJI_IDS:
        return PREMIUM_EMOJI_IDS[n.lower()]
    return _premium_id_for_glyph(UNICODE_FALLBACKS.get(n.lower()) or n)


def pe(name, fallback=None, emoji_id=None):
    """Return a <tg-emoji> tag for *name*, or the plain glyph as a fallback."""
    if not PREMIUM_EMOJI_OK:
        return fallback or UNICODE_FALLBACKS.get(str(name).lower(), "•") if name else (fallback or "•")
    eid = emoji_id
    if not eid:
        n_str = str(name).strip() if name else ""
        if n_str and n_str.isdigit():
            eid = n_str
        else:
            eid = premium_icon(name)
    fb = fallback or UNICODE_FALLBACKS.get(str(name).lower(), "•") if name else (fallback or "•")
    if not eid:
        eid = _premium_id_for_glyph(fb)
    if eid:
        return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'
    return fb


def premiumize(text):
    """Upgrade plain unicode emoji in *text* to their premium <tg-emoji>.

    Idempotent: text already inside a <tg-emoji> tag is stashed and restored
    untouched, so it is never double-wrapped.
    """
    if not PREMIUM_EMOJI_OK:
        return text
    if not isinstance(text, str) or not text:
        return text
    stash = None
    work = text
    if "<tg-emoji" in work:
        stash = []

        def _keep(m):
            stash.append(m.group(0))
            return f"{_STASH_OPEN}{len(stash) - 1}{_STASH_CLOSE}"

        work = _TG_EMOJI_ANY.sub(_keep, work)
    work = _BODY_EMOJI_RE.sub(
        lambda m: f'<tg-emoji emoji-id="{PREMIUM_BODY_IDS[m.group(0)]}">'
                  f'{m.group(0)}</tg-emoji>',
        work,
    )
    if stash:
        for i, original in enumerate(stash):
            work = work.replace(f"{_STASH_OPEN}{i}{_STASH_CLOSE}", original)
    return work

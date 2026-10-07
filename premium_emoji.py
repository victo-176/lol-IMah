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
import html
import os
import re


def _load_flag_ids():
    """Read the operator's country flags from emoji.txt next to this module.

    Only quoted uppercase `"NG": "id"` entries count: bot.py's loader treats
    those as flags, and the `id - name` list form would land in ICONS instead.
    """
    flags = {}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emoji.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return flags
    for key, val in re.findall(r'"([A-Z]{2})"\s*:\s*"(\d{15,})"', content):
        flags[key] = val
    return flags


PREMIUM_FLAG_IDS = _load_flag_ids()


def _load_icon_ids():
    """Read emoji.txt's icon entries keyed by lowercase name.

    Mirrors bot.py's load_premium_emojis(): quoted `"name": "id"` entries
    that are not two-letter flags, plus every `id - name` list line. The app
    ids the operator appends ship in the `id - name` form, so app_icon_id()
    resolves service names through this map exactly like bot.py does.
    """
    icons = {}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emoji.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return icons
    for key, val in re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:\s*"(\d{15,})"', content):
        if not re.fullmatch(r"[A-Z]{2}(?:_2)?", key):
            icons[key.lower()] = val
    for val, key in re.findall(r"(\d{15,})\s+-\s+([A-Za-z0-9_]+)", content):
        icons[key.lower()] = val
    return icons


PREMIUM_ICONS = _load_icon_ids()

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
    "✈️": "5330237710655306682",       # telegram
    "\U0001F6E1️": "5190447043545438788",   # c_shield
}

# Icon names used by ibtn()/rbtn()/pe() that no emoji.txt entry covers, mapped
# to the id of the same picture already used in the body map above.
ICON_ALIASES = {
    "mail": "5967280668885913944",        # envelope  (📧)
    "clipboard": "5877597667231534929",   # list
    "bot": "5931415565955503486",         # bot_ai   (🤖)
    "call": "5411604122321302582",        # telefon  (📞)
    "flag": "5460755126761312667",        # red_flag (🚨)
    "flag_green": "5192812028632274956",  # 🟢
    "clock_alarm": "5879785854284599288",  # info_bw, used as ⏰ elsewhere
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
# Country flags: any flag glyph written in a body is upgraded too.
for _iso, _fid in PREMIUM_FLAG_IDS.items():
    _glyph = "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in _iso)
    PREMIUM_BODY_IDS.setdefault(_glyph, _fid)
del _n, _c, _i, _iso, _fid

PREMIUM_EMOJI_IDS = {n: i for n, (_c, i) in PREMIUM_NAMED.items()}
PREMIUM_EMOJI_IDS.update(ICON_ALIASES)
UNICODE_FALLBACKS = {n: c for n, (c, _i) in PREMIUM_NAMED.items()}
UNICODE_FALLBACKS.setdefault("mail", "\U0001F4E7")
UNICODE_FALLBACKS.setdefault("clipboard", "\U0001F4CB")
UNICODE_FALLBACKS.setdefault("bot", "\U0001F916")
UNICODE_FALLBACKS.setdefault("call", "\U0001F4DE")
UNICODE_FALLBACKS.setdefault("flag", "\U0001F6A8")
UNICODE_FALLBACKS.setdefault("flag_green", "\U0001F7E2")
UNICODE_FALLBACKS.setdefault("clock_alarm", "⏰")

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
    """Resolve an icon name or ISO country code to its premium id, or None."""
    if not name:
        return None
    n = str(name).strip()
    if n.lower() in PREMIUM_EMOJI_IDS:
        return PREMIUM_EMOJI_IDS[n.lower()]
    if n in ICON_ALIASES:
        return ICON_ALIASES[n]
    if n in PREMIUM_FLAG_IDS:
        return PREMIUM_FLAG_IDS[n]
    direct = PREMIUM_ICONS.get(n.lower())
    if direct:
        return direct
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


# ======================= OTP GROUP MESSAGE FORMAT =======================
# One shared builder for every sender (bot.py's IVASMS, Choice SMS and panel
# forwarders, plus temp_numbers_panel.py), so the OTP group always gets the
# same layout: flag + #ISO + app icon + watermark number, an #AR/#EN tag
# line, a full-width green copy button carrying the REAL otp, and the blue
# NUMBER / CHANNEL link buttons — matching the reference screenshots.

# Dialling prefix -> ISO-2 for senders that only hold the phone number
# (same keys as bot.py's COUNTRY_CODES).
DIAL_TO_ISO = {
    "1": "US", "20": "EG", "211": "SS", "212": "MA", "213": "DZ", "216": "TN",
    "218": "LY", "220": "GM", "221": "SN", "222": "MR", "223": "ML", "224": "GN",
    "225": "CI", "226": "BF", "227": "NE", "228": "TG", "229": "BJ", "230": "MU",
    "231": "LR", "232": "SL", "233": "GH", "234": "NG", "235": "TD", "236": "CF",
    "237": "CM", "238": "CV", "239": "ST", "240": "GQ", "241": "GA", "242": "CG",
    "243": "CD", "244": "AO", "245": "GW", "248": "SC", "249": "SD", "250": "RW",
    "251": "ET", "252": "SO", "253": "DJ", "254": "KE", "255": "TZ", "256": "UG",
    "257": "BI", "258": "MZ", "260": "ZM", "261": "MG", "262": "RE", "263": "ZW",
    "264": "NA", "265": "MW", "266": "LS", "267": "BW", "268": "SZ", "269": "KM",
    "27": "ZA", "30": "GR", "31": "NL", "32": "BE", "33": "FR", "34": "ES",
    "350": "GI", "351": "PT", "352": "LU", "353": "IE", "354": "IS", "355": "AL",
    "356": "MT", "357": "CY", "358": "FI", "359": "BG", "36": "HU", "370": "LT",
    "371": "LV", "372": "EE", "373": "MD", "374": "AM", "375": "BY", "376": "AD",
    "377": "MC", "378": "SM", "380": "UA", "381": "RS", "382": "ME", "383": "XK",
    "385": "HR", "386": "SI", "387": "BA", "389": "MK", "39": "IT", "40": "RO",
    "41": "CH", "420": "CZ", "421": "SK", "423": "LI", "43": "AT", "44": "GB",
    "45": "DK", "46": "SE", "47": "NO", "48": "PL", "49": "DE", "500": "FK",
    "501": "BZ", "502": "GT", "503": "SV", "504": "HN", "505": "NI", "506": "CR",
    "507": "PA", "509": "HT", "51": "PE", "52": "MX", "53": "CU", "54": "AR",
    "55": "BR", "56": "CL", "57": "CO", "58": "VE", "591": "BO", "592": "GY",
    "593": "EC", "595": "PY", "597": "SR", "598": "UY", "60": "MY", "61": "AU",
    "62": "ID", "63": "PH", "64": "NZ", "65": "SG", "66": "TH", "670": "TL",
    "673": "BN", "674": "NR", "675": "PG", "676": "TO", "677": "SB", "678": "VU",
    "679": "FJ", "680": "PW", "685": "WS", "686": "KI", "687": "NC", "688": "TV",
    "689": "PF", "691": "FM", "692": "MH", "7": "RU", "81": "JP", "82": "KR",
    "84": "VN", "850": "KP", "852": "HK", "853": "MO", "855": "KH", "856": "LA",
    "86": "CN", "90": "TR", "91": "IN", "92": "PK", "93": "AF", "94": "LK",
    "95": "MM", "960": "MV", "961": "LB", "962": "JO", "963": "SY", "964": "IQ",
    "965": "KW", "966": "SA", "967": "YE", "968": "OM", "970": "PS", "971": "AE",
    "972": "IL", "973": "BH", "974": "QA", "975": "BT", "976": "MN", "977": "NP",
    "98": "IR", "992": "TJ", "993": "TM", "994": "AZ", "995": "GE", "996": "KG",
    "998": "UZ",
}

# Posts from Arabic-speaking countries are tagged #AR instead of #EN.
AR_LANG_ISO = frozenset({
    "AE", "BH", "DJ", "DZ", "EG", "IQ", "JO", "KW", "LB", "LY", "MA",
    "MR", "OM", "PS", "QA", "SA", "SD", "SO", "SY", "TD", "TN", "YE",
})

# Services whose icon is the envelope in the reference format (email /
# Switch-style OTPs) when emoji.txt holds no icon under their own name.
ENVELOPE_APPS = frozenset({
    "email", "email_otp", "none", "sms", "switch", "temp_numbers", "unknown",
})

# Service label detect_service() produces -> the key emoji.txt uses.
APP_ICON_ALIASES = {"twitter": "x"}

# Brand casing for services detect_service() returns lowercased; panel-supplied
# labels already arrive properly cased and are left untouched.
PROPER_APP_NAMES = {
    "whatsapp": "WhatsApp", "facebook": "Facebook", "instagram": "Instagram",
    "telegram": "Telegram", "twitter": "Twitter", "google": "Google",
    "discord": "Discord", "line": "LINE", "viber": "Viber", "skype": "Skype",
    "snapchat": "Snapchat", "tiktok": "TikTok", "amazon": "Amazon",
    "apple": "Apple", "microsoft": "Microsoft", "linkedin": "LinkedIn",
    "uber": "Uber", "airbnb": "Airbnb", "netflix": "Netflix",
    "spotify": "Spotify", "youtube": "YouTube", "github": "GitHub",
    "pinterest": "Pinterest", "paypal": "PayPal", "booking": "Booking.com",
    "tala": "Tala", "olx": "OLX", "stcpay": "stc pay", "unknown": "Unknown",
}

# Plain-unicode fallback shown inside <tg-emoji> for clients that cannot
# render the custom picture.
APP_GLYPHS = {
    "whatsapp": "\U0001F4AC",
    "telegram": "✈️",
    "facebook": "\U0001F4D8",
    "tiktok": "\U0001F3B5",
    "google": "\U0001F50D",
    "instagram": "\U0001F4F8",
    "twitter": "\U0001F426",
    "x": "\U0001F426",
    "discord": "\U0001F3AE",
    "paypal": "\U0001F4B3",
    "amazon": "\U0001F6D2",
    "netflix": "\U0001F3AC",
    "spotify": "\U0001F3B5",
    "youtube": "▶️",
    "snapchat": "\U0001F47B",
    "linkedin": "\U0001F4BC",
    "github": "\U0001F419",
    "reddit": "\U0001F4F0",
    "envelope": "\U0001F4E7",
    "default": "\U0001F4F1",
}


def _norm_app(name):
    """Service label -> emoji.txt key: `Apple Music` -> `apple_music`."""
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


def app_icon_id(name):
    """Premium id for an app/service.

    The operator's emoji.txt app ids win (the list a request just added),
    then the generic icon maps, then the envelope for unknown/email-style
    OTPs — the reference format uses an envelope there — then fire.
    """
    key = _norm_app(name)
    if not key:
        return premium_icon("fire")
    target = APP_ICON_ALIASES.get(key, key)
    eid = PREMIUM_ICONS.get(key) or PREMIUM_ICONS.get(target)
    if not eid:
        eid = premium_icon(str(name).strip())
    if not eid and (key in ENVELOPE_APPS or target in ENVELOPE_APPS):
        eid = ICON_ALIASES.get("mail")
    if not eid:
        eid = premium_icon(target)
    return eid or premium_icon("fire")


def app_emoji_html(name):
    """The app's icon as <tg-emoji> when an id exists, else its plain glyph."""
    key = _norm_app(name)
    target = APP_ICON_ALIASES.get(key, key)
    if key in ENVELOPE_APPS:
        glyph = APP_GLYPHS["envelope"]
    else:
        glyph = APP_GLYPHS.get(target) or APP_GLYPHS["default"]
    eid = app_icon_id(name)
    if eid and PREMIUM_EMOJI_OK:
        return f'<tg-emoji emoji-id="{eid}">{glyph}</tg-emoji>'
    return glyph


def iso_from_number(number):
    """Longest-prefix match of a phone number against DIAL_TO_ISO ('' if unknown)."""
    digits = re.sub(r"\D", "", str(number or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    if not digits:
        return ""
    for size in (3, 2, 1):
        iso = DIAL_TO_ISO.get(digits[:size])
        if iso:
            return iso
    return ""


def otp_lang_tag(iso):
    """`#AR` for Arabic-speaking countries, `#EN` otherwise."""
    return "#AR" if str(iso or "").strip().upper() in AR_LANG_ISO else "#EN"


def otp_number_display(number, watermark="¤¤¤¤"):
    """`+2637¤¤¤¤8206`: country prefix + watermark + last four digits.

    Matches the reference group format; numbers too short to mask pass
    through unchanged.
    """
    n = str(number or "").strip()
    digits = re.sub(r"\D", "", n)
    if len(digits) < 10:
        return n
    if not n.startswith("+"):
        n = "+" + digits
    return n[:5] + watermark + n[-4:]


def build_otp_group_message(number, otp, service, iso=None, number_link="",
                            channel_link="", copy_mode="text",
                            watermark="¤¤¤¤"):
    """Build the OTP group post: ``(text, reply_markup)``.

    Layout (reference screenshots, with the REAL otp):

        {flag} #ZW {app} +2637¤¤¤¤8206
        [ green full-width: {app icon} ⧉ Service | <real OTP> ]
        [ blue NUMBER ] [ blue CHANNEL ]

    The body is passed through premiumize() before returning, so every
    sender (bot.py, temp_numbers_panel.py, the panel scripts, evs_forwarder)
    emits fully premium <tg-emoji> even on the plain-glyph fallback paths.

    ``copy_mode="text"`` attaches a copy_text button (one tap copies the
    OTP); ``"callback"`` swaps it for a ``copy_<otp>`` callback for clients
    that reject copy_text buttons — the label stays identical either way.
    """
    iso = str(iso or "").strip().upper()
    if iso in ("", "UN", "NONE", "NULL"):
        iso = iso_from_number(number)
    if not (len(iso) == 2 and iso.isalpha()):
        iso = ""
    svc = str(service or "").strip() or "Unknown"
    svc = PROPER_APP_NAMES.get(_norm_app(svc),
                               svc.title() if svc.islower() else svc)
    otp_s = str(otp or "").strip()
    has_otp = bool(otp_s) and otp_s.upper() != "N/A"
    num_disp = html.escape(otp_number_display(number, watermark))

    # Line 1: flag, #ISO tag, app icon, watermark number.
    if iso:
        flag_glyph = "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso)
        flag_id = PREMIUM_FLAG_IDS.get(iso)
        flag = (f'<tg-emoji emoji-id="{flag_id}">{flag_glyph}</tg-emoji>'
                if flag_id and PREMIUM_EMOJI_OK else flag_glyph)
        parts = [flag, "#" + iso]
    else:
        parts = ["\U0001F30D"]  # 🌍 when the country cannot be derived
    parts += [app_emoji_html(svc), num_disp]
    text = premiumize(" ".join(parts))

    app_id = app_icon_id(svc)
    rows = []
    if has_otp:
        copy_btn = {"text": f"⧉ {svc} | {otp_s}", "style": "success"}
        if app_id:
            copy_btn["icon_custom_emoji_id"] = app_id
        if copy_mode == "callback":
            copy_btn["callback_data"] = ("copy_" + otp_s)[:64]
        else:
            copy_btn["copy_text"] = {"text": otp_s}
        rows.append([copy_btn])
    link_row = []
    if number_link:
        btn = {"text": "NUMBER", "url": number_link, "style": "primary"}
        if ICON_ALIASES.get("call"):
            btn["icon_custom_emoji_id"] = ICON_ALIASES["call"]
        link_row.append(btn)
    if channel_link:
        btn = {"text": "CHANNEL", "url": channel_link, "style": "primary"}
        meg_id = (PREMIUM_ICONS.get("c_cheering_megaphone")
                  or PREMIUM_ICONS.get("announcement"))
        if meg_id:
            btn["icon_custom_emoji_id"] = meg_id
        link_row.append(btn)
    if link_row:
        rows.append(link_row)
    return text, {"inline_keyboard": rows}


def kb_without_copy(kb, otp=""):
    """The same keyboard with copy_text buttons downgraded to `copy_<otp>`
    callbacks, for servers/clients that reject copy_text buttons.

    Returns the input unchanged when there is nothing to downgrade.
    """
    if not kb or not isinstance(kb, dict):
        return kb
    rows, changed = [], False
    for row in kb.get("inline_keyboard") or []:
        new_row = []
        for btn in row:
            if isinstance(btn, dict) and "copy_text" in btn:
                btn = dict(btn)
                want = str((btn.get("copy_text") or {}).get("text") or otp or "")
                btn.pop("copy_text", None)
                btn["callback_data"] = ("copy_" + want)[:64]
                changed = True
            new_row.append(btn)
        rows.append(new_row)
    return {"inline_keyboard": rows} if changed else kb
# ============== OTP GROUP FORWARD FORMAT (compat wrappers) ===============
# The standalone forwarders (evs_forwarder.py) and the 41 panel scripts import
# group_otp_body / group_otp_buttons / iso_from_flag from here. They delegate
# to build_otp_group_message() so every sender gets the reference layout —
# flag + #ISO + app icon + watermark number, the #AR/#EN tag line, a green
# copy button carrying the panel's OWN service and the real OTP, and the blue
# NUMBER / CHANNEL link buttons. The copy label is never hardcoded to "Switch".

DEFAULT_BOT_LINK = "https://t.me/Anon_MatrixxV3bot"
DEFAULT_CHANNEL_LINK = "https://t.me/AnonmatrixxOtp"

# group_otp_buttons() has no service parameter at the original call sites
# (panels call body, then buttons), so it picks the label up from here.
_LAST_SERVICE = ["Unknown"]


def iso_from_flag(flag):
    """Regional-indicator pair -> ISO-2 code ('UN' when not a flag)."""
    ris = []
    for ch in flag or "":
        cp = ord(ch)
        if 0x1F1E6 <= cp <= 0x1F1FF:
            ris.append(chr(cp - 0x1F1E6 + 65))
    return "".join(ris) if len(ris) == 2 else "UN"


def group_otp_body(flag, iso, phone, service):
    """Reference-format body for callers that already hold a rendered flag.

    *flag* is only used to derive the ISO code when *iso* is missing or
    invalid (a premium <tg-emoji> tag still works — the regional indicators
    inside it decode). The body itself is built by build_otp_group_message()
    so the layout, watermark and #ISO line match every other sender,
    and the service comes from the panel's own record.
    """
    svc = str(service or "").strip() or "Unknown"
    _LAST_SERVICE[0] = svc
    code = str(iso or "").strip().upper()
    if code == "UN" or not (len(code) == 2 and code.isalpha()):
        code = iso_from_flag(flag)
    text, _kb = build_otp_group_message(phone, "", svc, iso=code)
    return text


def group_otp_buttons(otp_code, bot_link=None, channel_link=None, service=None):
    """Reference keyboard rows for callers that build the body separately.

    Row 1 is the green full-width copy button ``⧉ Service | <otp>`` (the
    panel-supplied service — never a hardcoded label — plus the real OTP),
    row 2 the blue NUMBER / CHANNEL links. Delegates to
    build_otp_group_message() so icons, styles and copy_text match the
    other senders.
    """
    _, kb = build_otp_group_message(
        "", otp_code, service or _LAST_SERVICE[0], iso="",
        number_link=bot_link or DEFAULT_BOT_LINK,
        channel_link=channel_link or DEFAULT_CHANNEL_LINK,
        copy_mode="text")
    return kb.get("inline_keyboard") or []

# Default configurations acting as fallback
# These values are used if remote configuration cannot be loaded

DEFAULT_PLAYERS = {
    "wishonly": {
        "type": "default",
        "referrer": "full",
        "alt-used": True,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:cross-site;Content-Cache: no-cache",
        "mode": "proxy",
    },
    "hgbazooka": {"type": "default"},
    "hailindihg": {"type": "default"},
    "gradehgplus": {"type": "default"},
    "taylorplayer": {"type": "default"},
    "vidmoly": {"type": "vidmoly"},
    # "oneupload": {"type": "default"},
    "tipfly": {"type": "default"},
    "lulustream": {"type": "default"},
    "luluvdo": {"type": "default"},
    "luluvdoo": {"type": "default"},
    "luluvid": {"type": "default"},
    "ups2up": {"type": "default"},
    "ico3c": {"type": "default"},
    "fsvid": {"type": "default", "m3u8-extractor": {"no-header": True}},
    "darkibox": {"type": "default"},
    "minochinos": {"type": "default"},
    "movearnpre": {
        "type": "default",
        "referrer": "full",
        "alt-used": False,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:same-origin",
    },
    "smoothpre": {
        "type": "default",
        "referrer": "full",
        "alt-used": True,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:cross-site;Content-Cache: no-cache",
        "mode": "proxy",
    },
    "vidhideplus": {"type": "default"},
    "dinisglows": {
        "type": "default",
        "referrer": "full",
        "alt-used": True,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:same-origin",
    },
    "mivalyo": {"type": "default"},
    "dingtezuni": {"type": "default"},
    "bingezove": {"type": "default"},
    "vidzy": {"type": "default"},
    "ok.ru": {"type": "default"},
    "ansembed": { "type": "default" },
    "morencius": { "type": "default" },
    "videzz": {
        "type": "vidoza",
        "mode": "proxy",
        "no-header": True,
        "ext": "mp4",
    },
    "vidoza": {
        "type": "vidoza",
        "mode": "proxy",
        "no-header": True,
        "ext": "mp4",
    },
    "sendvid": {"type": "sendvid", "mode": "proxy", "ext": "mp4"},
    "sibnet": {
        "type": "sibnet",
        "mode": "proxy",
        "ext": "mp4",
        "referrer": "full",
        "no-header": True,
    },
    "uqload.is": {
        "type": "default"
    },
    "uqload": {
        "type": "uqload",
        "sec_headers": "Sec-Fetch-Dest:video;Sec-Fetch-Mode:no-cors;Sec-Fetch-Site:same-site",
        "ext": "mp4",
    },
    "filemoon": {
        "type": "filemoon",
        "referrer": "https://ico3c.com/",
        "no-header": True,
    },
    "bysebuho": {
        "type": "filemoon",
        "referrer": "https://ico3c.com/",
        "no-header": True,
    },
    "bysekoze": {
        "type": "filemoon",
        "referrer": "https://ico3c.com/",
        "no-header": True,
    },
    "kakaflix": {"type": "kakaflix"},
    # "myvidplay": {"type": "myvidplay", "referrer": "https://myvidplay.com/"},
    "embed4me": {"type": "embed4me"},
    "coflix.upn": {"type": "embed4me"},
    "veev": {"type": "veev", "ext": "mp4"},
    "xtremestream": {"type": "xtremestream"},
    "montmyoboky": {"type": "montmyoboky"}
}

DEFAULT_NEW_URL = {
    "lulustream": "luluvdo",
    "vidoza.net": "videzz.net",
    "oneupload.to": "oneupload.net",
    "uqload.cx": "uqload.is",
    # Dinisglows Player
    "mivalyo": "dinisglows",
    "vidhideplus": "dinisglows",
    "dingtezuni": "dinisglows",
    # Vidmoly Player
    "vidmoly.to": "vidmoly.biz",
    "vidmoly.me": "vidmoly.biz",
    "vidmoly.net": "vidmoly.biz",
}

DEFAULT_KAKAFLIX_PLAYERS = {
    "moon2": "ico3c",
    "viper": "ico3c",
    # "tokyo": "myvidplay"
}

DEFAULT_SOURCE_PORTAL = {
    "french-stream": "https://french-stream.one",
    "anime-sama": "https://anime-sama.pw",
    "arkanime": "https://arkanim.net",
    "coflix": "https://coflix.domains",
    "sudatchi": "https://sudatchi.com",
    "animetsu": "https://animetsu.live",
    "animetsu-api": "https://b.animetsu.live",
    "animetsu-proxy": "https://ani.metsu.site/proxy",
    "allanime-api": "https://api.allanime.day/api",
    "allanime-referer": "https://allmanga.to",
    "allanime-base": "https://allanime.day",
    "anizone": "https://anizone.to",
    "videasy": "https://api.videasy.net",
    "videasy-referer": "https://cineby.gd",
    "vidlink": "https://vidlink.pro",
    "hexa": "https://themoviedb.hexa.su",
    "hexa-referer": "https://hexa.su",
    "multi-decrypt": "https://enc-dec.app/api",
    "mapple": "https://mapple.uk",
    "xpass": "https://play.xpass.top",
}

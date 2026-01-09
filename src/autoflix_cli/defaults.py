# Default configurations acting as fallback
# These values are used if remote configuration cannot be loaded

DEFAULT_PLAYERS = {
    "wishonly": {
        "type": "a",
        "referrer": "full",
        "alt-used": True,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:cross-site;Content-Cache: no-cache",
        "mode": "proxy",
    },
    "hgbazooka": {"type": "a"},
    "hailindihg": {"type": "a"},
    "gradehgplus": {"type": "a"},
    "taylorplayer": {"type": "a"},
    "vidmoly": {"type": "vidmoly"},
    "oneupload": {"type": "b"},
    "tipfly": {"type": "b"},
    # "luluvdoo": {
    #     "type": "b",
    #     "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:cross-site",
    # },
    # "luluvdo": {
    #     "type": "b",
    #     "sec_headers": False,
    # },
    # "lulustream": {
    #     "type": "b",
    #     "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:cross-site",
    # },
    "ups2up": {"type": "c"},
    "ico3c": {"type": "c"},
    "fsvid": {"type": "c"},
    "darkibox": {"type": "d"},
    # "movearnpre": { # don't work
    #     "type": "e",
    #     "referrer": "full",
    #     "alt-used": False,
    #     "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:same-origin",
    # },
    "smoothpre": {
        "type": "e",
        "referrer": "full",
        "alt-used": True,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:cross-site;Content-Cache: no-cache",
        "mode": "proxy",
    },
    "vidhideplus": {"type": "e"},
    "dinisglows": {
        "type": "e",
        "referrer": "full",
        "alt-used": True,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:same-origin",
    },
    "mivalyo": {"type": "e"},
    "dingtezuni": {"type": "e"},
    "vidzy": {"type": "f"},
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
    "kakaflix": {"type": "kakaflix"},
    # "myvidplay": {"type": "myvidplay", "referrer": "https://myvidplay.com/"},
}

DEFAULT_NEW_URL = {
    "mivalyo": "dinisglows",
    "vidhideplus": "dinisglows",
    "dingtezuni": "dinisglows",
    "vidmoly.to": "vidmoly.me",
    "lulustream": "luluvdo",
    "vidoza.net": "videzz.net",
}

DEFAULT_KAKAFLIX_PLAYERS = {
    "moon2": "ico3c",
    "viper": "ico3c",
    # "tokyo": "myvidplay"
}

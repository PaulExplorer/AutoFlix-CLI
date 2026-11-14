"""Offline tests for subtitle payload normalization."""

import gzip
import lzma

from autoflix_cli.scraping.subtitles import normalize

VTT_WITH_ADS = b"""WEBVTT

header
00:00:01.000 --> 00:00:06.000
&gt;&gt;OpenSubtitles v3+ v0.0.4&lt;&lt;
<u>=&gt;Memories.1995.1080p.BluRay.x264.AAC5.1-[YTS.MX].srt</u>

WEBVTT

1
00:01:01.938 --> 00:01:03.538
D'o\xc3\xb9 vient ce vieux satellite ?

2
00:01:04.037 --> 00:01:07.398
Il a d\xc3\xbb \xc3\xaatre attir\xc3\xa9 par la gravit\xc3\xa9
"""


def test_vtt_envelope_becomes_clean_srt():
    text = normalize.to_srt(VTT_WITH_ADS, "https://x/sub.vtt/?sub_id=1")

    assert "OpenSubtitles" not in text
    assert "WEBVTT" not in text
    assert "1\n00:01:01,938 --> 00:01:03,538" in text
    assert "D'où vient ce vieux satellite ?" in text


def test_to_vtt_has_a_single_header():
    text = normalize.to_vtt(VTT_WITH_ADS, "https://x/sub.vtt/")

    assert text.startswith("WEBVTT\n\n")
    assert text.count("WEBVTT") == 1
    assert "00:01:01.938 --> 00:01:03.538" in text


def test_decode_utf16_and_cp1252():
    assert "café" in normalize.decode_text("café".encode("utf-16"))
    assert "café" in normalize.decode_text("café".encode("cp1252"))


def test_decompress_gzip_and_xz():
    payload = b"1\n00:00:01,000 --> 00:00:02,000\nHi\n"
    assert normalize.decompress(gzip.compress(payload), "x.srt.gz") == payload
    assert normalize.decompress(lzma.compress(payload), "x.srt.xz") == payload


def test_ass_is_converted_to_srt():
    ass = """[Script Info]
Title: Test

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\i1}Bonjour\\Nà tous{\\i0}
"""
    text = normalize.to_srt(ass.encode("utf-8"), "x.ass")

    assert "00:00:01,000 --> 00:00:02,500" in text
    assert "Bonjour\nà tous" in text
    assert "{\\" not in text


def test_html_error_page_is_rejected():
    assert normalize.looks_like_subtitle(b"<!DOCTYPE html><html><body>403</body></html>") is False
    assert normalize.looks_like_subtitle(b"1\n00:00:01,000 --> 00:00:02,000\nHi\n") is True


def test_invalid_cues_are_dropped():
    text = normalize.to_srt(
        b"1\n00:00:02,000 --> 00:00:01,000\nBackwards\n\n2\nnot a timestamp\nNope\n"
    )
    assert text == ""

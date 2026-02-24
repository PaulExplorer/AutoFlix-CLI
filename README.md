# Autoflix 🍿

> Watch movies, series, and anime in **multiple languages** (FR, EN, and more) directly from your terminal.

**Autoflix** is a CLI inspired by `ani-cli`. Originally focused on French content, it has evolved into a multi-language streaming tool. It scrapes links from various providers to let you stream content without ads or a browser.

> ⚠️ **Warning:** This project was developed very quickly with heavy use of AI. The main goal was functionality over code cleanliness or optimization. I apologize for the "spaghetti code", I just wanted it to work!

## ✨ Features

- 🌍 **Multi-language support:** Now supports French and English.
- 🚀 **Easily extendable:** The architecture allows adding new languages and providers with ease.
- 🎬 **Massive Library:**
  - **French (VF & VOSTFR):** Reliable sources like **Coflix**, **French-Stream**, and **Anime‑Sama**.
  - **English & Global:** A huge variety of sources (VidSrc, etc.) providing access to almost any movie or series.
- ⛩️ **Anime:** Latest episodes from dedicated providers.
- 🚫 **No ads, no trackers.**
- ⚡ **Lightweight and fast.**

## 🚀 Installation

### With **uv** (recommended)

```bash
uv tool install autoflix-cli
```

### With **pip**

```bash
pip install autoflix-cli
```

> **Note:** You need an external media player such as **MPV** or **VLC** installed.

## 💻 Usage

```bash
autoflix
```

1. Select your preferred **language**.
2. Select a **provider**.
3. Search for a title.
4. Choose a stream and launch it with your preferred player.

## 🛠️ Development

```bash
# Clone the repository
git clone https://github.com/PaulExplorer/autoflix-cli.git
cd autoflix-cli

# Install in editable mode
pip install -e .
```

## 📚 Credits

This project uses logic and inspiration from several open-source projects:

- [CineStream (CSX)](https://github.com/SaurabhKaperwan/CSX) by [SaurabhKaperwan](https://github.com/SaurabhKaperwan) - Major inspiration for the multi-provider architecture and English stream extraction.
- [Anime-Sama-Downloader](https://github.com/SertraFurr/Anime-Sama-Downloader) by [SertraFurr](https://github.com/SertraFurr) - Implementation of the `embed4me` stream extraction.
- [cloudstream-extensions-phisher](https://github.com/phisher98/cloudstream-extensions-phisher) by [phisher98](https://github.com/phisher98) - Implementation of the `Veev` stream extraction.

## 📜 License

This project is licensed under the GPL-3 License.

## ⚠️ Disclaimer

This notice is to inform you that **Autoflix** functions strictly as an automated search tool and specialized browser. It fetches video file metadata and links from the internet in a manner similar to any standard web browser.

- **No Hosting:** Autoflix does not host, store, or distribute any media files or copyrighted content. All content accessed through this tool is hosted by independent third-party websites.
- **DMCA Compliance:** This software does not violate the provisions of the Digital Millennium Copyright Act (DMCA) as it only provides access to publicly available links and does not store copies of any content on its own servers.
- **User Responsibility:** The use of this software and the legality of streaming content are the sole responsibility of the user, based on their respective country's or state's laws.
- **Copyright Holders:** If you believe any content accessed through this tool violates your intellectual property, please contact the **actual file hosts** or the websites providing the streams, as the developers of this repository have no control over or access to the hosted content.

_This project is for educational purposes only._

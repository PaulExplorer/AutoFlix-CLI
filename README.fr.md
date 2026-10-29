# Autoflix 🍿

> Regardez films, séries et animes en **plusieurs langues** (FR, EN, et plus) directement depuis votre terminal.

**Autoflix** est un outil en ligne de commande inspiré de `ani-cli`, pensé avant tout pour le contenu **français** (VF, VOSTFR) et tout en supportant aussi l'anglais. Il récupère les liens de différents fournisseurs pour vous permettre de streamer sans pub ni navigateur dans votre terminal.

## ✨ Fonctionnalités

- 🇫🇷 **Orientation française :** le contenu VF et VOSTFR reste la priorité.
- 🌍 Multilingue : l'anglais est aussi disponible.
- 🎬 **Grande bibliothèque :**
  - **Français (VF & VOSTFR) :** des sources fiables comme **Coflix**, **French-Stream** et **Anime-Sama**.
  - **Anglais & international :** une grande variété de sources (VidSrc, etc.) donnant accès à presque n'importe quel film ou série.
- 🚫 **Pas de pub, pas de trackers.**
- ⚡ **Léger et rapide.**

## 🎥 Démo

https://github.com/user-attachments/assets/bf95885f-b7b2-4bfc-b607-eb9939cc64d9

> [!NOTE]
> La vidéo ci-dessus montre AutoFlix en action : choix de la langue, du fournisseur, recherche d'un titre et lancement du stream.

## 🚀 Installation

### Avec **uv** (recommandé)

```bash
uv tool install autoflix-cli
```

### Avec **pip**

```bash
pip install autoflix-cli
```

> **Note :** vous avez besoin d'un lecteur externe comme **MPV**, **VLC** ou **un navigateur**.

## 💻 Utilisation

```bash
autoflix
```

1. Choisissez votre **langue**.
2. Choisissez un **fournisseur**.
3. Recherchez un titre.
4. Sélectionnez un stream et lancez-le avec votre lecteur préféré.

> **Des drapeaux existent aussi** pour un usage non-interactif :
> `autoflix --search "titre"`, `--url`, `--extract`... Voir [docs/CLI.md](docs/CLI.md).

## 🐍 API Python

AutoFlix est aussi utilisable **comme bibliothèque** : recherchez chez les fournisseurs, résolvez le contenu et extrayez les streams directement en Python. Voir [docs/API.md](docs/API.md) pour le guide complet (en anglais).

```python
import autoflix_cli.api as af

hit = af.search("bofuri", provider="anime-sama")[0]
content = af.get(hit)
season = af.get(content.seasons[0])
stream = af.extract(season.seasons[0].episodes[0].players[0])
```

## 🛠️ Développement

```bash
# Cloner le dépôt
git clone https://github.com/PaulExplorer/autoflix-cli.git
cd autoflix-cli

# Installer en mode éditable
pip install -e .

# Ou avec uv : pour lancer
uv run autoflix
```

## 📚 Crédits

Ce projet s'appuie sur la logique et l'inspiration de plusieurs projets open source :

- [CineStream (CSX)](https://github.com/SaurabhKaperwan/CSX) par [SaurabhKaperwan](https://github.com/SaurabhKaperwan), une inspiration majeure pour l'architecture multi-fournisseurs et l'extraction des streams anglais.
- [Anime-Sama-Downloader](https://github.com/SertraFurr/Anime-Sama-Downloader) par [SertraFurr](https://github.com/SertraFurr), une implémentation de l'extraction des streams `embed4me`.
- [cloudstream-extensions-phisher](https://github.com/phisher98/cloudstream-extensions-phisher) par [phisher98](https://github.com/phisher98), une implémentation de l'extraction des streams `Veev`.
- [Anivexa-API](https://github.com/walterwhite-69/Anivexa-API) par [walterwhite-69](https://github.com/walterwhite-69) : API REST utilisée pour l'extraction des streams et sous-titres des animes en VO (anizone, anikoto, et plus).

## 📜 Licence

Ce projet est sous licence GPL-3.

## ⚠️ Avertissement

Ce message est là pour vous informer qu'**Autoflix** fonctionne strictement comme un outil de recherche automatisé et un navigateur spécialisé. Il récupère les métadonnées et les liens de fichiers vidéo sur internet, de la même manière qu'un navigateur web classique.

- **Pas d'hébergement :** Autoflix n'héberge, ne stocke ni ne distribue aucun fichier média ni contenu protégé. Tout le contenu accessible via cet outil est hébergé par des sites tiers indépendants.
- **Conformité DMCA :** ce logiciel ne viole pas les dispositions du Digital Millennium Copyright Act (DMCA), car il donne seulement accès à des liens publiquement disponibles et ne stocke aucune copie de contenu sur ses propres serveurs.
- **Responsabilité de l'utilisateur :** l'utilisation de ce logiciel et la légalité du streaming relèvent de la seule responsabilité de l'utilisateur, selon les lois de son pays ou de son état.
- **Ayants droit :** si vous pensez qu'un contenu accessible via cet outil viole votre propriété intellectuelle, merci de contacter les **hébergeurs des fichiers** ou les sites qui fournissent les streams, car les développeurs de ce dépôt n'ont aucun contrôle ni accès sur le contenu hébergé.

_Ce projet est destiné à des fins éducatives uniquement._

## 🤖 Note sur l'IA

Ce projet a été développé très rapidement avec une grosse utilisation de l'IA. L'objectif principal était que ça fonctionne, plutôt que d'avoir un code propre. Désolé d'avance pour le « code spaghetti », je voulais juste que ça marche !

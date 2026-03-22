# Jonny Benzin – Hugo Portfolio Theme

Minimalistisches, dunkles Portfolio-Theme für Hugo, basierend auf dem Design von jonnybenzin.com.

## Features

- **Dunkles Design** mit `#1a1a1a` Hintergrund
- **2-Spalten Masonry Grid** auf der Startseite
- **Einzelprojekt-Seiten** mit Hero-Bild (volle Breite), Beschreibungstext, weiteren Bildern/Videos
- **Related Posts** als 3er-Thumbnail-Grid am Seitenende
- **Hamburger-Menü** mit Fullscreen-Overlay
- **Handschrift-Logo** (Caveat Font oder eigenes Bild)
- **Responsive** – funktioniert auf Desktop und Mobile
- **EB Garamond** Serif-Schrift für eleganten, minimalen Look

## Schnellstart

```bash
# 1. Hugo installieren (falls noch nicht vorhanden)
# macOS:  brew install hugo
# Ubuntu: sudo snap install hugo
# Oder:   https://gohugo.io/installation/

# 2. Neues Hugo-Projekt erstellen
hugo new site mein-portfolio
cd mein-portfolio

# 3. Theme-Dateien kopieren
# Kopiere den Inhalt dieses Ordners in dein Hugo-Projekt:
#   - layouts/     → mein-portfolio/layouts/
#   - static/      → mein-portfolio/static/
#   - config.toml  → mein-portfolio/config.toml
#   - archetypes/  → mein-portfolio/archetypes/

# 4. Scraper laufen lassen (aus dem vorherigen Script)
python3 wp_to_hugo.py https://jonnybenzin.com -o hugo-export

# 5. Gescrapte Inhalte reinkopieren
cp -r hugo-export/content/* content/
cp -r hugo-export/static/* static/

# 6. Starten
hugo server -D
# → http://localhost:1313
```

## Verzeichnisstruktur

```
mein-portfolio/
├── config.toml                 # Seitenkonfiguration
├── content/
│   └── posts/
│       ├── the-tripods/
│       │   └── index.md        # Projekt als Page Bundle
│       ├── barrcudas/
│       │   └── index.md
│       └── paul-encounters-gurney/
│           └── index.md
├── layouts/
│   ├── _default/
│   │   ├── baseof.html         # Basis-Layout
│   │   ├── list.html           # Kategorie/Tag-Seiten
│   │   └── single.html         # Einzelprojekt-Seite
│   ├── partials/
│   │   ├── head.html           # <head> mit Fonts, Meta
│   │   ├── header.html         # Logo + Hamburger
│   │   ├── footer.html         # Copyright
│   │   └── related.html        # Related Posts Grid
│   └── index.html              # Startseite (Masonry Grid)
├── static/
│   ├── css/
│   │   └── style.css           # Komplettes Styling
│   ├── images/
│   │   ├── logo.png            # Dein Logo (optional)
│   │   └── wp-uploads/         # Gescrapte Bilder
│   └── js/
│       └── main.js             # Menü-Toggle
└── archetypes/
    └── default.md              # Template für neue Posts
```

## Front Matter eines Posts

```yaml
---
title: "The Tripods"
date: 2019-04-13
slug: "the-tripods"
description: "Beschreibungstext, der auf der Einzelseite angezeigt wird."
image: "/images/wp-uploads/the-tripods/hero.jpg"
image_caption: "Bildunterschrift für das Hero-Bild"
categories: ["Sci-Fi", "The Tripods"]
tags: ["illustration"]
draft: false
---

Weiterer Content hier (Markdown).
Bilder einfach als ![Alt](pfad.jpg) einbinden.
```

## Logo anpassen

**Option A – Eigenes Bild:** Lege dein Logo als `static/images/logo.png` ab.

**Option B – Text-Logo:** Entferne den `logo`-Parameter aus `config.toml` – dann wird der Seitentitel in Caveat-Handschrift angezeigt.

## Anpassungen

- **Farben:** Alle Farben sind als CSS-Variablen in `style.css` definiert (`:root { ... }`)
- **Content-Breite:** `--content-width` (Text) und `--page-width` (Bilder) anpassen
- **Fonts:** In `head.html` den Google Fonts Link ändern und in `style.css` die `font-family` anpassen
- **Grid-Spalten:** In `.portfolio-grid` die `columns`-Eigenschaft ändern

## Build für Produktion

```bash
hugo --minify
# Output liegt in public/
# → Auf Netlify, Vercel, GitHub Pages o.ä. deployen
```

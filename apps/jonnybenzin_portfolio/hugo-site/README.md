# Jonny Benzin – Hugo Portfolio

## Starten

```bash
cd ~/Schreibtisch/Mora02/apps/jonnybenzin_portfolio/hugo-site
hugo server -D --bind 0.0.0.0
# → http://localhost:1313
```

Build für Produktion:
```bash
hugo --minify
# Output in public/
```

---

## Posts verwalten

Jeder Post ist ein **Page Bundle** – ein Ordner mit `index.md` und Bildern:

```
content/posts/mein-projekt/
├── index.md          ← Text + Einstellungen
├── hero.jpg          ← Hauptbild (wird auf Startseite + als Hero gezeigt)
├── sketch.jpg        ← Weiteres Bild
├── detail.png        ← Weiteres Bild
└── animation.mp4     ← Video
```

### Neuen Post erstellen

1. Ordner anlegen: `content/posts/mein-neuer-post/`
2. `index.md` erstellen (siehe Template unten)
3. Bilder reinlegen
4. **Wichtig:** Das Hauptbild muss `hero.jpg` / `hero.png` / `hero.jpeg` heißen!

### index.md Template

```yaml
---
title: "Mein Titel"
date: 2024-06-15
slug: "mein-titel"
description: "Beschreibungstext der über dem Hero-Bild erscheint."
image_caption: "Bildunterschrift unter dem Hero"
categories: ["Sci-Fi", "Dune"]
tags: ["illustration"]
draft: false
---

Hier kommt der Content unterhalb des Hero-Bildes.
```

### Reihenfolge auf der Startseite

Posts werden nach **Datum** sortiert (neueste zuerst).
Ändere das `date:` Feld um die Reihenfolge zu steuern.

---

## Bilder einbinden

Es gibt **drei Breiten** für Bilder:

### 1. Hero-Bild (FULL WIDTH – Rand zu Rand)
Das `hero.jpg` im Post-Ordner wird automatisch full-width angezeigt.
Muss nicht im Markdown referenziert werden – passiert automatisch.

### 2. Standard-Bild (MITTLERE SPALTE – 740px)
Einfach im Markdown einbinden – wird automatisch auf die mittlere Spalte skaliert:

```markdown
![Beschreibung](mein-bild.jpg)
```

### 3. Full-Width Bild im Content
Wenn ein Bild im Content (nicht Hero) auch full-width sein soll:

```html
<div class="full-width">

![Beschreibung](mein-bild.jpg)

</div>
```

### Bild mit Unterschrift

```html
<figure>
  <img src="mein-bild.jpg" alt="Beschreibung">
  <figcaption>Bildunterschrift hier</figcaption>
</figure>
```

---

## Videos einbinden

### Lokales Video (im Post-Ordner)

Lege die Videodatei in den Post-Ordner und binde sie so ein:

```html
<video controls preload="metadata" style="width:100%">
  <source src="mein-video.mp4" type="video/mp4">
</video>
```

### YouTube / Vimeo

```html
<iframe width="100%" height="400" src="https://www.youtube.com/embed/VIDEO_ID" 
  frameborder="0" allowfullscreen></iframe>
```

### Video full-width

```html
<div class="full-width">
<video controls preload="metadata" style="width:100%">
  <source src="mein-video.mp4" type="video/mp4">
</video>
</div>
```

---

## Seiten (About, Impressum)

Seiten liegen in eigenen Ordnern:
```
content/about/index.md
content/impressum/index.md
```

Diese verwenden das Page-Layout (zentriert, ohne Hero).

---

## Kurzreferenz – Breiten-Kürzel

| Was                  | Breite  | Wie                                        |
|----------------------|---------|--------------------------------------------|
| Text / Absätze       | 440px   | Normaler Markdown-Text                     |
| Bilder (Standard)    | 740px   | `![alt](bild.jpg)`                         |
| Hero-Bild            | 100%    | `hero.jpg` im Ordner (automatisch)         |
| Bild full-width      | 100%    | `<div class="full-width">` drumherum       |
| Video (Standard)     | 740px   | `<video>` Tag                              |
| Video full-width     | 100%    | `<div class="full-width">` drumherum       |

---

## Dateien

```
hugo-site/
├── config.toml              ← Seiteneinstellungen
├── content/
│   ├── posts/               ← Alle Portfolio-Posts
│   │   └── mein-post/
│   │       ├── index.md
│   │       └── hero.jpg
│   ├── about/               ← About-Seite
│   └── impressum/           ← Impressum
├── layouts/                 ← HTML-Templates
├── static/
│   ├── css/style.css        ← Styling
│   ├── js/main.js           ← Menü-Script
│   ├── images/logo.png      ← Logo
│   └── robots.txt           ← Suchmaschinen-Blocker
└── public/                  ← Generierte Seite (nach hugo build)
```

---

## Robots / AI-Schutz

- `robots.txt` blockiert alle Crawler
- Jede Seite hat `<meta name="robots" content="noindex, nofollow">`
- AI-Bots (GPTBot, ClaudeBot, CCBot etc.) sind explizit geblockt

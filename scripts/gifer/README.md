# Gifer - GIF Animation Creator

**Script:** `/opt/mora02/scripts/2501231500_gifer.py`  
**Befehl:** `gifer`  
**Version:** 2.0  
**Aktualisiert:** 2025-01-23

---

## Was macht gifer?

Erstellt animierte GIFs aus nummerierten Bildern mit individuellen Frame-Dauern, wählbarer Ausgabegröße und archiviert automatisch Quellbilder + GIF.

---

## Installation / Alias
```bash
alias gifer='python3 /opt/mora02/scripts/2501231500_gifer.py'
```

Bereits aktiv in `~/.bashrc`

---

## Verwendung

### Basis-Syntax
```bash
gifer [DAUERN] [--quality LEVEL] [--size WxH oder W]
```

### Parameter

| Parameter | Beschreibung | Pflicht | Standard |
|-----------|--------------|---------|----------|
| `DAUERN` | Frame-Dauern in **Sekunden** (z.B. 1, 0.5, 2) | Nein | 1s |
| `--quality` | Qualitätsstufe (low/medium/high/ultra) | Nein | medium |
| `--size` | Ausgabegröße in Pixel (800x600 oder 800) | Nein | kleinstes Bild |

---

## Frame-Dauern angeben (3 Methoden)

### Methode 1: Kommandozeile (empfohlen)
```bash
# Alle Frames gleiche Dauer (1 Sekunde):
gifer 1

# Individuelle Dauern (komma-separiert):
gifer 1,0.5,2,1.5

# Mit Qualität:
gifer 1,1.5,2 --quality high

# Mit Größe:
gifer 1,0.5,2 --size 800x600
```

### Methode 2: durations.txt
```bash
# Datei erstellen:
nano /opt/mora02/docs/gifer/source/durations.txt

# Inhalt (komma-separiert, in Sekunden):
1,0.5,2,1.5

# Oder zeilenweise:
1
0.5
2
1.5

# Dann ohne Parameter:
gifer
```

### Methode 3: Default
```bash
# Ohne Angabe → alle Frames 1 Sekunde:
gifer
```

**Priorität:** Kommandozeile > durations.txt > Default

---

## Ausgabegröße festlegen

### Mit --size Parameter
```bash
# Exakte Größe (Breite x Höhe):
gifer 1,2,0.5 --size 800x600

# Nur Breite (Höhe wird proportional berechnet):
gifer 1,2,0.5 --size 800

# Full HD:
gifer 1 --size 1920x1080

# Social Media optimiert:
gifer 0.5,1,0.5 --size 1080x1080
```

### Ohne --size (Standard)
```bash
# Kleinstes Quellbild bestimmt die Größe:
gifer 1,2,0.5
```

---

## Qualitätsstufen

| Level | Größe | Farben | Verwendung | Dateigröße |
|-------|-------|--------|------------|------------|
| **low** | 50% | 64 | Social Media, Web | Klein (~0.5 MB) |
| **medium** | 75% | 128 | Standard, ausgewogen | Mittel (~1-2 MB) |
| **high** | 100% | 256 | Präsentationen, Druck | Groß (~3-5 MB) |
| **ultra** | 100% | 256 | Maximale Qualität | Sehr groß (~5-10 MB) |

---

## Workflow

### 1. Bilder vorbereiten
```bash
cd /opt/mora02/docs/gifer/source

# Bilder MÜSSEN nummeriert sein:
01-name.jpg
02-name.jpg
03-name.jpg
```

### 2. GIF erstellen
```bash
# Schnell & einfach:
gifer 1

# Mit allen Optionen:
gifer 1,1.5,2 --quality high --size 800
```

### 3. Ergebnis
```
/opt/mora02/docs/gifer/
└── 202501231500_gifer/
    ├── 202501231500.gif
    └── source/
        ├── 202501231500_logs.md
        └── (Quellbilder)
```

---

## Alle Befehle auf einen Blick
```bash
gifer 1                              # Alle 1 Sekunde
gifer 0.5,2,1                        # Variable Dauern
gifer 1 --quality high               # Hohe Qualität
gifer 1 --size 800                   # 800px breit
gifer 1,2,0.5 --quality high --size 1920x1080  # Kombiniert
gifer --help                         # Hilfe
```

---

## Änderungshistorie

| Version | Datum | Änderungen |
|---------|-------|------------|
| 2.0 | 2025-01-23 | Sekunden statt Millisekunden, --size Parameter |
| 1.0 | 2025-12-10 | Initiale Version |

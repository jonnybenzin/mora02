# Mora02 Clipper v3.2 — 30fps Animation mit Ease In/Out und hoher Qualität (CRF 18)

Mora02 Clipper ist ein Tool zur Erstellung von hochwertigen, flüssigen 30fps-Animationen aus Bildern und Videos. Es unterstützt Smooth-Step-Ease-In/Out-Animationen, Parallax-Effekte und Overlay-Überlagerungen. Es wird in einem selbstgehosteten AI Creative Factory-System unter Ubuntu 24.04 mit RTX 5090 GPU verwendet.

## Quick Start

1. Quell-Ordner mit Medien (`/opt/mora02/output/_default/clipper/source`) vorbereiten
2. Overlay- und Parallax-Ordner (`overlay/`, `layers/`) mit entsprechenden Assets füllen
3. Skript ausführen: `python3 /opt/mora02/output/_default/clipper/clipper.py`

Das Skript erstellt eine 1920x1080-Animation mit 30fps, CRF 18 Qualität und speichert sie in `/opt/mora02/output/_default/clipper/archive/`.

## What It Does

- Erstellt flüssige 30fps-Animationen mit Ease In/Out-Übergängen
- Unterstützt Pan- und Zoom-Animationen mit Smooth-Step-Interpolation
- Fügt Overlay- und Parallax-Effekte hinzu
- Verknüpft Clips mit Übergängen (Crossfade oder harte Schnitte)
- Unterstützt verschiedene Auflösungen (1080p, 4k, story, reels, etc.)
- Erstellt hochwertige Videos mit CRF 18 und Preset `slow`
- Archiviert alle Eingabedaten und Logs

## Parameters

Die folgenden Parameter werden aus dem Code gelesen und können im Skript geändert werden:

| Parameter | Default | Beschreibung |
|---------|---------|-------------|
| `BASE_DIR` | `/opt/mora02/output/_default/clipper` | Basisverzeichnis für Ausgabe |
| `CRF_QUALITY` | `18` | Qualitätseinstellung für Video-Encoder (0 = lossless, 18 = sehr gut) |
| `PRESET` | `slow` | Encoder-Preset (slower = bessere Qualität) |
| `DEFAULT_FPS` | `30` | Standard-Framerate |
| `RESOLUTION_PRESETS` | `{...}` | Voreingestellte Auflösungen |
| `PARALLAX_SPEEDS` | `{'bg': 0.3, 'mg': 0.6, 'fg': 1.0}` | Geschwindigkeitsfaktoren für Parallax-Effekte |

## Practical Examples

### 1. Standard-Animation aus Bildern
```bash
python3 /opt/mora02/output/_default/clipper/clipper.py
```
Erstellt eine 1920x1080-Animation aus allen Bildern im Quell-Ordner mit Default-Animation (Pan, 0°, 20% Intensität).

### 2. Zoom-Animation mit Parallax
```bash
# Ordner mit 1000x1000-Bildern vorbereiten
# Parallax-Ordner mit bg/mg/fg-Unterordnern füllen
python3 /opt/mora02/output/_default/clipper/clipper.py
```
Erstellt eine Zoom-Animation mit Parallax-Effekt (Hintergrund 0.3x, Mittel 0.6x, Vordergrund 1.0x).

### 3. Custom-Auflösung und Übergänge
```bash
# Ordner mit 1280x720-Bildern vorbereiten
# Übergangsdauer auf 1.5s setzen
python3 /opt/mora02/output/_default/clipper/clipper.py
```
Erstellt eine 720p-Animation mit 1.5s Crossfade-Übergängen.

## How It Works

1. **Medien-Scanning**: Sucht nach Bildern und Videos im Quell-Ordner
2. **Animation-Generierung**: Erstellt für jedes Bild eine Animation mit Ease In/Out-Übergang
3. **Clip-Vorbereitung**: Konvertiert Videos in die Zielauflösung
4. **Clip-Verknüpfung**: Verknüpft alle Clips mit Übergängen (Crossfade oder harte Schnitte)
5. **Overlay- und Parallax-Verarbeitung**: Fügt Overlay-Bilder und Parallax-Effekte hinzu
6. **Audio-Verarbeitung**: Fügt optional Audio hinzu
7. **Archivierung**: Speichert alle Eingabedaten und Logs im Archiv-Ordner

## Directory Structure

```
/opt/mora02/output/_default/clipper/
├── source/                  # Quell-Ordner mit Medien
│   ├── image1.jpg
│   ├── video1.mp4
│   ├── overlay/             # Overlay-Bilder
│   └── layers/              # Parallax-Schichten
├── archive/                 # Ausgabe-Ordner
│   ├── source/              # Kopie der Eingabedaten
│   └── logs/                # Log-Dateien
```

## Dependencies

- **ffmpeg** (mit libx264, ffprobe)
- **Python 3** mit Bibliotheken:
  - `shutil`
  - `subprocess`
  - `tempfile`
  - `math`
  - `re`
  - `pathlib`
  - `datetime`

## Configuration

- **Auflösung**: Ändern Sie `RESOLUTION_PRESETS` in der KONFIGURATION-Section
- **Qualität**: Ändern Sie `CRF_QUALITY` und `PRESET` in der KONFIGURATION-Section
- **FPS**: Ändern Sie `DEFAULT_FPS` in der KONFIGURATION-Section
- **Parallax-Geschwindigkeiten**: Ändern Sie `PARALLAX_SPEEDS` in der KONFIGURATION-Section

## Troubleshooting

1. **ffmpeg nicht gefunden**:
   - Fehlermeldung: `❌ ffmpeg nicht gefunden!`
   - Lösung: Installieren Sie ffmpeg mit `sudo apt install ffmpeg`

2. **Keine Medien gefunden**:
   - Fehlermeldung: `❌ Keine Medien in {input_dir} gefunden!`
   - Lösung: Stellen Sie sicher, dass der Quell-Ordner mit Bildern/Videos gefüllt ist

3. **Overlay-Verarbeitung fehlschlägt**:
   - Fehlermeldung: `⚠️  Overlay: {overlay_info['count']} Frames`
   - Lösung: Stellen Sie sicher, dass der Overlay-Ordner mit PNG-Dateien gefüllt ist

4. **Parallax-Verarbeitung fehlschlägt**:
   - Fehlermeldung: `⚠️  Parallax: {layer_name} nicht gefunden`
   - Lösung: Stellen Sie sicher, dass der layers-Ordner mit bg/mg/fg-Unterordnern gefüllt ist

## Shell Script Collections

### backup/
- `backup_logs.sh`: Kopiert alle Log-Dateien in ein Backup-Verzeichnis

### docker/
- `build_docker.sh`: Erstellt eine Docker-Image für Mora02 Clipper
- `run_docker.sh`: Startet den Clipper-Container mit Volumen-Mounts

### system/
- `setup_ubuntu.sh`: Installiert alle erforderlichen System-Tools und Bibliotheken
- `cleanup.sh`: Löscht temporäre Dateien und leert den Quell-Ordner
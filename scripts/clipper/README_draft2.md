# Mora02 — Clipper v3.2: Eine Kreative AI-Factory für Flüssige Animationen

Mora02 — Clipper ist ein lokales Tool, das mit der Kraft von ffmpeg und intelligenten Animationen visuelle Inhalte in hoher Qualität erstellt. Es ist für Entwickler und Kreative gedacht, die schnell und präzise Videos mit flüssigen Übergängen, Parallax-Effekten und Overlay-Elementen produzieren möchten. Die Software ist besonders für die Erstellung von Social-Media-Clips, Produktpräsentationen und animierten Grafiken konzipiert.

## Schnellstart

Erstelle ein einfaches 1080p-Video mit einer 3-Sekunden-Pan-Animation:

```bash
python3 clipper.py
```

Wähle den Quellordner mit einem Bild, setze die Auflösung auf `1920x1080`, wähle `pan` als Animationstyp und bestätige mit Enter. Das Tool erstellt ein Video mit flüssigem Zoom und Bewegung, das in `output.mp4` gespeichert wird.

## Was Clipper kann

Clipper ist ein vollständiges Werkzeug zur Erstellung von animierten Videos. Es unterstützt:

- **Flüssige 30fps-Animationen** mit Ease-In/Out-Übergängen
- **Dynamische Bewegung** in 360°-Richtungen mit Intensitätssteuerung
- **Zoom-Animationen** mit Ein- und Auszoom-Effekten
- **Parallax-Layer-Animationen**, die Hintergrund, Mittel- und Vordergrund in unterschiedlichen Geschwindigkeiten verschieben
- **Überlagerungen (Overlays)**, die in verschiedenen Positionen, Größen und mit Loop-Funktionen hinzugefügt werden können
- **Hochwertige Ausgabe** mit CRF 18 und Slow-Preset für maximale Qualität
- **Automatische Archivierung** aller verwendeten Medien und Einstellungen

## Syntax & Parameter

Die meisten Einstellungen werden interaktiv abgefragt, aber hier sind die wichtigsten Parameter und ihre Defaultwerte:

| Parameter | Default | Beschreibung |
|---------|---------|--------------|
| `width` | 1920 | Bildbreite in Pixel |
| `height` | 1080 | Bildhöhe in Pixel |
| `fps` | 30 | Bildrate |
| `CRF_QUALITY` | 18 | Qualitätseinstellung für Video-Encoder (0 = lossless, 18 = sehr gut) |
| `PARALLAX_SPEEDS` | `bg: 0.3, mg: 0.6, fg: 1.0` | Geschwindigkeitsfaktoren für Parallax-Layer |
| `OVERLAY_POSITIONS` | `center, top-left, ...` | Voreingestellte Positionen für Overlays |
| `DEFAULT_DURATION` | 4.0 | Standarddauer für Bilder in Sekunden |
| `DEFAULT_TRANSITION` | 1.0 | Standarddauer für Übergänge in Sekunden |

## Beispiele aus der Praxis

### 1. LinkedIn-Video mit Pan-Animation
Du willst ein LinkedIn-Video erstellen, das eine Produktvorstellung mit einem flüssigen Zoom und Bewegungseffekt zeigt. Wähle `zoom_in` als Animationstyp, setze die Intensität auf 30% und die Dauer auf 4 Sekunden. Das Tool erstellt ein Video mit einem sanften Zoom-Effekt, der das Produkt in den Vordergrund rückt.

### 2. Instagram-Reels mit Parallax
Für ein Instagram-Reels-Video mit dynamischen Hintergründen nutzt du die Parallax-Funktion. Wähle `bg`, `mg`, `fg` als Layer-Names, setze die Richtung auf 90° und die Intensität auf 50px. Das Video wirkt lebendig und fängt die Aufmerksamkeit der Zuschauer.

### 3. TikTok-Clip mit Overlay
Ein TikTok-Clip benötigt oft ein Overlay mit Text oder Logo. Wähle `top-right` als Position, setze die Skalierung auf 1.2 und aktiviere Loop. Das Overlay bleibt sichtbar und bewegt sich mit dem Hintergrund, was das Video optisch ansprechender macht.

## Wie es technisch funktioniert

Clipper nutzt **ffmpeg** als Kern-Tool für die Videoerstellung. Der Prozess läuft in mehreren Schritten ab:

1. **Eingabe**: Bilder und Videos werden aus einem Quellordner geladen und sortiert.
2. **Animation**: Jedes Bild oder Video wird mit einem Animationsscript verarbeitet, das von `build_animation_filter()` generiert wird. Dabei wird der Ease-In/Out-Effekt implementiert.
3. **Übergänge**: Die Clips werden mit `concatenate_with_transitions()` verbunden, wobei Crossfade-Übergänge oder harte Schnitte unterstützt werden.
4. **Overlays & Parallax**: Overlay-Bilder und Parallax-Layer werden mit `apply_overlay()` und `apply_parallax_layers()` hinzugefügt.
5. **Audio**: Ein externes Audio-Datei kann mit `add_audio()` hinzugefügt werden.
6. **Ausgabe**: Das fertige Video wird in einem Archivordner gespeichert und dort mit einer Logdatei dokumentiert.

## Verzeichnisstruktur

```
/opt/mora02/output/_default/clipper/
├── source/                 # Quelldateien (Bilder, Videos, Overlays, Layers)
│   ├── overlay/            # Overlay-Dateien
│   └── layers/             # Parallax-Layer-Dateien
├── [timestamp]_clipper/    # Archivordner für das aktuelle Projekt
│   ├── source/             # Kopien der verwendeten Medien
│   └── [timestamp]_logs.md # Logdatei mit allen Verarbeitungsschritten
```

## Integration mit anderen Tools

Clipper ist als Teil der Mora02-Plattform konzipiert und kann mit anderen Tools wie:

- **Pexels** (für Bildquellen)
- **Typer** (für Text- und Untertitel-Erstellung)
- **Gifer** (für GIF-Animationen)
- **Script-Runner** (für automatisierte Prozesse)

integriert werden. Die Quelldateien werden automatisch in den `source/`-Ordner kopiert, sodass sie für andere Tools weiterverwendet werden können.

## Abhängigkeiten & Konfiguration

Clipper benötigt:

- **ffmpeg** (mit x264-Encoder)
- **Python 3** mit den Bibliotheken `shutil`, `subprocess`, `re`, `pathlib`, `datetime`, `sys`, `os`, `math`

Um Clipper zu starten, muss `ffmpeg` im System installiert sein. Die Konfiguration erfolgt über die `KONFIGURATION`-Sektion im Skript.

## Troubleshooting

### 1. Fehler bei der Videoerstellung
Wenn ein Fehler während der Videoerstellung auftritt, wird dies in der Logdatei protokolliert. Häufige Ursachen sind fehlende Dateien, unvollständige Overlay- oder Parallax-Ordner oder falsche Einstellungen für die Animation.

### 2. Fehlende ffmpeg-Unterstützung
Wenn `ffmpeg` nicht installiert ist oder nicht gefunden wird, wird ein Fehler ausgegeben. Stelle sicher, dass `ffmpeg` im Systempfad installiert ist und mit `ffmpeg -version` ausgeführt werden kann.

### 3. Falsche Dateiformate
Clipper unterstützt nur bestimmte Dateiformate (`.jpg`, `.png`, `.mp4`, `.mov`, etc.). Wenn eine Datei nicht erkannt wird, prüfe das Format und die Dateiendung.
# Mora02 GIF Creator — Bildsequenz zu GIF Converter mit Archivierung  
Erstellt animierte GIFs aus nummerierten Bildern mit individuellen Frame-Dauern und archiviert Quellbilder + GIF automatisch.  
Wird verwendet, um eine Serie von nummerierten Bildern (z. B. 01-name.jpg, 02-name.jpg) in ein GIF zu konvertieren und die Quelldaten sicher zu archivieren.

## Quick Start
```bash
cd /opt/mora02/output/_default/gifer/source
cp /path/to/your/images/*.jpg .
python3 /opt/mora02/output/_default/gifer/gifer.py 1000,1500,2000 --quality high
```

## What It Does
Der Tool:
- Sucht nach nummerierten Bildern im `source`-Verzeichnis (z. B. `01-name.jpg`, `02-name.jpg`)
- Standardisiert die Größe aller Bilder auf die kleinsten Dimensionen der Quellbilder
- Erstellt ein GIF mit individuellen Frame-Dauern (angegeben über Kommandozeile oder `durations.txt`)
- Archiviert Quellbilder und das erstellte GIF in einem zeitgestempelten Ordner
- Löscht alle Quellbilder im `source`-Verzeichnis nach der Konvertierung (außer `durations.txt`)
- Erstellt einen Log-File mit Details zur Konvertierung

## Parameters
Die folgenden Parameter können über die Kommandozeile oder in der Konfiguration geändert werden:

| Parameter | Default | Beschreibung |
|----------|---------|-------------|
| `DAUERN` | `1000` | Dauer jedes Frames in Millisekunden. Kann als Liste (z. B. `1000,1500,2000`) angegeben werden |
| `--quality` | `medium` | Qualitätseinstellung: `low`, `medium`, `high`, `ultra` |

## Practical Examples
### 1. Standard-Konvertierung
```bash
python3 gifer.py 1000
```
- Erstellt ein GIF mit 1000ms pro Frame
- Verwendet `medium`-Qualität (128 Farben, 75% Größenreduktion)
- Archiviert alle Bilder und das GIF in einem Ordner mit Zeitstempel

### 2. Hochqualitatives GIF
```bash
python3 gifer.py 1000,500,2000 --quality high
```
- Erstellt ein GIF mit variablen Frame-Dauern
- Verwendet `high`-Qualität (256 Farben, keine Komprimierung)
- Archiviert Quellbilder und GIF

### 3. Verwenden von `durations.txt`
```bash
echo "1000,1500" > /opt/mora02/output/_default/gifer/source/durations.txt
python3 gifer.py
```
- Frame-Dauern werden aus `durations.txt` gelesen
- Standard-Dauer (`1000ms`) wird für fehlende Einträge verwendet

## How It Works
1. **Bildsuche**: Nummerierte Bilder (`01-name.jpg`, `02-name.jpg`) werden im `source`-Verzeichnis gesucht
2. **Größenanalyse**: Die kleinsten Bildgrößen werden als Zielgröße verwendet
3. **Standardisierung**: Alle Bilder werden skaliert und gecroppt, um die Zielgröße zu erreichen
4. **Qualitätseinstellungen**: Farbtiefe, Komprimierung und Größenfaktor werden je nach Qualitätslevel angewendet
5. **GIF-Erstellung**: Bilder werden mit individuellen Frame-Dauern in ein GIF konvertiert
6. **Archivierung**: Quellbilder und GIF werden in einem zeitgestempelten Ordner gespeichert
7. **Aufräumen**: Quellbilder im `source`-Verzeichnis werden gelöscht (außer `durations.txt`)

## Directory Structure
```
/opt/mora02/output/_default/gifer/
├── source/                  # Quellbilder (01-name.jpg, 02-name.jpg, durations.txt)
├── [YYYYMMDDHHMM]_gifer/    # Archiv-Ordner mit Zeitstempel
│   ├── source/              # Kopie der Quellbilder
│   ├── [YYYYMMDDHHMM].gif   # Erstelles GIF
│   └── [YYYYMMDDHHMM]_logs.md  # Log-Datei mit Konvertierungsdetails
```

## Dependencies
- Python 3.10+
- `Pillow` (für Bildbearbeitung)
- `shutil` (für Dateikopie)
- `pathlib` (für Dateipfade)
- System-Tools: `mkdir`, `cp`, `rm`

## Configuration
Die folgenden Variablen in der Konfiguration können geändert werden:

- `BASE_DIR` (Zeile 13): Basis-Verzeichnis für Output
- `INPUT_DIR` (Zeile 14): Quellverzeichnis für Bilder
- `ARCHIVE_BASE` (Zeile 15): Basis-Verzeichnis für Archivierung
- `DEFAULT_DURATION` (Zeile 17): Standard-Frame-Dauer in ms
- `QUALITY_PRESETS` (Zeile 29–57): Qualitäts-Einstellungen

## Troubleshooting
### 1. Keine nummerierten Bilder gefunden
- **Ursache**: Keine Bilder im Format `01-name.jpg`, `02-name.jpg` im `source`-Verzeichnis
- **Lösung**: Bilder in das `source`-Verzeichnis kopieren und erneut ausführen

### 2. Fehler bei der GIF-Erstellung
- **Ursache**: Fehlende oder unvollständige Bilder, falsche Dateiformate
- **Lösung**: Überprüfen Sie, ob alle Bilder vorhanden sind und im korrekten Format vorliegen

### 3. Kein Log-File erstellt
- **Ursache**: Schreibrechte fehlen im Archiv-Verzeichnis
- **Lösung**: Schreibrechte für den Benutzer überprüfen oder Pfad anpassen

### 4. Fehler bei der Archivierung
- **Ursache**: Kein Schreibzugriff auf `ARCHIVE_BASE`
- **Lösung**: Schreibrechte für den Benutzer überprüfen oder Pfad anpassen

## Shell Script Collections
### backup/
- `backup_gif.sh`: Kopiert das erstellte GIF in ein Backup-Verzeichnis
- `backup_logs.sh`: Kopiert den Log-File in ein Backup-Verzeichnis

### docker/
- `build_docker.sh`: Erstellt eine Docker-Image für den Tool
- `run_docker.sh`: Führt den Tool in einem Docker-Container aus

### system/
- `setup_permissions.sh`: Stellt Schreibrechte für `source` und `archive`-Verzeichnis sicher
- `monitor_gif.sh`: Überwacht den `source`-Ordner und startet den Tool automatisch bei Änderungen
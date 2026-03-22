# typer — Text-Frame Generator for gifer  
Generiert PNG-Bilder mit Text in der Schriftart JetBrains Mono. Wird verwendet, um Text-Frame-Bilder für GIF-Animationen zu erstellen. Ideal für statische Text-Überschriften oder Titelbilder.

## Quick Start  
Erstelle ein Text-Frame mit Standard-Einstellungen:  
```bash
./typer "Hello, World!" --template dark --font bold --fontsize medium
```  
Dies erzeugt ein PNG-Bild mit dem Text "Hello, World!" in der Schriftart JetBrains Mono Bold auf einem dunklen Hintergrund.

## What It Does  
typer generiert PNG-Bilder mit Text, wobei folgende Funktionen unterstützt werden:  
- Text-Umbruch basierend auf der Bildbreite  
- Farbvorlagen für Hintergrund und Textfarbe (dunkel, hell, schwarz)  
- Schriftarten: Bold, Thin, Bold-Italic, Thin-Italic  
- Schriftgröße relativ zur Bildhöhe oder in Pixel  
- Layout-Optionen: linksbündig oder zentriert  
- Automatische Dateinamen mit Timestamp und Nummerierung  

## Parameters  
Die folgenden Parameter sind über die Befehlszeile konfigurierbar:  

| Parameter       | Default         | Beschreibung                                                                 |
|----------------|------------------|------------------------------------------------------------------------------|
| `text`         | (required)       | Der Text, der in das Bild eingefügt wird. Zeilenumbrüche mit `\n` angeben.   |
| `--size`       | `1080x1080`      | Bildgröße im Format `WxH`.                                                   |
| `--template`   | `dark`           | Farbvorlage: `dark`, `darker`, `light`, `black`.                            |
| `--font`       | `bold`           | Schriftart: `bold`, `bold-italic`, `thin`, `thin-italic`.                   |
| `--fontsize`   | `medium`         | Schriftgröße: `small`, `medium`, `large` oder direkte Pixelangabe.          |
| `--layout`     | `left`           | Text-Layout: `left` oder `centered`.                                        |

## Practical Examples  
### 1. Standard-Text-Frame  
```bash
./typer "Welcome to Mora02!" --template dark --font bold
```  
Erzeugt ein dunkles Bild mit zentriertem Text in Bold-Schrift.

### 2. Zentrierter Text mit hellen Farben  
```bash
./typer "This is a centered text" --template light --layout centered
```  
Erzeugt ein hellgrau-weißes Bild mit zentriertem Text.

### 3. Thin-Schrift mit benutzerdefinierter Größe  
```bash
./typer "Thin Text" --font thin --fontsize 48
```  
Erzeugt ein Bild mit Thin-Schrift in 48 Pixel Größe.

### 4. Großes Bild mit kleiner Schrift  
```bash
./typer "Small text on big image" --size 3840x2160 --fontsize small
```  
Erzeugt ein 4K-Bild mit kleiner Schrift.

## How It Works  
typer folgt einem einfachen Pipeline:  
1. **Eingabe**: Text und Parameter werden über die Befehlszeile empfangen.  
2. **Bild-Erstellung**: Ein neues PNG-Bild wird mit dem Hintergrundfarb-Template erstellt.  
3. **Schriftart**: Die gewählte JetBrains Mono-Schriftart wird geladen und skaliert.  
4. **Text-Umbruch**: Der Text wird basierend auf der Bildbreite umbrochen.  
5. **Positionierung**: Der Text wird entweder linksbündig oder zentriert platziert.  
6. **Speicherung**: Das Bild wird mit einem Dateinamen im Format `YYMMDDHHMM_typer_XXX.png` gespeichert.

## Directory Structure  
```
/opt/mora02/output/_default/typer/
├── fonts/                      # Schriftarten-Dateien (z. B. JetBrainsMono-ExtraBold.ttf)
└── [generated images]          # PNG-Dateien werden hier gespeichert
```

## Dependencies  
- Python 3.10+  
- `Pillow` (für Bildbearbeitung)  
- `argparse` (für Befehlszeilen-Parameter)  
- Schriftdateien in `/opt/mora02/output/_default/typer/fonts/`

## Configuration  
- **Font-Verzeichnis**: `/opt/mora02/output/_default/typer/fonts` (Zeile 13)  
- **Ausgabeverzeichnis**: `/opt/mora02/output/_default/typer` (Zeile 14)  
- **Farbvorlagen**: `TEMPLATES` (Zeile 18–23)  
- **Schriftarten-Mapping**: `FONTS` (Zeile 26–29)

## Troubleshooting  
### 1. **Fehlende Schriftdateien**  
**Problem**: Fehlermeldung `FileNotFoundError` beim Laden der Schrift.  
**Ursache**: Schriftdateien fehlen im Verzeichnis `/opt/mora02/output/_default/typer/fonts/`.  
**Lösung**: Stelle sicher, dass alle erforderlichen `.ttf`-Dateien vorhanden sind.

### 2. **Text wird abgeschnitten**  
**Problem**: Text ist nicht vollständig sichtbar.  
**Ursache**: Schriftgröße ist zu groß oder Text-Umbruch nicht korrekt.  
**Lösung**: Ändere `--fontsize` oder passe `--size` an.

### 3. **Bild wird nicht gespeichert**  
**Problem**: Keine Datei wird in `/opt/mora02/output/_default/typer/` erstellt.  
**Ursache**: Schreibrechte fehlen oder Ausgabeverzeichnis ist nicht vorhanden.  
**Lösung**: Überprüfe Rechte mit `ls -l /opt/mora02/output/_default/typer/` und stelle sicher, dass der Benutzer Schreibrechte hat.

### 4. **Falsche Farbvorlage**  
**Problem**: Farben stimmen nicht mit der gewählten Vorlage überein.  
**Ursache**: `TEMPLATES`-Dictionary ist falsch konfiguriert.  
**Lösung**: Prüfe Zeile 18–23 und passe `text_color` und `bg_color` an.

---

## Shell Script Collections  
### backup/  
- `backup_fonts.sh`: Kopiert Schriftdateien in ein Backup-Verzeichnis.  
- `backup_output.sh`: Sicherung aller generierten PNG-Dateien.  
**Zweck**: Automatisierte Sicherung von Schrift- und Ausgabedaten.  

### docker/  
- `build.sh`: Baut eine Docker-Image mit typer.  
- `run.sh`: Startet typer in einem Docker-Container.  
**Zweck**: Einfache Deployment und Isolation der Anwendung.  

### system/  
- `install_deps.sh`: Installiert Python-Abhängigkeiten.  
- `setup_dirs.sh`: Erstellt notwendige Verzeichnisse und setzt Rechte.  
**Zweck**: Automatisierte Systemvorbereitung.
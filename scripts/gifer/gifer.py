#!/usr/bin/env python3
"""
Mora02 - Bildsequenz zu GIF Converter mit Archivierung
Erstellt animierte GIFs aus nummerierten Bildern mit individuellen Frame-Dauern
und archiviert Quellbilder + GIF automatisch

USAGE:
  gifer [DAUERN] [--quality LEVEL]
"""

import os
import shutil
from pathlib import Path
from PIL import Image, ImageOps
import sys
from datetime import datetime

# ============================================================================
# KONFIGURATION
# ============================================================================

BASE_DIR = "/opt/mora02/output/_default/gifer"
INPUT_DIR = f"{BASE_DIR}/source"
ARCHIVE_BASE = BASE_DIR
DEFAULT_DURATION = 1000
LOOP = 0

# Qualitäts-Presets
QUALITY_PRESETS = {
    'low': {
        'colors': 64,
        'optimize': True,
        'resize': 0.5,
        'description': 'Kleine Datei, niedrige Qualität (50% Größe, 64 Farben)'
    },
    'medium': {
        'colors': 128,
        'optimize': True,
        'resize': 0.75,
        'description': 'Ausgewogen (75% Größe, 128 Farben)'
    },
    'high': {
        'colors': 256,
        'optimize': True,
        'resize': 1.0,
        'description': 'Beste Qualität (Original-Größe, 256 Farben)'
    },
    'ultra': {
        'colors': 256,
        'optimize': False,
        'resize': 1.0,
        'description': 'Maximale Qualität, größte Datei (unkomprimiert)'
    }
}

DEFAULT_QUALITY = 'medium'

# ============================================================================
# LOGGING
# ============================================================================

class Logger:
    """Dual-Output Logger (Console + File)"""
    
    def __init__(self):
        self.log_buffer = []
        self.log_file = None
        
    def set_log_file(self, log_file):
        """Setzt den Log-Dateipfad"""
        self.log_file = log_file
        
    def log(self, message):
        """Schreibt in Console UND speichert für Datei"""
        print(message)
        self.log_buffer.append(message)
    
    def save(self):
        """Speichert Log in Markdown-Datei"""
        if not self.log_file:
            return
            
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write("# Mora02 GIF Creator - Log\n\n")
                f.write(f"**Erstellt:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("```\n")
                f.write('\n'.join(self.log_buffer))
                f.write("\n```\n")
            self.log(f"\n📝 Log gespeichert: {self.log_file}")
        except Exception as e:
            print(f"⚠️  Log konnte nicht gespeichert werden: {e}")

# ============================================================================
# FUNCTIONS - IMAGE STANDARDIZATION
# ============================================================================

def get_smallest_image_dimensions(image_files):
    """Findet die kleinsten Dimensionen aus allen Bildern"""
    if not image_files:
        return None
    
    dimensions = []
    for img_path in image_files:
        try:
            img = Image.open(img_path)
            dimensions.append({
                'path': img_path,
                'width': img.width,
                'height': img.height,
                'area': img.width * img.height
            })
        except Exception as e:
            print(f"⚠️  Fehler beim Auslesen von {img_path.name}: {e}")
            continue
    
    if not dimensions:
        return None
    
    # Finde das Bild mit der kleinsten Fläche
    smallest = min(dimensions, key=lambda x: x['area'])
    return smallest['width'], smallest['height']

def standardize_image(img, target_width, target_height, logger):
    """
    Skaliert und croppt Bild intelligent auf Zielgröße:
    - Aspect ratio wird beibehalten
    - Von der Mitte wird gecroppt, wenn Seitenverhältnis nicht passt
    """
    try:
        standardized = ImageOps.fit(
            img,
            (target_width, target_height),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5)
        )
        return standardized
    except Exception as e:
        logger.log(f"   ❌ Fehler beim Standardisieren: {e}")
        return None

# ============================================================================
# FUNCTIONS - ORIGINAL
# ============================================================================

def create_timestamp():
    """Erstellt Zeitstempel im Format YYYYMMDDHHMM"""
    return datetime.now().strftime("%Y%m%d%H%M")

def parse_quality_from_args():
    """Liest Qualitäts-Parameter aus Kommandozeile"""
    if '--quality' in sys.argv:
        idx = sys.argv.index('--quality')
        if idx + 1 < len(sys.argv):
            quality = sys.argv[idx + 1].lower()
            if quality in QUALITY_PRESETS:
                return quality
            else:
                print(f"⚠️  Ungültige Qualität: {quality}")
                print(f"   Verfügbar: {', '.join(QUALITY_PRESETS.keys())}")
                print(f"   Verwende Default: {DEFAULT_QUALITY}")
    return DEFAULT_QUALITY

def find_numbered_images(directory):
    """Findet alle Bilder mit Nummerierung 01-*, 02-*, etc."""
    image_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
    
    images = []
    for file in sorted(Path(directory).glob("*")):
        if file.suffix.lower() in image_extensions:
            name = file.stem
            if len(name) >= 2 and name[:2].isdigit():
                images.append(file)
    
    return sorted(images, key=lambda x: x.stem[:2])

def parse_durations_from_args():
    """Liest Frame-Dauern aus Kommandozeilen-Argumenten"""
    args = [arg for i, arg in enumerate(sys.argv[1:]) 
            if arg != '--quality' and (i == 0 or sys.argv[i] != '--quality')]
    
    if len(args) < 1:
        return None
    
    duration_string = args[0]
    
    if duration_string.isdigit():
        return [int(duration_string)]
    
    try:
        durations = [int(d.strip()) for d in duration_string.split(',')]
        return durations
    except ValueError:
        return None

def parse_durations_from_file(input_dir):
    """Liest Frame-Dauern aus durations.txt im source-Ordner"""
    durations_file = Path(input_dir) / "durations.txt"
    
    if not durations_file.exists():
        return None
    
    try:
        content = durations_file.read_text().strip()
        
        if ',' in content:
            durations = [int(d.strip()) for d in content.split(',')]
        else:
            durations = [int(line.strip()) for line in content.split('\n') if line.strip()]
        
        return durations
    except:
        return None

def get_frame_durations(input_dir, num_frames, default_duration, logger):
    """Ermittelt Frame-Dauern mit Priorität"""
    
    durations = parse_durations_from_args()
    if durations:
        logger.log(f"✅ Frame-Dauern aus Kommandozeile: {durations}")
        if len(durations) == 1:
            return durations * num_frames
        if len(durations) < num_frames:
            missing = num_frames - len(durations)
            durations.extend([default_duration] * missing)
            logger.log(f"ℹ️  {missing} Frames mit Default-Dauer ({default_duration}ms) aufgefüllt")
        return durations[:num_frames]
    
    durations = parse_durations_from_file(input_dir)
    if durations:
        logger.log(f"✅ Frame-Dauern aus durations.txt geladen: {len(durations)} Werte")
        if len(durations) < num_frames:
            missing = num_frames - len(durations)
            durations.extend([default_duration] * missing)
            logger.log(f"ℹ️  {missing} Frames mit Default-Dauer ({default_duration}ms) aufgefüllt")
        return durations[:num_frames]
    
    logger.log(f"ℹ️  Keine Dauern angegeben → Default-Dauer ({default_duration}ms) für alle Frames")
    return [default_duration] * num_frames

def resize_image(img, scale):
    """Skaliert Bild nach Faktor"""
    if scale == 1.0:
        return img
    
    new_width = int(img.width * scale)
    new_height = int(img.height * scale)
    return img.resize((new_width, new_height), Image.Resampling.LANCZOS)

def create_gif(input_dir, output_path, quality_preset, logger):
    """Erstellt GIF aus Bildsequenz mit Qualitäts-Einstellungen"""
    
    image_files = find_numbered_images(input_dir)
    
    if not image_files:
        logger.log(f"❌ Keine nummerierten Bilder in {input_dir} gefunden!")
        logger.log("   Erwartet: 01-name.jpg, 02-name.jpg, etc.")
        return False, []
    
    # ========== Bild-Standardisierung ==========
    logger.log("\n🔍 Analysiere Bildgrößen...")
    
    target_dims = get_smallest_image_dimensions(image_files)
    if not target_dims:
        logger.log("❌ Fehler: Konnte keine Bildgrößen auslesen!")
        return False, []
    
    target_width, target_height = target_dims
    logger.log(f"✅ Zielformat (kleinstes Bild): {target_width}x{target_height}px")
    
    # Detaillierte Größen-Info
    logger.log("\n📊 Bildgrößen vor Standardisierung:")
    for img_path in image_files:
        img = Image.open(img_path)
        logger.log(f"   {img_path.name}: {img.width}x{img.height}px")
    # ========== END Bild-Standardisierung ==========
    
    preset = QUALITY_PRESETS[quality_preset]
    
    logger.log(f"\n✅ {len(image_files)} Bilder gefunden")
    logger.log(f"🎨 Qualität: {quality_preset.upper()} - {preset['description']}")
    
    durations = get_frame_durations(input_dir, len(image_files), DEFAULT_DURATION, logger)
    
    frames = []
    
    for idx, img_path in enumerate(image_files):
        try:
            img = Image.open(img_path)
            
            # Standardisierung anwenden
            img = standardize_image(img, target_width, target_height, logger)
            if img is None:
                return False, []
            
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            if preset['colors'] < 256:
                img = img.convert('P', palette=Image.Palette.ADAPTIVE, colors=preset['colors'])
                img = img.convert('RGB')
            
            frames.append(img)
            
            logger.log(f"   {idx+1}. {img_path.name}: {target_width}x{target_height}px → {durations[idx]}ms")
            
        except Exception as e:
            logger.log(f"   ❌ Fehler beim Laden von {img_path.name}: {e}")
            return False, []
    
    try:
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=LOOP,
            optimize=preset['optimize']
        )
        
        file_size = output_path.stat().st_size / (1024 * 1024)
        
        logger.log(f"\n✅ GIF erfolgreich erstellt!")
        logger.log(f"   📁 Pfad: {output_path}")
        logger.log(f"   📊 Größe: {file_size:.2f} MB")
        logger.log(f"   🎬 Frames: {len(frames)}")
        logger.log(f"   ⏱️  Gesamt-Dauer: {sum(durations)/1000:.1f}s")
        logger.log(f"   🎞️  Durchschnitt: {sum(durations)/len(durations):.0f}ms pro Frame")
        
        return True, image_files
        
    except Exception as e:
        logger.log(f"❌ Fehler beim Erstellen der GIF: {e}")
        return False, []

def archive_files(source_images, gif_path, archive_base, timestamp, logger):
    """Archiviert Quellbilder und GIF in timestamptem Ordner"""
    
    archive_dir = Path(archive_base) / f"{timestamp}_gifer"
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    logger.log(f"\n📦 Archivierung nach: {archive_dir}")
    
    source_archive = archive_dir / "source"
    source_archive.mkdir(exist_ok=True)
    
    for img in source_images:
        dest = source_archive / img.name
        shutil.copy2(img, dest)
        logger.log(f"   ✓ {img.name} → source/")
    
    logger.log(f"   ✓ {gif_path.name}")
    
    return archive_dir

def cleanup_source(input_dir, logger):
    """Löscht alle Dateien im Source-Ordner (außer durations.txt)"""
    
    logger.log(f"\n🧹 Räume Source-Ordner auf: {input_dir}")
    
    deleted_count = 0
    for file in Path(input_dir).iterdir():
        # Überspringe nur durations.txt
        if file.is_file() and file.name != 'durations.txt':
            try:
                file.unlink()
                logger.log(f"   ✓ Gelöscht: {file.name}")
                deleted_count += 1
            except Exception as e:
                logger.log(f"   ❌ Fehler beim Löschen von {file.name}: {e}")
    
    logger.log(f"✅ {deleted_count} Datei(en) aus Source gelöscht")

def print_usage():
    """Zeigt Hilfe-Text"""
    print("""
USAGE:

  gifer [DAUERN] [--quality LEVEL]

Beispiele:
  gifer 1000,1500,2000
  gifer 1000,1500,2000 --quality high
  gifer 1000 --quality low

Qualität: low, medium (default), high, ultra
""")

def main():
    """Hauptfunktion"""
    
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h', 'help']:
        print_usage()
        return
    
    # Logger initialisieren (ohne Log-File vorerst)
    logger = Logger()
    
    logger.log("=" * 70)
    logger.log("Mora02 - Bildsequenz zu GIF Converter mit Archivierung")
    logger.log("=" * 70)
    logger.log("")
    
    Path(INPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(ARCHIVE_BASE).mkdir(parents=True, exist_ok=True)
    
    test_images = find_numbered_images(INPUT_DIR)
    if not test_images:
        logger.log(f"ℹ️  Source-Verzeichnis leer: {INPUT_DIR}")
        logger.log(f"\nBitte Bilder in dieses Verzeichnis kopieren:")
        logger.log(f"   Format: 01-name.jpg, 02-name.jpg, etc.")
        logger.log(f"\nDann: gifer 1000,500,2000 --quality high")
        return
    
    quality = parse_quality_from_args()
    timestamp = create_timestamp()
    
    archive_dir = Path(ARCHIVE_BASE) / f"{timestamp}_gifer"
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    # WICHTIG: Log-File-Pfad im Archiv-Ordner/source setzen
    source_archive = archive_dir / "source"
    source_archive.mkdir(exist_ok=True)
    log_file = source_archive / f"{timestamp}_logs.md"
    logger.set_log_file(log_file)
    
    gif_filename = f"{timestamp}.gif"
    gif_path = archive_dir / gif_filename
    
    success, source_images = create_gif(INPUT_DIR, gif_path, quality, logger)
    
    if not success:
        logger.log("\n" + "=" * 70)
        logger.log("❌ Fehler beim Erstellen der GIF")
        logger.log("=" * 70)
        logger.save()
        sys.exit(1)
    
    archive_files(source_images, gif_path, ARCHIVE_BASE, timestamp, logger)
    cleanup_source(INPUT_DIR, logger)
    
    logger.log("\n" + "=" * 70)
    logger.log("✅ Fertig!")
    logger.log("=" * 70)
    logger.log(f"\n📁 Archiv: {archive_dir}")
    logger.log(f"   ├── {gif_filename}")
    logger.log(f"   └── source/")
    logger.log(f"       ├── {timestamp}_logs.md")
    logger.log(f"       └── (Quellbilder)")
    
    # Log speichern
    logger.save()

if __name__ == "__main__":
    main()

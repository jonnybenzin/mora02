#!/usr/bin/env python3
"""
Mora02 - Pixabay Batch Image Downloader
Lädt mehrere Bilder mit Suchbegriffen und archiviert sie automatisch.

USAGE:
  pixabay "query1" "query2" "query3"
"""

import os
import sys
import json
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

# ============================================================================
# KONFIGURATION
# ============================================================================

PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")
BASE_DIR = "/opt/mora02/output/_default/pixabay"

# laut Doku: image_type = all | photo | illustration | vector
IMAGE_TYPE = "photo"

# laut Doku: orientation = all | horizontal | vertical
ORIENTATION = "horizontal"

# ============================================================================
# FUNCTIONS
# ============================================================================

def create_timestamp():
    """Erstellt Zeitstempel im Format YYYYMMDDHHMM"""
    return datetime.now().strftime("%Y%m%d%H%M")

def search_pixabay(query):
    """Sucht ein Bild auf Pixabay"""

    params = {
        "key": PIXABAY_API_KEY,
        "q": query,
        "image_type": IMAGE_TYPE,
        "orientation": ORIENTATION,
        "per_page": 3,          # 3–200 erlaubt, hier: bestes Bild
        "safesearch": "true",   # laut Doku true/false
        "order": "popular",     # popular | latest
    }

    url = "https://pixabay.com/api/?" + urllib.parse.urlencode(params)

    try:
        with urllib.request.urlopen(url) as response:
            raw = response.read().decode()
            data = json.loads(raw)

            # laut Doku: totalHits = Anzahl der passenden Bilder
            if data.get("totalHits", 0) == 0:
                return None, None, None

            hits = data.get("hits") or []
            if not hits:
                return None, None, None

            hit = hits[0]

            # laut Doku: largeImageURL ist großes Bild, webformatURL 640px
            image_url = hit.get("largeImageURL") or hit.get("previewURL")
            image_id = hit.get("id")
            user = hit.get("user")

            if not image_url or not image_id:
                return None, None, None

            return image_url, image_id, user

    except urllib.error.HTTPError as e:
        print(f"   ❌ HTTP-Fehler {e.code}: {e.reason}")
        # Pixabay nutzt u.a. 400/401/403 bei Key-/Request-Problemen
        try:
            body = e.read().decode()
            if body:
                print(f"   ℹ️  Antwort: {body[:300]}...")
        except Exception:
            pass
        return None, None, None
    except Exception as e:
        print(f"   ❌ API-Fehler: {e}")
        return None, None, None

def download_image(url, output_path):
    """Lädt Bild herunter mit einfachem Header-Workaround"""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req) as resp, open(output_path, "wb") as f:
            f.write(resp.read())
        return True
    except Exception as e:
        print(f"   ❌ Download-Fehler: {e}")
        return Falsese

def get_file_size(filepath):
    """Gibt Dateigröße in MB zurück"""
    size_bytes = os.path.getsize(filepath)
    return size_bytes / (1024 * 1024)

def print_usage():
    """Zeigt Hilfe-Text"""
    print("""
USAGE - Pixabay Batch Image Downloader

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Basis-Syntax:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  pixabay "query1" "query2" "query3" ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Beispiele:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  pixabay "eiffel tower sunset"
  pixabay "olympic tower munich" "eiffel tower winter" "neuschwanstein"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

def main():
    """Hauptfunktion"""

    if len(sys.argv) < 2 or sys.argv[1] in ["--help", "-h", "help"]:
        print_usage()
        return

    print("=" * 70)
    print("Mora02 - Pixabay Batch Image Downloader")
    print("=" * 70)
    print()

    Path(BASE_DIR).mkdir(parents=True, exist_ok=True)

    timestamp = create_timestamp()
    archive_dir = Path(BASE_DIR) / f"{timestamp}_pixabay"
    archive_dir.mkdir(parents=True, exist_ok=True)

    print(f"📁 Archiv: {archive_dir}\n")

    queries = sys.argv[1:]
    print(f"🔍 {len(queries)} Suchbegriff(e)\n")

    downloaded = 0
    failed = 0

    for idx, query in enumerate(queries, 1):
        print(f"[{idx}/{len(queries)}] Suche: \"{query}\"")

        image_url, image_id, user = search_pixabay(query)

        if not image_url:
            print("   ❌ Kein Bild gefunden")
            failed += 1
            print()
            continue

        filename = f"{timestamp}_{image_id}.jpg"
        output_path = archive_dir / filename

        print(f"   📥 Lade herunter (ID: {image_id}, by {user})...")

        if download_image(image_url, output_path):
            size_mb = get_file_size(output_path)
            print(f"   ✅ Gespeichert: {filename} ({size_mb:.2f} MB)")
            downloaded += 1
        else:
            failed += 1

        print()

    print("=" * 70)
    print("✅ Download abgeschlossen!")
    print("=" * 70)
    print("\n📊 Statistik:")
    print(f"   Erfolgreich: {downloaded}")
    print(f"   Fehlgeschlagen: {failed}")
    print(f"   Gesamt: {len(queries)}")
    print(f"\n📁 Archiv: {archive_dir}")

    if downloaded > 0:
        print("\n📷 Heruntergeladene Bilder:")
        for img in sorted(archive_dir.glob("*.jpg")):
            size_mb = get_file_size(img)
            print(f"   • {img.name} ({size_mb:.2f} MB)")

if __name__ == "__main__":
    main()

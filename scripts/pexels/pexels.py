#!/usr/bin/env python3
"""
Mora02 - Pexels Batch Image Downloader (Multi-Select Optional)
Default: 1 Bild pro Query. Mit --count N: mehrere Versionen.

USAGE:
  pexels "query1" "query2"           # 1 pro Query (default)
  pexels "query1" --count 3          # 3 pro Query
  pexels "query1" "query2" --count 5 # 5 pro Query
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

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
BASE_DIR = "/opt/mora02/output/_default/pexels"
ORIENTATION = "landscape"

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# ============================================================================
# FUNCTIONS
# ============================================================================

def create_timestamp():
    return datetime.now().strftime("%Y%m%d%H%M")

def make_request(url, headers=None):
    """Führt Request mit Custom-Headers aus"""
    if headers is None:
        headers = {}
    
    req_headers = {
        "User-Agent": USER_AGENT,
        **headers
    }
    
    req = urllib.request.Request(url, headers=req_headers)
    return urllib.request.urlopen(req)

def search_pexels(query, count=1):
    """Sucht Bilder auf Pexels"""
    per_page = min(count, 80)
    
    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page={per_page}&orientation={ORIENTATION}"
    
    try:
        with make_request(url, {"Authorization": PEXELS_API_KEY}) as response:
            data = json.loads(response.read().decode())
            
            if 'photos' not in data or len(data['photos']) == 0:
                return []
            
            results = []
            for photo in data['photos'][:count]:
                src = photo['src']
                image_url = src.get('original') or src.get('large2x')
                photo_id = photo['id']
                photographer = photo['photographer']
                
                if image_url:
                    results.append({
                        'url': image_url,
                        'id': photo_id,
                        'photographer': photographer
                    })
            
            return results
            
    except urllib.error.HTTPError as e:
        print(f"   ❌ HTTP-Fehler {e.code}: {e.reason}")
        return []
    except Exception as e:
        print(f"   ❌ API-Fehler: {e}")
        return []

def download_image(url, output_path):
    """Lädt Bild mit User-Agent herunter"""
    try:
        with make_request(url) as response, open(output_path, "wb") as f:
            f.write(response.read())
        return True
    except Exception as e:
        print(f"      ❌ Download-Fehler: {e}")
        return False

def get_file_size(filepath):
    try:
        size_bytes = os.path.getsize(filepath)
        return size_bytes / (1024 * 1024)
    except:
        return 0

def print_usage():
    print("""
USAGE: pexels "query1" "query2" [--count N]

  Default: 1 Bild pro Query
  Mit --count N: N verschiedene Versionen pro Query

Beispiele:
  pexels "eiffel tower sunset"           # 1 Bild
  pexels "eiffel tower sunset" --count 3 # 3 Bilder zum Aussuchen
  pexels "paris" "london" --count 5      # 5 pro Query
""")

def parse_args():
    """Parse Kommandozeilenargumente"""
    if len(sys.argv) < 2 or sys.argv[1] in ['--help', '-h']:
        print_usage()
        sys.exit(0)
    
    queries = []
    count = 1  # DEFAULT: 1
    
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--count':
            if i + 1 < len(sys.argv):
                try:
                    count = int(sys.argv[i + 1])
                    count = max(1, min(count, 80))  # 1–80
                    i += 2
                except ValueError:
                    print(f"❌ Ungültige Zahl für --count: {sys.argv[i+1]}")
                    sys.exit(1)
            else:
                print("❌ --count benötigt eine Zahl")
                sys.exit(1)
        else:
            queries.append(sys.argv[i])
            i += 1
    
    if not queries:
        print("❌ Mindestens ein Suchbegriff erforderlich")
        print_usage()
        sys.exit(1)
    
    return queries, count

def main():
    queries, count = parse_args()
    
    print("=" * 70)
    print(f"Mora02 - Pexels Batch Image Downloader")
    print("=" * 70)
    print()
    
    Path(BASE_DIR).mkdir(parents=True, exist_ok=True)
    timestamp = create_timestamp()
    
    # Verzeichnis benennung: mit/ohne _multi suffix
    if count == 1:
        archive_dir = Path(BASE_DIR) / f"{timestamp}_pexels"
    else:
        archive_dir = Path(BASE_DIR) / f"{timestamp}_pexels_multi_{count}"
    
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Archiv: {archive_dir}\n")
    print(f"📋 Modus: {count} Bild(er) pro Query\n")
    
    total_downloaded = 0
    total_failed = 0
    
    for idx, query in enumerate(queries, 1):
        print(f"[{idx}/{len(queries)}] Suche: \"{query}\"")
        
        results = search_pexels(query, count)
        
        if not results:
            print(f"   ❌ Keine Bilder gefunden\n")
            total_failed += 1
            continue
        
        # Bei mehreren Bildern: pro Query ein Unterordner
        if count > 1:
            query_dir = archive_dir / query.replace(" ", "_")[:30]
            query_dir.mkdir(parents=True, exist_ok=True)
        else:
            query_dir = archive_dir
        
        for result_idx, result in enumerate(results, 1):
            image_url = result['url']
            photo_id = result['id']
            photographer = result['photographer']
            
            ext = ".jpg"
            if ".png" in image_url: ext = ".png"
            elif ".jpeg" in image_url: ext = ".jpeg"
            
            # Benennung unterscheiden je nach count
            if count > 1:
                filename = f"{result_idx:02d}_{photo_id}{ext}"
            else:
                filename = f"{timestamp}_{photo_id}{ext}"
            
            output_path = query_dir / filename
            
            if count > 1:
                print(f"   [{result_idx}/{len(results)}] Lade (ID: {photo_id}, by {photographer})...")
            else:
                print(f"   📥 Lade herunter (ID: {photo_id}, by {photographer})...")
            
            if download_image(image_url, output_path):
                size_mb = get_file_size(output_path)
                print(f"       ✅ {filename} ({size_mb:.2f} MB)")
                total_downloaded += 1
            else:
                total_failed += 1
        
        print()
    
    print("=" * 70)
    print(f"✅ Fertig: {total_downloaded} geladen, {total_failed} fehlgeschlagen")
    print(f"📁 {archive_dir}")

if __name__ == "__main__":
    main()

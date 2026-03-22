#!/usr/bin/env python3
"""
Perplexity Date Injector
========================
Liest _perplexity_dates.txt, matcht Titel fuzzy mit .md Dateien,
und schreibt **Created:** Header in die Dateien.

Usage:
    python3 inject-perplexity-dates.py              # Ausführen
    python3 inject-perplexity-dates.py --dry-run    # Nur anzeigen
"""
import re, sys, os
from pathlib import Path
from datetime import datetime, timedelta
from difflib import SequenceMatcher

PPLX_DIR = Path("/opt/mora02/knowledge/changelog/chats/perplexity")
DATES_FILE = PPLX_DIR / "_perplexity_dates.txt"

# Deutsche Monatsnamen → Nummer
MONTHS_DE = {
    "jan": 1, "feb": 2, "mär": 3, "mar": 3, "apr": 4,
    "mai": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "okt": 10, "nov": 11, "dez": 12,
}

def parse_date(text: str) -> str:
    """Parst deutsches Datum wie '26. Jan. 2026' → '26.01.2026, 12:00:00'"""
    text = text.strip().lower()

    # "vor X Stunden/Tagen"
    m = re.match(r'vor (\d+) stunden?', text)
    if m:
        dt = datetime.now() - timedelta(hours=int(m.group(1)))
        return dt.strftime("%d.%m.%Y, %H:%M:%S")

    m = re.match(r'vor (\d+) tagen?', text)
    if m:
        dt = datetime.now() - timedelta(days=int(m.group(1)))
        return dt.strftime("%d.%m.%Y, %H:%M:%S")

    # "26. Jan. 2026" oder "9. Nov. 2025"
    m = re.match(r'(\d{1,2})\.\s*(\w{3})\.?\s*(\d{4})', text)
    if m:
        day = int(m.group(1))
        month_str = m.group(2).lower()[:3]
        year = int(m.group(3))
        month = MONTHS_DE.get(month_str)
        if month:
            return f"{day:02d}.{month:02d}.{year}, 12:00:00"

    return ""


def parse_dates_file() -> list[dict]:
    """Parst _perplexity_dates.txt → Liste von {title, preview, date}"""
    if not DATES_FILE.exists():
        print(f"FEHLER: {DATES_FILE} nicht gefunden")
        return []

    content = DATES_FILE.read_text(encoding="utf-8")
    lines = [l.rstrip() for l in content.split("\n")]

    entries = []
    i = 0
    while i < len(lines):
        # Leere Zeilen überspringen
        if not lines[i].strip():
            i += 1
            continue

        # Zeile 1: Titel (Frage)
        title = lines[i].strip()
        i += 1

        # Zeile 2: Antwort-Preview (kann mehrzeilig sein bis Datum kommt)
        preview = ""
        while i < len(lines):
            line = lines[i].strip()
            # Prüfe ob diese Zeile ein Datum ist
            if re.match(r'^\d{1,2}\.\s*\w{3}\.?\s*\d{4}$', line) or \
               re.match(r'^vor \d+', line.lower()) or \
               line.lower() == "geteilt":
                break
            preview += line + " "
            i += 1

        # "Geteilt" überspringen
        if i < len(lines) and lines[i].strip().lower() == "geteilt":
            i += 1

        # Zeile 3: Datum
        date_str = ""
        if i < len(lines):
            date_str = lines[i].strip()
            i += 1

        if title and date_str:
            parsed = parse_date(date_str)
            if parsed:
                entries.append({
                    "title": title,
                    "date_raw": date_str,
                    "date_parsed": parsed,
                })

    return entries


def normalize(text: str) -> str:
    """Normalisiert Text für Vergleich."""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:80]  # Nur erste 80 Zeichen vergleichen


def find_best_match(title: str, md_files: list[Path]) -> tuple[Path, float]:
    """Findet die beste Übereinstimmung zwischen Titel und Dateiname."""
    norm_title = normalize(title)
    best_match = None
    best_score = 0

    for mf in md_files:
        # Dateiname (ohne .md) als Vergleichsbasis
        norm_name = normalize(mf.stem)
        # Auch den ersten H1 aus der Datei vergleichen
        try:
            content = mf.read_text(encoding="utf-8")[:500]
            h1 = re.search(r'^# (.+)$', content, re.MULTILINE)
            norm_h1 = normalize(h1.group(1)) if h1 else ""
        except:
            norm_h1 = ""

        # Bestes Match: Dateiname ODER H1-Überschrift
        score_name = SequenceMatcher(None, norm_title, norm_name).ratio()
        score_h1 = SequenceMatcher(None, norm_title, norm_h1).ratio()
        score = max(score_name, score_h1)

        if score > best_score:
            best_score = score
            best_match = mf

    return best_match, best_score


def inject_date(md_file: Path, date_str: str, dry_run: bool = False) -> bool:
    """Fügt **Created:** Header in .md Datei ein."""
    content = md_file.read_text(encoding="utf-8")

    # Schon vorhanden?
    if "**Created:**" in content:
        return False

    # Nach dem Perplexity Logo-Tag einfügen, oder ganz oben
    header = f"\n**Created:** {date_str}\n"

    # Vor dem ersten "# " einfügen
    m = re.search(r'^(#\s)', content, re.MULTILINE)
    if m:
        pos = m.start()
        new_content = content[:pos] + header + "\n" + content[pos:]
    else:
        new_content = header + "\n" + content

    if not dry_run:
        md_file.write_text(new_content, encoding="utf-8")
    return True


def main():
    dry_run = "--dry-run" in sys.argv

    print("Perplexity Date Injector")
    print("=" * 50)

    # Dates parsen
    entries = parse_dates_file()
    print(f"\nDaten aus dates.txt: {len(entries)} Einträge")

    # MD-Dateien sammeln (ohne _ prefix und ohne p00X)
    md_files = [f for f in PPLX_DIR.glob("*.md")
                if not f.name.startswith("_")]
    print(f"MD-Dateien: {len(md_files)}")

    # Matching
    matched = 0
    unmatched_entries = []
    unmatched_files = set(f.name for f in md_files)

    for entry in entries:
        best, score = find_best_match(entry["title"], md_files)

        if score >= 0.45:  # Threshold für Fuzzy-Match
            action = "[DRY]" if dry_run else ""
            injected = inject_date(best, entry["date_parsed"], dry_run)

            status = "✅ NEU" if injected else "⏭️ SKIP (schon drin)"
            print(f"\n  {status} {action} [{score:.0%}]")
            print(f"    Titel: {entry['title'][:60]}")
            print(f"    Datei: {best.name[:60]}")
            print(f"    Datum: {entry['date_parsed']}")

            matched += 1
            unmatched_files.discard(best.name)
        else:
            unmatched_entries.append((entry, score, best))

    # Report
    print(f"\n{'='*50}")
    print(f"Ergebnis: {matched}/{len(entries)} gematcht")

    if unmatched_entries:
        print(f"\n⚠️ Nicht gematcht ({len(unmatched_entries)}):")
        for entry, score, best in unmatched_entries:
            print(f"  [{score:.0%}] {entry['title'][:60]}")
            print(f"         Bester Kandidat: {best.name[:60] if best else 'keiner'}")

    if unmatched_files:
        print(f"\n📄 Dateien ohne Datum ({len(unmatched_files)}):")
        for name in sorted(unmatched_files):
            print(f"  {name[:60]}")


if __name__ == "__main__":
    main()

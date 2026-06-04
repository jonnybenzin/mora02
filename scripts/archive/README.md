# archive-to — reversibles Aufraeumen ueber /opt/mora02/_archive/

Skript zur Umsetzung der Konvention aus ADR-021. Anstatt Dateien oder
Verzeichnisse zu loeschen, werden sie ins zentrale Archive verschoben —
mit Timestamp, Manifest und Rollback-Hinweis.

## Verzeichnis-Struktur

Pro Archive-Aktion ein eigenes Sub-Verzeichnis unter
`/opt/mora02/_archive/`:

```
/opt/mora02/_archive/
└── 2606041500_knowledge-api/
    ├── _MANIFEST.md          # was, wann, warum, git-HEAD, Rollback-Befehl
    └── apps/knowledge-api/   # Inhalt wie er war, Original-Pfad-Struktur
        ├── Dockerfile
        └── knowledge-api.py
```

Der Verzeichnis-Name folgt dem Pattern `<YYMMDDHHMM>_<topic-slug>`
analog zum xray-Output.

## Aufrufe

```bash
# Einzelnen Pfad archivieren
/opt/mora02/scripts/archive/archive-to.sh apps/knowledge-api knowledge-api "aufgeloest per ADR-020"

# Source-Pfad kann absolut oder relativ sein
/opt/mora02/scripts/archive/archive-to.sh /opt/mora02/backups/pre-phase4 backups-pre-phase4

# Ohne Reason geht auch, ist aber im Manifest weniger informativ
/opt/mora02/scripts/archive/archive-to.sh learning-lab learning-lab
```

## Output

Das Skript zeigt nach Erfolg drei Zeilen: Original-Pfad, Archive-Ziel,
Manifest-Pfad. Plus den Rollback-Befehl als Copy-Paste — der gleiche
Befehl steht auch im `_MANIFEST.md`.

## Rollback

Aus dem Manifest heraus:

```bash
cp -r /opt/mora02/_archive/<TS>_<topic>/<original-pfad> /opt/mora02/<original-pfad>
```

Original-Pfad und exakter Befehl stehen im `_MANIFEST.md` der jeweiligen
Archive-Aktion. Nach dem Restore kann das Archive-Verzeichnis dann ein
zweites Mal in ein neues Sub-Verzeichnis archiviert werden, falls man
den Eintrag aufraeumen will.

## Sicherheits-Pruefungen

- Source-Pfad muss existieren
- Source-Pfad muss unter `/opt/mora02/` liegen (kein System-Pfad)
- Source-Pfad darf nicht schon im Archive liegen (kein Rekursions-Risiko)
- topic-slug muss kebab-case sein (lowercase, hyphens, underscores)
- Ziel-Verzeichnis darf noch nicht existieren (kein Ueberschreiben)

## Borg-Backup

`_archive/` wird vom Borg-Backup mit erfasst (siehe ADR-021 und ADR-014).
Damit ist auch eine versehentliche Loeschung im Archive selbst nicht
endgueltig — die Sicherheitskette ist:
  Original-Datei → archive-to.sh → _archive/<TS>_/ → Borg-Backup

## Permissions / ACL

Das `_archive/`-Verzeichnis muss fuer beide aktiven User schreibbar sein —
jonnybenzin (Hauptbenutzer) und mora02-claude (Subagent). Wenn das
Verzeichnis durch nur einen der beiden angelegt wurde, scheitern Archive-
Aufrufe vom jeweils anderen mit „Keine Berechtigung". Einmaliger Fix:

```bash
sudo chown -R jonnybenzin:jonnybenzin /opt/mora02/_archive/
sudo setfacl -R -m u:mora02-claude:rwX /opt/mora02/_archive/
sudo setfacl -R -d -m u:mora02-claude:rwX /opt/mora02/_archive/
```

Die Default-ACL sorgt dafuer, dass kuenftige Timestamp-Sub-Verzeichnisse
das Pattern erben.

## Stolperstein: Orphan-Verzeichnis bei Permission-Fehler

Wenn `archive-to.sh` zwischen `mkdir` und `mv` an einem Permission-Problem
scheitert (Source liegt unter einem Verzeichnis ohne Schreibrechte fuer
den Aufrufer), bleibt ein leeres Archive-Topic-Verzeichnis zurueck. Per
`rmdir _archive/<TS>_<topic>/<source-prefix> && rmdir _archive/<TS>_<topic>`
aufraeumen — `rmdir` schlaegt nur fehl wenn doch was drin landete.

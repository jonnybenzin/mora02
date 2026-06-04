# atlas-drift-check

Zeigt welche Atlas-Artikel im Kompendium durch einen oder mehrere Code-Commits
moeglicherweise veraltet sind.

## Funktionsweise

Das Skript liest die `## Quellen`-Sektion jedes Atlas-Artikels unter
`/opt/mora02/kompendium/atlas/`, extrahiert die referenzierten Pfade und
vergleicht sie mit den durch `git diff` betroffenen Dateien des gewaehlten
Commits oder Commit-Range. Wenn eine geaenderte Datei auf einen Quellen-
Pfad eines Atlas-Artikels matcht (direkt oder als Unter-Pfad), wird der
Artikel als Drift-Verdacht ausgegeben.

False-Positives sind moeglich: ein Tippfehler-Fix in einer Datei loest
einen Hinweis aus, auch wenn der inhaltliche Atlas-Stand stimmt. Das
Skript ist informativ, kein blockierender Check.

## Aufrufe

```bash
# Letzter Commit (HEAD)
python3 /opt/mora02/scripts/atlas-drift/atlas-drift-check.py

# Bestimmter Commit
python3 /opt/mora02/scripts/atlas-drift/atlas-drift-check.py 6473c0d

# Commit-Range (z.B. seit main)
python3 /opt/mora02/scripts/atlas-drift/atlas-drift-check.py main..HEAD
```

## Optional: post-commit-Hook

Damit das Skript automatisch nach jedem Commit laeuft, einen post-commit-
Hook anlegen:

```bash
cat > /opt/mora02/.git/hooks/post-commit <<'EOF'
#!/bin/bash
python3 /opt/mora02/scripts/atlas-drift/atlas-drift-check.py
EOF
chmod +x /opt/mora02/.git/hooks/post-commit
```

Der Hook ist optional und nicht im Repo eingecheckt (`.git/hooks/` ist
git-intern).

## Verhaeltnis zur SCHEMA-Disziplin

Das Skript ist die automatische Ergaenzung zur Pflicht-Sektion
"Betroffene Atlas-Artikel" im ADR-Schema (`kompendium/SCHEMA.md`).
Bei Implementations-ADRs werden die betroffenen Atlas-Artikel im selben
Commit aktualisiert — der Hook ist nur Backup-Reminder fuer Commits, die
ohne ADR-Doku-Disziplin laufen.

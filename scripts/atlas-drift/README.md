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

## post-commit-Hook

Der Hook liegt als `.githooks/post-commit` im Repository und laeuft nach jedem
Commit. Er ist ein Hinweis, kein Tor: er endet immer mit 0 und kann einen
Commit weder verhindern noch rueckgaengig machen.

Damit Git ihn findet, muss `core.hooksPath` gesetzt sein — einmalig pro Klon:

```bash
git config core.hooksPath .githooks
```

**Achtung, alte Anleitung war falsch.** Frueher stand hier, den Hook nach
`.git/hooks/post-commit` zu schreiben. Weil dieses Repository `core.hooksPath`
auf `.githooks` setzt, ignoriert Git `.git/hooks/` vollstaendig — ein dort
abgelegter Hook feuert nie und meldet das auch nicht. Genau deshalb lief die
Pruefung lange gar nicht.

Pruefen, ob er greift:

```bash
git config core.hooksPath        # muss .githooks ausgeben
ls -l .githooks/post-commit      # muss ausfuehrbar sein
```

## Gewichtung: warum nicht alle Treffer gleich viel wert sind

Ein Anker wird danach gewichtet, von wie vielen Artikeln er zitiert wird.
`docker/docker-compose.yml` steht in der Quellen-Sektion von sieben Artikeln —
ein Treffer darauf sagt fast nichts, weil jede Compose-Aenderung dieselben
sieben Verdaechtigen nennt. Ein Anker, den genau ein Artikel fuehrt, sagt fast
alles.

Jeder Anker zaehlt deshalb `1/n`, wobei `n` die Zahl der zitierenden Artikel
ist. Die Ausgabe ist nach der Summe sortiert; was unter einem Drittel des
Spitzenwerts liegt, erscheint nur noch als eine Zeile am Ende.

Der Unterschied ist praktisch, nicht kosmetisch. Fuer den Commit, der vier
LLM-Profile ausmusterte, nannte die ungewichtete Fassung zwoelf Artikel
alphabetisch, von denen einer wirklich veraltet war. Gewichtet steht dieser
eine oben, und die sechs Compose-Mitlaeufer stehen zusammengefasst in einer
Zeile darunter. Eine Warnung, die zwoelf Kandidaten nennt, wenn einer stimmt,
wird beim dritten Mal ueberflogen — und schuetzt dann nichts mehr.

## Verhaeltnis zur SCHEMA-Disziplin

Das Skript ist die automatische Ergaenzung zur Pflicht-Sektion
"Betroffene Atlas-Artikel" im ADR-Schema (`kompendium/SCHEMA.md`).
Bei Implementations-ADRs werden die betroffenen Atlas-Artikel im selben
Commit aktualisiert — der Hook ist nur Backup-Reminder fuer Commits, die
ohne ADR-Doku-Disziplin laufen.

Wer einen Artikel anfasst, zieht `last_updated` im Frontmatter mit. Das
Kompendium ist gitignored, ein Hook kann das also nicht pruefen; die Ausgabe
des Skripts erinnert daran.

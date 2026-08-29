# Testplan — Vokabular, Flows und Builder auf Herz und Nieren

**Angelegt:** 2026-08-28 · **Ziel:** vor dem Meilenstein „Rapid Automation" belegen, dass jede der 38 Vokabeln, der Builder, die Gates und der Teillauf das tun, was draufsteht — und dass Fehler bis zum Menschen durchkommen.

**Grundregel aus dem 26. August:** Ein Flow aus zwei Schritten deckte neun Fehler in fünf Schichten auf. Sechs davon waren *verschwiegenes* Fehlverhalten, nicht Fehlverhalten. Die Leitfrage bei jedem Test lautet deshalb nicht nur „läuft es", sondern **„und wenn es schiefgeht, sehe ich das?"**

---

## Schritt 0 — Commit (blockierend)

59 Dateien liegen unversioniert im Arbeitsbaum, `HEAD` steht auf `4ac1a22` — zwei volle Arbeitstage. Der Commit-Versuch vom 26. August scheiterte ohne erkennbare Ursache: nichts gestaged, kein Fehler sichtbar. Verdächtig ist der `pre-commit`-Hook (Credential-Scan).

**Diesmal die Ausgabe des Commit-Laufs wirklich lesen**, statt aus dem Endzustand zu schließen. Erst danach testen — sonst kostet ein Fehlschlag beim Aufräumen zwei Tage Arbeit.

## Wie getestet wird

Drei Wege, je nach Frage:

| Weg | wofür |
|---|---|
| `POST /pipeline/step/{op}` | eine Vokabel isoliert, ohne Pipeline drumherum |
| `POST /pipeline/run-spec` mit Inline-Spec | Ketten, Gates, Referenzen |
| Flow-Builder im Pilot | Bedienung, Speichern, Palette, Anzeige |

Skript-Muster liegen unter `/tmp/mora02-claude/test_*.py`; Playwright läuft direkt, kein MCP nötig. **Offene Frage:** ob die Testskripte dauerhaft ins Repo gehören — nach dem Klon-Test ja, sie sind maschinenunabhängig.

---

## Phase 1 — Durchreiche-Test (billig, höchste Trefferquote)

Genau hier saßen fast alle Fehler vom 26. August. **Eine** kanonische Nutzlast durch **jede** Vokabel schicken, die Werte weiterreicht:

```
Zeile eins mit Umlauten: äöüß und „typografischen Anführungszeichen".

Ein zweiter Absatz nach einer Leerzeile — prüft, ob Absätze überleben.
Emoji: 🐰 · Sonderzeichen: & < > % # ? = + /
Eine sehr lange Zeile ohne Umbruch: (300+ Zeichen wiederholen)
```

Zu prüfen pro Durchreicher: **alle** Zeilen kommen an (nicht nur `inputs[0]`), Leerzeilen überleben, keine stille Kappung, Sonderzeichen unverändert.

Betroffene Vokabeln: `notify`, `notify.image`, `llm.switch`, `publish.linkedin`, `text.overlay`, `tts.speak`, alle `llm.*`, `cloud.complete`, `db.insert`/`db.update`.

## Phase 2 — Fehlerpfade

Pro Fall die eigentliche Frage: **kommt die Meldung bis zum Menschen** — in RUNS, in der FLOWS-Meldung, in der Inbox?

- unbekannte Vokabel im Spec
- fehlender Pflichtparameter
- Dienst nicht erreichbar (ComfyUI aus, llama-server aus)
- leere LLM-Antwort
- Asset-Ref, die ins Nichts zeigt
- `image.edit` auf eine Text-Referenz statt auf ein Bild
- Fan-in mit einer ID, die es nicht gibt

## Phase 3 — Verkabelung und Referenzen

- Flow, in dem Schritt 8 auf Schritt 1 zeigt, mit gemischten Typen (Run-Bucket)
- Fan-in über drei Schritte, Reihenfolge muss der Liste folgen
- `{"from": "<gate>.feedback"}` — die gepunktete Referenz auf eine Gate-Antwort *(neu seit 2026-08-28)*
- **Landmine:** ein Flow mit parallelen Zweigen **ohne** ausdrückliches `in:`. Heute reiht sich alles zu einer Kette auf und liefert stillschweigend Unsinn. Punkt 1b (Vorgabe beim Speichern materialisieren) ist dafür die Reparatur und noch offen.

## Phase 4 — Gates

Position durchspielen: erster Schritt, mittendrin, letzter Schritt, zwei hintereinander. Dazu Freigabe gegen Review, Resume und Non-Blocking-Resume, Ablehnung, Abbruch.

Neu seit dem 28. August und ungetestet:
- landet je Entscheidung ein `gate_decision` im Lauf-Protokoll?
- steht die Antwort danach im Run-Bucket unter der Gate-ID *und* unter `<gate>.<feld>`?
- **stimmt die Zuordnung bei mehreren Gates?** Die n-te Entscheidung soll das n-te Gate beantworten — das ist die Annahme mit dem größten Restrisiko im ganzen Teillauf-Bau.

## Phase 5 — Teillauf *(komplett neu, nur teilweise erprobt)*

- `rerun-plan` gegen einen echten Lauf: stimmen `redo`/`reuse`/`gates_needed`?
- Teillauf mit `overrides` — greift der geänderte Wert?
- Teillauf mit **abweichender Spec** (Schritt eingefügt, Verkabelung geändert)
- Wachhund: Teillauf über ein Gate, dessen Entscheidung eine **Ablehnung** war → muss abgewiesen werden
- Teillauf gegen einen Lauf **ohne aufgezeichnete Spec** (alle Läufe vor dem 28.8.) → sauberer 409
- Platzhalter hinter einem noch offenen Gate: bei „Nein" darf er nicht feuern

## Phase 6 — Builder-UI

Speichern, Überschreiben, Löschen · Namenskollisionen · Slug-Grenzfälle (Umlaute, überlange Namen) · Einfügen an jeder Marke, nicht nur am Ende · ID-Entdopplung · Typ-Filterung mitten im Stack · Gates in der Palette · Freigabe-Text editierbar · Meldungen überleben ein Neu-Rendern (der DOM-Fehler vom 26.8.)

## Phase 7 — Jede Vokabel einmal in einer Kette

Gestaffelt nach Kosten, billig zuerst:

| Stufe | Vokabeln |
|---|---|
| **1 — gratis, schnell** | `llm.*` (7), `db.*` (6), `source.file`, `web.fetch`, `web.search`, `stock.search`, `stock.download` |
| **2 — lokal, GPU** | `image.generate` (sd15/photo/concept/epic/flux), `image.cutout`, `image.erase`, `image.upscale`, `image.expand`, `image.facefix`, `text.overlay`, `pixeltext.render`, `gif.create` |
| **3 — kostet Geld** | `image.generate` (nanban, nanban-pro, flux-ultra), `image.edit`, `cloud.complete`, `cloud.vision` |
| **4 — teuer in Zeit** | `video.generate` (3 Modi), `video.last_frame`, `music.generate`, `tts.speak`, `clip.generate` |
| **5 — Außenwirkung** | `notify`, `notify.image` (Signal), `publish.linkedin` — zuletzt, mit Bedacht |

## Phase 8 — Skurrile Kombinationen

Ausdrücklich gewünscht. Kandidaten:

- Typ-Missbrauch: Bild in eine Text-Vokabel, Video in `image.upscale`
- Kette aus zehn Schritten mit Gate an Position 1 **und** 10
- `llm.switch` mitten in einer Kette — und was danach mit den Folge-Schritten passiert
- `gif.create` mit einem einzigen Bild · `clip.generate` mit gemischten Bild- und Video-Refs
- Fan-in aus Schritten **hinter** einem Gate mit einem Schritt **davor**
- `image.erase` auf ein Bild ohne erkennbares Motiv
- leerer Prompt, Prompt mit 5000 Zeichen, `batch_size` groß
- zwei Flows gleichzeitig starten (Run-Bucket, GPU-Konkurrenz)

---

## Bekannte Baustellen — mitprüfen oder mitfixen

- **Upscale-Zweig in `photo`/`concept`/`epic` defekt:** `VAEDecode` erwartet 16 Kanäle (Flux), bekommt 4 (SDXL). Betrifft nur die UI-Schalter, nicht die Pipelines.
- **`in:`-Vorgabe implizit** (Punkt 1b) — siehe Phase 3.
- **`image.facefix`** steht im Container noch auf `planned`; ein Bau fehlt.
- **`entrypoint.sh`-Klon-Liste** noch nicht eingetragen (`/tmp/mora02-claude/patch-entrypoint.py`).
- **Aufbewahrung der Run-Buckets** ungeregelt — Teilläufe hängen daran.

## Danach: das Ganze lokalisieren

Erklärtes Ziel: was heute ein Cloud-Modell an Flows zusammenbaut, soll lokal entstehen. Der Testdurchgang liefert dafür das Material — jeder Flow, den wir hier von Hand schreiben, ist zugleich ein Beispiel für den späteren lokalen Autor. Vorgehen und Kostenrechnung stehen in der Notiz *Flow-Authoring aus natürlicher Sprache*: Vokabelliste plus Beispiele plus Validierungsschleife, dann Grammatik-Zwang, dann Schritt-für-Schritt mit Typ-Filterung.

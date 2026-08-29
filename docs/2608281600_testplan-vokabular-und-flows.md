# Testplan — Vokabular, Flows und Builder auf Herz und Nieren

**Angelegt:** 2026-08-28 · **Ziel:** vor dem Meilenstein „Rapid Automation" belegen, dass jede der 38 Vokabeln, der Builder, die Gates und der Teillauf das tun, was draufsteht — und dass Fehler bis zum Menschen durchkommen.

**Grundregel aus dem 26. August:** Ein Flow aus zwei Schritten deckte neun Fehler in fünf Schichten auf. Sechs davon waren *verschwiegenes* Fehlverhalten, nicht Fehlverhalten. Die Leitfrage bei jedem Test lautet deshalb nicht nur „läuft es", sondern **„und wenn es schiefgeht, sehe ich das?"**

---

## Stand: durchgeführt am 2026-08-29

Alle acht Phasen abgearbeitet. **158 Prüfungen in zehn Suiten**, aus denen vierzehn Reparaturen hervorgingen. Der Plan bleibt unten stehen, wie er am 28. August geschrieben wurde — was dabei herauskam, steht hier:

| Phase | Suite | Ergebnis | Was sie fand |
|---|---|---|---|
| 1 Durchreichen | `test_passthrough.py` | 28 | Lauf-Protokoll kappte stumm bei 200 Zeichen; `publish.linkedin` versprach im Vokabular weniger, als es kann; `stock.download` las seine deklarierte Eingabe nie |
| 2 Fehlerpfade | `test_errorpaths.py` | 25 | Verkabelungsfehler hinterließen **keine Spur** im Protokoll; die Kappungs-Warnung war gebaut, aber nie an die Ansicht angeschlossen |
| 3 Verkabelung | `test_wiring.py` | 5 | die Landmine: ein Schritt ohne `in:` schluckt still die Ausgabe des Vorgängers |
| 4 Gates | `test_gates.py` | 8 | ein Gate mit eigenem Schema übersprang **alles dahinter** und meldete `ok` |
| 5 Teillauf | `test_rerun.py` | 9 | keine echten Fehler — die riskanteste Annahme (n-te Entscheidung ↔ n-tes Gate) hält |
| 6a Bibliothek | `test_library.py` | 16 | ein Flow mit Verweis nach vorn wurde anstandslos gespeichert |
| 6b Builder | `test_builder_ui.py` | 9 | keine Fehler — der DOM-Fehler vom 26.8. ist wirklich behoben |
| 7 Vokabular | `test_vocabulary.py` | 32/38 Ops | der ganze `cloud`-Zweig war tot (`temperature` an ein SDK, das ihn nicht mehr kennt) |
| 8 Grenzfälle | `test_edgecases.py` | 6 | **keine Typprüfung auf den Leitungen** — ein Bild lief durch eine Text-Vokabel |
| (quer) | `test_truncation.py` | 14 | jede Kappung im System klassifiziert und begründet |

Die Suiten liegen unter `tests/pipeline/` und laufen gegen den **laufenden Stack** — sie sind keine Unit-Tests. Ein Befehl startet die billigen:

```
bash tests/pipeline/run-all.sh            # acht Suiten, gratis, wenige Minuten
bash tests/pipeline/run-all.sh --ui       # plus die Browser-Suite (Playwright)
bash tests/pipeline/run-all.sh --vocab 1  # plus jede Vokabel einzeln, Stufe 1
```

Ab Vokabel-Stufe 2 kostet es GPU-Minuten, ab Stufe 3 Geld, ab Stufe 5 verlässt es das Haus (Signal, LinkedIn). Nichts davon läuft, ohne dass die Stufe ausdrücklich genannt wird.

**Die Fehlerklasse, die den Tag bestimmt hat:** Von den vierzehn Reparaturen betrafen neun nicht Fehlverhalten, sondern **verschwiegenes** Fehlverhalten — ein Lauf-Protokoll, das stumm bei 200 Zeichen kappt; ein Gate, das alles dahinter überspringt und `ok` meldet; eine Kappungs-Warnung, die gebaut, aber nie angeschlossen war; eine Vokabel, die eine Eingabe verspricht, die sie nie liest. Die Leitfrage des Plans hat sich damit selbst bestätigt.

**Drei Befunde hielten der Nachprüfung nicht stand** und wurden zurückgenommen, bevor jemand sie reparierte: die Gate-Zuordnung ist korrekt, der `approve`-Rückfall der Inbox ist aus einem Spec gar nicht erreichbar, und `gates_needed` bedeutet etwas anderes als sein Name nahelegt (geerbte Entscheidungen, nicht bevorstehende Rückfragen). Ohne diese Rücknahmen wären drei Reparaturen an funktionierenden Dingen entstanden.

**Was keine Suite je zusichern kann:** die Zustellung selbst. Der schwerste Fund des Tages — Signal-Bildunterschriften kamen auf ihr erstes Zeichen gekürzt an — war nur sichtbar, weil ein Mensch aufs Handy geschaut und einen Screenshot geschickt hat. Alle Ebenen innerhalb unserer Reichweite meldeten korrekt „versendet".

## Schritt 0 — Commit (blockierend) · ERLEDIGT

Commit `10a81b3` (58 Dateien) am 29.8. Die Ursache des Fehlschlags vom 26. August blieb ungeklärt, aber ein verwandtes Phänomen trat am 29.8. erneut auf und ist geklärt: Beim zweistufigen Commit-Script lief nur der `check`-Schritt, dessen Schlusssatz („nothing committed yet") unter dreißig Zeilen Torwächter-Ausgabe stand. Eine ganze Phase lag deshalb eine Stunde gestaged im Baum. **Hinweise, zu denen man scrollen muss, werden übersehen** — auch das eine Form von Schweigen.

## Wie getestet wird

Drei Wege, je nach Frage:

| Weg | wofür |
|---|---|
| `POST /pipeline/step/{op}` | eine Vokabel isoliert, ohne Pipeline drumherum |
| `POST /pipeline/run-spec` mit Inline-Spec | Ketten, Gates, Referenzen |
| Flow-Builder im Pilot | Bedienung, Speichern, Palette, Anzeige |

**Beantwortet:** Die Testskripte gehören ins Repo (`tests/pipeline/`) — die Vorgänger-Muster unter `/tmp` hatte ein Neustart gefressen, bevor sie ein zweites Mal gebraucht wurden. Playwright läuft direkt, kein MCP nötig.

**Zwei Messinstrumente**, die sich bewährt haben und beim Weiterbauen Zeit sparen:
- `llm.classify` mit **einem einzigen Etikett** kann nur eine Antwort geben — ein freier lokaler Modellaufruf wird damit zum deterministischen Wertgeber. Vorsicht: unzuverlässig, sobald der eingehende Text selbst ein Etikett ist; dann echot das Modell die Eingabe.
- Ein Schritt, der eine Eingabe **sofort ablehnt** (z. B. `image.edit` auf Text), protokolliert trotzdem, was er bekommen hat — eine Sonde ohne GPU, ohne Kosten, ohne Nebenwirkung.

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
- **`in:`-Vorgabe implizit** (Punkt 1b) — **erledigt.** `materialize_wiring()` schreibt die Leitung beim Speichern *und* beim Starten ins Spec; die Vorgabe bleibt erlaubt, sie wird nur nicht mehr verschwiegen.
- **`image.facefix`** — **war längst gebaut.** Die Doku hing hinterher und stand auf `planned`; die Vokabel läuft (6 s in Stufe 2). Es gibt inzwischen **keine** `planned`-Vokabel mehr, weshalb die Compile-Sperre gegen ungebaute Vokabeln zurzeit nicht ausgelöst werden kann.
- **`entrypoint.sh`-Klon-Liste** — offen; das Patch-Skript lag unter `/tmp` und ist einem Neustart zum Opfer gefallen.
- **Aufbewahrung der Run-Buckets** ungeregelt — offen, Teilläufe hängen daran.

## Offen nach dem Durchgang vom 29.8.

- **37 von 38 Vokabeln belegt.** Offen bleibt allein `stock.download`: aus einer Kette nicht erreichbar, bis die Feld-Pick-Vokabel existiert. `stock.search` liefert eine Trefferliste, der Download will zwei Einzelwerte daraus — das Herausgreifen eines Feldes ist die fehlende Vokabel, und sie fehlt an derselben Stelle noch zweimal (Scheduled-Publish, und der `db.*`-Zyklus, der deshalb keine Kette sein kann).
- **Nachgeholt am 29.8.:** `llm.switch` läuft als eigene Stufe 6 (rund eine Minute je Wechsel, schaltet zurück und prüft das), die vier schreibenden `db.*` als Zyklus anlegen→lesen→ändern→löschen gegen eine Wegwerf-Tabelle. Deren ID kommt aus `MORA02_TEST_TABLE` — ein Wert, der nur auf dieser Maschine gilt und deshalb nicht im Repo steht.
- **Keine Typprüfung war der größte Einzelfund** und ist repariert (`check_wire_types`), aber sie prüft nur die stdin-Leitung. Parameter-Verweise `{"from": …}` tragen ihre eigenen Typen und bleiben ungeprüft.
- **„Dienst nicht erreichbar" im engeren Sinn** — ComfyUI oder llama-server tatsächlich abschalten. Die Ersatzprüfung (toter Port, unauflösbarer Name) ist grün, prüft aber keine Zeitüberschreitungen.
- **`cloud.vision`** hat noch eine feste Grenze von 1024 Token.
- **Signal-Bildunterschriften** werden auf ihr erstes Zeichen gekürzt (Fehler außerhalb dieses Repos, in OpenClaw). Umgangen: Bild und Worte reisen als zwei Nachrichten, das Bild trägt ein Zero-Width-Space als eigene Unterschrift. Zurückschalten mit `MORA02_NOTIFY_MEDIA_CAPTION=inline`, sobald das Gateway Unterschriften trägt.
- **Modell-Liste veraltet** (`claude-sonnet-4-5`, `claude-opus-4-6`, `claude-haiku-4-5`) und die SDK-Stände von Pilot und Script-Runner driften auseinander — Thema für das halbjährliche Modell-Review, nicht für einen Testdurchgang.

## Danach: das Ganze lokalisieren

Erklärtes Ziel: was heute ein Cloud-Modell an Flows zusammenbaut, soll lokal entstehen. Der Testdurchgang liefert dafür das Material — jeder Flow, den wir hier von Hand schreiben, ist zugleich ein Beispiel für den späteren lokalen Autor. Vorgehen und Kostenrechnung stehen in der Notiz *Flow-Authoring aus natürlicher Sprache*: Vokabelliste plus Beispiele plus Validierungsschleife, dann Grammatik-Zwang, dann Schritt-für-Schritt mit Typ-Filterung.

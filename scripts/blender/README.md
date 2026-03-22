# MORA02 Blender Logo Animator

**Script:** `mora02_allinone.py`
**Stand:** 2026-02-15
**Blender:** 5.0+ (Snap)

---

## Was ist das?

Ein Blender-Script das das MORA02 Pixel-Logo aus 93 Würfeln generiert und animiert. Alles über ein N-Panel steuerbar, kein manuelles Keyframe-Setzen nötig.

## Zwei Animations-Modi

**Waves** — Kontinuierliche Effekte, einzeln ein/ausschaltbar:
- Pulse (Scale-Oszillation)
- Float (Position-Oszillation auf X/Y/Z)
- Opacity (Alpha-Oszillation)
- Camera Zoom (Focal Length)

**Factory** — Mechanische Shuffle-Animation in drei Phasen:
1. Explode: Würfel fahren gerade in alle Richtungen raus
2. Shuffle: Richtungswechsel mit 90°-Rotations-Kick, kollisionsfrei
3. Reassemble: Würfel fahren gerade an neue Plätze, Logo steht wieder

## Setup (erstmalig)

1. Blender öffnen (leere Datei)
2. Scripting Tab → Open → `mora02_allinone.py`
3. Alt+P (Script ausführen)
4. Layout Tab → N-Taste → "MORA02" Tab erscheint
5. File → Save As → `mora02_projekt.blend`

**Tipp:** `Edit → Preferences → Save & Load → Auto Run Python Scripts` aktivieren — dann startet das Script automatisch beim Öffnen der .blend Datei.

## Tägliche Nutzung

1. `mora02_projekt.blend` öffnen
2. Scripting Tab → Alt+P (falls kein Auto Run)
3. N-Taste → MORA02 Panel → Parameter einstellen
4. Space → Preview abspielen
5. RENDER Button → Timestamp-Datei in Output-Ordner

## Panel-Übersicht

| Bereich | Einstellungen |
|---------|---------------|
| Mode | Waves / Factory Toggle |
| Animation | Duration, FPS, Theme (dark/light) |
| Waves | Ease In/Out, Pulse, Float, Opacity, Zoom |
| Factory | Seed, Explode/Shuffle Dist, Moves, Phase-Aufteilung |
| Output | MP4/PNG, Pfad, Resolution |
| Render Settings | Engine (EEVEE/Cycles), Samples |

## Output

Renderings landen in `/opt/mora02/output/_default/blender/` mit automatischem Timestamp-Dateinamen:

```
2602151430_mora02_waves.mp4
2602151445_mora02_factory.mp4
```

PNG-Sequenzen landen in einem Timestamp-Unterordner.

## Technische Details

**Logo-Grid:** 5×5 Pixel pro Buchstabe, 93 Würfel total (M=17, O=17, R=18, A=19, 0=13, 2=17)

**Kamera:** Perspective, Focal Length 100mm, Z=200. Gibt den Würfeln 3D-Tiefe.

**Animation:** Kein Keyframe-System — ein Frame-Change-Handler berechnet alle Positionen/Rotationen mathematisch pro Frame. Deterministische Randomisierung über MD5-Hash (gleicher Seed = gleiche Animation).

**Factory Kollisionsvermeidung:** Vorberechnetes Grid-System. Alle Pfade werden beim "Recalculate" berechnet und auf Überschneidungen geprüft. Seed ändern = komplett neue Animation.

**Render Engine:** EEVEE (Default, schnell) oder Cycles (fotorealistisch). EEVEE reicht für einfarbige Würfel vollkommen.

## Blender-Settings neben dem Panel

Das Panel überschreibt nur seine eigenen Settings. Alle anderen Blender-Einstellungen (Motion Blur, Depth of Field, Color Management, Bloom, Materialien) können frei im normalen Blender-UI angepasst werden und bleiben erhalten.

## VRAM-Hinweis

Bei laufendem LLM (Qwen3-14B, ~15.5GB VRAM) mit niedrigerer Resolution rendern (540p). Für Final Render in 1080p: LLM vorher stoppen. EEVEE nutzt GPU über OpenGL, nicht CUDA — zeigt sich nicht in nvidia-smi.

## Seed-System (Factory)

Jeder Seed erzeugt eine einzigartige, aber reproduzierbare Animation. Gleicher Seed + gleiche Parameter = identische Animation. Zum Experimentieren einfach Seed-Zahl ändern und "Recalculate Paths" klicken.

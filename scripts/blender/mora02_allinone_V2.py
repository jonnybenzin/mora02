"""
MORA02 — Logo + Animator (All-in-One) v3
==========================================
Leere Blender-Datei → Scripting → Open → Alt+P → fertig.
Config ändern → Alt+P → neue Animation.
Space = Play | Ctrl+F12 = Render

FIX v3: Origin liegt im Zentrum des Logos (nicht links unten).

OUTPUT:
  "PNG"  → PNG-Sequenz (RGBA, transparent)
  "MP4"  → direkt MP4 (H.264)

NEUEN EFFEKT HINZUFÜGEN:
  1. Funktion: def apply_xxx(obj, t, progress, cfg): ...
  2. EFFECT_FUNCTIONS["xxx"] = apply_xxx
  3. In EFFECTS Config eintragen
"""

import bpy
import math
import hashlib


# ╔══════════════════════════════════════════════════════════════╗
# ║  CONFIG — hier alles einstellen                              ║
# ╚══════════════════════════════════════════════════════════════╝

DURATION_SEC = 5
FPS = 30
EASE_IN_PCT = 0.15         # Erste 15%: Default → Animation
EASE_OUT_PCT = 0.15        # Letzte 15%: Animation → Default

# ── Output ───────────────────────────────────────────────
RENDER_OUTPUT = "/tmp/mora02_anim_"
RENDER_FORMAT = "MP4"      # "PNG" oder "MP4"
RENDER_QUALITY = 90

# ── Theme ────────────────────────────────────────────────
THEME = "dark"             # "dark" = schwarz bg + weisse Würfel
                           # "light" = weiss bg + schwarze Würfel

# ── Kamera ───────────────────────────────────────────────
CAMERA_ZOOM = {
    "enabled": False,
    "min": 0.8,
    "max": 1.5,
    "freq": 0.3,
}

# ── Effekte ──────────────────────────────────────────────
EFFECTS = {

    "pulse": {
        "enabled": True,
        "min": 0.5,
        "max": 1.5,
        "wave": "sin",
        "freq_range": (0.4, 1.2),
    },

    "float": {
        "enabled": True,
        "wave": "sin",
        "freq_range": (0.2, 0.8),
        "amplitude": {
            "x": 0.3,
            "y": 0.3,
            "z": 0.5,
        },
        "per_axis_freq": True,
    },

    "opacity": {
        "enabled": False,
        "min": 0.3,
        "max": 1.0,
        "wave": "sin",
        "freq_range": (0.3, 0.9),
    },
}


# ╔══════════════════════════════════════════════════════════════╗
# ║  AB HIER NICHTS ÄNDERN (außer neue Effekte)                 ║
# ╚══════════════════════════════════════════════════════════════╝


# ============================================================
# CLEANUP
# ============================================================
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for mesh in bpy.data.meshes:
    bpy.data.meshes.remove(mesh)
for mat in bpy.data.materials:
    bpy.data.materials.remove(mat)
for col in list(bpy.data.collections):
    if col.name != "Scene Collection":
        bpy.data.collections.remove(col)

# Alte Handler entfernen
bpy.app.handlers.frame_change_post[:] = [
    h for h in bpy.app.handlers.frame_change_post
    if getattr(h, '__name__', '') != 'mora02_frame_handler'
]


# ============================================================
# 5x5 PIXEL GRIDS (top→bottom, '#'=cube, '.'=empty)
# ============================================================

M_grid = [
    "#...#",
    "##.##",
    "#.#.#",
    "#...#",
    "#...#",
]

O_grid = [
    ".###.",
    "#...#",
    "#...#",
    "#...#",
    ".###.",
]

R_grid = [
    "####.",
    "#...#",
    "####.",
    "#.#..",
    "#..#.",
]

A_grid = [
    ".###.",
    "#...#",
    "#####",
    "#...#",
    "#...#",
]

Zero_grid = [
    ".###.",
    "#...#",
    "#...#",
    "#...#",
    ".###.",
]

Two_grid = [
    "#####",
    "....#",
    "#####",
    "#....",
    "#####",
]


# ============================================================
# LAYOUT
# ============================================================
letter_defs = [
    ("M", M_grid),
    ("O", O_grid),
    ("R", R_grid),
    ("A", A_grid),
    ("Z", Zero_grid),   # Z = Zero
    ("T", Two_grid),    # T = Two
]

layout = []
x_cursor = 0
for prefix, grid in letter_defs:
    width = len(grid[0])
    layout.append((prefix, grid, x_cursor, width))
    x_cursor += width + 1  # +1 gap

total_width = x_cursor - 1  # Letzte Lücke abziehen
grid_height = 5


# ============================================================
# HELPERS
# ============================================================
def grid_to_pixels(grid):
    """Grid-Zeilen (top→bottom) in (x, y) Koordinaten (y=0 unten)."""
    height = len(grid)
    pixels = []
    for row_idx, row_str in enumerate(grid):
        y = height - 1 - row_idx
        for col_idx, char in enumerate(row_str):
            if char == '#':
                pixels.append((col_idx, y))
    pixels.sort(key=lambda p: (p[0], p[1]))
    return pixels


# ============================================================
# THEME + MATERIALS
# ============================================================
if THEME == "dark":
    cube_color = (0.95, 0.95, 0.95, 1.0)
    bg_color = (0.02, 0.02, 0.02, 1.0)
else:
    cube_color = (0.02, 0.02, 0.02, 1.0)
    bg_color = (0.95, 0.95, 0.95, 1.0)

# World Background
world = bpy.context.scene.world
if not world:
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
world.use_nodes = True
bg_node = world.node_tree.nodes.get("Background")
if bg_node:
    bg_node.inputs["Color"].default_value = bg_color
    bg_node.inputs["Strength"].default_value = 1.0

# Pro-Würfel Materialien (für Opacity-Effekt)
cube_materials = {}


# ============================================================
# WÜRFEL ERSTELLEN
# ============================================================

# ── Zentrum berechnen ────────────────────────────────────
# Origin soll im Mittelpunkt des gesamten Logos liegen
center_x = total_width / 2.0
center_y = grid_height / 2.0
center_z = 0.5  # Halbe Würfelhöhe

# Collections
logo_collection = bpy.data.collections.new("MORA02_Logo")
bpy.context.scene.collection.children.link(logo_collection)

all_cubes = []
cube_count = 0

for prefix, grid, x_offset, width in layout:
    letter_col = bpy.data.collections.new(f"Letter_{prefix}")
    logo_collection.children.link(letter_col)

    pixels = grid_to_pixels(grid)

    for idx, (px, py) in enumerate(pixels, start=1):
        name = f"{prefix}{idx}"

        # World-Position (zentriert!)
        wx = x_offset + px + 0.5 - center_x
        wy = py + 0.5 - center_y
        wz = 0.5 - center_z  # = 0.0

        # Mesh erstellen
        bpy.ops.mesh.primitive_cube_add(size=1, location=(wx, wy, wz))
        obj = bpy.context.active_object
        obj.name = name
        obj.data.name = f"Mesh_{name}"

        # Material (eigenes pro Würfel für Opacity)
        mat = bpy.data.materials.new(name=f"Mat_{name}")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = cube_color
        bsdf.inputs["Roughness"].default_value = 0.3
        bsdf.inputs["Metallic"].default_value = 0.1
        bsdf.inputs["Alpha"].default_value = 1.0
        mat.blend_method = 'HASHED'  # Für Alpha-Transparenz
        obj.data.materials.append(mat)
        cube_materials[name] = mat

        # Custom Properties für Animation
        obj["letter"] = prefix
        obj["grid_x"] = px
        obj["grid_y"] = py
        obj["home_x"] = wx
        obj["home_y"] = wy
        obj["home_z"] = wz

        # In Letter-Collection verschieben
        for col in obj.users_collection:
            col.objects.unlink(obj)
        letter_col.objects.link(obj)

        all_cubes.append(obj)
        cube_count += 1


# ============================================================
# KAMERA (ortho, top-down, zentriert auf 0,0,0)
# ============================================================
bpy.ops.object.camera_add(location=(0, 0, 20), rotation=(0, 0, 0))
camera = bpy.context.active_object
camera.name = "MORA02_Camera"
camera.data.type = 'ORTHO'
camera.data.ortho_scale = total_width + 4  # Etwas Padding
bpy.context.scene.camera = camera

base_ortho = camera.data.ortho_scale

# Licht
bpy.ops.object.light_add(type='SUN', location=(0, 0, 15))
light = bpy.context.active_object
light.name = "MORA02_Sun"
light.data.energy = 3.0


# ============================================================
# WAVE FUNCTIONS
# ============================================================
def wave_sin(t, freq, phase):
    return math.sin(2 * math.pi * freq * t + phase)

def wave_cos(t, freq, phase):
    return math.cos(2 * math.pi * freq * t + phase)

def wave_triangle(t, freq, phase):
    x = (t * freq + phase / (2 * math.pi)) % 1.0
    return 4 * abs(x - 0.5) - 1.0

WAVE_FUNCS = {
    "sin": wave_sin,
    "cos": wave_cos,
    "triangle": wave_triangle,
}


# ============================================================
# SEED / RANDOMNESS (deterministisch pro Würfel)
# ============================================================
def obj_seed(name, salt=""):
    h = hashlib.md5(f"{name}_{salt}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF

def obj_rand_range(name, salt, lo, hi):
    return lo + obj_seed(name, salt) * (hi - lo)


# ============================================================
# EASING
# ============================================================
def ease_multiplier(progress):
    """0→1 ease in, 1 sustain, 1→0 ease out."""
    if progress < EASE_IN_PCT:
        t = progress / EASE_IN_PCT
        return t * t * (3 - 2 * t)  # smoothstep
    elif progress > (1.0 - EASE_OUT_PCT):
        t = (1.0 - progress) / EASE_OUT_PCT
        return t * t * (3 - 2 * t)
    else:
        return 1.0


# ============================================================
# EFFECT: PULSE (Scale)
# ============================================================
def apply_pulse(obj, t, progress, cfg):
    ease = ease_multiplier(progress)
    wave_fn = WAVE_FUNCS[cfg["wave"]]
    name = obj.name

    freq = obj_rand_range(name, "pulse_f", *cfg["freq_range"])
    phase = obj_seed(name, "pulse_p") * 2 * math.pi
    w = wave_fn(t, freq, phase)

    lo, hi = cfg["min"], cfg["max"]
    mid = (lo + hi) / 2
    amp = (hi - lo) / 2
    raw = mid + w * amp

    scale_val = raw * ease + 1.0 * (1.0 - ease)
    obj.scale = (scale_val, scale_val, scale_val)


# ============================================================
# EFFECT: FLOAT (Position offset)
# ============================================================
def apply_float(obj, t, progress, cfg):
    ease = ease_multiplier(progress)
    wave_fn = WAVE_FUNCS[cfg["wave"]]
    name = obj.name
    amp = cfg["amplitude"]

    home_x = obj.get("home_x", obj.location.x)
    home_y = obj.get("home_y", obj.location.y)
    home_z = obj.get("home_z", obj.location.z)

    if cfg.get("per_axis_freq"):
        fx = obj_rand_range(name, "fl_fx", *cfg["freq_range"])
        fy = obj_rand_range(name, "fl_fy", *cfg["freq_range"])
        fz = obj_rand_range(name, "fl_fz", *cfg["freq_range"])
    else:
        fx = fy = fz = obj_rand_range(name, "fl_f", *cfg["freq_range"])

    px = obj_seed(name, "fl_px") * 2 * math.pi
    py = obj_seed(name, "fl_py") * 2 * math.pi
    pz = obj_seed(name, "fl_pz") * 2 * math.pi

    dx = wave_fn(t, fx, px) * amp["x"] * ease
    dy = wave_fn(t, fy, py) * amp["y"] * ease
    dz = wave_fn(t, fz, pz) * amp["z"] * ease

    obj.location = (home_x + dx, home_y + dy, home_z + dz)


# ============================================================
# EFFECT: OPACITY (Alpha)
# ============================================================
def apply_opacity(obj, t, progress, cfg):
    ease = ease_multiplier(progress)
    wave_fn = WAVE_FUNCS[cfg["wave"]]
    name = obj.name

    freq = obj_rand_range(name, "opa_f", *cfg["freq_range"])
    phase = obj_seed(name, "opa_p") * 2 * math.pi
    w = wave_fn(t, freq, phase)

    lo, hi = cfg["min"], cfg["max"]
    mid = (lo + hi) / 2
    amp = (hi - lo) / 2
    raw = mid + w * amp

    alpha_val = raw * ease + 1.0 * (1.0 - ease)
    alpha_val = max(0.0, min(1.0, alpha_val))

    mat = cube_materials.get(name)
    if mat and mat.use_nodes:
        mat.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = alpha_val


# ============================================================
# EFFECT REGISTRY
# ============================================================
EFFECT_FUNCTIONS = {
    "pulse": apply_pulse,
    "float": apply_float,
    "opacity": apply_opacity,
}


# ============================================================
# FRAME CHANGE HANDLER
# ============================================================
def mora02_frame_handler(scene):
    frame = scene.frame_current
    total_frames = DURATION_SEC * FPS
    t = frame / FPS
    progress = min(frame / total_frames, 1.0) if total_frames > 0 else 1.0

    # Kamera Zoom
    if CAMERA_ZOOM["enabled"]:
        cam_obj = scene.camera
        if cam_obj:
            if progress >= 1.0:
                cam_obj.data.ortho_scale = base_ortho
            else:
                ease = ease_multiplier(progress)
                lo, hi = CAMERA_ZOOM["min"], CAMERA_ZOOM["max"]
                mid = (lo + hi) / 2
                amp = (hi - lo) / 2
                w = math.sin(2 * math.pi * CAMERA_ZOOM["freq"] * t)
                raw = mid + w * amp
                zoom = raw * ease + 1.0 * (1.0 - ease)
                cam_obj.data.ortho_scale = base_ortho * zoom

    # Würfel animieren
    logo_col = bpy.data.collections.get("MORA02_Logo")
    if not logo_col:
        return

    objects = []
    for child_col in logo_col.children:
        objects.extend(child_col.objects)

    for obj in objects:
        if obj.type != 'MESH':
            continue

        # Letzter Frame: alles auf Default zurücksetzen
        if progress >= 1.0:
            obj.scale = (1, 1, 1)
            obj.location = (
                obj.get("home_x", obj.location.x),
                obj.get("home_y", obj.location.y),
                obj.get("home_z", obj.location.z),
            )
            mat = cube_materials.get(obj.name)
            if mat and mat.use_nodes:
                mat.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = 1.0
            continue

        # Effekte anwenden
        for effect_name, cfg in EFFECTS.items():
            if not cfg.get("enabled"):
                continue
            fn = EFFECT_FUNCTIONS.get(effect_name)
            if fn:
                fn(obj, t, progress, cfg)


# Handler registrieren
bpy.app.handlers.frame_change_post.append(mora02_frame_handler)


# ============================================================
# TIMELINE + RENDER SETTINGS
# ============================================================
scene = bpy.context.scene
scene.frame_start = 0
scene.frame_end = DURATION_SEC * FPS
scene.render.fps = FPS
scene.render.filepath = RENDER_OUTPUT
scene.render.resolution_x = 1080
scene.render.resolution_y = 1080

if RENDER_FORMAT == "MP4":
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'MEDIUM'
    scene.render.ffmpeg.ffmpeg_preset = 'GOOD'
else:
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

# EEVEE (schneller als Cycles für diese Szene)
scene.render.engine = 'BLENDER_EEVEE'
scene.frame_set(0)


# ============================================================
# REPORT
# ============================================================
print("\n" + "=" * 50)
print("MORA02 ALL-IN-ONE v3 (zentrierter Origin)")
print("=" * 50)

# ASCII Preview
for row in range(5):
    line = "  "
    for _, grid, _, _ in layout:
        line += grid[row].replace('#', '█').replace('.', ' ') + " "
    print(line)

print(f"\n  Würfel: {cube_count}")
print(f"  Grid: {total_width} x {grid_height}")
print(f"  Origin: (0, 0, 0) = Logo-Zentrum")
print(f"  Theme: {THEME}")
print(f"  Duration: {DURATION_SEC}s @ {FPS}fps")
print(f"  Effekte: {', '.join(k for k,v in EFFECTS.items() if v.get('enabled'))}")
print(f"  Render: {RENDER_FORMAT} → {RENDER_OUTPUT}")
print("=" * 50)

"""
MORA02 — Logo + Animator + Panel (Complete)
=============================================
SETUP:
  1. Leere Blender-Datei → Scripting → Open → Alt+P
  2. Layout Tab → N-Taste → "MORA02" Tab
  3. File → Save As → mora02_projekt.blend

MODI:
  "Waves"   — Pulse, Float, Opacity (kontinuierliche Effekte)
  "Factory" — Mechanisches Explode → Shuffle → Reassemble

N-Taste → MORA02 Tab → alles einstellen → RENDER
"""

import bpy
import math
import random
import hashlib
from bpy.props import (
    FloatProperty, IntProperty, BoolProperty,
    EnumProperty, PointerProperty
)
from bpy.types import Panel, Operator, PropertyGroup


# ╔══════════════════════════════════════════════════════════════╗
# ║  PIXEL GRIDS                                                ║
# ╚══════════════════════════════════════════════════════════════╝

M_grid = ["#####", "#.#.#", "#.#.#", "#.#.#", "#.#.#"]
O_grid = ["#####", "#...#", "#...#", "#...#", "#####"]
R_grid = ["#####", "#...#", "####.", "#...#", "#...#"]
A_grid = ["#####", "#...#", "#####", "#...#", "#...#"]
Zero_grid = [".###.", "#...#", "#...#", "#...#", ".###."]
Two_grid = ["#####", "....#", "#####", "#....", "#####"]

LETTER_DEFS = [
    ("M", M_grid), ("O", O_grid), ("R", R_grid),
    ("A", A_grid), ("Z", Zero_grid), ("T", Two_grid),
]


# ╔══════════════════════════════════════════════════════════════╗
# ║  PROPERTIES                                                  ║
# ╚══════════════════════════════════════════════════════════════╝

class MORA02_Properties(PropertyGroup):

    # ── Mode ─────────────────────────────────────────────
    anim_mode: EnumProperty(
        name="Mode",
        items=[
            ('waves', 'Waves', 'Pulse, Float, Opacity Effekte'),
            ('factory', 'Factory', 'Mechanisches Explode/Shuffle/Reassemble'),
        ],
        default='waves',
    )

    # ── Allgemein ────────────────────────────────────────
    duration: FloatProperty(
        name="Duration", description="Sekunden",
        default=5.0, min=0.5, max=60.0, step=50,
    )
    fps: IntProperty(
        name="FPS", default=30, min=12, max=60,
    )
    ease_in: FloatProperty(
        name="Ease In", description="Einblend-Phase",
        default=0.15, min=0.0, max=0.5, step=5,
    )
    ease_out: FloatProperty(
        name="Ease Out", description="Ausblend-Phase",
        default=0.15, min=0.0, max=0.5, step=5,
    )
    theme: EnumProperty(
        name="Theme",
        items=[
            ('dark', 'Dark', 'Schwarz bg, weiße Würfel'),
            ('light', 'Light', 'Weiß bg, schwarze Würfel'),
            ('custom', 'Custom', 'Eigene Farben'),
        ],
        default='dark',
    )
    cube_color: bpy.props.FloatVectorProperty(
        name="Cube Color", subtype='COLOR',
        default=(1.0, 1.0, 1.0), min=0.0, max=1.0,
    )
    bg_color: bpy.props.FloatVectorProperty(
        name="BG Color", subtype='COLOR',
        default=(0.0, 0.0, 0.0), min=0.0, max=1.0,
    )

    # ── Glow / Emission ──────────────────────────────────
    glow_enabled: BoolProperty(name="Glow", default=False)
    emission_strength: FloatProperty(
        name="Emission", description="Emission Stärke",
        default=2.0, min=0.0, max=50.0, step=50,
    )
    emission_color: bpy.props.FloatVectorProperty(
        name="Emit Color", subtype='COLOR',
        default=(1.0, 1.0, 1.0), min=0.0, max=1.0,
    )

    # ── Render ───────────────────────────────────────────
    render_format: EnumProperty(
        name="Format",
        items=[('MP4', 'MP4', ''), ('PNG', 'PNG', '')],
        default='MP4',
    )
    render_path: bpy.props.StringProperty(
        name="Output Dir",
        default="/opt/mora02/output/_default/blender/",
        subtype='DIR_PATH',
    )
    resolution: IntProperty(
        name="Resolution", default=1080, min=256, max=4096, step=100,
    )
    render_engine: EnumProperty(
        name="Engine",
        items=[
            ('BLENDER_EEVEE', 'EEVEE', 'Schnell, gut für einfache Szenen'),
            ('CYCLES', 'Cycles', 'Fotorealistisch, langsamer'),
        ],
        default='BLENDER_EEVEE',
    )
    eevee_samples: IntProperty(
        name="EEVEE Samples", description="Render Samples (weniger=schneller)",
        default=16, min=1, max=256,
    )
    cycles_samples: IntProperty(
        name="Cycles Samples", description="Render Samples",
        default=64, min=1, max=4096,
    )
    render_settings_expanded: BoolProperty(
        name="Render Settings", default=False,
    )

    # ── Waves: Pulse ─────────────────────────────────────
    pulse_enabled: BoolProperty(name="Pulse", default=True)
    pulse_min: FloatProperty(name="Min Scale", default=0.5, min=0.01, max=1.0, step=5)
    pulse_max: FloatProperty(name="Max Scale", default=1.5, min=1.0, max=5.0, step=5)
    pulse_freq_min: FloatProperty(name="Freq Min", default=0.4, min=0.05, max=5.0, step=5)
    pulse_freq_max: FloatProperty(name="Freq Max", default=1.2, min=0.05, max=5.0, step=5)
    pulse_wave: EnumProperty(
        name="Wave",
        items=[('sin', 'Sin', ''), ('cos', 'Cos', ''), ('triangle', 'Triangle', '')],
        default='sin',
    )

    # ── Waves: Float ─────────────────────────────────────
    float_enabled: BoolProperty(name="Float", default=False)
    float_amp_x: FloatProperty(name="Amp X", default=0.3, min=0.0, max=5.0, step=5)
    float_amp_y: FloatProperty(name="Amp Y", default=0.3, min=0.0, max=5.0, step=5)
    float_amp_z: FloatProperty(name="Amp Z", default=0.5, min=0.0, max=5.0, step=5)
    float_freq_min: FloatProperty(name="Freq Min", default=0.2, min=0.05, max=5.0, step=5)
    float_freq_max: FloatProperty(name="Freq Max", default=0.8, min=0.05, max=5.0, step=5)
    float_wave: EnumProperty(
        name="Wave",
        items=[('sin', 'Sin', ''), ('cos', 'Cos', ''), ('triangle', 'Triangle', '')],
        default='sin',
    )
    float_per_axis: BoolProperty(name="Per Axis Freq", default=True)

    # ── Waves: Opacity ───────────────────────────────────
    opacity_enabled: BoolProperty(name="Opacity", default=False)
    opacity_min: FloatProperty(name="Min Alpha", default=0.1, min=0.0, max=1.0, step=5)
    opacity_max: FloatProperty(name="Max Alpha", default=1.0, min=0.0, max=1.0, step=5)
    opacity_freq_min: FloatProperty(name="Freq Min", default=0.3, min=0.05, max=5.0, step=5)
    opacity_freq_max: FloatProperty(name="Freq Max", default=1.0, min=0.05, max=5.0, step=5)
    opacity_wave: EnumProperty(
        name="Wave",
        items=[('sin', 'Sin', ''), ('cos', 'Cos', ''), ('triangle', 'Triangle', '')],
        default='sin',
    )

    # ── Waves: Camera Zoom ───────────────────────────────
    zoom_enabled: BoolProperty(name="Camera Zoom", default=False)
    zoom_min: FloatProperty(name="Zoom Min", default=0.8, min=0.1, max=3.0, step=5)
    zoom_max: FloatProperty(name="Zoom Max", default=1.5, min=0.1, max=3.0, step=5)
    zoom_freq: FloatProperty(name="Zoom Freq", default=0.3, min=0.05, max=2.0, step=5)

    # ── Factory ──────────────────────────────────────────
    factory_seed: IntProperty(
        name="Seed", description="Andere Zahl = neue Animation",
        default=42, min=1, max=9999,
    )
    factory_explode_min: FloatProperty(name="Explode Min", default=5, min=1, max=30, step=100)
    factory_explode_max: FloatProperty(name="Explode Max", default=15, min=2, max=50, step=100)
    factory_shuffle_moves: IntProperty(name="Shuffle Moves", default=3, min=1, max=8)
    factory_phase_explode: FloatProperty(name="Explode %", default=0.30, min=0.1, max=0.5, step=5)
    factory_phase_shuffle: FloatProperty(name="Shuffle %", default=0.35, min=0.1, max=0.5, step=5)
    factory_phase_reassemble: FloatProperty(name="Reassemble %", default=0.35, min=0.1, max=0.5, step=5)


# ╔══════════════════════════════════════════════════════════════╗
# ║  PANEL                                                       ║
# ╚══════════════════════════════════════════════════════════════╝

class MORA02_PT_main(Panel):
    bl_label = "MORA02"
    bl_idname = "MORA02_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MORA02"

    def draw(self, context):
        layout = self.layout
        props = context.scene.mora02

        # ── Mode Switch ──────────────────────────────
        box = layout.box()
        row = box.row(align=True)
        row.scale_y = 1.3
        row.prop(props, "anim_mode", expand=True)

        # ── Allgemein ────────────────────────────────
        box = layout.box()
        box.label(text="Animation", icon='TIME')
        row = box.row(align=True)
        row.prop(props, "duration")
        row.prop(props, "fps")
        box.prop(props, "theme")
        if props.theme == 'custom':
            row = box.row(align=True)
            row.prop(props, "cube_color")
            row.prop(props, "bg_color")

        # ── Glow ─────────────────────────────────────
        row = box.row()
        row.prop(props, "glow_enabled", icon='LIGHT_SUN' if props.glow_enabled else 'LIGHT_DATA')
        if props.glow_enabled:
            sub = box.box()
            sub.prop(props, "emission_strength")
            sub.prop(props, "emission_color")
            sub.label(text="Bloom: Compositor → Glare Node", icon='INFO')

        if props.anim_mode == 'waves':
            # ── Ease ─────────────────────────────────
            row = box.row(align=True)
            row.prop(props, "ease_in")
            row.prop(props, "ease_out")

            # ── Camera Zoom ──────────────────────────
            box = layout.box()
            row = box.row()
            row.prop(props, "zoom_enabled", icon='RADIOBUT_ON' if props.zoom_enabled else 'RADIOBUT_OFF')
            if props.zoom_enabled:
                row = box.row(align=True)
                row.prop(props, "zoom_min")
                row.prop(props, "zoom_max")
                box.prop(props, "zoom_freq")

        elif props.anim_mode == 'factory':
            # ── Factory Settings ─────────────────────
            box = layout.box()
            box.label(text="Factory", icon='MOD_ARRAY')
            box.prop(props, "factory_seed")
            row = box.row(align=True)
            row.prop(props, "factory_explode_min")
            row.prop(props, "factory_explode_max")
            box.prop(props, "factory_shuffle_moves")
            row = box.row(align=True)
            row.prop(props, "factory_phase_explode")
            row.prop(props, "factory_phase_shuffle")
            row.prop(props, "factory_phase_reassemble")

            # Recalc Button
            box.operator("mora02.factory_recalc", text="Recalculate Paths", icon='FILE_REFRESH')

        # ── Effects (beide Modi) ─────────────────────
        box = layout.box()
        box.label(text="Effects", icon='SHADERFX')

        # Pulse
        row = box.row()
        row.prop(props, "pulse_enabled", icon='RADIOBUT_ON' if props.pulse_enabled else 'RADIOBUT_OFF')
        if props.pulse_enabled:
            sub = box.box()
            row = sub.row(align=True)
            row.prop(props, "pulse_min")
            row.prop(props, "pulse_max")
            row = sub.row(align=True)
            row.prop(props, "pulse_freq_min")
            row.prop(props, "pulse_freq_max")
            sub.prop(props, "pulse_wave")

        # Float (nur Waves — kollidiert mit Factory-Positionierung)
        if props.anim_mode == 'waves':
            row = box.row()
            row.prop(props, "float_enabled", icon='RADIOBUT_ON' if props.float_enabled else 'RADIOBUT_OFF')
            if props.float_enabled:
                sub = box.box()
                row = sub.row(align=True)
                row.prop(props, "float_amp_x")
                row.prop(props, "float_amp_y")
                row.prop(props, "float_amp_z")
                row = sub.row(align=True)
                row.prop(props, "float_freq_min")
                row.prop(props, "float_freq_max")
                sub.prop(props, "float_wave")
                sub.prop(props, "float_per_axis")

        # Opacity
        row = box.row()
        row.prop(props, "opacity_enabled", icon='RADIOBUT_ON' if props.opacity_enabled else 'RADIOBUT_OFF')
        if props.opacity_enabled:
            sub = box.box()
            row = sub.row(align=True)
            row.prop(props, "opacity_min")
            row.prop(props, "opacity_max")
            row = sub.row(align=True)
            row.prop(props, "opacity_freq_min")
            row.prop(props, "opacity_freq_max")
            sub.prop(props, "opacity_wave")

        # ── Output ───────────────────────────────────
        box = layout.box()
        box.label(text="Output", icon='OUTPUT')
        row = box.row(align=True)
        row.prop(props, "render_format", expand=True)
        box.prop(props, "render_path")
        box.prop(props, "resolution")

        # ── Render Settings (aufklappbar) ────────────
        box2 = box.box()
        row = box2.row()
        row.prop(props, "render_settings_expanded",
                 icon='TRIA_DOWN' if props.render_settings_expanded else 'TRIA_RIGHT',
                 text="Render Settings", emboss=False)
        if props.render_settings_expanded:
            box2.prop(props, "render_engine")
            if props.render_engine == 'BLENDER_EEVEE':
                box2.prop(props, "eevee_samples")
            else:
                box2.prop(props, "cycles_samples")

        layout.separator()

        # ── Buttons ──────────────────────────────────
        row = layout.row(align=True)
        row.scale_y = 2.0
        row.operator("mora02.render_animation", text="RENDER", icon='RENDER_ANIMATION')

        row = layout.row(align=True)
        row.operator("mora02.apply_settings", text="Apply", icon='CHECKMARK')
        row.operator("mora02.rebuild_logo", text="Rebuild", icon='MESH_CUBE')


# ╔══════════════════════════════════════════════════════════════╗
# ║  OPERATORS                                                   ║
# ╚══════════════════════════════════════════════════════════════╝

class MORA02_OT_apply_settings(Operator):
    bl_idname = "mora02.apply_settings"
    bl_label = "Apply Settings"
    bl_description = "Timeline und Render-Settings aktualisieren"

    def execute(self, context):
        props = context.scene.mora02
        scene = context.scene
        scene.frame_start = 0
        scene.frame_end = int(props.duration * props.fps)
        scene.render.fps = props.fps
        scene.render.resolution_x = props.resolution
        scene.render.resolution_y = props.resolution

        if props.render_format == "MP4":
            try:
                # Blender 5.0+: media_type muss zuerst auf VIDEO gesetzt werden
                if hasattr(scene.render.image_settings, 'media_type'):
                    scene.render.image_settings.media_type = 'VIDEO'
                scene.render.image_settings.file_format = 'FFMPEG'
                scene.render.ffmpeg.format = 'MPEG4'
                scene.render.ffmpeg.codec = 'H264'
                scene.render.ffmpeg.constant_rate_factor = 'MEDIUM'
            except Exception as e:
                print(f"FFMPEG setup failed ({e}), falling back to PNG")
                scene.render.image_settings.file_format = 'PNG'
                scene.render.image_settings.color_mode = 'RGBA'
        else:
            scene.render.image_settings.file_format = 'PNG'
            scene.render.image_settings.color_mode = 'RGBA'

        scene.render.engine = props.render_engine
        if props.render_engine == 'BLENDER_EEVEE':
            scene.eevee.taa_render_samples = props.eevee_samples
            scene.eevee.taa_samples = max(props.eevee_samples // 4, 1)
        elif props.render_engine == 'CYCLES':
            scene.cycles.samples = props.cycles_samples
            scene.cycles.device = 'GPU'
        apply_theme(props.theme, props)
        scene.frame_set(0)
        self.report({'INFO'}, f"{props.duration}s @ {props.fps}fps | {props.anim_mode}")
        return {'FINISHED'}


class MORA02_OT_rebuild_logo(Operator):
    bl_idname = "mora02.rebuild_logo"
    bl_label = "Rebuild Logo"

    def execute(self, context):
        build_logo(context.scene.mora02.theme)
        if context.scene.mora02.anim_mode == 'factory':
            bpy.ops.mora02.factory_recalc()
        self.report({'INFO'}, "Logo rebuilt")
        return {'FINISHED'}


class MORA02_OT_render(Operator):
    bl_idname = "mora02.render_animation"
    bl_label = "Render Animation"

    def execute(self, context):
        import datetime, os
        props = context.scene.mora02
        ts = datetime.datetime.now().strftime("%y%m%d%H%M")
        out_dir = bpy.path.abspath(props.render_path)
        os.makedirs(out_dir, exist_ok=True)

        if props.render_format == "MP4":
            filepath = os.path.join(out_dir, f"{ts}_mora02_{props.anim_mode}.mp4")
        else:
            seq_dir = os.path.join(out_dir, f"{ts}_mora02_{props.anim_mode}")
            os.makedirs(seq_dir, exist_ok=True)
            filepath = os.path.join(seq_dir, "frame_")

        context.scene.render.filepath = filepath

        # Compositor-Check: ausschalten wenn kein gültiger Node Tree
        scene = context.scene
        comp_tree = getattr(scene, 'compositing_node_group', None)
        if comp_tree is None:
            scene.render.use_compositing = False
        else:
            # Prüfe ob Group Output Node existiert
            has_output = any(n.type == 'GROUP_OUTPUT' for n in comp_tree.nodes)
            if not has_output:
                scene.render.use_compositing = False

        bpy.ops.mora02.apply_settings()
        bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
        self.report({'INFO'}, f"Rendering → {filepath}")
        return {'FINISHED'}


class MORA02_OT_factory_recalc(Operator):
    bl_idname = "mora02.factory_recalc"
    bl_label = "Recalculate Factory Paths"
    bl_description = "Pfade neu berechnen (bei geänderten Parametern)"

    def execute(self, context):
        props = context.scene.mora02
        n = compute_factory_paths(props)
        self.report({'INFO'}, f"Factory: {n} moves berechnet")
        return {'FINISHED'}


# ╔══════════════════════════════════════════════════════════════╗
# ║  CORE: GRID + LOGO                                          ║
# ╚══════════════════════════════════════════════════════════════╝

def grid_to_pixels(grid):
    height = len(grid)
    pixels = []
    for row_idx, row_str in enumerate(grid):
        y = height - 1 - row_idx
        for col_idx, char in enumerate(row_str):
            if char == '#':
                pixels.append((col_idx, y))
    pixels.sort(key=lambda p: (p[0], p[1]))
    return pixels


def get_all_home_positions():
    positions = []
    x_cursor = 0
    for prefix, grid in LETTER_DEFS:
        width = len(grid[0])
        for px, py in grid_to_pixels(grid):
            positions.append((x_cursor + px, py, 0))
        x_cursor += width + 1
    return positions


def get_total_width():
    x = 0
    for _, grid in LETTER_DEFS:
        x += len(grid[0]) + 1
    return x - 1


def apply_theme(theme, props=None):
    if theme == "dark":
        cube_color = (1.0, 1.0, 1.0, 1.0)
        bg_color = (0.0, 0.0, 0.0, 1.0)
    elif theme == "light":
        cube_color = (0.0, 0.0, 0.0, 1.0)
        bg_color = (1.0, 1.0, 1.0, 1.0)
    elif theme == "custom" and props:
        cc = props.cube_color
        bc = props.bg_color
        cube_color = (cc[0], cc[1], cc[2], 1.0)
        bg_color = (bc[0], bc[1], bc[2], 1.0)
    else:
        return
    for mat in bpy.data.materials:
        if mat.name.startswith("Mat_") and mat.use_nodes:
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = cube_color
                # Emission
                if props and props.glow_enabled:
                    ec = props.emission_color
                    bsdf.inputs["Emission Color"].default_value = (ec[0], ec[1], ec[2], 1.0)
                    bsdf.inputs["Emission Strength"].default_value = props.emission_strength
                else:
                    bsdf.inputs["Emission Strength"].default_value = 0.0

    world = bpy.context.scene.world
    if world and world.use_nodes:
        bg = world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs["Color"].default_value = bg_color


def build_logo(theme="dark"):
    # Cleanup logo
    logo_col = bpy.data.collections.get("MORA02_Logo")
    if logo_col:
        for child_col in list(logo_col.children):
            for obj in list(child_col.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(child_col)
        for obj in list(logo_col.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(logo_col)

    for mesh in [m for m in bpy.data.meshes if m.name.startswith("Mesh_") and m.users == 0]:
        bpy.data.meshes.remove(mesh)
    for mat in [m for m in bpy.data.materials if m.name.startswith("Mat_") and m.users == 0]:
        bpy.data.materials.remove(mat)

    cube_color = (1.0, 1.0, 1.0, 1.0) if theme == "dark" else (0.0, 0.0, 0.0, 1.0)
    bg_color = (0.0, 0.0, 0.0, 1.0) if theme == "dark" else (1.0, 1.0, 1.0, 1.0)

    mat_base = bpy.data.materials.new(name="MORA02_Base")
    mat_base.use_nodes = True
    bsdf = mat_base.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = cube_color
    bsdf.inputs["Roughness"].default_value = 0.3
    bsdf.inputs["Metallic"].default_value = 0.1
    bsdf.inputs["Alpha"].default_value = 1.0

    world = bpy.context.scene.world
    if not world:
        world = bpy.data.worlds.new("MORA02_World")
        bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = bg_color

    logo_col = bpy.data.collections.new("MORA02_Logo")
    bpy.context.scene.collection.children.link(logo_col)

    homes = get_all_home_positions()
    total_width = get_total_width()
    cube_count = 0

    for idx, (wx, wy, wz) in enumerate(homes):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(wx + 0.5, wy + 0.5, 0.5))
        obj = bpy.context.active_object
        obj.name = f"Cube_{idx:03d}"
        obj.data.name = f"Mesh_{idx:03d}"
        mat = mat_base.copy()
        mat.name = f"Mat_{idx:03d}"
        obj.data.materials.append(mat)

        obj["cube_idx"] = idx
        obj["home_x"] = float(wx + 0.5)
        obj["home_y"] = float(wy + 0.5)
        obj["home_z"] = 0.5

        for c in obj.users_collection:
            c.objects.unlink(obj)
        logo_col.objects.link(obj)
        cube_count += 1

    bpy.data.materials.remove(mat_base)

    # Camera
    cx, cy = total_width / 2.0, 2.5
    if not bpy.data.objects.get("MORA02_Camera"):
        bpy.ops.object.camera_add(location=(cx, cy, 200))
        cam = bpy.context.active_object
        cam.name = "MORA02_Camera"
        cam.data.type = 'PERSP'
        cam.data.lens = 100  # Focal length
        cam.rotation_euler = (0, 0, 0)
        bpy.context.scene.camera = cam
    cam = bpy.data.objects["MORA02_Camera"]
    cam["base_focal"] = 100.0

    # Light
    if not bpy.data.objects.get("MORA02_Sun"):
        bpy.ops.object.light_add(type='SUN', location=(cx, cy, 20))
        sun = bpy.context.active_object
        sun.name = "MORA02_Sun"
        sun.data.energy = 3.0
        sun.rotation_euler = (0.3, 0.1, 0)

    bpy.context.scene.render.engine = 'BLENDER_EEVEE'
    print(f"MORA02: {cube_count} Würfel | Theme: {theme}")
    return cube_count


# ╔══════════════════════════════════════════════════════════════╗
# ║  WAVES: Wave Functions + Effects                             ║
# ╚══════════════════════════════════════════════════════════════╝

def wave_sin(t, freq, phase):
    return math.sin(2 * math.pi * freq * t + phase)

def wave_cos(t, freq, phase):
    return math.cos(2 * math.pi * freq * t + phase)

def wave_triangle(t, freq, phase):
    p = (t * freq + phase / (2 * math.pi)) % 1.0
    return 4 * abs(p - 0.5) - 1

WAVE_FUNCS = {"sin": wave_sin, "cos": wave_cos, "triangle": wave_triangle}

def obj_seed(name, salt=""):
    h = hashlib.md5((name + salt).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF

def obj_rand_range(name, salt, lo, hi):
    return lo + obj_seed(name, salt) * (hi - lo)

def ease_multiplier(progress, ease_in, ease_out):
    if progress < ease_in and ease_in > 0:
        t = progress / ease_in
        return t * t
    elif progress > (1.0 - ease_out) and ease_out > 0:
        t = (progress - (1.0 - ease_out)) / ease_out
        return 1.0 - t * t
    return 1.0

def apply_pulse(obj, t, ease, props):
    wave_fn = WAVE_FUNCS[props.pulse_wave]
    name = obj.name
    freq = obj_rand_range(name, "pulse_f", props.pulse_freq_min, props.pulse_freq_max)
    phase = obj_seed(name, "pulse_p") * 2 * math.pi
    w = wave_fn(t, freq, phase)
    lo, hi = props.pulse_min, props.pulse_max
    raw = (lo + hi) / 2 + w * (hi - lo) / 2
    val = raw * ease + 1.0 * (1.0 - ease)
    obj.scale = (val, val, val)

def apply_float(obj, t, ease, props):
    wave_fn = WAVE_FUNCS[props.float_wave]
    name = obj.name
    hx, hy, hz = obj.get("home_x", 0), obj.get("home_y", 0), obj.get("home_z", 0)
    if props.float_per_axis:
        fx = obj_rand_range(name, "fl_fx", props.float_freq_min, props.float_freq_max)
        fy = obj_rand_range(name, "fl_fy", props.float_freq_min, props.float_freq_max)
        fz = obj_rand_range(name, "fl_fz", props.float_freq_min, props.float_freq_max)
    else:
        fx = fy = fz = obj_rand_range(name, "fl_f", props.float_freq_min, props.float_freq_max)
    px = obj_seed(name, "fl_px") * 2 * math.pi
    py = obj_seed(name, "fl_py") * 2 * math.pi
    pz = obj_seed(name, "fl_pz") * 2 * math.pi
    obj.location = (
        hx + wave_fn(t, fx, px) * props.float_amp_x * ease,
        hy + wave_fn(t, fy, py) * props.float_amp_y * ease,
        hz + wave_fn(t, fz, pz) * props.float_amp_z * ease,
    )

def apply_opacity(obj, t, ease, props):
    wave_fn = WAVE_FUNCS[props.opacity_wave]
    name = obj.name
    freq = obj_rand_range(name, "opa_f", props.opacity_freq_min, props.opacity_freq_max)
    phase = obj_seed(name, "opa_p") * 2 * math.pi
    w = wave_fn(t, freq, phase)
    lo, hi = props.opacity_min, props.opacity_max
    raw = (lo + hi) / 2 + w * (hi - lo) / 2
    alpha = max(0.0, min(1.0, raw * ease + 1.0 * (1.0 - ease)))
    for ms in obj.material_slots:
        if ms.material and ms.material.use_nodes:
            ms.material.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = alpha


# ╔══════════════════════════════════════════════════════════════╗
# ║  FACTORY: Collision Grid + Path Planner                      ║
# ╚══════════════════════════════════════════════════════════════╝

DIRECTIONS = [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]

# Global: vorberechnete Pfade
_factory_data = {"paths": {}, "homes": [], "targets": [], "computed": False}


class CollisionGrid:
    def __init__(self):
        self.occupied = {}

    def reserve_path(self, name, start, end, f_start, f_end):
        cells = self._cells(start, end)
        for f in range(f_start, f_end + 1):
            for c in cells:
                k = (c[0], c[1], c[2], f)
                if k in self.occupied and self.occupied[k] != name:
                    return False
        for f in range(f_start, f_end + 1):
            for c in cells:
                self.occupied[(c[0], c[1], c[2], f)] = name
        return True

    def reserve_static(self, name, pos, f_start, f_end):
        c = (int(round(pos[0])), int(round(pos[1])), int(round(pos[2])))
        for f in range(f_start, f_end + 1):
            self.occupied[(c[0], c[1], c[2], f)] = name

    def _cells(self, start, end):
        sx, sy, sz = int(round(start[0])), int(round(start[1])), int(round(start[2]))
        ex, ey, ez = int(round(end[0])), int(round(end[1])), int(round(end[2]))
        cells = set()
        dx, dy, dz = ex-sx, ey-sy, ez-sz
        if dx != 0:
            for x in range(sx, ex + (1 if dx > 0 else -1), 1 if dx > 0 else -1):
                cells.add((x, sy, sz))
        elif dy != 0:
            for y in range(sy, ey + (1 if dy > 0 else -1), 1 if dy > 0 else -1):
                cells.add((sx, y, sz))
        elif dz != 0:
            for z in range(sz, ez + (1 if dz > 0 else -1), 1 if dz > 0 else -1):
                cells.add((sx, sy, z))
        else:
            cells.add((sx, sy, sz))
        return cells


def compute_factory_paths(props):
    global _factory_data
    rng = random.Random(props.factory_seed)
    total_frames = int(props.duration * props.fps)
    homes = get_all_home_positions()
    n = len(homes)

    # Phasen normalisieren (Summe = 1.0)
    p_sum = props.factory_phase_explode + props.factory_phase_shuffle + props.factory_phase_reassemble
    p_exp = props.factory_phase_explode / p_sum
    p_shuf = props.factory_phase_shuffle / p_sum
    f_exp_end = int(total_frames * p_exp)
    f_shuf_end = int(total_frames * (p_exp + p_shuf))

    targets = list(homes)
    rng.shuffle(targets)

    coll = CollisionGrid()
    paths = {}
    indices = list(range(n))
    rng.shuffle(indices)

    exp_min = int(props.factory_explode_min)
    exp_max = int(props.factory_explode_max)
    n_shuffle = props.factory_shuffle_moves

    # Phase 1: Explode
    explode_pos = {}
    for i, idx in enumerate(indices):
        home = homes[idx]
        name = f"c{idx}"
        stagger = int((i / n) * f_exp_end * 0.6)
        dur = int((f_exp_end - stagger) * (0.5 + rng.random() * 0.5))
        m_end = min(stagger + max(dur, 5), f_exp_end - 2)

        if stagger > 0:
            coll.reserve_static(name, home, 0, stagger)

        placed = False
        for _ in range(20):
            d = rng.choice(DIRECTIONS)
            dist = rng.randint(exp_min, exp_max)
            tgt = (home[0]+d[0]*dist, home[1]+d[1]*dist, home[2]+d[2]*dist)
            if coll.reserve_path(name, home, tgt, stagger, m_end):
                explode_pos[idx] = tgt
                paths[idx] = [(stagger, m_end, home, tgt)]
                coll.reserve_static(name, tgt, m_end, f_exp_end)
                placed = True
                break
        if not placed:
            tgt = (home[0], home[1], home[2] + exp_max + idx)
            explode_pos[idx] = tgt
            paths[idx] = [(stagger, m_end, home, tgt)]

    # Phase 2: Shuffle
    coll2 = CollisionGrid()
    for idx in range(n):
        coll2.reserve_static(f"c{idx}", explode_pos.get(idx, homes[idx]), f_exp_end, f_exp_end+1)

    shuffle_pos = {}
    budget = f_shuf_end - f_exp_end
    fps = props.fps

    for i, idx in enumerate(indices):
        pos = explode_pos.get(idx, homes[idx])
        name = f"c{idx}"
        fc = f_exp_end + int((i / n) * budget * 0.3)

        for _ in range(n_shuffle):
            if fc >= f_shuf_end - 5:
                break
            m_dur = int(fps * (0.3 + rng.random() * 0.7))
            m_end = min(fc + m_dur, f_shuf_end - 2)

            for _ in range(15):
                d = rng.choice(DIRECTIONS)
                dist = rng.randint(2, 8)
                nxt = (pos[0]+d[0]*dist, pos[1]+d[1]*dist, pos[2]+d[2]*dist)
                if coll2.reserve_path(name, pos, nxt, fc, m_end):
                    paths[idx].append((fc, m_end, pos, nxt))
                    coll2.reserve_static(name, nxt, m_end, m_end + 2)
                    pos = nxt
                    fc = m_end + 2
                    break
        shuffle_pos[idx] = pos

    # Phase 3: Reassemble
    coll3 = CollisionGrid()
    for idx in range(n):
        coll3.reserve_static(f"c{idx}", shuffle_pos.get(idx, homes[idx]), f_shuf_end, f_shuf_end+1)

    r_budget = total_frames - f_shuf_end
    r_order = list(range(n))
    rng.shuffle(r_order)

    for i, idx in enumerate(r_order):
        pos = shuffle_pos.get(idx, homes[idx])
        tgt = targets[idx]
        name = f"c{idx}"
        stagger = int((i / n) * r_budget * 0.5)
        fc = f_shuf_end + stagger

        remaining = [tgt[a] - pos[a] for a in range(3)]
        axes = [a for a in range(3) if remaining[a] != 0]
        rng.shuffle(axes)
        fpm = max(5, (total_frames - fc - 2 * len(axes)) // max(len(axes), 1))

        for ax in axes:
            if fc + 3 >= total_frames:
                break
            m_end = min(fc + fpm, total_frames - 1)
            nxt = list(pos)
            nxt[ax] = tgt[ax]
            nxt = tuple(nxt)
            if coll3.reserve_path(name, pos, nxt, fc, m_end):
                paths[idx].append((fc, m_end, pos, nxt))
                pos = nxt
                fc = m_end + 2

        if pos != tgt:
            paths[idx].append((min(fc, total_frames-3), total_frames-1, pos, tgt))

    _factory_data["paths"] = paths
    _factory_data["homes"] = homes
    _factory_data["targets"] = targets
    _factory_data["shuffle_end"] = f_shuf_end
    _factory_data["computed"] = True

    total_moves = sum(len(m) for m in paths.values())
    print(f"Factory: {n} cubes, {total_moves} moves, seed={props.factory_seed}")
    return total_moves


def lerp(a, b, t):
    return a + (b - a) * t

def factory_pos_at_frame(idx, frame, total_frames):
    d = _factory_data
    if not d["computed"]:
        return None, (0, 0, 0)
    homes = d["homes"]
    targets = d["targets"]
    moves = d["paths"].get(idx, [])
    home = homes[idx]
    hp = (home[0]+0.5, home[1]+0.5, 0.5)

    if not moves:
        return hp, (0, 0, 0)
    if frame <= 0:
        return hp, (0, 0, 0)
    target = targets[idx]
    tp = (target[0]+0.5, target[1]+0.5, 0.5)
    if frame >= total_frames:
        return tp, (0, 0, 0)

    ROT_FRAMES = 6
    ROT_ANGLE = math.radians(90)
    shuffle_end = d.get("shuffle_end", total_frames)

    current_rot = [0.0, 0.0, 0.0]

    for i, (sf, ef, sp, ep) in enumerate(moves):
        s = (sp[0]+0.5, sp[1]+0.5, sp[2]+0.5)
        e = (ep[0]+0.5, ep[1]+0.5, ep[2]+0.5)

        # Nur Shuffle-Moves drehen (nicht Explode i==0, nicht Reassemble sf>=shuffle_end)
        is_shuffle_move = (i > 0) and (sf < shuffle_end)

        if frame < sf:
            # Warte-Phase: wenn nächster Move Reassemble ist → Rotation schon weg
            if sf >= shuffle_end:
                return s, (0, 0, 0)
            return s, tuple(current_rot)

        elif frame <= ef:
            dur = ef - sf
            if dur <= 0:
                return e, (0, 0, 0)
            t = (frame - sf) / dur
            t = 4*t*t*t if t < 0.5 else 1 - pow(-2*t+2, 3)/2
            pos = (lerp(s[0],e[0],t), lerp(s[1],e[1],t), lerp(s[2],e[2],t))

            # Reassemble oder Explode: immer gerade, keine Rotation
            if not is_shuffle_move:
                return pos, (0, 0, 0)

            # Shuffle: drehen
            dx, dy, dz = e[0]-s[0], e[1]-s[1], e[2]-s[2]
            rot_add = _direction_to_rotation(dx, dy, dz, ROT_ANGLE)
            frames_into = frame - sf
            rot_f = min(ROT_FRAMES, dur // 2)

            if rot_f > 0 and frames_into < rot_f:
                kt = frames_into / rot_f
                kt = kt * kt * (3 - 2 * kt)
                return pos, (
                    current_rot[0] + rot_add[0] * kt,
                    current_rot[1] + rot_add[1] * kt,
                    current_rot[2] + rot_add[2] * kt,
                )
            return pos, (
                current_rot[0] + rot_add[0],
                current_rot[1] + rot_add[1],
                current_rot[2] + rot_add[2],
            )

        else:
            # Move vorbei: Rotation addieren für nächsten Move
            if is_shuffle_move:
                dx, dy, dz = e[0]-s[0], e[1]-s[1], e[2]-s[2]
                rot_add = _direction_to_rotation(dx, dy, dz, ROT_ANGLE)
                current_rot[0] += rot_add[0]
                current_rot[1] += rot_add[1]
                current_rot[2] += rot_add[2]

    return tp, (0, 0, 0)


def _direction_to_rotation(dx, dy, dz, angle):
    """Wandelt Bewegungsrichtung in eine Rotationsachse um.
    Würfel kippt in die Richtung in die er sich bewegt."""
    if abs(dx) > 0.01:
        # Bewegt sich auf X → rotiert um Y
        return (0, angle if dx > 0 else -angle, 0)
    elif abs(dy) > 0.01:
        # Bewegt sich auf Y → rotiert um X
        return (-angle if dy > 0 else angle, 0, 0)
    elif abs(dz) > 0.01:
        # Bewegt sich auf Z → rotiert um X (kippt nach vorne/hinten)
        return (angle if dz > 0 else -angle, 0, 0)
    return (0, 0, 0)


# ╔══════════════════════════════════════════════════════════════╗
# ║  UNIFIED FRAME HANDLER                                      ║
# ╚══════════════════════════════════════════════════════════════╝

def mora02_frame_handler(scene):
    try:
        _mora02_frame_handler_inner(scene)
    except Exception as e:
        print(f"MORA02 Handler Error: {e}")

def _mora02_frame_handler_inner(scene):
    if not hasattr(scene, 'mora02'):
        return
    props = scene.mora02
    frame = scene.frame_current
    total_frames = int(props.duration * props.fps)
    if total_frames <= 0:
        return

    logo_col = bpy.data.collections.get("MORA02_Logo")
    if not logo_col:
        return

    objects = list(logo_col.objects)

    if props.anim_mode == 'waves':
        t = frame / props.fps
        progress = min(frame / total_frames, 1.0)
        ease = ease_multiplier(progress, props.ease_in, props.ease_out)

        # Camera zoom (via focal length for perspective cam)
        if props.zoom_enabled:
            cam = scene.camera
            if cam:
                base = cam.get("base_focal", cam.data.lens)
                if progress >= 1.0:
                    cam.data.lens = base
                else:
                    lo, hi = props.zoom_min, props.zoom_max
                    w = math.sin(2 * math.pi * props.zoom_freq * t)
                    raw = (lo+hi)/2 + w*(hi-lo)/2
                    # Zoom: höherer Multiplikator = mehr Zoom (längere Focal Length)
                    cam.data.lens = base * (raw * ease + 1.0 * (1.0 - ease))

        for obj in objects:
            if obj.type != 'MESH':
                continue
            if progress >= 1.0:
                obj.scale = (1, 1, 1)
                obj.location = (obj.get("home_x",0), obj.get("home_y",0), obj.get("home_z",0.5))
                for ms in obj.material_slots:
                    if ms.material and ms.material.use_nodes:
                        ms.material.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = 1.0
                continue
            if props.pulse_enabled:
                apply_pulse(obj, t, ease, props)
            if props.float_enabled:
                apply_float(obj, t, ease, props)
            if props.opacity_enabled:
                apply_opacity(obj, t, ease, props)

    elif props.anim_mode == 'factory':
        if not _factory_data["computed"]:
            return
        t = frame / props.fps
        progress = min(frame / total_frames, 1.0) if total_frames > 0 else 0

        for obj in objects:
            if obj.type != 'MESH':
                continue
            idx = obj.get("cube_idx")
            if idx is None:
                continue
            pos, rot = factory_pos_at_frame(idx, frame, total_frames)
            if pos:
                obj.location = pos
                obj.rotation_euler = rot

            # Frame 0 und letzter Frame: alles auf Default
            if frame <= 0 or progress >= 1.0:
                obj.scale = (1, 1, 1)
                for ms in obj.material_slots:
                    if ms.material and ms.material.use_nodes:
                        ms.material.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = 1.0
                continue

            # Wave-Effekte additiv (Pulse=Scale, Opacity=Alpha)
            if props.pulse_enabled:
                apply_pulse(obj, t, 1.0, props)
            else:
                obj.scale = (1, 1, 1)
            if props.opacity_enabled:
                apply_opacity(obj, t, 1.0, props)
            else:
                for ms in obj.material_slots:
                    if ms.material and ms.material.use_nodes:
                        ms.material.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = 1.0


# ╔══════════════════════════════════════════════════════════════╗
# ║  REGISTER                                                    ║
# ╚══════════════════════════════════════════════════════════════╝

classes = [
    MORA02_Properties, MORA02_PT_main,
    MORA02_OT_apply_settings, MORA02_OT_rebuild_logo,
    MORA02_OT_render, MORA02_OT_factory_recalc,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mora02 = PointerProperty(type=MORA02_Properties)
    bpy.app.handlers.frame_change_post[:] = [
        h for h in bpy.app.handlers.frame_change_post
        if getattr(h, '__name__', '') != 'mora02_frame_handler'
    ]
    bpy.app.handlers.frame_change_post.append(mora02_frame_handler)

def unregister():
    bpy.app.handlers.frame_change_post[:] = [
        h for h in bpy.app.handlers.frame_change_post
        if getattr(h, '__name__', '') != 'mora02_frame_handler'
    ]
    del bpy.types.Scene.mora02
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

try:
    unregister()
except:
    pass

register()

if not bpy.data.collections.get("MORA02_Logo"):
    build_logo("dark")

# Blender 5.0: Minimal Compositor erstellen (ohne den crasht Render)
try:
    scene = bpy.context.scene
    comp_tree = getattr(scene, 'compositing_node_group', None)
    if comp_tree is None:
        tree = bpy.data.node_groups.new("MORA02_Comp", "CompositorNodeTree")
        scene.compositing_node_group = tree
        rlayers = tree.nodes.new(type="CompositorNodeRLayers")
        rlayers.location = (0, 0)
        output = tree.nodes.new(type='NodeGroupOutput')
        output.location = (400, 0)
        tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        tree.links.new(rlayers.outputs["Image"], output.inputs["Image"])
        print("MORA02: Compositor Node Tree erstellt")
except Exception as e:
    print(f"MORA02: Compositor setup skipped ({e})")

bpy.ops.mora02.apply_settings()

# Alle 3D-Viewports auf Kamera-Ansicht locken
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        for space in area.spaces:
            if space.type == 'VIEW_3D':
                space.lock_camera = True
                # In Kamera-Ansicht wechseln
                for region in area.regions:
                    if region.type == 'WINDOW':
                        override = {'area': area, 'region': region}
                        with bpy.context.temp_override(**override):
                            bpy.ops.view3d.view_camera()
                        break

print("\n" + "=" * 50)
print("MORA02 COMPLETE")
print("=" * 50)
print("  N-Taste → MORA02 Tab")
print("  Modes: Waves | Factory")
print("  Space → Play | RENDER → Output")
print("=" * 50)

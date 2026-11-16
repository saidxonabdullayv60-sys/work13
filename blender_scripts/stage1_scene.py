"""
Stage 1 - Cinematic Night-Rain Drift Scene
Blender 5.0 | EEVEE | Python (bpy)

This script:
  1. Imports the map (GLB), BMW (.blend append), Mercedes (GLB)
  2. Scales cars to real-world size (~4.3 m long), groups under parent empties
  3. Sets up night world, wet asphalt, volumetric fog, rain particles
  4. Adds headlights (spot + emission), tail lights (red emission)
  5. Animates both cars on a Follow Path curve with drift at the curve
  6. Sets up 3 camera shots via markers, DOF, handheld shake
  7. Configures EEVEE render settings
  8. Saves .blend, does a test render, then full render

Run: blender --background --python stage1_scene.py
Or:  Paste into Blender Scripting tab and Run
"""

import bpy
import bmesh
import math
import os
import random
from mathutils import Vector, Euler

# ============================================================================
# CONFIGURATION - Replace these paths with yours
# ============================================================================
ASSET_DIR = r"C:\Users\PC-01\Desktop\work ai site 3d"

MAP_GLB    = os.path.join(ASSET_DIR, "hongkong-city", "source", "burnout_revenge_-_central_route_crash_junction.glb")
BMW_BLEND  = os.path.join(ASSET_DIR, "free-bmw-m3-e30", "source", "E30_Final01.blend")
MERC_GLB   = os.path.join(ASSET_DIR, "1990-mercedes-benz-190e-25-16-evolution-ii", "source", "1990 Mercedes-Benz 190 Evo II.glb")

BLEND_FILE = os.path.join(ASSET_DIR, "output", "drift_scene.blend")
TEST_RENDER_DIR = os.path.join(ASSET_DIR, "output", "test_render")
FINAL_RENDER_DIR = os.path.join(ASSET_DIR, "output", "final_render")
TEST_RENDER_PATH = os.path.join(TEST_RENDER_DIR, "test_")
FINAL_RENDER_PATH = os.path.join(FINAL_RENDER_DIR, "drift_")

# Animation
FPS = 30
TOTAL_FRAMES = 270  # 9 seconds at 30fps
DRIFT_START_FRAME = 90   # frame 3s - when drift begins
DRIFT_END_FRAME = 210    # frame 7s - drift ends

# Render
RESOLUTION_X = 1920
RESOLUTION_Y = 1080
TEST_SCALE = 50  # percentage for test render

random.seed(42)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_action_fcurves(action):
    """Get fcurves from an Action, compatible with Blender 4.x and 5.0.

    In Blender 5.0, the animation system changed. Fcurves may be accessed via:
    - action.fcurves (old API, may still work)
    - action.layers[0].strips[0].channelbag(slot).fcurves (new slotted API)
    """
    # Try old API first
    if hasattr(action, 'fcurves'):
        try:
            return list(action.fcurves)
        except Exception:
            pass

    # Try new slotted API (Blender 5.0+)
    try:
        fcurves = []
        for layer in action.layers:
            for strip in layer.strips:
                # channelbag might need a slot argument
                try:
                    bag = strip.channelbag(strip.slot)
                except TypeError:
                    try:
                        bag = strip.channelbag()
                    except Exception:
                        continue
                except Exception:
                    continue
                if bag and hasattr(bag, 'fcurves'):
                    fcurves.extend(bag.fcurves)
        return fcurves
    except Exception:
        pass

    return []


def deselect_all():
    """Remove everything from the scene."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    # Clean orphan data
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)
    for block in bpy.data.images:
        if block.users == 0:
            bpy.data.images.remove(block)
    for block in bpy.data.lights:
        if block.users == 0:
            bpy.data.lights.remove(block)
    for block in bpy.data.cameras:
        if block.users == 0:
            bpy.data.cameras.remove(block)
    for block in bpy.data.curves:
        if block.users == 0:
            bpy.data.curves.remove(block)
    for block in bpy.data.particles:
        if block.users == 0:
            bpy.data.particles.remove(block)
    print("[OK] Scene cleared")


def deselect_all():
    bpy.ops.object.select_all(action='DESELECT')


def get_object_bbox_size(obj):
    """Get the bounding box dimensions in local space."""
    bbox = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_co = Vector((min(v.x for v in bbox), min(v.y for v in bbox), min(v.z for v in bbox)))
    max_co = Vector((max(v.x for v in bbox), max(v.y for v in bbox), max(v.z for v in bbox)))
    return max_co - min_co


def scale_object_to_length(obj, target_length):
    """Scale an object (and its children) so its longest bbox dimension = target_length."""
    # We need to evaluate the bbox of the whole hierarchy
    # Temporarily parent check
    all_children = [obj] + list(obj.children_recursive) if hasattr(obj, 'children_recursive') else [obj]

    # Get combined bbox
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    for child in all_children:
        if child.type != 'MESH':
            continue
        for corner in child.bound_box:
            world_corner = child.matrix_world @ Vector(corner)
            min_x = min(min_x, world_corner.x)
            max_x = max(max_x, world_corner.x)
            min_y = min(min_y, world_corner.y)
            max_y = max(max_y, world_corner.y)
            min_z = min(min_z, world_corner.z)
            max_z = max(max_z, world_corner.z)

    current_length = max(max_x - min_x, max_y - min_y)
    if current_length > 0:
        scale_factor = target_length / current_length
        obj.scale *= scale_factor
        bpy.context.view_layer.update()
        return scale_factor
    return 1.0


def find_wheels_by_name(parent, keywords=None):
    """Find wheel/tyre/rim/disc/caliper objects under a parent."""
    if keywords is None:
        keywords = ['wheel', 'tire', 'tyre', 'rim', 'disc', 'disk', 'caliper', 'brake', 'rad', 'reifen', 'felge']
    wheels = []
    for child in parent.children_recursive if hasattr(parent, 'children_recursive') else []:
        name_lower = child.name.lower()
        if any(kw in name_lower for kw in keywords):
            wheels.append(child)
    return wheels


def find_lights_by_name(parent, keywords_head=None, keywords_tail=None):
    """Find headlight and tail light objects under a parent."""
    if keywords_head is None:
        keywords_head = ['headlight', 'head_light', 'head light', 'front_light', 'hlight', 'scheinwerfer',
                         'frontlight', 'lens', 'light_fl', 'light_fr', 'headlight_lens', 'hl_', 'headlamp']
    if keywords_tail is None:
        keywords_tail = ['taillight', 'tail_light', 'tail light', 'rear_light', 'tlight', 'ruecklicht',
                         'tailight', 'light_rl', 'light_rr', 'brake_light', 'reflector', 'taillight_lens',
                         'tail_light_lens', 'tl_', 'tail_lamp', 'rearlight']

    headlights = []
    taillights = []
    for child in parent.children_recursive if hasattr(parent, 'children_recursive') else []:
        name_lower = child.name.lower()
        if any(kw in name_lower for kw in keywords_tail):
            taillights.append(child)
        elif any(kw in name_lower for kw in keywords_head):
            headlights.append(child)
    return headlights, taillights


def set_material_emission(mat, color, strength=5.0):
    """Set a material to emit light."""
    if mat and mat.use_nodes:
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        output = nodes.get("Material Output")
        if not output:
            output = nodes.new(type='ShaderNodeOutputMaterial')
            output.location = (300, 0)
        # Try to find existing Principled BSDF
        bsdf = nodes.get("Principled BSDF")
        if bsdf:
            # Set emission on Principled BSDF
            if 'Emission Color' in bsdf.inputs:
                bsdf.inputs['Emission Color'].default_value = (color[0], color[1], color[2], 1.0)
            elif 'Emission' in bsdf.inputs:
                bsdf.inputs['Emission'].default_value = (color[0], color[1], color[2], 1.0)
            if 'Emission Strength' in bsdf.inputs:
                bsdf.inputs['Emission Strength'].default_value = strength
        else:
            # Create emission node
            emit = nodes.new(type='ShaderNodeEmission')
            emit.inputs['Color'].default_value = (color[0], color[1], color[2], 1.0)
            emit.inputs['Strength'].default_value = strength
            links.new(emit.outputs['Emission'], output.inputs['Surface'])


def make_wet_asphalt(mat):
    """Modify a material to look like wet asphalt."""
    if not mat:
        return
    if not mat.use_nodes:
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    bsdf = nodes.get("Principled BSDF")
    if not bsdf:
        # Try to find any BSDF
        for node in nodes:
            if node.type == 'BSDF_PRINCIPLED':
                bsdf = node
                break

    if bsdf:
        # Wet road: low roughness, high specular
        if 'Roughness' in bsdf.inputs:
            # We'll drive roughness with a noise texture
            # First set a base value
            bsdf.inputs['Roughness'].default_value = 0.1

        # Add noise texture for roughness variation
        noise_tex = nodes.new(type='ShaderNodeTexNoise')
        noise_tex.inputs['Scale'].default_value = 15.0
        noise_tex.inputs['Detail'].default_value = 8.0
        noise_tex.inputs['Roughness'].default_value = 0.6
        noise_tex.location = (-600, -200)

        # Map range to keep roughness between 0.05 and 0.15
        map_range = nodes.new(type='ShaderNodeMapRange')
        map_range.inputs['From Min'].default_value = 0.0
        map_range.inputs['From Max'].default_value = 1.0
        map_range.inputs['To Min'].default_value = 0.05
        map_range.inputs['To Max'].default_value = 0.15
        map_range.location = (-300, -200)

        links.new(noise_tex.outputs['Fac'], map_range.inputs['Value'])
        links.new(map_range.outputs['Result'], bsdf.inputs['Roughness'])

        # Increase specular if available
        if 'Specular IOR Level' in bsdf.inputs:
            bsdf.inputs['Specular IOR Level'].default_value = 1.0
        elif 'Specular' in bsdf.inputs:
            bsdf.inputs['Specular'].default_value = 1.0


# ============================================================================
# STEP 1: IMPORT MAP
# ============================================================================

def import_map():
    """Import the Hong Kong city map GLB."""
    print("[STEP 1] Importing map...")
    deselect_all()
    bpy.ops.import_scene.gltf(filepath=MAP_GLB)
    # Get the imported root (usually the last imported object's parent or collection)
    map_objects = [o for o in bpy.context.selected_objects]
    print(f"  Imported {len(map_objects)} root map objects")

    # Find the root parent
    map_root = None
    for obj in map_objects:
        if obj.parent is None:
            map_root = obj
            break

    if not map_root and map_objects:
        map_root = map_objects[0]

    # Count meshes and triangles
    mesh_count = 0
    tri_count = 0
    all_meshes = []
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            mesh_count += 1
            all_meshes.append(obj)
            if obj.data and obj.data.polygons:
                tri_count += len(obj.data.polygons)

    print(f"  Map: {mesh_count} meshes, ~{tri_count} polygons")
    return map_root, all_meshes


# ============================================================================
# STEP 2: IMPORT BMW (Append from .blend)
# ============================================================================

def import_bmw():
    """Append all objects from the BMW blend file."""
    print("[STEP 2] Importing BMW M3 E30...")
    deselect_all()

    # Append all objects from the blend file
    with bpy.data.libraries.load(BMW_BLEND, link=False) as (data_from, data_to):
        data_to.objects = data_from.objects
        # Also bring materials
        data_to.materials = data_from.materials
        data_to.images = data_from.images

    # Link all appended objects to the scene
    bmw_objects = []
    for obj in data_to.objects:
        if obj is not None:
            bpy.context.collection.objects.link(obj)
            bmw_objects.append(obj)

    print(f"  Appended {len(bmw_objects)} BMW objects")

    # Find the main body (largest mesh) to determine scale
    body_obj = None
    max_vol = 0
    for obj in bmw_objects:
        if obj.type == 'MESH' and obj.data and obj.data.polygons:
            vol = len(obj.data.polygons)
            if vol > max_vol:
                max_vol = vol
                body_obj = obj

    # Create parent empty
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
    car_parent = bpy.context.active_object
    car_parent.name = "CAR_BMW"

    # Parent all top-level BMW objects to the empty
    for obj in bmw_objects:
        if obj.parent is None:
            obj.parent = car_parent

    # Scale to ~4.3m long
    bpy.context.view_layer.update()
    scale_factor = scale_object_to_length(car_parent, 4.3)
    print(f"  BMW scaled by {scale_factor:.3f} to ~4.3m")

    return car_parent


# ============================================================================
# STEP 3: IMPORT MERCEDES (GLB)
# ============================================================================

def import_mercedes():
    """Import the Mercedes 190E Evo II GLB."""
    print("[STEP 3] Importing Mercedes 190E Evo II...")
    deselect_all()
    bpy.ops.import_scene.gltf(filepath=MERC_GLB)

    merc_objects = [o for o in bpy.context.selected_objects]
    print(f"  Imported {len(merc_objects)} Mercedes objects")

    # Create parent empty
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
    car_parent = bpy.context.active_object
    car_parent.name = "CAR_MERC"

    # Parent all top-level Mercedes objects
    for obj in merc_objects:
        if obj.parent is None:
            obj.parent = car_parent

    # Scale to ~4.3m long
    bpy.context.view_layer.update()
    scale_factor = scale_object_to_length(car_parent, 4.3)
    print(f"  Mercedes scaled by {scale_factor:.3f} to ~4.3m")

    return car_parent


# ============================================================================
# STEP 4: FIND ROAD AND PLACE CARS
# ============================================================================

def find_road_and_place(map_root, all_map_meshes, car_bmw, car_merc):
    """Find a suitable road section and place cars there."""
    print("[STEP 4] Finding road section and placing cars...")

    # Find the approximate center of the map
    map_min = Vector((float('inf'),) * 3)
    map_max = Vector((float('-inf'),) * 3)
    for obj in all_map_meshes:
        for corner in obj.bound_box:
            wc = obj.matrix_world @ Vector(corner)
            map_min.x = min(map_min.x, wc.x)
            map_max.x = max(map_max.x, wc.x)
            map_min.y = min(map_min.y, wc.y)
            map_max.y = max(map_max.y, wc.y)
            map_min.z = min(map_min.z, wc.z)
            map_max.z = max(map_max.z, wc.z)

    map_center = (map_min + map_max) / 2
    map_size = map_max - map_min
    print(f"  Map bounds: min={map_min}, max={map_max}, center={map_center}")

    # Place cars at a reasonable starting point on the road
    # We'll use the map center as reference and place cars slightly offset
    start_x = map_center.x
    start_y = map_center.y - map_size.y * 0.2  # offset toward one side
    start_z = map_min.z + 0.5  # slightly above ground

    car_bmw.location = (start_x - 1.5, start_y, start_z)
    car_merc.location = (start_x + 1.5, start_y, start_z)

    # Orient cars facing +Y direction
    car_bmw.rotation_euler = (0, 0, math.radians(90))
    car_merc.rotation_euler = (0, 0, math.radians(90))

    # The map is compact (~15m x 30m), so keep everything visible for now.
    # Only hide objects that are very far from the driving area (more than 2x map size away).
    keep_radius = max(map_size.x, map_size.y) * 1.5
    hidden_count = 0
    for obj in all_map_meshes:
        dist = (obj.location - Vector((start_x, start_y, start_z))).length
        if dist > keep_radius:
            obj.hide_render = True
            obj.hide_viewport = True
            hidden_count += 1

    print(f"  Hidden {hidden_count} distant map objects (keep radius={keep_radius:.1f})")
    print(f"  BMW placed at {car_bmw.location}")
    print(f"  Mercedes placed at {car_merc.location}")

    return Vector((start_x, start_y, start_z)), map_center, map_size


# ============================================================================
# STEP 5: NIGHT WORLD + WET ASPHALT
# ============================================================================

def setup_night_world():
    """Set up a dark night world with low blue ambient."""
    print("[STEP 5] Setting up night world...")

    world = bpy.context.scene.world
    if not world:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world

    try:
        world.use_nodes = True
    except Exception:
        pass
    nodes = world.node_tree.nodes
    links = world.node_tree.links

    # Clear existing nodes
    nodes.clear()

    # Background node with dark blue
    bg = nodes.new(type='ShaderNodeBackground')
    bg.inputs['Color'].default_value = (0.015, 0.025, 0.045, 1.0)  # very dark blue
    bg.inputs['Strength'].default_value = 0.3

    output = nodes.new(type='ShaderNodeOutputWorld')
    links.new(bg.outputs['Background'], output.inputs['Surface'])

    print("  Night world set (dark blue, strength 0.3)")


def make_wet_roads(all_map_meshes):
    """Find road/ground materials and make them wet.

    Strategy:
    1. Try matching by name (road, asphalt, ground, etc.)
    2. Try matching large flat meshes at ground level
    3. Fall back: apply wet look to ALL dark-colored Principled BSDF materials
       that appear to be ground/wall surfaces.
    """
    print("[STEP 5b] Making road materials wet...")
    road_keywords = ['road', 'asphalt', 'street', 'ground', 'floor', 'pavement', 'tarmac', 'surface',
                     'concrete', 'cement', 'tar']
    wet_count = 0
    processed_mats = set()

    # Strategy 1: match by name
    for obj in all_map_meshes:
        if obj.type != 'MESH' or not obj.data.materials:
            continue
        obj_name_lower = obj.name.lower()
        is_road = any(kw in obj_name_lower for kw in road_keywords)

        for slot in obj.data.materials:
            if slot is None or slot.name in processed_mats:
                continue
            mat_name_lower = slot.name.lower()
            if is_road or any(kw in mat_name_lower for kw in road_keywords):
                make_wet_asphalt(slot)
                processed_mats.add(slot.name)
                wet_count += 1

    # Strategy 2: large flat meshes at low Z
    if wet_count == 0:
        print("  No road by name. Trying large flat ground meshes...")
        for obj in all_map_meshes:
            if obj.type != 'MESH' or not obj.data or not obj.data.polygons:
                continue
            size = get_object_bbox_size(obj)
            # Ground-like: wide in X/Y, thin in Z, near ground level
            if size.x > 3 and size.y > 3 and size.z < 1.5:
                for slot in obj.data.materials:
                    if slot is None or slot.name in processed_mats:
                        continue
                    make_wet_asphalt(slot)
                    processed_mats.add(slot.name)
                    wet_count += 1

    # Strategy 3: apply to ALL materials that use Principled BSDF with dark base color
    if wet_count == 0:
        print("  No ground meshes found. Applying wet look to all dark materials...")
        for mat in bpy.data.materials:
            if mat is None or mat.name in processed_mats:
                continue
            if not mat.use_nodes:
                continue
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                base_color = bsdf.inputs.get('Base Color')
                if base_color:
                    c = base_color.default_value
                    # Dark materials (low brightness)
                    brightness = (c[0] + c[1] + c[2]) / 3
                    if brightness < 0.25:
                        make_wet_asphalt(mat)
                        processed_mats.add(mat.name)
                        wet_count += 1

    print(f"  Made {wet_count} materials wet")


# ============================================================================
# STEP 6: VOLUMETRIC FOG
# ============================================================================

def setup_fog():
    """Add volumetric fog to the world."""
    print("[STEP 6] Setting up volumetric fog...")

    world = bpy.context.scene.world
    if not world:
        return

    nodes = world.node_tree.nodes
    links = world.node_tree.links

    # Find the output
    output = None
    for node in nodes:
        if node.type == 'OUTPUT_WORLD':
            output = node
            break

    if not output:
        return

    # Add volume scatter
    vol_scatter = nodes.new(type='ShaderNodeVolumeScatter')
    vol_scatter.inputs['Density'].default_value = 0.01
    vol_scatter.inputs['Anisotropy'].default_value = 0.3
    vol_scatter.inputs['Color'].default_value = (0.4, 0.5, 0.7, 1.0)  # slight blue tint
    vol_scatter.location = (200, -200)

    links.new(vol_scatter.outputs['Volume'], output.inputs['Volume'])

    print("  Volume scatter added (density 0.01, anisotropy 0.3)")


# ============================================================================
# STEP 7: RAIN PARTICLE SYSTEM
# ============================================================================

def setup_rain(camera):
    """Create a rain particle system parented to the camera."""
    print("[STEP 7] Setting up rain particles...")

    # Create a rain emitter plane above the camera
    bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, 15))
    rain_plane = bpy.context.active_object
    rain_plane.name = "RainEmitter"
    rain_plane.hide_render = True
    rain_plane.hide_viewport = False

    # Create rain particle material (thin streaks)
    rain_mat = bpy.data.materials.new(name="RainStreak")
    try:
        rain_mat.use_nodes = True
    except Exception:
        pass
    rnodes = rain_mat.node_tree.nodes
    rlinks = rain_mat.node_tree.links
    rnodes.clear()
    emit = rnodes.new(type='ShaderNodeEmission')
    emit.inputs['Color'].default_value = (0.6, 0.7, 0.9, 0.3)
    emit.inputs['Strength'].default_value = 0.5
    rout = rnodes.new(type='ShaderNodeOutputMaterial')
    rlinks.new(emit.outputs['Emission'], rout.inputs['Surface'])
    rain_mat.blend_method = 'BLEND'

    # Create the particle system
    bpy.context.view_layer.objects.active = rain_plane
    bpy.ops.object.particle_system_add()
    ps = rain_plane.particle_systems[0]
    psettings = ps.settings

    psettings.count = 4500
    psettings.frame_start = 1
    psettings.frame_end = TOTAL_FRAMES
    psettings.lifetime = 30
    psettings.emit_from = 'VERT'
    # Blender 5.0: physics_type enum is 'NO', 'NEWTON', 'KEYED', 'BOIDS', 'FLUID'
    psettings.physics_type = 'NEWTON'
    psettings.render_type = 'OBJECT'
    psettings.particle_size = 0.02
    psettings.size_random = 0.3

    # Create the rain streak object (thin elongated cylinder)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.008, depth=0.4, location=(100, 100, -50))
    rain_streak = bpy.context.active_object
    rain_streak.name = "RainStreakMesh"
    rain_streak.data.materials.append(rain_mat)
    # Make it elongated (stretch Z)
    rain_streak.scale = (1, 1, 3)

    # Assign as particle render object
    psettings.instance_object = rain_streak
    rain_streak.hide_render = True
    rain_streak.hide_viewport = True

    # Set initial velocity downward (normal_factor on a plane emits along normal = +Z up, we want down)
    # So we use gravity force field for downward motion instead
    psettings.mass = 0.001
    psettings.normal_factor = 0

    # Add a force field for gravity (stronger than default for rain effect)
    bpy.ops.object.effector_add(type='FORCE', location=(0, 0, 10))
    force = bpy.context.active_object
    force.name = "RainGravity"
    force.field.strength = 30  # strong downward
    force.field.shape = 'POINT'

    # Parent rain plane to camera so it follows
    rain_plane.parent = camera
    rain_plane.matrix_parent_inverse = camera.matrix_world.inverted()

    # Also parent the force field
    force.parent = camera
    force.matrix_parent_inverse = camera.matrix_world.inverted()

    # Animate the rain plane to stay above camera
    # We'll update its position each frame via driver or keyframes
    # Simple approach: parent to camera with offset
    rain_plane.location = (0, 0, 15)  # relative to camera

    print(f"  Rain: {psettings.count} particles, streak object created, parented to camera")


# ============================================================================
# STEP 8: CAR LIGHTS
# ============================================================================

def setup_car_lights(car_parent, is_bmw=True):
    """Add headlights and tail lights to a car."""
    print(f"[STEP 8] Setting up lights for {car_parent.name}...")

    headlights, taillights = find_lights_by_name(car_parent)

    # If no lights found by name, create them based on car bbox
    car_size = Vector((0, 0, 0))
    car_min = Vector((float('inf'),) * 3)
    car_max = Vector((float('-inf'),) * 3)
    for child in car_parent.children_recursive if hasattr(car_parent, 'children_recursive') else []:
        if child.type != 'MESH':
            continue
        for corner in child.bound_box:
            wc = child.matrix_world @ Vector(corner)
            car_min.x = min(car_min.x, wc.x)
            car_max.x = max(car_max.x, wc.x)
            car_min.y = min(car_min.y, wc.y)
            car_max.y = max(car_max.y, wc.y)
            car_min.z = min(car_min.z, wc.z)
            car_max.z = max(car_max.z, wc.z)

    car_size = car_max - car_min
    car_center = (car_min + car_max) / 2

    # Determine front direction (we set rotation_euler Z=90 so front is +Y in world, but locally +X)
    # After parenting and rotation, front is typically +X in local space
    front_offset = car_size.x * 0.48
    side_offset = car_size.y * 0.35
    height_offset = car_size.z * 0.35

    # Headlight positions (local to car_parent)
    hl_left_pos = Vector((front_offset, -side_offset, height_offset))
    hl_right_pos = Vector((front_offset, side_offset, height_offset))

    # Tail light positions
    tl_left_pos = Vector((-front_offset, -side_offset, height_offset))
    tl_right_pos = Vector((-front_offset, side_offset, height_offset))

    # Create headlight spot lights
    for name, pos in [("HEADLIGHT_L", hl_left_pos), ("HEADLIGHT_R", hl_right_pos)]:
        bpy.ops.object.light_add(type='SPOT', location=pos)
        light = bpy.context.active_object
        light.name = f"{car_parent.name}_{name}"
        light.data.energy = 800
        light.data.spot_size = math.radians(45)
        light.data.spot_blend = 0.3
        light.data.color = (1.0, 0.95, 0.8)  # warm white
        light.data.shadow_soft_size = 0.15
        # Aim forward (+X)
        light.rotation_euler = (0, math.radians(90), 0)
        light.parent = car_parent
        light.matrix_parent_inverse = car_parent.matrix_world.inverted()

    # Make headlight lens materials emissive
    for hl in headlights:
        for slot in hl.data.materials if hl.data else []:
            if slot:
                set_material_emission(slot, (1.0, 0.95, 0.8), strength=10.0)

    # Tail lights - red emission
    for tl in taillights:
        for slot in tl.data.materials if tl.data else []:
            if slot:
                set_material_emission(slot, (1.0, 0.05, 0.02), strength=8.0)

    # If no taillight objects found by name, create small emissive planes
    if not taillights:
        for name, pos in [("TAILLIGHT_L", tl_left_pos), ("TAILLIGHT_R", tl_right_pos)]:
            bpy.ops.mesh.primitive_plane_add(size=0.15, location=pos)
            tl_obj = bpy.context.active_object
            tl_obj.name = f"{car_parent.name}_{name}"
            tl_obj.rotation_euler = (math.radians(90), 0, math.radians(90))
            tl_mat = bpy.data.materials.new(name=f"{car_parent.name}_TL_{name}")
            set_material_emission(tl_mat, (1.0, 0.05, 0.02), strength=8.0)
            tl_obj.data.materials.append(tl_mat)
            tl_obj.parent = car_parent
            tl_obj.matrix_parent_inverse = car_parent.matrix_world.inverted()

    print(f"  {car_parent.name}: {len(headlights)} headlight objects, {len(taillights)} taillight objects found")


# ============================================================================
# STEP 9: DRIVING PATH AND ANIMATION
# ============================================================================

def create_drive_path(start_pos, map_center, map_size):
    """Create a Bezier curve path for the cars to follow."""
    print("[STEP 9] Creating drive path...")

    # Create a curve that goes straight then curves
    curve_data = bpy.data.curves.new('DrivePath', type='CURVE')
    curve_data.dimensions = '3D'
    curve_data.resolution_u = 64

    spline = curve_data.splines.new('BEZIER')
    spline.bezier_points.add(6)  # 7 points total

    z = start_pos.z

    # Straight section then curve
    points = [
        Vector((start_pos.x, start_pos.y - 10, z)),
        Vector((start_pos.x, start_pos.y, z)),
        Vector((start_pos.x, start_pos.y + 10, z)),
        Vector((start_pos.x + 5, start_pos.y + 20, z)),
        Vector((start_pos.x + 15, start_pos.y + 25, z)),
        Vector((start_pos.x + 25, start_pos.y + 20, z)),
        Vector((start_pos.x + 30, start_pos.y + 10, z)),
    ]

    for i, pt in enumerate(points):
        bp = spline.bezier_points[i]
        bp.co = pt
        bp.handle_left_type = 'AUTO'
        bp.handle_right_type = 'AUTO'

    # Create the curve object
    curve_obj = bpy.data.objects.new("DrivePath", curve_data)
    bpy.context.collection.objects.link(curve_obj)

    print(f"  Drive path created with {len(points)} control points")
    return curve_obj


def animate_cars_on_path(car_bmw, car_merc, path_curve, start_pos):
    """Animate both cars following the path with drift at the curve."""
    print("[STEP 9b] Animating cars on path...")

    # Add Follow Path constraint to both cars
    for car, offset_x, name in [(car_bmw, -1.5, "BMW"), (car_merc, 1.5, "MERC")]:
        # Clear existing constraints
        car.constraints.clear()

        # Add Follow Path constraint
        fp = car.constraints.new(type='FOLLOW_PATH')
        fp.target = path_curve
        fp.forward_axis = 'TRACK_AXIS_Y' if False else 'FORWARD_X'
        fp.up_axis = 'UP_Z'
        fp.use_curve_follow = True
        fp.use_fixed_location = True
        fp.offset_factor = 0.0

        # Animate offset_factor: 0 at frame 1, 1 at frame TOTAL_FRAMES
        fp.offset_factor = 0.0
        fp.keyframe_insert(data_path="offset_factor", frame=1)
        fp.offset_factor = 1.0
        fp.keyframe_insert(data_path="offset_factor", frame=TOTAL_FRAMES)

        # Set the follow path offset for side-by-side
        fp.offset = offset_x * 100  # offset in the curve's offset space

    # Now add drift animation by keyframing rotation on each car
    # The Follow Path constraint controls position+heading, we add drift on top
    # We'll add an extra rotation via keyframes on a child empty

    drift_objects = []
    for car, drift_start, drift_end, drift_angle, name in [
        (car_bmw, DRIFT_START_FRAME, DRIFT_END_FRAME, math.radians(32), "BMW"),
        (car_merc, DRIFT_START_FRAME + 5, DRIFT_END_FRAME + 3, math.radians(28), "MERC")
    ]:
        # Keyframe the car's Z rotation for drift
        # Before drift: 0
        # During drift: drift_angle
        # After drift: back to 0

        # We need to keyframe rotation_euler on top of the follow path
        # Since follow path controls rotation, we add an extra rotation offset
        # by animating a parent empty

        # Create a drift offset empty
        bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
        drift_empty = bpy.context.active_object
        drift_empty.name = f"{name}_DriftOffset"

        # Reparent: car's current parent becomes the drift empty's parent
        old_parent = car.parent
        car_parent_world = car.matrix_world.copy()

        # Unparent car, parent to drift empty
        car.parent = None
        car.matrix_world = car_parent_world  # preserve world position

        drift_empty.parent = old_parent
        drift_empty.matrix_world = car_parent_world  # match car position
        car.parent = drift_empty
        car.matrix_parent_inverse = drift_empty.matrix_world.inverted()

        # Now keyframe the drift empty's Z rotation
        # Actually, since the car has Follow Path, the constraint is on the car
        # Let's put the Follow Path on the drift empty instead
        car.constraints.clear()

        fp = drift_empty.constraints.new(type='FOLLOW_PATH')
        fp.target = path_curve
        fp.forward_axis = 'FORWARD_X'
        fp.up_axis = 'UP_Z'
        fp.use_curve_follow = True
        fp.use_fixed_location = True
        fp.offset_factor = 0.0

        fp.offset_factor = 0.0
        fp.keyframe_insert(data_path="offset_factor", frame=1)
        fp.offset_factor = 1.0
        fp.keyframe_insert(data_path="offset_factor", frame=TOTAL_FRAMES)

        # Keyframe drift rotation on the CAR (relative to drift_empty)
        # Before drift
        car.rotation_euler.z = 0
        car.keyframe_insert(data_path="rotation_euler", index=2, frame=1)
        car.keyframe_insert(data_path="rotation_euler", index=2, frame=drift_start - 1)

        # Start of drift - ramp up
        car.rotation_euler.z = drift_angle
        car.keyframe_insert(data_path="rotation_euler", index=2, frame=drift_start + 8)

        # Hold drift
        car.rotation_euler.z = drift_angle
        car.keyframe_insert(data_path="rotation_euler", index=2, frame=drift_end - 8)

        # End of drift - ramp down
        car.rotation_euler.z = 0
        car.keyframe_insert(data_path="rotation_euler", index=2, frame=drift_end)
        car.keyframe_insert(data_path="rotation_euler", index=2, frame=TOTAL_FRAMES)

        # Body roll - keyframe X rotation slightly
        roll_angle = math.radians(3)
        car.rotation_euler.x = 0
        car.keyframe_insert(data_path="rotation_euler", index=0, frame=drift_start)
        car.rotation_euler.x = roll_angle
        car.keyframe_insert(data_path="rotation_euler", index=0, frame=drift_start + 10)
        car.rotation_euler.x = -roll_angle * 0.5
        car.keyframe_insert(data_path="rotation_euler", index=0, frame=drift_end - 10)
        car.rotation_euler.x = 0
        car.keyframe_insert(data_path="rotation_euler", index=0, frame=drift_end)

        # Wheel rotation animation
        wheels = find_wheels_by_name(car)
        for wheel in wheels:
            # Determine if front or rear
            wheel_local = wheel.matrix_local.translation
            is_front = wheel_local.x > 0
            is_rear = wheel_local.x < 0

            # Spin wheels
            wheel.rotation_euler.y = 0
            wheel.keyframe_insert(data_path="rotation_euler", index=1, frame=1)

            spin_speed = 15 if is_rear else 8  # rear wheels spin faster during drift
            if is_rear:
                # Extra fast spin during drift
                wheel.rotation_euler.y = spin_speed * math.pi * (drift_start / FPS)
                wheel.keyframe_insert(data_path="rotation_euler", index=1, frame=drift_start)

                wheel.rotation_euler.y = spin_speed * math.pi * 3 * ((drift_end - drift_start) / FPS)
                wheel.keyframe_insert(data_path="rotation_euler", index=1, frame=drift_end)

                wheel.rotation_euler.y = spin_speed * math.pi * 3 * ((drift_end - drift_start) / FPS) + spin_speed * math.pi * 2 * ((TOTAL_FRAMES - drift_end) / FPS)
                wheel.keyframe_insert(data_path="rotation_euler", index=1, frame=TOTAL_FRAMES)
            else:
                # Front wheels: normal speed + steering
                wheel.rotation_euler.y = spin_speed * math.pi * 2 * (TOTAL_FRAMES / FPS)
                wheel.keyframe_insert(data_path="rotation_euler", index=1, frame=TOTAL_FRAMES)

                # Counter-steer front wheels during drift (Z rotation)
                steer_angle = -math.radians(15) if is_front else 0
                wheel.rotation_euler.z = 0
                wheel.keyframe_insert(data_path="rotation_euler", index=2, frame=drift_start - 1)
                wheel.rotation_euler.z = steer_angle
                wheel.keyframe_insert(data_path="rotation_euler", index=2, frame=drift_start + 5)
                wheel.rotation_euler.z = steer_angle * 0.5
                wheel.keyframe_insert(data_path="rotation_euler", index=2, frame=drift_end - 5)
                wheel.rotation_euler.z = 0
                wheel.keyframe_insert(data_path="rotation_euler", index=2, frame=drift_end)

        drift_objects.append((car, drift_empty, drift_start, drift_end))

    # Set interpolation to BEZIER for smooth motion
    for obj in [car_bmw, car_merc]:
        if obj.animation_data and obj.animation_data.action:
            for fcurve in get_action_fcurves(obj.animation_data.action):
                for kp in fcurve.keyframe_points:
                    kp.interpolation = 'BEZIER'

    print(f"  Animation complete: BMW drift at f{DRIFT_START_FRAME}, MERC drift at f{DRIFT_START_FRAME+5}")
    return drift_objects


# ============================================================================
# STEP 10: TYRE SMOKE
# ============================================================================

def setup_tyre_smoke(car_parent, drift_start, drift_end):
    """Add cheap particle tyre smoke from rear wheels."""
    print("[STEP 10] Setting up tyre smoke...")

    wheels = find_wheels_by_name(car_parent)
    rear_wheels = [w for w in wheels if w.matrix_local.translation.x < 0]

    if not rear_wheels:
        # If we can't determine, use the last 2 wheels
        rear_wheels = wheels[-2:] if len(wheels) >= 2 else wheels

    # Create smoke material
    smoke_mat = bpy.data.materials.new(name=f"{car_parent.name}_Smoke")
    try:
        smoke_mat.use_nodes = True
    except Exception:
        pass
    snodes = smoke_mat.node_tree.nodes
    slinks = smoke_mat.node_tree.links
    snodes.clear()

    # Smoke shader: translucent white/grey
    principled = snodes.new(type='ShaderNodeBsdfPrincipled')
    principled.inputs['Base Color'].default_value = (0.5, 0.5, 0.55, 0.6)
    if 'Alpha' in principled.inputs:
        principled.inputs['Alpha'].default_value = 0.4
    if 'Roughness' in principled.inputs:
        principled.inputs['Roughness'].default_value = 0.9

    sout = snodes.new(type='ShaderNodeOutputMaterial')
    slinks.new(principled.outputs['BSDF'], sout.inputs['Surface'])
    smoke_mat.blend_method = 'BLEND'

    smoke_count = 0
    for wheel in rear_wheels:
        # Create an emitter plane at the wheel position
        wheel_pos = wheel.matrix_world.translation
        bpy.ops.mesh.primitive_plane_add(size=0.3, location=wheel_pos)
        emitter = bpy.context.active_object
        emitter.name = f"{car_parent.name}_smoke_{smoke_count}"
        emitter.hide_render = True
        emitter.parent = wheel
        emitter.matrix_parent_inverse = wheel.matrix_world.inverted()

        # Add particle system
        bpy.context.view_layer.objects.active = emitter
        bpy.ops.object.particle_system_add()
        ps = emitter.particle_systems[0]
        psettings = ps.settings

        psettings.count = 200
        psettings.frame_start = drift_start
        psettings.frame_end = drift_end
        psettings.lifetime = 60
        psettings.emit_from = 'FACE'
        psettings.physics_type = 'NEWTON'
        psettings.mass = 0.01

        # Upward velocity
        if hasattr(psettings, 'normal_factor'):
            psettings.normal_factor = 1.5

        # Render as halo/sphere
        psettings.render_type = 'OBJECT'

        # Create a simple smoke puff sphere
        bpy.ops.mesh.primitive_ico_sphere_add(radius=0.3, location=(200, 200, -50))
        puff = bpy.context.active_object
        puff.name = f"SmokePuff_{smoke_count}"
        puff.data.materials.append(smoke_mat)
        puff.hide_render = True
        puff.hide_viewport = True

        psettings.instance_object = puff
        psettings.particle_size = 0.5
        psettings.size_random = 0.8

        # Fade: use a force field for slight upward drift
        bpy.ops.object.effector_add(type='FORCE', location=wheel_pos)
        turb = bpy.context.active_object
        turb.field.type = 'TURBULENCE'
        turb.field.strength = 2
        turb.field.size = 0.5
        turb.parent = wheel
        turb.matrix_parent_inverse = wheel.matrix_world.inverted()

        smoke_count += 1

    print(f"  Tyre smoke: {smoke_count} emitters, {200 * smoke_count} total particles")


# ============================================================================
# STEP 11: CAMERAS - 3 SHOTS WITH MARKERS
# ============================================================================

def setup_cameras(start_pos, map_center, path_curve):
    """Set up 3 cameras and bind them to frame ranges with markers."""
    print("[STEP 11] Setting up 3 camera shots...")

    cameras = []

    # Camera 1: Low tracking shot beside the cars
    bpy.ops.object.camera_add(location=(start_pos.x - 5, start_pos.y + 5, start_pos.z + 0.5))
    cam1 = bpy.context.active_object
    cam1.name = "CAM_1_LowSide"
    cam1.data.lens = 35
    cam1.data.dof.use_dof = True
    cam1.data.dof.focus_distance = 8
    cam1.data.dof.aperture_fstop = 2.8
    cameras.append(cam1)

    # Camera 2: Front low angle - cars drift toward camera
    bpy.ops.object.camera_add(location=(start_pos.x + 15, start_pos.y + 35, start_pos.z + 0.3))
    cam2 = bpy.context.active_object
    cam2.name = "CAM_2_FrontLow"
    cam2.data.lens = 28
    cam2.data.dof.use_dof = True
    cam2.data.dof.focus_distance = 12
    cam2.data.dof.aperture_fstop = 2.8
    cameras.append(cam2)

    # Camera 3: Wide chase from behind
    bpy.ops.object.camera_add(location=(start_pos.x - 8, start_pos.y - 15, start_pos.z + 3))
    cam3 = bpy.context.active_object
    cam3.name = "CAM_3_Chase"
    cam3.data.lens = 50
    cam3.data.dof.use_dof = True
    cam3.data.dof.focus_distance = 15
    cam3.data.dof.aperture_fstop = 4.0
    cameras.append(cam3)

    # Bind cameras to frame ranges using markers
    scene = bpy.context.scene

    # Clear existing markers
    while scene.timeline_markers:
        scene.timeline_markers.remove(scene.timeline_markers[0])

    # Shot 1: frames 1-89 (camera 1)
    m1 = scene.timeline_markers.new("CAM_1", frame=1)
    m1.camera = cam1

    # Shot 2: frames 90-179 (camera 2)
    m2 = scene.timeline_markers.new("CAM_2", frame=90)
    m2.camera = cam2

    # Shot 3: frames 180-270 (camera 3)
    m3 = scene.timeline_markers.new("CAM_3", frame=180)
    m3.camera = cam3

    # Set cam1 as the active camera initially
    scene.camera = cam1

    # Add handheld shake via keyframes on each camera
    for cam in cameras:
        shake_amp = 0.02
        for f in range(1, TOTAL_FRAMES + 1, 3):
            shake_x = random.uniform(-shake_amp, shake_amp)
            shake_y = random.uniform(-shake_amp, shake_amp)
            # Only keyframe during the camera's active range
            cam_idx = cameras.index(cam)
            frame_ranges = [(1, 89), (90, 179), (180, TOTAL_FRAMES)]
            f_start, f_end = frame_ranges[cam_idx]
            if f_start <= f <= f_end:
                # Store original location and add shake
                base_loc = cam.location.copy()
                cam.location.x += shake_x
                cam.location.y += shake_y
                cam.keyframe_insert(data_path="location", index=0, frame=f)
                cam.keyframe_insert(data_path="location", index=1, frame=f)
                # Reset
                cam.location = base_loc

    print(f"  3 cameras created with markers at frames 1, 90, 180")
    return cameras


# ============================================================================
# STEP 12: RENDER SETTINGS
# ============================================================================

def setup_render(is_test=False):
    """Configure EEVEE render settings."""
    print(f"[STEP 12] Setting up render (test={is_test})...")

    scene = bpy.context.scene

    # Engine
    scene.render.engine = 'BLENDER_EEVEE'

    # Resolution
    scene.render.resolution_x = RESOLUTION_X
    scene.render.resolution_y = RESOLUTION_Y
    if is_test:
        scene.render.resolution_percentage = TEST_SCALE
    else:
        scene.render.resolution_percentage = 100

    # FPS
    scene.render.fps = FPS

    # Frame range
    scene.frame_start = 1
    scene.frame_end = TOTAL_FRAMES if not is_test else min(150, TOTAL_FRAMES)  # test: 5 seconds

    # Output
    if is_test:
        scene.render.filepath = TEST_RENDER_PATH
    else:
        scene.render.filepath = FINAL_RENDER_PATH

    # Output format
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.constant_rate_factor = 'MEDIUM' if not is_test else 'LOW'
    scene.render.ffmpeg.audio_codec = 'AAC'

    # EEVEE settings
    eevee = scene.eevee

    # Try Blender 5.0 property names
    # Motion blur
    eevee.use_motion_blur = True
    if hasattr(eevee, 'motion_blur_position'):
        eevee.motion_blur_position = 'START'
    if hasattr(eevee, 'motion_blur_shutter'):
        eevee.motion_blur_shutter = 0.5

    # Bloom (called "Bloom" in older EEVEE, check for it)
    if hasattr(eevee, 'use_bloom'):
        eevee.use_bloom = True
        eevee.bloom_intensity = 0.15
        eevee.bloom_threshold = 0.8
    elif hasattr(eevee, 'use_gtao') or hasattr(scene, 'view_settings'):
        # In Blender 5.0, bloom may be a compositor node or different
        pass

    # Soft shadows
    eevee.use_soft_shadows = True if hasattr(eevee, 'use_soft_shadows') else False

    # Volumetrics
    if hasattr(eevee, 'use_volumetric'):
        eevee.use_volumetric = True
        eevee.volumetric_start = 0.1
        eevee.volumetric_end = 100
        if hasattr(eevee, 'volumetric_tile_size'):
            eevee.volumetric_tile_size = '8'

    # Samples
    if hasattr(eevee, 'taa_render_samples'):
        eevee.taa_render_samples = 32 if not is_test else 8
    elif hasattr(scene, 'eevee'):
        if hasattr(eevee, 'samples'):
            eevee.samples = 32 if not is_test else 8

    # Denoising
    if hasattr(eevee, 'use_denoising'):
        eevee.use_denoising = True

    # Raytracing - try to enable if available
    if hasattr(eevee, 'use_raytracing'):
        eevee.use_raytracing = False  # Keep off for performance on GTX 1660

    # Shadow resolution
    if hasattr(eevee, 'shadow_cube_size'):
        eevee.shadow_cube_size = '1024'
    if hasattr(eevee, 'shadow_cascade_size'):
        eevee.shadow_cascade_size = '2048'

    # Color management
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look = 'Medium High Contrast'

    print(f"  EEVEE configured: {RESOLUTION_X}x{RESOLUTION_Y}" +
          f" at {TEST_SCALE}% (test)" if is_test else
          f" EEVEE configured: {RESOLUTION_X}x{RESOLUTION_Y} at 100%")
    print(f"  Motion blur: ON, Denoise: ON, Volumetrics: ON")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    print("=" * 60)
    print("STAGE 1: NIGHT-RAIN DRIFT SCENE")
    print("=" * 60)

    # Set frame range
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = TOTAL_FRAMES
    bpy.context.scene.render.fps = FPS

    # Step 1: Clear scene
    clear_scene()

    # Step 2: Import map
    map_root, all_map_meshes = import_map()

    # Step 3: Import BMW
    car_bmw = import_bmw()

    # Step 4: Import Mercedes
    car_merc = import_mercedes()

    # Step 5: Find road and place cars
    start_pos, map_center, map_size = find_road_and_place(map_root, all_map_meshes, car_bmw, car_merc)

    # Step 6: Night world
    setup_night_world()

    # Step 7: Wet asphalt
    make_wet_roads(all_map_meshes)

    # Step 8: Volumetric fog
    setup_fog()

    # Step 9: Set up cameras first (needed for rain parenting)
    cameras = setup_cameras(start_pos, map_center, None)
    main_camera = cameras[0]

    # Step 10: Rain
    setup_rain(main_camera)

    # Step 11: Car lights
    setup_car_lights(car_bmw, is_bmw=True)
    setup_car_lights(car_merc, is_bmw=False)

    # Step 12: Drive path
    path_curve = create_drive_path(start_pos, map_center, map_size)

    # Step 13: Animate cars
    drift_info = animate_cars_on_path(car_bmw, car_merc, path_curve, start_pos)

    # Step 14: Tyre smoke for each car
    for car, drift_empty, ds, de in drift_info:
        setup_tyre_smoke(car, ds, de)

    # Step 15: Render settings (full)
    setup_render(is_test=False)

    # Step 16: Save .blend
    os.makedirs(os.path.dirname(BLEND_FILE), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_FILE)
    print(f"\n[SAVED] .blend file: {BLEND_FILE}")

    # Print animation summary
    print("\n" + "=" * 60)
    print("ANIMATION SUMMARY")
    print("=" * 60)

    animated_objects = []
    for obj in bpy.data.objects:
        if obj.animation_data and obj.animation_data.action:
            action = obj.animation_data.action
            channels = []
            for fc in get_action_fcurves(action):
                ch_name = fc.data_path
                if fc.array_index > 0 and fc.data_path == 'rotation_euler':
                    axis = ['X', 'Y', 'Z'][fc.array_index]
                    ch_name = f"rotation_{axis}"
                elif fc.data_path == 'location':
                    axis = ['X', 'Y', 'Z'][fc.array_index]
                    ch_name = f"location_{axis}"
                channels.append(ch_name)
            frame_range = (int(action.frame_range[0]), int(action.frame_range[1]))
            animated_objects.append((obj.name, channels, frame_range))

    for name, channels, fr in animated_objects:
        print(f"  {name}: {channels} (frames {fr[0]}-{fr[1]})")

    print(f"\n  Camera markers: CAM_1@f1, CAM_2@f90, CAM_3@f180")
    print(f"  BMW drift: f{DRIFT_START_FRAME}-f{DRIFT_END_FRAME}")
    print(f"  MERC drift: f{DRIFT_START_FRAME+5}-f{DRIFT_END_FRAME+3}")
    print(f"  Total frames: {TOTAL_FRAMES} ({TOTAL_FRAMES/FPS:.1f}s at {FPS}fps)")

    print("\n" + "=" * 60)
    print("READY FOR TEST RENDER")
    print(f"  Test: {TEST_RENDER_DIR}")
    print(f"  Final: {FINAL_RENDER_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()

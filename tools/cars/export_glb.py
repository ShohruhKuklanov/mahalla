# Game export of the coupe: modifiers applied, body decimated, one node per wheel (origin at the hub), the rest joined.
import bpy, sys
src, out, ratio = sys.argv[-3], sys.argv[-2], float(sys.argv[-1])
bpy.ops.wm.open_mainfile(filepath=src)
for o in list(bpy.data.objects):
    if o.type != 'MESH' or any(c.name == 'Studio' for c in o.users_collection): bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action='SELECT'); bpy.context.view_layer.objects.active = bpy.data.objects[0]
bpy.ops.object.convert(target='MESH')                       # apply all modifiers
def decimate(o, r):
    m = o.modifiers.new('dec', 'DECIMATE'); m.ratio = r
    bpy.context.view_layer.objects.active = o; bpy.ops.object.modifier_apply(modifier='dec')
for o in bpy.data.objects:
    if any(c.name == 'Body' for c in o.users_collection) and len(o.data.polygons) > 20000: decimate(o, ratio)
    elif o.name.startswith(('Wheel_F', 'Wheel_R')) and len(o.data.polygons) > 2000: decimate(o, 0.45)
    elif o.name.startswith('Tyre_'): decimate(o, 0.5)
    elif len(o.data.polygons) > 500: decimate(o, 0.4)
def join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]; bpy.ops.object.join(); j = bpy.context.view_layer.objects.active; j.name = name; return j
for w in ('FL', 'FR', 'RL', 'RR'):
    parts = [o for o in bpy.data.objects if o.name.split('.')[0].endswith('_' + w) and o.name.split('.')[0].split('_')[0] in ('Tyre', 'Wheel', 'Lug', 'Brake') and 'Caliper' not in o.name]
    hub = bpy.data.objects['Tyre_' + w].matrix_world.translation.copy()
    j = join(parts, 'Wheel_' + w)
    bpy.context.scene.cursor.location = hub
    bpy.ops.object.select_all(action='DESELECT'); j.select_set(True); bpy.context.view_layer.objects.active = j
    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
rest = [o for o in bpy.data.objects if not o.name.startswith('Wheel_') or len(o.name) > 8]
rest = [o for o in rest if o.name not in ('Wheel_FL', 'Wheel_FR', 'Wheel_RL', 'Wheel_RR')]
join(rest, 'Car')
bpy.context.scene.cursor.location = (0, 0, 0)
print('faces', sum(len(o.data.polygons) for o in bpy.data.objects), [o.name for o in bpy.data.objects])
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_apply=True, export_yup=True, export_cameras=False, export_lights=False, export_texcoords=False, export_normals=True)

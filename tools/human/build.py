# Susambil people: realistic MakeHuman (MPFB, CC0) bodies with clothes, hair, a baked skin texture, the game-engine
# (Unreal-style) skeleton and idle / walk / run animations, exported as GLB for Babylon.
# usage: python3.11 build.py <male|female> <out.glb> [preview.png]
import os, sys, math
exec(open('/home/claude/human/common.py').read())
from mathutils import Matrix, Quaternion, Vector
from PIL import Image, ImageFilter, ImageChops
import numpy as np

KIND, OUT = sys.argv[1], sys.argv[2]
PREVIEW = sys.argv[3] if len(sys.argv) > 3 else None
TEX = '/home/claude/makehumancommunity/mpfb2/src/mpfb/data/textures/'
WORK = '/home/claude/human/'

for o in list(bpy.data.objects): bpy.data.objects.remove(o)

# ---------- body ----------
print('STEP h = HumanService.cre', flush=True); h = HumanService.create_human()
P = dict(male=dict(gender=1.0, age=0.52, muscle=0.62, weight=0.52, height=0.6, asian=0.35, caucasian=0.65, african=0.0),
         female=dict(gender=0.0, age=0.48, muscle=0.48, weight=0.48, height=0.45, asian=0.35, caucasian=0.65, african=0.0))[KIND]
for k, v in P.items(): HOP.set_value(k, v, entity_reference=h)
TargetService.reapply_macro_details(h)
bpy.context.view_layer.objects.active = h; h.select_set(True)
if h.data.shape_keys:
    bpy.ops.object.shape_key_remove(all=True, apply_mix=True)
print('STEP rig = HumanService.a', flush=True); rig = HumanService.add_builtin_rig(h, 'game_engine')
rig.name = 'Rig'; h.name = 'Body'

me = h.data
vg = {g.name: g.index for g in h.vertex_groups}
BONES = [b.name for b in rig.data.bones]
def dominant(v):
    best, bw = None, 0.0
    for g in v.groups:
        n = h.vertex_groups[g.group].name
        if n in BONES and g.weight > bw: best, bw = n, g.weight
    return best
def in_group(v, name):
    gi = vg.get(name); return gi is not None and any(g.group == gi and g.weight > 0.5 for g in v.groups)
print('STEP vdom = [', flush=True); vdom = [dominant(v) for v in me.vertices]
vgrp = []
for v in me.vertices:
    tag = 'body'
    for n in ('helper-tights', 'helper-hair', 'helper-l-eye', 'helper-r-eye', 'helper-skirt'):
        if in_group(v, n): tag = n; break
    else:
        if not in_group(v, 'body'): tag = 'junk'
    vgrp.append(tag)

LONG = KIND == 'female'
PANTS = {'pelvis', 'thigh_l', 'thigh_r', 'calf_l', 'calf_r'}
SHIRT = {'spine_01', 'spine_02', 'spine_03', 'clavicle_l', 'clavicle_r', 'upperarm_l', 'upperarm_r'} | ({'lowerarm_l', 'lowerarm_r'} if LONG else set())
FEET = {'foot_l', 'foot_r', 'ball_l', 'ball_r'}

# materials: 0 skin, 1 shirt, 2 pants, 3 shoes, 4 hair, 5 eyes
def mat(name, col, rough, tex=None):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']; b.inputs['Base Color'].default_value = (*col, 1); b.inputs['Roughness'].default_value = rough
    if tex:
        t = m.node_tree.nodes.new('ShaderNodeTexImage'); t.image = bpy.data.images.load(tex); m.node_tree.links.new(t.outputs['Color'], b.inputs['Base Color'])
    return m
def lin(hexs): c = [int(hexs[i:i+2], 16)/255 for i in (1, 3, 5)]; return tuple(((x + 0.055)/1.055)**2.4 if x > 0.04045 else x/12.92 for x in c)

# baked skin: warm tan base, a little blotchy noise, redder lips, darker lids, paler nails
print('STEP S = 1024', flush=True); S = 1024
def mask(f): return np.asarray(Image.open(TEX + f).convert('L').resize((S, S)), dtype=np.float32)/255
base = np.array([197, 146, 112], np.float32) if KIND == 'male' else np.array([214, 165, 132], np.float32)
rng = np.random.default_rng(3)
noise = np.asarray(Image.fromarray((rng.random((S//8, S//8))*255).astype(np.uint8)).resize((S, S), Image.BICUBIC), np.float32)/255 - 0.5
sk = np.ones((S, S, 3), np.float32) * base * (1 + 0.06*noise[..., None])
lips, lids, nails, face = mask('mpfb_lips.jpg'), mask('mpfb_eyelids.jpg'), mask('mpfb_fingernails.jpg'), mask('mpfb_face.jpg')
sk = sk*(1 - 0.75*lips[..., None]) + np.array([172, 92, 88], np.float32)*0.75*lips[..., None]
sk *= (1 - 0.18*lids[..., None]); sk = sk*(1 - 0.5*nails[..., None]) + np.array([228, 190, 178], np.float32)*0.5*nails[..., None]
sk *= (1 + 0.03*face[..., None])
skin_png = WORK + f'skin_{KIND}.png'; Image.fromarray(np.clip(sk, 0, 255).astype(np.uint8)).save(skin_png)

M = [mat('Skin', (1, 1, 1), 0.5, skin_png), mat('Shirt', lin('#ffffff'), 0.85), mat('Pants', lin('#2c3e5c'), 0.8),
     mat('Shoes', lin('#1c1c1e'), 0.45), mat('Hair', lin('#1d1410' if KIND == 'male' else '#2a1a12'), 0.55), mat('Eyes', lin('#2b1d14'), 0.15), mat('Sclera', lin('#e8e2da'), 0.2)]
me.materials.clear()
for m in M: me.materials.append(m)

# assign / delete faces
print('STEP import bmesh', flush=True)
HB = rig.data.bones['head'].head_local
ZTOP = max(v.co.z for v in me.vertices if vgrp[v.index] == 'body')
HEADF = min(v.co.y for v in me.vertices if vgrp[v.index] == 'body' and v.co.z > ZTOP - 0.18)   # nose tip (front = -Y)
def hair_keep(vs):
    if KIND == 'male': return False                       # men: the hair is a solid cap grown from the scalp
    z = sum(v.co.z for v in vs)/len(vs); y = sum(v.co.y for v in vs)/len(vs)
    return y > HB.y - 0.01 and z > ZTOP - 0.36            # women: long hair falling down the back, no fringe
def scalp(vs):
    z = sum(v.co.z for v in vs)/len(vs); y = sum(v.co.y for v in vs)/len(vs)
    t = min(1.0, max(0.0, (y - (HEADF + 0.03)) / ((HB.y + 0.05) - (HEADF + 0.03))))
    return z > ZTOP - (0.062 + t*(0.11 if KIND == 'male' else 0.12))

import bmesh
bm = bmesh.new(); bm.from_mesh(me); bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
kill = []
for f in bm.faces:
    tags = {vgrp[v.index] for v in f.verts}; doms = [vdom[v.index] for v in f.verts]
    t = next(iter(tags)) if len(tags) == 1 else 'mixed'
    if t == 'helper-tights':
        if all(d in PANTS for d in doms): f.material_index = 2
        elif all(d in SHIRT for d in doms): f.material_index = 1
        elif all(d in PANTS | SHIRT for d in doms): f.material_index = 1 if sum(d in SHIRT for d in doms) >= sum(d in PANTS for d in doms) else 2
        else: kill.append(f)
    elif t == 'helper-hair':
        if hair_keep(f.verts): f.material_index = 4
        else: kill.append(f)
    elif t in ('helper-l-eye', 'helper-r-eye'):
        f.material_index = 5 if f.normal.y < -0.80 else 6
    elif t == 'body':
        if all(d in PANTS | SHIRT for d in doms): kill.append(f)            # hidden under the clothes
        elif all(d in FEET for d in doms): f.material_index = 3              # the shoes are the feet, darkened and glossy
        else: f.material_index = 4 if scalp(f.verts) else 0
    else: kill.append(f)
bmesh.ops.delete(bm, geom=kill, context='FACES')
# inflate clothes and shoes a little so no skin pokes through
for v in bm.verts:
    mats = {f.material_index for f in v.link_faces}
    if mats & {1, 2}: v.co += v.normal * 0.006
    elif mats == {3}: v.co += v.normal * 0.004
    elif 4 in mats and not (mats & {0}): v.co += v.normal * (0.007 if KIND == 'male' else 0.005)
bm.to_mesh(me); bm.free()
# drop the helper vertex groups (keep the bone weights only)
for g in list(h.vertex_groups):
    if g.name not in BONES: h.vertex_groups.remove(g)
# lighter for crowds: collapse to about 9k triangles
bpy.context.view_layer.objects.active = h
print('STEP dec = h.modifiers', flush=True); dec = h.modifiers.new('dec', 'DECIMATE'); dec.ratio = 0.42
bpy.ops.object.modifier_move_to_index(modifier='dec', index=0); bpy.ops.object.modifier_apply(modifier='dec')
bpy.ops.object.shade_smooth()
print('tris', sum(len(p.vertices) - 2 for p in me.polygons))

# ---------- animations ----------
# Armature axes: +X = the character's left, -Y = forward, +Z = up.
# Every bone is driven by its world (armature-space) rotation delta D; the local pose is L = R^-1 Dp^-1 D R.
bpy.context.view_layer.objects.active = rig; bpy.ops.object.mode_set(mode='POSE')
REST = {b.name: b.matrix_local.to_quaternion() for b in rig.data.bones}
RDIR = {b.name: (b.tail_local - b.head_local).normalized() for b in rig.data.bones}
PARENT = {b.name: (b.parent.name if b.parent else None) for b in rig.data.bones}
ORDER = [b.name for b in rig.data.bones]          # parents come before children
def Rx(d): return Quaternion((1, 0, 0), math.radians(d))
def Ry(d): return Quaternion((0, 1, 0), math.radians(d))
def Rz(d): return Quaternion((0, 0, 1), math.radians(d))
I = Quaternion()
KEYED = ['pelvis', 'spine_01', 'spine_02', 'spine_03', 'neck_01', 'head', 'clavicle_l', 'clavicle_r', 'upperarm_l', 'upperarm_r',
         'lowerarm_l', 'lowerarm_r', 'hand_l', 'hand_r', 'thigh_l', 'thigh_r', 'calf_l', 'calf_r', 'foot_l', 'foot_r', 'ball_l', 'ball_r']
def aim(D, bone, target):
    """world delta that turns `bone` (already carried by its parent delta D) to point along target"""
    cur = D @ RDIR[bone]
    return cur.rotation_difference(target.normalized()) @ D
def apply(frame, W, bob=0.0):
    D = {}
    for bn in ORDER:
        p = PARENT[bn]; Dp = D.get(p, I) if p else I
        D[bn] = W.get(bn, Dp)
        if bn in KEYED:
            pb = rig.pose.bones[bn]; pb.rotation_mode = 'QUATERNION'
            r = REST[bn]; pb.rotation_quaternion = r.inverted() @ Dp.inverted() @ D[bn] @ r
            pb.keyframe_insert('rotation_quaternion', frame=frame)
    pb = rig.pose.bones['pelvis']; pb.location = REST['pelvis'].to_matrix().inverted() @ Vector((0, 0, bob)); pb.keyframe_insert('location', frame=frame)
SIDE = 0.13 if KIND == 'male' else 0.10              # hands hang slightly away from the hips
def gait(ph, amp, bend, lean, elbow, bob, arm_amp, breath=0.0):
    s = math.sin(2*math.pi*ph); c = math.cos(2*math.pi*ph)
    tw = 5*s*(amp/30)
    W = {}
    W['pelvis'] = Rz(tw)
    W['spine_01'] = Rz(tw*0.5) @ Rx(lean*0.4)
    W['spine_02'] = Rz(-tw*0.2) @ Rx(lean*0.75)
    W['spine_03'] = Rz(-tw*0.6) @ Rx(lean + breath)
    W['neck_01'] = Rz(-tw*0.3) @ Rx(lean*0.4)
    W['head'] = Rz(-tw*0.1) @ Rx(-breath*0.5)
    for side, sg in (('l', 1), ('r', -1)):
        sw = amp*s*sg                                   # + = this leg in front
        ph_side = 2*math.pi*ph + (0 if sg > 0 else math.pi)
        knee = bend*max(0.0, math.cos(ph_side + 0.5))**2 + 3 + 6*max(0.0, math.sin(ph_side - 2.0))*(bend/42)
        W['thigh_' + side] = Rx(-sw)
        W['calf_' + side] = Rx(knee - sw)
        W['foot_' + side] = Rx(-0.35*sw + 0.25*max(0.0, -sw) * (1 if knee > 20 else 0))
        W['ball_' + side] = W['foot_' + side]
        # arms swing opposite to the leg on the same side
        asw = -arm_amp*s*sg
        Dc = W['spine_03']
        up_t = Rx(asw) @ Vector((sg*SIDE, 0.04, -1))
        W['upperarm_' + side] = aim(Dc, 'upperarm_' + side, Dc @ up_t)
        el = elbow + (10 if asw < 0 else 2) * abs(math.sin(ph_side)) * (arm_amp/18)
        lo_t = Rx(-el) @ up_t
        W['lowerarm_' + side] = aim(W['upperarm_' + side], 'lowerarm_' + side, Dc @ lo_t)
        W['hand_' + side] = aim(W['lowerarm_' + side], 'hand_' + side, Dc @ (Rx(-el - 4) @ up_t))
    return W, bob*(abs(c) - 1)
def make_action(name, frames, fn):
    act = bpy.data.actions.new(name); rig.animation_data_create(); rig.animation_data.action = act
    for f in range(frames + 1):
        W, bob = fn(f/frames); apply(f + 1, W, bob)
    act.use_fake_user = True
    tr = rig.animation_data.nla_tracks.new(); tr.name = name; tr.strips.new(name, 1, act); rig.animation_data.action = None
    return act
print('STEP anim', flush=True)
make_action('walk', 32, lambda t: gait(t, 22, 42, 3, 14, 0.022, 18))
make_action('run', 20, lambda t: gait(t, 36, 80, 9, 72, 0.045, 26))
make_action('idle', 90, lambda t: gait(0, 0, 0, 0, 8, 0, 0, breath=1.5*math.sin(2*math.pi*t)))
bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.scene.render.fps = 30

# ---------- optional preview render (side and front, walk mid-stride) ----------
print('STEP if PREVIEW:', flush=True)

if PREVIEW:
    sc = bpy.context.scene; sc.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items] else 'CYCLES'
    if sc.render.engine == 'CYCLES': sc.cycles.samples = 24
    sc.render.resolution_x, sc.render.resolution_y = 900, 900
    rig.animation_data.action = bpy.data.actions['walk']; sc.frame_set(9)
    w = bpy.data.worlds.new('w'); w.use_nodes = True; w.node_tree.nodes['Background'].inputs[0].default_value = (0.75, 0.8, 0.85, 1); w.node_tree.nodes['Background'].inputs[1].default_value = 0.9; sc.world = w
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN')); sun.data.energy = 3.5; sun.rotation_euler = (math.radians(50), 0, math.radians(30)); sc.collection.objects.link(sun)
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam; cam.data.lens = 60
    for i, (pos, rot) in enumerate([((3.6, -0.0, 1.0), (math.radians(88), 0, math.radians(90))), ((0.9, -3.4, 1.05), (math.radians(87), 0, math.radians(15)))]):
        cam.location = pos; cam.rotation_euler = rot
        sc.render.filepath = PREVIEW.replace('.png', f'_{i}.png'); bpy.ops.render.render(write_still=True)
    rig.animation_data.action = None

# ---------- export ----------
for o in bpy.data.objects:
    o.select_set(o.name in ('Body', 'Rig'))
print('STEP bpy.ops.export_scene', flush=True); bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB', use_selection=True, export_animations=True, export_animation_mode='NLA_TRACKS',
                          export_skins=True, export_apply=False, export_yup=True, export_image_format='JPEG', export_jpeg_quality=85, export_morph=False)
print('exported', OUT, os.path.getsize(OUT))
os._exit(0)

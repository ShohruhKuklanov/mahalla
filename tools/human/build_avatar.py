# Susambil player avatars: a customisable MakeHuman (MPFB, CC0) body for the avatar editor and the person you walk.
# Unlike the crowd bodies (build.py) these keep full resolution and carry everything the editor switches or tints:
#   morph targets   face_round/square/long/heart/diamond/triangle/rect/full/lean/chin, nose_narrow/wide/long, mouth_small/wide/full, eyes_big/small
#   hair            Hair (short cap) · HairMid (to the collar) · HairLong (to the shoulders) · HairBun
#   brows           BrowThin · BrowNormal · BrowThick · BrowArched · BrowStraight · BrowAngled · BrowBushy · BrowShort · BrowUni
#   beard           BeardStubble · Mustache · BeardGoatee · BeardShort · BeardFull · BeardLong (shells of the face skin, so they follow the face shapes)
#   clothes         Shirt · Sleeve · PantsTop · PantsLow · Skirt · Jacket · Shoes
#   accessories     GlassesRound · GlassesSquare · GlassesSun + Lens · HatDoppi + HatDoppiPattern · HatCap · HatWide
# plus Skin (baked texture, tinted per player), Eyes (iris, tinted) and Sclera; and the idle / walk / run actions.
# usage: python3.11 build_avatar.py <m|f|n> <out.glb>
import os, sys, math
exec(open('/home/claude/human/common.py').read())
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree
from PIL import Image, ImageDraw
import numpy as np
import bmesh

KIND, OUT = sys.argv[1], sys.argv[2]
TEX = '/home/claude/makehumancommunity/mpfb2/src/mpfb/data/textures/'
TGT = '/home/claude/makehumancommunity/mpfb2/src/mpfb/data/targets/'
WORK = '/home/claude/human/'
for o in list(bpy.data.objects): bpy.data.objects.remove(o)

# ---------- body ----------
h = HumanService.create_human()
P = dict(m=dict(gender=1.0, age=0.5, muscle=0.58, weight=0.5, height=0.58, asian=0.35, caucasian=0.65, african=0.0),
         f=dict(gender=0.0, age=0.48, muscle=0.48, weight=0.48, height=0.45, asian=0.35, caucasian=0.65, african=0.0),
         n=dict(gender=0.5, age=0.48, muscle=0.5, weight=0.47, height=0.52, asian=0.35, caucasian=0.65, african=0.0))[KIND]
for k, v in P.items(): HOP.set_value(k, v, entity_reference=h)
TargetService.reapply_macro_details(h)
bpy.context.view_layer.objects.active = h; h.select_set(True)
if h.data.shape_keys: bpy.ops.object.shape_key_remove(all=True, apply_mix=True)

# ---------- face morphs (each one a mix of MakeHuman targets) ----------
h.shape_key_add(name='Basis', from_mix=False)
MORPHS = {
    'face_round':  [('head/head-round', 1.0)],
    'face_square': [('head/head-square', 1.0)],
    'face_long':   [('head/head-oval', 0.6), ('head/head-scale-vert-incr', 0.5)],
    'face_heart':  [('head/head-invertedtriangular', 1.0)],
    'face_diamond':  [('head/head-diamond', 1.0)],
    'face_triangle': [('head/head-triangular', 1.0), ('chin/chin-width-incr', 0.4)],
    'face_rect':     [('head/head-rectangular', 1.0)],
    'face_full':     [('head/head-fat-incr', 0.9), ('cheek/l-cheek-volume-incr', 0.8), ('cheek/r-cheek-volume-incr', 0.8)],
    'face_lean':     [('head/head-fat-decr', 0.9), ('cheek/l-cheek-volume-decr', 0.8), ('cheek/r-cheek-volume-decr', 0.8), ('cheek/l-cheek-bones-incr', 0.6), ('cheek/r-cheek-bones-incr', 0.6)],
    'face_chin':     [('chin/chin-prominent-incr', 0.8), ('chin/chin-width-incr', 0.6), ('chin/chin-bones-incr', 0.5), ('chin/chin-height-incr', 0.4)],
    'nose_narrow': [('nose/nose-scale-horiz-decr', 0.8), ('nose/nose-nostrils-width-decr', 0.5)],
    'nose_wide':   [('nose/nose-scale-horiz-incr', 0.8), ('nose/nose-flaring-incr', 0.6)],
    'nose_long':   [('nose/nose-scale-vert-incr', 0.8)],
    'mouth_small': [('mouth/mouth-scale-horiz-decr', 0.8)],
    'mouth_wide':  [('mouth/mouth-scale-horiz-incr', 0.9)],
    'mouth_full':  [('mouth/mouth-upperlip-volume-incr', 0.9), ('mouth/mouth-lowerlip-volume-incr', 0.9)],
    'eyes_big':    [('eyes/l-eye-scale-incr', 0.8), ('eyes/r-eye-scale-incr', 0.8)],
    'eyes_small':  [('eyes/l-eye-scale-decr', 0.6), ('eyes/r-eye-scale-decr', 0.6)],
}
for name, parts in MORPHS.items():
    tmp = [TargetService.load_target(h, TGT + p + '.target.gz', weight=w, name=f'tmp{i}') for i, (p, w) in enumerate(parts)]
    k = h.shape_key_add(name=name, from_mix=True); k.value = 0.0
    for t in tmp: h.shape_key_remove(t)
print('morphs', [k.name for k in h.data.shape_keys.key_blocks], flush=True)

rig = HumanService.add_builtin_rig(h, 'game_engine'); rig.name = 'Rig'; h.name = 'Body'
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
vdom = [dominant(v) for v in me.vertices]
vgrp = []
for v in me.vertices:
    tag = 'body'
    for n in ('helper-tights', 'helper-hair', 'helper-l-eye', 'helper-r-eye', 'helper-skirt'):
        if in_group(v, n): tag = n; break
    else:
        if not in_group(v, 'body'): tag = 'junk'
    vgrp.append(tag)

TORSO = {'spine_01', 'spine_02', 'spine_03', 'clavicle_l', 'clavicle_r', 'upperarm_l', 'upperarm_r'}
FORE = {'lowerarm_l', 'lowerarm_r'}
HIPS = {'pelvis', 'thigh_l', 'thigh_r'}
CALF = {'calf_l', 'calf_r'}
FEET = {'foot_l', 'foot_r', 'ball_l', 'ball_r'}

def lin(hexs): c = [int(hexs[i:i+2], 16)/255 for i in (1, 3, 5)]; return tuple(((x + 0.055)/1.055)**2.4 if x > 0.04045 else x/12.92 for x in c)
def mat(name, col, rough, tex=None, alpha=False):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']; b.inputs['Base Color'].default_value = (*col, 1); b.inputs['Roughness'].default_value = rough
    if tex:
        t = m.node_tree.nodes.new('ShaderNodeTexImage'); t.image = bpy.data.images.load(tex); m.node_tree.links.new(t.outputs['Color'], b.inputs['Base Color'])
        if alpha: m.node_tree.links.new(t.outputs['Alpha'], b.inputs['Alpha']); m.blend_method = 'CLIP' if hasattr(m, 'blend_method') else None
    return m

# skin: one neutral mid tone, tinted per player in the game
S = 1024
def mask(f): return np.asarray(Image.open(TEX + f).convert('L').resize((S, S)), dtype=np.float32)/255
base = np.array([252, 232, 220], np.float32)
rng = np.random.default_rng(3)
noise = np.asarray(Image.fromarray((rng.random((S//8, S//8))*255).astype(np.uint8)).resize((S, S), Image.BICUBIC), np.float32)/255 - 0.5
sk = np.ones((S, S, 3), np.float32) * base * (1 + 0.05*noise[..., None])
lips, lids, nails, face = mask('mpfb_lips.jpg'), mask('mpfb_eyelids.jpg'), mask('mpfb_fingernails.jpg'), mask('mpfb_face.jpg')
sk = sk*(1 - 0.7*lips[..., None]) + np.array([226, 150, 150], np.float32)*0.7*lips[..., None]
sk *= (1 - 0.12*lids[..., None]); sk = sk*(1 - 0.5*nails[..., None]) + np.array([255, 236, 230], np.float32)*0.5*nails[..., None]
skin_png = WORK + 'skin_avatar.jpg'; Image.fromarray(np.clip(sk, 0, 255).astype(np.uint8)).save(skin_png, quality=88)

# beard: a fine light grain (tinted per player) and, for stubble, a dotted alpha
BS = 512
g = np.asarray(Image.fromarray((rng.random((BS//4, BS//4))*255).astype(np.uint8)).resize((BS, BS), Image.BILINEAR), np.float32)/255
fine = rng.random((BS, BS)).astype(np.float32)
bt = np.clip(0.78 + 0.22*(0.6*g + 0.4*fine), 0, 1)
beard_png = WORK + 'beard_avatar.jpg'; Image.fromarray((bt*255).astype(np.uint8)).convert('RGB').save(beard_png, quality=70)
dots = (fine > 0.55).astype(np.uint8)*255
stub_png = WORK + 'stubble_avatar.png'; Image.fromarray(np.dstack([np.full((BS, BS), 242, np.uint8), dots]), 'LA').save(stub_png, optimize=True)
NAMES = ['Skin', 'Shirt', 'Sleeve', 'PantsTop', 'PantsLow', 'Shoes', 'Hair', 'Eyes', 'Sclera', 'HairMid', 'HairLong', 'Skirt', 'Jacket',
         'BeardStubble', 'Mustache', 'BeardGoatee', 'BeardShort', 'BeardFull']
COL = {'Shirt': '#f2f0ea', 'Sleeve': '#f2f0ea', 'PantsTop': '#2c3e5c', 'PantsLow': '#2c3e5c', 'Shoes': '#1c1c1e', 'Hair': '#2a1d15', 'Eyes': '#3b2a1e',
       'Sclera': '#e8e2da', 'HairMid': '#2a1d15', 'HairLong': '#2a1d15', 'Skirt': '#5a3a6e', 'Jacket': '#3a4a5c'}
MI = {n: i for i, n in enumerate(NAMES)}
me.materials.clear()
BEARDS = ('BeardStubble', 'Mustache', 'BeardGoatee', 'BeardShort', 'BeardFull')
for n in NAMES:
    if n == 'Skin': me.materials.append(mat(n, (1, 1, 1), 0.5, skin_png))
    elif n == 'BeardStubble': me.materials.append(mat(n, lin('#2a1d15'), 0.9, stub_png, alpha=True))
    elif n in BEARDS: me.materials.append(mat(n, lin('#2a1d15'), 0.92, beard_png))
    else: me.materials.append(mat(n, lin(COL[n]), 0.15 if n in ('Eyes', 'Sclera') else 0.8))

# head landmarks (before editing)
HB = rig.data.bones['head'].head_local
ZTOP = max(v.co.z for v in me.vertices if vgrp[v.index] == 'body')
HEADF = min(v.co.y for v in me.vertices if vgrp[v.index] == 'body' and v.co.z > ZTOP - 0.18)
HEADB = max(v.co.y for v in me.vertices if vgrp[v.index] == 'body' and v.co.z > ZTOP - 0.1)
def centroid(tag):
    vs = [v.co for v in me.vertices if vgrp[v.index] == tag]; c = sum(vs, Vector())/len(vs)
    return c, min(v.y for v in vs)
EYE_L, EYE_LF = centroid('helper-l-eye'); EYE_R, EYE_RF = centroid('helper-r-eye')
HEAD_HW = max(abs(v.co.x) for v in me.vertices if vgrp[v.index] == 'body' and abs(v.co.z - (EYE_L.z + 0.01)) < 0.015 and v.co.y > HEADF and v.co.y < HEADB)
# the face profile down the middle: nose tip, under the nose, chin
prof = []
for i in range(80):
    z = EYE_L.z - 0.01 - i*0.002
    fr = [v.co.y for v in me.vertices if vgrp[v.index] == 'body' and abs(v.co.x) < 0.006 and abs(v.co.z - z) < 0.0025 and v.co.y < HB.y]
    if fr: prof.append((z, min(fr)))
tip = min((p for p in prof if EYE_L.z - 0.075 < p[0] < EYE_L.z - 0.02), key=lambda p: p[1])
NOSE_Z, NOSE_Y = tip
NOSE_BASE = next(z for z, y in prof if z < NOSE_Z and y > NOSE_Y + 0.009)
CHIN_Z = None
for (z0, y0), (z1, y1) in zip(prof, prof[1:]):
    if z0 < NOSE_Z - 0.035 and y1 - y0 > 0.02: CHIN_Z = z0; break
CHIN_Y = min(y for z, y in prof if CHIN_Z <= z <= CHIN_Z + 0.03)
print('profile nose', round(NOSE_Z, 3), 'base', round(NOSE_BASE, 3), 'chin', round(CHIN_Z, 3), round(CHIN_Y, 3), flush=True)
print('head', round(ZTOP, 3), 'eyes', tuple(round(x, 3) for x in EYE_L), 'hw', round(HEAD_HW, 3), flush=True)

def scalp(vs):
    z = sum(v.co.z for v in vs)/len(vs); y = sum(v.co.y for v in vs)/len(vs)
    t = min(1.0, max(0.0, (y - (HEADF + 0.03)) / ((HB.y + 0.05) - (HEADF + 0.03))))
    return z > ZTOP - (0.062 + t*0.115)
def hair_part(vs):
    """helper hair strands: none in front of the ears; to the collar (Mid) and on down to the shoulders (Long)"""
    z = sum(v.co.z for v in vs)/len(vs); y = sum(v.co.y for v in vs)/len(vs)
    if y < HB.y - 0.01 and z < ZTOP - 0.05: return None
    if z > ZTOP - 0.24: return 'HairMid'
    if z > ZTOP - 0.36: return 'HairLong'
    return None

bm = bmesh.new(); bm.from_mesh(me); bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
kill, shirtish = [], []
for f in bm.faces:
    tags = {vgrp[v.index] for v in f.verts}; doms = [vdom[v.index] for v in f.verts]
    t = next(iter(tags)) if len(tags) == 1 else 'mixed'
    if t == 'helper-tights':
        cnt = lambda S_: sum(d in S_ for d in doms)
        groups = [('Shirt', TORSO), ('Sleeve', FORE), ('PantsTop', HIPS), ('PantsLow', CALF)]
        if not all(d in TORSO | FORE | HIPS | CALF for d in doms): kill.append(f); continue
        best = max(groups, key=lambda g: cnt(g[1]))[0]
        f.material_index = MI[best]
        if best in ('Shirt', 'Sleeve'): shirtish.append(f)
    elif t == 'helper-skirt': f.material_index = MI['Skirt']
    elif t == 'helper-hair':
        hp = hair_part(f.verts)
        if hp: f.material_index = MI[hp]
        else: kill.append(f)
    elif t in ('helper-l-eye', 'helper-r-eye'):
        f.material_index = MI['Eyes'] if f.normal.y < -0.80 else MI['Sclera']
    elif t == 'body':
        if all(d in TORSO | HIPS for d in doms): kill.append(f)                 # always under a top and trousers
        elif all(d in FEET for d in doms): f.material_index = MI['Shoes']
        else: f.material_index = MI['Hair'] if scalp(f.verts) else MI['Skin']
    else: kill.append(f)
# the jacket: a second, looser layer over the top and sleeves
dup = bmesh.ops.duplicate(bm, geom=shirtish)
jfaces = [g for g in dup['geom'] if isinstance(g, bmesh.types.BMFace)]
for f in jfaces: f.material_index = MI['Jacket']
bmesh.ops.delete(bm, geom=kill, context='FACES')
bm.normal_update()
SHAPES = list(bm.verts.layers.shape.values())
OFF = {MI['Shirt']: 0.006, MI['Sleeve']: 0.006, MI['PantsTop']: 0.006, MI['PantsLow']: 0.007, MI['Skirt']: 0.009, MI['Jacket']: 0.014,
       MI['Shoes']: 0.004, MI['Hair']: 0.007, MI['HairMid']: 0.006, MI['HairLong']: 0.006}
for v in bm.verts:
    mats = {f.material_index for f in v.link_faces}
    if not mats or MI['Skin'] in mats: continue
    off = max(OFF.get(m, 0.0) for m in mats)
    if off:
        d = v.normal * off; v.co += d
        for lay in SHAPES: v[lay] += d            # keep the face morphs from pulling clothes back in
# ---- beards: copies of the face skin, lifted off it ----
uvl = bm.loops.layers.uv.active
MASKS = {k: mask(f) for k, f in (('lips', 'mpfb_lips.jpg'), ('ears', 'mpfb_ears.jpg'), ('lids', 'mpfb_eyelids.jpg'), ('mouth', 'mpfb_inside-mouth.jpg'))}
def mval(f, k):
    u = sum(l[uvl].uv.x for l in f.loops)/len(f.loops); v = sum(l[uvl].uv.y for l in f.loops)/len(f.loops)
    return MASKS[k][min(S - 1, max(0, int((1 - v)*S))), min(S - 1, max(0, int(u*S)))]
skinf = [f for f in bm.faces if f.material_index == MI['Skin']]
lipf = [f for f in skinf if mval(f, 'lips') > 0.5 and f.calc_center_median().y < HB.y - 0.06]
LZ = [f.calc_center_median().z for f in lipf]
MOUTH_TOP, MOUTH_BOT = max(LZ), min(LZ); MOUTH_Z = (MOUTH_TOP + MOUTH_BOT)/2
MOUTH_HW = max(abs(f.calc_center_median().x) for f in lipf)
print('mouth', round(MOUTH_TOP, 3), round(MOUTH_BOT, 3), 'hw', round(MOUTH_HW, 3), flush=True)
def sst(a, b, x): t = min(1.0, max(0.0, (x - a)/(b - a))); return t*t*(3 - 2*t)
def ang(c): return math.degrees(math.atan2(abs(c.x), -(c.y - HB.y)))
def is_must(c):
    ax = abs(c.x); droop = 0.013*sst(MOUTH_HW - 0.006, MOUTH_HW + 0.004, ax)
    return ax < MOUTH_HW + 0.008 and MOUTH_TOP - 0.001 - droop < c.z < NOSE_BASE - 0.002 and c.y < HB.y - 0.06
def is_goatee(c):
    return abs(c.x) < MOUTH_HW*0.85 and CHIN_Z - 0.014 < c.z < MOUTH_BOT - 0.003 and c.y < CHIN_Y + 0.045
def jaw(c, top_front, top_side, a0, a1):
    a = ang(c)
    if a > 100 or c.y > HB.y + 0.005: return False
    top = top_front + (top_side - top_front)*sst(a0, a1, a)
    if not (CHIN_Z - 0.018 < c.z < top): return False
    if c.z < CHIN_Z + 0.004 and c.y > CHIN_Y + 0.05: return False          # only the front of the neck under the chin
    return not is_must(c)
REG = {
    'Mustache':     is_must,
    'BeardGoatee':  is_goatee,
    'BeardShort':   lambda c: jaw(c, MOUTH_Z + 0.004, EYE_L.z - 0.04, 38, 72),
    'BeardFull':    lambda c: jaw(c, NOSE_BASE - 0.004, EYE_L.z - 0.03, 22, 58),
    'BeardStubble': lambda c: is_must(c) or jaw(c, NOSE_BASE - 0.004, EYE_L.z - 0.03, 22, 58),
}
THICK = {'BeardStubble': (0.0011, 0.0), 'Mustache': (0.0034, 0.0), 'BeardGoatee': (0.0050, 0.004), 'BeardShort': (0.0040, 0.002), 'BeardFull': (0.0075, 0.008)}
good = [f for f in skinf if mval(f, 'lips') < 0.3 and mval(f, 'ears') < 0.3 and mval(f, 'lids') < 0.3 and mval(f, 'mouth') < 0.3]
for name, test in REG.items():
    src = [f for f in good if test(f.calc_center_median())]
    dup = bmesh.ops.duplicate(bm, geom=src)
    nf = [g for g in dup['geom'] if isinstance(g, bmesh.types.BMFace)]
    nv = [g for g in dup['geom'] if isinstance(g, bmesh.types.BMVert)]
    for f in nf: f.material_index = MI[name]
    T, chin = THICK[name]
    for v in nv:
        edge = any(e.is_boundary for e in v.link_edges)
        k = 1.0 if name == 'BeardStubble' else (0.3 if edge else 1.0)
        extra = chin*sst(MOUTH_BOT, CHIN_Z - 0.005, v.co.z)*(0 if edge else 1)*(1 - sst(0.02, 0.05, abs(v.co.x)))
        d = v.normal*(T*k + extra)
        if extra: d += Vector((0, -extra*0.5, -extra*0.6))                  # the chin tuft hangs forward and down
        v.co += d
        for lay in SHAPES: v[lay] += d
    print('beard', name, len(nf), 'faces', flush=True)
bm.normal_update()
bm.to_mesh(me); bm.free()
for g in list(h.vertex_groups):
    if g.name not in BONES: h.vertex_groups.remove(g)
bpy.ops.object.shade_smooth()

# ---------- head pieces (all ride on the head bone) ----------
bpy.context.view_layer.objects.active = h
dg = bpy.context.evaluated_depsgraph_get()
bvh = BVHTree.FromObject(h, dg)
def on_skin(x, z, out=0.002):
    hit = bvh.ray_cast(Vector((x, HEADF - 0.2, z)), Vector((0, 1, 0)), 1.0)
    return (hit[0] + Vector((0, -out, 0))) if hit[0] is not None else None
pieces = []
def piece(name, bmesh_fn, material):
    b = bmesh.new(); bmesh_fn(b)
    m = bpy.data.meshes.new(name); b.to_mesh(m); b.free()
    o = bpy.data.objects.new(name, m); bpy.context.scene.collection.objects.link(o)
    m.materials.append(material)
    vgh = o.vertex_groups.new(name='head'); vgh.add(list(range(len(m.vertices))), 1.0, 'REPLACE')
    for p in m.polygons: p.use_smooth = True
    pieces.append(o); return o

# brows: strips laid on the brow ridge; shape = how high they arch, where the peak is, how long and how ragged
def brow(width_m, arch=0.008, length=0.05, start=-0.024, slope=-0.004, peak=None, jag=0.0, join=False, rows=9):
    rnd = np.random.default_rng(11)
    def fn(b):
        inner = []
        for sgn, E in ((1, EYE_L), (-1, EYE_R)):
            pts = []
            for i in range(rows):
                u = i/(rows - 1); x = E.x + sgn*(start + length*u)
                bump = arch*math.sin(math.pi*min(1, u*1.2)) if peak is None else arch*(u/peak if u < peak else max(0.0, 1 - (u - peak)/(1 - peak)*1.3))
                z = E.z + 0.021 + bump + slope*u
                p = on_skin(x, z)
                if p: pts.append((p, (1 - 0.55*u**2)*(1 + jag*(rnd.random() - 0.5)*2)))
            rs = []
            for p, k in pts:
                hw = width_m*k/2; rs.append((b.verts.new(p + Vector((0, 0, hw))), b.verts.new(p + Vector((0, -0.0004, -hw)))))
            for a, c in zip(rs, rs[1:]):
                b.faces.new((a[0], c[0], c[1], a[1]))
            if pts: inner.append(pts[0][0])
        if join and len(inner) == 2:                                        # the two meet over the nose
            rs = []
            for i in range(7):
                u = i/6; x = inner[1].x + (inner[0].x - inner[1].x)*u; z = inner[0].z - 0.0012*math.sin(math.pi*u)
                p = on_skin(x, z)
                if p: hw = width_m*0.42/2; rs.append((b.verts.new(p + Vector((0, 0, hw))), b.verts.new(p + Vector((0, -0.0004, -hw)))))
            for a, c in zip(rs, rs[1:]): b.faces.new((a[0], c[0], c[1], a[1]))
    return fn
BROWS = {
    'BrowThin':     brow(0.0042),
    'BrowNormal':   brow(0.0068),
    'BrowThick':    brow(0.0105),
    'BrowArched':   brow(0.0060, arch=0.0145, slope=-0.007),
    'BrowStraight': brow(0.0075, arch=0.0015, slope=-0.001),
    'BrowAngled':   brow(0.0072, arch=0.0120, peak=0.66, slope=-0.002),
    'BrowBushy':    brow(0.0125, arch=0.0070, jag=0.35, rows=15),
    'BrowShort':    brow(0.0070, length=0.036, start=-0.018),
    'BrowUni':      brow(0.0085, arch=0.0060, join=True),
}
for nm, fn in BROWS.items(): piece(nm, fn, mat(nm, lin('#2a1d15'), 0.9))

# the long beard: a full, tapering lock hanging from the chin
def long_beard(b):
    rnd = np.random.default_rng(5); N, K = 48, 14
    rings = []
    for k in range(K):
        t = k/(K - 1); z = CHIN_Z + 0.014 - 0.115*t
        hw = 0.046*(1 - 0.72*t**1.2) + 0.004; yc = CHIN_Y + 0.016 - 0.012*t; dep = 0.030*(1 - 0.6*t) + 0.004
        ring = []
        for i in range(N):
            th = 2*math.pi*i/N; wob = 1 + 0.10*math.sin(9*th + 2.5*t) + 0.05*(rnd.random() - 0.5)    # locks of hair
            sn = math.sin(th); y = yc - dep*sn*wob if sn > 0 else yc - 0.3*dep*sn
            ring.append(b.verts.new((hw*math.cos(th)*wob, y, z)))
        rings.append(ring)
    for A, B_ in zip(rings, rings[1:]):
        for i in range(N): b.faces.new((A[i], A[(i + 1) % N], B_[(i + 1) % N], B_[i]))
    tipv = b.verts.new((0, CHIN_Y + 0.004, CHIN_Z + 0.014 - 0.13))
    for i in range(N): b.faces.new((rings[-1][i], rings[-1][(i + 1) % N], tipv))
    bmesh.ops.recalc_face_normals(b, faces=b.faces)
    uv = b.loops.layers.uv.new('UVMap')
    for f in b.faces:
        for l in f.loops: l[uv].uv = (0.5 + l.vert.co.x*3, 0.5 + l.vert.co.z*3)
piece('BeardLong', long_beard, mat('BeardLong', lin('#2a1d15'), 0.92, beard_png))

# hair bun at the back of the crown
def bun(b):
    bmesh.ops.create_uvsphere(b, u_segments=20, v_segments=12, radius=0.052)
    for v in b.verts: v.co = Vector((v.co.x*1.0, v.co.y*0.85, v.co.z*0.9)) + Vector((0, HEADB + 0.018, ZTOP - 0.035))
piece('HairBun', bun, mat('HairBun', lin('#2a1d15'), 0.6))

# glasses
def ring(b, c, rx, rz, minor, segs=28, square=False):
    rings = []
    for i in range(segs):
        a = 2*math.pi*i/segs
        if square:
            ca, sa = math.cos(a), math.sin(a); k = 1/max(abs(ca), abs(sa))**0.85
            px, pz = ca*k*rx, sa*k*rz
        else: px, pz = math.cos(a)*rx, math.sin(a)*rz
        ctr = c + Vector((px, 0, pz)); n = Vector((px, 0, pz)).normalized()
        rings.append([b.verts.new(ctr + n*minor*math.cos(t) + Vector((0, minor*math.sin(t), 0))) for t in [2*math.pi*j/6 for j in range(6)]])
    for i in range(segs):
        A, B_ = rings[i], rings[(i + 1) % segs]
        for j in range(6): b.faces.new((A[j], A[(j + 1) % 6], B_[(j + 1) % 6], B_[j]))
def tube(b, p0, p1, r):
    d = (p1 - p0); L = d.length; d.normalize(); a = d.orthogonal().normalized(); c = d.cross(a)
    r0 = [b.verts.new(p0 + (a*math.cos(t) + c*math.sin(t))*r) for t in [2*math.pi*j/6 for j in range(6)]]
    r1 = [b.verts.new(p1 + (a*math.cos(t) + c*math.sin(t))*r) for t in [2*math.pi*j/6 for j in range(6)]]
    for j in range(6): b.faces.new((r0[j], r0[(j + 1) % 6], r1[(j + 1) % 6], r1[j]))
GY = min(EYE_LF, EYE_RF) - 0.016
def glasses(square, rx, rz):
    def fn(b):
        for E in (EYE_L, EYE_R):
            ring(b, Vector((E.x, GY, E.z)), rx, rz, 0.0016, square=square)
        tube(b, Vector((EYE_L.x - rx, GY, EYE_L.z + 0.004)), Vector((EYE_R.x + rx, GY, EYE_R.z + 0.004)), 0.0014)
        for E, sg in ((EYE_L, 1), (EYE_R, -1)):
            tube(b, Vector((E.x + sg*rx, GY, E.z + 0.003)), Vector((sg*(HEAD_HW + 0.004), EYE_L.y + 0.075, E.z + 0.006)), 0.0014)
            tube(b, Vector((sg*(HEAD_HW + 0.004), EYE_L.y + 0.075, E.z + 0.006)), Vector((sg*(HEAD_HW - 0.004), EYE_L.y + 0.1, E.z - 0.012)), 0.0014)
    return fn
piece('GlassesRound', glasses(False, 0.021, 0.019), mat('GlassesRound', lin('#1a1a1c'), 0.3))
piece('GlassesSquare', glasses(True, 0.024, 0.017), mat('GlassesSquare', lin('#1a1a1c'), 0.3))
piece('GlassesSun', glasses(True, 0.025, 0.019), mat('GlassesSun', lin('#1a1a1c'), 0.3))
def lens(b):
    for E in (EYE_L, EYE_R):
        c = b.verts.new((E.x, GY + 0.0005, E.z)); rim = []
        for i in range(24):
            a = 2*math.pi*i/24; ca, sa = math.cos(a), math.sin(a); k = 1/max(abs(ca), abs(sa))**0.85
            rim.append(b.verts.new((E.x + ca*k*0.024, GY + 0.0005, E.z + sa*k*0.018)))
        for i in range(24): b.faces.new((c, rim[i], rim[(i + 1) % 24]))
piece('Lens', lens, mat('Lens', lin('#111418'), 0.05))

# hats
HR = HEAD_HW + 0.012
HC = Vector((0, (HEADF + HEADB)/2 + 0.012, 0))
def doppi(pattern):
    def fn(b):
        n = 4; zb, zt = ZTOP - 0.072, ZTOP + 0.012
        rings = []
        for k, (z, r) in enumerate(((zb, HR*1.02), (zb + 0.04, HR*1.0), (zt, HR*0.9))):
            ring_ = []
            for i in range(32):
                a = 2*math.pi*i/32 + math.pi/4
                ca, sa = math.cos(a), math.sin(a); s = 1/max(abs(ca), abs(sa))**0.55       # a soft four-cornered crown
                rr = r*s*(1.003 if pattern else 1.0)
                ring_.append(b.verts.new((ca*rr, HC.y + sa*rr*1.08, z + (0.0008 if pattern else 0))))
            rings.append(ring_)
        for A, B_ in zip(rings, rings[1:]):
            for i in range(32): b.faces.new((A[i], A[(i + 1) % 32], B_[(i + 1) % 32], B_[i]))
        if not pattern:
            top = b.verts.new((0, HC.y, zt + 0.004))
            for i in range(32): b.faces.new((rings[-1][i], rings[-1][(i + 1) % 32], top))
        uv = b.loops.layers.uv.new('UVMap')
        for f in b.faces:
            for l in f.loops:
                co = l.vert.co; l[uv].uv = ((math.atan2(co.y - HC.y, co.x)/(2*math.pi)) % 1.0 * 4, (co.z - zb)/(zt - zb))
    return fn
# the doppi's white almond (qalampir) motif, one per side, as an alpha-cut decal over the cap
W_, H_ = 256, 128
img = Image.new('RGBA', (W_, H_), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
def almond(cx, cy, s):
    pts = [(cx + s*0.5*math.sin(t)*(1 - 0.4*math.cos(t)), cy - s*math.cos(t)) for t in [i*2*math.pi/40 for i in range(40)]]
    d.polygon(pts, fill=(255, 255, 255, 255))
almond(W_*0.5, H_*0.45, 44); almond(W_*0.18, H_*0.62, 16); almond(W_*0.82, H_*0.62, 16)
d.line([(0, H_*0.1), (W_, H_*0.1)], fill=(255, 255, 255, 255), width=5)
pat_png = WORK + 'doppi_pattern.png'; img.save(pat_png)
piece('HatDoppi', doppi(False), mat('HatDoppi', lin('#111111'), 0.75))
piece('HatDoppiPattern', doppi(True), mat('HatDoppiPattern', (1, 1, 1), 0.7, pat_png, alpha=True))
def cap(b):
    zc = ZTOP - 0.075; R = HR*1.04
    rings = []
    for k in range(9):
        t = (k/8)*math.pi/2; z = zc + math.sin(t)*R*0.95; r = math.cos(t)*R
        rings.append([b.verts.new((math.cos(2*math.pi*i/32)*r, HC.y + math.sin(2*math.pi*i/32)*r*1.1, z)) for i in range(32)])
    for A, B_ in zip(rings, rings[1:]):
        for i in range(32): b.faces.new((A[i], A[(i + 1) % 32], B_[(i + 1) % 32], B_[i]))
    # the peak, out over the forehead
    pk = []
    for i in range(13):
        a = math.pi + math.pi*i/12            # front half (towards -Y)
        rin = Vector((math.cos(a)*R, HC.y + math.sin(a)*R*1.1, zc + 0.006))
        rout = Vector((math.cos(a)*R*1.02, HC.y + math.sin(a)*R*1.1 - 0.075*(math.sin(a)**2)**0.5, zc - 0.004))
        pk.append((b.verts.new(rin), b.verts.new(rout)))
    for a, c in zip(pk, pk[1:]): b.faces.new((a[0], c[0], c[1], a[1]))
piece('HatCap', cap, mat('HatCap', lin('#1f4f9a'), 0.8))
def wide(b):
    zb = ZTOP - 0.06; R = HR*1.03
    crown = []
    for z, r in ((zb, R), (zb + 0.1, R*0.93), (zb + 0.11, R*0.6)):
        crown.append([b.verts.new((math.cos(2*math.pi*i/32)*r, HC.y + math.sin(2*math.pi*i/32)*r*1.1, z)) for i in range(32)])
    for A, B_ in zip(crown, crown[1:]):
        for i in range(32): b.faces.new((A[i], A[(i + 1) % 32], B_[(i + 1) % 32], B_[i]))
    top = b.verts.new((0, HC.y, zb + 0.112))
    for i in range(32): b.faces.new((crown[-1][i], crown[-1][(i + 1) % 32], top))
    brim = [[b.verts.new((math.cos(2*math.pi*i/32)*r, HC.y + math.sin(2*math.pi*i/32)*r*1.08, zb + dz)) for i in range(32)] for r, dz in ((R, 0.0), (R + 0.085, -0.012))]
    for i in range(32): b.faces.new((brim[0][i], brim[0][(i + 1) % 32], brim[1][(i + 1) % 32], brim[1][i]))
piece('HatWide', wide, mat('HatWide', lin('#c9a36a'), 0.85))

# join the pieces into the body (one skinned mesh, one primitive per material)
bpy.ops.object.select_all(action='DESELECT')
for o in pieces: o.select_set(True)
h.select_set(True); bpy.context.view_layer.objects.active = h
bpy.ops.object.join()
print('verts', len(h.data.vertices), 'mats', [m.name for m in h.data.materials], flush=True)

# ---------- animations: the same idle / walk / run as the crowd bodies ----------
src = open('/home/claude/human/build.py').read()
a = src.index('# ---------- animations'); b = src.index('# ---------- optional preview')
exec(src[a:b])

# ---------- export ----------
for o in bpy.data.objects: o.select_set(o.name in ('Body', 'Rig'))
bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB', use_selection=True, export_animations=True, export_animation_mode='NLA_TRACKS',
                          export_skins=True, export_apply=False, export_yup=True, export_image_format='AUTO',
                          export_morph=True, export_morph_normal=False, export_try_sparse_sk=True)
print('exported', OUT, os.path.getsize(OUT), flush=True)
os._exit(0)

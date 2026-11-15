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
# the same feminine face as the player avatars (tools/human/build_avatar.py)
FACE_F = {'nose/nose-scale-vert-decr': 0.25, 'nose/nose-point-width-decr': 0.2, 'nose/nose-scale-horiz-decr': 0.1, 'nose/nose-width1-decr': 0.35,
          'nose/nose-hump-decr': 0.3, 'mouth/mouth-trans-up': 0.25, 'chin/chin-height-incr': 0.35, 'chin/chin-prominent-incr': 0.15, 'chin/chin-width-incr': 0.15,
          'eyes/l-eye-trans-out': 0.35, 'eyes/r-eye-trans-out': 0.35, 
          'eyes/l-eye-corner2-up': 0.3, 'eyes/r-eye-corner2-up': 0.3,
          'cheek/l-cheek-bones-incr': 0.45, 'cheek/r-cheek-bones-incr': 0.45, 'cheek/l-cheek-volume-decr': 0.1, 'cheek/r-cheek-volume-decr': 0.1,
          'mouth/mouth-upperlip-volume-incr': 0.15, 'mouth/mouth-lowerlip-volume-incr': 0.4, 'mouth/mouth-cupidsbow-incr': 0.3, 'mouth/mouth-philtrum-volume-incr': 0.3,
          'forehead/forehead-scale-vert-incr': 0.3}
if KIND == 'female':
    for i, (p, w) in enumerate(FACE_F.items()): TargetService.load_target(h, '/home/claude/makehumancommunity/mpfb2/src/mpfb/data/targets/' + p + '.target.gz', weight=w, name=f'ff{i}')
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
base = np.array([197, 146, 112], np.float32) if KIND == 'male' else np.array([206, 156, 122], np.float32)
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
# Walk and run follow measured human gait curves (hip, knee, ankle and toe angles over one stride, heel strike at 0),
# with the pelvis turning, tilting and shifting over the standing leg, the chest turning against it and the arms
# swinging opposite the legs. The body's height is solved every frame so the standing foot rests on the ground:
# that gives the natural rise and fall of a walk, and the push-off, flight and landing of a run.
bpy.context.view_layer.objects.active = rig; bpy.ops.object.mode_set(mode='POSE')
REST = {b.name: b.matrix_local.to_quaternion() for b in rig.data.bones}
RMAT = {b.name: b.matrix_local.copy() for b in rig.data.bones}
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
def pose(W, loc):
    D = {}
    for bn in ORDER:
        p = PARENT[bn]; Dp = D.get(p, I) if p else I
        D[bn] = W.get(bn, Dp)
        if bn in KEYED:
            pb = rig.pose.bones[bn]; pb.rotation_mode = 'QUATERNION'
            r = REST[bn]; pb.rotation_quaternion = r.inverted() @ Dp.inverted() @ D[bn] @ r
    rig.pose.bones['pelvis'].location = REST['pelvis'].to_matrix().inverted() @ loc
    for bn, ang in FINGERS.items():                              # relaxed hands: fingers gently curled
        pb = rig.pose.bones[bn]; pb.rotation_mode = 'QUATERNION'; pb.rotation_quaternion = Quaternion(CURL_AXIS, math.radians(ang))
FINGERS = {}
for f, a0 in (('index', 14), ('middle', 18), ('ring', 22), ('pinky', 26), ('thumb', 8)):
    for k, m in (('01', 1.0), ('02', 1.2), ('03', 0.9)):
        for sd in ('l', 'r'):
            if f'{f}_{k}_{sd}' in rig.pose.bones: FINGERS[f'{f}_{k}_{sd}'] = a0*m
CURL_AXIS = Vector((1, 0, 0))
def key(frame):
    for bn in FINGERS: rig.pose.bones[bn].keyframe_insert('rotation_quaternion', frame=frame)
    for bn in KEYED: rig.pose.bones[bn].keyframe_insert('rotation_quaternion', frame=frame)
    rig.pose.bones['pelvis'].keyframe_insert('location', frame=frame)

# where each foot meets the ground: the heel, the ball and the tip of the toes (each in its bone's own frame)
GROUND = min(v.co.z for v in h.data.vertices)
CONTACT = {}
for sd in ('l', 'r'):
    fh, bh, bt = RMAT['foot_' + sd].translation, RMAT['ball_' + sd].translation, rig.data.bones['ball_' + sd].tail_local
    heel = Vector((fh.x, fh.y + 0.035, GROUND)); pad = Vector((bh.x, bh.y, GROUND)); tip = Vector((bt.x, bt.y, GROUND))
    CONTACT[sd] = [('foot_' + sd, RMAT['foot_' + sd].inverted() @ heel), ('foot_' + sd, RMAT['foot_' + sd].inverted() @ pad),
                   ('ball_' + sd, RMAT['ball_' + sd].inverted() @ tip)]
def contacts(sd):
    bpy.context.view_layer.update()
    return [rig.pose.bones[bn].matrix @ p for bn, p in CONTACT[sd]]

def curve(pts):
    """a smooth periodic curve through (phase, value) points (Catmull-Rom over one cycle)"""
    pts = sorted(pts); n = len(pts)
    def f(t):
        t %= 1.0
        i = max(k for k in range(n) if pts[k][0] <= t) if t >= pts[0][0] else n - 1
        p0, p1, p2, p3 = (pts[(i + k) % n] for k in (-1, 0, 1, 2))
        t1 = p1[0]; t2 = p2[0] + (1 if p2[0] <= t1 else 0); tt = t + (1 if t < t1 else 0)
        u = (tt - t1)/(t2 - t1)
        a, b, c, d = p0[1], p1[1], p2[1], p3[1]
        return 0.5*((2*b) + (-a + c)*u + (2*a - 5*b + 4*c - d)*u*u + (-a + 3*b - 3*c + d)*u**3)
    return f
# joint angles over one stride of the right leg (degrees; + = hip flexed forward, knee bent, ankle toes-up, toes bent up)
G = {
  'walk': dict(
    hip=curve([(0, 28), (0.12, 24), (0.3, 6), (0.5, -11), (0.6, -4), (0.75, 22), (0.88, 30)]),
    knee=curve([(0, 4), (0.13, 17), (0.38, 4), (0.5, 9), (0.62, 40), (0.72, 60), (0.84, 32), (0.95, 3)]),
    ankle=curve([(0, -1), (0.07, -6), (0.3, 7), (0.48, 10), (0.62, -16), (0.72, -3), (0.88, 1)]),
    toe=curve([(0, 0), (0.44, 0), (0.54, 22), (0.6, 32), (0.67, 4), (0.75, 0)]),
    stance=0.6, lean=2.5, prot=4.0, obl=3.5, shift=0.014, arm=(13, 2), elbow=(14, 14), across=0.0, head=0.8),
  'run': dict(
    hip=curve([(0, 36), (0.16, 12), (0.33, -20), (0.5, 8), (0.75, 52), (0.9, 42)]),
    knee=curve([(0, 22), (0.13, 44), (0.33, 20), (0.5, 85), (0.65, 110), (0.82, 62), (0.94, 28)]),
    ankle=curve([(0, 2), (0.13, 17), (0.33, -26), (0.5, -6), (0.8, 6)]),
    toe=curve([(0, 0), (0.24, 0), (0.3, 28), (0.38, 4), (0.45, 0)]),
    stance=0.33, lean=9.0, prot=7.0, obl=4.5, shift=0.01, arm=(28, -3), elbow=(84, 10), across=0.04, head=0.5),
}
SIDE = 0.13 if KIND in ('male', 'm') else 0.10              # hands hang slightly away from the hips
def gait(name, t):
    g = G[name]; W = {}
    rot = g['prot']*math.cos(2*math.pi*t)                    # the right hip comes forward with the right foot
    obl = g['obl']*math.sin(2*math.pi*(t + 0.1))             # the hip over the swinging leg dips
    W['pelvis'] = Rz(rot) @ Ry(obl)
    W['spine_01'] = Rz(rot*0.4) @ Ry(obl*0.3) @ Rx(g['lean']*0.3)
    W['spine_02'] = Rz(-rot*0.3) @ Rx(g['lean']*0.7)
    W['spine_03'] = Rz(-rot*0.9) @ Ry(-obl*0.2) @ Rx(g['lean'])
    W['neck_01'] = Rz(-rot*0.4) @ Rx(g['lean']*0.3)
    W['head'] = Rz(-rot*0.1*g['head']) @ Rx(-g['lean']*0.15)              # the eyes stay level and ahead
    for sd, off in (('r', 0.0), ('l', 0.5)):
        tp = t + off
        hip, knee, ank, toe = g['hip'](tp), g['knee'](tp), g['ankle'](tp), g['toe'](tp)
        W['thigh_' + sd] = Rx(-hip)
        W['calf_' + sd] = Rx(-hip + knee)
        W['foot_' + sd] = Rx(-hip + knee - ank)
        W['ball_' + sd] = Rx(-hip + knee - ank - toe)
        # the arm on this side swings with the opposite leg, a moment behind it
        sg = 1 if sd == 'l' else -1
        A, A0 = g['arm']; sw = A0 - A*math.cos(2*math.pi*(tp - 0.04))       # + = arm forward
        fw = max(0.0, sw/A)
        Dc = W['spine_03']
        up_t = Rx(-sw) @ Vector((sg*(SIDE - g['across']*fw), 0.04, -1))
        W['upperarm_' + sd] = aim(Dc, 'upperarm_' + sd, Dc @ up_t)
        E0, E1 = g['elbow']; el = E0 + E1*fw
        lo_t = Rx(-el) @ up_t
        if g['across']: lo_t = lo_t + Vector((-sg*0.25*g['across']*10*fw, 0, 0))
        W['lowerarm_' + sd] = aim(W['upperarm_' + sd], 'lowerarm_' + sd, Dc @ lo_t)
        W['hand_' + sd] = aim(W['lowerarm_' + sd], 'hand_' + sd, Dc @ (Rx(-el - 6) @ up_t))
    shift = -g['shift']*math.sin(2*math.pi*t)                # the body sways over the standing foot
    return W, shift
def stance(name, sd, t):
    tp = (t + (0.5 if sd == 'l' else 0.0)) % 1.0
    return tp < G[name]['stance']
def make_gait(name, frames):
    """pose every frame, then lift or lower the body so the standing foot is on the ground"""
    act = bpy.data.actions.new(name); rig.animation_data_create(); rig.animation_data.action = act
    lift, poses, track = [], [], []
    for f in range(frames):
        t = f/frames; W, shift = gait(name, t)
        pose(W, Vector((shift, 0, 0)))
        on = [sd for sd in ('l', 'r') if stance(name, sd, t)]
        pts = {sd: contacts(sd) for sd in ('l', 'r')}
        if on:
            low = min(p.z for sd in on for p in pts[sd]); lift.append(GROUND - low)
        else: lift.append(None)
        # how fast the ground slides under the standing foot (sets the speed this cycle covers)
        track.append((t, pts['r'][1].y if 0.12 <= t <= G[name]['stance'] - 0.12 else None))
        poses.append((W, shift))
    # flight (run): a ballistic arc between take-off and landing
    n = frames
    for f in range(n):
        if lift[f] is not None: continue
        a = f
        while lift[(a - 1) % n] is None: a -= 1
        b = f
        while lift[b % n] is None: b += 1
        za, zb = lift[(a - 1) % n], lift[b % n]; L = b - a + 1; u = (f - a + 1)/L
        hgt = 9.8*(L/30.0)**2/8                                # peak of a jump that lasts the whole flight
        lift[f] = za + (zb - za)*u + 4*0.55*hgt*u*(1 - u)
    for f, (W, shift) in enumerate(poses):
        pose(W, Vector((shift, 0, lift[f]))); key(f + 1)
    pose(poses[0][0], Vector((poses[0][1], 0, lift[0]))); key(frames + 1)
    act.use_fake_user = True
    tr = rig.animation_data.nla_tracks.new(); tr.name = name; tr.strips.new(name, 1, act); rig.animation_data.action = None
    st = [(t, y) for t, y in track if y is not None]
    span = st[-1][0] - st[0][0]; dy = st[-1][1] - st[0][1]
    speed = dy/(span*frames/30.0)
    print(f'GAIT {name}: cycle {frames/30:.3f}s stride {speed*frames/30:.3f} m speed {speed:.3f} m/s bob {max(lift)-min(lift):.3f} m', flush=True)
def make_idle(frames):
    act = bpy.data.actions.new('idle'); rig.animation_data_create(); rig.animation_data.action = act
    for f in range(frames + 1):
        t = f/frames; b = 1.5*math.sin(2*math.pi*t); sway = 0.006*math.sin(2*math.pi*t*0.5)
        W = {'spine_03': Rx(b*0.6), 'spine_02': Rx(b*0.3), 'head': Rx(-b*0.3) @ Rz(1.5*math.sin(2*math.pi*t*0.5))}
        for sd in ('l', 'r'):
            sg = 1 if sd == 'l' else -1; Dc = W['spine_03']; up_t = Vector((sg*SIDE, 0.04, -1))
            W['upperarm_' + sd] = aim(Dc, 'upperarm_' + sd, Dc @ up_t)
            lo_t = Rx(-10) @ up_t
            W['lowerarm_' + sd] = aim(W['upperarm_' + sd], 'lowerarm_' + sd, Dc @ lo_t)
            W['hand_' + sd] = aim(W['lowerarm_' + sd], 'hand_' + sd, Dc @ (Rx(-14) @ up_t))
        pose(W, Vector((sway, 0, 0))); key(f + 1)
    act.use_fake_user = True
    tr = rig.animation_data.nla_tracks.new(); tr.name = 'idle'; tr.strips.new('idle', 1, act); rig.animation_data.action = None
print('BONES', [b.name for b in rig.data.bones if 'hand' in b.name or '_01_l' in b.name], flush=True)
print('STEP anim', flush=True)
make_gait('walk', 32)
make_gait('run', 20)
make_idle(90)
for pb in rig.pose.bones: pb.rotation_quaternion = Quaternion(); pb.location = Vector()
bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.scene.render.fps = 30

# ---------- optional preview render (side and front, walk mid-stride) ----------
print('STEP if PREVIEW:', flush=True)

if PREVIEW:
    # side-view strips of the walk and the run (Workbench: quick), one picture per few frames, with the ground line
    sc = bpy.context.scene; sc.render.engine = 'BLENDER_WORKBENCH'
    sc.render.resolution_x, sc.render.resolution_y = 260, 420
    bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 0, GROUND))
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.type = 'ORTHO'; cam.data.ortho_scale = 2.1; cam.location = (4, -0.1, 0.95); cam.rotation_euler = (math.radians(90), 0, math.radians(90))
    rig.animation_data.action = bpy.data.actions['idle']; sc.frame_set(1)
    cam.data.ortho_scale = 0.5; cam.location = (4, -0.0, 0.85); sc.render.filepath = PREVIEW.replace('.png', '_hand.png'); bpy.ops.render.render(write_still=True)
    cam.location = (-0.0, -4, 0.85); cam.rotation_euler = (math.radians(90), 0, 0); cam.location.x = 0.2; sc.render.filepath = PREVIEW.replace('.png', '_hand2.png'); bpy.ops.render.render(write_still=True)
    cam.data.ortho_scale = 2.1; cam.location = (4, -0.1, 0.95); cam.rotation_euler = (math.radians(90), 0, math.radians(90))
    for act, fr in (('walk', 32), ('run', 20)):
        rig.animation_data.action = bpy.data.actions[act]
        for k in range(8):
            sc.frame_set(1 + round(k*fr/8)); sc.render.filepath = PREVIEW.replace('.png', f'_{act}{k}.png'); bpy.ops.render.render(write_still=True)
    rig.animation_data.action = None

# ---------- export ----------
for o in bpy.data.objects:
    o.select_set(o.name in ('Body', 'Rig'))
print('STEP bpy.ops.export_scene', flush=True); bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB', use_selection=True, export_animations=True, export_animation_mode='NLA_TRACKS',
                          export_skins=True, export_apply=False, export_yup=True, export_image_format='JPEG', export_jpeg_quality=85, export_morph=False)
print('exported', OUT, os.path.getsize(OUT))
os._exit(0)

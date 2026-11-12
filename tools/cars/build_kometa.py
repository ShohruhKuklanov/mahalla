# Susambil Kometa: an original futuristic electric concept (bpy 4.5).
# Units: metres. X = width (car's left is +X), Y = length (front at -Y), Z = up, ground at Z = 0.
# A slim teardrop fuselage under a full bubble canopy, open front wheels under floating blade fenders on
# visible wishbones, rear wheels half-hidden in pods joined by a bridge wing; turbine wheels with a glowing ring.
import bpy, bmesh, math, sys, os
from mathutils import Vector

OUT = sys.argv[-1] if sys.argv[-1].endswith('.blend') else '/home/claude/coupe/kometa.blend'
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

def coll(name, parent=None):
    c = bpy.data.collections.new(name); (parent or scene.collection).children.link(c); return c
C_CAR = coll('Kometa'); C_BODY = coll('Body', C_CAR); C_DET = coll('Details', C_CAR); C_WHEELS = coll('Wheels', C_CAR); C_STUDIO = coll('Studio')

def principled(name, base, metallic=0.0, rough=0.5, coat=0.0, transmission=0.0, emission=None, strength=0.0, alpha=1.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*base, 1); b.inputs['Metallic'].default_value = metallic; b.inputs['Roughness'].default_value = rough
    if coat: b.inputs['Coat Weight'].default_value = coat; b.inputs['Coat Roughness'].default_value = 0.03
    if transmission: b.inputs['Transmission Weight'].default_value = transmission
    if emission: b.inputs['Emission Color'].default_value = (*emission, 1); b.inputs['Emission Strength'].default_value = strength
    m.diffuse_color = (*base, 1)
    return m
M = {
    'paint':  principled('Paint_PearlWhite', (0.8, 0.82, 0.85), metallic=0.35, rough=0.22, coat=1.0),
    'glass':  principled('Glass_Tinted', (0.02, 0.035, 0.05), rough=0.04, coat=1.0),
    'satin':  principled('Trim_SatinBlack', (0.018, 0.018, 0.02), rough=0.45),
    'black':  principled('Trim_GlossBlack', (0.008, 0.008, 0.01), rough=0.1, coat=1.0),
    'chrome': principled('Chrome', (0.88, 0.89, 0.9), metallic=1.0, rough=0.08),
    'rubber': principled('Tyre_Rubber', (0.016, 0.016, 0.017), rough=0.8),
    'rim':    principled('Wheel_Graphite', (0.05, 0.055, 0.06), metallic=0.9, rough=0.28, coat=0.5),
    'glow':   principled('Hub_Glow_LED', (0.2, 0.9, 1.0), emission=(0.25, 0.85, 1.0), strength=6.0),
    'led':    principled('LED_White', (1, 1, 1), emission=(0.85, 0.95, 1.0), strength=5.0),
    'tail':   principled('Taillight_Lens', (0.3, 0.0, 0.01), rough=0.1, emission=(1.0, 0.05, 0.04), strength=4.0),
}

def lerp(a, b, t): return a + (b - a) * t
def clamp(v, a, b): return max(a, min(b, v))
def cr(pts, s):
    if s <= pts[0][0]: return pts[0][1]
    if s >= pts[-1][0]: return pts[-1][1]
    i = 0
    while s > pts[i + 1][0]: i += 1
    n = len(pts); p0, p1, p2, p3 = pts[max(0, i-1)][1], pts[i][1], pts[i+1][1], pts[min(n-1, i+2)][1]
    t = (s - pts[i][0]) / (pts[i+1][0] - pts[i][0])
    return 0.5*(2*p1 + (-p0 + p2)*t + (2*p0 - 5*p1 + 4*p2 - p3)*t*t + (-p0 + 3*p1 - 3*p2 + p3)*t**3)

L = 4.6
yof = lambda s: s - L/2
S_FA, S_RA = 0.98, 3.72
RF, RR = 0.355, 0.375          # tyre radii front / rear
XF, XR = 0.93, 0.79            # wheel centres (half track) front / rear

def obj(name, bm, c, mat, smooth=True):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); c.objects.link(o)
    if mat: me.materials.append(mat)
    for p in me.polygons: p.use_smooth = smooth
    return o
def mod(o, kind, **kw):
    m = o.modifiers.new(kind.title(), kind)
    for k, v in kw.items(): setattr(m, k, v)
    return m

def loft(name, stations, section, c, mat, nseg=48, cap=True):
    """stations: list of s; section(s) -> list of (x, z) closed ring (same count each); y from s"""
    b = bmesh.new(); rings = []
    for s in stations:
        rings.append([b.verts.new((x, yof(s), z)) for (x, z) in section(s)])
    for A, B_ in zip(rings, rings[1:]):
        n = len(A)
        for k in range(n): b.faces.new((A[k], A[(k+1) % n], B_[(k+1) % n], B_[k]))
    if cap:
        for R, rev in ((rings[0], True), (rings[-1], False)):
            ctr = b.verts.new(sum((v.co for v in R), Vector()) / len(R))
            n = len(R)
            for k in range(n):
                f = (ctr, R[k], R[(k+1) % n]) if not rev else (ctr, R[(k+1) % n], R[k])
                b.faces.new(f)
    bmesh.ops.recalc_face_normals(b, faces=b.faces)
    return obj(name, b, c, mat)

def superellipse(cx, cz, a, h, n=48, p=2.6, top_only=False):
    out = []
    for i in range(n):
        t = 2*math.pi*i/n
        ct, st = math.cos(t), math.sin(t)
        out.append((cx + a*math.copysign(abs(ct)**(2/p), ct), cz + h*math.copysign(abs(st)**(2/p), st)))
    return out

# ---------------------------------------------------------------- fuselage: a long teardrop
W = [(0, 0.04), (0.12, 0.17), (0.45, 0.3), (1.0, 0.39), (1.7, 0.47), (2.4, 0.53), (3.0, 0.54), (3.6, 0.5), (4.15, 0.41), (4.6, 0.26)]
T = [(0, 0.36), (0.18, 0.44), (0.6, 0.54), (1.2, 0.66), (2.0, 0.74), (2.8, 0.79), (3.4, 0.8), (4.0, 0.79), (4.6, 0.74)]
Bt = [(0, 0.3), (0.25, 0.22), (0.8, 0.19), (3.9, 0.19), (4.6, 0.3)]
def fus_sec(s):
    t, b_, w = cr(T, s), cr(Bt, s), cr(W, s)
    return superellipse(0, (t + b_)/2, w, (t - b_)/2, 56, 2.7)
st = [0.0, 0.01, 0.03, 0.06, 0.1] + [0.15 + i*0.05 for i in range(int((L - 0.3)/0.05))] + [L - 0.1, L - 0.05, L - 0.02, L]
body = loft('Body', st, fus_sec, C_BODY, M['paint'])
mod(body, 'SUBSURF', levels=1, render_levels=2)

# ---------------------------------------------------------------- canopy: one smoked bubble from the nose cone to the tail
C0, C1 = 1.05, 3.55
def can_sec(s):
    u = clamp((s - C0)/(C1 - C0), 0, 1)
    rise = math.sin(math.pi * u ** 0.85) ** 0.75
    t = cr(T, s); w = cr(W, s)
    a = max(0.02, 0.9*w*math.sin(math.pi*u) ** 0.45)
    h = max(0.01, 0.37*rise)
    pts = superellipse(0, t - 0.06, a, h + 0.06, 40, 2.2)
    return [(x, max(z, t - 0.06)) for x, z in pts]
cst = [C0 + (C1 - C0)*i/60 for i in range(61)]
canopy = loft('Glass_Canopy', cst, can_sec, C_BODY, M['glass'])
mod(canopy, 'SUBSURF', levels=1, render_levels=2)
# a thin chrome seam where the canopy meets the body
seam = []
for i in range(81):
    s = C0 + 0.02 + (C1 - C0 - 0.04)*i/80
    u = clamp((s - C0)/(C1 - C0), 0, 1); w = cr(W, s)
    seam.append((0.9*w*math.sin(math.pi*u) ** 0.45 * 1.002, s, cr(T, s) - 0.045))
def curve(name, pts, r, mat, c, cyclic=False):
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = r; cu.bevel_resolution = 3
    sp = cu.splines.new('POLY'); sp.points.add(len(pts) - 1); sp.use_cyclic_u = cyclic
    for i, p in enumerate(pts): sp.points[i].co = (*p, 1)
    o = bpy.data.objects.new(name, cu); c.objects.link(o); cu.materials.append(mat); return o
for sg in (1, -1):
    curve('Canopy_Seam', [(sg*x, yof(s), z) for x, s, z in seam], 0.006, M['chrome'], C_DET)

# ---------------------------------------------------------------- rear pods over the rear wheels, joined to the body
def pod_sec_fn(sg):
    def f(s):
        u = clamp((s - 2.95)/(4.6 - 2.95), 0, 1)
        k = math.sin(math.pi*u) ** 0.55
        return superellipse(sg*(XR - 0.02), 0.6 + 0.06*u, max(0.02, 0.25*k), max(0.02, 0.32*k), 40, 2.4)
    return f
for sg, nm in ((1, 'L'), (-1, 'R')):
    p = loft(f'Body_Pod_{nm}', [2.95 + (4.6 - 2.95)*i/50 for i in range(51)], pod_sec_fn(sg), C_BODY, M['paint'])
    mod(p, 'SUBSURF', levels=1, render_levels=2)
# bridge wing across the pod tails
wing = bmesh.new(); foil = [(0, 0), (0.05, 0.022), (0.16, 0.03), (0.3, 0.012), (0.34, 0), (0.18, -0.008), (0.05, -0.006)]
secs = []
for i in range(31):
    x = -(XR - 0.02) + 2*(XR - 0.02)*i/30
    zc = 1.0 + 0.03*(1 - (x/(XR))**2)
    secs.append([wing.verts.new((x, yof(4.2) + u, zc + v)) for u, v in foil])
for A, B_ in zip(secs, secs[1:]):
    n = len(foil)
    for k in range(n): wing.faces.new((A[k], A[(k+1) % n], B_[(k+1) % n], B_[k]))
wing.faces.new(secs[0]); wing.faces.new(secs[-1][::-1]); bmesh.ops.recalc_face_normals(wing, faces=wing.faces)
wo = obj('Body_Wing', wing, C_BODY, M['paint']); mod(wo, 'SUBSURF', levels=1, render_levels=2)
for sg in (1, -1):      # struts from the pods into the wing
    curve('Wing_Strut', [(sg*(XR - 0.02), yof(4.25), 0.9), (sg*(XR - 0.04), yof(4.3), 1.0)], 0.02, M['paint'], C_DET)

# ---------------------------------------------------------------- front: floating blade fenders and wishbones
for sg, nm in ((1, 'L'), (-1, 'R')):
    b = bmesh.new(); rows = []
    for i in range(41):
        th = math.radians(lerp(18, 160, i/40))           # angle from the front, over the top, to the back
        r = RF + 0.075
        y = yof(S_FA) - r*math.cos(th); z = RF + r*math.sin(th)
        half = 0.15*(0.7 + 0.3*math.sin(th))
        rows.append([b.verts.new((sg*XF + dx, y, z)) for dx in (-half, -half*0.4, half*0.4, half)])
    for A, B_ in zip(rows, rows[1:]):
        for k in range(3): b.faces.new((A[k], A[k+1], B_[k+1], B_[k]))
    bmesh.ops.recalc_face_normals(b, faces=b.faces)
    fo = obj(f'Body_Fender_{nm}', b, C_BODY, M['paint']); mod(fo, 'SOLIDIFY', thickness=0.018, offset=1); mod(fo, 'SUBSURF', levels=2, render_levels=2)
    # the headlight: a glowing strip along the fender's leading edge
    hl = []
    for i in range(13):
        th = math.radians(lerp(20, 34, i/12)); r = RF + 0.083
        hl.append((sg*XF - sg*0.0, yof(S_FA) - r*math.cos(th), RF + r*math.sin(th)))
    for dx in (-0.1, 0.0, 0.1):
        curve(f'Headlight_Strip_{nm}', [(x + dx, y, z) for x, y, z in hl], 0.007, M['led'], C_DET)
    # the fender rides on a stalk from the hub
    curve(f'Fender_Stalk_{nm}', [(sg*XF, yof(S_FA) + 0.1, RF + 0.05), (sg*XF, yof(S_FA) + 0.25, RF + 0.33)], 0.022, M['satin'], C_DET)
    # wishbones from the body to the hub
    for (z0, z1, dy) in ((0.26, 0.28, 0.0), (0.5, 0.46, 0.0)):
        for off in (-0.16, 0.16):
            curve(f'Wishbone_{nm}', [(sg*0.36, yof(S_FA + off), z0), (sg*(XF - 0.12), yof(S_FA), z1)], 0.017, M['satin'], C_DET)
    curve(f'Pushrod_{nm}', [(sg*0.38, yof(S_FA + 0.12), 0.62), (sg*(XF - 0.14), yof(S_FA + 0.02), 0.3)], 0.012, M['chrome'], C_DET)
    # a dark air inlet on the flank behind the front wheel
    b2 = bmesh.new(); bmesh.ops.create_uvsphere(b2, u_segments=32, v_segments=16, radius=1.0)
    for v in b2.verts: v.co = Vector((v.co.x*0.03, v.co.y*0.34, v.co.z*0.08))
    io = obj(f'Side_Intake_{nm}', b2, C_DET, M['black']); io.location = (sg*0.505, yof(1.95), 0.44); io.rotation_euler = (math.radians(-8), 0, sg*math.radians(4))

# ---------------------------------------------------------------- nose and tail lights
nose = []
for i in range(25):
    x = lerp(-0.2, 0.2, i/24); s = 0.13 + 2.2*(x*x)
    nose.append((x, yof(s) - 0.004, 0.36))
curve('Headlight_Nose_Bar', nose, 0.008, M['led'], C_DET)
tl = []
for i in range(41):
    t = math.pi*(0.08 + 0.84*i/40); s = L - 0.04
    w = cr(W, s); zc = (cr(T, s) + cr(Bt, s))/2; h = (cr(T, s) - cr(Bt, s))/2
    tl.append((w*0.98*math.cos(t), yof(s) + 0.012, zc + h*0.55*math.sin(t)))
curve('Taillight_Arc', tl, 0.012, M['tail'], C_DET)
for sg in (1, -1):
    # a glowing ring round the tail tip of each pod
    curve('Taillight_Pod', [(sg*(XR - 0.02) + 0.045*math.cos(2*math.pi*i/24), yof(4.598), 0.66 + 0.055*math.sin(2*math.pi*i/24)) for i in range(24)], 0.012, M['tail'], C_DET, cyclic=True)
# diffuser blades under the tail
for x in (-0.24, -0.08, 0.08, 0.24):
    b3 = bmesh.new(); bmesh.ops.create_cube(b3, size=1.0)
    for v in b3.verts: v.co = Vector((v.co.x*0.008, v.co.y*0.34, v.co.z*0.06))
    d = obj('Diffuser_Fin', b3, C_DET, M['satin'], smooth=False); d.location = (x, yof(4.15), 0.27); d.rotation_euler = (math.radians(-12), 0, 0)

# ---------------------------------------------------------------- wheels: tyre, turbine rim, glowing ring, hub cap
def lathe(name, prof, segs, c, mat):
    b = bmesh.new(); rings = []
    for i in range(segs):
        a = 2*math.pi*i/segs
        rings.append([b.verts.new((w, r*math.cos(a), r*math.sin(a))) for r, w in prof])
    for i in range(segs):
        A, B_ = rings[i], rings[(i+1) % segs]
        for k in range(len(prof) - 1): b.faces.new((A[k], A[k+1], B_[k+1], B_[k]))
    bmesh.ops.recalc_face_normals(b, faces=b.faces)
    return obj(name, b, c, mat)
def wheel(tag, hub, R, wid, sg):
    parts = []
    hw = wid/2
    tyre = [(R - 0.11, -hw*0.92), (R - 0.03, -hw), (R - 0.004, -hw*0.85), (R, -hw*0.5), (R, hw*0.5), (R - 0.004, hw*0.85), (R - 0.03, hw), (R - 0.11, hw*0.92)]
    t = lathe(f'Tyre_{tag}', tyre, 64, C_WHEELS, M['rubber']); parts.append(t)
    rim = [(R - 0.11, hw*0.9), (R - 0.12, hw*0.75), (R - 0.12, -hw*0.8), (R - 0.11, -hw*0.9)]
    parts.append(lathe(f'Wheel_Barrel_{tag}', rim, 48, C_WHEELS, M['rim']))
    face = [(0.06, hw*0.9), (R - 0.125, hw*0.86), (R - 0.125, hw*0.83), (0.06, hw*0.7)]
    disc = lathe(f'Wheel_Face_{tag}', face, 48, C_WHEELS, M['rim']); parts.append(disc)
    # turbine blades on the outer face, swept like a fan
    b = bmesh.new()
    for k in range(9):
        a0 = 2*math.pi*k/9
        pts = []
        for j in range(8):
            r = lerp(0.07, R - 0.13, j/7); a = a0 + 0.55*j/7
            pts.append((r, a))
        prev = None
        for r, a in pts:
            vs = [b.verts.new((hw*0.9 + dz, r*math.cos(a + da), r*math.sin(a + da))) for dz, da in ((0.0, -0.05), (0.0, 0.05), (0.035, 0.05), (0.035, -0.05))]
            if prev:
                for q in range(4): b.faces.new((prev[q], prev[(q+1) % 4], vs[(q+1) % 4], vs[q]))
            prev = vs
    bmesh.ops.recalc_face_normals(b, faces=b.faces)
    parts.append(obj(f'Wheel_Blades_{tag}', b, C_WHEELS, M['chrome']))
    # the glowing ring behind the blades
    bpy.ops.mesh.primitive_torus_add(major_radius=R - 0.16, minor_radius=0.012, major_segments=64, minor_segments=8, rotation=(0, math.pi/2, 0), location=(hw*0.78, 0, 0))
    g = bpy.context.active_object; g.name = f'Wheel_Glow_{tag}'
    for cl in g.users_collection: cl.objects.unlink(g)
    C_WHEELS.objects.link(g); g.data.materials.append(M['glow']); parts.append(g)
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.06, depth=0.04, rotation=(0, math.pi/2, 0), location=(hw*0.92, 0, 0))
    hcap = bpy.context.active_object; hcap.name = f'Wheel_Cap_{tag}'
    for cl in hcap.users_collection: cl.objects.unlink(hcap)
    C_WHEELS.objects.link(hcap); hcap.data.materials.append(M['chrome']); parts.append(hcap)
    for p in parts:
        if sg < 0: p.scale = (-1, 1, 1)
        p.location = Vector(hub) + Vector((sg*p.location.x if p.location.x else 0, 0, 0))
    # mirrored parts need flipped normals: apply the scale
    for p in parts:
        bpy.ops.object.select_all(action='DESELECT'); p.select_set(True); bpy.context.view_layer.objects.active = p
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        if sg < 0:
            bm_ = bmesh.new(); bm_.from_mesh(p.data); bmesh.ops.reverse_faces(bm_, faces=bm_.faces); bm_.to_mesh(p.data); bm_.free()
    return parts
for tag, s, x, R, wid in (('FL', S_FA, XF, RF, 0.25), ('FR', S_FA, -XF, RF, 0.25), ('RL', S_RA, XR, RR, 0.33), ('RR', S_RA, -XR, RR, 0.33)):
    wheel(tag, (x, yof(s), R), R, wid, 1 if x > 0 else -1)

# ---------------------------------------------------------------- cabin seen through the canopy: two seats and a yoke
def rbox(name, size, loc, mat, rot=(0, 0, 0)):
    b = bmesh.new(); bmesh.ops.create_cube(b, size=1.0)
    for v in b.verts: v.co = Vector((v.co.x*size[0], v.co.y*size[1], v.co.z*size[2]))
    o = obj(name, b, C_BODY, mat); o.location = loc; o.rotation_euler = rot; mod(o, 'BEVEL', width=0.02, segments=2); return o
interior = principled('Interior_Leather', (0.06, 0.05, 0.045), rough=0.55)
for sg in (1, -1):
    rbox('Seat_Cushion', (0.32, 0.44, 0.08), (sg*0.2, yof(2.55), 0.5), interior)
    rbox('Seat_Back', (0.32, 0.08, 0.44), (sg*0.2, yof(2.85), 0.72), interior, (math.radians(-24), 0, 0))
rbox('Dashboard', (0.7, 0.3, 0.06), (0, yof(1.75), 0.8), M['satin'], (math.radians(12), 0, 0))
rbox('Steering_Yoke', (0.26, 0.03, 0.08), (0.2, yof(2.0), 0.88), M['satin'], (math.radians(-60), 0, 0))

# ---------------------------------------------------------------- root, studio, cameras
root = bpy.data.objects.new('Kometa_Root', None); C_CAR.objects.link(root)
for c in (C_BODY, C_DET, C_WHEELS):
    for o in c.objects:
        if o.parent is None: o.parent = root
w = bpy.data.worlds.new('w'); w.use_nodes = True; w.node_tree.nodes['Background'].inputs[0].default_value = (0.05, 0.055, 0.07, 1); w.node_tree.nodes['Background'].inputs[1].default_value = 0.6; scene.world = w
bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0)); fl = bpy.context.active_object; fl.name = 'Studio_Floor'
for cl in fl.users_collection: cl.objects.unlink(fl)
C_STUDIO.objects.link(fl); fl.data.materials.append(principled('Studio_Backdrop', (0.5, 0.52, 0.56), rough=0.6))
def area(name, loc, rot, size, power):
    l = bpy.data.lights.new(name, 'AREA'); l.size = size; l.energy = power
    o = bpy.data.objects.new(name, l); o.location = loc; o.rotation_euler = rot; C_STUDIO.objects.link(o)
area('Key', (0, 0, 6), (0, 0, 0), 6, 1800); area('Side', (5, -3, 3), (math.radians(60), 0, math.radians(60)), 4, 900); area('Back', (-4, 4, 3), (math.radians(-60), 0, math.radians(-140)), 4, 700)
def camera(name, loc, target=(0, 0, 0.5), lens=50):
    cd = bpy.data.cameras.new(name); cd.lens = lens; o = bpy.data.objects.new(name, cd); o.location = loc; C_STUDIO.objects.link(o)
    d = Vector(target) - Vector(loc); o.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler(); return o
camera('Camera_Hero_Front34', (4.6, -6.0, 1.9)); camera('Camera_Hero_Rear34', (-4.8, 5.8, 2.0)); camera('Camera_Side', (8.5, 0, 0.9), lens=55); camera('Camera_Front', (0, -8, 1.0), lens=60)
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print('saved', OUT, len(bpy.data.objects))
os._exit(0)

# Build a low-slung two-door front-engine sports coupe in Blender (bpy 4.5), save as .blend.
# Units: metres. X = width (car's left is +X), Y = length (front at -Y), Z = up, ground at Z = 0.
import bpy, bmesh, math, sys, os
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

OUT = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else '/home/claude/coupe/roadster.blend'

# ---------------------------------------------------------------- scene reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.length_unit = 'METERS'

def coll(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or scene.collection).children.link(c)
    return c
C_CAR = coll('Roadster')
C_BODY, C_DET, C_WHEELS = coll('Body', C_CAR), coll('Details', C_CAR), coll('Wheels', C_CAR)
C_STUDIO = coll('Studio')

def link(obj, c):
    c.objects.link(obj)
    return obj

def mesh_obj(name, verts, faces, c, mat=None, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.validate(); me.update()
    ob = bpy.data.objects.new(name, me)
    link(ob, c)
    if mat: me.materials.append(mat)
    if smooth:
        for p in me.polygons: p.use_smooth = True
    return ob

def bm_obj(name, bm, c, mat=None, smooth=True):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    link(ob, c)
    if mat: me.materials.append(mat)
    for p in me.polygons: p.use_smooth = smooth
    return ob

def recalc_normals(ob):
    bm = bmesh.new(); bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data); bm.free()

def add_mod(ob, kind, **kw):
    m = ob.modifiers.new(kind.title(), kind)
    for k, v in kw.items(): setattr(m, k, v)
    return m


# ---------------------------------------------------------------- materials (PBR, Principled BSDF)
def principled(name, base, metallic=0.0, rough=0.5, coat=0.0, coat_rough=0.03, transmission=0.0, ior=1.45, emission=None, emission_strength=0.0, spec=0.5):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*base, 1)
    b.inputs['Metallic'].default_value = metallic
    b.inputs['Roughness'].default_value = rough
    b.inputs['IOR'].default_value = ior
    b.inputs['Specular IOR Level'].default_value = spec
    if coat: b.inputs['Coat Weight'].default_value = coat; b.inputs['Coat Roughness'].default_value = coat_rough
    if transmission: b.inputs['Transmission Weight'].default_value = transmission
    if emission: b.inputs['Emission Color'].default_value = (*emission, 1); b.inputs['Emission Strength'].default_value = emission_strength
    m.diffuse_color = (*base, 1)
    return m

M = {
    # silver-white metallic with a clear coat: bright but not mirror-like
    'paint':   principled('Paint_DeepRed', (0.32, 0.02, 0.03), metallic=0.6, rough=0.3, coat=1.0, coat_rough=0.04),
    'glass':   principled('Glass_Tinted', (0.2, 0.22, 0.24), rough=0.06, transmission=0.94, ior=1.52, spec=0.5),
    'lens':    principled('Headlight_Lens', (0.97, 0.98, 1.0), rough=0.0, transmission=1.0, ior=1.49),
    'housing': principled('Headlight_Housing', (0.03, 0.032, 0.036), metallic=0.85, rough=0.22),
    'reflect': principled('Headlight_Reflector', (0.82, 0.84, 0.88), metallic=1.0, rough=0.1),
    'led':     principled('LED_White', (1, 1, 1), emission=(0.92, 0.96, 1.0), emission_strength=2.5),
    'tail':    principled('Taillight_Lens', (0.28, 0.0, 0.01), rough=0.08, coat=1.0, emission=(1.0, 0.04, 0.03), emission_strength=1.8),
    'black':   principled('Trim_GlossBlack', (0.01, 0.01, 0.012), rough=0.12, coat=0.8),
    'satin':   principled('Trim_SatinBlack', (0.018, 0.018, 0.02), rough=0.45),
    'slat':    principled('Grille_Slats_Chrome', (0.62, 0.64, 0.67), metallic=1.0, rough=0.12),
    'chrome':  principled('Chrome', (0.88, 0.89, 0.9), metallic=1.0, rough=0.06),
    'rubber':  principled('Tyre_Rubber', (0.016, 0.016, 0.017), rough=0.78, spec=0.3),
    'wheel':   principled('Wheel_Graphite', (0.055, 0.058, 0.062), metallic=0.9, rough=0.3, coat=0.5, coat_rough=0.15),
    'disc':    principled('Brake_Disc', (0.42, 0.42, 0.43), metallic=1.0, rough=0.38),
    'hat':     principled('Brake_Hat', (0.1, 0.1, 0.11), metallic=0.6, rough=0.5),
    'caliper': principled('Brake_Caliper', (0.55, 0.56, 0.58), metallic=0.8, rough=0.28),
    'interior':principled('Interior_Leather', (0.06, 0.05, 0.045), rough=0.55),
    'dash':    principled('Interior_Dash', (0.03, 0.03, 0.033), rough=0.45),
    'gap':     principled('PanelGap', (0.006, 0.006, 0.007), rough=0.6),
    'mirror':  principled('Mirror_Glass', (0.8, 0.82, 0.85), metallic=1.0, rough=0.02),
    'studio':  principled('Studio_Backdrop', (0.14, 0.155, 0.185), rough=0.65),
}

def dark_backfaces(mat):
    nt = mat.node_tree; bsdf = nt.nodes['Principled BSDF']; out = nt.nodes['Material Output']
    geo = nt.nodes.new('ShaderNodeNewGeometry'); dark = nt.nodes.new('ShaderNodeBsdfDiffuse'); mix = nt.nodes.new('ShaderNodeMixShader')
    dark.inputs['Color'].default_value = (0.02, 0.02, 0.022, 1)
    nt.links.new(geo.outputs['Backfacing'], mix.inputs['Fac']); nt.links.new(bsdf.outputs['BSDF'], mix.inputs[1]); nt.links.new(dark.outputs['BSDF'], mix.inputs[2])
    nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])
dark_backfaces(M['paint'])

# ---------------------------------------------------------------- dimensions (front-engine GT coupe)
L, WB = 4.73, 2.70
S_FA = 0.94                     # front axle, measured from the nose
S_RA = S_FA + WB                # rear axle
RW = 0.36                       # tyre radius (low-profile on 21" wheels)
AR = 0.385                      # arch opening radius: a tight gap over the tyre
yof = lambda s: s - L/2          # distance from the nose → Y (front at -Y)
def lerp(a, b, t): return a + (b - a) * t
def clamp(v, a, b): return max(a, min(b, v))
def smooth01(t): t = clamp(t, 0, 1); return t * t * (3 - 2 * t)

def cr(pts, s):
    """Catmull-Rom through (s, value) points sorted by s."""
    if s <= pts[0][0]: return pts[0][1]
    n = len(pts)
    if s >= pts[-1][0]: return pts[-1][1]
    i = 0
    while s > pts[i+1][0]: i += 1
    p0, p1, p2, p3 = pts[max(0, i-1)][1], pts[i][1], pts[i+1][1], pts[min(n-1, i+2)][1]
    t = (s - pts[i][0]) / (pts[i+1][0] - pts[i][0])
    return 0.5*(2*p1 + (-p0 + p2)*t + (2*p0 - 5*p1 + 4*p2 - p3)*t*t + (-p0 + 3*p1 - 3*p2 + p3)*t**3)

# side profile: nose, long bonnet, raked screen, roof, fastback, short rounded tail
TOP = [(0.0,0.44),(0.01,0.52),(0.03,0.575),(0.07,0.612),(0.15,0.64),(0.4,0.676),(0.8,0.724),(1.2,0.768),(1.55,0.803),(1.8,0.828),
       (1.93,0.848),(2.06,0.94),(2.2,1.04),(2.36,1.13),(2.52,1.19),(2.66,1.222),(2.82,1.236),(2.98,1.232),(3.14,1.212),(3.3,1.168),
       (3.44,1.1),(3.56,1.03),(3.66,0.99),(3.78,0.976),(4.0,0.972),(4.2,0.968),(4.4,0.96),(4.55,0.948),(4.62,0.92),(4.67,0.875),(4.705,0.795),(4.722,0.7),(4.73,0.58)]
BOT = [(0.0,0.4),(0.012,0.25),(0.04,0.18),(0.12,0.145),(0.4,0.13),(1.0,0.125),(3.9,0.135),(4.15,0.16),(4.4,0.22),(4.58,0.31),(4.68,0.41),(4.73,0.5)]
BELT = [(0.0,0.835),(1.93,0.835),(2.4,0.862),(3.0,0.9),(3.4,0.935),(3.7,0.955),(4.73,0.955)]
WID = [(0.0,0.5),(0.01,0.66),(0.035,0.77),(0.1,0.86),(0.3,0.93),(0.6,0.975),(0.94,0.996),(1.3,0.976),(1.8,0.938),(2.3,0.92),
       (2.9,0.945),(3.35,0.99),(3.64,1.012),(4.0,0.99),(4.28,0.94),(4.48,0.862),(4.6,0.76),(4.67,0.65),(4.71,0.54),(4.73,0.42)]
WRF = [(0.0,0.72),(1.92,0.73),(2.3,0.67),(2.7,0.615),(3.1,0.62),(3.45,0.66),(3.7,0.78),(4.2,0.84),(4.73,0.7)]

def arch_z(s):
    z = 0.0
    for sa in (S_FA, S_RA):
        d = abs(s - sa)
        if d < AR: z = max(z, RW + math.sqrt(AR*AR - d*d))
    return z

def chaikin(pts, it):
    for _ in range(it):
        o = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            o += [(0.75*a[0] + 0.25*b[0], 0.75*a[1] + 0.25*b[1]), (0.25*a[0] + 0.75*b[0], 0.25*a[1] + 0.75*b[1])]
        o.append(pts[-1]); pts = o
    return pts

HOOD_W = float(__import__('os').environ.get('HOOD_W', '1'))
def half_section(s):
    """Half cross-section (x ≥ 0) at distance s from the nose: rounded flanks that roll under at the sill and
    into the shoulder; front fenders crown above the bonnet, which carries two soft domes; tumblehome cabin."""
    yt, W = cr(TOP, s), cr(WID, s)
    belt = min(cr(BELT, s), yt)
    WR = min(cr(WRF, s), W - 0.07)
    yb = min(max(cr(BOT, s), arch_z(s)), yt - 0.012)
    h = max(0.01, belt - yb)
    k = smooth01((yt - belt) / 0.16)                  # bonnet → glasshouse blend, soft at the cowl
    fender = 0.062 * math.exp(-((s - 0.88) / 0.66) ** 2) if s < 2.0 else 0.05 * math.exp(-((s - 3.68) / 0.5) ** 2)
    dome = 0.016 * math.exp(-((s - 1.05) / 0.55) ** 2)
    scoop = 1 - 0.022 * math.exp(-((s - 2.45) / 0.55) ** 4)      # lower door sculpted in between the wheels
    lower = [(0, yb), (W*0.76, yb), (W*0.9*scoop, yb + 0.07*h), (W*0.962*scoop, yb + 0.26*h), (W*0.995, yb + 0.58*h), (W*0.984, yb + 0.8*h), (W*0.93, belt)]
    fender *= (1 - k)
    bonnet = [(W*0.84, yt + fender*0.9), (W*0.66, yt + fender*0.5), (W*0.44, yt + 0.002 + dome*0.4), (W*0.2, yt + 0.012 + dome), (0, yt + 0.012 + dome*0.8)]
    glass = [(W*0.93 - 0.035, belt + 0.02), (WR + 0.05, yt - 0.075), (WR + 0.002, yt - 0.02), (WR*0.55, yt + 0.006), (0, yt + 0.01)]
    up = [(lerp(a[0], b[0], k), lerp(a[1], b[1], k)) for a, b in zip(bonnet, glass)]
    pts = chaikin(lower + up, 3)
    # sculpted bonnet, applied as a smooth height offset on the bonnet skin (same topology as before, so the
    # grille / intake cut-outs are untouched): a broader central crown, a raised centre section bounded by two
    # soft ridges running from the grille corners back towards the windscreen base (diverging slightly), and a
    # shallow channel outboard of each ridge that rolls up into the fender crown
    wb = HOOD_W * smooth01((s - 0.16) / 0.34) * (1 - k)
    if wb > 1e-4:
        rr = 0.335 + 0.085 * smooth01(s / 1.85)
        P = 0.015 * (1 - 0.6 * smooth01((s - 1.45) / 0.45))     # ridges soften as they reach the screen
        crown = 0.006 + 0.004 * smooth01((s - 0.2) / 0.6)
        def dz(x):
            ridge = P * (1 - smooth01((x - rr + 0.06) / 0.12))
            chan = -0.003 * math.exp(-((x - rr - 0.075) / 0.05) ** 2)
            cz = crown * (1 - (x / (W * 0.8)) ** 2)
            edge = 1 - smooth01((x - W * 0.7) / (W * 0.12))           # nothing at the fender crown / shut line
            return (ridge + chan + cz) * edge
        pts = [(x, z + wb * dz(x)) if (z > yt - 0.03 and x < W * 0.84) else (x, z) for x, z in pts]
    return pts

# stations along the car, denser at the ends and around the arches
st = set(round(i * 0.018, 4) for i in range(int(L / 0.018) + 1))
for e in (0.002, 0.005, 0.009, 0.014):
    st.add(e); st.add(round(L - e, 4))
for sa in (S_FA, S_RA):
    for d in (-AR, -AR + 0.004, AR - 0.004, AR):
        st.add(round(sa + d, 4))
S = sorted(x for x in st if 0 <= x <= L)

verts, faces = [], []
NR = None
for s in S:
    hp = half_section(s)
    ring = [(x, z) for x, z in hp] + [(-x, z) for x, z in reversed(hp[1:-1])]
    NR = len(ring)
    for x, z in ring: verts.append((x, yof(s), z))
for i in range(len(S) - 1):
    for k in range(NR):
        a, b = i*NR + k, i*NR + (k + 1) % NR
        faces.append((a, b, b + NR, a + NR))
for i in (0, len(S) - 1):
    c = len(verts)
    cz = sum(verts[i*NR + k][2] for k in range(NR)) / NR
    verts.append((0, yof(S[i]), cz))
    for k in range(NR): faces.append((c, i*NR + k, i*NR + (k + 1) % NR))

# ---------------------------------------------------------------- glazing: windscreen, frameless side windows, fastback glass
S_COWL, S_ROOF0, S_ROOF1 = 1.93, 2.5, 3.22
def a_edge(z):   # front edge of the side glass, parallel to the slim A-pillar
    return lerp(S_COWL + 0.13, S_ROOF0 + 0.07, clamp((z - 0.84) / 0.45, 0, 1))
def c_edge(z):   # the side glass ends in a point towards the C-pillar
    return lerp(3.28, 2.98, clamp((z - 0.94) / 0.28, 0, 1))
def window_kind(x, y, z):
    s = y + L/2
    yt, W = cr(TOP, s), cr(WID, s)
    belt = min(cr(BELT, s), yt)
    WR = min(cr(WRF, s), W - 0.07)
    if z < belt + 0.022 or yt - belt < 0.03: return None
    ax = abs(x)
    if S_COWL + 0.03 < s < S_ROOF0 - 0.02 and ax < WR - 0.005: return 'front'
    if a_edge(z) < s < c_edge(z) and ax > WR + 0.012 and z < yt - 0.024: return 'side'
    if S_ROOF1 + 0.05 < s < 3.55 and ax < 0.4 and z > belt + 0.07: return 'rear'
    return None

# ---------------------------------------------------------------- front openings cut into the bumper (front-view outlines)
def _cs(poly, it):
    pts = poly + [poly[0]]
    for _ in range(it):
        o = []
        for a, b in zip(pts, pts[1:]):
            o += [(0.75*a[0] + 0.25*b[0], 0.75*a[1] + 0.25*b[1]), (0.25*a[0] + 0.75*b[0], 0.25*a[1] + 0.75*b[1])]
        pts = o + [o[0]]
    return pts[:-1]
OPEN_GRILLE = _cs([(-0.42, 0.49), (0.42, 0.49), (0.52, 0.45), (0.545, 0.34), (0.5, 0.25), (-0.5, 0.25), (-0.545, 0.34), (-0.52, 0.45)], 4)
_INT = [(0.585, 0.445), (0.75, 0.46), (0.81, 0.41), (0.815, 0.26), (0.78, 0.2), (0.6, 0.195), (0.565, 0.3)]
OPEN_INTAKE_L = _cs(_INT, 2); OPEN_INTAKE_R = _cs([(-x, z) for x, z in _INT][::-1], 2)
OPEN_DAM = _cs([(-0.78, 0.205), (-0.56, 0.212), (0.56, 0.212), (0.78, 0.205), (0.83, 0.175), (0.78, 0.162), (-0.78, 0.162), (-0.83, 0.175)], 2)
def pip(poly, x, z):
    c = False
    for (x1, z1), (x2, z2) in zip(poly, poly[1:] + poly[:1]):
        if (z1 > z) != (z2 > z) and x < x1 + (z - z1) * (x2 - x1) / (z2 - z1): c = not c
    return c
def open_kind(x, y, z):
    s = y + L/2
    if s > 0.42: return None
    if pip(OPEN_GRILLE, x, z): return 'grille'
    if pip(OPEN_INTAKE_L, x, z) or pip(OPEN_INTAKE_R, x, z): return 'intake'
    if pip(OPEN_DAM, x, z): return 'dam'
    return None
OPEN_KINDS = ('grille', 'intake', 'dam')
def region_kind(x, y, z): return window_kind(x, y, z) or open_kind(x, y, z)

V = [Vector(v) for v in verts]
_t = mesh_obj('tmp_full', verts, faces, C_BODY); recalc_normals(_t)
NRM = [v.normal.copy() for v in _t.data.vertices]; bpy.data.meshes.remove(_t.data)
kind_cache = {}
def kind_of(i):
    if i not in kind_cache: kind_cache[i] = region_kind(*V[i])
    return kind_cache[i]
cross_cache = {}
def crossing(i, j):
    key = (min(i, j), max(i, j))
    if key in cross_cache: return cross_cache[key]
    a_, b_ = (V[i], V[j]) if kind_of(i) is not None else (V[j], V[i])
    kd = region_kind(*a_)
    lo, hi = 0.0, 1.0
    for _ in range(18):
        mid_ = (lo + hi) / 2
        if region_kind(*a_.lerp(b_, mid_)) == kd: lo = mid_
        else: hi = mid_
    V.append(a_.lerp(b_, lo)); cross_cache[key] = len(V) - 1; kind_cache[len(V) - 1] = 'edge'
    ia, ib = (i, j) if kind_of(i) is not None else (j, i)
    NRM.append(NRM[ia].lerp(NRM[ib], lo).normalized())
    return len(V) - 1
# clip the skin along the window outlines (per quad, like marching squares): edges follow the outlines exactly
body_faces, glass_faces, open_faces = [], [], []
def _bucket(ks): return open_faces if any(k in OPEN_KINDS for k in ks) else glass_faces
for f in faces:
    ks = [kind_of(i) for i in f]
    if len(f) != 4 or all(k is None for k in ks): body_faces.append(f); continue
    if all(k is not None for k in ks): _bucket(ks).append(f); continue
    inp, outp = [], []
    for a_, b_ in zip(f, f[1:] + f[:1]):
        (inp if kind_of(a_) is not None else outp).append(a_)
        if (kind_of(a_) is None) != (kind_of(b_) is None):
            x_ = crossing(a_, b_); inp.append(x_); outp.append(x_)
    if len(inp) >= 3: _bucket(ks).append(tuple(inp))
    if len(outp) >= 3: body_faces.append(tuple(outp))
FULL_BVH = BVHTree.FromPolygons([tuple(v) for v in V], body_faces + glass_faces + open_faces)
tmp = mesh_obj('tmp', V, body_faces + glass_faces + open_faces, C_BODY); recalc_normals(tmp)
nrm_of = {i: NRM[i] for i in range(len(V))}
bpy.data.meshes.remove(tmp.data)
body = mesh_obj('Body', V, body_faces, C_BODY, M['paint'])
FABRIC = principled('SoftTop_Fabric', (0.03, 0.032, 0.036), rough=0.92, spec=0.2)
body.data.materials.append(FABRIC)
for p in body.data.polygons:
    c_ = p.center; s_ = c_.y + L/2
    if S_ROOF0 - 0.035 < s_ < 3.7 and c_.z > min(cr(BELT, s_), cr(TOP, s_)) + 0.03: p.material_index = 1
recalc_normals(body)
bmc = bmesh.new(); bmc.from_mesh(body.data)
bmesh.ops.delete(bmc, geom=[v for v in bmc.verts if not v.link_faces], context='VERTS')
bmc.to_mesh(body.data); bmc.free()
def offset_copy(name, fs, dist, mat, c=C_BODY):
    used = sorted({i for f in fs for i in f}); m = {i: n for n, i in enumerate(used)}
    vs = [V[i] + nrm_of.get(i, Vector((0, 0, 1))) * dist for i in used]
    return mesh_obj(name, vs, [tuple(m[i] for i in f) for f in fs], c, mat)
windows = offset_copy('Glass', glass_faces, 0.002, M['glass']); recalc_normals(windows)
for ob_ in (windows, body):         # clipped edge polygons → clean triangles for even shading along the window lines
    bmt = bmesh.new(); bmt.from_mesh(ob_.data)
    bmesh.ops.triangulate(bmt, faces=[f for f in bmt.faces if len(f.verts) > 4], quad_method='BEAUTY', ngon_method='BEAUTY')
    bmt.to_mesh(ob_.data); bmt.free()
    for p in ob_.data.polygons: p.use_smooth = True
# glass: shading normals from the smooth surface underneath (even reflections right up to the edges)
gv = sorted({i for f in glass_faces for i in f})
windows.data.normals_split_custom_set_from_vertices([tuple(NRM[i]) for i in gv])
add_mod(windows, 'SOLIDIFY', thickness=0.005, offset=-1)
# recessed cavities behind the front openings: walls from the cut edge, a back face set 7 cm in
def cavity(name, fs, depth, mat, c):
    used = sorted({i for f in fs for i in f}); m = {i: n for n, i in enumerate(used)}
    b = bmesh.new()
    outer = [b.verts.new(V[i]) for i in used]
    inner = [b.verts.new(V[i] - nrm_of[i] * depth) for i in used]
    for f in fs: b.faces.new([inner[m[i]] for i in f][::-1])
    cnt = {}
    for f in fs:
        for a_, b_ in zip(f, f[1:] + f[:1]): cnt[(a_, b_)] = cnt.get((a_, b_), 0) + 1
    for (a_, b_), n in cnt.items():
        if (b_, a_) in cnt: continue                     # interior edge
        b.faces.new((outer[m[a_]], outer[m[b_]], inner[m[b_]], inner[m[a_]]))
    return bm_obj(name, b, c, mat, smooth=False)
add_mod(body, 'SUBSURF', levels=1, render_levels=2)
# slim black seal around every pane (the glass' open edges)
bmw = bmesh.new(); bmw.from_mesh(windows.data)
edges = [e for e in bmw.edges if e.is_boundary]
cu = bpy.data.curves.new('Window_Seals', 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = 0.0045; cu.bevel_resolution = 2
seen = set()
for e0 in edges:
    if e0.index in seen: continue
    loop = [e0.verts[0]]; cur = e0; v = e0.verts[1]; seen.add(e0.index)
    while v is not loop[0]:
        loop.append(v)
        nxt = [e for e in v.link_edges if e.is_boundary and e.index not in seen]
        if not nxt: break
        cur = nxt[0]; seen.add(cur.index); v = cur.other_vert(v)
    if len(loop) < 8: continue
    spl = cu.splines.new('POLY'); spl.points.add(len(loop) - 1); spl.use_cyclic_u = True
    for i, vv in enumerate(loop): spl.points[i].co = (*vv.co, 1)
bmw.free()
seals = link(bpy.data.objects.new('Window_Seals', cu), C_BODY); cu.materials.append(M['satin'])


# ---------------------------------------------------------------- simple cabin seen through the glass
def rbox(name, size, loc, mat, c, bevel=0.02, rot=(0, 0, 0)):
    b = bmesh.new(); bmesh.ops.create_cube(b, size=1.0)
    for v in b.verts: v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    ob = bm_obj(name, b, c, mat, smooth=True); ob.location = loc; ob.rotation_euler = rot
    if bevel: add_mod(ob, 'BEVEL', width=bevel, segments=3)
    return ob
for sgn, nm in ((1, 'L'), (-1, 'R')):
    cx = sgn * 0.37
    # sport seat: cushion with raised bolsters, reclined back with bolsters and an integrated headrest
    rbox(f'Seat_Cushion_{nm}', (0.34, 0.5, 0.09), (cx, yof(2.98), 0.31), M['interior'], C_BODY, 0.03)
    for dx in (-0.2, 0.2): rbox(f'Seat_Bolster_{nm}', (0.08, 0.48, 0.13), (cx + dx, yof(2.98), 0.34), M['interior'], C_BODY, 0.03)
    back = (math.radians(-17), 0, 0)
    rbox(f'Seat_Back_{nm}', (0.34, 0.1, 0.58), (cx, yof(3.24), 0.62), M['interior'], C_BODY, 0.035, back)
    for dx in (-0.2, 0.2): rbox(f'Seat_Back_Bolster_{nm}', (0.08, 0.14, 0.5), (cx + dx, yof(3.22), 0.6), M['interior'], C_BODY, 0.03, back)
    rbox(f'Seat_Headrest_{nm}', (0.26, 0.1, 0.16), (cx, yof(3.33), 0.98), M['interior'], C_BODY, 0.04, back)
    # door card
    rbox(f'Door_Card_{nm}', (0.03, 1.05, 0.48), (sgn * 0.84, yof(2.65), 0.58), M['dash'], C_BODY, 0.01)
rbox('Dashboard', (1.4, 0.34, 0.14), (0, yof(2.34), 0.76), M['dash'], C_BODY, 0.04)
rbox('Dash_Lower', (1.4, 0.2, 0.22), (0, yof(2.42), 0.6), M['dash'], C_BODY, 0.03)
rbox('Instrument_Hood', (0.36, 0.14, 0.07), (0.37, yof(2.44), 0.86), M['dash'], C_BODY, 0.02)
scr = rbox('Centre_Screen', (0.3, 0.012, 0.17), (0, yof(2.5), 0.8), principled('Screen', (0.01, 0.012, 0.02), rough=0.1, emission=(0.12, 0.2, 0.32), emission_strength=0.6), C_BODY, 0.004, (math.radians(-18), 0, 0))
rbox('Centre_Console', (0.22, 1.0, 0.2), (0, yof(2.85), 0.42), M['dash'], C_BODY, 0.03)
rbox('Gear_Selector', (0.04, 0.06, 0.06), (0, yof(2.8), 0.55), M['chrome'], C_BODY, 0.01)
bpy.ops.mesh.primitive_torus_add(major_radius=0.18, minor_radius=0.017, major_segments=48, minor_segments=10,
                                 location=(0.37, yof(2.52), 0.8), rotation=(math.radians(68), 0, 0))
sw = bpy.context.active_object; sw.name = 'Steering_Wheel'
for cl in sw.users_collection: cl.objects.unlink(sw)
link(sw, C_BODY); sw.data.materials.append(M['dash'])
for p in sw.data.polygons: p.use_smooth = True
for ang in (0, 120, 240):           # three spokes and a hub
    a_ = math.radians(ang + 90)
    rbox('Steering_Spoke', (0.16, 0.02, 0.03), (0.37 + 0.08 * math.cos(a_), yof(2.52) + 0.08 * math.sin(a_) * math.cos(math.radians(68)) * 0, 0.8 + 0.08 * math.sin(a_) * math.sin(math.radians(68))),
         M['dash'], C_BODY, 0.006, (math.radians(68 - 90), 0, a_ * 0 + math.radians(ang + 90))).parent = None
rbox('Steering_Hub', (0.09, 0.05, 0.09), (0.37, yof(2.5), 0.8), M['dash'], C_BODY, 0.02, (math.radians(-22), 0, 0))
rbox('Cabin_Floor', (1.5, 1.6, 0.03), (0, yof(2.85), 0.2), M['interior'], C_BODY, 0)
rbox('Rear_Bulkhead', (1.5, 0.04, 0.5), (0, yof(3.48), 0.6), M['interior'], C_BODY, 0.01, (math.radians(-25), 0, 0))
rbox('Rear_Shelf', (1.4, 0.6, 0.03), (0, yof(3.7), 0.86), M['dash'], C_BODY, 0)

# BVH of the (unsubdivided) body for projecting details onto the skin
dg = bpy.context.evaluated_depsgraph_get()
def body_bvh():
    bm2 = bmesh.new(); bm2.from_mesh(body.data); bm2.normal_update()
    t = BVHTree.FromBMesh(bm2); return t
BVH = body_bvh()

def hit(origin, direction):
    loc, nrm, idx, d = BVH.ray_cast(Vector(origin), Vector(direction).normalized(), 10.0)
    return (loc, nrm) if loc is not None else (None, None)

def snap(p):
    loc, nrm, idx, d = BVH.find_nearest(Vector(p))
    return loc, nrm

def proj_patch(name, outline, plane, c, mat, offset=0.003, rings=8, thickness=0.0):
    """Project a closed outline onto the body and fill it with a conforming patch.
    plane(u, v) -> (origin, direction) of the projection ray for outline point (u, v)."""
    n = len(outline)
    cu = sum(p[0] for p in outline) / n; cv = sum(p[1] for p in outline) / n
    bmp = bmesh.new(); grid = []
    for r in range(1, rings + 1):
        t = r / rings; row = []
        for u, v in outline:
            o, d = plane(cu + (u - cu) * t, cv + (v - cv) * t)
            loc, nrm = hit(o, d)
            if loc is None: loc, nrm = snap(Vector(o) + Vector(d) * 2)
            row.append(bmp.verts.new(loc + nrm * offset))
        grid.append(row)
    o, d = plane(cu, cv); loc, nrm = hit(o, d)
    if loc is None: loc, nrm = snap(Vector(o) + Vector(d) * 2)
    ctr = bmp.verts.new(loc + nrm * offset)
    for k in range(n): bmp.faces.new((ctr, grid[0][k], grid[0][(k + 1) % n]))
    for r in range(rings - 1):
        for k in range(n):
            k2 = (k + 1) % n
            bmp.faces.new((grid[r][k], grid[r + 1][k], grid[r + 1][k2], grid[r][k2]))
    bmesh.ops.recalc_face_normals(bmp, faces=bmp.faces)
    ob = bm_obj(name, bmp, c, mat)
    if thickness: add_mod(ob, 'SOLIDIFY', thickness=thickness, offset=1)
    return ob

def resample(poly, step=0.012, closed=True):
    pts = poly + ([poly[0]] if closed else [])
    out = []
    for a, b in zip(pts, pts[1:]):
        L_ = math.hypot(b[0] - a[0], b[1] - a[1]); n = max(1, int(L_ / step))
        for i in range(n): out.append((a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n))
    if not closed: out.append(poly[-1])
    return out

front_plane = lambda u, v: ((u, -3.5, v), (0, 1, 0))
rear_plane = lambda u, v: ((u, 3.5, v), (0, -1, 0))
def side_plane(sign):
    return lambda u, v: ((sign * 2.5, yof(u), v), (-sign, 0, 0))

def tube_on_surface(name, pts3, radius, c, mat, sink=0.0, ray=None):
    """A thin tube following points projected onto the skin (panel gaps, trims); ray = projection direction."""
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'
    cu.bevel_depth = radius; cu.bevel_resolution = 2; cu.use_fill_caps = True
    sp = cu.splines.new('POLY'); sp.points.add(len(pts3) - 1)
    for i, p in enumerate(pts3):
        loc, nrm = hit(p, ray) if ray else (None, None)
        if loc is None: loc, nrm = snap(p)
        q = loc - nrm * sink
        sp.points[i].co = (q.x, q.y, q.z, 1)
    ob = bpy.data.objects.new(name, cu); link(ob, c); cu.materials.append(mat)
    return ob

def closed_smooth(poly, it=3):
    """Round the corners of a closed polygon (Chaikin)."""
    pts = poly + [poly[0]]
    for _ in range(it):
        o = []
        for a, b in zip(pts, pts[1:]):
            o += [(0.75*a[0] + 0.25*b[0], 0.75*a[1] + 0.25*b[1]), (0.25*a[0] + 0.75*b[0], 0.25*a[1] + 0.75*b[1])]
        pts = o + [o[0]]
    return pts[:-1]
def curve_obj(name, pts, radius, mat, c, cyclic=False, res=2):
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = radius; cu.bevel_resolution = res; cu.use_fill_caps = not cyclic
    sp = cu.splines.new('POLY'); sp.points.add(len(pts) - 1); sp.use_cyclic_u = cyclic
    for i, p in enumerate(pts): sp.points[i].co = (p.x, p.y, p.z, 1)
    ob = link(bpy.data.objects.new(name, cu), c); cu.materials.append(mat)
    return ob
def unlink_active(name, c, mat=None):
    ob = bpy.context.active_object; ob.name = name
    for cl in ob.users_collection: cl.objects.unlink(ob)
    link(ob, c)
    if mat: ob.data.materials.append(mat)
    return ob

# ---------------------------------------------------------------- panel gaps: doors, clamshell bonnet, boot lid (thin, even grooves)
G = 0.0018
for sgn, nm in ((1, 'L'), (-1, 'R')):
    side = (-sgn, 0, 0)
    def sp(s, z): return Vector((sgn * 1.3, yof(s), z))
    front = [sp(lerp(1.98, 2.02, t), lerp(0.24, 0.85, t)) for t in [i / 24 for i in range(25)]]
    rear = [sp(3.2 + 0.06 * math.sin(t * math.pi / 2), lerp(0.24, 0.925, t)) for t in [i / 24 for i in range(25)]]
    tube_on_surface(f'Gap_Door_Front_{nm}', front, G, C_BODY, M['gap'], sink=0.001, ray=side)
    tube_on_surface(f'Gap_Door_Rear_{nm}', rear, G, C_BODY, M['gap'], sink=0.001, ray=side)
    # flush door handle: a slim recessed pad with its outline
    hs, hz = 2.98, 0.82
    hp = closed_smooth([(hs - 0.1, hz - 0.012), (hs + 0.1, hz - 0.012), (hs + 0.1, hz + 0.012), (hs - 0.1, hz + 0.012)], 3)
    proj_patch(f'Door_Handle_{nm}', hp, side_plane(sgn), C_DET, M['paint'], offset=0.0025, rings=3)
    tube_on_surface(f'Door_Handle_Gap_{nm}', [sp(u, v) for u, v in hp + [hp[0]]], 0.0012, C_BODY, M['gap'], sink=0.0005, ray=side)
    # bonnet seam just inside the fender crown
    pts = [Vector((sgn * (0.6 + 0.12 * smooth01(s / 1.9)), yof(s), 2.0)) for s in [0.1 + i * 0.045 for i in range(41)]]
    tube_on_surface(f'Gap_Bonnet_{nm}', pts, G, C_BODY, M['gap'], sink=0.001, ray=(0, 0, -1))
tube_on_surface('Gap_Bonnet_Front', [Vector((x, yof(0.11), 2.0)) for x in [-0.6 + i * 0.03 for i in range(41)]], G, C_BODY, M['gap'], sink=0.001, ray=(0, 0, -1))
tube_on_surface('Gap_Bootlid', [Vector((x, yof(4.12), 2.0)) for x in [-0.66 + i * 0.03 for i in range(45)]], G, C_BODY, M['gap'], sink=0.001, ray=(0, 0, -1))

# ---------------------------------------------------------------- grille: wide rounded opening, narrow vertical chrome slats, plain roundel
GRILLE = closed_smooth([(-0.42, 0.49), (0.42, 0.49), (0.52, 0.45), (0.545, 0.34), (0.5, 0.25), (-0.5, 0.25), (-0.545, 0.34), (-0.52, 0.45)], 4)
def hit_full(origin, direction):
    loc, nrm, idx, d = FULL_BVH.ray_cast(Vector(origin), Vector(direction).normalized(), 10.0)
    return (loc, nrm) if loc is not None else (None, None)
cavM = principled('Opening_Cavity', (0.008, 0.008, 0.009), rough=0.55)
_of = {'grille': [], 'intake': [], 'dam': []}
for f in open_faces:
    c_ = sum((V[i] for i in f), Vector()) / len(f)
    _of[open_kind(c_.x, c_.y, c_.z) or 'dam'].append(f)
cavity('Grille_Cavity', _of['grille'], 0.09, cavM, C_DET)
cavity('Air_Intake_Cavities', _of['intake'], 0.07, cavM, C_DET)
cavity('Lower_Air_Dam_Cavity', _of['dam'], 0.05, cavM, C_DET)
def span_at(poly, x):
    zs = []
    pts = poly + [poly[0]]
    for a, b in zip(pts, pts[1:]):
        if (a[0] - x) * (b[0] - x) <= 0 and a[0] != b[0]:
            t = (x - a[0]) / (b[0] - a[0]); zs.append(a[1] + (b[1] - a[1]) * t)
    return (min(zs), max(zs)) if len(zs) >= 2 else None
sb = bmesh.new()
def span_x(poly, z):
    xs = []
    pts = poly + [poly[0]]
    for a, b in zip(pts, pts[1:]):
        if (a[1] - z) * (b[1] - z) <= 0 and a[1] != b[1]:
            t = (z - a[1]) / (b[1] - a[1]); xs.append(a[0] + (b[0] - a[0]) * t)
    return (min(xs), max(xs)) if len(xs) >= 2 else None
NBAR = 6
for i in range(NBAR):
    z = lerp(0.272, 0.468, i / (NBAR - 1))
    span = span_x(GRILLE, z)
    if not span: continue
    x0, x1 = span[0] + 0.016, span[1] - 0.016
    row = []
    for j in range(31):
        x = lerp(x0, x1, j / 30)
        loc, _ = hit_full((x, -3.5, z), (0, 1, 0)); row.append(loc)
    vs = []
    for loc in row:      # bar: 9 mm tall, 6 cm deep, set 5 mm back, its face tilted a touch downward
        f = loc + Vector((0, 0.005, 0)); bk = loc + Vector((0, 0.065, -0.004))
        vs.append([sb.verts.new(f + Vector((0, 0, -0.0045))), sb.verts.new(f + Vector((0, 0, 0.0045))),
                   sb.verts.new(bk + Vector((0, 0, 0.0045))), sb.verts.new(bk + Vector((0, 0, -0.0045)))])
    for a, b in zip(vs, vs[1:]):
        for k in range(4): sb.faces.new((a[k], a[(k + 1) % 4], b[(k + 1) % 4], b[k]))
    sb.faces.new(vs[0][::-1]); sb.faces.new(vs[-1])
bmesh.ops.recalc_face_normals(sb, faces=sb.faces)
slats = bm_obj('Grille_Slats', sb, C_DET, M['slat'])
add_mod(slats, 'BEVEL', width=0.0012, segments=2)
frame = [hit_full((u, -3.5, v), (0, 1, 0))[0] + Vector((0, -0.001, 0)) for u, v in resample(GRILLE, 0.012)]
curve_obj('Grille_Surround', frame, 0.0045, M['slat'], C_DET, cyclic=True, res=3)
# no badge on this car

# ---------------------------------------------------------------- headlights: slim, swept back along the bonnet/fender edge
def corner_plane(sign):
    d = Vector((-sign * 0.3, 1, -0.14)).normalized()
    return lambda u, v: (tuple(Vector((sign * u, -2.62, v)) - d * 1.6), tuple(d))
# swept teardrop outline: low, pointed inner end beside the grille corner, rising and widening outboard,
# its top edge following the bonnet shut line and its outer end wrapping round onto the fender
HL = closed_smooth([(0.43, 0.585), (0.55, 0.604), (0.7, 0.628), (0.84, 0.652), (0.93, 0.668), (0.962, 0.664),
                    (0.966, 0.632), (0.93, 0.618), (0.84, 0.604), (0.7, 0.584), (0.55, 0.566), (0.45, 0.558), (0.425, 0.568)], 3)
lensM = principled('Headlight_Lens_Clear', (0.95, 0.97, 1.0), rough=0.02, transmission=1.0, ior=1.5, coat=1.0)
hlHousing = principled('Headlight_Housing_Inner', (0.07, 0.075, 0.082), metallic=0.8, rough=0.28)
bezelM = principled('Headlight_Bezel', (0.3, 0.31, 0.33), metallic=1.0, rough=0.18)
projM = principled('Projector_Lens', (0.02, 0.022, 0.026), rough=0.02, coat=1.0, spec=0.8)
def circ(cu, cv, r, n=28): return [(cu + r * math.cos(2 * math.pi * i / n), cv + r * 0.92 * math.sin(2 * math.pi * i / n)) for i in range(n)]
def tilt(poly, sgn): return poly if sgn > 0 else poly[::-1]
for sgn, nm in ((1, 'L'), (-1, 'R')):
    pl = corner_plane(sgn)
    out = tilt(resample(HL, 0.008), sgn)
    # dark housing (back of the unit), a slightly inset bezel, then the internal modules, then a clear outer lens
    proj_patch(f'Headlight_Housing_{nm}', out, pl, C_DET, hlHousing, offset=0.001, rings=8)
    for i, cu in enumerate((0.62, 0.7, 0.78)):
        cv = 0.578 + 0.165 * (cu - 0.5)
        proj_patch(f'Headlight_Reflector_{nm}_{i+1}', tilt(circ(cu, cv, 0.017), sgn), pl, C_DET, M['reflect'], offset=0.0035, rings=4)
        proj_patch(f'Headlight_Projector_{nm}_{i+1}', tilt(circ(cu, cv, 0.0105), sgn), pl, C_DET, projM, offset=0.0055, rings=3)
    for k, (dv, top) in enumerate(((0.0, True), (0.0, False))):
        if top: drl = [(0.47, 0.584), (0.55, 0.596), (0.7, 0.62), (0.84, 0.644), (0.93, 0.658)]
        else:   drl = [(0.47, 0.566), (0.55, 0.574), (0.7, 0.592), (0.84, 0.612), (0.93, 0.626)]
        band = closed_smooth([(u, v) for u, v in drl] + [(u, v - 0.0055) for u, v in reversed(drl)], 1)
        proj_patch(f'Headlight_DRL_{nm}_{k+1}', tilt(resample(band, 0.005), sgn), pl, C_DET, M['led'], offset=0.0045, rings=2)
    lens = proj_patch(f'Headlight_Lens_{nm}', out, pl, C_DET, lensM, offset=0.009, rings=8)
    # chrome-free satin black seal around the lens so it reads as a separate, flush unit
    ring = [Vector(pl(u, v)[0]) for u, v in tilt(resample(HL, 0.01), sgn)]
    tube_on_surface(f'Headlight_Seal_{nm}', ring + [ring[0]], 0.0048, C_DET, M["satin"], sink=0.0, ray=pl(0.7, 0.6)[1])

# ---------------------------------------------------------------- bumper: corner intakes with a fin, lower intake, splitter
# corner intakes: tall, tapered openings joined to the lower air dam; two body-colour blades and a slim air-curtain slot
INTAKE = closed_smooth([(0.585, 0.445), (0.75, 0.46), (0.81, 0.41), (0.815, 0.26), (0.78, 0.2), (0.6, 0.195), (0.565, 0.3)], 2)
for sgn, nm in ((1, 'L'), (-1, 'R')):
    out = [(sgn * u, v) for u, v in resample(INTAKE, 0.01)]
    if sgn < 0: out = out[::-1]
    for zb in (0.29, 0.36):
        fin = [hit_full((sgn * (0.58 + 0.012 * i), -3.5, zb + 0.0008 * i), (0, 1, 0))[0] for i in range(21)]
        curve_obj(f'Intake_Blade_{nm}', [p + Vector((0, 0.006, 0)) for p in fin if p is not None], 0.006, M['satin'], C_DET)
    SLOT = closed_smooth([(0.875, 0.44), (0.9, 0.44), (0.905, 0.26), (0.885, 0.26)], 1)
    o2 = [(sgn * u, v) for u, v in resample(SLOT, 0.006)]
    if sgn < 0: o2 = o2[::-1]
    proj_patch(f'Air_Curtain_{nm}', o2, front_plane, C_DET, M['black'], offset=0.0015, rings=3)
LOW = closed_smooth([(-0.8, 0.205), (-0.56, 0.215), (0.56, 0.215), (0.8, 0.205), (0.86, 0.16), (0.8, 0.14), (-0.8, 0.14), (-0.86, 0.16)], 2)
SPL = [(-0.9, 0.14), (0.9, 0.14), (0.93, 0.115), (-0.93, 0.115)]
proj_patch('Front_Splitter', resample(SPL, 0.02), front_plane, C_DET, M['satin'], offset=0.012, rings=3, thickness=0.016)

# ---------------------------------------------------------------- side: vent behind the front wheel, skirts
for sgn, nm in ((1, 'L'), (-1, 'R')):
    VENT = closed_smooth([(1.45, 0.62), (1.495, 0.62), (1.56, 0.42), (1.515, 0.42)], 2)
    proj_patch(f'Side_Vent_{nm}', resample(VENT, 0.008), side_plane(sgn), C_DET, M['black'], offset=0.002, rings=4)
    for k in range(2):
        z0, z1 = 0.62 - k * 0.0, 0.44
        pts = [hit((sgn * 2.0, yof(lerp(1.47 + k * 0.03, 1.535 + k * 0.03, t)), lerp(0.6, 0.44, t)), (-sgn, 0, 0))[0] for t in [i / 12 for i in range(13)]]
        if k == 0: curve_obj(f'Side_Vent_Trim_{nm}', [p + Vector((sgn * 0.004, 0, 0)) for p in pts if p is not None], 0.003, M['chrome'], C_DET)
    # skirt: body-coloured sill blade with a black lower lip, following the rocker
    sb2 = bmesh.new(); rows = []
    for i in range(41):
        s = lerp(S_FA + AR + 0.03, S_RA - AR - 0.03, i / 40)
        y = yof(s)
        loc, nrm = hit((sgn * 2.0, y, 0.2), (-sgn, 0, 0))
        x = loc.x if loc else sgn * cr(WID, s) * 0.95
        taper = smooth01(min(i, 40 - i) / 6)
        prof = [(x - sgn * 0.02, 0.112), (x + sgn * 0.022 * taper, 0.118), (x + sgn * 0.02 * taper, 0.15), (x - sgn * 0.004, 0.2)]
        rows.append([sb2.verts.new((px, y, pz)) for px, pz in prof])
    for a, b in zip(rows, rows[1:]):
        for k in range(3): sb2.faces.new((a[k], a[k + 1], b[k + 1], b[k]))
    bmesh.ops.recalc_face_normals(sb2, faces=sb2.faces)
    sk = bm_obj(f'Side_Skirt_{nm}', sb2, C_DET, M['satin'])
    add_mod(sk, 'SOLIDIFY', thickness=0.003); add_mod(sk, 'SUBSURF', levels=1, render_levels=2)

# ---------------------------------------------------------------- mirrors: aero housings on slim stalks from the door shoulder
for sgn, nm in ((1, 'L'), (-1, 'R')):
    s = 2.12; z = 0.8
    base, n_ = hit((sgn * 2.0, yof(s), z), (-sgn, 0, 0))
    bm3 = bmesh.new()
    bmesh.ops.create_uvsphere(bm3, u_segments=36, v_segments=18, radius=1.0)
    for v in bm3.verts:
        x, y, zz = v.co
        t_ = (y + 1) / 2                               # 0 at the front, 1 at the glass face
        sx = 0.1 * (0.55 + 0.45 * math.sqrt(max(t_, 0)))
        sz = 0.054 * (0.6 + 0.4 * math.sqrt(max(t_, 0)))
        v.co = Vector((x * sx, y * 0.066 + (0.016 if y > 0 else 0) * y, zz * sz))
    mo = bm_obj(f'Mirror_{nm}', bm3, C_DET, M['paint'])
    mo.location = Vector((sgn * (abs(base.x) + 0.085), base.y + 0.04, 0.925)); mo.rotation_euler = (0, 0, -sgn * 0.08)
    mg = bmesh.new(); bmesh.ops.create_circle(mg, cap_ends=True, segments=36, radius=1.0)
    for v in mg.verts: v.co = Vector((v.co.x * 0.08, 0, v.co.y * 0.043))
    mgo = bm_obj(f'Mirror_Glass_{nm}', mg, C_DET, M['mirror'])
    mgo.location = mo.location + Vector((0, 0.081, 0)); mgo.rotation_euler = (0, 0, -sgn * 0.08)
    # stalk: a swept blade from the door to the housing
    p0 = base + Vector((-sgn * 0.01, 0.03, 0.035)); p1 = mo.location + Vector((-sgn * 0.06, 0.02, -0.03))
    stalk = [p0.lerp(p1, t) + Vector((0, 0, 0.025 * math.sin(t * math.pi))) for t in [i / 8 for i in range(9)]]
    st_ = curve_obj(f'Mirror_Stalk_{nm}', stalk, 0.012, M['paint'], C_DET); st_.data.bevel_resolution = 4
    st_.scale = (1, 1, 1)

# ---------------------------------------------------------------- rear: raised wing on two stands, segmented taillights, finned diffuser, quad exhausts
deck_s = 4.4
# ducktail: a slim body-coloured lip along the tail edge
lip = [hit((x, yof(4.6), 2.0), (0, 0, -1))[0] for x in [-0.78 + 0.03 * i for i in range(53)]]
curve_obj('Rear_Lip', [p + Vector((0, 0, 0.004)) for p in lip if p is not None], 0.011, M['paint'], C_DET)
# fuel filler door on the right rear fender
fd = closed_smooth([(3.47, 0.8), (3.63, 0.8), (3.63, 0.92), (3.47, 0.92)], 3)
tube_on_surface('Gap_Fuel_Door', [Vector((-1.3, yof(u), v)) for u, v in fd + [fd[0]]], 0.0016, C_BODY, M['gap'], sink=0.001, ray=(1, 0, 0))
# taillights: one continuous light bar across the tail, darker housing above and below
for k, (zc, hh, mat_) in enumerate(((0.872, 0.026, M['black']), (0.872, 0.0085, M['tail']))):
    bar = []
    for x in [-0.86 + 0.02 * i for i in range(87)]:
        loc, _ = hit((x, 3.5, zc), (0, -1, 0))
        if loc is not None: bar.append(loc)
    cu_ = curve_obj(f'Taillight_Bar_{k+1}', [p + Vector((0, 0.002 + 0.002 * k, 0)) for p in bar], hh, mat_, C_DET)
    cu_.data.bevel_resolution = 1
    cu_.scale = (1, 1, 1)
PLATE = [(-0.26, 0.48), (0.26, 0.48), (0.26, 0.595), (-0.26, 0.595)]
proj_patch('Rear_Plate_Recess', resample(PLATE, 0.012), rear_plane, C_DET, M['satin'], offset=0.002, rings=3)
DIFF = closed_smooth([(-0.9, 0.39), (0.9, 0.39), (0.95, 0.26), (0.9, 0.14), (-0.9, 0.14), (-0.95, 0.26)], 1)
proj_patch('Rear_Diffuser', resample(DIFF, 0.02), rear_plane, C_DET, M['satin'], offset=0.003, rings=4)
for xf in (-0.27, -0.09, 0.09, 0.27):
    pts = []
    for zz in (0.22, 0.3):
        lc, _ = hit((xf, 3.5, zz), (0, -1, 0)); pts.append(lc)
    if None in pts: continue
    fb = bmesh.new(); bmesh.ops.create_cube(fb, size=1.0)
    for v in fb.verts: v.co = Vector((v.co.x * 0.006, v.co.y * 0.12, v.co.z * 0.07))
    fo = bm_obj('Diffuser_Fin', fb, C_DET, M['satin'], smooth=False)
    fo.location = ((pts[0] + pts[1]) / 2) + Vector((0, -0.03, 0.0)); fo.rotation_euler = (math.radians(-8), 0, 0)
for sgn in (1, -1):
    for dx in (0.0, 0.135):
        x = sgn * (0.52 + dx)
        loc, nrm = hit((x, 3.5, 0.25), (0, -1, 0))
        bpy.ops.mesh.primitive_cylinder_add(vertices=4, radius=0.055, depth=0.09, location=loc + Vector((0, -0.025, 0)), rotation=(math.pi / 2, 0, math.pi / 4))
        ex = unlink_active('Exhaust_Tip', C_DET, M['chrome']); ex.scale = (1.0, 0.62, 1)
        add_mod(ex, 'SOLIDIFY', thickness=0.004); add_mod(ex, 'BEVEL', width=0.008, segments=3)
        bm_e = bmesh.new(); bm_e.from_mesh(ex.data)
        bmesh.ops.delete(bm_e, geom=[f for f in bm_e.faces if abs(f.normal.z) > 0.9], context='FACES'); bm_e.to_mesh(ex.data); bm_e.free()

# ---------------------------------------------------------------- wheels: 21" five-twin-spoke graphite alloys, low-profile tyres, brakes
def lathe(name, prof, segs, c, mat, smooth=True):
    """Revolve (radius, axial) points around the local X axis."""
    b = bmesh.new(); rings = []
    for i in range(segs):
        a = 2 * math.pi * i / segs
        rings.append([b.verts.new((w, r * math.cos(a), r * math.sin(a))) for r, w in prof])
    for i in range(segs):
        A, B_ = rings[i], rings[(i + 1) % segs]
        for k in range(len(prof) - 1): b.faces.new((A[k], A[k + 1], B_[k + 1], B_[k]))
    bmesh.ops.recalc_face_normals(b, faces=b.faces)
    return bm_obj(name, b, c, mat, smooth)

RIM = 0.268                        # 21"
for (sa, tw, tag) in ((S_FA, 0.285, 'F'), (S_RA, 0.305, 'R')):
    for sgn, side in ((1, 'L'), (-1, 'R')):
        tag2 = tag + side
        x = sgn * (0.84 if tag == 'F' else 0.83)
        loc = Vector((x, yof(sa), RW)); hw = tw / 2
        # tyre: square shoulders, short bulging sidewall, four tread grooves
        tread = []
        for g in (-0.6, -0.2, 0.2, 0.6):
            c0 = g * hw
            tread += [(RW, c0 - 0.012), (RW - 0.008, c0 - 0.008), (RW - 0.008, c0 + 0.008), (RW, c0 + 0.012)]
        tprof = ([(RIM + 0.004, -hw + 0.014), (RIM + 0.03, -hw + 0.002), (RW - 0.04, -hw - 0.004), (RW - 0.012, -hw + 0.012), (RW - 0.002, -hw + 0.04)]
                 + tread + [(RW - 0.002, hw - 0.04), (RW - 0.012, hw - 0.012), (RW - 0.04, hw + 0.004), (RIM + 0.03, hw - 0.002), (RIM + 0.004, hw - 0.014)])
        tyre = lathe(f'Tyre_{tag2}', tprof, 96, C_WHEELS, M['rubber'])
        # wheel: barrel, polished-edge lip, dished face
        wprof = [(RIM - 0.014, -hw + 0.012), (RIM + 0.008, -hw + 0.016), (RIM + 0.008, -hw + 0.03), (RIM - 0.014, -hw + 0.034),
                 (RIM - 0.014, hw - 0.034), (RIM + 0.014, hw - 0.024), (RIM + 0.014, hw - 0.006), (RIM - 0.002, hw - 0.001), (RIM - 0.02, hw - 0.012)]
        rim = lathe(f'Wheel_{tag2}', wprof, 96, C_WHEELS, M['wheel'])
        wb = bmesh.new(); wb.from_mesh(rim.data)
        # ten Y-spokes: a slim beam from the hub that splits into two arms towards the rim (concave face)
        def beam(r0, a0, r1, a1, w0, w1, x0, x1, d0, d1):
            q = []
            for (r, a, w, xx, dep) in ((r0, a0, w0, x0, d0), (r1, a1, w1, x1, d1)):
                ca, sa_ = math.cos(a), math.sin(a)
                for ts in (-1, 1):
                    for dd in (0, -dep):
                        q.append(wb.verts.new(Vector((xx + dd, r * ca, r * sa_)) + Vector((0, -sa_, ca)) * (ts * w / 2)))
            A, B_ = q[:4], q[4:]
            for f in ((0, 2), (3, 1), (1, 0), (2, 3)): wb.faces.new((A[f[0]], A[f[1]], B_[f[1]], B_[f[0]]))
            wb.faces.new((q[0], q[1], q[3], q[2])); wb.faces.new((q[4], q[6], q[7], q[5]))
        r0, rm, r1 = 0.078, 0.175, RIM - 0.012
        x0, xm, x1 = hw - 0.072, hw - 0.04, hw - 0.016
        for i in range(10):
            a = 2 * math.pi * i / 10
            beam(r0, a, rm + 0.01, a, 0.026, 0.02, x0, xm, 0.036, 0.03)
            for da in (-0.085, 0.085):
                beam(rm - 0.004, a + da * 0.25, r1, a + da, 0.014, 0.011, xm, x1, 0.028, 0.022)
        hub = bmesh.ops.create_cone(wb, cap_ends=True, segments=40, radius1=0.092, radius2=0.082, depth=0.05)
        for v in hub['verts']: v.co = Matrix.Rotation(math.pi / 2, 4, 'Y') @ v.co + Vector((hw - 0.08, 0, 0))
        bmesh.ops.recalc_face_normals(wb, faces=wb.faces)
        wb.to_mesh(rim.data); wb.free()
        for p in rim.data.polygons: p.use_smooth = True
        add_mod(rim, 'BEVEL', width=0.0025, segments=2, limit_method='ANGLE')
        add_mod(rim, 'WEIGHTED_NORMAL')
        cap = lathe(f'Wheel_Cap_{tag2}', [(0.0, hw - 0.05), (0.03, hw - 0.051), (0.042, hw - 0.056), (0.046, hw - 0.064)], 40, C_WHEELS, M['chrome'])
        cap.parent = rim
        for i in range(5):
            a = 2 * math.pi * i / 5 + math.pi / 5
            nut = lathe(f'Lug_Nut_{tag2}', [(0.0, hw - 0.052), (0.008, hw - 0.053), (0.009, hw - 0.066)], 6, C_WHEELS, M['chrome'], smooth=False)
            nut.location = (0, 0.06 * math.cos(a), 0.06 * math.sin(a)); nut.parent = rim
        # brakes: vented disc with a dark hat, a big caliper at the rear of the disc
        disc = lathe(f'Brake_Disc_{tag2}', [(0.1, -0.017), (0.2, -0.017), (0.2, 0.017), (0.1, 0.017)], 64, C_WHEELS, M['disc'])
        disc.location = (hw - 0.14, 0, 0); disc.parent = rim
        hat = lathe(f'Brake_Hat_{tag2}', [(0.0, 0.02), (0.1, 0.02), (0.1, -0.02)], 40, C_WHEELS, M['hat'])
        hat.location = (hw - 0.12, 0, 0); hat.parent = rim
        cb = bmesh.new(); bmesh.ops.create_cube(cb, size=1.0)
        for v in cb.verts: v.co = Vector((v.co.x * 0.08, v.co.y * 0.17, v.co.z * 0.055))
        cal = bm_obj(f'Brake_Caliper_{tag2}', cb, C_WHEELS, M['caliper'], smooth=False)
        add_mod(cal, 'BEVEL', width=0.016, segments=3)
        ang = math.radians(28 if tag == 'F' else 152)       # behind the axle, towards the car's centre
        cal.location = (hw - 0.125, 0.17 * math.cos(ang), 0.17 * math.sin(ang)); cal.rotation_euler = (ang - math.pi / 2, 0, 0); cal.parent = rim
        for ob in (tyre, rim):
            ob.location = loc
            ob.rotation_euler = (0, 0, 0 if sgn > 0 else math.pi)

# inner wheel wells (dark), so the arches don't show through
for sa, nm in ((S_FA, 'Front'), (S_RA, 'Rear')):
    b = bmesh.new(); rings = []
    for i in range(29):
        a = math.pi * (-0.12 + 1.24 * i / 28)
        rings.append([b.verts.new((x, yof(sa) + math.cos(a) * (AR + 0.006), RW + math.sin(a) * (AR + 0.006))) for x in (-0.95, -0.64, 0.64, 0.95)])
    for A, B_ in zip(rings, rings[1:]):
        for k in (0, 2): b.faces.new((A[k], A[k + 1], B_[k + 1], B_[k]))     # one liner per side, clear of the bonnet
    bmesh.ops.recalc_face_normals(b, faces=b.faces)
    bm_obj(f'Wheel_Well_{nm}', b, C_BODY, M['satin'])

# ---------------------------------------------------------------- collections by role
ROLES = [
    ('Glass', ('Glass', 'Window_Seals')),
    ('Lights', ('Headlight_', 'Taillight')),
    ('Spoiler', ('Rear_Spoiler', 'Spoiler_')),
    ('Grille_Emblem', ('Grille_', 'Emblem', 'Air_', 'Intake_', 'Lower_Air_Dam', 'Front_Splitter')),
    ('Wheels_Brakes', ('Wheel_', 'Tyre_', 'Brake_', 'Lug_Nut')),
    ('Interior', ('Seat_', 'Door_Card', 'Headliner', 'Dashboard', 'Dash_', 'Instrument', 'Centre_', 'Gear_', 'Steering', 'Cabin_', 'Rear_Bulkhead', 'Rear_Shelf', 'Interior_')),
    ('Exterior_Trim', ('Mirror', 'Side_Vent', 'Side_Skirt', 'Rear_Diffuser', 'Diffuser_', 'Exhaust', 'Rear_Plate')),
]
role_coll = {nm: coll(nm, C_CAR) for nm, _ in ROLES}
for ob in list(C_BODY.objects) + list(C_DET.objects) + list(C_WHEELS.objects):
    if ob.name.startswith('Wheel_Well'): continue
    for nm, prefixes in ROLES:
        if ob.name.startswith(prefixes):
            for c_ in ob.users_collection: c_.objects.unlink(ob)
            role_coll[nm].objects.link(ob); break
C_DET.name = 'Details_Misc'
# ---------------------------------------------------------------- parent everything to one root
root = bpy.data.objects.new('Roadster_Root', None); link(root, C_CAR); root.empty_display_type = 'ARROWS'; root.empty_display_size = 1.0
for c in [C_BODY, C_DET, C_WHEELS] + list(role_coll.values()):
    for ob in c.objects:
        if ob.parent is None: ob.parent = root

# ---------------------------------------------------------------- studio: curved backdrop, soft lights, cameras
prof = [(0.0, 0.0), (6.0, 0.0), (14.0, 0.0)] + [(14.0 + 8 * math.sin(a), 8 - 8 * math.cos(a)) for a in [i * math.pi / 2 / 16 for i in range(1, 17)]] + [(22.0, 10.0)]
cyc = lathe('Studio_Backdrop', [(r, z) for r, z in prof], 96, C_STUDIO, M['studio'])
cyc.rotation_euler = (0, math.radians(-90), 0)            # lathe axis X → Z (a bowl around the car)


def area(name, loc, rot, size, power, color=(1, 1, 1), shape='RECTANGLE', size_y=None):
    l = bpy.data.lights.new(name, 'AREA'); l.energy = power; l.color = color; l.shape = shape; l.size = size
    if size_y: l.size_y = size_y
    ob = bpy.data.objects.new(name, l); link(ob, C_STUDIO); ob.location = loc; ob.rotation_euler = rot; ob.visible_camera = False
    return ob
def aim(ob, target=(0, 0, 0.5)):
    d = Vector(target) - ob.location
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
k = area('Key_Light', (3.5, -4.5, 5.0), (0, 0, 0), 5.0, 800, (1, 0.98, 0.95), 'RECTANGLE', 2.5); aim(k)
f = area('Fill_Light', (-5.5, -2.0, 2.5), (0, 0, 0), 5.0, 300, (0.92, 0.96, 1.0)); aim(f)
r_ = area('Rim_Light', (-2.0, 6.0, 3.0), (0, 0, 0), 4.0, 1100); aim(r_)
t = area('Top_Softbox', (0, 0, 5.5), (0, 0, 0), 8.0, 420, (1, 1, 1), 'RECTANGLE', 4.5); aim(t, (0, 0, 0))

world = bpy.data.worlds.new('Studio_World'); scene.world = world; world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.12, 0.13, 0.15, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.35

def camera(name, loc, target, lens=50):
    cd = bpy.data.cameras.new(name); cd.lens = lens
    ob = bpy.data.objects.new(name, cd); link(ob, C_STUDIO); ob.location = loc; aim(ob, target)
    return ob
cam = camera('Camera_Front34', (5.2, -7.4, 1.75), (0.0, -0.25, 0.5), 50)
camera('Camera_Rear34', (-5.2, 7.4, 1.85), (0.0, 0.25, 0.55), 50)
# inspection views: long-lens cameras from 13 m (near-orthographic), the whole car with comfortable margins
ortho_like = lambda name, loc, target, lens: camera(name, loc, target, lens)
ortho_like('Camera_Front', (0, -13.0, 1.0), (0, 0, 0.6), 140)
ortho_like('Camera_Rear', (0, 13.0, 1.0), (0, 0, 0.6), 140)
ortho_like('Camera_Side', (13.0, 0, 1.0), (0, 0, 0.6), 78)
ortho_like('Camera_Side_R', (-13.0, 0, 1.0), (0, 0, 0.6), 78)
top = camera('Camera_Top', (0, 0, 13.0), (0, 0, 0), 78); top.rotation_euler = (0, 0, math.pi / 2)
camera('Camera_Hero_Front34', (4.5, -6.3, 1.4), (0.0, -0.3, 0.52), 50)
camera('Camera_Hero_Rear34', (-4.5, 6.3, 1.5), (0.0, 0.3, 0.55), 50)
camera('Camera_Interior', (2.2, -1.6, 1.75), (0.1, 0.4, 0.75), 40)
camera('Camera_Detail_Front', (1.6, -4.0, 0.95), (0.55, -2.3, 0.55), 50)
scene.camera = bpy.data.objects['Camera_Hero_Front34']

# render settings: Cycles, denoised, filmic look
scene.render.engine = 'CYCLES'
scene.cycles.samples = 256
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
scene.view_settings.view_transform = 'AgX'
scene.view_settings.look = 'AgX - Medium High Contrast'

bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True)
print('saved', OUT, 'objects:', len(bpy.data.objects))

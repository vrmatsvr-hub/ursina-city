"""
world.py  -  core engine helpers + the city itself
====================================================

Contents
  * colour helpers and a procedural MeshBuilder (boxes, wedges, beams,
    cylinders, cones, spheres, rings) - every model in the game is built here,
    no external model files are needed
  * a custom GLSL "lit" shader: sun/moon light, sky/ground ambient,
    16 dynamic point lights (street lamps, explosions, headlights), fog
  * a procedural sky-dome shader (gradient, sun + moon discs, stars)
  * procedural sound synthesis (numpy -> .wav through the `wave` module)
    and a small SoundBank that plays them through Panda3D
  * particles (additive sparks/fire and alpha smoke), scorch decals,
    tyre marks
  * city generation: asphalt roads with markings and zebra crossings,
    sidewalks with curbs, Dutch row houses, modern blocks, enterable
    shops, the E-tuning garage, business properties, a park with the
    fireworks dealer, parking lots, streetlights, trees and a dike border
  * collision world (AABB spatial hash) + ground height + camera raycasts
  * the day/night cycle that drives every light in the scene
  * knock-able props (bins, cones, boxes)
"""
from ursina import *
import math
import random
import os
import wave
import heapq
import builtins
from collections import deque
from panda3d.core import (Shader as PandaShader, PTA_LVecBase4f, LVecBase4f, LVecBase3f,
                          TransparencyAttrib, Filename, PNMImage, ColorBlendAttrib,
                          Texture as PandaTexture)

try:
    Color
except NameError:                       # some Ursina versions don't export Color at top level
    from ursina.color import Color

try:
    import numpy as np
except Exception:          # numpy is optional - the game runs silently without it
    np = None


# ============================================================== constants
N_BLOCKS = 7                       # 7 x 7 city blocks
CELL = 52.0                        # road centre to road centre
ROAD_W = 12.0
HALF_ROAD = ROAD_W / 2.0
SIDEWALK = 3.5
CURB_H = 0.18
LANE_OFFSET = 2.9                  # traffic drives on the right, 2.9 m from the centre line
CITY_HALF = N_BLOCKS * CELL / 2.0  # 130
ROADS = [-CITY_HALF + i * CELL for i in range(N_BLOCKS + 1)]
ASPHALT_MIN = ROADS[0] - HALF_ROAD
ASPHALT_MAX = ROADS[-1] + HALF_ROAD
BOUNDARY = CITY_HALF + 36.0        # the dike around the city
DAY_LENGTH = 480.0                 # seconds for a full 24h cycle
START_HOUR = 16.8                  # start in the late afternoon -> sunset soon

HERE = os.path.dirname(os.path.abspath(__file__))
SOUND_DIR = os.path.join(HERE, 'generated_sounds')


# ============================================================== small math / colour helpers
def rgb(r, g, b, a=255):
    return Color(r / 255.0, g / 255.0, b / 255.0, a / 255.0)


def clampf(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def lerpf(a, b, t):
    return a + (b - a) * t


def smoothstep(e0, e1, x):
    t = clampf((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def wrap_angle(a):
    return (a + 180.0) % 360.0 - 180.0


def lerp_angle(a, b, t):
    return a + wrap_angle(b - a) * t


def col_lerp(a, b, t):
    t = clampf(t, 0.0, 1.0)
    return Color(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                 a[2] + (b[2] - a[2]) * t, a[3] + (b[3] - a[3]) * t)


def col_mul(c, k, alpha=None):
    return Color(c[0] * k, c[1] * k, c[2] * k, c[3] if alpha is None else alpha)


def jitter(c, amount=0.06):
    k = 1.0 + random.uniform(-amount, amount)
    return Color(clampf(c[0] * k, 0, 1), clampf(c[1] * k, 0, 1), clampf(c[2] * k, 0, 1), c[3])


def tup_lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a)))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _normalize(a):
    l = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    if l < 1e-9:
        return (0.0, 1.0, 0.0)
    return (a[0] / l, a[1] / l, a[2] / l)


def heading_vectors(heading_deg):
    """forward and right vectors (x, z) for a yaw in degrees (Ursina: +z forward, +x right)."""
    h = math.radians(heading_deg)
    return (math.sin(h), math.cos(h)), (math.cos(h), -math.sin(h))


def yaw_towards(dx, dz):
    return math.degrees(math.atan2(dx, dz))


# ============================================================== shaders
LIT_VERT = '''
#version 140
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
uniform mat4 p3d_ModelViewMatrix;
in vec4 p3d_Vertex;
in vec3 p3d_Normal;
in vec4 p3d_Color;
in vec2 p3d_MultiTexCoord0;
out vec3 v_normal;
out vec4 v_color;
out vec3 v_world;
out float v_dist;
out vec2 v_uv;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    v_world = (p3d_ModelMatrix * p3d_Vertex).xyz;
    v_normal = mat3(p3d_ModelMatrix) * p3d_Normal;
    v_color = p3d_Color;
    v_dist = length((p3d_ModelViewMatrix * p3d_Vertex).xyz);
    v_uv = p3d_MultiTexCoord0;
}
'''

LIT_FRAG = '''
#version 140
uniform vec4 p3d_ColorScale;
uniform vec3 sun_dir;
uniform vec3 sun_color;
uniform vec3 ambient_color;
uniform vec3 ground_color;
uniform vec3 up_dir;
uniform vec3 fog_color;
uniform float fog_density;
uniform float emissive;
uniform vec4 lights[16];
uniform vec4 light_colors[16];
uniform float light_count;
in vec3 v_normal;
in vec4 v_color;
in vec3 v_world;
in float v_dist;
in vec2 v_uv;
out vec4 frag;
void main() {
    vec4 base = v_color * p3d_ColorScale;
    vec3 n = normalize(v_normal);
    float ndl = max(dot(n, sun_dir), 0.0);
    float hemi = dot(n, up_dir) * 0.5 + 0.5;
    vec3 light = mix(ground_color, ambient_color, hemi) + sun_color * ndl;
    for (int i = 0; i < 16; i++) {
        if (float(i) >= light_count) break;
        float r = lights[i].w;
        if (r > 0.01) {
            vec3 d = lights[i].xyz - v_world;
            float dist = length(d);
            float att = clamp(1.0 - dist / r, 0.0, 1.0);
            att *= att;
            float lam = max(dot(n, d / max(dist, 0.001)), 0.0) * 0.75 + 0.25;
            light += light_colors[i].rgb * att * lam;
        }
    }
    vec3 col = base.rgb * light;
    col = mix(col, base.rgb, clamp(emissive, 0.0, 1.0));
    float f = 1.0 - exp(-v_dist * v_dist * fog_density * fog_density);
    col = mix(col, fog_color, clamp(f, 0.0, 1.0) * (1.0 - clamp(emissive, 0.0, 1.0) * 0.6));
    frag = vec4(col, base.a);
}
'''

PARTICLE_FRAG = '''
#version 140
uniform vec4 p3d_ColorScale;
uniform sampler2D p3d_Texture0;
uniform vec3 sun_color;
uniform vec3 ambient_color;
uniform vec3 fog_color;
uniform float fog_density;
uniform float emissive;
in vec3 v_normal;
in vec4 v_color;
in vec3 v_world;
in float v_dist;
in vec2 v_uv;
out vec4 frag;
void main() {
    vec4 base = v_color * p3d_ColorScale;
    float a = texture(p3d_Texture0, v_uv).a;
    vec3 lit = base.rgb * (ambient_color * 1.3 + sun_color * 0.55);
    vec3 col = mix(lit, base.rgb, clamp(emissive, 0.0, 1.0));
    float f = 1.0 - exp(-v_dist * v_dist * fog_density * fog_density);
    col = mix(col, fog_color, clamp(f, 0.0, 1.0) * 0.8);
    frag = vec4(col, base.a * a);
}
'''

SKY_VERT = '''
#version 140
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
in vec4 p3d_Vertex;
out vec3 v_dir;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    v_dir = mat3(p3d_ModelMatrix) * p3d_Vertex.xyz;
}
'''

SKY_FRAG = '''
#version 140
uniform vec3 sky_zenith;
uniform vec3 sky_horizon;
uniform vec3 true_sun_dir;
uniform vec3 up_dir;
uniform vec3 sun_disc_color;
uniform float night;
in vec3 v_dir;
out vec4 frag;
float hash(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
void main() {
    vec3 d = normalize(v_dir);
    float h = dot(d, up_dir);
    float t = pow(clamp(h, 0.0, 1.0), 0.5);
    vec3 col = mix(sky_horizon, sky_zenith, t);
    if (h < 0.0) col = mix(sky_horizon, sky_horizon * 0.5, clamp(-h * 4.0, 0.0, 1.0));
    float sd = dot(d, true_sun_dir);
    float vis = clamp(dot(true_sun_dir, up_dir) * 6.0 + 0.6, 0.0, 1.0);
    col += sun_disc_color * pow(max(sd, 0.0), 10.0) * 0.45 * vis;
    col += sun_disc_color * smoothstep(0.9988, 0.9994, sd) * 2.5 * vis;
    float md = dot(d, -true_sun_dir);
    col += vec3(0.85, 0.88, 1.0) * smoothstep(0.9992, 0.9996, md) * night;
    col += vec3(0.25, 0.3, 0.5) * pow(max(md, 0.0), 40.0) * 0.4 * night;
    vec3 cell = floor(d * 230.0);
    float s = hash(cell);
    col += vec3(1.0) * step(0.9972, s) * night * clamp(h * 3.0, 0.0, 1.0) * (0.4 + 0.6 * hash(cell + 3.1));
    frag = vec4(col, 1.0);
}
'''

_SHADERS = {}


def get_shader(name):
    if name not in _SHADERS:
        if name == 'lit':
            _SHADERS[name] = PandaShader.make(PandaShader.SL_GLSL, LIT_VERT, LIT_FRAG)
        elif name == 'particle':
            _SHADERS[name] = PandaShader.make(PandaShader.SL_GLSL, LIT_VERT, PARTICLE_FRAG)
        elif name == 'sky':
            _SHADERS[name] = PandaShader.make(PandaShader.SL_GLSL, SKY_VERT, SKY_FRAG)
    return _SHADERS[name]


def make_lit(entity, emissive=None, transparent=False):
    """Give an entity the game's lit shader (priority 1 so it always wins)."""
    entity.setShader(get_shader('lit'), 1)
    entity.setTwoSided(True)
    if emissive is not None:
        entity.setShaderInput('emissive', float(emissive))
    if transparent:
        entity.setTransparency(TransparencyAttrib.MAlpha)
    return entity


# ============================================================== procedural mesh builder
class MeshBuilder:
    """Accumulates flat-shaded, vertex-coloured triangles and turns them into Ursina Meshes."""

    def __init__(self):
        self.v = []
        self.n = []
        self.c = []
        self.uv = []

    def __len__(self):
        return len(self.v)

    # ---- primitives
    def tri(self, a, b, c, n, col, uvs=None):
        e1 = _sub(b, a)
        e2 = _sub(c, a)
        if _dot(_cross(e1, e2), n) > 0:        # consistent winding (entities are two sided anyway)
            b, c = c, b
            if uvs:
                uvs = (uvs[0], uvs[2], uvs[1])
        self.v.extend((a, b, c))
        self.n.extend((n, n, n))
        self.c.extend((col, col, col))
        if uvs:
            self.uv.extend(uvs)
        else:
            self.uv.extend(((0, 0), (0, 0), (0, 0)))

    def quad(self, a, b, c, d, n, col, uvs=None):
        self.tri(a, b, c, n, col, (uvs[0], uvs[1], uvs[2]) if uvs else None)
        self.tri(a, c, d, n, col, (uvs[0], uvs[2], uvs[3]) if uvs else None)

    def hexa(self, p, col, top_col=None, bottom=False, face_cols=None):
        """Any convex 8-corner solid. p[0..3] bottom ring, p[4..7] the matching top ring."""
        cen = (sum(q[0] for q in p) / 8.0, sum(q[1] for q in p) / 8.0, sum(q[2] for q in p) / 8.0)
        faces = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
        for fi, f in enumerate(faces):
            if fi == 0 and not bottom:
                continue
            a, b, c, d = p[f[0]], p[f[1]], p[f[2]], p[f[3]]
            n = _normalize(_cross(_sub(c, a), _sub(d, b)))
            fc = ((a[0] + b[0] + c[0] + d[0]) / 4, (a[1] + b[1] + c[1] + d[1]) / 4, (a[2] + b[2] + c[2] + d[2]) / 4)
            if _dot(n, _sub(fc, cen)) < 0:
                n = (-n[0], -n[1], -n[2])
            colr = col
            if fi == 1 and top_col is not None:
                colr = top_col
            if face_cols and fi in face_cols:
                colr = face_cols[fi]
            self.quad(a, b, c, d, n, colr)

    def box(self, center, size, col, top_col=None, bottom=False, rot_y=0.0, face_cols=None):
        cx, cy, cz = center
        hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
        local = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz),
                 (-hx, hy, -hz), (hx, hy, -hz), (hx, hy, hz), (-hx, hy, hz)]
        if rot_y:
            r = math.radians(rot_y)
            cs, sn = math.cos(r), math.sin(r)
            pts = [(cx + x * cs + z * sn, cy + y, cz - x * sn + z * cs) for (x, y, z) in local]
        else:
            pts = [(cx + x, cy + y, cz + z) for (x, y, z) in local]
        self.hexa(pts, col, top_col, bottom, face_cols)

    def beam(self, p, q, w, h, col):
        """A rectangular bar from point p to point q (frames, forks, poles)."""
        d = _normalize(_sub(q, p))
        ref = (0.0, 1.0, 0.0) if abs(d[1]) < 0.95 else (1.0, 0.0, 0.0)
        s = _normalize(_cross(d, ref))
        u = _normalize(_cross(s, d))
        sw, uh = _scale(s, w / 2.0), _scale(u, h / 2.0)

        def ring(o):
            return [_sub(_sub(o, sw), uh), _sub(_add(o, sw), uh), _add(_add(o, sw), uh), _add(_sub(o, sw), uh)]
        self.hexa(ring(p) + ring(q), col, bottom=True)

    def cylinder(self, center, radius, height, col, seg=12, axis='y', radius_top=None, cap_col=None, caps=True):
        rt = radius if radius_top is None else radius_top
        cx, cy, cz = center
        h2 = height / 2.0

        def P(ang, rr, hh):
            a, b = math.cos(ang) * rr, math.sin(ang) * rr
            if axis == 'y':
                return (cx + a, cy + hh, cz + b)
            if axis == 'x':
                return (cx + hh, cy + a, cz + b)
            return (cx + a, cy + b, cz + hh)

        def N(ang, k):
            a, b = math.cos(ang), math.sin(ang)
            if axis == 'y':
                return _normalize((a, k, b))
            if axis == 'x':
                return _normalize((k, a, b))
            return _normalize((a, b, k))
        ax = {'y': (0.0, 1.0, 0.0), 'x': (1.0, 0.0, 0.0), 'z': (0.0, 0.0, 1.0)}[axis]
        slope = (radius - rt) / max(height, 1e-6)
        cb, ct = P(0, 0, -h2), P(0, 0, h2)
        capc = cap_col if cap_col is not None else col
        for k in range(seg):
            a0 = 2 * math.pi * k / seg
            a1 = 2 * math.pi * (k + 1) / seg
            am = (a0 + a1) / 2
            p0, p1 = P(a0, radius, -h2), P(a1, radius, -h2)
            p2, p3 = P(a1, rt, h2), P(a0, rt, h2)
            n = N(am, slope)
            if rt <= 1e-4:
                self.tri(p0, p1, p2, n, col)
            else:
                self.quad(p0, p1, p2, p3, n, col)
            if caps:
                self.tri(cb, p1, p0, (-ax[0], -ax[1], -ax[2]), capc)
                if rt > 1e-4:
                    self.tri(ct, p3, p2, ax, capc)

    def sphere(self, center, radius, col, rings=6, segs=10, squash=(1.0, 1.0, 1.0)):
        cx, cy, cz = center
        for i in range(rings):
            th0, th1 = math.pi * i / rings, math.pi * (i + 1) / rings
            for k in range(segs):
                ph0, ph1 = 2 * math.pi * k / segs, 2 * math.pi * (k + 1) / segs

                def pt(th, ph):
                    d = (math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph))
                    return (cx + d[0] * radius * squash[0], cy + d[1] * radius * squash[1], cz + d[2] * radius * squash[2])
                thm, phm = (th0 + th1) / 2, (ph0 + ph1) / 2
                n = _normalize((math.sin(thm) * math.cos(phm) / squash[0], math.cos(thm) / squash[1],
                                math.sin(thm) * math.sin(phm) / squash[2]))
                self.quad(pt(th0, ph0), pt(th0, ph1), pt(th1, ph1), pt(th1, ph0), n, col)

    def rect_xz(self, x0, z0, x1, z1, y, col, uv=False):
        uvs = ((0, 0), (1, 0), (1, 1), (0, 1)) if uv else None
        self.quad((x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1), (0.0, 1.0, 0.0), col, uvs)

    def ring_xz(self, center, r0, r1, y, col, seg=32):
        cx, cz = center[0], center[2]
        for k in range(seg):
            a0, a1 = 2 * math.pi * k / seg, 2 * math.pi * (k + 1) / seg
            self.quad((cx + math.cos(a0) * r0, y, cz + math.sin(a0) * r0), (cx + math.cos(a1) * r0, y, cz + math.sin(a1) * r0),
                      (cx + math.cos(a1) * r1, y, cz + math.sin(a1) * r1), (cx + math.cos(a0) * r1, y, cz + math.sin(a0) * r1),
                      (0.0, 1.0, 0.0), col)

    def face_quad(self, center, along, up, nrm, w, h, col, offset=0.04):
        c = _add(center, _scale(nrm, offset))
        a, u = _scale(along, w / 2.0), _scale(up, h / 2.0)
        self.quad(_sub(_sub(c, a), u), _sub(_add(c, a), u), _add(_add(c, a), u), _add(_sub(c, a), u), nrm, col)

    # ---- output
    def build(self, static=True, start=0, end=None):
        v = self.v[start:end]
        if not v:
            z = Color(0, 0, 0, 0)
            return Mesh(vertices=[(0, 0, 0), (0.001, 0, 0), (0, 0, 0.001)], triangles=[0, 1, 2],
                        colors=[z, z, z], normals=[(0, 1, 0)] * 3, uvs=[(0, 0)] * 3, static=static)
        return Mesh(vertices=v, triangles=list(range(len(v))), colors=self.c[start:end],
                    normals=self.n[start:end], uvs=self.uv[start:end], static=static)

    def entities(self, emissive=None, transparent=False, parent=None, chunk=59997):
        """Build one or more entities (meshes are split to stay below 65k vertices)."""
        ents = []
        total = len(self.v)
        start = 0
        while True:
            end = min(total, start + chunk)
            e = Entity(model=self.build(start=start, end=end), parent=parent if parent is not None else scene)
            make_lit(e, emissive, transparent)
            ents.append(e)
            start = end
            if start >= total:
                break
        return ents

    def entity(self, emissive=None, transparent=False, parent=None, **kwargs):
        e = Entity(model=self.build(), parent=parent if parent is not None else scene, **kwargs)
        return make_lit(e, emissive, transparent)


def world_text(txt, pos, rot_y, height=0.9, col=None):
    t = Text(text=txt, parent=scene, position=pos, origin=(0, 0), scale=height * 40.0,
             rotation_y=rot_y, color=col if col is not None else color.white)
    try:
        t.setTwoSided(True)
    except Exception:
        pass
    return t


def soft_texture(size=64):
    img = PNMImage(size, size, 4)
    for y in range(size):
        for x in range(size):
            dx = (x + 0.5) / size * 2 - 1
            dy = (y + 0.5) / size * 2 - 1
            a = max(0.0, 1.0 - math.sqrt(dx * dx + dy * dy))
            a = a * a * (3 - 2 * a)
            img.setXelA(x, y, 1.0, 1.0, 1.0, a)
    tex = PandaTexture('soft_particle')
    tex.load(img)
    return tex


# ============================================================== coordinate bridge
class GPUSpace:
    """Converts Ursina vectors into the coordinate space the GPU sees (render space).
    Keeps the custom shaders correct regardless of how Ursina maps its axes onto Panda3D."""

    def __init__(self):
        probe = Entity(parent=scene)
        root = scene.getTop()

        def get(v):
            probe.position = Vec3(*v)
            p = probe.getPos(root)
            return (p[0], p[1], p[2])
        self.o = get((0, 0, 0))
        self.ex = _sub(get((1, 0, 0)), self.o)
        self.ey = _sub(get((0, 1, 0)), self.o)
        self.ez = _sub(get((0, 0, 1)), self.o)
        destroy(probe)

    def vec(self, v):
        x, y, z = v[0], v[1], v[2]
        return LVecBase3f(self.ex[0] * x + self.ey[0] * y + self.ez[0] * z,
                          self.ex[1] * x + self.ey[1] * y + self.ez[1] * z,
                          self.ex[2] * x + self.ey[2] * y + self.ez[2] * z)

    def point(self, v):
        r = self.vec(v)
        return LVecBase3f(r[0] + self.o[0], r[1] + self.o[1], r[2] + self.o[2])


class LightManager:
    """Feeds up to 16 point lights into the lit shader every frame."""
    SLOTS = 16

    def __init__(self, world):
        self.world = world
        self.pos = PTA_LVecBase4f.emptyArray(self.SLOTS)
        self.col = PTA_LVecBase4f.emptyArray(self.SLOTS)
        self.flashes = []
        self.frame = []
        self.active = self.SLOTS            # lowered by the Graphics setting
        self._push()

    def set_quality(self, n):
        self.active = max(2, min(self.SLOTS, int(n)))
        scene.setShaderInput('light_count', float(self.active))

    def flash(self, pos, rgbv, radius, duration):
        self.flashes.append([pos[0], pos[1], pos[2], rgbv, radius, 0.0, duration])

    def add(self, pos, rgbv, radius):
        self.frame.append(((pos[0], pos[1], pos[2]), rgbv, radius))

    def update(self, dt, cam_pos, candidates):
        entries = []
        keep = []
        for f in self.flashes:
            f[5] += dt
            if f[5] < f[6]:
                keep.append(f)
                k = 1.0 - f[5] / f[6]
                k *= k
                entries.append(((f[0], f[1], f[2]), (f[3][0] * k, f[3][1] * k, f[3][2] * k), f[4]))
        self.flashes = keep
        entries.extend(self.frame[:6])
        self.frame = []
        entries = entries[:min(9, self.active)]
        remaining = self.active - len(entries)
        if candidates and remaining > 0:
            cx, cy, cz = cam_pos[0], cam_pos[1], cam_pos[2]
            entries.extend(heapq.nsmallest(remaining, candidates,
                                           key=lambda e: (e[0][0] - cx) ** 2 + (e[0][2] - cz) ** 2 + (e[0][1] - cy) ** 2))
        g = self.world.gpu
        for i in range(self.SLOTS):
            if i < len(entries):
                p, c, r = entries[i]
                gp = g.point(p)
                self.pos[i] = LVecBase4f(gp[0], gp[1], gp[2], r)
                self.col[i] = LVecBase4f(c[0], c[1], c[2], 1.0)
            else:
                self.pos[i] = LVecBase4f(0, -1000, 0, 0)
                self.col[i] = LVecBase4f(0, 0, 0, 0)
        self._push()

    def _push(self):
        scene.setShaderInput('lights', self.pos)
        scene.setShaderInput('light_colors', self.col)


# ============================================================== procedural audio
SR = 44100


def _np_norm(x):
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    return x / m if m > 1e-9 else x


def _lowpass(x, cutoff):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    X *= 1.0 / (1.0 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))


def _highpass(x, cutoff):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    X *= 1.0 - 1.0 / (1.0 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))


def _bandpass(x, lo, hi):
    return _lowpass(_highpass(x, lo), hi)


def _noise(n):
    return np.random.uniform(-1.0, 1.0, n)


def _t(dur):
    n = int(SR * dur)
    return np.arange(n) / SR, n


def _fade(x, fin=0.002, fout=0.02):
    a = int(SR * fin)
    b = int(SR * fout)
    if a > 0:
        x[:a] *= np.linspace(0, 1, a)
    if b > 0:
        x[-b:] *= np.linspace(1, 0, b)
    return x


def _echo(x, taps=((0.11, 0.33), (0.23, 0.2), (0.41, 0.1))):
    y = x.copy()
    for delay, g in taps:
        k = int(delay * SR)
        if k < len(x):
            y[k:] += _lowpass(x[:-k], 2200) * g
    return y


def _write_wav(name, x, peak=0.95):
    x = _np_norm(np.nan_to_num(x)) * peak
    data = (np.clip(x, -1, 1) * 32767).astype('<i2').tobytes()
    with wave.open(os.path.join(SOUND_DIR, name + '.wav'), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data)


def synth_bang(dur, body_cut, sub_freq, decay, tail=1.0, crack=1.0):
    t, n = _t(dur)
    crack_sig = _noise(n) * np.exp(-t / 0.005) * crack
    body = _np_norm(_lowpass(_noise(n), body_cut)) * np.exp(-t / decay) * (1 - np.exp(-t / 0.0015))
    freq = sub_freq * (0.4 + 0.6 * np.exp(-t / 0.09))
    sub = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t / (decay * 1.4))
    rumble = _np_norm(_lowpass(_noise(n), 160)) * np.exp(-t / (decay * 4.5)) * tail
    x = crack_sig * 0.9 + body * 2.0 + sub * 1.5 + rumble * 1.2
    x = np.tanh(x * 2.8)
    x = _echo(x)
    return _fade(x, 0.0005, 0.25)


def synth_sounds():
    """Generates every sound effect in the game (runs once, cached on disk)."""
    os.makedirs(SOUND_DIR, exist_ok=True)
    np.random.seed(7)

    _write_wav('bang_cobra', synth_bang(2.4, 1100, 72, 0.16, tail=1.0))
    _write_wav('bang_scream', synth_bang(3.4, 750, 52, 0.27, tail=1.6, crack=1.3))

    # scream 100: rising, wobbling whistle with crackling sparks
    t, n = _t(2.1)
    f = 1300 + 2700 * (t / t[-1]) ** 1.25 + 90 * np.sin(2 * np.pi * 7.5 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    whistle = np.sin(ph) + 0.35 * np.sin(2 * ph) + 0.12 * np.sin(3 * ph)
    env = np.minimum(t / 0.06, 1.0) * (0.75 + 0.25 * t / t[-1]) * (0.85 + 0.15 * np.sin(2 * np.pi * 13 * t))
    hiss = _np_norm(_bandpass(_noise(n), 3000, 9000)) * 0.25
    crackle = np.zeros(n)
    for _ in range(140):
        p = np.random.randint(0, n - 200)
        crackle[p:p + 200] += _noise(200) * np.exp(-np.arange(200) / 25.0) * np.random.uniform(0.3, 1.0)
    _write_wav('scream', _fade(whistle * env + hiss + crackle * 0.5, 0.01, 0.03), 0.9)

    # scream 100 (new): a clean 10 second rising, oscillating whistle with fountain crackle
    t, n = _t(10.0)
    rise = (t / t[-1]) ** 0.8
    f = 1500 + 2600 * rise + (120 + 160 * rise) * np.sin(2 * np.pi * (5.0 + 4.0 * rise) * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    whistle = np.sin(ph) + 0.3 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
    env = np.minimum(t / 0.08, 1.0) * (0.7 + 0.3 * rise) * (0.88 + 0.12 * np.sin(2 * np.pi * 11 * t))
    hiss = _np_norm(_bandpass(_noise(n), 2500, 9000)) * 0.18
    crackle = np.zeros(n)
    for _ in range(700):
        p = np.random.randint(0, n - 200)
        crackle[p:p + 200] += _noise(200) * np.exp(-np.arange(200) / 22.0) * np.random.uniform(0.2, 0.9)
    _write_wav('scream10', _fade(whistle * env + hiss + crackle * 0.35, 0.02, 0.04), 0.92)

    # spark fountain sizzle (Cobra 6 pre-blast, no whistle)
    t, n = _t(3.2)
    fs = _np_norm(_bandpass(_noise(n), 1800, 11000)) * 0.5 * (0.8 + 0.2 * np.sin(2 * np.pi * 6 * t))
    for _ in range(420):
        p = np.random.randint(0, n - 300)
        fs[p:p + 300] += _noise(300) * np.exp(-np.arange(300) / 35.0) * np.random.uniform(0.3, 1.2)
    _write_wav('fountain', _fade(fs, 0.02, 0.05), 0.75)

    # the big bang both fireworks use: deeper, longer sub-bass
    _write_wav('bang_mega', synth_bang(4.0, 700, 44, 0.3, tail=2.0, crack=1.4))

    # fuse: hiss and crackle
    t, n = _t(1.9)
    fz = _np_norm(_highpass(_noise(n), 3500)) * 0.35 * (0.7 + 0.3 * np.sin(2 * np.pi * 3 * t))
    for _ in range(int(1.9 * 55)):
        p = np.random.randint(0, n - 300)
        fz[p:p + 300] += _noise(300) * np.exp(-np.arange(300) / 40.0) * np.random.uniform(0.2, 1.0)
    _write_wav('fuse', _fade(fz, 0.01, 0.05), 0.6)

    # combustion engine loop (1 s, integer cycles -> seamless)
    t, n = _t(1.0)
    eng = np.zeros(n)
    for k in range(1, 14):
        eng += np.sin(2 * np.pi * 48 * k * t + np.random.uniform(0, 6.28)) / (k ** 0.85)
    eng *= 0.75 + 0.25 * np.sin(2 * np.pi * 24 * t)
    eng += _np_norm(_lowpass(_noise(n), 700)) * 0.35
    _write_wav('engine_car', np.tanh(_np_norm(eng) * 1.6), 0.8)

    # electric motor whine loop
    ev = (np.sin(2 * np.pi * 180 * t) * 0.6 + np.sin(2 * np.pi * 360 * t) * 0.35 + np.sin(2 * np.pi * 540 * t) * 0.15
          + np.sin(2 * np.pi * 2160 * t) * 0.08)
    ev += _np_norm(_bandpass(_noise(n), 300, 2500)) * 0.12
    _write_wav('engine_ev', ev, 0.7)

    # tyre screech loop (FFT-filtered noise is periodic -> loops perfectly)
    sk = _np_norm(_bandpass(_noise(n), 700, 2600)) * 0.6
    sk += np.sin(2 * np.pi * 1050 * t + 0.4 * np.sin(2 * np.pi * 6 * t)) * 0.5
    sk *= 0.8 + 0.2 * np.sin(2 * np.pi * 9 * t)
    _write_wav('skid', sk, 0.7)

    # police siren (2 s wail)
    t2, n2 = _t(2.0)
    fs = 750 + 550 * (0.5 - 0.5 * np.cos(2 * np.pi * t2 / 2.0))
    phs = np.cumsum(fs) / SR
    phs *= round(phs[-1]) / phs[-1]
    sir = np.tanh(np.sin(2 * np.pi * phs) * 2.2) + 0.3 * np.sin(4 * np.pi * phs)
    _write_wav('siren', sir, 0.6)

    # shop alarm (two tone)
    t, n = _t(1.0)
    half = n // 2
    al = np.concatenate([np.sin(2 * np.pi * 960 * t[:half]), np.sin(2 * np.pi * 770 * t[half:])])
    _write_wav('alarm', np.tanh(al * 3.0), 0.55)

    # cash register "ka-ching"
    t, n = _t(0.9)
    ding = np.zeros(n)
    for start, amp in ((0.0, 0.6), (0.11, 1.0)):
        k = int(start * SR)
        tt = t[:n - k]
        bell = sum(np.sin(2 * np.pi * fr * tt) * a for fr, a in ((2093, 1.0), (2637, 0.6), (3520, 0.35), (4186, 0.2)))
        ding[k:] += bell * np.exp(-tt / 0.22) * amp
    ding[:int(0.03 * SR)] += _noise(int(0.03 * SR)) * 0.5
    _write_wav('cash', _fade(ding), 0.8)

    # purchase chime
    t, n = _t(0.55)
    ch = np.zeros(n)
    for i, fr in enumerate((660, 880, 1320)):
        k = int(i * 0.09 * SR)
        tt = t[:n - k]
        ch[k:] += np.sin(2 * np.pi * fr * tt) * np.exp(-tt / 0.18)
    _write_wav('buy', _fade(ch), 0.7)

    # error buzz
    t, n = _t(0.28)
    _write_wav('error', _fade(np.sign(np.sin(2 * np.pi * 150 * t)) * 0.6 + np.sin(2 * np.pi * 300 * t) * 0.3), 0.45)

    # crash thud
    t, n = _t(0.45)
    th = _np_norm(_lowpass(_noise(n), 320)) * np.exp(-t / 0.07) + np.sin(2 * np.pi * 65 * t) * np.exp(-t / 0.09)
    th += _np_norm(_bandpass(_noise(n), 2000, 6000)) * np.exp(-t / 0.03) * 0.4
    _write_wav('thud', _fade(np.tanh(th * 2.0), 0.0005), 0.9)

    # car horn loop (integer cycles in 0.5 s)
    t, n = _t(0.5)
    hn = np.tanh((np.sin(2 * np.pi * 350 * t) + np.sin(2 * np.pi * 440 * t)) * 2.0)
    _write_wav('horn', _lowpass(hn, 2500), 0.6)

    # throw whoosh
    t, n = _t(0.35)
    wh = _np_norm(_bandpass(_noise(n), 500, 3000)) * np.sin(np.pi * t / t[-1]) ** 2
    _write_wav('whoosh', _fade(wh), 0.5)

    # footstep
    t, n = _t(0.09)
    st = _np_norm(_lowpass(_noise(n), 500)) * np.exp(-t / 0.018)
    _write_wav('step', _fade(st, 0.0005, 0.01), 0.5)

    # UI blip
    t, n = _t(0.14)
    _write_wav('blip', _fade(np.sin(2 * np.pi * 1250 * t) * np.exp(-t / 0.05)), 0.5)

    # small spark burst for collisions
    t, n = _t(0.3)
    sp = _np_norm(_highpass(_noise(n), 2500)) * np.exp(-t / 0.06)
    _write_wav('scrape', _fade(sp), 0.5)

    with open(os.path.join(SOUND_DIR, 'version.txt'), 'w') as f:
        f.write('4')


SOUND_NAMES = ('bang_cobra', 'bang_scream', 'bang_mega', 'scream', 'scream10', 'fountain', 'fuse', 'engine_car', 'engine_ev', 'skid', 'siren',
               'alarm', 'cash', 'buy', 'error', 'thud', 'horn', 'whoosh', 'step', 'blip', 'scrape')


def ensure_sounds():
    if np is None:
        print('[audio] numpy not installed -> no sound. Run:  pip install numpy')
        return False
    vf = os.path.join(SOUND_DIR, 'version.txt')
    ok = os.path.exists(vf) and open(vf).read().strip() == '4' and all(
        os.path.exists(os.path.join(SOUND_DIR, n + '.wav')) for n in SOUND_NAMES)
    if not ok:
        print('[audio] synthesizing sound effects ...')
        synth_sounds()
    return True


class LoopSound:
    def __init__(self, snd, bank=None):
        self.snd = snd
        self.bank = bank
        self.vol = 0.0
        self.playing = False

    def set(self, volume, rate=1.0):
        if self.snd is None:
            return
        volume = clampf(volume * (self.bank.master if self.bank is not None else 1.0), 0.0, 1.0)
        if volume < 0.004:
            if self.playing:
                self.snd.stop()
                self.playing = False
            return
        self.snd.setVolume(volume)
        self.snd.setPlayRate(clampf(rate, 0.2, 4.0))
        if not self.playing:
            self.snd.setLoop(True)
            self.snd.play()
            self.playing = True


class SoundBank:
    def __init__(self):
        self.base = getattr(application, 'base', None) or getattr(builtins, 'base', None)
        self.enabled = False
        self.pools = {}
        self.index = {}
        self.listener = (0.0, 0.0, 0.0)
        self.master = 1.0
        try:
            if self.base is not None and ensure_sounds():
                for name in SOUND_NAMES:
                    copies = 4 if name in ('bang_cobra', 'bang_scream', 'bang_mega', 'thud', 'step', 'cash', 'fuse', 'scream', 'scream10', 'fountain') else 2
                    self.pools[name] = [self._load(name) for _ in range(copies)]
                    self.index[name] = 0
                self.enabled = True
        except Exception as ex:
            print('[audio] disabled:', ex)
            self.enabled = False

    def _load(self, name):
        return self.base.loader.loadSfx(Filename.fromOsSpecific(os.path.join(SOUND_DIR, name + '.wav')))

    def play(self, name, volume=1.0, rate=1.0, pos=None, ref=18.0):
        if not self.enabled or name not in self.pools:
            return
        if pos is not None:
            d = math.sqrt((pos[0] - self.listener[0]) ** 2 + (pos[1] - self.listener[1]) ** 2 + (pos[2] - self.listener[2]) ** 2)
            volume *= 1.0 / (1.0 + (d / ref) ** 2)
        volume *= self.master
        if volume < 0.01:
            return
        pool = self.pools[name]
        i = self.index[name]
        self.index[name] = (i + 1) % len(pool)
        s = pool[i]
        s.stop()
        s.setLoop(False)
        s.setVolume(clampf(volume, 0, 1))
        s.setPlayRate(rate)
        s.play()
        return s

    def loop(self, name):
        if not self.enabled:
            return LoopSound(None)
        return LoopSound(self._load(name), self)

    def falloff(self, pos, ref=18.0):
        d = math.sqrt((pos[0] - self.listener[0]) ** 2 + (pos[1] - self.listener[1]) ** 2 + (pos[2] - self.listener[2]) ** 2)
        return 1.0 / (1.0 + (d / ref) ** 2)


# ============================================================== particles & decals
def _quad_mesh_xy(size=1.0):
    mb = MeshBuilder()
    s = size / 2.0
    mb.quad((-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0), (0.0, 0.0, -1.0), Color(1, 1, 1, 1),
            ((0, 0), (1, 0), (1, 1), (0, 1)))
    return mb.build()


def _quad_mesh_flat(size=1.0):
    mb = MeshBuilder()
    s = size / 2.0
    mb.rect_xz(-s, -s, s, s, 0.0, Color(1, 1, 1, 1), uv=True)
    return mb.build()


class _P:
    __slots__ = ('e', 'life', 'max', 'x', 'y', 'z', 'vx', 'vy', 'vz', 's0', 's1', 'c0', 'c1', 'grav', 'drag')


class ParticlePool:
    def __init__(self, tex, count, additive):
        self.items = []
        self.next = 0
        for _ in range(count):
            p = _P()
            e = Entity(model=_quad_mesh_xy(), enabled=False)
            e.billboard = True
            e.setShader(get_shader('particle'), 1)
            e.setTexture(tex, 1)
            e.setTwoSided(True)
            e.setDepthWrite(False)
            e.setTransparency(TransparencyAttrib.MAlpha)
            e.setShaderInput('emissive', 1.0 if additive else 0.0)
            if additive:
                e.setAttrib(ColorBlendAttrib.make(ColorBlendAttrib.MAdd, ColorBlendAttrib.OIncomingAlpha,
                                                  ColorBlendAttrib.OOne))
                e.setBin('fixed', 20)
            p.e = e
            p.life = 0.0
            self.items.append(p)

    def emit(self, pos, vel, life, s0, s1, c0, c1=None, grav=0.0, drag=0.0):
        p = self.items[self.next]
        self.next = (self.next + 1) % len(self.items)
        p.x, p.y, p.z = pos[0], pos[1], pos[2]
        p.vx, p.vy, p.vz = vel[0], vel[1], vel[2]
        p.life = p.max = life
        p.s0, p.s1 = s0, s1
        p.c0 = c0
        p.c1 = c1 if c1 is not None else Color(c0[0], c0[1], c0[2], 0.0)
        p.grav, p.drag = grav, drag
        p.e.enabled = True
        p.e.position = (p.x, p.y, p.z)
        p.e.scale = s0
        p.e.color = c0

    def update(self, dt):
        for p in self.items:
            if p.life <= 0.0:
                continue
            p.life -= dt
            if p.life <= 0.0:
                p.e.enabled = False
                continue
            k = 1.0 - p.life / p.max
            p.vy -= p.grav * dt
            if p.drag:
                f = max(0.0, 1.0 - p.drag * dt)
                p.vx *= f
                p.vy *= f
                p.vz *= f
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.z += p.vz * dt
            if p.y < 0.03:
                p.y = 0.03
                p.vy = abs(p.vy) * 0.3
            p.e.position = (p.x, p.y, p.z)
            p.e.scale = p.s0 + (p.s1 - p.s0) * k
            c0, c1 = p.c0, p.c1
            p.e.color = Color(c0[0] + (c1[0] - c0[0]) * k, c0[1] + (c1[1] - c0[1]) * k,
                              c0[2] + (c1[2] - c0[2]) * k, c0[3] + (c1[3] - c0[3]) * k)


class Particles:
    def __init__(self):
        tex = soft_texture()
        self.glow = ParticlePool(tex, 420, additive=True)     # sparks, fire, flashes, fountains
        self.smoke = ParticlePool(tex, 320, additive=False)   # smoke, dust, lingering blast clouds

    def spark(self, pos, vel, life=0.5, size=0.12, col=None, grav=9.0):
        c = col if col is not None else Color(1.0, 0.75, 0.3, 1.0)
        self.glow.emit(pos, vel, life, size, size * 0.3, c, Color(c[0], c[1] * 0.5, 0.0, 0.0), grav, 0.5)

    def fire(self, pos, vel, life=0.6, s0=1.5, s1=4.0):
        self.glow.emit(pos, vel, life, s0, s1, Color(1.0, 0.75, 0.35, 1.0), Color(0.8, 0.15, 0.02, 0.0), -2.0, 2.5)

    def flash(self, pos, size=6.0, life=0.15):
        self.glow.emit(pos, (0, 0, 0), life, size, size * 1.6, Color(1, 0.95, 0.8, 1), Color(1, 0.6, 0.2, 0), 0, 0)

    def smoke_puff(self, pos, vel, life=1.6, s0=0.6, s1=2.6, shade=0.6, alpha=0.5, rise=-0.6, drag=1.2):
        self.smoke.emit(pos, vel, life, s0, s1, Color(shade, shade, shade, alpha), Color(shade, shade, shade, 0.0), rise, drag)

    def update(self, dt):
        self.glow.update(dt)
        self.smoke.update(dt)


class Decals:
    def __init__(self, count=40):
        tex = soft_texture(32)
        self.items = []
        self.next = 0
        for _ in range(count):
            e = Entity(model=_quad_mesh_flat(), enabled=False)
            e.setShader(get_shader('particle'), 1)
            e.setTexture(tex, 1)
            e.setTwoSided(True)
            e.setDepthWrite(False)
            e.setDepthOffset(2)
            e.setTransparency(TransparencyAttrib.MAlpha)
            e.setShaderInput('emissive', 0.0)
            self.items.append([e, 0.0, 1.0])

    def place(self, x, y, z, size, life=60.0):
        d = self.items[self.next]
        self.next = (self.next + 1) % len(self.items)
        d[0].enabled = True
        d[0].position = (x, y + 0.03, z)
        d[0].scale = size
        d[0].rotation_y = random.uniform(0, 360)
        d[0].color = Color(0.02, 0.02, 0.02, 0.85)
        d[1] = life
        d[2] = life

    def update(self, dt):
        for d in self.items:
            if d[1] > 0:
                d[1] -= dt
                if d[1] <= 0:
                    d[0].enabled = False
                else:
                    d[0].alpha = 0.85 * min(1.0, d[1] / (d[2] * 0.3))


class TireMarks:
    MAX = 900

    def __init__(self):
        self.segs = deque(maxlen=self.MAX)
        self.dirty = False
        self.timer = 0.0
        self.ent = Entity(model=MeshBuilder().build(static=False))
        make_lit(self.ent, 0.0, transparent=True)
        self.ent.setDepthWrite(False)
        self.ent.setDepthOffset(2)

    def add(self, ax, az, bx, bz, y, width=0.26, alpha=0.75):
        if (bx - ax) ** 2 + (bz - az) ** 2 < 0.0004:
            return
        self.segs.append((ax, az, bx, bz, y + 0.025, width, alpha))
        self.dirty = True

    def update(self, dt):
        self.timer += dt
        if self.dirty and self.timer > 0.12:
            self.timer = 0.0
            self.dirty = False
            mb = MeshBuilder()
            n = len(self.segs)
            for k, (ax, az, bx, bz, y, w, a) in enumerate(self.segs):
                dx, dz = bx - ax, bz - az
                l = math.sqrt(dx * dx + dz * dz) or 1.0
                px, pz = -dz / l * w / 2, dx / l * w / 2
                c = Color(0.03, 0.03, 0.035, a * (0.3 + 0.7 * (k + 1) / n))
                mb.quad((ax - px, y, az - pz), (ax + px, y, az + pz), (bx + px, y, bz + pz), (bx - px, y, bz - pz),
                        (0.0, 1.0, 0.0), c)
            old = self.ent.model
            self.ent.model = mb.build(static=False)
            self.ent.setShader(get_shader('lit'), 1)
            try:
                if old is not None and not old.isEmpty():
                    old.removeNode()
            except Exception:
                pass


# ============================================================== collision world
class Collision:
    CS = 16.0

    def __init__(self):
        self.boxes = []
        self.grid = {}

    def add(self, x0, y0, z0, x1, y1, z1, tag=None):
        b = (min(x0, x1), min(y0, y1), min(z0, z1), max(x0, x1), max(y0, y1), max(z0, z1), tag)
        idx = len(self.boxes)
        self.boxes.append(b)
        for cx in range(int(math.floor(b[0] / self.CS)), int(math.floor(b[3] / self.CS)) + 1):
            for cz in range(int(math.floor(b[2] / self.CS)), int(math.floor(b[5] / self.CS)) + 1):
                self.grid.setdefault((cx, cz), []).append(idx)
        return idx

    def nearby(self, x0, z0, x1, z1):
        out = set()
        for cx in range(int(math.floor(x0 / self.CS)), int(math.floor(x1 / self.CS)) + 1):
            for cz in range(int(math.floor(z0 / self.CS)), int(math.floor(z1 / self.CS)) + 1):
                lst = self.grid.get((cx, cz))
                if lst:
                    out.update(lst)
        return out

    def resolve_circle(self, x, z, r, y0, y1):
        """Pushes a vertical cylinder out of every box it overlaps. Returns x, z, normal-or-None."""
        normal = None
        for idx in self.nearby(x - r, z - r, x + r, z + r):
            b = self.boxes[idx]
            if b[4] < y0 or b[1] > y1:
                continue
            cx = clampf(x, b[0], b[3])
            cz = clampf(z, b[2], b[5])
            dx, dz = x - cx, z - cz
            d2 = dx * dx + dz * dz
            if d2 >= r * r:
                continue
            if d2 > 1e-10:
                d = math.sqrt(d2)
                nx, nz = dx / d, dz / d
                x += nx * (r - d)
                z += nz * (r - d)
            else:
                pens = ((x - b[0] + r, -1.0, 0.0), (b[3] - x + r, 1.0, 0.0), (z - b[2] + r, 0.0, -1.0), (b[5] - z + r, 0.0, 1.0))
                p, nx, nz = min(pens, key=lambda q: q[0])
                x += nx * p
                z += nz * p
            normal = (nx, nz) if normal is None else (normal[0] + nx, normal[1] + nz)
        if normal is not None:
            l = math.hypot(normal[0], normal[1]) or 1.0
            normal = (normal[0] / l, normal[1] / l)
        return x, z, normal

    def raycast(self, o, d, maxd):
        ex = (o[0] + d[0] * maxd, o[2] + d[2] * maxd)
        best = maxd
        for idx in self.nearby(min(o[0], ex[0]), min(o[2], ex[1]), max(o[0], ex[0]), max(o[2], ex[1])):
            b = self.boxes[idx]
            tmin, tmax = 0.0, best
            hit = True
            for a in range(3):
                lo, hi = b[a], b[a + 3]
                if abs(d[a]) < 1e-9:
                    if o[a] < lo or o[a] > hi:
                        hit = False
                        break
                else:
                    t1 = (lo - o[a]) / d[a]
                    t2 = (hi - o[a]) / d[a]
                    if t1 > t2:
                        t1, t2 = t2, t1
                    tmin = max(tmin, t1)
                    tmax = min(tmax, t2)
                    if tmin > tmax:
                        hit = False
                        break
            if hit and tmin < best:
                best = tmin
        return best

    def inside(self, x, y, z, margin=0.0):
        for idx in self.nearby(x, z, x, z):
            b = self.boxes[idx]
            if b[0] - margin <= x <= b[3] + margin and b[2] - margin <= z <= b[5] + margin and b[1] <= y <= b[4]:
                return True
        return False


# ============================================================== knock-able props
class Prop:
    def __init__(self, kind, x, y, z):
        mb = MeshBuilder()
        self.kind = kind
        if kind == 'bin':
            mb.cylinder((0, 0, 0), 0.3, 0.9, rgb(38, 105, 58), seg=10)
            mb.cylinder((0, 0.48, 0), 0.33, 0.07, rgb(28, 70, 40), seg=10)
            mb.box((0, 0.1, 0.31), (0.18, 0.08, 0.04), rgb(220, 220, 220))
            self.h, self.r, self.mass = 0.45, 0.32, 1.0
        elif kind == 'cone':
            mb.cylinder((0, 0.02, 0), 0.24, 0.66, rgb(245, 100, 20), seg=10, radius_top=0.03)
            mb.cylinder((0, 0.08, 0), 0.19, 0.12, rgb(240, 240, 240), seg=10, caps=False)
            mb.box((0, -0.31, 0), (0.56, 0.05, 0.56), rgb(30, 30, 30))
            self.h, self.r, self.mass = 0.34, 0.28, 0.4
        elif kind == 'crate':
            mb.box((0, 0, 0), (0.8, 0.8, 0.8), rgb(150, 110, 64), bottom=True)
            mb.box((0, 0, 0), (0.84, 0.16, 0.84), rgb(110, 80, 45), bottom=True)
            self.h, self.r, self.mass = 0.4, 0.45, 1.5
        else:  # cardboard box
            mb.box((0, 0, 0), (0.6, 0.5, 0.6), rgb(176, 136, 90), bottom=True)
            mb.box((0, 0.251, 0), (0.12, 0.004, 0.6), rgb(200, 180, 140))
            self.h, self.r, self.mass = 0.25, 0.34, 0.5
        self.e = mb.entity()
        self.x, self.y, self.z = x, y + self.h, z
        self.vx = self.vy = self.vz = 0.0
        self.rx = self.rz = 0.0
        self.ry = random.uniform(0, 360)
        self.wx = self.wz = 0.0
        self.rest = True
        self.lying = False
        self._apply()

    def _apply(self):
        self.e.position = (self.x, self.y, self.z)
        self.e.rotation = (self.rx, self.ry, self.rz)

    def push(self, vx, vy, vz, spin=200.0):
        self.vx += vx / self.mass
        self.vy += vy / self.mass
        self.vz += vz / self.mass
        self.wx = random.uniform(-spin, spin)
        self.wz = random.uniform(-spin, spin)
        self.rest = False


class Props:
    def __init__(self, world, spots):
        self.world = world
        self.items = [Prop(k, x, world.ground_height(x, z), z) for (k, x, z) in spots]

    def knockback(self, pos, radius, force):
        for p in self.items:
            dx, dz = p.x - pos[0], p.z - pos[2]
            d = math.hypot(dx, dz)
            if d < radius:
                k = force * (1.0 - d / radius)
                d = d or 0.01
                p.push(dx / d * k, k * 0.7 + 3.0, dz / d * k, 500)

    def update(self, dt):
        w = self.world
        for p in self.items:
            if p.rest:
                continue
            p.vy -= 18.0 * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.z += p.vz * dt
            p.rx += p.wx * dt
            p.rz += p.wz * dt
            floor = w.ground_height(p.x, p.z) + p.h * 0.9
            on_ground = False
            if p.y <= floor:
                p.y = floor
                on_ground = True
                if p.vy < -2.5:
                    p.vy = -p.vy * 0.32
                    w.game.sound.play('thud', 0.25, 1.6, (p.x, p.y, p.z), 10)
                else:
                    p.vy = 0.0
                f = max(0.0, 1.0 - 5.0 * dt)
                p.vx *= f
                p.vz *= f
                p.wx *= f
                p.wz *= f
            x, z, n = w.collision.resolve_circle(p.x, p.z, p.r, p.y - p.h, p.y + p.h)
            if n is not None:
                vn = p.vx * n[0] + p.vz * n[1]
                if vn < 0:
                    p.vx -= 1.5 * vn * n[0]
                    p.vz -= 1.5 * vn * n[1]
            p.x, p.z = x, z
            if on_ground and abs(p.vx) + abs(p.vz) < 0.4:
                p.lying = abs(wrap_angle(p.rx)) > 45 or abs(wrap_angle(p.rz)) > 45
                p.rx = 90.0 if p.lying else 0.0
                p.rz = 0.0
                p.y = w.ground_height(p.x, p.z) + (p.r * 0.85 if p.lying else p.h)
                p.vx = p.vy = p.vz = p.wx = p.wz = 0.0
                p.rest = True
            p._apply()


# ============================================================== city frame helper
class Frame:
    """Local frame for buildings that can face N/E/S/W. Local -z is the street side (door)."""

    def __init__(self, ox, oz, angle, y=CURB_H):
        self.ox, self.oz, self.a, self.y = ox, oz, angle, y
        self.c = int(round(math.cos(math.radians(angle))))
        self.s = int(round(math.sin(math.radians(angle))))

    def p(self, lx, ly, lz):
        return (self.ox + lx * self.c + lz * self.s, self.y + ly, self.oz - lx * self.s + lz * self.c)

    def size(self, sx, sy, sz):
        return (sz, sy, sx) if abs(self.s) == 1 else (sx, sy, sz)

    def dir(self, lx, lz):
        return (lx * self.c + lz * self.s, -lx * self.s + lz * self.c)

    def yaw_of(self, lx, lz):
        d = self.dir(lx, lz)
        return yaw_towards(d[0], d[1])


# ============================================================== palettes
FACADES = [rgb(168, 84, 64), rgb(140, 70, 55), rgb(120, 62, 50), rgb(186, 110, 80), rgb(206, 192, 168),
           rgb(172, 172, 174), rgb(226, 222, 212), rgb(96, 108, 122), rgb(122, 96, 82), rgb(190, 160, 122)]
BRICKS = [rgb(150, 72, 54), rgb(128, 60, 46), rgb(170, 92, 66), rgb(110, 56, 44), rgb(96, 60, 50),
          rgb(180, 120, 90), rgb(70, 64, 60), rgb(200, 190, 170)]
ROOF_COL = rgb(58, 60, 64)
TILE_ROOF = [rgb(70, 52, 48), rgb(52, 52, 56), rgb(110, 58, 44)]
SIDEWALK_COL = rgb(168, 166, 160)
CURB_COL = rgb(140, 140, 138)
ASPHALT = rgb(50, 52, 56)
GRASS = rgb(78, 128, 58)
MARK = rgb(226, 226, 214)
GLASS_DARK = rgb(40, 50, 62)
POLE = rgb(46, 50, 54)

#               lot      type        name                    kind / price, income per minute
LOT_SPECIAL = {
    (3, 3): ('park',),
    (2, 3): ('shop', 'CORNER SHOP', 'convenience'),
    (4, 2): ('shop', 'ELECTRONICS', 'electronics'),
    (3, 1): ('shop', 'JEWELRY STORE', 'jewelry'),
    (4, 4): ('garage',),
    (2, 2): ('business', 'KEBAB & SNACK BAR', 2500, 150),
    (2, 4): ('business', 'CAR WASH', 6000, 360),
    (3, 5): ('business', 'TOUCAN COFFEE SHOP', 12000, 700),
    (1, 3): ('business', 'E-SCOOTER RENTAL', 4000, 240),
    (5, 3): ('business', 'NIGHTCLUB BASS', 20000, 1150),
    (1, 2): ('shop', 'NIGHT SHOP', 'convenience'),
    (5, 4): ('shop', 'GAS STATION', 'gas'),
    (5, 1): ('parking',),
    (1, 5): ('parking',),
    # new districts
    (0, 0): ('industrial',),
    (1, 0): ('industrial',),
    (0, 1): ('industrial',),
    (6, 6): ('stunt',),
    (0, 6): ('field',),
    (6, 0): ('park2',),
}
DOWNTOWN_RADIUS = 1.5                 # lots this close to the centre get skyscrapers

SKY_KEYS = [
    # hour  zenith               horizon              sun colour          ambient               ground bounce
    (0.0, (0.015, 0.02, 0.06), (0.05, 0.06, 0.12), (0.0, 0.0, 0.0), (0.085, 0.095, 0.15), (0.03, 0.03, 0.04)),
    (4.6, (0.015, 0.02, 0.06), (0.05, 0.06, 0.12), (0.0, 0.0, 0.0), (0.085, 0.095, 0.15), (0.03, 0.03, 0.04)),
    (5.6, (0.10, 0.12, 0.28), (0.45, 0.30, 0.35), (0.6, 0.35, 0.2), (0.16, 0.15, 0.22), (0.06, 0.05, 0.05)),
    (6.4, (0.25, 0.35, 0.60), (0.98, 0.62, 0.40), (1.0, 0.62, 0.35), (0.30, 0.28, 0.34), (0.12, 0.10, 0.09)),
    (8.0, (0.30, 0.52, 0.86), (0.80, 0.82, 0.85), (1.0, 0.90, 0.76), (0.40, 0.43, 0.50), (0.17, 0.16, 0.14)),
    (12.0, (0.22, 0.47, 0.88), (0.68, 0.80, 0.94), (1.05, 1.0, 0.93), (0.44, 0.47, 0.55), (0.20, 0.19, 0.17)),
    (16.0, (0.25, 0.48, 0.86), (0.76, 0.80, 0.86), (1.02, 0.94, 0.82), (0.42, 0.44, 0.52), (0.19, 0.17, 0.15)),
    (17.8, (0.26, 0.36, 0.66), (0.98, 0.66, 0.42), (1.0, 0.66, 0.38), (0.36, 0.31, 0.34), (0.15, 0.12, 0.10)),
    (18.7, (0.16, 0.16, 0.40), (0.98, 0.42, 0.22), (0.95, 0.42, 0.20), (0.28, 0.20, 0.26), (0.10, 0.07, 0.07)),
    (19.6, (0.05, 0.06, 0.16), (0.28, 0.16, 0.24), (0.3, 0.15, 0.2), (0.13, 0.11, 0.18), (0.05, 0.04, 0.05)),
    (20.8, (0.015, 0.02, 0.06), (0.05, 0.06, 0.12), (0.0, 0.0, 0.0), (0.085, 0.095, 0.15), (0.03, 0.03, 0.04)),
    (24.0, (0.015, 0.02, 0.06), (0.05, 0.06, 0.12), (0.0, 0.0, 0.0), (0.085, 0.095, 0.15), (0.03, 0.03, 0.04)),
]
MOON_COL = (0.14, 0.16, 0.27)


# ============================================================== the world
class World:
    def __init__(self, game):
        self.game = game
        self.gpu = GPUSpace()
        self.hour = START_HOUR
        self.night = 0.0
        self.time_scale = 1.0
        self.fog_scale = 1.0
        self.collision = Collision()
        self.lamps = []
        self.interior_lights = []
        self.shops = []
        self.businesses = []
        self.garage = None
        self.dealer = None
        self.parking_spots = []
        self.prop_spots = []
        self.pois = []
        self.bumps = []
        self.ramps = []                         # stunt park: (x0, z0, x1, z1, h_start, h_end, along_z)
        self.ramp_box = None
        self.featured_spawns = []
        self._init_shader_inputs()
        self.lights = LightManager(self)

        state = random.getstate()
        random.seed(1337)                      # the city layout is the same every run
        self._build_city()
        random.setstate(state)

        self.particles = Particles()
        self.decals = Decals()
        self.tire_marks = TireMarks()
        self.props = Props(self, self.prop_spots)
        self._build_sky()
        self._apply_lighting((0, 2, 0))

    # ------------------------------------------------------------ shader globals
    def _init_shader_inputs(self):
        z3 = LVecBase3f(0, 0, 0)
        scene.setShaderInput('emissive', 0.0)
        for name in ('sun_dir', 'sun_color', 'ambient_color', 'ground_color', 'fog_color'):
            scene.setShaderInput(name, z3)
        scene.setShaderInput('up_dir', self.gpu.vec((0, 1, 0)))
        scene.setShaderInput('fog_density', 0.004)
        scene.setShaderInput('light_count', 16.0)

    # ------------------------------------------------------------ geometry queries
    def lot_rect(self, i, j):
        return (ROADS[i] + HALF_ROAD, ROADS[j] + HALF_ROAD, ROADS[i + 1] - HALF_ROAD, ROADS[j + 1] - HALF_ROAD)

    def ground_height(self, x, z):
        h = 0.0
        i = int(math.floor((x - ROADS[0]) / CELL))
        j = int(math.floor((z - ROADS[0]) / CELL))
        if 0 <= i < N_BLOCKS and 0 <= j < N_BLOCKS:
            lx = x - ROADS[i]
            lz = z - ROADS[j]
            if HALF_ROAD <= lx <= CELL - HALF_ROAD and HALF_ROAD <= lz <= CELL - HALF_ROAD:
                h = CURB_H
        for (bx0, bz0, bx1, bz1, bh, along_z) in self.bumps:
            if bx0 <= x <= bx1 and bz0 <= z <= bz1:
                t = ((z - bz0) / (bz1 - bz0)) if along_z else ((x - bx0) / (bx1 - bx0))
                h = max(h, bh * (1.0 - abs(t * 2.0 - 1.0)))
        rb = self.ramp_box
        if rb is not None and rb[0] <= x <= rb[2] and rb[1] <= z <= rb[3]:
            for (rx0, rz0, rx1, rz1, h0, h1, along_z) in self.ramps:
                if rx0 <= x <= rx1 and rz0 <= z <= rz1:
                    t = ((z - rz0) / (rz1 - rz0)) if along_z else ((x - rx0) / (rx1 - rx0))
                    h = max(h, CURB_H + h0 + (h1 - h0) * t)
        return h

    def is_road(self, x, z):
        return self.ground_height(x, z) < 0.01 and ASPHALT_MIN <= x <= ASPHALT_MAX and ASPHALT_MIN <= z <= ASPHALT_MAX

    def node_pos(self, i, j):
        return (ROADS[i], ROADS[j])

    def node_neighbors(self, i, j):
        out = []
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = i + di, j + dj
            if 0 <= a <= N_BLOCKS and 0 <= b <= N_BLOCKS:
                out.append((a, b))
        return out

    def sidewalk_corners(self, i, j, inset=1.9):
        x0, z0, x1, z1 = self.lot_rect(i, j)
        return [(x0 + inset, z0 + inset), (x1 - inset, z0 + inset), (x1 - inset, z1 - inset), (x0 + inset, z1 - inset)]

    # ------------------------------------------------------------ city building
    def _build_city(self):
        B = {k: MeshBuilder() for k in ('ground', 'side', 'bld', 'glass', 'winlit', 'neon', 'lamps', 'misc')}
        self.B = B
        self._build_ground(B)
        self._build_roads(B)
        for i in range(N_BLOCKS):
            for j in range(N_BLOCKS):
                self._build_lot(B, i, j)
        self._build_streetlights(B)
        self._build_boundary(B)
        self.static_entities = []
        for key in ('ground', 'side', 'bld', 'glass', 'misc'):
            self.static_entities += B[key].entities()
        self.win_ents = B['winlit'].entities(emissive=0.0)
        self.lamp_ents = B['lamps'].entities(emissive=0.0)
        self.neon_ents = B['neon'].entities(emissive=0.7)
        self.B = None

    def _fbox(self, key, fr, lc, ls, col, top=None, collide=False, bottom=False):
        c = fr.p(*lc)
        s = fr.size(*ls)
        self.B[key].box(c, s, col, top, bottom)
        if collide:
            self.collision.add(c[0] - s[0] / 2, c[1] - s[1] / 2, c[2] - s[2] / 2,
                               c[0] + s[0] / 2, c[1] + s[1] / 2, c[2] + s[2] / 2)
        return c

    def _build_ground(self, B):
        ext = 900.0
        step = 40.0
        x = -300.0
        while x < 300.0:
            z = -300.0
            while z < 300.0:
                x1, z1 = x + step, z + step
                if not (x >= ASPHALT_MIN - 1e-6 and x1 <= ASPHALT_MAX + 1e-6 and z >= ASPHALT_MIN - 1e-6 and z1 <= ASPHALT_MAX + 1e-6):
                    # clip tiles against the asphalt square (split into up to 4 rectangles)
                    for (a0, b0, a1, b1) in self._minus_square(x, z, x1, z1, ASPHALT_MIN, ASPHALT_MAX):
                        B['ground'].rect_xz(a0, b0, a1, b1, -0.005, jitter(GRASS, 0.08))
                z = z1
            x += step
        for (a0, b0, a1, b1) in ((-ext, -ext, ext, -300), (-ext, 300, ext, ext), (-ext, -300, -300, 300), (300, -300, ext, 300)):
            B['ground'].rect_xz(a0, b0, a1, b1, -0.02, col_mul(GRASS, 0.85))

    @staticmethod
    def _minus_square(x0, z0, x1, z1, m0, m1):
        if x1 <= m0 or x0 >= m1 or z1 <= m0 or z0 >= m1:
            return [(x0, z0, x1, z1)]
        out = []
        if x0 < m0:
            out.append((x0, z0, m0, z1))
        if x1 > m1:
            out.append((m1, z0, x1, z1))
        cx0, cx1 = max(x0, m0), min(x1, m1)
        if z0 < m0:
            out.append((cx0, z0, cx1, m0))
        if z1 > m1:
            out.append((cx0, m1, cx1, z1))
        return out

    def _build_roads(self, B):
        g = B['ground']
        # intersections
        for rx in ROADS:
            for rz in ROADS:
                g.rect_xz(rx - HALF_ROAD, rz - HALF_ROAD, rx + HALF_ROAD, rz + HALF_ROAD, 0.0, jitter(col_mul(ASPHALT, 0.95), 0.03))
                # manhole
                g.cylinder((rx + 2.0, 0.006, rz - 2.5), 0.45, 0.01, rgb(40, 40, 42), seg=10)
        bump_choices = {(1, 2, 'z'), (3, 4, 'x'), (2, 1, 'x'), (4, 2, 'z')}
        for idx, rc in enumerate(ROADS):
            for k in range(N_BLOCKS):
                a0 = ROADS[k] + HALF_ROAD
                a1 = ROADS[k + 1] - HALF_ROAD
                # road running along z at x = rc
                g.rect_xz(rc - HALF_ROAD, a0, rc + HALF_ROAD, a1, 0.0, jitter(ASPHALT, 0.04))
                # road running along x at z = rc
                g.rect_xz(a0, rc - HALF_ROAD, a1, rc + HALF_ROAD, 0.0, jitter(ASPHALT, 0.04))
                y = 0.018
                # centre dashes + edge lines
                p = a0 + 10.0
                while p < a1 - 9.0:
                    g.rect_xz(rc - 0.08, p, rc + 0.08, p + 3.0, y, MARK)
                    g.rect_xz(p, rc - 0.08, p + 3.0, rc + 0.08, y, MARK)
                    p += 6.0
                for s in (-1, 1):
                    e = rc + s * (HALF_ROAD - 0.45)
                    g.rect_xz(e - 0.06, a0 + 9.3, e + 0.06, a1 - 9.3, y, MARK)
                    g.rect_xz(a0 + 9.3, e - 0.06, a1 - 9.3, e + 0.06, y, MARK)
                # zebra crossings at both ends of the segment
                for zc in (a0 + 1.7, a1 - 1.7):
                    xs = rc - HALF_ROAD + 0.6
                    while xs < rc + HALF_ROAD - 0.6:
                        g.rect_xz(xs, zc - 1.3, xs + 0.5, zc + 1.3, y + 0.002, MARK)
                        g.rect_xz(zc - 1.3, xs, zc + 1.3, xs + 0.5, y + 0.002, MARK)
                        xs += 1.0
                # stop lines
                for zc, sgn in ((a0 + 3.3, 1), (a1 - 3.3, -1)):
                    side_x0, side_x1 = (rc, rc + HALF_ROAD - 0.5) if sgn > 0 else (rc - HALF_ROAD + 0.5, rc)
                    g.rect_xz(side_x0, zc - 0.2, side_x1, zc + 0.2, y, MARK)
                    sz0, sz1 = (rc - HALF_ROAD + 0.5, rc) if sgn > 0 else (rc, rc + HALF_ROAD - 0.5)
                    g.rect_xz(zc - 0.2, sz0, zc + 0.2, sz1, y, MARK)
                # speed bumps (great for testing suspension)
                if (idx, k, 'z') in bump_choices:
                    self._speed_bump(B, rc - HALF_ROAD, (a0 + a1) / 2 - 0.8, rc + HALF_ROAD, (a0 + a1) / 2 + 0.8, True)
                if (idx, k, 'x') in bump_choices:
                    self._speed_bump(B, (a0 + a1) / 2 - 0.8, rc - HALF_ROAD, (a0 + a1) / 2 + 0.8, rc + HALF_ROAD, False)

    def _speed_bump(self, B, x0, z0, x1, z1, along_z, h=0.13):
        self.bumps.append((x0, z0, x1, z1, h, along_z))
        n = 10
        for s in range(n):
            col = rgb(235, 190, 30) if s % 2 == 0 else rgb(30, 30, 30)
            if along_z:
                a, b = x0 + (x1 - x0) * s / n, x0 + (x1 - x0) * (s + 1) / n
                zm = (z0 + z1) / 2
                B['ground'].hexa([(a, 0, z0), (b, 0, z0), (b, 0, z1), (a, 0, z1),
                                  (a, h, zm), (b, h, zm), (b, h, zm), (a, h, zm)], col)
            else:
                a, b = z0 + (z1 - z0) * s / n, z0 + (z1 - z0) * (s + 1) / n
                xm = (x0 + x1) / 2
                B['ground'].hexa([(x0, 0, a), (x1, 0, a), (x1, 0, b), (x0, 0, b),
                                  (xm, h, a), (xm, h, a), (xm, h, b), (xm, h, b)], col)

    # ---------------------------------------------------------------- lots
    def _facing(self, i, j):
        c = (N_BLOCKS - 1) / 2.0
        if abs(i - c) >= abs(j - c) and i != c:
            return 'E' if i < c else 'W'
        return 'N' if j < c else 'S'

    def _special_frame(self, inner, side, d):
        ix0, iz0, ix1, iz1 = inner
        cx, cz = (ix0 + ix1) / 2, (iz0 + iz1) / 2
        if side == 'S':
            return Frame(cx, iz0 + d / 2, 0), (ix0, iz0 + d + 2.5, ix1, iz1)
        if side == 'N':
            return Frame(cx, iz1 - d / 2, 180), (ix0, iz0, ix1, iz1 - d - 2.5)
        if side == 'E':
            return Frame(ix1 - d / 2, cz, -90), (ix0, iz0, ix1 - d - 2.5, iz1)
        return Frame(ix0 + d / 2, cz, 90), (ix0 + d + 2.5, iz0, ix1, iz1)

    def _build_lot(self, B, i, j):
        x0, z0, x1, z1 = self.lot_rect(i, j)
        B['side'].box(((x0 + x1) / 2, CURB_H / 2, (z0 + z1) / 2), (x1 - x0, CURB_H, z1 - z0), CURB_COL,
                      top_col=jitter(SIDEWALK_COL, 0.03))
        inner = (x0 + SIDEWALK, z0 + SIDEWALK, x1 - SIDEWALK, z1 - SIDEWALK)
        ix0, iz0, ix1, iz1 = inner
        # sidewalk tile seams for a bit of texture
        for t in range(1, int((x1 - x0) / 2.0)):
            xx = x0 + t * 2.0
            B['side'].rect_xz(xx - 0.02, z0, xx + 0.02, iz0, CURB_H + 0.004, col_mul(SIDEWALK_COL, 0.88))
            B['side'].rect_xz(xx - 0.02, iz1, xx + 0.02, z1, CURB_H + 0.004, col_mul(SIDEWALK_COL, 0.88))
        for t in range(1, int((z1 - z0) / 2.0)):
            zz = z0 + t * 2.0
            B['side'].rect_xz(x0, zz - 0.02, ix0, zz + 0.02, CURB_H + 0.004, col_mul(SIDEWALK_COL, 0.88))
            B['side'].rect_xz(ix1, zz - 0.02, x1, zz + 0.02, CURB_H + 0.004, col_mul(SIDEWALK_COL, 0.88))

        spec = LOT_SPECIAL.get((i, j))
        c = (N_BLOCKS - 1) / 2.0
        dist = math.hypot(i - c, j - c)
        tall = 1.0 + max(0.0, 2.0 - 0.55 * dist)
        open_lot = spec is not None and spec[0] in ('park', 'park2', 'parking', 'stunt', 'industrial', 'field')
        if spec is None or spec[0] in ('park', 'park2', 'field'):
            self._street_trees(B, i, j)
        if spec is None:
            if dist <= DOWNTOWN_RADIUS:
                self._skyscrapers(B, inner)
            elif dist >= 2.6 and random.random() < 0.75:
                self._rowhouses(B, inner)              # quieter residential outskirts
            elif random.random() < 0.4:
                self._rowhouses(B, inner)
            else:
                self._blocks(B, inner, tall)
            return
        kind = spec[0]
        side = self._facing(i, j)
        if kind == 'industrial':
            self._industrial(B, inner)
            return
        if kind == 'stunt':
            self._stunt_park(B, inner)
            return
        if kind == 'field':
            self._football_field(B, inner)
            return
        if kind == 'park2':
            self._park2(B, inner)
            return
        if kind == 'park':
            self._park(B, inner)
        elif kind == 'parking':
            self._parking(B, inner)
        elif kind == 'shop':
            fr, rest = self._special_frame(inner, side, 14.0)
            self._shop(B, fr, spec[1], spec[2])
            self._blocks(B, rest, tall * 0.9, allow_split=False)
        elif kind == 'garage':
            fr, rest = self._special_frame(inner, side, 16.0)
            self._garage(B, fr)
            self._blocks(B, rest, tall * 0.8, allow_split=False)
        elif kind == 'business':
            fr, rest = self._special_frame(inner, side, 12.0)
            self._business(B, fr, spec[1], spec[2], spec[3])
            self._blocks(B, rest, tall * 0.9, allow_split=False)

    def _plaza_props(self, inner):
        ix0, iz0, ix1, iz1 = inner
        for _ in range(3):
            self.prop_spots.append((random.choice(('box', 'crate', 'box')), random.uniform(ix0 + 1, ix1 - 1),
                                    random.uniform(iz0 + 1, iz1 - 1)))

    # ---- generic modern blocks
    def _blocks(self, B, rect, tall, allow_split=True):
        x0, z0, x1, z1 = rect
        w, d = x1 - x0, z1 - z0
        if w < 7 or d < 7:
            return
        r = random.random()
        parts = []
        gap = 2.2
        if allow_split and w > 22 and d > 22 and r < 0.35:
            mx, mz = (x0 + x1) / 2, (z0 + z1) / 2
            parts = [(x0, z0, mx - gap / 2, mz - gap / 2), (mx + gap / 2, z0, x1, mz - gap / 2),
                     (x0, mz + gap / 2, mx - gap / 2, z1), (mx + gap / 2, mz + gap / 2, x1, z1)]
        elif allow_split and r < 0.72:
            t = random.uniform(0.4, 0.6)
            if w >= d:
                m = x0 + w * t
                parts = [(x0, z0, m - gap / 2, z1), (m + gap / 2, z0, x1, z1)]
            else:
                m = z0 + d * t
                parts = [(x0, z0, x1, m - gap / 2), (x0, m + gap / 2, x1, z1)]
        else:
            parts = [(x0, z0, x1, z1)]
        for p in parts:
            self._tower(B, p, random.uniform(9.0, 21.0) * tall)

    def _tower(self, B, rect, h):
        x0, z0, x1, z1 = rect
        cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
        w, d = x1 - x0, z1 - z0
        base = CURB_H
        fac = random.choice(FACADES)
        B['bld'].box((cx, base + h / 2, cz), (w, h, d), fac, top_col=ROOF_COL)
        B['bld'].box((cx, base + 0.35, cz), (w + 0.16, 0.7, d + 0.16), col_mul(fac, 0.55))
        B['bld'].box((cx, base + h + 0.2, cz), (w + 0.4, 0.45, d + 0.4), col_mul(fac, 0.8), top_col=ROOF_COL)
        for _ in range(random.randint(1, 3)):
            ax, az = random.uniform(x0 + 1.5, x1 - 1.5), random.uniform(z0 + 1.5, z1 - 1.5)
            B['misc'].box((ax, base + h + 0.9, az), (random.uniform(1.0, 2.2), 1.0, random.uniform(1.0, 2.2)), rgb(150, 152, 155))
        if random.random() < 0.35:
            B['misc'].cylinder((cx + w * 0.2, base + h + 1.6, cz - d * 0.2), 1.0, 2.4, rgb(110, 90, 70), seg=10)
        if random.random() < 0.3:
            B['misc'].cylinder((cx - w * 0.25, base + h + 3.0, cz + d * 0.25), 0.05, 5.0, POLE, seg=5)
        modern = fac in (FACADES[7], FACADES[5]) or random.random() < 0.25
        self._facade_windows(B, x0, z0, x1, z1, base, h, modern)
        self.collision.add(x0, -5, z0, x1, base + h + 0.45, z1)

    def _facade_windows(self, B, x0, z0, x1, z1, base, h, modern=False):
        faces = (((x0, z0), (x1, z0), (0.0, 0.0, -1.0)), ((x1, z1), (x0, z1), (0.0, 0.0, 1.0)),
                 ((x0, z1), (x0, z0), (-1.0, 0.0, 0.0)), ((x1, z0), (x1, z1), (1.0, 0.0, 0.0)))
        spacing = 2.4 if modern else 3.0
        ww, wh = (2.0, 2.3) if modern else (1.3, 1.8)
        for (a, b, n) in faces:
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            along = ((b[0] - a[0]) / L, 0.0, (b[1] - a[1]) / L)
            cols = int((L - 1.6) / spacing)
            if cols < 1:
                continue
            margin = (L - (cols - 1) * spacing) / 2
            y = base + 4.3
            while y + wh < base + h - 0.6:
                for k in range(cols):
                    t = margin + k * spacing
                    c = (a[0] + along[0] * t, y + wh / 2, a[1] + along[2] * t)
                    if random.random() < 0.5:
                        tint = random.choice((Color(1, 1, 1, 1), Color(1, 0.9, 0.74, 1), Color(0.86, 0.94, 1, 1), Color(1, 0.8, 0.6, 1)))
                        B['winlit'].face_quad(c, along, (0, 1, 0), n, ww, wh, tint)
                    else:
                        B['glass'].face_quad(c, along, (0, 1, 0), n, ww, wh, jitter(GLASS_DARK, 0.1))
                y += 3.2
            # ground floor shop band + awning
            if random.random() < 0.55 and L > 6:
                c = ((a[0] + b[0]) / 2, base + 2.0, (a[1] + b[1]) / 2)
                B['winlit'].face_quad(c, along, (0, 1, 0), n, L - 2.0, 2.2, Color(1, 0.93, 0.82, 1))
                aw = random.choice((rgb(180, 40, 40), rgb(30, 90, 160), rgb(40, 120, 70), rgb(200, 140, 30), rgb(60, 60, 60)))
                ac = (c[0] + n[0] * 0.7, base + 3.45, c[2] + n[2] * 0.7)
                if abs(n[2]) > 0.5:
                    B['misc'].box(ac, (L - 3.0, 0.12, 1.4), aw)
                else:
                    B['misc'].box(ac, (1.4, 0.12, L - 3.0), aw)

    # ---- Dutch row houses around a courtyard
    def _rowhouses(self, B, rect):
        x0, z0, x1, z1 = rect
        depth = 9.0
        strips = (('S', x0, z0, x1, z0 + depth), ('N', x0, z1 - depth, x1, z1),
                  ('W', x0, z0 + depth, x0 + depth, z1 - depth), ('E', x1 - depth, z0 + depth, x1, z1 - depth))
        for side, a0, b0, a1, b1 in strips:
            along_x = side in ('S', 'N')
            length = (a1 - a0) if along_x else (b1 - b0)
            pos = 0.0
            while pos < length - 0.5:
                wdt = random.uniform(4.6, 7.2)
                if length - pos - wdt < 3.6:
                    wdt = length - pos
                if along_x:
                    r = (a0 + pos, b0, a0 + pos + wdt, b1)
                else:
                    r = (a0, b0 + pos, a1, b0 + pos + wdt)
                self._canal_house(B, r, side, random.uniform(9.0, 15.5))
                pos += wdt
        # courtyard garden
        cx0, cz0, cx1, cz1 = x0 + depth, z0 + depth, x1 - depth, z1 - depth
        B['side'].rect_xz(cx0, cz0, cx1, cz1, CURB_H + 0.012, jitter(GRASS, 0.05))
        self._tree(B, (cx0 + cx1) / 2, (cz0 + cz1) / 2, 1.1)

    def _canal_house(self, B, r, side, h):
        x0, z0, x1, z1 = r
        base = CURB_H
        brick = jitter(random.choice(BRICKS), 0.05)
        cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
        B['bld'].box((cx, base + h / 2, cz), (x1 - x0, h, z1 - z0), brick)
        yb = base + h
        roof = random.choice(TILE_ROOF)
        along_x = side in ('S', 'N')
        if along_x:
            gh = (x1 - x0) * 0.62
            pts = [(x0, yb, z0), (x1, yb, z0), (x1, yb, z1), (x0, yb, z1),
                   (cx, yb + gh, z0), (cx, yb + gh, z0), (cx, yb + gh, z1), (cx, yb + gh, z1)]
            B['bld'].hexa(pts, roof, face_cols={2: brick, 4: brick})
        else:
            gh = (z1 - z0) * 0.62
            pts = [(x0, yb, z0), (x1, yb, z0), (x1, yb, z1), (x0, yb, z1),
                   (x0, yb + gh, cz), (x1, yb + gh, cz), (x1, yb + gh, cz), (x0, yb + gh, cz)]
            B['bld'].hexa(pts, roof, face_cols={3: brick, 5: brick})
        # street facade
        if side == 'S':
            fc, along, n, L = (cx, 0, z0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0), x1 - x0
        elif side == 'N':
            fc, along, n, L = (cx, 0, z1), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), x1 - x0
        elif side == 'W':
            fc, along, n, L = (x0, 0, cz), (0.0, 0.0, -1.0), (-1.0, 0.0, 0.0), z1 - z0
        else:
            fc, along, n, L = (x1, 0, cz), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), z1 - z0
        white = rgb(236, 236, 230)
        # cornice line
        cl = (fc[0], yb - 0.15, fc[2])
        B['bld'].face_quad(cl, along, (0, 1, 0), n, L, 0.3, white, 0.03)
        # door + ground floor window
        door_t = -L * 0.28
        dc = (fc[0] + along[0] * door_t, base + 1.15, fc[2] + along[2] * door_t)
        B['bld'].face_quad(dc, along, (0, 1, 0), n, 1.05, 2.3, random.choice((rgb(30, 50, 40), rgb(60, 30, 30), rgb(25, 30, 55), rgb(40, 40, 40))), 0.04)
        B['bld'].face_quad(dc, along, (0, 1, 0), n, 1.25, 2.45, white, 0.025)
        wc = (fc[0] + along[0] * L * 0.18, base + 1.6, fc[2] + along[2] * L * 0.18)
        B['bld'].face_quad(wc, along, (0, 1, 0), n, L * 0.45, 2.0, white, 0.025)
        if random.random() < 0.55:
            B['winlit'].face_quad(wc, along, (0, 1, 0), n, L * 0.45 - 0.2, 1.8, Color(1, 0.88, 0.7, 1), 0.04)
        else:
            B['glass'].face_quad(wc, along, (0, 1, 0), n, L * 0.45 - 0.2, 1.8, GLASS_DARK, 0.04)
        # upper floors
        ncols = 2 if L < 6.0 else 3
        y = base + 3.6
        while y + 1.9 < yb - 0.4:
            for k in range(ncols):
                t = (k - (ncols - 1) / 2.0) * (L / (ncols + 0.4))
                c = (fc[0] + along[0] * t, y + 0.95, fc[2] + along[2] * t)
                B['bld'].face_quad(c, along, (0, 1, 0), n, 1.15, 2.0, white, 0.025)
                if random.random() < 0.45:
                    B['winlit'].face_quad(c, along, (0, 1, 0), n, 0.95, 1.8, random.choice((Color(1, 0.9, 0.72, 1), Color(1, 0.82, 0.6, 1), Color(0.9, 0.95, 1, 1))), 0.04)
                else:
                    B['glass'].face_quad(c, along, (0, 1, 0), n, 0.95, 1.8, jitter(GLASS_DARK, 0.1), 0.04)
            y += 3.0
        # gable window + hoisting beam (very Amsterdam)
        gc = (fc[0], yb + 0.9, fc[2])
        B['bld'].face_quad(gc, along, (0, 1, 0), n, 0.8, 1.0, white, 0.025)
        B['glass'].face_quad(gc, along, (0, 1, 0), n, 0.6, 0.8, GLASS_DARK, 0.04)
        hb = (fc[0] + n[0] * 0.5, yb + 1.8, fc[2] + n[2] * 0.5)
        B['misc'].box(hb, (0.15 + abs(n[0]) * 0.85, 0.15, 0.15 + abs(n[2]) * 0.85), rgb(60, 40, 30))
        self.collision.add(x0, -5, z0, x1, yb + 1.0, z1)

    # ---- park with fountain and the fireworks dealer
    def _park(self, B, inner):
        ix0, iz0, ix1, iz1 = inner
        cx, cz = (ix0 + ix1) / 2, (iz0 + iz1) / 2
        B['side'].rect_xz(ix0, iz0, ix1, iz1, CURB_H + 0.012, jitter(GRASS, 0.04))
        path = rgb(196, 176, 140)
        B['side'].rect_xz(cx - 1.4, iz0 - 0.5, cx + 1.4, iz1 + 0.5, CURB_H + 0.018, path)
        B['side'].rect_xz(ix0 - 0.5, cz - 1.4, ix1 + 0.5, cz + 1.4, CURB_H + 0.019, path)
        # fountain
        base = CURB_H
        B['misc'].cylinder((cx, base + 0.35, cz), 4.0, 0.7, rgb(150, 150, 152), seg=20)
        B['neon'].cylinder((cx, base + 0.66, cz), 3.6, 0.06, rgb(70, 140, 190), seg=20)
        B['misc'].cylinder((cx, base + 1.4, cz), 0.45, 2.0, rgb(160, 160, 162), seg=10)
        B['misc'].cylinder((cx, base + 2.5, cz), 1.2, 0.25, rgb(150, 150, 152), seg=14)
        self.collision.add(cx - 3.6, -1, cz - 3.6, cx + 3.6, base + 1.0, cz + 3.6)
        self.fountain = (cx, base + 2.7, cz)
        # trees and benches
        for (tx, tz) in ((ix0 + 4, iz0 + 4), (ix1 - 4, iz0 + 4), (ix0 + 4, iz1 - 4), (ix1 - 4, iz1 - 4),
                         (ix0 + 9, cz + 7), (ix1 - 9, cz - 7), (cx + 8, iz1 - 6), (cx - 8, iz0 + 9), (ix0 + 3, cz - 6)):
            self._tree(B, tx, tz, random.uniform(0.9, 1.3))
        for (bx, bz, rot) in ((cx + 5.5, cz + 2.4, 0), (cx - 5.5, cz - 2.4, 0), (cx + 2.4, cz + 5.5, 90), (cx - 2.4, cz - 5.5, 90)):
            self._bench(B, bx, bz, rot)
        # fireworks dealer stall on the south path entrance
        sx, sz = cx + 5.5, iz0 + 3.2
        fr = Frame(sx, sz, 0)
        self._fbox('misc', fr, (0, 1.1, 0.4), (4.4, 0.08, 2.6), rgb(200, 30, 30))                    # canopy
        for px in (-2.1, 2.1):
            for pz in (-0.8, 1.6):
                self._fbox('misc', fr, (px, 0.55, pz), (0.08, 1.1, 0.08), POLE)
        self._fbox('misc', fr, (0, 2.6, -0.85), (4.4, 0.7, 0.1), rgb(20, 20, 20))
        self._fbox('misc', fr, (0, 0.45, -0.2), (3.6, 0.9, 0.9), rgb(90, 60, 40), collide=True)     # table
        for k in range(9):
            col = random.choice((rgb(220, 30, 40), rgb(240, 200, 30), rgb(40, 90, 220), rgb(30, 160, 60)))
            self._fbox('misc', fr, (-1.5 + k * 0.38, 1.05, -0.2 + random.uniform(-0.2, 0.2)), (0.3, 0.3, 0.3), col)
        for px in (-2.1, 2.1):
            self._fbox('misc', fr, (px, 1.75, -0.8), (0.08, 1.4, 0.08), POLE)
        self._fbox('neon', fr, (0, 2.6, -0.92), (4.0, 0.5, 0.04), rgb(255, 120, 20))
        world_text('FIREWORKS', fr.p(0, 2.6, -0.98), fr.a, 0.42, rgb(20, 10, 0))
        self._fbox('misc', fr, (0, 1.12, 0.1), (4.5, 0.04, 2.8), rgb(240, 240, 240))
        self.dealer = dict(pos=fr.p(0, 0, -1.6), npc=fr.p(0, 0, 0.6), npc_yaw=fr.yaw_of(0, -1), name='Fireworks Dealer')
        self.interior_lights.append((fr.p(0, 1.0, -0.3), (1.0, 0.55, 0.25), 7.0))
        self.pois.append((sx, sz, 'dealer'))
        self.player_spawn = (cx - 2.0, CURB_H, iz0 - 1.6)
        self.hospital_spawn = self.player_spawn
        # starter vehicles parked by the curb right in front of the park
        rz = iz0 - SIDEWALK - HALF_ROAD + 5.0         # the road just south of the park
        self.featured_spawns = [('kickscooter', cx - 12.5, rz, -90.0), ('scooter', cx - 9.0, rz, -90.0), ('motorbike', cx - 5.5, rz, -90.0),
                                ('sports', cx + 4.0, rz, -90.0)]

    # ================================================================= new districts
    def _street_trees(self, B, i, j):
        """Trees along the sidewalk, away from the zebra crossings at the corners."""
        x0, z0, x1, z1 = self.lot_rect(i, j)
        o = 0.95
        for (ax, az, bx, bz) in ((x0, z0 + o, x1, z0 + o), (x0, z1 - o, x1, z1 - o),
                                 (x0 + o, z0, x0 + o, z1), (x1 - o, z0, x1 - o, z1)):
            L = math.hypot(bx - ax, bz - az)
            t = 8.0
            while t < L - 8.0:
                k = t / L
                self._tree(B, ax + (bx - ax) * k, az + (bz - az) * k, random.uniform(0.75, 1.0))
                t += random.uniform(11.0, 15.0)

    def _skyscrapers(self, B, inner):
        """Downtown: glass towers with a podium, setbacks, a crown and an aviation light."""
        ix0, iz0, ix1, iz1 = inner
        w, d = ix1 - ix0, iz1 - iz0
        if random.random() < 0.5:
            parts = [(ix0 + 1, iz0 + 1, ix1 - 1, iz1 - 1)]
        elif w >= d:
            m = (ix0 + ix1) / 2
            parts = [(ix0 + 1, iz0 + 1, m - 1.5, iz1 - 1), (m + 1.5, iz0 + 1, ix1 - 1, iz1 - 1)]
        else:
            m = (iz0 + iz1) / 2
            parts = [(ix0 + 1, iz0 + 1, ix1 - 1, m - 1.5), (ix0 + 1, m + 1.5, ix1 - 1, iz1 - 1)]
        for p in parts:
            self._glass_tower(B, p, random.uniform(42.0, 90.0) / (1.0 if len(parts) == 1 else 1.25))

    def _glass_tower(self, B, rect, h):
        x0, z0, x1, z1 = rect
        base = CURB_H
        glass = random.choice((rgb(52, 78, 104), rgb(40, 62, 80), rgb(70, 96, 110), rgb(36, 54, 70), rgb(92, 110, 120)))
        frame = random.choice((rgb(170, 176, 182), rgb(60, 64, 70), rgb(200, 196, 186), rgb(40, 42, 46)))
        # podium: a 2-storey stone base with lit shop windows
        pod_h = 7.5
        cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
        B['bld'].box((cx, base + pod_h / 2, cz), (x1 - x0, pod_h, z1 - z0), rgb(150, 146, 138), top_col=ROOF_COL)
        self._facade_windows(B, x0, z0, x1, z1, base - 3.0, pod_h + 2.0, modern=True)
        self.collision.add(x0, -5, z0, x1, base + pod_h, z1)
        # tiers with setbacks
        y = base + pod_h
        tiers = random.choice(((0.62, 0.28, 0.10), (0.75, 0.25), (1.0,), (0.5, 0.3, 0.2)))
        inset = random.uniform(1.0, 2.0)
        bx0, bz0, bx1, bz1 = x0 + inset, z0 + inset, x1 - inset, z1 - inset
        for k, frac in enumerate(tiers):
            th = (h - pod_h) * frac
            if bx1 - bx0 < 5 or bz1 - bz0 < 5:
                break
            tcx, tcz = (bx0 + bx1) / 2, (bz0 + bz1) / 2
            tw, td = bx1 - bx0, bz1 - bz0
            B['glass'].box((tcx, y + th / 2, tcz), (tw, th, td), glass)
            # vertical mullions + floor bands make it read as a curtain wall
            for f in range(1, int(th / 3.6)):
                yy = y + f * 3.6
                B['bld'].box((tcx, yy, tcz), (tw + 0.12, 0.22, td + 0.12), frame)
            nm = max(2, int(tw / 3.2))
            for m in range(nm + 1):
                xx = bx0 + tw * m / nm
                for zz in (bz0 - 0.05, bz1 + 0.05):
                    B['bld'].box((xx, y + th / 2, zz), (0.18, th, 0.12), frame)
            nm = max(2, int(td / 3.2))
            for m in range(nm + 1):
                zz = bz0 + td * m / nm
                for xx in (bx0 - 0.05, bx1 + 0.05):
                    B['bld'].box((xx, y + th / 2, zz), (0.12, th, 0.18), frame)
            # lit offices at night
            for f in range(int(th / 3.6)):
                yy = y + f * 3.6 + 1.8
                for (ax, az, bx, bz, n) in ((bx0, bz0 - 0.08, bx1, bz0 - 0.08, (0, 0, -1)), (bx1, bz1 + 0.08, bx0, bz1 + 0.08, (0, 0, 1)),
                                            (bx0 - 0.08, bz1, bx0 - 0.08, bz0, (-1, 0, 0)), (bx1 + 0.08, bz0, bx1 + 0.08, bz1, (1, 0, 0))):
                    L = math.hypot(bx - ax, bz - az)
                    along = ((bx - ax) / L, 0.0, (bz - az) / L)
                    t = 1.6
                    while t < L - 1.6:
                        if random.random() < 0.33:
                            run = min(random.uniform(3.0, 8.0), L - 1.6 - t)
                            c = (ax + along[0] * (t + run / 2), yy, az + along[2] * (t + run / 2))
                            B['winlit'].face_quad(c, along, (0, 1, 0), n, run, 2.2,
                                                  random.choice((Color(1, 1, 1, 1), Color(0.86, 0.94, 1, 1), Color(1, 0.93, 0.8, 1))), 0.02)
                            t += run + random.uniform(1.0, 4.0)
                        else:
                            t += random.uniform(3.0, 7.0)
            self.collision.add(bx0, base, bz0, bx1, y + th, bz1)
            y += th
            s = random.uniform(1.6, 3.2)
            bx0, bz0, bx1, bz1 = bx0 + s, bz0 + s, bx1 - s, bz1 - s
        # crown, rooftop plant and aviation light
        tcx, tcz = (bx0 + bx1) / 2, (bz0 + bz1) / 2
        B['bld'].box((tcx, y + 0.6, tcz), (max(3, bx1 - bx0 + 2), 1.2, max(3, bz1 - bz0 + 2)), frame)
        B['misc'].box((tcx + 1.0, y + 2.2, tcz - 0.8), (2.6, 2.0, 2.0), rgb(150, 152, 155))
        if random.random() < 0.6:
            B['misc'].cylinder((tcx, y + 9.0, tcz), 0.12, 16.0, POLE, seg=6, radius_top=0.05)
            B['neon'].sphere((tcx, y + 17.2, tcz), 0.35, rgb(255, 30, 20), 3, 6)
        else:
            B['neon'].sphere((tcx, y + 1.5, tcz), 0.35, rgb(255, 30, 20), 3, 6)

    def _industrial(self, B, inner):
        """Docks / industry: warehouses, stacked shipping containers, a gantry crane, a fence."""
        ix0, iz0, ix1, iz1 = inner
        base = CURB_H
        B['side'].rect_xz(ix0, iz0, ix1, iz1, base + 0.012, rgb(86, 86, 84))
        for k in range(6):                                                            # painted yard lines
            zz = iz0 + 4 + k * (iz1 - iz0 - 8) / 5
            B['side'].rect_xz(ix0 + 2, zz - 0.06, ix1 - 2, zz + 0.06, base + 0.02, rgb(220, 190, 40))
        cx, cz = (ix0 + ix1) / 2, (iz0 + iz1) / 2
        # warehouse with corrugated walls, roller doors and a sawtooth roof
        wx0, wz0, wx1, wz1 = ix0 + 1, iz0 + 1, ix0 + (ix1 - ix0) * 0.55, iz1 - 1
        wh = random.uniform(9.0, 12.0)
        wall = random.choice((rgb(120, 128, 136), rgb(150, 120, 90), rgb(96, 110, 96), rgb(170, 170, 165)))
        wcx, wcz = (wx0 + wx1) / 2, (wz0 + wz1) / 2
        B['bld'].box((wcx, base + wh / 2, wcz), (wx1 - wx0, wh, wz1 - wz0), wall, top_col=ROOF_COL)
        x = wx0 + 0.5
        while x < wx1:
            for zz in (wz0 - 0.04, wz1 + 0.04):
                B['bld'].box((x, base + wh / 2, zz), (0.16, wh, 0.1), col_mul(wall, 0.82))
            x += 0.9
        z = wz0 + 0.5
        while z < wz1:
            B['bld'].box((wx1 + 0.04, base + wh / 2, z), (0.1, wh, 0.16), col_mul(wall, 0.82))
            z += 0.9
        for k in range(3):
            zc = wz0 + (k + 0.5) * (wz1 - wz0) / 3
            B['misc'].box((wx1 + 0.08, base + 2.4, zc), (0.12, 4.6, 4.2), rgb(70, 72, 76))     # roller door
            for s in range(9):
                B['misc'].box((wx1 + 0.15, base + 0.4 + s * 0.5, zc), (0.04, 0.05, 4.2), rgb(50, 52, 56))
            B['lamps'].box((wx1 + 0.3, base + 5.2, zc), (0.3, 0.2, 0.6), Color(1, 0.95, 0.8, 1))
            self.interior_lights.append(((wx1 + 2.0, base + 4.5, zc), (1.0, 0.9, 0.7), 9.0))
        n_saw = max(2, int((wz1 - wz0) / 6))
        for k in range(n_saw):
            za, zb = wz0 + k * (wz1 - wz0) / n_saw, wz0 + (k + 1) * (wz1 - wz0) / n_saw
            yb = base + wh
            B['bld'].hexa([(wx0, yb, za), (wx1, yb, za), (wx1, yb, zb), (wx0, yb, zb),
                           (wx0, yb, za), (wx1, yb, za), (wx1, yb + 2.2, zb - 0.3), (wx0, yb + 2.2, zb - 0.3)], ROOF_COL)
            B['glass'].face_quad((wcx, yb + 1.1, zb - 0.15), (1, 0, 0), (0, 1, 0), (0, 0, 1), wx1 - wx0 - 0.4, 2.0, GLASS_DARK, 0.02)
        self.collision.add(wx0, -5, wz0, wx1, base + wh + 2.2, wz1)
        # container yard
        cols = (rgb(190, 50, 40), rgb(40, 90, 160), rgb(220, 150, 30), rgb(40, 130, 80), rgb(120, 120, 126), rgb(230, 230, 228),
                rgb(110, 60, 120), rgb(200, 90, 30))
        yx0 = wx1 + 7.0
        zz = iz0 + 2.0
        while zz + 2.6 < iz1 - 2.0:
            if random.random() < 0.8:
                xx = yx0 + random.uniform(0, 1.5)
                stack = random.choice((1, 1, 2, 2, 3))
                for s in range(stack):
                    self._container(B, xx + 3.05, base + s * 2.6, zz + 1.25, random.choice(cols))
                self.collision.add(xx, base, zz, xx + 6.1, base + stack * 2.6, zz + 2.5)
            zz += 3.2
        # gantry crane over the yard
        gx0, gx1 = yx0 - 1.5, min(ix1 - 0.8, yx0 + 9.5)
        gz = cz + random.uniform(-6, 6)
        ch = 16.0
        crane = rgb(230, 170, 20)
        for gxx in (gx0, gx1):
            for dz in (-3.0, 3.0):
                B['misc'].box((gxx, base + ch / 2, gz + dz), (0.6, ch, 0.6), crane)
                self.collision.add(gxx - 0.3, base, gz + dz - 0.3, gxx + 0.3, base + ch, gz + dz + 0.3)
            B['misc'].box((gxx, base + ch - 0.4, gz), (0.7, 0.8, 6.6), crane)
        for dz in (-3.0, 3.0):
            B['misc'].box(((gx0 + gx1) / 2, base + ch + 0.4, gz + dz), (gx1 - gx0 + 1.2, 1.0, 0.7), crane)
        B['misc'].box(((gx0 + gx1) / 2 + 1.5, base + ch - 0.4, gz), (2.4, 1.6, 2.4), rgb(60, 62, 66))
        B['misc'].cylinder(((gx0 + gx1) / 2 + 1.5, base + ch - 5.0, gz), 0.05, 8.0, rgb(30, 30, 30), seg=4)
        B['neon'].sphere(((gx0 + gx1) / 2, base + ch + 1.2, gz), 0.3, rgb(255, 120, 0), 3, 6)
        # fence posts along the back, barrels and pallets as knock-over props
        for k in range(int((ix1 - ix0) / 2.5)):
            px = ix0 + 1 + k * 2.5
            B['misc'].cylinder((px, base + 1.0, iz1 - 0.4), 0.05, 2.0, POLE, seg=5)
        B['misc'].box(((ix0 + ix1) / 2, base + 1.9, iz1 - 0.4), (ix1 - ix0 - 2, 0.05, 0.05), POLE)
        B['misc'].box(((ix0 + ix1) / 2, base + 1.0, iz1 - 0.4), (ix1 - ix0 - 2, 1.8, 0.02), rgb(120, 126, 130, 255))
        self.collision.add(ix0, base, iz1 - 0.5, ix1, base + 2.0, iz1 - 0.3)
        for _ in range(6):
            self.prop_spots.append((random.choice(('crate', 'box', 'crate')), random.uniform(wx1 + 2, yx0 - 1.5),
                                    random.uniform(iz0 + 2, iz1 - 3)))
        self.pois.append((cx, cz, 'industrial'))

    def _container(self, B, x, y, z, col):
        L, W, H = 6.1, 2.5, 2.6
        B['bld'].box((x, y + H / 2, z), (L, H, W), col, top_col=col_mul(col, 0.9))
        k = 0.0
        while k < L - 0.2:                                               # corrugation ribs
            B['bld'].box((x - L / 2 + 0.2 + k, y + H / 2, z - W / 2 - 0.03), (0.12, H - 0.25, 0.06), col_mul(col, 0.8))
            B['bld'].box((x - L / 2 + 0.2 + k, y + H / 2, z + W / 2 + 0.03), (0.12, H - 0.25, 0.06), col_mul(col, 0.8))
            k += 0.45
        for s in (-1, 1):                                                # door end with locking bars
            B['bld'].box((x + s * (L / 2 + 0.02), y + H / 2, z), (0.06, H - 0.1, W - 0.1), col_mul(col, 0.7))
        for b in (-0.6, -0.2, 0.2, 0.6):
            B['misc'].box((x + L / 2 + 0.07, y + H / 2, z + b), (0.05, H - 0.4, 0.05), rgb(60, 60, 60))

    def _stunt_park(self, B, inner):
        """Concrete stunt park: kickers, a big gap jump, a bowl wall and mini ramps for e-scooters.
        The ramps are real ground (ground_height), so cars and bikes actually launch off them."""
        ix0, iz0, ix1, iz1 = inner
        base = CURB_H
        B['side'].rect_xz(ix0, iz0, ix1, iz1, base + 0.012, rgb(150, 150, 146))
        self.ramp_box = (ix0, iz0, ix1, iz1)
        cx, cz = (ix0 + ix1) / 2, (iz0 + iz1) / 2
        stripe = (rgb(240, 190, 20), rgb(30, 30, 32))

        def ramp(x0, z0, x1, z1, h0, h1, along_z, back=True):
            self.ramps.append((x0, z0, x1, z1, h0, h1, along_z))
            n = 8
            for s in range(n):                                       # striped deck, built in slices
                ta, tb = s / n, (s + 1) / n
                ya, yb = base + h0 + (h1 - h0) * ta, base + h0 + (h1 - h0) * tb
                col = stripe[s % 2] if s in (0, n - 1) else rgb(176, 176, 172)
                if along_z:
                    za, zb = z0 + (z1 - z0) * ta, z0 + (z1 - z0) * tb
                    B['misc'].hexa([(x0, base, za), (x1, base, za), (x1, base, zb), (x0, base, zb),
                                    (x0, ya, za), (x1, ya, za), (x1, yb, zb), (x0, yb, zb)], col)
                else:
                    xa, xb = x0 + (x1 - x0) * ta, x0 + (x1 - x0) * tb
                    B['misc'].hexa([(xa, base, z0), (xb, base, z0), (xb, base, z1), (xa, base, z1),
                                    (xa, ya, z0), (xb, yb, z0), (xb, yb, z1), (xa, ya, z1)], col)
            if back:                                                 # the vertical back stops you driving up the wrong way
                hi = max(h0, h1)
                if along_z:
                    zb = z1 if h1 > h0 else z0
                    self.collision.add(x0, base - 1, zb - 0.15 if h1 > h0 else zb, x1, base + max(0.3, hi - 1.0), zb if h1 > h0 else zb + 0.15)
                else:
                    xb = x1 if h1 > h0 else x0
                    self.collision.add(xb - 0.15 if h1 > h0 else xb, base - 1, z0, xb if h1 > h0 else xb + 0.15, base + max(0.3, hi - 1.0), z1)

        # big gap jump along z through the middle: run-up, 9 m gap, landing
        ramp(cx - 3.5, iz0 + 2.0, cx + 3.5, iz0 + 11.0, 0.0, 2.3, True)
        ramp(cx - 4.0, iz0 + 20.0, cx + 4.0, iz0 + 31.0, 2.3, 0.0, True)
        B['neon'].box((cx, base + 2.36, iz0 + 10.9), (7.0, 0.08, 0.2), rgb(255, 120, 20))
        # side kickers
        ramp(ix0 + 2.0, cz - 2.5, ix0 + 7.5, cz + 2.5, 0.0, 1.3, False)
        ramp(ix1 - 7.5, cz - 2.5, ix1 - 2.0, cz + 2.5, 1.3, 0.0, False)
        # mini kickers for scooters
        for k in range(3):
            zz = iz1 - 4.0 - k * 4.5
            ramp(ix0 + 3.0, zz - 1.0, ix0 + 5.0, zz + 1.0, 0.0, 0.45, False, back=False)
        # quarter-pipe style wall at the far end
        ramp(cx - 6.0, iz1 - 6.0, cx + 6.0, iz1 - 1.0, 0.0, 2.6, True)
        # floodlights + a sign
        for (lx, lz) in ((ix0 + 1, iz0 + 1), (ix1 - 1, iz1 - 1)):
            B['misc'].cylinder((lx, base + 5.0, lz), 0.12, 10.0, POLE, seg=6)
            B['lamps'].box((lx, base + 10.1, lz), (1.2, 0.4, 0.6), Color(1, 0.97, 0.9, 1))
            self.lamps.append((lx, base + 9.8, lz))
        self.featured_spawns.append(('motorbike', ix0 + 4.0, iz0 + 3.5, 0.0))
        self.featured_spawns.append(('sports', ix0 + 8.0, iz0 + 4.0, 0.0))
        world_text('STUNT PARK', (cx, base + 4.6, iz0 - 0.2), 0, 0.9, rgb(255, 140, 30))
        B['misc'].box((cx, base + 4.6, iz0 - 0.1), (8.0, 1.4, 0.12), rgb(20, 20, 22))
        for s in (-1, 1):
            B['misc'].cylinder((cx + s * 3.8, base + 2.0, iz0 - 0.1), 0.08, 4.0, POLE, seg=5)
        self.pois.append((cx, cz, 'stunt'))

    def _football_field(self, B, inner):
        ix0, iz0, ix1, iz1 = inner
        base = CURB_H
        B['side'].rect_xz(ix0, iz0, ix1, iz1, base + 0.012, rgb(60, 130, 56))
        fx0, fz0, fx1, fz1 = ix0 + 3, iz0 + 2, ix1 - 8, iz1 - 2
        for k in range(8):                                                  # mowing stripes
            a, b = fz0 + (fz1 - fz0) * k / 8, fz0 + (fz1 - fz0) * (k + 1) / 8
            B['side'].rect_xz(fx0, a, fx1, b, base + 0.016, rgb(70, 146, 62) if k % 2 else rgb(62, 134, 56))
        line = rgb(240, 240, 236)
        y = base + 0.024
        for (a0, b0, a1, b1) in ((fx0, fz0, fx1, fz0 + 0.12), (fx0, fz1 - 0.12, fx1, fz1), (fx0, fz0, fx0 + 0.12, fz1),
                                 (fx1 - 0.12, fz0, fx1, fz1), ((fx0 + fx1) / 2 - 0.06, fz0, (fx0 + fx1) / 2 + 0.06, fz1)):
            B['side'].rect_xz(a0, b0, a1, b1, y, line)
        B['side'].ring_xz(((fx0 + fx1) / 2, y, (fz0 + fz1) / 2), 4.0, 4.14, y, line, 32)
        cz = (fz0 + fz1) / 2
        for gx, s in ((fx0, 1), (fx1, -1)):
            B['side'].rect_xz(min(gx, gx + s * 5), cz - 6, max(gx, gx + s * 5), cz - 5.88, y, line)
            B['side'].rect_xz(min(gx, gx + s * 5), cz + 5.88, max(gx, gx + s * 5), cz + 6, y, line)
            B['side'].rect_xz(gx + s * 5 - 0.06, cz - 6, gx + s * 5 + 0.06, cz + 6, y, line)
            for dz in (-2.5, 2.5):                                         # goal posts
                B['misc'].cylinder((gx, base + 1.2, cz + dz), 0.07, 2.4, line, seg=6)
                self.collision.add(gx - 0.1, base, cz + dz - 0.1, gx + 0.1, base + 2.4, cz + dz + 0.1)
            B['misc'].box((gx, base + 2.4, cz), (0.14, 0.14, 5.1), line)
            B['misc'].box((gx - s * 0.9, base + 1.2, cz), (0.02, 2.4, 5.0), rgb(220, 220, 220, 255))
        # stand (tribune) along the east side
        sx0 = ix1 - 6.5
        for r in range(4):
            B['bld'].box((sx0 + 0.75 + r * 1.4, base + 0.35 + r * 0.7, (iz0 + iz1) / 2), (1.4, 0.7 + r * 1.4, iz1 - iz0 - 6),
                         rgb(150, 150, 154) if r % 2 else rgb(130, 130, 136))
            B['misc'].box((sx0 + 0.9 + r * 1.4, base + 0.95 + r * 1.4, (iz0 + iz1) / 2), (0.5, 0.25, iz1 - iz0 - 7),
                          random.choice((rgb(200, 40, 40), rgb(40, 80, 180))))
        self.collision.add(sx0, base, iz0 + 3, ix1, base + 5.6, iz1 - 3)
        B['misc'].box((ix1 - 0.6, base + 6.5, (iz0 + iz1) / 2), (0.3, 2.0, iz1 - iz0 - 6), rgb(40, 42, 46))   # roof back
        B['misc'].box((sx0 + 2.8, base + 7.4, (iz0 + iz1) / 2), (6.2, 0.2, iz1 - iz0 - 5), rgb(220, 220, 224))
        for (lx, lz) in ((fx0 - 1.5, fz0 - 1), (fx0 - 1.5, fz1 + 1), (fx1 + 1.5, fz0 - 1), (fx1 + 1.5, fz1 + 1)):
            B['misc'].cylinder((lx, base + 8.0, lz), 0.18, 16.0, POLE, seg=6)
            B['lamps'].box((lx, base + 16.2, lz), (1.8, 1.0, 0.4), Color(1, 0.98, 0.92, 1))
            self.collision.add(lx - 0.2, base, lz - 0.2, lx + 0.2, base + 16, lz + 0.2)
            self.lamps.append((lx, base + 15.6, lz))
        self.prop_spots.append(('box', (fx0 + fx1) / 2, cz))
        self.pois.append(((fx0 + fx1) / 2, cz, 'field'))

    def _park2(self, B, inner):
        """Quiet park with a pond, a little bridge, trees and benches."""
        ix0, iz0, ix1, iz1 = inner
        base = CURB_H
        B['side'].rect_xz(ix0, iz0, ix1, iz1, base + 0.012, jitter(GRASS, 0.04))
        cx, cz = (ix0 + ix1) / 2, (iz0 + iz1) / 2
        B['side'].ring_xz((cx, base + 0.02, cz), 0.0, 9.0, base + 0.02, rgb(150, 130, 100), 36)
        B['neon'].ring_xz((cx, base + 0.03, cz), 0.0, 8.2, base + 0.03, rgb(46, 104, 140), 36)   # glints at night
        self.collision.add(cx - 7.5, -1, cz - 7.5, cx + 7.5, base + 0.6, cz + 7.5)
        # wooden bridge across the pond
        B['misc'].box((cx, base + 0.75, cz), (19.0, 0.15, 2.0), rgb(130, 90, 55))
        for s in (-1, 1):
            B['misc'].box((cx, base + 1.35, cz + s * 0.95), (19.0, 0.08, 0.08), rgb(110, 76, 46))
        path = rgb(196, 176, 140)
        B['side'].rect_xz(ix0 - 0.5, cz - 1.2, cx - 9.0, cz + 1.2, base + 0.018, path)
        B['side'].rect_xz(cx + 9.0, cz - 1.2, ix1 + 0.5, cz + 1.2, base + 0.018, path)
        for _ in range(14):
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(11.0, 15.0)
            tx, tz = cx + math.cos(a) * r, cz + math.sin(a) * r
            if ix0 + 1.5 < tx < ix1 - 1.5 and iz0 + 1.5 < tz < iz1 - 1.5 and abs(tz - cz) > 2.5:
                self._tree(B, tx, tz, random.uniform(0.9, 1.4))
        for (bx, bz, rot) in ((cx - 11.0, cz + 3.5, 0), (cx + 11.0, cz - 3.5, 0), (cx, cz + 11.0, 0), (cx, cz - 11.0, 0)):
            self._bench(B, bx, bz, rot)

    def _bench(self, B, x, z, rot):
        base = CURB_H
        fr = Frame(x, z, rot)
        self._fbox('misc', fr, (0, 0.45, 0), (1.8, 0.08, 0.5), rgb(130, 90, 55))
        self._fbox('misc', fr, (0, 0.8, 0.22), (1.8, 0.4, 0.06), rgb(130, 90, 55))
        for px in (-0.8, 0.8):
            self._fbox('misc', fr, (px, 0.22, 0), (0.07, 0.45, 0.45), POLE)
        self.collision.add(x - 0.9, base, z - 0.5, x + 0.9, base + 0.9, z + 0.5)

    def _tree(self, B, x, z, s=1.0):
        base = self.ground_height(x, z)
        B['misc'].cylinder((x, base + 1.4 * s, z), 0.17 * s, 2.8 * s, rgb(92, 66, 46), seg=7)
        greens = (rgb(56, 110, 46), rgb(70, 128, 52), rgb(46, 96, 44), rgb(84, 136, 60))
        for (ox, oy, oz, r) in ((0, 3.4, 0, 1.6), (0.7, 4.2, 0.3, 1.2), (-0.6, 4.0, -0.4, 1.25), (0.1, 4.9, 0.0, 0.95)):
            B['misc'].sphere((x + ox * s, base + oy * s, z + oz * s), r * s, jitter(random.choice(greens), 0.06), 4, 7)
        self.collision.add(x - 0.25, base, z - 0.25, x + 0.25, base + 3.0 * s, z + 0.25)

    def _parking(self, B, inner):
        ix0, iz0, ix1, iz1 = inner
        B['side'].rect_xz(ix0, iz0, ix1, iz1, CURB_H + 0.012, rgb(62, 64, 68))
        rows = (iz0 + 5.0, iz1 - 5.0)
        for rz in rows:
            x = ix0 + 2.0
            while x + 3.0 < ix1 - 1.0:
                B['side'].rect_xz(x - 0.06, rz - 2.6, x + 0.06, rz + 2.6, CURB_H + 0.02, MARK)
                if random.random() < 0.7:
                    self.parking_spots.append((x + 1.5, rz, 0.0 if rz < (iz0 + iz1) / 2 else 180.0))
                x += 3.0
            B['side'].rect_xz(x - 0.06, rz - 2.6, x + 0.06, rz + 2.6, CURB_H + 0.02, MARK)
        cx = (ix0 + ix1) / 2
        B['misc'].box((cx, CURB_H + 1.3, (iz0 + iz1) / 2), (2.2, 2.6, 2.2), rgb(210, 205, 190), top_col=ROOF_COL)
        self.collision.add(cx - 1.1, 0, (iz0 + iz1) / 2 - 1.1, cx + 1.1, 3.0, (iz0 + iz1) / 2 + 1.1)
        for k in range(4):
            self.prop_spots.append(('cone', cx - 4 + k * 2.6, (iz0 + iz1) / 2 + 3.2))

    # ---- enterable shop
    def _shop(self, B, fr, name, kind):
        w, d, h, H = 18.0, 14.0, 5.2, 11.5
        t = 0.35
        outside = jitter(random.choice(FACADES[:5]), 0.04)
        wall = rgb(236, 232, 224)
        floor_col = {'convenience': rgb(205, 200, 190), 'electronics': rgb(66, 70, 78), 'jewelry': rgb(120, 24, 34),
                     'gas': rgb(190, 190, 196)}[kind]
        brand = {'convenience': rgb(40, 150, 60), 'electronics': rgb(30, 90, 220), 'jewelry': rgb(200, 160, 40),
                 'gas': rgb(225, 40, 30)}[kind]
        self._fbox('side', fr, (0, 0.012, 0), (w - 2 * t, 0.02, d - 2 * t), floor_col)
        self._fbox('bld', fr, (0, h / 2, d / 2 - t / 2), (w, h, t), wall, collide=True)
        self._fbox('bld', fr, (-w / 2 + t / 2, h / 2, 0), (t, h, d), wall, collide=True)
        self._fbox('bld', fr, (w / 2 - t / 2, h / 2, 0), (t, h, d), wall, collide=True)
        door = 3.4
        seg = (w - door) / 2
        for sgn in (-1, 1):
            cxl = sgn * (door / 2 + seg / 2)
            self._fbox('bld', fr, (cxl, 0.45, -d / 2 + t / 2), (seg, 0.9, t), outside, collide=True)
            self._fbox('bld', fr, (cxl, (3.3 + h) / 2, -d / 2 + t / 2), (seg, h - 3.3, t), outside, collide=True)
            self._fbox('neon', fr, (cxl, 2.1, -d / 2 + t / 2), (seg - 0.5, 2.4, t * 0.5), rgb(150, 190, 215), collide=True)
            for e in (-seg / 2 + 0.12, seg / 2 - 0.12):
                self._fbox('bld', fr, (cxl + e, 2.1, -d / 2 + t / 2), (0.24, 2.4, t + 0.04), rgb(40, 40, 44))
        self._fbox('bld', fr, (0, (3.1 + h) / 2, -d / 2 + t / 2), (door, h - 3.1, t), outside, collide=True)
        self._fbox('bld', fr, (0, (h + H) / 2, 0), (w, H - h, d), outside, top=ROOF_COL, collide=True, bottom=True)
        self._fbox('bld', fr, (0, H + 0.2, 0), (w + 0.4, 0.4, d + 0.4), col_mul(outside, 0.8), top=ROOF_COL)
        # upper floor windows (front)
        along = fr.dir(1, 0)
        along3 = (along[0], 0.0, along[1])
        nrm2 = fr.dir(0, -1)
        nrm = (nrm2[0], 0.0, nrm2[1])
        for row in range(2):
            for k in range(5):
                c = fr.p(-6.4 + k * 3.2, h + 1.6 + row * 2.9, -d / 2)
                if random.random() < 0.5:
                    self.B['winlit'].face_quad(c, along3, (0, 1, 0), nrm, 1.3, 1.8, Color(1, 0.9, 0.74, 1))
                else:
                    self.B['glass'].face_quad(c, along3, (0, 1, 0), nrm, 1.3, 1.8, GLASS_DARK)
        # awning, sign and lettering
        self._fbox('misc', fr, (0, 3.5, -d / 2 - 0.9), (6.0, 0.14, 1.8), brand)
        self._fbox('neon', fr, (0, 4.4, -d / 2 - 0.12), (10.0, 1.1, 0.2), brand)
        world_text(name, fr.p(0, 4.4, -d / 2 - 0.25), fr.a, 0.75, color.white)
        # interior: counter + register
        self._fbox('misc', fr, (4.2, 0.55, 0.5), (1.0, 1.1, 5.0), rgb(120, 84, 52), collide=True)
        self._fbox('misc', fr, (4.2, 1.12, 0.5), (1.1, 0.05, 5.1), rgb(60, 60, 64))
        self._fbox('misc', fr, (4.2, 1.27, -0.5), (0.55, 0.25, 0.45), rgb(30, 30, 34))
        self._fbox('neon', fr, (4.0, 1.45, -0.5), (0.05, 0.22, 0.35), rgb(60, 220, 120))
        # shelves
        if kind == 'gas':
            # fuel canopy over the sidewalk with two pumps
            for px in (-7.5, 7.5):
                for pz in (-d / 2 - 0.3, -d / 2 - 3.1):
                    self._fbox('misc', fr, (px, 2.4, pz), (0.25, 4.8, 0.25), rgb(220, 220, 224))
            self._fbox('misc', fr, (0, 4.95, -d / 2 - 1.7), (16.0, 0.3, 3.4), rgb(240, 240, 244), bottom=True)
            self._fbox('neon', fr, (0, 4.75, -d / 2 - 3.42), (16.0, 0.28, 0.04), brand)
            for px in (-5.0, 5.0):
                self._fbox('misc', fr, (px, 0.8, -d / 2 - 2.2), (0.7, 1.6, 0.45), brand, collide=True)
                self._fbox('neon', fr, (px, 1.25, -d / 2 - 2.44), (0.45, 0.3, 0.02), rgb(120, 255, 160))
            for sx in (-6.3, -3.3):
                self._shelf(fr, sx, 0.6, 6.0, ['food'])
            for k in range(4):
                self._fbox('neon', fr, (-6.5 + k * 1.7, 1.2, d / 2 - t - 0.45), (1.5, 2.2, 0.7), rgb(170, 220, 240))
        elif kind == 'convenience':
            for sx in (-6.3, -3.3, -0.3):
                self._shelf(fr, sx, 0.6, 6.0, ['food'])
            for k in range(6):
                self._fbox('neon', fr, (-6.5 + k * 1.7, 1.2, d / 2 - t - 0.45), (1.5, 2.2, 0.7), rgb(170, 220, 240))
        elif kind == 'electronics':
            for sx in (-6.0, -2.5):
                self._shelf(fr, sx, 0.6, 6.0, ['tech'])
            for k in range(6):
                self._fbox('misc', fr, (-6.8 + k * 2.2, 2.3, d / 2 - t - 0.1), (2.0, 1.2, 0.1), rgb(15, 15, 18))
                self._fbox('neon', fr, (-6.8 + k * 2.2, 2.3, d / 2 - t - 0.17), (1.8, 1.0, 0.03),
                           random.choice((rgb(40, 120, 255), rgb(255, 60, 140), rgb(60, 220, 160), rgb(255, 170, 40))))
        else:
            for (px, pz) in ((-5.5, -2.0), (-5.5, 2.0), (-1.8, -2.0), (-1.8, 2.0)):
                self._fbox('misc', fr, (px, 0.5, pz), (2.4, 1.0, 1.2), rgb(30, 26, 24), collide=True)
                self._fbox('neon', fr, (px, 1.12, pz), (2.3, 0.22, 1.1), rgb(200, 230, 255))
                for k in range(4):
                    self._fbox('neon', fr, (px - 0.8 + k * 0.55, 1.05, pz), (0.2, 0.1, 0.2), rgb(250, 200, 60))
        # ceiling light panels
        for (lx, lz) in ((-4.5, -2.5), (-4.5, 2.5), (1.5, -2.5), (1.5, 2.5)):
            self._fbox('neon', fr, (lx, h - 0.06, lz), (2.4, 0.06, 0.6), rgb(255, 250, 235))
        self.interior_lights.append((fr.p(-1.5, h - 0.8, 0), (1.0, 0.96, 0.88), 11.0))
        self.prop_spots.append(('box', *self._xz(fr.p(-w / 2 - 1.0, 0, -d / 2 + 1.5))))
        self.prop_spots.append(('crate', *self._xz(fr.p(w / 2 + 1.2, 0, -d / 2 + 2.0))))
        cmin = fr.p(-w / 2, 0, -d / 2)
        cmax = fr.p(w / 2, 0, d / 2)
        self.shops.append(dict(
            name=name, kind=kind,
            register=fr.p(4.2, 1.3, -0.5), interact=fr.p(3.1, 0, -0.5),
            clerk=fr.p(5.8, 0, -0.3), clerk_yaw=fr.yaw_of(-1, 0),
            door=fr.p(0, 0, -d / 2 - 1.2),
            bounds=(min(cmin[0], cmax[0]), min(cmin[2], cmax[2]), max(cmin[0], cmax[0]), max(cmin[2], cmax[2])),
        ))
        self.pois.append((fr.ox, fr.oz, 'shop'))

    @staticmethod
    def _xz(p):
        return (p[0], p[2])

    def _shelf(self, fr, sx, z0, length, kinds):
        self._fbox('misc', fr, (sx, 0.95, z0), (0.8, 1.9, length), rgb(210, 210, 214), collide=True)
        cols = [rgb(220, 40, 40), rgb(240, 200, 40), rgb(40, 120, 220), rgb(50, 170, 80), rgb(240, 120, 30),
                rgb(160, 60, 200), rgb(240, 240, 240)] if 'food' in kinds else [rgb(30, 30, 34), rgb(200, 200, 205), rgb(30, 80, 200), rgb(60, 60, 64)]
        for level in (0.45, 1.0, 1.55):
            zz = z0 - length / 2 + 0.3
            while zz < z0 + length / 2 - 0.3:
                hh = random.uniform(0.2, 0.42)
                for side in (-1, 1):
                    self._fbox('misc', fr, (sx + side * 0.42, level + hh / 2, zz), (0.06 + random.uniform(0.0, 0.1), hh, 0.3), random.choice(cols))
                zz += 0.42

    # ---- E-tuning garage
    def _garage(self, B, fr):
        w, d, h = 20.0, 16.0, 7.0
        t = 0.4
        outside = rgb(70, 74, 82)
        self._fbox('side', fr, (0, 0.012, 0), (w - 2 * t, 0.02, d - 2 * t), rgb(52, 56, 62))
        self._fbox('bld', fr, (0, h / 2, d / 2 - t / 2), (w, h, t), outside, collide=True)
        self._fbox('bld', fr, (-w / 2 + t / 2, h / 2, 0), (t, h, d), outside, collide=True)
        self._fbox('bld', fr, (w / 2 - t / 2, h / 2, 0), (t, h, d), outside, collide=True)
        self._fbox('bld', fr, (0, (4.8 + h) / 2, -d / 2 + t / 2), (w, h - 4.8, t), outside, collide=True)
        for sgn in (-1, 1):
            self._fbox('bld', fr, (sgn * (w / 2 - 1.5), 2.4, -d / 2 + t / 2), (3.0, 4.8, t), outside, collide=True)
        self._fbox('bld', fr, (0, h + 0.2, 0), (w + 0.3, 0.4, d + 0.3), rgb(50, 52, 58), top=ROOF_COL, collide=True, bottom=True)
        # tuning pad
        self._fbox('neon', fr, (0, 0.03, 0.5), (6.0, 0.02, 9.0), rgb(0, 200, 230))
        self._fbox('side', fr, (0, 0.035, 0.5), (5.4, 0.02, 8.4), rgb(20, 40, 50))
        # neon strips, workbenches, tyre stacks, lift
        for lz in (-4.0, 0.0, 4.0):
            self._fbox('neon', fr, (0, h - 0.08, lz), (14.0, 0.08, 0.25), rgb(120, 230, 255))
        self._fbox('misc', fr, (-w / 2 + 1.2, 0.5, 2.0), (1.2, 1.0, 6.0), rgb(180, 40, 30), collide=True)
        self._fbox('misc', fr, (-w / 2 + 1.2, 1.05, 2.0), (1.3, 0.08, 6.1), rgb(90, 90, 96))
        self._fbox('misc', fr, (-w / 2 + 0.5, 2.3, 2.0), (0.1, 1.6, 6.0), rgb(40, 40, 44))
        for k in range(3):
            for s in range(4):
                c = fr.p(w / 2 - 1.5, 0.15 + s * 0.3, 4.5 - k * 1.3)
                self.B['misc'].cylinder(c, 0.55, 0.28, rgb(25, 25, 28), seg=12)
        self.collision.add(*self._garage_box(fr, w / 2 - 2.1, 1.0, w / 2 - 0.9, 5.2))
        self._fbox('neon', fr, (0, 5.9, -d / 2 - 0.14), (9.0, 1.2, 0.2), rgb(0, 190, 255))
        world_text('E-TUNING GARAGE', fr.p(0, 5.9, -d / 2 - 0.27), fr.a, 0.7, rgb(5, 20, 40))
        world_text('MOTOR - BATTERY - SUSPENSION - PAINT', fr.p(0, 5.1, -d / 2 - 0.27), fr.a, 0.35, rgb(160, 230, 255))
        self.interior_lights.append((fr.p(0, h - 1.0, 0.5), (0.7, 0.95, 1.0), 13.0))
        zmin = fr.p(-3.0, 0, -4.0)
        zmax = fr.p(3.0, 0, 5.0)
        self.garage = dict(zone=(min(zmin[0], zmax[0]), min(zmin[2], zmax[2]), max(zmin[0], zmax[0]), max(zmin[2], zmax[2])),
                           center=fr.p(0, 0, 0.5), entrance=fr.p(0, 0, -d / 2 - 2.0), yaw=fr.yaw_of(0, -1))
        for k in range(3):
            self.prop_spots.append(('cone', *self._xz(fr.p(-6 + k * 1.2, 0, -d / 2 - 1.2))))
        self.pois.append((fr.ox, fr.oz, 'garage'))

    def _garage_box(self, fr, lx0, lz0, lx1, lz1):
        a = fr.p(lx0, 0, lz0)
        b = fr.p(lx1, 0, lz1)
        return (min(a[0], b[0]), 0.0, min(a[2], b[2]), max(a[0], b[0]), 1.4, max(a[2], b[2]))

    # ---- buyable business property
    def _business(self, B, fr, name, price, income):
        w, d, h, H = 16.0, 12.0, 4.6, 10.0
        outside = jitter(random.choice(BRICKS), 0.04)
        brand = random.choice((rgb(220, 120, 20), rgb(30, 160, 150), rgb(160, 40, 140), rgb(200, 40, 40)))
        self._fbox('bld', fr, (0, H / 2, 0), (w, H, d), outside, top=ROOF_COL, collide=True)
        self._fbox('bld', fr, (0, H + 0.2, 0), (w + 0.4, 0.4, d + 0.4), col_mul(outside, 0.8), top=ROOF_COL)
        self._fbox('neon', fr, (-3.0, 1.9, -d / 2 - 0.03), (8.0, 2.4, 0.06), rgb(255, 225, 170))
        self._fbox('bld', fr, (4.5, 1.2, -d / 2 - 0.04), (1.4, 2.4, 0.08), rgb(40, 30, 26))
        self._fbox('bld', fr, (0, 3.6, -d / 2 - 0.9), (14.0, 0.14, 1.8), brand)
        self._fbox('neon', fr, (0, 4.15, -d / 2 - 0.12), (11.0, 0.9, 0.2), brand)
        world_text(name, fr.p(0, 4.15, -d / 2 - 0.25), fr.a, 0.55, color.white)
        along = fr.dir(1, 0)
        nrm2 = fr.dir(0, -1)
        for row in range(2):
            for k in range(4):
                c = fr.p(-5.4 + k * 3.6, h + 1.3 + row * 2.7, -d / 2)
                self.B['glass' if random.random() < 0.5 else 'winlit'].face_quad(
                    c, (along[0], 0.0, along[1]), (0, 1, 0), (nrm2[0], 0.0, nrm2[1]), 1.3, 1.8, Color(1, 0.9, 0.74, 1))
        # "FOR SALE" board on the sidewalk
        bp = (5.8, 0, -d / 2 - 2.3)
        self._fbox('misc', fr, (bp[0], 1.0, bp[2]), (0.1, 2.0, 0.1), POLE)
        self._fbox('misc', fr, (bp[0], 2.2, bp[2]), (1.9, 1.1, 0.08), rgb(245, 245, 240))
        sale = world_text('FOR SALE', fr.p(bp[0], 2.35, bp[2] - 0.07), fr.a, 0.38, rgb(200, 20, 20))
        price_txt = world_text('$%s' % format(price, ','), fr.p(bp[0], 1.95, bp[2] - 0.07), fr.a, 0.3, rgb(20, 20, 20))
        self.collision.add(*self._garage_box(fr, bp[0] - 0.1, bp[2] - 0.1, bp[0] + 0.1, bp[2] + 0.1))
        self.businesses.append(dict(name=name, price=price, income=income, pos=fr.p(2.0, 0, -d / 2 - 1.6),
                                    sale_text=sale, price_text=price_txt))
        self.pois.append((fr.ox, fr.oz, 'business'))

    # ---- streetlights and trees along every road
    def _build_streetlights(self, B):
        for rc in ROADS:
            for k in range(N_BLOCKS):
                start = ROADS[k] + HALF_ROAD
                for m, off in enumerate((7.0, 20.0, 33.0)):
                    side = 1 if m % 2 == 0 else -1
                    along = start + off
                    self._lamp(B, rc + side * (HALF_ROAD + 0.55), along, -side, 'x')
                    self._lamp(B, along, rc + side * (HALF_ROAD + 0.55), -side, 'z')
                for off in (13.5, 26.5):
                    along = start + off
                    for side in (-1, 1):
                        if random.random() < 0.45:
                            x, z = rc + side * (HALF_ROAD + 1.0), along
                            if self.ground_height(x, z) > 0.1 and not self.collision.inside(x, 1.0, z, 0.6):
                                self._tree(B, x, z, random.uniform(0.75, 1.0))
                        if random.random() < 0.45:
                            x, z = along, rc + side * (HALF_ROAD + 1.0)
                            if self.ground_height(x, z) > 0.1 and not self.collision.inside(x, 1.0, z, 0.6):
                                self._tree(B, x, z, random.uniform(0.75, 1.0))

    def _lamp(self, B, x, z, dirsign, axis):
        base = self.ground_height(x, z)
        B['misc'].cylinder((x, base + 0.2, z), 0.2, 0.4, POLE, seg=8)
        B['misc'].cylinder((x, base + 3.0, z), 0.08, 6.0, POLE, seg=8)
        if axis == 'x':
            hx, hz = x + dirsign * 1.7, z
            B['misc'].box((x + dirsign * 0.85, base + 5.95, z), (1.75, 0.1, 0.1), POLE)
            B['misc'].box((hx, base + 5.9, hz), (0.75, 0.16, 0.36), rgb(36, 38, 42))
            B['lamps'].box((hx, base + 5.8, hz), (0.6, 0.05, 0.26), Color(1, 1, 1, 1))
        else:
            hx, hz = x, z + dirsign * 1.7
            B['misc'].box((x, base + 5.95, z + dirsign * 0.85), (0.1, 0.1, 1.75), POLE)
            B['misc'].box((hx, base + 5.9, hz), (0.36, 0.16, 0.75), rgb(36, 38, 42))
            B['lamps'].box((hx, base + 5.8, hz), (0.26, 0.05, 0.6), Color(1, 1, 1, 1))
        B['lamps'].sphere((hx, base + 5.72, hz), 0.16, Color(1, 1, 1, 1), 3, 6)
        self.lamps.append((hx, base + 5.4, hz))
        self.collision.add(x - 0.18, base, z - 0.18, x + 0.18, base + 6.0, z + 0.18)
        if base > 0.1 and random.random() < 0.28:
            ox, oz = (0.0, 1.1) if axis == 'x' else (1.1, 0.0)
            self.prop_spots.append(('bin', x + ox, z + oz))

    def _build_boundary(self, B):
        dike = rgb(90, 140, 66)
        L = BOUNDARY + 14
        for (cx, cz, sx, sz) in ((0, -BOUNDARY - 7, 2 * L, 14), (0, BOUNDARY + 7, 2 * L, 14),
                                 (-BOUNDARY - 7, 0, 14, 2 * L), (BOUNDARY + 7, 0, 14, 2 * L)):
            hx, hz = sx / 2, sz / 2
            ix, iz = (hx, hz - 4.5) if sx > sz else (hx - 4.5, hz)
            pts = [(cx - hx, -0.02, cz - hz), (cx + hx, -0.02, cz - hz), (cx + hx, -0.02, cz + hz), (cx - hx, -0.02, cz + hz),
                   (cx - ix, 4.5, cz - iz), (cx + ix, 4.5, cz - iz), (cx + ix, 4.5, cz + iz), (cx - ix, 4.5, cz + iz)]
            B['ground'].hexa(pts, dike, top_col=rgb(100, 150, 72))
            self.collision.add(cx - hx, -5, cz - hz, cx + hx, 4.6, cz + hz)
        for k in range(48):
            a = k / 48.0 * 2 * math.pi
            r = BOUNDARY - 8 + random.uniform(-4, 3)
            x, z = math.cos(a) * r * 1.05, math.sin(a) * r * 1.05
            x = clampf(x, -BOUNDARY + 4, BOUNDARY - 4)
            z = clampf(z, -BOUNDARY + 4, BOUNDARY - 4)
            if abs(x) > ASPHALT_MAX + 3 or abs(z) > ASPHALT_MAX + 3:
                self._tree(B, x, z, random.uniform(1.0, 1.5))

    # ------------------------------------------------------------ sky + lighting
    def _build_sky(self):
        mb = MeshBuilder()
        mb.sphere((0, 0, 0), 1.0, Color(1, 1, 1, 1), 10, 18)
        self.sky = Entity(model=mb.build(), scale=850)
        self.sky.setShader(get_shader('sky'), 2)
        self.sky.setBin('background', 0)
        self.sky.setDepthWrite(False)
        self.sky.setDepthTest(False)
        self.sky.setTwoSided(True)
        self.sky.setLightOff()

    def is_day(self):
        return 6.2 < self.hour < 18.6

    def toggle_day_night(self):
        self.hour = 22.5 if self.is_day() else 11.0

    def _sample_keys(self, hour):
        for k in range(len(SKY_KEYS) - 1):
            a, b = SKY_KEYS[k], SKY_KEYS[k + 1]
            if a[0] <= hour <= b[0]:
                t = (hour - a[0]) / (b[0] - a[0])
                t = t * t * (3 - 2 * t)
                return [tup_lerp(a[i], b[i], t) for i in range(1, 6)]
        return [SKY_KEYS[0][i] for i in range(1, 6)]

    def _apply_lighting(self, cam_pos):
        zen, hor, sun_col, amb, grd = self._sample_keys(self.hour)
        a = (self.hour - 6.0) / 12.0 * math.pi
        sun = _normalize((math.cos(a) * 0.82, math.sin(a), 0.38))
        sy = sun[1]
        if sy > -0.12:
            d = _normalize((sun[0], max(sun[1], 0.12), sun[2]))
            k = smoothstep(-0.12, 0.05, sy)
            lc = (sun_col[0] * k, sun_col[1] * k, sun_col[2] * k)
        else:
            d = _normalize((-sun[0], max(-sun[1], 0.15), -sun[2]))
            k = smoothstep(-0.12, -0.35, sy)
            lc = (MOON_COL[0] * k, MOON_COL[1] * k, MOON_COL[2] * k)
        self.night = smoothstep(0.10, -0.08, sy)
        g = self.gpu
        scene.setShaderInput('sun_dir', g.vec(d))
        scene.setShaderInput('sun_color', LVecBase3f(*lc))
        scene.setShaderInput('ambient_color', LVecBase3f(*amb))
        scene.setShaderInput('ground_color', LVecBase3f(*grd))
        fog = (hor[0] * 0.9, hor[1] * 0.9, hor[2] * 0.9)
        scene.setShaderInput('fog_color', LVecBase3f(*fog))
        scene.setShaderInput('fog_density', (0.0042 + 0.0016 * self.night) * self.fog_scale)
        self.sky.setShaderInput('sky_zenith', LVecBase3f(*zen))
        self.sky.setShaderInput('sky_horizon', LVecBase3f(*hor))
        self.sky.setShaderInput('true_sun_dir', g.vec(sun))
        self.sky.setShaderInput('sun_disc_color', LVecBase3f(1.0, 0.75 + 0.2 * max(0.0, sy), 0.45 + 0.4 * max(0.0, sy)))
        self.sky.setShaderInput('night', self.night)
        window.color = Color(hor[0], hor[1], hor[2], 1)
        wn = smoothstep(0.18, -0.05, sy)
        for e in self.win_ents:
            e.setShaderInput('emissive', 0.1 + 0.9 * wn)
            e.color = col_lerp(Color(0.42, 0.52, 0.62, 1), Color(1.0, 0.86, 0.62, 1), wn)
        for e in self.lamp_ents:
            e.setShaderInput('emissive', self.night)
            e.color = col_lerp(Color(0.75, 0.75, 0.72, 1), Color(1.0, 0.86, 0.55, 1), self.night)
        for e in self.neon_ents:
            e.setShaderInput('emissive', 0.55 + 0.45 * self.night)

    def update(self, dt, cam_pos):
        self.hour = (self.hour + dt * self.time_scale * 24.0 / DAY_LENGTH) % 24.0
        self._apply_lighting(cam_pos)
        self.sky.position = cam_pos
        cands = []
        if self.night > 0.02:
            lc = (1.6 * self.night, 1.15 * self.night, 0.62 * self.night)
            for p in self.lamps:
                cands.append((p, lc, 16.0))
        for (p, c, r) in self.interior_lights:
            cands.append((p, c, r))
        self.lights.update(dt, cam_pos, cands)
        self.particles.update(dt)
        self.decals.update(dt)
        self.tire_marks.update(dt)
        self.props.update(dt)

    def clock_text(self):
        h = int(self.hour)
        m = int((self.hour - h) * 60)
        return '%02d:%02d' % (h, m)

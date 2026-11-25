"""
vehicles.py  -  cars, E-scooters and E-motorbikes
====================================================

* procedural low-poly car bodies (sedan, hatchback, sports, van, taxi, police)
  with transparent glass, visible drivers, emissive head/tail/brake lights
* arcade drift physics: handbrake (Space) drops rear lateral grip, adds yaw,
  throttle keeps the slide alive (power-over), counter-steer to hold it;
  burnouts and donuts when you hold Space + W at low speed
* tyre marks + smoke + screech, drift score that pays out cash
* suspension spring per vehicle (curbs and speed bumps make it bounce)
* E-scooters and E-motorbikes with real leaning physics and an electric
  drivetrain: motor wattage, battery (Wh), boost (Shift), range estimate,
  suspension setup and two paint colours - all tunable in the garage
"""
from ursina import *
import math
import random
from world import (Color, MeshBuilder, make_lit, rgb, col_mul, clampf, lerpf, wrap_angle, heading_vectors,
                   CURB_H, ROADS, HALF_ROAD, N_BLOCKS)

# ------------------------------------------------------------------ tuning tables
MOTOR_TIERS = [
    dict(watt=500, price=0, top_kmh=28, accel=3.4),
    dict(watt=1500, price=450, top_kmh=46, accel=5.4),
    dict(watt=3000, price=1300, top_kmh=68, accel=7.8),
    dict(watt=8000, price=3800, top_kmh=108, accel=12.0),
]
# KuKirin G2 standing e-scooter: starts stock at 1500W / 55 km/h
KICK_MOTOR_TIERS = [
    dict(watt=1500, price=0, top_kmh=55, accel=5.8),
    dict(watt=2400, price=900, top_kmh=68, accel=7.4),
    dict(watt=4000, price=2200, top_kmh=82, accel=9.4),
    dict(watt=8000, price=4800, top_kmh=105, accel=12.5),
]
BATTERY_TIERS = [
    dict(name='36V 10Ah', wh=360, price=0),
    dict(name='48V 20Ah', wh=960, price=350),
    dict(name='60V 30Ah', wh=1800, price=950),
    dict(name='72V 50Ah', wh=3600, price=2600),
]
SUSPENSION_TIERS = [
    dict(name='Standard', ride=0.0, k=150.0, c=15.0, absorb=0.45, grip=1.00, price=0),
    dict(name='Sport (lowered)', ride=-0.07, k=240.0, c=24.0, absorb=0.25, grip=1.12, price=300),
    dict(name='Comfort (raised)', ride=0.07, k=90.0, c=11.0, absorb=0.75, grip=0.96, price=300),
    dict(name='Off-road (long travel)', ride=0.16, k=110.0, c=16.0, absorb=0.92, grip=0.99, price=700),
]
PAINT_COLORS = [('Midnight Black', rgb(22, 24, 28)), ('Arctic White', rgb(236, 237, 240)),
                ('Racing Red', rgb(205, 28, 36)), ('Toxic Green', rgb(96, 222, 56)),
                ('Electric Blue', rgb(28, 108, 236)), ('Sunset Orange', rgb(250, 122, 18)),
                ('Royal Purple', rgb(118, 48, 190)), ('Chrome Silver', rgb(172, 176, 184)),
                ('Gunmetal Grey', rgb(62, 66, 72))]
ACCENT_COLORS = [('Black', rgb(18, 18, 20)), ('White', rgb(240, 240, 240)), ('Neon Cyan', rgb(0, 230, 255)),
                 ('Neon Pink', rgb(255, 40, 170)), ('Gold', rgb(232, 182, 40)), ('Lime', rgb(172, 255, 40)),
                 ('Red', rgb(220, 30, 30)), ('Copper', rgb(192, 110, 60)), ('KuKirin Orange', rgb(255, 110, 0))]
GUNMETAL = 8
KUKIRIN_ORANGE = 8
PAINT_PRICE = 75
ENERGY_SCALE = 8.0         # compresses real-world Wh so a battery lasts minutes, not hours

CAR_TYPES = {
    'sedan': dict(L=4.6, W=1.9, H=1.46, wheel_r=0.36, top=40.0, accel=9.0, grip=10.0, hb_grip=1.3, steer=95.0, mass=1.2,
                  colors=[rgb(160, 20, 30), rgb(30, 40, 60), rgb(200, 200, 205), rgb(40, 40, 44), rgb(60, 90, 70), rgb(120, 120, 128)]),
    'hatch': dict(L=4.0, W=1.8, H=1.5, wheel_r=0.33, top=36.0, accel=8.6, grip=10.5, hb_grip=1.4, steer=105.0, mass=1.0,
                  colors=[rgb(240, 240, 240), rgb(30, 90, 170), rgb(220, 120, 30), rgb(90, 160, 60), rgb(200, 40, 40)]),
    'sports': dict(L=4.5, W=2.0, H=1.2, wheel_r=0.35, top=56.0, accel=14.5, grip=11.0, hb_grip=1.05, steer=108.0, mass=1.1,
                   colors=[rgb(230, 190, 0), rgb(200, 20, 20), rgb(20, 20, 24), rgb(0, 150, 220), rgb(110, 220, 40)]),
    'van': dict(L=5.2, W=2.1, H=2.25, wheel_r=0.4, top=30.0, accel=6.2, grip=8.8, hb_grip=1.6, steer=85.0, mass=1.8,
                colors=[rgb(235, 235, 230), rgb(60, 70, 90), rgb(150, 30, 30)]),
    'taxi': dict(L=4.6, W=1.9, H=1.46, wheel_r=0.36, top=42.0, accel=9.5, grip=10.0, hb_grip=1.3, steer=95.0, mass=1.2,
                 colors=[rgb(30, 30, 34)]),
    'police': dict(L=4.7, W=1.95, H=1.46, wheel_r=0.36, top=50.0, accel=13.0, grip=11.5, hb_grip=1.3, steer=100.0, mass=1.4,
                   colors=[rgb(240, 240, 242)]),
}

GLASS = rgb(60, 80, 100, 130)
DARK = rgb(26, 26, 28)
TRIM = rgb(58, 60, 64)


# ------------------------------------------------------------------ mesh builders
def wheel_builder(r, width, rim_col=None, trim_col=None, knobby=False):
    mb = MeshBuilder()
    mb.cylinder((0, 0, 0), r, width, rgb(24, 24, 26), seg=14, axis='x')
    if knobby:                                   # chunky off-road tread blocks
        for k in range(14):
            a = 2 * math.pi * (k + 0.5) / 14
            mb.box((0, math.sin(a) * r, math.cos(a) * r), (width * 1.08, 0.05, 0.07), rgb(18, 18, 20))
    if trim_col is not None:
        for s in (-1, 1):
            mb.cylinder((s * width * 0.52, 0, 0), r * 0.72, 0.012, trim_col, seg=14, axis='x')
    rc = rim_col if rim_col is not None else rgb(185, 188, 194)
    for s in (-1, 1):
        mb.cylinder((s * width * 0.5, 0, 0), r * 0.62, 0.02, rc, seg=12, axis='x')
    mb.box((0, 0, 0), (width + 0.05, r * 1.15, 0.09), col_mul(rc, 0.8))
    mb.box((0, 0, 0), (width + 0.05, 0.09, r * 1.15), col_mul(rc, 0.8))
    return mb


def _nrm(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / l, v[1] / l, v[2] / l)


def loft(mb, rings, col, caps=(True, True), center_fn=None, cols=None):
    """Skin a series of cross-section rings (same point count) into a closed shape.
    cols: optional per-face-index colour list (face k = between point k and k+1)."""
    n = len(rings[0])
    for i in range(len(rings) - 1):
        A, Bq = rings[i], rings[i + 1]
        ca = tuple(sum(p[c] for p in A) / n for c in range(3))
        cb = tuple(sum(p[c] for p in Bq) / n for c in range(3))
        cen = ((ca[0] + cb[0]) / 2, (ca[1] + cb[1]) / 2, (ca[2] + cb[2]) / 2)
        for k in range(n):
            a, b, c, d = A[k], A[(k + 1) % n], Bq[(k + 1) % n], Bq[k]
            e1 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
            e2 = (d[0] - b[0], d[1] - b[1], d[2] - b[2])
            nn = _nrm((e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]))
            mid = ((a[0] + c[0]) / 2, (a[1] + c[1]) / 2, (a[2] + c[2]) / 2)
            if nn[0] * (mid[0] - cen[0]) + nn[1] * (mid[1] - cen[1]) + nn[2] * (mid[2] - cen[2]) < 0:
                nn = (-nn[0], -nn[1], -nn[2])
            mb.quad(a, b, c, d, nn, cols[k] if cols else col)
    for idx, flip in ((0, -1.0), (len(rings) - 1, 1.0)):
        if not caps[0 if idx == 0 else 1]:
            continue
        R = rings[idx]
        cx = sum(p[0] for p in R) / n
        cy = sum(p[1] for p in R) / n
        cz = sum(p[2] for p in R) / n
        other = rings[1 if idx == 0 else -2]
        oz = sum(p[2] for p in other) / n
        nn = (0.0, 0.0, 1.0 if cz > oz else -1.0)
        for k in range(n):
            mb.tri((cx, cy, cz), R[k], R[(k + 1) % n], nn, col)


def _section(z, hw, yb, ys, yt, hwt):
    """Car body cross-section (8 points): tucked floor, vertical sides, rounded shoulders, top."""
    return [(-hw * 0.93, yb, z), (hw * 0.93, yb, z), (hw, yb + 0.1, z), (hw, ys, z),
            (hw * 0.5 + hwt * 0.5, (ys + yt) / 2 + 0.02, z), (hwt, yt, z),
            (-hwt, yt, z), (-hw * 0.5 - hwt * 0.5, (ys + yt) / 2 + 0.02, z), (-hw, ys, z), (-hw, yb + 0.1, z)]


# body silhouettes: (z as fraction of half-length, width frac, bottom, shoulder, top, top-width frac) - heights in metres
CAR_SHAPES = {
    'sedan': [(-1.0, 0.86, 0.36, 0.72, 0.86, 0.70), (-0.95, 0.97, 0.30, 0.80, 0.96, 0.86), (-0.82, 1.0, 0.26, 0.82, 1.0, 0.9),
              (0.0, 1.0, 0.24, 0.82, 0.98, 0.9), (0.72, 1.0, 0.24, 0.8, 0.93, 0.9), (0.92, 0.98, 0.26, 0.74, 0.85, 0.86),
              (1.0, 0.86, 0.32, 0.62, 0.74, 0.7)],
    'taxi': None, 'police': None,
    'hatch': [(-1.0, 0.9, 0.34, 0.8, 1.0, 0.78), (-0.94, 0.98, 0.28, 0.84, 1.04, 0.88), (0.0, 1.0, 0.24, 0.84, 1.0, 0.9),
              (0.7, 1.0, 0.24, 0.8, 0.94, 0.9), (0.92, 0.97, 0.26, 0.72, 0.85, 0.85), (1.0, 0.86, 0.32, 0.6, 0.74, 0.7)],
    'sports': [(-1.0, 0.84, 0.30, 0.6, 0.74, 0.7), (-0.94, 0.98, 0.24, 0.68, 0.84, 0.86), (-0.6, 1.0, 0.2, 0.7, 0.86, 0.88),
               (0.0, 0.97, 0.2, 0.66, 0.8, 0.86), (0.55, 1.0, 0.2, 0.64, 0.74, 0.88), (0.88, 0.97, 0.21, 0.54, 0.62, 0.84),
               (1.0, 0.84, 0.24, 0.42, 0.5, 0.66)],
    'van': [(-1.0, 0.97, 0.4, 0.95, 1.08, 0.94), (-0.97, 1.0, 0.34, 0.98, 1.1, 0.96), (0.6, 1.0, 0.32, 0.98, 1.1, 0.96),
            (0.8, 0.99, 0.32, 0.95, 1.06, 0.93), (0.94, 0.95, 0.34, 0.86, 0.96, 0.86), (1.0, 0.86, 0.38, 0.7, 0.82, 0.72)],
}
CAR_SHAPES['taxi'] = CAR_SHAPES['sedan']
CAR_SHAPES['police'] = CAR_SHAPES['sedan']
CHROME = rgb(200, 204, 210)


def car_wheel(r, width, side=1, sporty=False):
    """Tyre with sidewall bulge, 5-spoke rim, hub, brake disc and caliper. side=+1 right wheel, -1 left."""
    mb = MeshBuilder()
    s = side
    mb.cylinder((0, 0, 0), r, width, rgb(22, 22, 24), seg=18, axis='x')
    mb.cylinder((s * width * 0.36, 0, 0), r * 0.97, width * 0.32, rgb(34, 34, 36), seg=18, axis='x')   # sidewall
    face = s * width * 0.5
    mb.cylinder((face - s * 0.02, 0, 0), r * 0.68, 0.03, rgb(18, 18, 20), seg=16, axis='x')          # dark barrel
    mb.cylinder((face - s * 0.07, 0, 0), r * 0.5, 0.025, rgb(120, 120, 124), seg=14, axis='x')       # brake disc
    mb.box((face - s * 0.07, r * 0.32, -r * 0.18), (0.07, r * 0.3, r * 0.36), rgb(200, 30, 30) if sporty else rgb(80, 80, 84))
    rim = rgb(205, 208, 214) if not sporty else rgb(40, 40, 44)
    mb.cylinder((face, 0, 0), r * 0.68, 0.02, col_mul(rim, 0.85), seg=18, axis='x', radius_top=None) if False else None
    # rim lip ring
    for k in range(18):
        a0, a1 = 2 * math.pi * k / 18, 2 * math.pi * (k + 1) / 18
        p0 = (face, math.sin(a0) * r * 0.68, math.cos(a0) * r * 0.68)
        p1 = (face, math.sin(a1) * r * 0.68, math.cos(a1) * r * 0.68)
        q0 = (face, math.sin(a0) * r * 0.6, math.cos(a0) * r * 0.6)
        q1 = (face, math.sin(a1) * r * 0.6, math.cos(a1) * r * 0.6)
        mb.quad(p0, p1, q1, q0, (s, 0, 0), rim)
    for k in range(5):                                                       # spokes
        a = 2 * math.pi * k / 5
        mb.beam((face, 0, 0), (face, math.sin(a) * r * 0.62, math.cos(a) * r * 0.62), r * 0.17, 0.035, rim)
    mb.cylinder((face + s * 0.005, 0, 0), r * 0.17, 0.04, col_mul(rim, 0.8), seg=10, axis='x')
    mb.cylinder((face + s * 0.03, 0, 0), r * 0.07, 0.02, rgb(30, 30, 30), seg=8, axis='x')
    return mb


def build_car(spec, kind, body):
    L, W, H = spec['L'], spec['W'], spec['H']
    r = spec['wheel_r']
    B = dict(body=MeshBuilder(), glass=MeshBuilder(), head=MeshBuilder(), tail=MeshBuilder(),
             red=MeshBuilder(), blue=MeshBuilder())
    bb, gl = B['body'], B['glass']
    hl, hw = L / 2.0, W / 2.0
    sports = kind == 'sports'
    van = kind == 'van'
    shape = CAR_SHAPES[kind]
    hscale = 1.0
    # ---- lower body as a lofted shell
    def top_at(z):
        """height of the body's top surface at z (interpolated through the stations)"""
        zs = [st[0] * hl for st in shape]
        for k in range(len(shape) - 1):
            if zs[k] <= z <= zs[k + 1]:
                t = (z - zs[k]) / (zs[k + 1] - zs[k])
                return shape[k][4] * hscale + (shape[k + 1][4] - shape[k][4]) * hscale * t
        return shape[-1][4] * hscale
    rings = []
    for (zf, wf, yb, ys, yt, tw) in shape:
        rings.append(_section(zf * hl, hw * wf, yb, ys, yt, hw * tw))
    nseg = len(rings[0])
    cols = [body] * nseg
    cols[0] = rgb(30, 30, 32)                         # floor
    loft(bb, rings, body, cols=cols)
    belt_rear, belt_front = top_at(-hl * 0.3), top_at(hl * 0.3)
    belt = top_at(0.0)
    # ---- greenhouse (cabin glass + roof)
    if van:
        cb0, cb1, ct0, ct1 = hl * 0.32, hl * 0.84, hl * 0.32, hl * 0.42
    elif kind == 'hatch':
        cb0, cb1, ct0, ct1 = -hl * 0.86, hl * 0.4, -hl * 0.74, hl * 0.02
    elif sports:
        cb0, cb1, ct0, ct1 = -hl * 0.52, hl * 0.36, -hl * 0.26, -hl * 0.0
    else:
        cb0, cb1, ct0, ct1 = -hl * 0.6, hl * 0.4, -hl * 0.36, hl * 0.06
    roof_y = H - 0.06
    if not van:
        cwb, cwt = hw * 0.9, hw * 0.72
        yb0, yb1 = top_at(cb0) - 0.01, top_at(cb1) - 0.01
        g_rings = [[(-cwb, yb0, cb0), (cwb, yb0, cb0), (cwt, roof_y, ct0), (-cwt, roof_y, ct0)],
                   [(-cwb, yb1, cb1), (cwb, yb1, cb1), (cwt, roof_y, ct1), (-cwt, roof_y, ct1)]]
        gl.hexa([g_rings[0][0], g_rings[0][1], g_rings[1][1], g_rings[1][0],
                 g_rings[0][3], g_rings[0][2], g_rings[1][2], g_rings[1][3]], GLASS)
        # roof panel, slightly domed
        bb.hexa([(-cwt - 0.03, roof_y, ct0 - 0.04), (cwt + 0.03, roof_y, ct0 - 0.04), (cwt + 0.03, roof_y, ct1 + 0.04),
                 (-cwt - 0.03, roof_y, ct1 + 0.04),
                 (-cwt + 0.05, H, ct0 + 0.05), (cwt - 0.05, H, ct0 + 0.05), (cwt - 0.05, H, ct1 - 0.05), (-cwt + 0.05, H, ct1 - 0.05)],
                body, bottom=True)
        # A / B / C pillars and window trim
        trim = rgb(20, 20, 22)
        for sd in (-1, 1):
            bb.beam((sd * cwb, yb1, cb1), (sd * cwt, roof_y, ct1), 0.09, 0.07, body)
            bb.beam((sd * cwb, yb0, cb0), (sd * cwt, roof_y, ct0), 0.13, 0.1, body)
            mb_ = (cb0 + cb1) / 2 + (0.08 if not sports else 0.0)
            mt_ = (ct0 + ct1) / 2
            bb.beam((sd * cwb * 1.005, top_at(mb_), mb_), (sd * cwt * 1.005, roof_y, mt_), 0.1, 0.05, trim)
            bb.beam((sd * (cwb + 0.005), yb0 + 0.02, cb0), (sd * (cwb + 0.005), yb1 + 0.02, cb1), 0.04, 0.04, trim)
        if kind in ('sedan', 'taxi', 'police', 'hatch'):
            bb.box((0, H + 0.03, (ct0 + ct1) / 2 - 0.2), (0.06, 0.06, 0.18), rgb(20, 20, 22))     # shark-fin antenna
    else:
        # van: cab glass up front, solid cargo box behind
        cwb = hw * 0.95
        yb0, yb1 = top_at(cb0), top_at(cb1)
        top = H - 0.1
        # cab glass: windshield sloping from the hood up to the roof, side windows down to the belt
        gl.hexa([(-cwb, yb0, cb0), (cwb, yb0, cb0), (cwb, yb1, cb1), (-cwb, yb1, cb1),
                 (-cwb, top, cb0), (cwb, top, cb0), (cwb, top, ct1), (-cwb, top, ct1)], GLASS)
        # high cargo box with a rounded roof edge
        cz0, cz1 = -hl, cb0
        bb.box((0, (top + belt) / 2, (cz0 + cz1) / 2), (W, top - belt + 0.02, cz1 - cz0), body)
        bb.box((0, top + 0.05, (cz0 + ct1) / 2), (W * 0.97, 0.1, ct1 - cz0), body)
        bb.box((0, top + 0.02, ct1 + 0.04), (W * 0.97, 0.08, 0.1), body)
        for sd in (-1, 1):
            bb.beam((sd * cwb, yb1, cb1), (sd * cwb, top, ct1), 0.1, 0.08, body)                      # A-pillar
            bb.box((sd * (hw + 0.012), belt + 0.75, -hl * 0.12), (0.02, 0.04, 1.7), rgb(30, 30, 32))   # sliding door rail
            bb.box((sd * (hw + 0.012), (belt + top) / 2, cb0 - 0.9), (0.02, top - belt - 0.2, 0.03), rgb(40, 40, 42))
        bb.box((0, (top + 0.4) / 2, -hl - 0.012), (0.03, top - 0.5, 0.02), rgb(40, 40, 42))           # rear door split
        for sd in (-1, 1):
            bb.box((sd * 0.5, top - 0.25, -hl - 0.015), (0.4, 0.3, 0.02), rgb(60, 80, 100))           # small rear windows
    # ---- interior seats kept well under the roof
    seat = rgb(30, 30, 32)
    seat_z = (cb0 + cb1) / 2 - (0.1 if not van else 0.0)
    for sd in (-1, 1):
        bb.box((sd * hw * 0.42, belt - 0.2, seat_z), (0.5, 0.18, 0.5), seat)
        bb.box((sd * hw * 0.42, min(belt + 0.15, H - 0.45), seat_z - 0.27), (0.48, min(0.62, H - 0.5 - belt + 0.5), 0.1), seat)
    bb.box((0, belt - 0.02, cb1 - 0.28), (W * 0.84, 0.16, 0.32), rgb(24, 24, 26))                 # dashboard
    bb.cylinder((-hw * 0.42, belt + 0.12, cb1 - 0.45), 0.17, 0.04, DARK, seg=12, axis='z')
    # ---- wheel arches: dark wells + body-colour lips
    wb2 = L * 0.6 / 2
    for zc in (wb2, -wb2):
        for sd in (-1, 1):
            xw = sd * (hw * (1.0 if not sports else 1.0) + 0.006)
            n = 12
            for k in range(n):
                a0 = math.pi * k / n
                a1 = math.pi * (k + 1) / n
                R1, R0 = r * 1.16, r * 0.2
                p = lambda a, R: (xw, r + math.sin(a) * R, zc + math.cos(a) * R)
                bb.quad(p(a0, R0), p(a1, R0), p(a1, R1), p(a0, R1), (sd, 0, 0), rgb(14, 14, 16))
                q = lambda a, R: (xw + sd * 0.012, r + math.sin(a) * R, zc + math.cos(a) * R)
                bb.quad(q(a0, R1), q(a1, R1), q(a1, R1 + 0.07), q(a0, R1 + 0.07), (sd, 0, 0),
                        col_mul(body, 0.9) if not sports else rgb(25, 25, 28))
    # ---- side details: skirts, door seams, handles, mirrors
    for sd in (-1, 1):
        xs = sd * (hw + 0.008)
        bb.box((xs, 0.3, 0), (0.03, 0.12, L * 0.42), rgb(24, 24, 26) if not van else col_mul(body, 0.8))
        if not van:
            for zs in ((cb0 + cb1) / 2 + 0.05, cb1 - 0.05):
                bb.box((xs, (belt + 0.32) / 2 + 0.1, zs), (0.015, belt - 0.42, 0.025), col_mul(body, 0.6))
            for zs in ((cb0 + cb1) / 2 + 0.3, cb0 + 0.35):
                bb.box((sd * (hw + 0.02), belt - 0.1, zs), (0.03, 0.04, 0.16), CHROME)
        mz = cb1 - 0.1
        my = top_at(cb1) + (0.12 if not van else 0.3)
        bb.beam((sd * hw * 0.92, my - 0.05, mz), (sd * (hw + 0.16), my, mz - 0.02), 0.04, 0.04, rgb(24, 24, 26))
        bb.box((sd * (hw + 0.19), my + 0.02, mz - 0.03), (0.08, 0.11, 0.17), body)
        bb.box((sd * (hw + 0.19), my + 0.02, mz - 0.12), (0.06, 0.09, 0.01), rgb(150, 170, 190))
    # ---- front: grille, lights, bumper, plate
    zf = hl
    nose_top = shape[-1][4]
    nose_mid = (shape[-1][3] + shape[-1][2]) / 2
    gw = W * (0.42 if not sports else 0.5)
    bb.box((0, nose_mid - 0.02, zf + 0.005), (gw, 0.17 if not sports else 0.12, 0.03), rgb(18, 18, 20))
    for k in range(3):
        bb.box((0, nose_mid - 0.07 + k * 0.05, zf + 0.022), (gw * 0.95, 0.012, 0.012), CHROME if not sports else rgb(40, 40, 44))
    lip_y = shape[-1][2] + 0.04
    bb.box((0, lip_y, zf - 0.05), (W * 0.86, 0.1, 0.16), rgb(24, 24, 26))
    bb.box((0, lip_y + 0.12, zf + 0.025), (0.5, 0.11, 0.015), rgb(240, 200, 30))                     # Dutch yellow plate
    for sd in (-1, 1):
        hx = sd * hw * 0.62
        hy = (nose_top + nose_mid) / 2 + 0.02
        bb.box((hx, hy, zf - 0.04), (W * 0.27, 0.15, 0.1), rgb(20, 20, 22))                            # housing
        B['head'].box((hx - sd * 0.04, hy, zf - 0.005), (W * 0.15, 0.09, 0.06), Color(1, 1, 1, 1))
        B['head'].box((hx + sd * 0.1, hy - 0.06, zf - 0.005), (W * 0.1, 0.025, 0.06), Color(1, 1, 1, 1))  # DRL strip
    # ---- rear: tail lights, bumper, plate, exhausts, diffuser
    zr = -hl
    deck = shape[0][4]
    rear_mid = (shape[0][3] + shape[0][2]) / 2
    for sd in (-1, 1):
        if van:
            B['tail'].box((sd * hw * 0.9, belt + 0.25, zr - 0.005), (0.14, 0.5, 0.05), Color(1, 1, 1, 1))
            bb.box((sd * hw * 0.9, belt + 0.25, zr + 0.005), (0.18, 0.56, 0.04), rgb(60, 10, 10))
            continue
        ty = (deck + rear_mid) / 2
        B['tail'].box((sd * hw * 0.66, ty, zr + 0.005), (W * 0.26, 0.12, 0.06), Color(1, 1, 1, 1))
        bb.box((sd * hw * 0.66, ty, zr + 0.02), (W * 0.3, 0.16, 0.06), rgb(60, 10, 10))
    if sports:
        B['tail'].box((0, (deck + rear_mid) / 2, zr + 0.005), (W * 0.5, 0.03, 0.05), Color(1, 1, 1, 1))     # light bar
    bb.box((0, shape[0][2] + 0.05, zr + 0.04), (W * 0.86, 0.12, 0.14), rgb(24, 24, 26))
    bb.box((0, rear_mid - 0.02, zr - 0.012), (0.5, 0.11, 0.015), rgb(240, 200, 30))
    for sd in ((-1, 1) if sports else (1,)):
        bb.cylinder((sd * hw * 0.45, shape[0][2] + 0.04, zr - 0.02), 0.045, 0.16, CHROME, seg=8, axis='z')
    if sports:
        for k in range(5):                                                                            # diffuser fins
            bb.box((-0.4 + k * 0.2, shape[0][2] + 0.0, zr + 0.15), (0.02, 0.1, 0.3), rgb(20, 20, 22))
        # rear wing on struts, side intakes, splitter
        wy = deck + 0.28
        for sd in (-1, 1):
            bb.box((sd * hw * 0.55, deck + 0.14, -hl + 0.2), (0.05, 0.26, 0.1), rgb(20, 20, 22))
            bb.box((sd * (hw + 0.004), 0.48, -hl * 0.25), (0.02, 0.14, 0.5), rgb(16, 16, 18))
            bb.box((sd * hw * 0.96, wy, -hl + 0.16), (0.04, 0.16, 0.36), rgb(20, 20, 22))
        bb.box((0, wy, -hl + 0.16), (W * 0.96, 0.04, 0.34), rgb(20, 20, 22))
        bb.box((0, shape[-1][2] - 0.02, hl - 0.08), (W * 0.92, 0.03, 0.3), rgb(20, 20, 22))
    if kind == 'taxi':
        bb.box((0, H + 0.04, (ct0 + ct1) / 2), (0.75, 0.06, 0.3), rgb(30, 30, 30))
        B['head'].box((0, H + 0.15, (ct0 + ct1) / 2), (0.7, 0.18, 0.26), Color(1, 1, 1, 1))
        for sd in (-1, 1):                                                                             # checker band
            for k in range(14):
                zc = -hl * 0.62 + k * (hl * 1.24 / 14)
                bb.box((sd * (hw + 0.01), belt - 0.22, zc), (0.012, 0.09, hl * 1.24 / 14),
                       rgb(240, 196, 20) if k % 2 == 0 else rgb(20, 20, 20))
    if kind == 'police':
        seg = 0.46
        n = int(L * 0.8 / seg)
        for k in range(n):
            zc = -L * 0.4 + (k + 0.5) * seg
            for sd in (-1, 1):
                bb.box((sd * (hw + 0.012), (0.3 + belt) / 2 + 0.03, zc), (0.02, 0.24, seg),
                       rgb(20, 60, 200) if k % 2 == 0 else rgb(245, 215, 20))
        bb.box((0, H + 0.04, (ct0 + ct1) / 2), (1.2, 0.06, 0.32), DARK)
        B['red'].box((-0.33, H + 0.13, (ct0 + ct1) / 2), (0.5, 0.12, 0.26), Color(1, 1, 1, 1))
        B['blue'].box((0.33, H + 0.13, (ct0 + ct1) / 2), (0.5, 0.12, 0.26), Color(1, 1, 1, 1))
        for sd in (-1, 1):                                                                             # push bar
            bb.box((sd * 0.35, lip_y + 0.15, hl + 0.12), (0.06, 0.42, 0.06), rgb(20, 20, 22))
        bb.box((0, lip_y + 0.28, hl + 0.12), (0.8, 0.06, 0.06), rgb(20, 20, 22))
    # ---- driver figure (seated low, head clears the roof)
    drv = MeshBuilder()
    shirt = random.choice((rgb(200, 60, 50), rgb(50, 90, 170), rgb(240, 240, 240), rgb(40, 40, 44), rgb(80, 140, 70)))
    if kind == 'police':
        shirt = rgb(30, 50, 110)
    skin = random.choice((rgb(240, 200, 170), rgb(200, 150, 110), rgb(140, 95, 65), rgb(90, 60, 45)))
    dz = seat_z
    dx = -hw * 0.42
    hip_y = belt - 0.12
    sc = clampf((H - 0.16 - hip_y) / 0.8, 0.55, 1.0)
    tw, td, th = 0.42 * sc, 0.25 * sc, 0.46 * sc
    lean = 0.1 * sc
    drv.hexa([(dx - tw / 2, hip_y, dz - td / 2), (dx + tw / 2, hip_y, dz - td / 2), (dx + tw / 2, hip_y, dz + td / 2), (dx - tw / 2, hip_y, dz + td / 2),
              (dx - tw / 2, hip_y + th, dz - td / 2 - lean), (dx + tw / 2, hip_y + th, dz - td / 2 - lean),
              (dx + tw / 2, hip_y + th, dz + td / 2 - lean), (dx - tw / 2, hip_y + th, dz + td / 2 - lean)], shirt, bottom=True)
    head = (dx, hip_y + th + 0.14 * sc, dz - lean - 0.01)
    drv.sphere(head, 0.115 * sc, skin, 5, 9)
    drv.box((head[0], head[1] + 0.09 * sc, head[2] - 0.01), (0.23 * sc, 0.06 * sc, 0.24 * sc), rgb(40, 30, 24))
    wheel = (dx, belt + 0.12, cb1 - 0.45)
    for sxa in (-1, 1):
        drv.beam((dx + sxa * tw / 2, hip_y + th - 0.05, dz - lean), (wheel[0] + sxa * 0.14, wheel[1], wheel[2] - 0.05),
                 0.08 * sc, 0.08 * sc, shirt)
    B['driver'] = drv
    B['driver_head'] = head
    return B, belt


def build_kukirin_g2(primary, accent):
    """KuKirin G2 standing e-scooter: long grip-taped deck, C-fork, swingarm, tall raked stem."""
    ch, fk, hd = MeshBuilder(), MeshBuilder(), MeshBuilder()
    black = rgb(20, 20, 22)
    metal = rgb(120, 124, 130)
    r = 0.26
    deck_y = 0.34
    # deck + grip tape
    ch.box((0, 0.3, -0.04), (0.24, 0.08, 0.8), primary, bottom=True)
    ch.box((0, deck_y + 0.003, -0.06), (0.2, 0.006, 0.7), black)
    # orange checkered strip along both deck sides
    for k in range(13):
        zc = -0.42 + k * 0.06 + 0.03
        for row, yy in enumerate((0.285, 0.315)):
            c = accent if (k + row) % 2 == 0 else black
            for sx in (-1, 1):
                ch.box((sx * 0.1215, yy, zc), (0.006, 0.03, 0.06), c)
    # neck block where the stem meets the deck
    ch.hexa([(-0.1, 0.26, 0.34), (0.1, 0.26, 0.34), (0.1, 0.26, 0.47), (-0.1, 0.26, 0.47),
             (-0.08, 0.44, 0.38), (0.08, 0.44, 0.38), (0.08, 0.44, 0.5), (-0.08, 0.44, 0.5)], primary, bottom=True)
    # angled kicktail footrest at the rear
    ch.hexa([(-0.11, 0.3, -0.44), (0.11, 0.3, -0.44), (0.11, 0.3, -0.62), (-0.11, 0.3, -0.62),
             (-0.11, 0.37, -0.44), (0.11, 0.37, -0.44), (0.11, 0.47, -0.66), (-0.11, 0.47, -0.66)], primary, bottom=True)
    ch.box((0, 0.425, -0.55), (0.16, 0.006, 0.16), black)
    # rear swingarms (orange) + shock with orange spring
    for sx in (-1, 1):
        ch.beam((sx * 0.085, 0.27, -0.36), (sx * 0.085, r, -0.575), 0.03, 0.06, accent)
    ch.beam((0, 0.3, -0.4), (0, 0.46, -0.58), 0.05, 0.05, black)
    for k in range(5):
        ch.cylinder((0, 0.33 + k * 0.03, -0.43 - k * 0.032), 0.04, 0.012, accent, seg=8)
    # rear fender
    ch.hexa([(-0.07, r * 2 + 0.02, -0.42), (0.07, r * 2 + 0.02, -0.42), (0.07, r * 2 - 0.04, -0.86), (-0.07, r * 2 - 0.04, -0.86),
             (-0.07, r * 2 + 0.05, -0.42), (0.07, r * 2 + 0.05, -0.42), (0.07, r * 2 - 0.01, -0.86), (-0.07, r * 2 - 0.01, -0.86)], black)
    # kickstand (left) and amber side reflectors
    ch.beam((-0.12, 0.27, -0.12), (-0.24, 0.02, -0.22), 0.025, 0.025, black)
    for sx in (-1, 1):
        ch.box((sx * 0.124, 0.3, 0.26), (0.006, 0.03, 0.07), rgb(255, 160, 20))   # amber reflectors
    ch.box((0, 0.44, -0.67), (0.14, 0.04, 0.02), rgb(255, 30, 30))                 # red LED taillight
    # ---- steering parts (fork pivot sits at z = wb/2 - 0.2, front axle at local z = 0.2)
    fk.beam((0, 0.42, -0.04), (0, 1.2, -0.17), 0.065, 0.065, primary)          # tall raked stem
    fk.beam((0, 0.5, -0.02), (0, 0.85, -0.1), 0.075, 0.075, black)             # folding clamp
    fk.box((0, 1.22, -0.17), (0.62, 0.04, 0.04), black)                         # handlebar
    for sx in (-1, 1):
        fk.box((sx * 0.27, 1.22, -0.17), (0.11, 0.05, 0.05), rgb(32, 32, 34))  # grips
        fk.box((sx * 0.2, 1.24, -0.12), (0.12, 0.012, 0.025), metal)           # brake levers
    fk.box((0, 1.25, -0.15), (0.11, 0.035, 0.07), black)                        # LCD housing
    hd.box((0, 1.27, -0.15), (0.08, 0.004, 0.05), rgb(120, 230, 255))           # glowing LCD display
    # hanging KuKirin strap (black / orange)
    fk.beam((0.1, 1.2, -0.15), (0.06, 0.98, -0.11), 0.03, 0.006, black)
    fk.beam((0.06, 0.98, -0.11), (-0.02, 0.9, -0.09), 0.03, 0.006, accent)
    fk.beam((-0.02, 0.9, -0.09), (-0.08, 1.0, -0.12), 0.03, 0.006, black)
    fk.beam((-0.08, 1.0, -0.12), (-0.1, 1.2, -0.15), 0.03, 0.006, accent)
    # C-shaped front suspension fork
    for sx in (-1, 1):
        fk.beam((sx * 0.075, 0.45, -0.02), (sx * 0.075, 0.6, 0.18), 0.03, 0.05, accent)
        fk.beam((sx * 0.075, 0.6, 0.18), (sx * 0.075, 0.45, 0.32), 0.03, 0.05, accent)
        fk.beam((sx * 0.075, 0.45, 0.32), (sx * 0.075, r, 0.2), 0.03, 0.05, accent)
    fk.beam((0, 0.44, -0.02), (0, 0.6, 0.12), 0.04, 0.04, black)                # damper
    fk.hexa([(-0.07, r * 2 + 0.03, 0.02), (0.07, r * 2 + 0.03, 0.02), (0.07, r * 2 - 0.03, 0.42), (-0.07, r * 2 - 0.03, 0.42),
             (-0.07, r * 2 + 0.06, 0.02), (0.07, r * 2 + 0.06, 0.02), (0.07, r * 2, 0.42), (-0.07, r * 2, 0.42)], black)
    hd.box((0, 0.95, -0.075), (0.1, 0.07, 0.02), Color(1, 1, 1, 1))            # headlight on the stem
    return ch, fk, hd, r, 1.15, deck_y, -0.08


def build_two_wheeler(kind, primary, accent):
    """Returns builders: chassis (bounces), fork (steers), headlight."""
    if kind == 'kickscooter':
        return build_kukirin_g2(primary, accent)
    ch, fk, hd = MeshBuilder(), MeshBuilder(), MeshBuilder()
    metal = rgb(150, 154, 160)
    seat = rgb(26, 26, 28)
    if kind == 'scooter':
        r = 0.27
        ch.box((0, 0.33, -0.05), (0.36, 0.08, 0.75), primary)                                   # floorboard
        ch.hexa([(-0.21, 0.3, -0.72), (0.21, 0.3, -0.72), (0.21, 0.3, -0.12), (-0.21, 0.3, -0.12),
                 (-0.17, 0.78, -0.8), (0.17, 0.78, -0.8), (0.19, 0.78, -0.15), (-0.19, 0.78, -0.15)], primary, bottom=True)
        ch.box((0, 0.84, -0.42), (0.34, 0.1, 0.66), seat)
        ch.box((0, 0.79, -0.42), (0.36, 0.03, 0.68), accent)
        for s in (-1, 1):
            ch.box((s * 0.215, 0.55, -0.45), (0.01, 0.08, 0.5), accent)
        ch.box((0, 0.6, -0.86), (0.22, 0.1, 0.06), rgb(200, 20, 20))                            # tail light (dark red)
        ch.hexa([(-0.22, 0.3, 0.32), (0.22, 0.3, 0.32), (0.22, 0.3, 0.42), (-0.22, 0.3, 0.42),
                 (-0.17, 1.02, 0.3), (0.17, 1.02, 0.3), (0.17, 1.02, 0.4), (-0.17, 1.02, 0.4)], primary, bottom=True)
        ch.box((0, 0.2, -0.62), (0.12, 0.22, 0.3), metal)                                       # hub motor housing
        fk.box((0, 0.98, 0.0), (0.07, 0.58, 0.07), metal)
        fk.box((0, 1.24, -0.04), (0.64, 0.05, 0.05), DARK)
        fk.box((0, 1.12, 0.06), (0.3, 0.18, 0.12), primary)
        fk.box((0, 0.62, 0.12), (0.2, 0.06, 0.4), accent)                                        # front fender
        for s in (-1, 1):
            fk.box((s * 0.27, 1.32, -0.05), (0.03, 0.14, 0.03), DARK)
            fk.box((s * 0.29, 1.4, -0.05), (0.1, 0.06, 0.02), metal)
        hd.box((0, 1.12, 0.125), (0.16, 0.1, 0.02), Color(1, 1, 1, 1))
        wb, seat_y, seat_z = 1.25, 0.89, -0.4
    else:
        r = 0.35
        ch.box((0, 0.78, 0.08), (0.26, 0.4, 0.52), primary)                                      # battery box
        ch.box((-0.135, 0.78, 0.08), (0.01, 0.12, 0.42), accent)
        ch.box((0.135, 0.78, 0.08), (0.01, 0.12, 0.42), accent)
        ch.beam((0, 1.12, 0.46), (0, 0.78, 0.32), 0.12, 0.12, metal)                            # down tube
        ch.beam((0, 1.12, 0.46), (0, 1.02, -0.2), 0.08, 0.1, metal)                             # top tube
        ch.beam((0, 0.6, -0.15), (0, 1.02, -0.22), 0.09, 0.09, metal)
        ch.box((0, 1.1, -0.36), (0.25, 0.09, 0.82), seat)
        ch.hexa([(-0.12, 0.98, -0.25), (0.12, 0.98, -0.25), (0.12, 0.98, -0.88), (-0.12, 0.98, -0.88),
                 (-0.1, 1.06, -0.25), (0.1, 1.06, -0.25), (0.1, 1.16, -0.92), (-0.1, 1.16, -0.92)], primary)
        for s in (-1, 1):
            ch.beam((s * 0.12, 0.58, -0.14), (s * 0.08, r, -0.68), 0.05, 0.09, DARK)            # swingarm
        ch.cylinder((0, 0.58, -0.14), 0.13, 0.3, accent, seg=12, axis='x')                       # motor
        ch.box((0, 1.0, -0.95), (0.14, 0.08, 0.04), rgb(200, 20, 20))
        for s in (-1, 1):
            fk.beam((s * 0.11, 1.18, 0.0), (s * 0.11, r, 0.2), 0.055, 0.055, accent)            # gold USD forks
        fk.box((0, 1.24, -0.04), (0.74, 0.05, 0.05), DARK)
        fk.box((0, 1.08, 0.1), (0.3, 0.32, 0.06), primary)                                        # number plate
        fk.box((0, 0.66, 0.25), (0.16, 0.05, 0.5), primary)                                       # high fender
        hd.box((0, 1.1, 0.135), (0.14, 0.09, 0.02), Color(1, 1, 1, 1))
        wb, seat_y, seat_z = 1.36, 1.15, -0.35
    return ch, fk, hd, r, wb, seat_y, seat_z


# ------------------------------------------------------------------ base vehicle
class Vehicle:
    culled = False                      # hidden because it is far from the camera
    is_two_wheeler = False
    is_ev = False
    kind = 'car'

    def __init__(self, game, x, z, heading):
        self.game = game
        self.world = game.world
        self.x, self.z = x, z
        self.y = self.world.ground_height(x, z)
        self.vy = 0.0
        self.heading = heading
        self.vx = self.vz = 0.0
        self.yaw_rate = 0.0
        self.throttle = 0.0
        self.steer = 0.0
        self.handbrake = False
        self.boost = False
        self.horn = False
        self.driver = None              # None, 'player', 'npc' or 'remote' (multiplayer puppet)
        self.ai = None
        self.remote = False
        self.net_target = None
        self.frozen = False
        self.pitch = self.roll = 0.0
        self.susp = 0.0
        self.susp_v = 0.0
        self.health = 100.0
        self.skid = 0.0
        self.drift_angle = 0.0
        self.vl = 0.0
        self.burnout = False
        self.airborne = False
        self.asleep = False
        self.spin_angle = 0.0
        self.last_marks = {}
        self.smoke_acc = 0.0
        self.impact_cooldown = 0.0
        self._ax = 0.0
        self.rear_spin = 0.0
        self.pitch_v = self.roll_v = 0.0
        self.ground_vy = 0.0
        self.on_ground = True
        self.root = Entity(position=(x, self.y, z), rotation_y=heading)
        self.wheels = []
        self.front_pivots = []

    # ---- overridable parameters
    def top_speed(self):
        return self.max_speed

    def accel_value(self):
        return self.accel

    def power_factor(self, dt, thr):
        return 0.35 if self.health <= 0 else 1.0

    def grip_value(self):
        return self.grip

    def absorb(self):
        return 0.45

    def ride(self):
        return 0.0

    @property
    def speed(self):
        return math.hypot(self.vx, self.vz)

    @property
    def pos(self):
        return Vec3(self.x, self.y, self.z)

    def forward(self):
        return heading_vectors(self.heading)[0]

    def wake(self):
        self.asleep = False

    def impulse(self, vx, vy, vz, spin=0.0):
        self.vx += vx
        self.vz += vz
        self.vy += vy
        self.yaw_rate += spin
        self.susp_v -= 1.5
        self.asleep = False

    # ---- multiplayer puppet: follow network snapshots, no local physics
    def _remote_update(self, dt):
        t = self.net_target
        if t is not None:
            x, y, z, h = t['x'], t['y'], t['z'], t['h']
            # extrapolate a little with the sent velocity, then ease towards it
            age = min(0.25, t.get('age', 0.0))
            t['age'] = age + dt
            x += t.get('vx', 0.0) * age
            z += t.get('vz', 0.0) * age
            k = 1.0 - math.exp(-dt * 12.0)
            old_h = self.heading
            self.x += (x - self.x) * k
            self.z += (z - self.z) * k
            self.y += (y - self.y) * k
            self.heading = (self.heading + wrap_angle(h - self.heading) * k) % 360.0
            self.yaw_rate = wrap_angle(self.heading - old_h) / max(dt, 1e-4)
            self.vx, self.vz = t.get('vx', 0.0), t.get('vz', 0.0)
            (fx, fz), _ = heading_vectors(self.heading)
            self.vl = self.vx * fx + self.vz * fz
            self.steer = t.get('st', 0.0)
            self.throttle = t.get('th', 0.0)
            self.handbrake = bool(t.get('hb', 0))
        self.spin_angle = (self.spin_angle + self.vl * dt / self.wheel_r * 57.2958) % 360.0
        self.update_visuals(dt)
        if self.handbrake and self.speed > 4:
            self.effects(dt, 3.0)
        else:
            self.skid = 0.0
            self.last_marks = {}

    # ---- physics
    def update(self, dt):
        if self.remote:
            self._remote_update(dt)
            return
        if self.frozen:
            self.vx = self.vz = self.yaw_rate = 0.0
            self.throttle = 0.0
        if (self.asleep and self.driver is None and self.ai is None):
            return
        w = self.world
        (fx, fz), (rx, rz) = heading_vectors(self.heading)
        vl = self.vx * fx + self.vz * fz
        vt = self.vx * rx + self.vz * rz
        thr = clampf(self.throttle, -1.0, 1.0)
        power = self.power_factor(dt, thr)
        top = self.top_speed()
        acc_long = 0.0
        two = self.is_two_wheeler
        if not self.airborne:
            if (not two) and self.handbrake and thr > 0.5 and abs(vl) < 4.5:
                self.burnout = True
                vl *= max(0.0, 1.0 - 3.0 * dt)
            else:
                self.burnout = False
                if thr > 0.01:
                    if vl < -0.3:
                        acc_long = self.brake * thr
                    else:
                        f = clampf(1.0 - max(vl, 0.0) / max(top, 0.1), 0.0, 1.0)
                        acc_long = self.accel_value() * power * thr * (0.3 + 0.7 * f)
                        if self.handbrake and not two:
                            acc_long *= 0.4
                        if vl > top:
                            acc_long = -(vl - top) * 1.5
                elif thr < -0.01:
                    if vl > 0.3:
                        acc_long = -self.brake * (-thr)
                    elif vl > -self.max_reverse:
                        acc_long = -self.accel_value() * 0.55 * power * (-thr)
                else:
                    acc_long = -vl * 0.12 - math.copysign(0.6, vl) * min(1.0, abs(vl))
                if self.handbrake and abs(vl) > 0.05:
                    dec = self.brake * 0.9 if two else self.hb_decel
                    acc_long -= math.copysign(min(abs(vl) / max(dt, 1e-4), dec), vl)
            vl += acc_long * dt
            vl -= vl * abs(vl) * 0.0011 * dt
        if not two:
            acc_long, vt = self._tire_dynamics(dt, thr, power, top)
        else:
            acc_long, vt = self._arcade_dynamics(dt, thr, two, vl, vt, acc_long, fx, fz, rx, rz)
        self.x += self.vx * dt
        self.z += self.vz * dt
        # world collisions
        impact = 0.0
        hit_pt = None
        (fx, fz), _ = heading_vectors(self.heading)
        for off in self.circle_offsets:
            cx, cz = self.x + fx * off, self.z + fz * off
            nx_, nz_, n = w.collision.resolve_circle(cx, cz, self.radius, self.y + 0.25, self.y + self.height)
            if n is not None:
                self.x += nx_ - cx
                self.z += nz_ - cz
                # rigid-body impulse at the contact point: corner hits make the car spin
                px, pz = fx * off - n[0] * self.radius, fz * off - n[1] * self.radius
                rpx, rpz = pz, -px                        # contact velocity per rad/s of yaw
                k2 = self.yaw_inertia()
                wr = math.radians(self.yaw_rate)
                vpx, vpz = self.vx + wr * rpx, self.vz + wr * rpz
                vn = vpx * n[0] + vpz * n[1]
                if vn < 0:
                    rn = rpx * n[0] + rpz * n[1]
                    j = -(1.0 + 0.25) * vn / (1.0 + rn * rn / k2)
                    # scraping friction along the wall
                    tx, tz = -n[1], n[0]
                    vt_c = vpx * tx + vpz * tz
                    rt = rpx * tx + rpz * tz
                    jt = clampf(-vt_c / (1.0 + rt * rt / k2), -0.35 * j, 0.35 * j)
                    self.vx += j * n[0] + jt * tx
                    self.vz += j * n[1] + jt * tz
                    wr += (j * rn + jt * rt) / k2
                    self.yaw_rate = math.degrees(wr)
                    impact = max(impact, -vn)
                    hit_pt = (nx_ - n[0] * self.radius, self.y + 0.6, nz_ - n[1] * self.radius)
        self.impact_cooldown -= dt
        if impact > 3.0 and self.impact_cooldown <= 0:
            self.on_impact(impact, hit_pt)
        # vertical: rigid body + suspension spring
        wb2 = self.wheelbase / 2.0
        ghf = w.ground_height(self.x + fx * wb2, self.z + fz * wb2)
        ghr = w.ground_height(self.x - fx * wb2, self.z - fz * wb2)
        gh = (ghf + ghr) / 2.0
        if self.y > gh + 0.04 and self.on_ground and self.ground_vy > 0.5:
            self.vy = max(self.vy, self.ground_vy)        # driving off a ramp keeps its upward speed: real launches
        if self.y > gh + 0.04 or self.vy > 0.1:
            self.on_ground = False
            self.ground_vy = 0.0
            self.vy -= 18.0 * dt
            self.y += self.vy * dt
            if self.y <= gh:
                if self.vy < -4:
                    self.game.sound.play('thud', min(1.0, -self.vy / 12), 0.8, (self.x, self.y, self.z))
                    if self.vy < -7 and self.driver == 'player':
                        self.game.camera_rig.shake(min(1.0, -self.vy / 20.0))
                self.susp_v += self.vy * 0.25
                self.pitch_v += self.vy * -2.0                # landing slams the nose / tail
                self.vy = 0.0
                self.y = gh
        else:
            dg = gh - self.y
            spd = self.speed
            # gravity pulls you back on a slope (ramps), instead of a curb-style speed loss
            slope = (ghf - ghr) / self.wheelbase
            if abs(slope) > 0.02:
                self.vx -= fx * 9.81 * slope * dt
                self.vz -= fz * 9.81 * slope * dt
            step = dg / max(spd * dt, 1e-3)                 # height gained per metre travelled
            if dg > 0.04 and spd > 1.0 and step > 0.8:
                k = 1.0 - self.absorb()
                self.susp_v += dg * min(spd, 25.0) * 0.9 * k
                loss = 1.0 - min(0.5, dg * 0.7 * k)
                self.vx *= loss
                self.vz *= loss
                if two:
                    self.yaw_rate += random.uniform(-25, 25) * k * dg * 5
            elif dg < -0.04 and spd > 1.0:
                self.susp_v += dg * min(spd, 25.0) * 0.4
            self.on_ground = True
            y_prev = self.y
            if abs(step) <= 0.8:
                self.y = gh                                  # smooth slope: wheels follow the surface
            else:
                self.y += dg * min(1.0, dt * 18.0)           # curb / step: the suspension soaks it up
            self.vy = 0.0
            self.ground_vy = clampf((self.y - y_prev) / max(dt, 1e-4), -20.0, 20.0)
        self.airborne = self.y > gh + 0.3
        self.susp_v += (-self.susp_k * self.susp - self.susp_c * self.susp_v) * dt
        self.susp = clampf(self.susp + self.susp_v * dt, -0.25, 0.3)
        # body attitude
        slope = -math.degrees(math.atan2(ghf - ghr, self.wheelbase))
        if two:
            pitch_t = clampf(-acc_long * 0.4, -5.0, 5.0) + slope
            roll_t = clampf(-vl * math.radians(self.yaw_rate) * 0.55, -6.0, 6.0)
            self.pitch += (pitch_t - self.pitch) * min(1.0, dt * 6.0)
            self.roll += (roll_t - self.roll) * min(1.0, dt * 6.0)
        else:
            # sprung body: dive under braking, squat on throttle, lean in corners - with a little overshoot
            lat_acc = self.vl * math.radians(self.yaw_rate)
            soft = 1.0 + (self.height - 1.4) * 0.6                     # tall vans lean more
            pitch_t = clampf(-acc_long * 0.42 * soft, -6.5, 6.5) + slope
            roll_t = clampf(-lat_acc * 0.5 * soft, -7.5, 7.5)
            if self.airborne:
                pitch_t = -math.degrees(math.atan2(self.vy, max(abs(self.vl), 2.0))) * 0.8   # nose follows the arc
                roll_t = self.roll
            on, z = 11.0, 0.38                                        # natural frequency (rad/s), damping ratio
            self.pitch_v += (on * on * (pitch_t - self.pitch) - 2 * z * on * self.pitch_v) * dt
            self.roll_v += (on * on * (roll_t - self.roll) - 2 * z * on * self.roll_v) * dt
            self.pitch += self.pitch_v * dt
            self.roll += self.roll_v * dt
        self.spin_angle = (self.spin_angle + vl * dt / self.wheel_r * 57.2958) % 360.0
        if self.burnout:
            self.spin_angle = (self.spin_angle + 1400 * dt) % 360.0
        self.update_visuals(dt)
        self.effects(dt, vt)
        # sleep when parked and settled
        if (self.driver is None and self.ai is None and self.speed < 0.02 and abs(self.susp_v) < 0.01
                and not self.airborne and abs(self.yaw_rate) < 0.5):
            self.vx = self.vz = self.yaw_rate = 0.0
            self.asleep = True

    # ------------------------------------------------------------ car tyre model
    def _tire_dynamics(self, dt, thr, power, top):
        """Bicycle-model car physics:
        * slip angle per axle with a Pacejka-style curve (grip peaks around 8 deg, then falls off)
        * longitudinal weight transfer (braking loads the nose, throttle squats the rear)
        * rear-wheel drive with a friction ellipse: too much throttle = wheelspin = less side grip
        * handbrake locks the rear wheels, so the tail steps out; counter-steer + throttle holds a drift
        * speed-sensitive steering lock, aero drag, rolling resistance, yaw inertia
        Integrated in small sub-steps so it stays stable at any frame rate."""
        G = 9.81
        L = self.wheelbase
        a = b = L * 0.5
        cg_h = 0.5 * (self.height / 1.46)
        k2 = (L * 0.5) ** 2 * 1.05                      # yaw inertia / mass
        mu = self.grip_value() / 10.0 * 1.22             # a touch above real tyres: fun but believable
        hb = self.handbrake and not self.airborne
        h_lat = getattr(self, 'hb_lat', 0.45)
        (fx, fz), (rx, rz) = heading_vectors(self.heading)
        vl = self.vx * fx + self.vz * fz
        vt = self.vx * rx + self.vz * rz
        w = math.radians(self.yaw_rate)
        ax_out = 0.0
        if self.airborne:
            # no tyre contact: keep momentum, slow spin
            w *= math.exp(-0.3 * dt)
            vl -= vl * abs(vl) * 0.0009 * dt
        elif self.burnout:
            vl *= math.exp(-3.0 * dt)
            vt *= math.exp(-4.0 * dt)
            w += (math.radians(self.steer * 150.0) - w) * min(1.0, dt * 4.0)
        else:
            steps = max(1, int(math.ceil(dt / (1.0 / 240.0))))
            h = dt / steps
            for _ in range(steps):
                sp = abs(vl)
                # speed-sensitive lock, but full counter-steer lock while the tail is sliding
                slide = clampf(abs(math.atan2(vt - w * b, max(abs(vl), 3.0))) / 0.3, 0.0, 1.0)
                delta = self.steer * math.radians(36.0) / (1.0 + (sp / 15.0) * (1.0 - slide))
                cd, sd = math.cos(delta), math.sin(delta)
                # ---- driver requests (accelerations, m/s^2)
                drive = 0.0
                brake = 0.0
                if thr > 0.01:
                    if vl < -0.4:
                        brake = self.brake * thr
                    else:
                        f = clampf(1.0 - max(vl, 0.0) / max(top, 0.1), 0.0, 1.0)
                        drive = self.accel_value() * power * thr * (0.32 + 0.68 * f)
                        if vl > top:
                            drive = -(vl - top) * 1.5
                elif thr < -0.01:
                    if vl > 0.4:
                        brake = self.brake * (-thr)
                    elif vl > -self.max_reverse:
                        drive = -self.accel_value() * 0.55 * power * (-thr)
                else:
                    drive = -vl * 0.1 - math.copysign(0.45, vl) * min(1.0, abs(vl))   # engine braking + rolling
                # ---- axle loads with weight transfer (fractions of the car's weight)
                dN = clampf(self._ax * cg_h / L / G, -0.3, 0.3)
                Nf = 0.5 - dN
                Nr = 0.5 + dN
                capf, capr = mu * Nf * G * 2.0, mu * Nr * G * 2.0     # per axle, per unit mass (x2: half the mass each)
                # ---- front axle (steered): velocities in the wheel's own frame
                vtf = vt + w * a
                u = vl * cd + vtf * sd
                s = -vl * sd + vtf * cd
                af = math.atan2(s, max(abs(u), 3.0))
                Fyw = -capf * 0.5 * math.sin(1.6 * math.atan(10.7 * af))
                Fxw = -math.copysign(min(brake * 0.62, capf * 0.5), u) if brake > 0 and abs(u) > 0.05 else 0.0
                # ---- rear axle (driven)
                vtr = vt - w * b
                ar = math.atan2(vtr, max(abs(vl), 3.0))
                Fyr = -capr * 0.5 * math.sin(1.6 * math.atan(10.7 * ar))
                Fxr = drive
                if brake > 0 and abs(vl) > 0.05:
                    Fxr -= math.copysign(brake * 0.38, vl)
                # wheelspin memory: once the tail is out, throttle keeps the rear tyres spinning (drift)
                spin_up = drive > capr * 0.5 * 1.15 and abs(self.steer) > 0.3 and not self.ai     # too much power: wheelspin
                if (abs(ar) > 0.13 or hb or spin_up) and thr > 0.45 and sp > 3.0:
                    self.rear_spin = min(1.0, self.rear_spin + h * 6.0)
                else:
                    self.rear_spin = max(0.0, self.rear_spin - h * (2.0 if thr > 0.2 else 4.0))
                Fyr *= 1.0 - 0.38 * self.rear_spin
                if hb:
                    Fyr *= h_lat                                           # locked wheels slide sideways
                    if abs(vl) > 0.05:
                        Fxr -= math.copysign(min(self.hb_decel * 1.6, abs(vl) / h), vl)
                # friction ellipse on the rear: wheelspin eats side grip (power oversteer)
                lim = capr * 0.5
                e = (Fxr / (lim * 1.3)) ** 2 + (Fyr / lim) ** 2
                if e > 1.0 and not hb:
                    k = 1.0 / math.sqrt(e)
                    Fyr *= k
                    Fxr *= max(k, 0.55)
                # ---- sum in the body frame
                ax = Fxr + Fxw * cd - Fyw * sd
                ay = Fyr + Fxw * sd + Fyw * cd
                torque = a * (Fyw * cd + Fxw * sd) - b * Fyr
                ax -= vl * abs(vl) * 0.0011                                # aero drag
                vl_new = vl + (ax + vt * w) * h
                if (brake > 0 or hb) and vl != 0.0 and vl_new * vl < 0 and thr >= -0.01:
                    vl_new = 0.0                                           # brakes stop the car, they don't reverse it
                vt += (ay - vl * w) * h
                vl = vl_new
                w += torque / k2 * h
                # low speed: wheels roll where they point (parking manoeuvres)
                if sp < 5.0:
                    kin = vl * math.tan(delta) / L
                    blend = (1.0 - sp / 5.0) * min(1.0, h * 14.0)
                    w += (kin - w) * blend
                    vt *= 1.0 - (1.0 - sp / 5.0) * min(1.0, h * 10.0)
                self.heading = (self.heading + math.degrees(w) * h) % 360.0
                self._ax += (ax - self._ax) * min(1.0, h * 8.0)
                ax_out = ax
        (fx, fz), (rx, rz) = heading_vectors(self.heading)
        self.vx = fx * vl + rx * vt
        self.vz = fz * vl + rz * vt
        self.vl = vl
        self.yaw_rate = math.degrees(w)
        self.drift_angle = math.degrees(math.atan2(vt, abs(vl) + 0.5))
        return ax_out, vt

    def _arcade_dynamics(self, dt, thr, two, vl, vt, acc_long, fx, fz, rx, rz):
        """Original arcade model, still used by the e-scooters and e-motorbikes (they lean instead)."""
        sp = abs(vl)
        # steering
        sliding = (not two) and (abs(self.drift_angle) > 9 or (self.handbrake and sp > 3.0))
        steer_gain = clampf(sp / 5.0, 0.0, 1.0) / (1.0 + sp * 0.022 * (0.45 if sliding else 1.0))
        dirn = 1.0 if vl >= -0.1 else -1.0
        target_yaw = self.steer * self.steer_rate * steer_gain * dirn
        if two and getattr(self, 'wheelie', 0.0) > 10.0:
            # on the back wheel the bike pivots easily: sharper turns, even at low speed
            target_yaw = self.steer * self.steer_rate * max(steer_gain, 0.75) * 1.35 * dirn
        if not two and self.handbrake and sp > 3.0:
            target_yaw *= 2.1
        elif sliding and thr > 0.3:
            # power-over: throttle keeps the rear rotating, counter-steer (steer against the slide) reins it in
            slide_dir = -1.0 if self.drift_angle > 0 else 1.0
            target_yaw += slide_dir * min(abs(self.drift_angle), 40.0) * 1.1 * thr
        if self.burnout:
            target_yaw = self.steer * 150.0
        if self.airborne:
            target_yaw = self.yaw_rate * 0.98
        self.yaw_rate += (target_yaw - self.yaw_rate) * min(1.0, dt * (4.5 if sliding else 6.0))
        self.heading = (self.heading + self.yaw_rate * dt) % 360.0
        # lateral grip
        grip_t = self.grip_value()
        if self.airborne:
            grip_t = 0.15
        elif not two and self.handbrake and sp > 3.0:
            grip_t = self.hb_grip
        elif not two and abs(self.drift_angle) > 9 and thr > 0.4 and sp > 6:
            grip_t = self.grip * 0.3
        rate = 2.4 if grip_t > self.cur_grip else 14.0
        self.cur_grip += (grip_t - self.cur_grip) * min(1.0, rate * dt)
        vt *= math.exp(-self.cur_grip * dt)
        self.vx = fx * vl + rx * vt
        self.vz = fz * vl + rz * vt
        self.vl = vl
        self.drift_angle = math.degrees(math.atan2(vt, abs(vl) + 0.5))
        return acc_long, vt

    def yaw_inertia(self):
        return (self.wheelbase * 0.5) ** 2 * 1.05

    def on_impact(self, impact, pt):
        self.impact_cooldown = 0.25
        g = self.game
        g.sound.play('thud', min(1.0, impact / 14.0), random.uniform(0.85, 1.1), (self.x, self.y, self.z))
        if impact > 7:
            g.sound.play('scrape', min(1.0, impact / 20.0), 1.0, (self.x, self.y, self.z))
        if pt is not None:
            for _ in range(int(min(18, impact * 1.5))):
                g.world.particles.spark(pt, (random.uniform(-4, 4), random.uniform(1, 5), random.uniform(-4, 4)), 0.4, 0.09)
        self.health = max(0.0, self.health - impact * 1.2)
        if self.driver == 'player' and not self.is_two_wheeler:
            g.vehicles.drift.crash()
        if self.driver == 'player':
            g.camera_rig.shake(min(1.0, impact / 15.0))
            if impact > 12:
                g.player.damage(impact * 0.6, silent=True)

    def effects(self, dt, vt):
        sp = self.speed
        s = 0.0
        if not self.airborne:
            if not self.is_two_wheeler:
                if sp > 4.0:
                    s = clampf((abs(vt) - 2.0) / 6.0, 0.0, 1.0)
                if self.handbrake and sp > 3.0:
                    s = max(s, 0.65)
            elif self.handbrake and sp > 4.0:
                s = 0.6
            if self.burnout:
                s = 1.0
        self.skid = s
        if s > 0.12:
            for key, pt in self.rear_wheel_points():
                last = self.last_marks.get(key)
                if last is not None:
                    self.world.tire_marks.add(last[0], last[1], pt[0], pt[1], self.world.ground_height(pt[0], pt[1]),
                                              0.24 if not self.is_two_wheeler else 0.13, 0.55 + 0.35 * s)
                self.last_marks[key] = pt
            self.smoke_acc += dt * (30.0 * s)
            while self.smoke_acc > 1.0:
                self.smoke_acc -= 1.0
                key, pt = random.choice(self.rear_wheel_points())
                self.world.particles.smoke_puff((pt[0], self.y + 0.3, pt[1]),
                                                (random.uniform(-0.6, 0.6) - self.vx * 0.15, random.uniform(0.6, 1.4),
                                                 random.uniform(-0.6, 0.6) - self.vz * 0.15),
                                                life=random.uniform(1.2, 2.2), s0=0.7, s1=3.2, shade=0.82, alpha=0.42 * s + 0.1)
        else:
            self.last_marks = {}
        if self.health <= 0 and random.random() < dt * 12:
            (fx, fz), _ = heading_vectors(self.heading)
            p = (self.x + fx * self.wheelbase * 0.6, self.y + 1.0, self.z + fz * self.wheelbase * 0.6)
            self.world.particles.smoke_puff(p, (random.uniform(-0.3, 0.3), 1.8, random.uniform(-0.3, 0.3)), 2.0, 0.6, 2.4, 0.15, 0.6)

    def rear_wheel_points(self):
        (fx, fz), (rx, rz) = heading_vectors(self.heading)
        bx, bz = self.x - fx * self.wheelbase / 2, self.z - fz * self.wheelbase / 2
        if self.is_two_wheeler:
            return [('r', (bx, bz))]
        o = self.track / 2
        return [('rl', (bx - rx * o, bz - rz * o)), ('rr', (bx + rx * o, bz + rz * o))]

    def exit_points(self):
        (fx, fz), (rx, rz) = heading_vectors(self.heading)
        o = (self.track / 2 + 1.0) if not self.is_two_wheeler else 0.9
        return [(self.x - rx * o, self.z - rz * o), (self.x + rx * o, self.z + rz * o),
                (self.x - fx * (self.length / 2 + 1.0), self.z - fz * (self.length / 2 + 1.0)),
                (self.x + fx * (self.length / 2 + 1.0), self.z + fz * (self.length / 2 + 1.0))]

    def circles(self):
        (fx, fz), _ = heading_vectors(self.heading)
        return [(self.x + fx * o, self.z + fz * o) for o in self.circle_offsets]

    def reset_upright(self):
        self.vx = self.vz = self.vy = self.yaw_rate = 0.0
        self.y = self.world.ground_height(self.x, self.z) + 0.6
        self.vy = 1.0
        self.susp = self.susp_v = 0.0

    def destroy(self):
        destroy(self.root)


# ------------------------------------------------------------------ cars
class Car(Vehicle):
    def __init__(self, game, kind, x, z, heading, body_color=None):
        super().__init__(game, x, z, heading)
        spec = CAR_TYPES[kind]
        self.spec = spec
        self.kind = kind
        self.length, self.width, self.height = spec['L'], spec['W'], spec['H']
        self.track = spec['W'] - 0.2
        self.wheel_r = spec['wheel_r']
        self.wheelbase = spec['L'] * 0.6
        self.max_speed = spec['top']
        self.accel = spec['accel']
        self.brake = 16.0
        self.hb_decel = 4.0
        self.max_reverse = 9.0
        self.grip = spec['grip']
        self.hb_grip = spec['hb_grip']
        self.cur_grip = self.grip
        self.steer_rate = spec['steer']
        self.mass = spec['mass']
        self.susp_k, self.susp_c = 160.0, 16.0
        self.radius = self.width / 2
        o = self.length / 2 - self.width / 2
        self.circle_offsets = (-o, 0.0, o)
        self.color = body_color if body_color is not None else random.choice(spec['colors'])
        self.siren_t = 0.0
        self.build_model()

    def build_model(self):
        B, belt = build_car(self.spec, self.kind, self.color)
        self.belt = belt
        self.body = Entity(parent=self.root)
        B['body'].entity(parent=self.body)
        B['glass'].entity(parent=self.body, transparent=True)
        self.head_ent = B['head'].entity(parent=self.body, emissive=0.3)
        self.tail_ent = B['tail'].entity(parent=self.body, emissive=0.4)
        self.tail_ent.color = rgb(150, 10, 10)
        self.driver_ent = B['driver'].entity(parent=self.body)
        self.driver_head = B['driver_head']
        self.driver_ent.enabled = False
        self.red_ent = self.blue_ent = None
        if self.kind == 'police':
            self.red_ent = B['red'].entity(parent=self.body, emissive=1.0)
            self.blue_ent = B['blue'].entity(parent=self.body, emissive=1.0)
        r = self.wheel_r
        hx = self.track / 2
        hz = self.wheelbase / 2
        for (x, z, front) in ((-hx, hz, True), (hx, hz, True), (-hx, -hz, False), (hx, -hz, False)):
            pivot = Entity(parent=self.root, position=(x, r, z))
            wheel = car_wheel(r, 0.26, 1 if x > 0 else -1, self.kind == 'sports').entity(parent=pivot)
            self.wheels.append(wheel)
            if front:
                self.front_pivots.append(pivot)

    def set_npc_driver(self, on):
        self.driver_ent.enabled = on

    def update_visuals(self, dt):
        if self.culled:
            return
        self.root.position = (self.x, self.y, self.z)
        self.root.rotation_y = self.heading
        self.body.y = self.susp
        self.body.rotation_x = self.pitch
        self.body.rotation_z = self.roll
        for wl in self.wheels:
            wl.rotation_x = self.spin_angle
        for p in self.front_pivots:
            p.rotation_y = self.steer * 30.0
        night = self.world.night
        occupied = self.driver is not None
        hl_on = occupied and night > 0.3
        self.head_ent.setShaderInput('emissive', 1.0 if hl_on else 0.25)
        self.head_ent.color = Color(1.0, 0.97, 0.85, 1) if hl_on else Color(0.85, 0.85, 0.8, 1)
        braking = (self.throttle < -0.1 and self.vl > 0.5) or self.handbrake
        if braking and occupied:
            self.tail_ent.setShaderInput('emissive', 1.0)
            self.tail_ent.color = Color(1.0, 0.1, 0.08, 1)
        else:
            self.tail_ent.setShaderInput('emissive', 0.8 if (occupied and night > 0.3) else 0.3)
            self.tail_ent.color = Color(0.7, 0.05, 0.05, 1)
        if self.red_ent is not None:
            self.siren_t += dt
            on = self.ai is not None and getattr(self.ai, 'siren', False)
            ph = int(self.siren_t * 6) % 2 == 0
            self.red_ent.color = Color(1, 0.1, 0.1, 1) if (on and ph) else Color(0.3, 0.05, 0.05, 1)
            self.blue_ent.color = Color(0.15, 0.3, 1, 1) if (on and not ph) else Color(0.05, 0.08, 0.3, 1)
            if on:
                p = (self.x, self.y + 2.0, self.z)
                self.world.lights.add(p, (2.2, 0.2, 0.2) if ph else (0.3, 0.5, 2.6), 13.0)
        if hl_on and self.driver == 'player':
            (fx, fz), _ = heading_vectors(self.heading)
            self.world.lights.add((self.x + fx * 7.0, self.y + 1.0, self.z + fz * 7.0), (1.5, 1.4, 1.2), 15.0)


# ------------------------------------------------------------------ E-scooters & E-motorbikes
class TwoWheeler(Vehicle):
    is_two_wheeler = True
    is_ev = True

    def __init__(self, game, kind, x, z, heading):
        super().__init__(game, x, z, heading)
        self.kind = kind
        self.standing = kind == 'kickscooter'
        self.display_name = {'scooter': 'E-Scooter', 'motorbike': 'E-Motorbike', 'kickscooter': 'KuKirin G2'}[kind]
        self.motor_tier = 0 if kind in ('scooter', 'kickscooter') else 1
        self.battery_tier = 0 if kind == 'scooter' else 1
        self.susp_tier = 0
        self.primary = {'scooter': 4, 'motorbike': 0, 'kickscooter': GUNMETAL}[kind]
        self.accent = {'scooter': 1, 'motorbike': 2, 'kickscooter': KUKIRIN_ORANGE}[kind]
        self.battery_wh = BATTERY_TIERS[self.battery_tier]['wh']
        self.length, self.width = {'scooter': (1.8, 0.7), 'motorbike': (2.0, 0.75), 'kickscooter': (1.4, 0.62)}[kind]
        self.height = 1.4
        self.track = 0.0
        self.brake = 11.0
        self.hb_decel = 6.0
        self.max_reverse = 2.0
        self.grip = 13.0
        self.hb_grip = 13.0
        self.cur_grip = self.grip
        self.steer_rate = {'scooter': 115.0, 'motorbike': 105.0, 'kickscooter': 122.0}[kind]
        self.mass = {'scooter': 0.35, 'motorbike': 0.5, 'kickscooter': 0.25}[kind]
        self.radius = 0.38 if self.standing else 0.42
        self.circle_offsets = (-0.45, 0.45) if self.standing else (-0.55, 0.55)
        self.head_height = 1.62 if self.standing else 0.78
        self.lean = 0.0
        self.boost_active = False
        self.model_ents = []
        # wheelie: the whole bike pivots around the rear contact patch
        self.wheelie = 0.0              # degrees nose-up
        self.wheelie_w = 0.0            # deg / s
        self.wheelie_key = False
        self.wheelie_time = 0.0
        self.lying = False              # fell over - lies on its side until someone picks it up
        self.wheelie_pivot = Entity(parent=self.root)
        self.lean_pivot = Entity(parent=self.wheelie_pivot)
        self.body = Entity(parent=self.lean_pivot)
        self.seat = Entity(parent=self.body)
        self.fork = Entity(parent=self.lean_pivot)
        self.build_model()

    # ---- tuning-derived stats
    def motor_tiers(self):
        return KICK_MOTOR_TIERS if self.kind == 'kickscooter' else MOTOR_TIERS

    def tier_top_kmh(self, t):
        return t['top_kmh'] * (1.15 if self.kind == 'motorbike' else 1.0)

    @property
    def watt(self):
        return self.motor_tiers()[self.motor_tier]['watt']

    @property
    def capacity(self):
        return BATTERY_TIERS[self.battery_tier]['wh']

    @property
    def susp_spec(self):
        return SUSPENSION_TIERS[self.susp_tier]

    @property
    def susp_k(self):
        return self.susp_spec['k']

    @property
    def susp_c(self):
        return self.susp_spec['c']

    def base_top(self):
        return self.tier_top_kmh(self.motor_tiers()[self.motor_tier]) / 3.6

    def top_speed(self):
        t = self.base_top()
        if self.battery_wh <= 0:
            t *= 0.35
        return t * (1.2 if self.boost_active else 1.0)

    def accel_value(self):
        return self.motor_tiers()[self.motor_tier]['accel'] * (1.35 if self.boost_active else 1.0)

    def grip_value(self):
        return self.grip * self.susp_spec['grip']

    def absorb(self):
        return self.susp_spec['absorb']

    def ride(self):
        return self.susp_spec['ride']

    def power_factor(self, dt, thr):
        self.boost_active = self.boost and self.battery_wh > 0 and thr > 0.1 and self.driver == 'player'
        if thr > 0:
            drain = self.watt * thr * (2.5 if self.boost_active else 1.0) * ENERGY_SCALE / 3600.0 * dt
            self.battery_wh = max(0.0, self.battery_wh - drain)
        elif self.speed < 0.5:
            self.battery_wh = min(self.capacity, self.battery_wh + self.capacity * 0.004 * dt)
        return 0.15 if self.battery_wh <= 0 else 1.0

    def battery_pct(self):
        return 100.0 * self.battery_wh / self.capacity

    def range_km(self):
        seconds = self.battery_wh / (self.watt * ENERGY_SCALE / 3600.0)
        return seconds * self.base_top() * 0.7 / 1000.0

    def recharge(self):
        self.battery_wh = self.capacity

    # ---- model
    def build_model(self):
        for e in self.model_ents:
            destroy(e)
        self.model_ents = []
        self.wheels = []
        self.front_pivots = []
        prim = PAINT_COLORS[self.primary][1]
        acc = ACCENT_COLORS[self.accent][1]
        ch, fk, hd, r, wb, seat_y, seat_z = build_two_wheeler(self.kind, prim, acc)
        self.wheel_r, self.wheelbase = r, wb
        self.wheelie_pivot.position = (0, 0, -wb / 2)
        self.lean_pivot.position = (0, 0, wb / 2)
        self.seat_y, self.seat_z = seat_y, seat_z
        e = ch.entity(parent=self.body)
        self.model_ents.append(e)
        self.fork.position = (0, 0, wb / 2 - 0.2)
        f = fk.entity(parent=self.fork)
        self.model_ents.append(f)
        self.head_ent = hd.entity(parent=self.fork, emissive=0.3)
        self.model_ents.append(self.head_ent)
        if self.kind == 'kickscooter':
            dark = rgb(40, 42, 46)
            fw = wheel_builder(r, 0.17, dark, knobby=True).entity(parent=self.fork, position=(0, r, 0.2))
            rw = wheel_builder(r, 0.17, dark, trim_col=rgb(40, 120, 255), knobby=True).entity(
                parent=self.lean_pivot, position=(0, r, -wb / 2))
        else:
            width = 0.14 if self.kind == 'scooter' else 0.12
            fw = wheel_builder(r, width, acc).entity(parent=self.fork, position=(0, r, 0.2))
            rw = wheel_builder(r, width, acc).entity(parent=self.lean_pivot, position=(0, r, -wb / 2))
        self.model_ents += [fw, rw]
        self.wheels = [fw, rw]
        self.front_pivots = [self.fork]
        self.seat.position = (0, seat_y, seat_z)

    def grip_targets(self):
        """Left/right handlebar grip positions in the rider's local space (follows steering)."""
        a = math.radians(self.fork.rotation_y)
        c, sn = math.cos(a), math.sin(a)
        fz = self.fork.z - self.seat_z
        fy = -(self.seat_y + self.body.y)
        out = []
        for gx in (-0.27, 0.27):
            gz = -0.17
            x = gx * c + gz * sn
            z = -gx * sn + gz * c
            out.append((x, fy + 1.22, fz + z))
        return out

    def repaint(self, primary=None, accent=None):
        if primary is not None:
            self.primary = primary
        if accent is not None:
            self.accent = accent
        rider = self.game.player.body.root if self.driver == 'player' else None
        self.build_model()
        if rider is not None:
            rider.parent = self.seat

    # ---- manual wheelie (CTRL): no auto-balance, the rider has to feather it
    BALANCE = 74.0          # balance point in degrees: beyond it the bike flips over backwards
    GRAVITY = 260.0
    LIFT = 360.0
    MAX_RISE = 38.0         # deg/s - the front comes up slowly and smoothly

    def update(self, dt):
        if self.remote:
            t = self.net_target
            if t is not None:
                self.wheelie += (t.get('wh', 0.0) - self.wheelie) * min(1.0, dt * 12)
            super().update(dt)
            return
        self._wheelie(dt)
        super().update(dt)

    def _wheelie(self, dt):
        rider = self.driver == 'player'
        lift_on = (rider and self.wheelie_key and not self.airborne and not self.frozen
                   and self.speed > 1.5 and self.battery_wh > 0)
        if self.wheelie <= 0.0 and not lift_on:
            self.wheelie = 0.0
            self.wheelie_w = 0.0
            self._bank_wheelie()
            return
        torque = -self.GRAVITY * math.cos(math.radians(self.wheelie + (90.0 - self.BALANCE)))
        if lift_on:
            power = clampf(self.accel_value() / 6.0, 0.75, 1.9)
            torque += self.LIFT * (0.55 + 0.45 * max(0.0, self.throttle)) * power
        if self.handbrake:
            torque -= 380.0                     # rear brake drops the front wheel
        if not rider:
            torque -= 200.0
        torque -= self.wheelie_w * 2.0
        self.wheelie_w += torque * dt
        if lift_on:
            # the motor can only raise the front this fast; gravity can still win near the balance point
            self.wheelie_w = min(self.wheelie_w, self.MAX_RISE * (0.6 + 0.4 * max(0.0, self.throttle)))
        self.wheelie += self.wheelie_w * dt
        if self.wheelie <= 0.0:
            if self.wheelie_w < -60:
                self.susp_v -= min(2.5, -self.wheelie_w / 120.0)
                self.game.sound.play('thud', min(0.8, -self.wheelie_w / 300.0), 1.3, (self.x, self.y, self.z), 12)
            self.wheelie = 0.0
            self.wheelie_w = 0.0
            self._bank_wheelie()
        elif rider and self.wheelie > 20:
            self.wheelie_time += dt
        if self.wheelie > 88.0:
            self.fall_over()

    def _bank_wheelie(self):
        if self.wheelie_time > 1.0 and self.driver == 'player':
            t = self.wheelie_time
            cash = int(t * 45 + t * t * 4)          # long wheelies pay extra
            self.game.player.add_cash(cash, 'WHEELIE %.1fs' % self.wheelie_time)
        self.wheelie_time = 0.0

    def fall_over(self):
        """Looped the wheelie: rider is thrown off, bike crashes onto its side."""
        self.wheelie = 0.0
        self.wheelie_w = 0.0
        self.wheelie_time = 0.0
        self.lying = True
        self.game.sound.play('thud', 0.9, 0.9, (self.x, self.y, self.z))
        self.game.sound.play('scrape', 0.7, 1.0, (self.x, self.y, self.z))
        if self.driver == 'player':
            self.game.player.crash_off_bike(self)
        self.vx *= 0.4
        self.vz *= 0.4

    def update_visuals(self, dt):
        if self.culled:
            return
        self.root.position = (self.x, self.y, self.z)
        self.root.rotation_y = self.heading
        self.wheelie_pivot.rotation_x = -self.wheelie
        if self.lying and self.driver is None:
            lean_t = 80.0                       # lying on its side after a crash
        elif self.driver is None and self.speed < 0.3:
            lean_t = -9.0                       # resting on its kickstand
        else:
            w = math.radians(self.yaw_rate)
            lean_t = clampf(math.degrees(math.atan(self.vl * w / 9.81)), -42.0, 42.0)
        self.lean += (lean_t - self.lean) * min(1.0, dt * 7.0)
        self.lean_pivot.rotation_z = self.lean
        self.lean_pivot.rotation_x = self.pitch * 0.5
        self.body.y = self.ride() + self.susp
        self.wheels[0].rotation_x = self.spin_angle
        self.wheels[1].rotation_x = self.spin_angle
        self.fork.rotation_y = self.steer * 22.0 * (1.0 - min(0.7, self.speed / 30.0))
        night = self.world.night
        on = self.driver is not None
        self.head_ent.setShaderInput('emissive', 1.0 if (on and night > 0.3) else 0.25)
        if on and night > 0.3 and self.driver == 'player':
            (fx, fz), _ = heading_vectors(self.heading)
            self.world.lights.add((self.x + fx * 5.0, self.y + 1.0, self.z + fz * 5.0), (1.2, 1.15, 1.0), 11.0)


# ------------------------------------------------------------------ drift scoring
class DriftScore:
    def __init__(self, game):
        self.game = game
        self.points = 0.0
        self.mult = 1
        self.idle = 0.0
        self.active = False
        self.chain_time = 0.0

    def update(self, dt, v):
        drifting = (v is not None and not v.is_two_wheeler and not v.airborne and v.speed > 8.0
                    and abs(v.drift_angle) > 15.0)
        if drifting:
            self.active = True
            self.idle = 0.0
            self.chain_time += dt
            self.mult = 1 + min(4, int(self.chain_time / 2.5))
            self.points += dt * v.speed * abs(v.drift_angle) * 0.25 * self.mult
        elif self.active:
            self.idle += dt
            if self.idle > 1.3:
                self.bank()

    def meter(self):
        """0..1 combo meter: how close the current chain is to the next multiplier."""
        if self.mult >= 5:
            return 1.0
        return (self.chain_time % 2.5) / 2.5

    def bank(self):
        cash = int(self.points / 12)
        if cash >= 5:
            bonus = int(cash * 0.1 * (self.mult - 1))      # clean-finish combo bonus
            self.game.player.add_cash(cash + bonus, 'CLEAN DRIFT x%d' % self.mult)
            self.game.hud.notify('Drift banked: %d pts  =  $%d%s' % (self.points, cash + bonus,
                                 ('  (+$%d combo bonus)' % bonus) if bonus else ''), rgb(255, 200, 60))
        self.points = 0.0
        self.mult = 1
        self.chain_time = 0.0
        self.active = False
        self.idle = 0.0

    def crash(self):
        if self.active and self.points > 50:
            self.game.hud.notify('Drift lost - you crashed!', rgb(255, 90, 90))
        self.points = 0.0
        self.active = False
        self.chain_time = 0.0
        self.mult = 1


# ------------------------------------------------------------------ manager
class VehicleManager:
    def __init__(self, game):
        self.game = game
        self.world = game.world
        self.list = []
        self.cull_dist = 140.0
        self.cull_t = 0.0
        self.drift = DriftScore(game)
        snd = game.sound
        self.engine_loop = snd.loop('engine_car')
        self.ev_loop = snd.loop('engine_ev')
        self.skid_loop = snd.loop('skid')
        self.horn_loop = snd.loop('horn')
        self.siren_loop = snd.loop('siren')
        self._spawn_initial()

    def spawn_car(self, kind, x, z, heading, color=None):
        c = Car(self.game, kind, x, z, heading, color)
        self.list.append(c)
        return c

    def spawn_two_wheeler(self, kind, x, z, heading):
        v = TwoWheeler(self.game, kind, x, z, heading)
        self.list.append(v)
        return v

    def remove(self, v):
        if v in self.list:
            self.list.remove(v)
        v.destroy()

    def _spawn_initial(self):
        w = self.world
        for (kind, x, z, h) in w.featured_spawns:
            if kind in ('scooter', 'motorbike', 'kickscooter'):
                self.spawn_two_wheeler(kind, x, z, h)
            else:
                self.spawn_car(kind, x, z, h)
        kinds = ['sedan', 'hatch', 'sedan', 'van', 'taxi', 'sports', 'hatch']
        for (x, z, h) in w.parking_spots:
            self.spawn_car(random.choice(kinds), x, z, h + random.uniform(-3, 3))
        # cars parked along the curb, plus scattered e-scooters / e-motorbikes
        rng = random.Random(42)
        for _ in range(17):
            idx = rng.randint(1, N_BLOCKS - 1)
            k = rng.randint(0, N_BLOCKS - 1)
            along = ROADS[k] + HALF_ROAD + rng.uniform(10, 30)
            if rng.random() < 0.5:
                self.spawn_car(rng.choice(kinds), ROADS[idx] + 5.0, along, 0.0)
            else:
                self.spawn_car(rng.choice(kinds), along, ROADS[idx] - 5.0, 90.0)
        for _ in range(8):
            idx = rng.randint(0, N_BLOCKS)
            k = rng.randint(0, N_BLOCKS - 1)
            along = ROADS[k] + HALF_ROAD + rng.uniform(8, 32)
            kind = rng.choice(('scooter', 'motorbike', 'scooter', 'kickscooter'))
            side = rng.choice((-1, 1))
            x, z = ROADS[idx] + side * (HALF_ROAD + 1.2), along
            gy = self.world.ground_height(x, z)
            if gy > 0.1 and self.world.collision.resolve_circle(x, z, 0.9, gy + 0.3, gy + 1.2)[2] is None:
                v = self.spawn_two_wheeler(kind, x, z, 0.0 if side > 0 else 180.0)
                if kind == 'kickscooter':
                    continue                    # KuKirins always spawn in stock colours
                v.primary = rng.randrange(len(PAINT_COLORS))
                v.accent = rng.randrange(len(ACCENT_COLORS))
                v.build_model()
        # fixed ids for the e-vehicles so your tuning can be saved and loaded again
        n = 0
        for v in self.list:
            if v.is_two_wheeler:
                v.save_id = 'ev%d' % n
                n += 1

    def tuned_state(self):
        out = {}
        for v in self.list:
            sid = getattr(v, 'save_id', None)
            if sid and getattr(v, 'tuned', False):
                out[sid] = dict(kind=v.kind, motor=v.motor_tier, motor_owned=getattr(v, 'motor_owned', v.motor_tier),
                                battery=v.battery_tier, battery_owned=getattr(v, 'battery_owned', v.battery_tier),
                                susp=v.susp_tier, susp_owned=sorted(getattr(v, 'susp_owned', {0})),
                                primary=v.primary, accent=v.accent, charge=round(float(v.battery_wh), 1),
                                x=round(v.x, 2), z=round(v.z, 2), h=round(v.heading, 1), map=2)
        return out

    def load_tuned(self, data):
        by_id = {getattr(v, 'save_id', None): v for v in self.list}
        for sid, d in (data or {}).items():
            v = by_id.get(sid)
            if v is None or d.get('kind') != v.kind:
                continue
            try:
                n_m = len(v.motor_tiers())
                v.motor_tier = max(0, min(n_m - 1, int(d.get('motor', 0))))
                v.motor_owned = max(v.motor_tier, min(n_m - 1, int(d.get('motor_owned', 0))))
                v.battery_tier = max(0, min(len(BATTERY_TIERS) - 1, int(d.get('battery', 0))))
                v.battery_owned = max(v.battery_tier, min(len(BATTERY_TIERS) - 1, int(d.get('battery_owned', 0))))
                v.susp_tier = max(0, min(len(SUSPENSION_TIERS) - 1, int(d.get('susp', 0))))
                v.susp_owned = set(int(q) for q in d.get('susp_owned', [0])) | {0, v.susp_tier}
                v.battery_wh = max(0.0, min(v.capacity, float(d.get('charge', v.capacity))))
                p = int(d.get('primary', v.primary)) % len(PAINT_COLORS)
                a = int(d.get('accent', v.accent)) % len(ACCENT_COLORS)
                if (p, a) != (v.primary, v.accent):
                    v.primary, v.accent = p, a
                    v.build_model()
                spot_ok = False
                if 'x' in d and d.get('map') == 2:          # parking spots from the old (smaller) city are ignored
                    gy = self.world.ground_height(float(d['x']), float(d['z']))
                    spot_ok = self.world.collision.resolve_circle(float(d['x']), float(d['z']), 0.6, gy + 0.3, gy + 1.2)[2] is None
                if spot_ok:
                    v.x, v.z, v.heading = float(d['x']), float(d['z']), float(d.get('h', v.heading)) % 360.0
                    v.y = self.world.ground_height(v.x, v.z)
                    v.vx = v.vz = v.vy = v.yaw_rate = 0.0
                    v.asleep = False
                    v.update_visuals(0.0)
                v.tuned = True
            except Exception as ex:
                print('[save] could not restore', sid, ex)

    def interactions(self, player):
        out = []
        if player.vehicle is not None or player.state != 'foot':
            return out
        p = player.pos
        best, bd = None, 99.0
        for v in self.list:
            if v.remote:
                continue
            d = math.hypot(v.x - p.x, v.z - p.z) - (v.length / 2.0 if not v.is_two_wheeler else 0.6)
            if d < 1.8 and d < bd and v.speed < 6.0:
                best, bd = v, d
        if best is not None:
            v = best
            if v.kind == 'police' and v.ai is not None:
                return out
            if v.driver == 'npc':
                text = 'Carjack the %s' % ('police car' if v.kind == 'police' else v.kind)
            elif v.is_two_wheeler:
                text = 'Ride the %s (%dW)' % (v.display_name, v.watt)
            else:
                text = 'Steal the %s' % v.kind
            out.append(dict(key='e', text=text, dist=bd, action=lambda v=v: player.enter_vehicle(v)))
        return out

    def knockback(self, pos, radius, force):
        for v in self.list:
            dx, dz = v.x - pos[0], v.z - pos[2]
            d = math.hypot(dx, dz)
            if d < radius:
                k = force * (1.0 - d / radius) / v.mass
                d = d or 0.01
                v.impulse(dx / d * k, k * 0.45, dz / d * k, random.uniform(-80, 80) * (1.0 - d / radius))
                v.health = max(0.0, v.health - 35 * (1.0 - d / radius))

    def _collide_pair(self, a, b):
        for (ax, az) in a.circles():
            for (bx, bz) in b.circles():
                dx, dz = bx - ax, bz - az
                rr = a.radius + b.radius
                d2 = dx * dx + dz * dz
                if d2 < rr * rr and d2 > 1e-8:
                    d = math.sqrt(d2)
                    nx, nz = dx / d, dz / d
                    pen = rr - d
                    wa = b.mass / (a.mass + b.mass)
                    wb_ = a.mass / (a.mass + b.mass)
                    a.x -= nx * pen * wa
                    a.z -= nz * pen * wa
                    b.x += nx * pen * wb_
                    b.z += nz * pen * wb_
                    # contact point halfway between the two circles; full 2D rigid-body impulse with spin
                    cpx, cpz = ax + nx * a.radius, az + nz * a.radius
                    ra = (cpz - a.z, -(cpx - a.x))
                    rb = (cpz - b.z, -(cpx - b.x))
                    wa_, wb2 = math.radians(a.yaw_rate), math.radians(b.yaw_rate)
                    va = (a.vx + wa_ * ra[0], a.vz + wa_ * ra[1])
                    vb = (b.vx + wb2 * rb[0], b.vz + wb2 * rb[1])
                    rv = (vb[0] - va[0]) * nx + (vb[1] - va[1]) * nz
                    if rv < 0:
                        ka, kb = a.yaw_inertia(), b.yaw_inertia()
                        rna = ra[0] * nx + ra[1] * nz
                        rnb = rb[0] * nx + rb[1] * nz
                        denom = 1.0 / a.mass + 1.0 / b.mass + rna * rna / (a.mass * ka) + rnb * rnb / (b.mass * kb)
                        j = -(1.0 + 0.3) * rv / denom
                        a.vx -= j * nx / a.mass
                        a.vz -= j * nz / a.mass
                        b.vx += j * nx / b.mass
                        b.vz += j * nz / b.mass
                        a.yaw_rate -= math.degrees(j * rna / (a.mass * ka))
                        b.yaw_rate += math.degrees(j * rnb / (b.mass * kb))
                        a.asleep = b.asleep = False
                        if -rv > 3.0:
                            for v in (a, b):
                                if v.impact_cooldown <= 0:
                                    v.on_impact(-rv, (ax + nx * a.radius, a.y + 0.6, az + nz * a.radius))
                            if a.driver == 'player' or b.driver == 'player':
                                self.drift.crash()
                    return

    def cull(self, dt, force=False):
        """Hide cars that are far from the camera - fewer draw calls, no animation work."""
        self.cull_t -= dt
        if self.cull_t > 0 and not force:
            return
        self.cull_t = 0.2
        cam = camera.world_position
        cx, cz = cam.x, cam.z
        d2 = self.cull_dist * self.cull_dist
        pv = self.game.player.vehicle
        for v in self.list:
            far = (v.x - cx) ** 2 + (v.z - cz) ** 2 > d2 and v is not pv
            if far != v.culled:
                v.culled = far
                v.root.enabled = not far
                if not far:
                    v.update_visuals(0.0)

    def update(self, dt):
        self.cull(dt)
        for v in self.list:
            if v.ai is not None:
                v.ai.update(dt)
        for v in self.list:
            v.update(dt)
        n = len(self.list)
        for i in range(n):
            a = self.list[i]
            for k in range(i + 1, n):
                b = self.list[k]
                if abs(a.x - b.x) < 7.0 and abs(a.z - b.z) < 7.0:
                    if a.asleep and b.asleep:
                        continue
                    self._collide_pair(a, b)
        # props get kicked by moving vehicles
        for v in self.list:
            if v.speed < 1.0:
                continue
            for p in self.world.props.items:
                if abs(p.x - v.x) > 4 or abs(p.z - v.z) > 4:
                    continue
                for (cx, cz) in v.circles():
                    if (p.x - cx) ** 2 + (p.z - cz) ** 2 < (p.r + v.radius) ** 2:
                        dx, dz = p.x - cx, p.z - cz
                        d = math.hypot(dx, dz) or 0.1
                        p.push(v.vx * 1.1 + dx / d * 2.0, 2.0 + v.speed * 0.15, v.vz * 1.1 + dz / d * 2.0, 400)
                        v.vx *= 0.97
                        v.vz *= 0.97
                        self.game.sound.play('thud', 0.35, 1.5, (p.x, p.y, p.z), 12)
                        break
        self._audio(dt)
        pv = self.game.player.vehicle
        self.drift.update(dt, pv if (pv is not None and not pv.is_two_wheeler) else None)

    def _audio(self, dt):
        pv = self.game.player.vehicle
        if pv is not None and not self.game.paused:
            sp = pv.speed
            top = max(pv.top_speed(), 1.0)
            thr = max(0.0, pv.throttle)
            if pv.is_ev:
                self.ev_loop.set(0.12 + 0.35 * thr + 0.2 * min(1, sp / top), 0.45 + 1.7 * min(1.2, sp / top) + (0.25 if pv.boost_active else 0))
                self.engine_loop.set(0)
            else:
                gear_pos = (sp / top * 4.0) % 1.0
                rate = 0.55 + 0.9 * gear_pos * min(1.0, sp / 6.0) + 0.5 * min(1.0, sp / top) + (0.6 if pv.burnout else 0)
                self.engine_loop.set(0.22 + 0.3 * thr, rate)
                self.ev_loop.set(0)
            self.horn_loop.set(0.7 if pv.horn else 0.0)
        else:
            self.engine_loop.set(0)
            self.ev_loop.set(0)
            self.horn_loop.set(0)
        skid = 0.0
        for v in self.list:
            if v.skid > 0.1:
                skid = max(skid, v.skid * self.game.sound.falloff((v.x, v.y, v.z), 25))
        self.skid_loop.set(0.0 if self.game.paused else skid * 0.6, 0.9 + 0.2 * skid)
        siren = 0.0
        for v in self.list:
            if v.kind == 'police' and v.ai is not None and getattr(v.ai, 'siren', False):
                siren = max(siren, self.game.sound.falloff((v.x, v.y, v.z), 40))
        self.siren_loop.set(0.0 if self.game.paused else siren * 0.55)

    def silence(self):
        for l in (self.engine_loop, self.ev_loop, self.skid_loop, self.horn_loop, self.siren_loop):
            l.set(0)

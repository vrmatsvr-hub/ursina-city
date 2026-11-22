"""
items_and_shops.py  -  fireworks, shops, robberies, businesses, tuning
========================================================================

* Inventory + weapon wheel (hold Tab, flick the mouse, release) / keys 1-3
* Cobra 6:   thrown with Left Click, short sparking fuse, massive bang,
             flash light, fireball, smoke, scorch mark, camera shake,
             knockback on NPCs / vehicles / props / you
* Scream 100: lands, hisses, then screams (rising whistle) with a fountain
             of bright sparks for 2 seconds, hops around, then a very loud
             bang with an expanding shockwave ring
* Fireworks dealer stall (menu)
* Store robberies in the shops - stay at the register while the clerk
  empties it, shop alarm goes off, wanted stars + alert timer, cooldown
* Ownable businesses: buy with stolen cash, passive income into a safe,
  collect + upgrade the income rate
* E-Tuning Garage: ride an E-Scooter / E-Motorbike onto the glowing pad:
  motor wattage, battery, suspension, primary + accent paint
"""
from ursina import *
import math
import random
from world import (Color, MeshBuilder, make_lit, rgb, col_mul, clampf, heading_vectors, smoothstep, yaw_towards,
                   ROADS, N_BLOCKS, CURB_H)
from vehicles import (TwoWheeler, MOTOR_TIERS, BATTERY_TIERS, SUSPENSION_TIERS, PAINT_COLORS, ACCENT_COLORS,
                      PAINT_PRICE)
from panda3d.core import ColorBlendAttrib

UI_BG = rgb(14, 16, 22, 236)
UI_ACCENT = rgb(255, 140, 30)
BTN = rgb(46, 52, 66)
BTN_GOOD = rgb(36, 140, 70)
BTN_OWNED = rgb(40, 90, 160)
BTN_BAD = rgb(110, 40, 40)

SLOTS = [('hands', 'Unarmed'), ('cobra6', 'Cobra 6'), ('scream100', 'Scream 100')]
FIREWORK_INFO = {
    'cobra6': dict(name='Cobra 6', price=40, pack=5, pack_price=180, desc='Lands upright, 3 s spark fountain, then a massive bang.'),
    'scream100': dict(name='Scream 100', price=95, pack=5, pack_price=425, desc='Screams for 10 s with a huge fountain, then a massive bang.'),
}


def ui_circle_mesh(n=32):
    verts = [(0, 0, 0)]
    for k in range(n + 1):
        a = 2 * math.pi * k / n
        verts.append((math.cos(a) * 0.5, math.sin(a) * 0.5, 0))
    tris = []
    for k in range(1, n + 1):
        tris += [0, k, k + 1]
    return Mesh(vertices=verts, triangles=tris)


# =================================================================== generic menu
class Menu:
    def __init__(self, game, title, w=1.1, h=0.78):
        self.game = game
        self.title = title
        self.w, self.h = w, h
        self.ents = []
        self.static = []
        game.open_menu(self)
        self.rebuild()

    def add(self, e):
        self.ents.append(e)
        return e

    def text(self, txt, x, y, scale=1.0, col=None, origin=(-0.5, 0.5)):
        return self.add(Text(text=txt, parent=camera.ui, position=(x, y), origin=origin, scale=scale,
                             color=col if col is not None else color.white, z=-0.1))

    def button(self, label, x, y, w, h, cb, col=None, text_scale=1.0):
        c = col if col is not None else BTN
        b = Button(text=label, parent=camera.ui, position=(x, y), scale=(w, h), color=c,
                   highlight_color=col_mul(c, 1.35), pressed_color=col_mul(c, 0.75), z=-0.1)
        b.on_click = cb
        if text_scale != 1.0:
            try:
                b.text_entity.scale = b.text_entity.scale * text_scale
            except Exception:
                pass
        return self.add(b)

    def swatch(self, x, y, size, col, cb, selected):
        if selected:
            self.add(Entity(parent=camera.ui, model='quad', position=(x, y), scale=size + 0.012, color=color.white, z=-0.05))
        b = Button(text='', parent=camera.ui, position=(x, y), scale=size, color=col, highlight_color=col_mul(col, 1.25),
                   pressed_color=col_mul(col, 0.8), z=-0.1)
        b.on_click = cb
        return self.add(b)

    def rebuild(self):
        for e in self.ents:
            destroy(e)
        self.ents = []
        w, h = self.w, self.h
        self.add(Entity(parent=camera.ui, model='quad', scale=(w, h), color=UI_BG, z=0.1))
        self.add(Entity(parent=camera.ui, model='quad', scale=(w, 0.006), position=(0, h / 2 - 0.075), color=UI_ACCENT, z=0.05))
        self.text(self.title, -w / 2 + 0.03, h / 2 - 0.02, 1.6, UI_ACCENT)
        self.text('Cash: $%s' % format(int(self.game.player.cash), ','), w / 2 - 0.03, h / 2 - 0.025, 1.25,
                  rgb(120, 255, 140), origin=(0.5, 0.5))
        self.build()
        self.button('Close  [Esc]', w / 2 - 0.13, -h / 2 + 0.045, 0.22, 0.05, self.close)

    def build(self):
        pass

    def close(self):
        for e in self.ents:
            destroy(e)
        self.ents = []
        self.game.close_menu(self)
        self.on_close()

    def on_close(self):
        pass


# =================================================================== fireworks
# tiny 3x5 pixel font for the procedural labels
_PIX = {
    'S': ('111', '100', '111', '001', '111'), 'C': ('111', '100', '100', '100', '111'),
    'R': ('110', '101', '110', '101', '101'), 'E': ('111', '100', '110', '100', '111'),
    'A': ('010', '101', '111', '101', '101'), 'M': ('101', '111', '111', '101', '101'),
    'O': ('111', '101', '101', '101', '111'), 'B': ('110', '101', '110', '101', '110'),
    '1': ('010', '110', '010', '010', '111'), '0': ('111', '101', '101', '101', '111'),
    '6': ('111', '100', '111', '101', '111'), ' ': ('000', '000', '000', '000', '000'),
}


def _wrap_px(mb, r, ang, y, w_ang, h, col):
    """One label 'pixel' lying on the surface of a cylinder (radius r) at angle ang (deg) and height y."""
    a0, a1 = math.radians(ang - w_ang / 2), math.radians(ang + w_ang / 2)
    am = (a0 + a1) / 2
    p = lambda a, yy: (math.sin(a) * r, yy, math.cos(a) * r)
    n = (math.sin(am), 0.0, math.cos(am))
    mb.quad(p(a0, y - h / 2), p(a1, y - h / 2), p(a1, y + h / 2), p(a0, y + h / 2), n, col)


def _wrap_text(mb, text, r, ang0, y0, px, col, slant=0.0, vertical=False):
    """Pixel text wrapped onto a cylinder. Horizontal: left->right across the front.
    Vertical: runs up the length of the body (letters rotated 90 deg)."""
    w_ang = math.degrees(px / r)
    cx = 0
    for ch in text:
        g = _PIX.get(ch, _PIX[' '])
        for row in range(5):
            for col_i in range(3):
                if g[row][col_i] != '1':
                    continue
                if vertical:
                    # letter rows go around the body, letter columns go up the body
                    yy = y0 + (cx + col_i) * px
                    aa = ang0 + (row - 2) * w_ang
                else:
                    aa = ang0 + (cx + col_i) * w_ang
                    yy = y0 - row * px + (cx + col_i) * px * slant
                _wrap_px(mb, r, aa, yy, w_ang * 1.02, px * 1.02, col)
        cx += 4


def build_firework_model(kind):
    """Procedural 3D models. Origin = centre of the bottom, so it stands on the ground."""
    mb = MeshBuilder()
    black = rgb(16, 16, 18)
    paper = rgb(28, 28, 30)
    fuse_g = rgb(40, 190, 60)
    white = rgb(240, 240, 240)
    red = rgb(220, 24, 30)
    if kind == 'scream100':
        R, H = 0.11, 0.34
        mb.cylinder((0, H / 2, 0), R, H, black, seg=20)
        # crinkled, tapered paper neck
        neck = [(0.105, 0.02), (0.092, 0.02), (0.098, 0.018), (0.078, 0.018), (0.084, 0.016), (0.062, 0.016),
                (0.068, 0.014), (0.046, 0.014), (0.05, 0.012), (0.034, 0.016)]
        y = H
        for k, (rr, hh) in enumerate(neck):
            nxt = neck[k + 1][0] if k + 1 < len(neck) else 0.028
            mb.cylinder((0, y + hh / 2, 0), rr, hh, paper if k % 2 else black, seg=14, radius_top=nxt)
            y += hh
        mb.cylinder((0, y + 0.006, 0), 0.03, 0.012, black, seg=10)
        mb.cylinder((0.004, y + 0.05, 0), 0.0055, 0.09, fuse_g, seg=6)       # green visco fuse
        top = y + 0.1
        # label on the front: jagged sound-wave band, slanted SCREAM, red 100
        rl = R + 0.0015
        px = 0.0105
        for k in range(26):
            a = -66 + k * 5.2
            hgt = 0.012 + 0.022 * abs(math.sin(k * 1.3)) * (0.5 + 0.5 * math.sin(k * 0.7))
            _wrap_px(mb, rl, a, H - 0.045, 4.6, hgt, white)
        _wrap_text(mb, 'SCREAM', rl, -62, H - 0.1, px, white, slant=0.32)
        _wrap_text(mb, '100', rl, -22, 0.105, px * 1.6, red)
        _wrap_px(mb, rl, 0, 0.028, 120, 0.006, red)
        return mb.entity(), top
    # cobra 6
    R, H = 0.068, 0.26
    mb.cylinder((0, H / 2, 0), R, H, black, seg=16)
    mb.cylinder((0, H + 0.03, 0), R, 0.06, paper, seg=14, radius_top=0.022)    # tapered paper top
    mb.cylinder((0.003, H + 0.1, 0), 0.0048, 0.085, fuse_g, seg=6)
    top = H + 0.14
    rl = R + 0.0015
    px = 0.0072
    _wrap_text(mb, 'COBRA 6', rl, 0, 0.03, px, red, vertical=True)              # red name up the length
    # white zig-zag accent next to the name
    for k in range(9):
        _wrap_px(mb, rl, 40 + (8 if k % 2 else -8) * 0.5, 0.04 + k * 0.023, 9, 0.026, white)
    # green rings around the bottom
    for yy in (0.012, 0.024):
        _wrap_px(mb, rl, 0, yy, 359, 0.006, fuse_g)
    return mb.entity(), top


class Firework:
    """Thrown in an arc, lands and stands upright, then:
    Scream 100: 10 s rising scream + huge titanium fountain, then a massive bang.
    Cobra 6:    3 s sizzling spark fountain (no scream), then the same massive bang."""
    FOUNTAIN = {'scream100': 10.0, 'cobra6': 3.0}

    def __init__(self, system, kind, pos, vel, fid=None):
        self.sys = system
        self.game = system.game
        self.kind = kind
        self.fid = fid
        self.e, self.top = build_firework_model(kind)
        self.x, self.y, self.z = pos
        self.vx, self.vy, self.vz = vel
        self.yaw = math.degrees(math.atan2(vel[0], vel[2])) if abs(vel[0]) + abs(vel[2]) > 0.01 else 0.0
        self.rx = self.rz = 0.0
        self.spin = (random.uniform(-520, 520), random.uniform(-520, 520))
        self.t = 0.0
        self.phase = 'flying'
        self.dead = False
        self.remote = False
        self.alarm_cd = 0.0
        self.emit_acc = 0.0
        self.loop_snd = None
        self.loop_t = 0.0
        self.fuse_snd = self.game.sound.play('fuse', 0.55, 1.0, pos, 12)

    # ---- landing
    def land(self, x=None, z=None, yaw=None):
        if self.phase != 'flying':
            return
        w = self.game.world
        if x is not None:
            self.x, self.z = x, z
        if yaw is not None:
            self.yaw = yaw
        self.y = w.ground_height(self.x, self.z)
        self.vx = self.vy = self.vz = 0.0
        self.rx = self.rz = 0.0                       # stands perfectly upright: rotation = (0, yaw, 0)
        self.phase = 'fountain'
        self.t = 0.0
        if self.fuse_snd is not None:
            self.fuse_snd.stop()
        p = (self.x, self.y + self.top, self.z)
        if self.kind == 'scream100':
            self.loop_snd = self.game.sound.play('scream10', 1.0, 1.0, p, 34)
        else:
            self.loop_snd = self.game.sound.play('fountain', 0.9, 1.0, p, 20)
        self.game.world.particles.smoke_puff((self.x, self.y + 0.1, self.z), (0, 0.4, 0), 1.0, 0.2, 0.8, 0.7, 0.35)
        if not self.remote and self.game.net is not None and self.fid is not None:
            self.game.net.send_firework_land(self.fid, (self.x, self.y, self.z), self.yaw)

    def update(self, dt):
        w = self.game.world
        self.t += dt
        if self.phase == 'flying':
            self.vy -= 16.0 * dt
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.z += self.vz * dt
            x, z, n = w.collision.resolve_circle(self.x, self.z, 0.1, self.y - 0.1, self.y + 0.1)
            if n is not None:
                vn = self.vx * n[0] + self.vz * n[1]
                if vn < 0:
                    self.vx -= 1.4 * vn * n[0]
                    self.vz -= 1.4 * vn * n[1]
            self.x, self.z = x, z
            self.rx += self.spin[0] * dt
            self.rz += self.spin[1] * dt
            self.e.position = (self.x, self.y, self.z)
            self.e.rotation = (self.rx, self.yaw, self.rz)
            p = (self.x, self.y + 0.1, self.z)
            if random.random() < 0.7:
                w.particles.spark(p, (random.uniform(-1, 1), random.uniform(0.5, 2), random.uniform(-1, 1)), 0.25, 0.06,
                                  Color(1.0, 0.7, 0.25, 1.0), 6.0)
            w.lights.add(p, (1.0, 0.6, 0.25), 3.0)
            if (self.y <= w.ground_height(self.x, self.z) and self.vy <= 0) or self.t > 6.0:
                if not self.remote:
                    self.land()
                else:
                    self.y = w.ground_height(self.x, self.z)
                    self.land()                        # the thrower's 'landed' message corrects the spot
            return
        if self.phase != 'fountain':
            return
        # standing upright on the ground
        self.e.position = (self.x, self.y, self.z)
        self.e.rotation = (0, self.yaw, 0)
        dur = self.FOUNTAIN[self.kind]
        k = min(1.0, self.t / dur)
        top = (self.x, self.y + self.top, self.z)
        P = w.particles
        big = self.kind == 'scream100'
        rate = (70.0 + 50.0 * k) if big else 55.0
        self.emit_acc += rate * dt
        cols = ((Color(1, 1, 1, 1), Color(1, 0.95, 0.75, 1), Color(1, 0.82, 0.35, 1), Color(0.85, 0.9, 1, 1)) if big else
                (Color(1, 0.9, 0.6, 1), Color(1, 0.75, 0.3, 1), Color(1, 1, 1, 1)))
        while self.emit_acc >= 1.0:
            self.emit_acc -= 1.0
            if big:
                up = random.uniform(13.0, 21.0) * (0.75 + 0.35 * k)
                sp = random.uniform(-1.6, 1.6)
                P.spark(top, (sp + random.uniform(-0.6, 0.6), up, random.uniform(-1.6, 1.6)),
                        random.uniform(1.0, 1.7), random.uniform(0.12, 0.2), random.choice(cols), 9.0)
            else:
                P.spark(top, (random.uniform(-1.3, 1.3), random.uniform(6.0, 10.0), random.uniform(-1.3, 1.3)),
                        random.uniform(0.6, 1.0), random.uniform(0.09, 0.14), random.choice(cols), 9.0)
        if random.random() < (0.35 if big else 0.2):
            P.smoke_puff(top, (random.uniform(-0.4, 0.4), 1.2, random.uniform(-0.4, 0.4)), 2.2, 0.3, 1.8, 0.8, 0.3)
        flick = 0.75 + 0.25 * random.random()
        if big:
            w.lights.add((self.x, self.y + 2.5, self.z), (2.6 * flick, 2.4 * flick, 2.0 * flick), 16.0)
            P.flash(top, 0.5 + 0.3 * random.random(), 0.06)
        else:
            w.lights.add((self.x, self.y + 1.2, self.z), (2.0 * flick, 1.5 * flick, 0.8 * flick), 9.0)
        self.alarm_cd -= dt
        if self.alarm_cd <= 0:
            self.alarm_cd = 0.5
            self.game.npcs.alarm(top, 30.0 if big else 20.0, 5.0)
        if self.t >= dur and not self.remote:
            self.explode()
        elif self.remote and self.t >= dur + 1.0:
            self.explode()                             # backup if the network 'explode' message never arrives

    def explode(self, pos=None):
        if self.dead:
            return
        self.dead = True
        for s in (self.fuse_snd, self.loop_snd):
            if s is not None:
                s.stop()
        if pos is not None:
            self.x, self.y, self.z = pos
        destroy(self.e)
        if not self.remote and self.game.net is not None and self.fid is not None:
            self.game.net.send_firework_explode(self.fid, (self.x, self.y, self.z))
        self.sys.explode((self.x, self.y, self.z), self.kind, local=not self.remote)


class ShockRing:
    def __init__(self, pos, radius, life=0.55):
        mb = MeshBuilder()
        mb.ring_xz((0, 0, 0), 0.82, 1.0, 0.0, Color(1, 1, 1, 1), 40)
        self.e = mb.entity(emissive=1.0, transparent=True)
        self.e.setDepthWrite(False)
        self.e.setAttrib(ColorBlendAttrib.make(ColorBlendAttrib.MAdd, ColorBlendAttrib.OIncomingAlpha, ColorBlendAttrib.OOne))
        self.e.position = (pos[0], pos[1] + 0.15, pos[2])
        self.radius = radius
        self.t = 0.0
        self.life = life

    def update(self, dt):
        self.t += dt
        k = self.t / self.life
        if k >= 1.0:
            destroy(self.e)
            return False
        s = 0.5 + self.radius * 1.7 * (1.0 - (1.0 - k) ** 2)
        self.e.scale = (s, 1, s)
        self.e.color = Color(1.0, 0.85, 0.6, (1.0 - k) * 0.9)
        return True


class WeaponWheel:
    def __init__(self, system):
        self.sys = system
        self.ents = []
        self.open = False
        self.cx = self.cy = 0.0
        self.sel = 0
        self.discs = []

    def show(self):
        if self.open:
            return
        self.open = True
        self.cx = self.cy = 0.0
        self.sel = self.sys.selected
        self.ents.append(Entity(parent=camera.ui, model=ui_circle_mesh(), scale=0.62, color=rgb(10, 12, 16, 170), z=0.1))
        self.discs = []
        for i, (key, name) in enumerate(SLOTS):
            a = math.radians(90 - i * 120)
            x, y = math.cos(a) * 0.19, math.sin(a) * 0.19
            d = Entity(parent=camera.ui, model=ui_circle_mesh(), position=(x, y), scale=0.15, color=rgb(50, 56, 70, 230), z=0.05)
            self.discs.append(d)
            self.ents.append(d)
            icon_col = {'hands': rgb(230, 200, 170), 'cobra6': rgb(220, 30, 40), 'scream100': rgb(30, 90, 220)}[key]
            self.ents.append(Entity(parent=camera.ui, model='quad', position=(x, y + 0.025), scale=(0.03, 0.06) if key != 'hands' else (0.05, 0.05),
                                    color=icon_col, z=0.0))
            label = name if key == 'hands' else '%s  x%d' % (name, self.sys.inv[key])
            self.ents.append(Text(text=label, parent=camera.ui, position=(x, y - 0.035), origin=(0, 0), scale=0.85, z=-0.01))
        self.ents.append(Text(text='WEAPON WHEEL - move mouse, release TAB', parent=camera.ui, position=(0, -0.36),
                              origin=(0, 0), scale=0.9, color=rgb(200, 200, 200)))

    def update(self, dt):
        if not self.open:
            return
        self.cx = clampf(self.cx + mouse.velocity[0] * 6.0, -1, 1)
        self.cy = clampf(self.cy + mouse.velocity[1] * 6.0, -1, 1)
        if math.hypot(self.cx, self.cy) > 0.25:
            ang = math.degrees(math.atan2(self.cy, self.cx))
            best = min(range(3), key=lambda i: abs((ang - (90 - i * 120) + 180) % 360 - 180))
            self.sel = best
        for i, d in enumerate(self.discs):
            d.color = rgb(255, 140, 30, 240) if i == self.sel else rgb(50, 56, 70, 230)

    def hide(self):
        if not self.open:
            return
        self.open = False
        for e in self.ents:
            destroy(e)
        self.ents = []
        self.discs = []
        self.sys.select(self.sel)


class FireworksSystem:
    def __init__(self, game):
        self.game = game
        self.inv = {'cobra6': 3, 'scream100': 1}
        self.selected = 1
        self.active = []
        self.effects = []
        self.wheel = WeaponWheel(self)
        self.throw_cd = 0.0
        self.next_id = random.randint(1, 1 << 20)
        self.remote_by_id = {}

    def equipped(self):
        return SLOTS[self.selected][0]

    def select(self, i):
        self.selected = i % len(SLOTS)
        self.game.sound.play('blip', 0.5)

    def cycle(self, d):
        self.select(self.selected + d)

    def throw(self):
        g = self.game
        key = self.equipped()
        if key == 'hands' or self.throw_cd > 0:
            return
        if self.inv[key] <= 0:
            g.hud.notify('No %s left - visit the fireworks dealer in the park.' % FIREWORK_INFO[key]['name'], rgb(255, 160, 80))
            g.sound.play('error', 0.5)
            return
        rig = g.camera_rig
        fwd = rig.forward()
        pl = g.player
        if pl.vehicle is not None:
            v = pl.vehicle
            (fx, fz), (rx, rz) = heading_vectors(v.heading)
            origin = (v.x - rx * 1.4, v.y + 1.3, v.z - rz * 1.4)
            vel = (fwd[0] * 9 + v.vx, 3.5 + fwd[1] * 6, fwd[2] * 9 + v.vz)
        else:
            if pl.state != 'foot':
                return
            yaw = math.radians(rig.yaw)
            origin = (pl.pos.x + math.cos(yaw) * 0.3 + fwd[0] * 0.4, pl.pos.y + 1.5, pl.pos.z - math.sin(yaw) * 0.3 + fwd[2] * 0.4)
            vel = (fwd[0] * 12.5 + pl.vel_x, 3.5 + fwd[1] * 9.0, fwd[2] * 12.5 + pl.vel_z)
            pl.body.throw()
        self.inv[key] -= 1
        self.throw_cd = 0.45
        self.next_id += 1
        self.active.append(Firework(self, key, origin, vel, fid=self.next_id))
        g.sound.play('whoosh', 0.6, 1.0)
        if g.net is not None:
            g.net.send_firework(key, origin, vel, self.next_id)

    def spawn_remote(self, kind, pos, vel, owner=None, fid=None):
        """A firework thrown by another player in multiplayer."""
        if kind not in FIREWORK_INFO:
            return
        f = Firework(self, kind, tuple(pos), tuple(vel))
        f.remote = True
        self.active.append(f)
        if fid is not None:
            self.remote_by_id[(owner, fid)] = f

    def remote_land(self, owner, fid, pos, yaw):
        f = self.remote_by_id.get((owner, fid))
        if f is None or f.dead:
            return
        if f.phase == 'flying':
            f.land(pos[0], pos[2], yaw)
        else:                                   # already landed locally: move it to the thrower's exact spot
            f.x, f.z, f.yaw = pos[0], pos[2], yaw
            f.y = self.game.world.ground_height(f.x, f.z)
            f.t = max(f.t, 0.0)

    def remote_explode(self, owner, fid, pos):
        f = self.remote_by_id.pop((owner, fid), None)
        if f is not None and not f.dead:
            f.explode(tuple(pos))

    def sky_burst(self, pos):
        """Decorative aerial firework (used on the main menu)."""
        g = self.game
        P = g.world.particles
        col = random.choice((Color(1, 0.3, 0.3, 1), Color(0.3, 1, 0.4, 1), Color(0.4, 0.6, 1, 1), Color(1, 0.85, 0.3, 1),
                             Color(1, 0.4, 1, 1), Color(1, 1, 1, 1)))
        for _ in range(70):
            a = random.uniform(0, 2 * math.pi)
            b = random.uniform(-1, 1)
            r = math.sqrt(1 - b * b)
            sp = random.uniform(9, 14)
            P.spark(pos, (math.cos(a) * r * sp, b * sp, math.sin(a) * r * sp), random.uniform(1.0, 1.6), 0.35, col, 3.0)
        P.flash(pos, 10.0, 0.25)
        g.world.lights.flash(pos, (col[0] * 3, col[1] * 3, col[2] * 3), 60.0, 0.6)
        g.sound.play('bang_cobra', 0.5, random.uniform(0.7, 0.9), pos, 70)

    def explode(self, pos, kind, local=True):
        """Both fireworks end with the same massive, bass-heavy blast and a thick lingering smoke cloud."""
        g = self.game
        w = g.world
        big = True
        radius = 14.0
        force = 26.0
        x, y, z = pos
        g.sound.play('bang_mega', 1.0, random.uniform(0.96, 1.04), pos, 60)
        g.sound.play('bang_scream', 0.7, random.uniform(0.85, 0.95), pos, 45)     # layered for extra bass
        w.lights.flash((x, y + 1.5, z), (11.0, 8.0, 5.0), radius * 3.2, 0.6)
        P = w.particles
        P.flash((x, y + 0.8, z), 10.0, 0.18)
        P.flash((x, y + 0.6, z), 5.0, 0.35)
        for _ in range(18):
            P.fire((x + random.uniform(-0.6, 0.6), y + random.uniform(0.2, 1.0), z + random.uniform(-0.6, 0.6)),
                   (random.uniform(-6, 6), random.uniform(1, 7), random.uniform(-6, 6)), random.uniform(0.35, 0.75),
                   1.2, random.uniform(4.0, 7.0))
        for _ in range(110):
            a = random.uniform(0, 2 * math.pi)
            sp = random.uniform(6, 24)
            P.spark((x, y + 0.3, z), (math.cos(a) * sp, random.uniform(2, 15), math.sin(a) * sp), random.uniform(0.4, 1.2), 0.13)
        # thick grey/white smoke that billows out and hangs in the air for several seconds
        for _ in range(46):
            a = random.uniform(0, 2 * math.pi)
            d = random.uniform(0.0, 2.2)
            sh = random.uniform(0.55, 0.9)
            P.smoke_puff((x + math.cos(a) * d, y + random.uniform(0.4, 3.0), z + math.sin(a) * d),
                         (math.cos(a) * random.uniform(1.0, 3.5), random.uniform(0.3, 1.4), math.sin(a) * random.uniform(1.0, 3.5)),
                         random.uniform(7.0, 11.0), random.uniform(1.8, 3.0), random.uniform(6.5, 9.5), sh,
                         random.uniform(0.55, 0.75), rise=-0.12, drag=0.9)
        for k in range(28):
            a = 2 * math.pi * k / 28
            P.smoke_puff((x + math.cos(a), y + 0.3, z + math.sin(a)), (math.cos(a) * 10, 0.4, math.sin(a) * 10),
                         random.uniform(3.5, 5.0), 1.0, 3.6, 0.7, 0.5, rise=-0.2, drag=1.3)
        w.decals.place(x, w.ground_height(x, z), z, 4.5)
        if big:
            self.effects.append(ShockRing((x, w.ground_height(x, z), z), radius))
        self.effects.append(ShockRing((x, w.ground_height(x, z), z), radius * 0.6, 0.35))
        cam = camera.world_position
        dcam = math.sqrt((cam.x - x) ** 2 + (cam.y - y) ** 2 + (cam.z - z) ** 2)
        g.camera_rig.shake(clampf(1.9 - dcam / 32.0, 0.0, 1.8))
        g.hud.flash(clampf(1.05 - dcam / 70.0, 0.0, 0.9))
        g.npcs.knockback(pos, radius, force)
        g.npcs.alarm(pos, 55.0, 9.0)
        g.traffic.alarm(pos, 45.0)
        g.vehicles.knockback(pos, radius, force * 0.8)
        w.props.knockback(pos, radius * 1.3, force)
        pl = g.player
        pp = pl.pos
        d = math.sqrt((pp.x - x) ** 2 + (pp.z - z) ** 2)
        if pl.vehicle is None and d < radius:
            k = 1.0 - d / radius
            pl.damage((70.0 if big else 50.0) * k)
            if d > 0.01:
                pl.knock((pp.x - x) / d * force * k, 4.0 + 5.0 * k, (pp.z - z) / d * force * k)
        elif pl.vehicle is not None and d < radius * 0.5:
            pl.damage(20.0 * (1.0 - d / (radius * 0.5)))
        # cops nearby take fireworks in the street seriously
        for p in (g.wanted.police if local else ()):
            if p.mode == 'chase' or math.hypot(p.car.x - x, p.car.z - z) < 45:
                g.wanted.report(1, 'Illegal fireworks')
                break

    def update(self, dt):
        self.throw_cd = max(0.0, self.throw_cd - dt)
        for f in list(self.active):
            f.update(dt)
            if f.dead:
                self.active.remove(f)
        if len(self.remote_by_id) > 40:
            self.remote_by_id = {k: f for k, f in self.remote_by_id.items() if not f.dead}
        self.effects = [e for e in self.effects if e.update(dt)]
        self.wheel.update(dt)


# =================================================================== dealer
class DealerMenu(Menu):
    def __init__(self, game):
        super().__init__(game, 'FIREWORKS DEALER', 1.15, 0.62)

    def build(self):
        g = self.game
        fw = g.fireworks
        y = 0.17
        self.text('"Real Dutch quality, mate. Don\'t tell the cops where you got it."', -0.54, 0.22, 0.9, rgb(200, 200, 200))
        for key in ('cobra6', 'scream100'):
            info = FIREWORK_INFO[key]
            y -= 0.1
            self.add(Entity(parent=camera.ui, model='quad', position=(-0.49, y - 0.015), scale=(0.035, 0.07),
                            color=rgb(210, 20, 30) if key == 'cobra6' else rgb(20, 70, 200), z=0.0))
            self.text('%s   (owned: %d)' % (info['name'], fw.inv[key]), -0.45, y + 0.02, 1.2)
            self.text(info['desc'], -0.45, y - 0.02, 0.85, rgb(190, 190, 190))
            c1 = BTN_GOOD if g.player.cash >= info['price'] else BTN_BAD
            c5 = BTN_GOOD if g.player.cash >= info['pack_price'] else BTN_BAD
            self.button('1x  $%d' % info['price'], 0.25, y - 0.012, 0.15, 0.055, lambda k=key: self.buy(k, 1), c1)
            self.button('%dx  $%d' % (info['pack'], info['pack_price']), 0.43, y - 0.012, 0.17, 0.055, lambda k=key: self.buy(k, 5), c5)
            y -= 0.08
        self.text('Left Click = throw   |   TAB = weapon wheel   |   1/2/3 = select', -0.54, -0.2, 0.85, rgb(255, 200, 120))

    def buy(self, key, n):
        info = FIREWORK_INFO[key]
        cost = info['price'] if n == 1 else info['pack_price']
        if self.game.player.spend(cost):
            self.game.fireworks.inv[key] += n
            if self.game.fireworks.equipped() == 'hands':
                self.game.fireworks.selected = 1 if key == 'cobra6' else 2
            self.game.hud.notify('Bought %dx %s' % (n, info['name']), rgb(255, 200, 120))
        self.rebuild()


# =================================================================== robberies
class RobberySystem:
    DURATION = 4.5
    PAYOUT = {'convenience': (750, 1500), 'electronics': (1800, 3200), 'jewelry': (4000, 7000), 'gas': (1200, 2400)}
    STARS = {'convenience': 2, 'electronics': 2, 'jewelry': 3, 'gas': 2}

    def __init__(self, game):
        self.game = game
        self.shops = game.world.shops
        self.state = [dict(cooldown=0.0, robbing=False, progress=0.0, paid=0, total=0, alarm=0.0, tick=0.0,
                           loop=game.sound.loop('alarm')) for _ in self.shops]
        self.current = None

    def interactions(self, player):
        out = []
        if player.vehicle is not None or player.state != 'foot':
            return out
        p = player.pos
        for i, s in enumerate(self.shops):
            ix, _, iz = s['interact']
            d = math.hypot(p.x - ix, p.z - iz)
            if d > 2.4:
                continue
            st = self.state[i]
            if st['robbing']:
                continue
            if st['cooldown'] > 0:
                out.append(dict(key=None, text='Register empty (%ds)' % int(st['cooldown']), dist=d, action=None))
            else:
                out.append(dict(key='e', text='Rob the register', dist=d, action=lambda i=i: self.start(i)))
            if self.game.wanted.level == 0:
                out.append(dict(key='b', text='Buy a snack $15 (+25 HP)', dist=d + 0.01, action=self.buy_snack))
        return out

    def buy_snack(self):
        pl = self.game.player
        if pl.health >= 100:
            self.game.hud.notify('You are not hungry.', rgb(200, 200, 200))
            return
        if pl.spend(15):
            pl.health = min(100.0, pl.health + 25)
            self.game.hud.notify('Tasty snack! +25 HP', rgb(120, 255, 140))

    def start(self, i):
        g = self.game
        s, st = self.shops[i], self.state[i]
        st['robbing'] = True
        st['progress'] = 0.0
        st['paid'] = 0
        lo, hi = self.PAYOUT[s['kind']]
        st['total'] = random.randint(lo, hi)
        st['alarm'] = 25.0
        st['tick'] = 0.0
        self.current = i
        g.npcs.clerks[i].set_state('hands_up', 30.0)
        g.npcs.alarm(s['register'], 40.0, 10.0)
        g.wanted.report(self.STARS[s['kind']], 'Robbery at %s' % s['name'].title())
        g.hud.notify('Stay at the register while the clerk empties it!', rgb(255, 220, 120))
        g.camera_rig.shake(0.15)

    def update(self, dt):
        g = self.game
        pp = g.player.pos
        for i, (s, st) in enumerate(zip(self.shops, self.state)):
            st['cooldown'] = max(0.0, st['cooldown'] - dt)
            if st['alarm'] > 0:
                st['alarm'] -= dt
                vol = g.sound.falloff(s['register'], 22) * 0.6
                st['loop'].set(0.0 if (st['alarm'] <= 0 or g.paused) else vol)
            if not st['robbing']:
                continue
            ix, _, iz = s['interact']
            if math.hypot(pp.x - ix, pp.z - iz) > 3.2 or g.player.state != 'foot':
                self._finish(i, aborted=True)
                continue
            st['progress'] += dt / self.DURATION
            st['tick'] += dt
            if st['tick'] > 0.45:
                st['tick'] = 0.0
                chunk = int(st['total'] * min(st['progress'], 1.0)) - st['paid']
                if chunk > 0:
                    st['paid'] += chunk
                    g.player.add_cash(chunk, None, sound=False)
                    g.sound.play('cash', 0.5, random.uniform(0.9, 1.15), s['register'])
                    g.world.particles.spark(s['register'], (random.uniform(-1, 1), 2.5, random.uniform(-1, 1)), 0.5, 0.06,
                                            Color(0.4, 1.0, 0.4, 1), 6)
            if st['progress'] >= 1.0:
                self._finish(i, aborted=False)

    def _finish(self, i, aborted):
        g = self.game
        s, st = self.shops[i], self.state[i]
        rest = (int(st['total'] * min(st['progress'], 1.0)) - st['paid']) if not aborted else 0
        if rest > 0:
            g.player.add_cash(rest, None, sound=False)
            st['paid'] += rest
        st['robbing'] = False
        st['cooldown'] = 150.0
        self.current = None
        g.npcs.clerks[i].set_state('cower', 25.0)
        if aborted:
            g.hud.notify('Robbery interrupted - you got $%d' % st['paid'], rgb(255, 180, 80))
        else:
            g.hud.notify('ROBBERY COMPLETE  +$%d   Lose the cops!' % st['paid'], rgb(120, 255, 140))
            g.sound.play('cash', 1.0, 1.0)

    def progress(self):
        if self.current is None:
            return None
        return self.state[self.current]['progress']


# =================================================================== businesses
class BusinessMenu(Menu):
    def __init__(self, game, sys, idx):
        self.sys = sys
        self.idx = idx
        b = sys.data[idx]
        super().__init__(game, b['name'], 1.05, 0.56)

    def build(self):
        s = self.sys
        b = s.data[self.idx]
        st = s.state[self.idx]
        g = self.game
        if not st['owned']:
            self.text('This property is for sale.', -0.48, 0.17, 1.15)
            self.text('Passive income: $%d / minute (level 1), upgradeable to level 5.' % b['income'], -0.48, 0.11, 0.95,
                      rgb(200, 200, 200))
            self.text('Income is stored in the safe - come back to collect it.', -0.48, 0.07, 0.95, rgb(200, 200, 200))
            c = BTN_GOOD if g.player.cash >= b['price'] else BTN_BAD
            self.button('BUY PROPERTY  $%s' % format(b['price'], ','), 0.0, -0.06, 0.42, 0.075, lambda: self.buy(), c)
            return
        rate = s.rate(self.idx)
        self.text('Level %d / 5     Income: $%d per minute' % (st['level'], rate), -0.48, 0.17, 1.15)
        self.text('Safe: $%d   (max $%d)' % (int(st['safe']), int(s.cap(self.idx))), -0.48, 0.11, 1.05, rgb(120, 255, 140))
        self.button('COLLECT  $%d' % int(st['safe']), -0.22, -0.02, 0.32, 0.075, self.collect,
                    BTN_GOOD if st['safe'] >= 1 else BTN)
        if st['level'] < 5:
            cost = s.upgrade_cost(self.idx)
            nxt = int(b['income'] * (1 + 0.6 * st['level']))
            self.button('UPGRADE to Lv %d  ($%s)\nearns $%d / min' % (st['level'] + 1, format(cost, ','), nxt), 0.2, -0.02, 0.36, 0.1,
                        self.upgrade, BTN_GOOD if g.player.cash >= cost else BTN_BAD)
        else:
            self.text('MAX LEVEL', 0.12, 0.0, 1.2, UI_ACCENT)

    def buy(self):
        self.sys.buy(self.idx)
        self.rebuild()

    def collect(self):
        self.sys.collect(self.idx)
        self.rebuild()

    def upgrade(self):
        self.sys.upgrade(self.idx)
        self.rebuild()


class BusinessSystem:
    def __init__(self, game):
        self.game = game
        self.data = game.world.businesses
        self.state = [dict(owned=False, level=1, safe=0.0) for _ in self.data]

    def rate(self, i):
        return int(self.data[i]['income'] * (1 + 0.6 * (self.state[i]['level'] - 1)))

    def cap(self, i):
        return self.rate(i) * 8

    def upgrade_cost(self, i):
        return int(self.data[i]['price'] * 0.45 * self.state[i]['level'])

    def total_income(self):
        return sum(self.rate(i) for i, st in enumerate(self.state) if st['owned'])

    def buy(self, i):
        b, st = self.data[i], self.state[i]
        if st['owned']:
            return
        if self.game.player.spend(b['price']):
            st['owned'] = True
            b['sale_text'].text = 'OWNED'
            b['sale_text'].color = rgb(20, 150, 40)
            b['price_text'].text = 'Level 1'
            self.game.hud.notify('You now own %s!  +$%d / min' % (b['name'].title(), self.rate(i)), rgb(120, 255, 140))

    def collect(self, i):
        st = self.state[i]
        amt = int(st['safe'])
        if amt > 0:
            st['safe'] -= amt
            self.game.player.add_cash(amt, 'Business income')

    def upgrade(self, i):
        st = self.state[i]
        if st['level'] >= 5:
            return
        if self.game.player.spend(self.upgrade_cost(i)):
            st['level'] += 1
            self.data[i]['price_text'].text = 'Level %d' % st['level']
            self.game.hud.notify('%s upgraded to level %d' % (self.data[i]['name'].title(), st['level']), rgb(120, 255, 140))

    def interactions(self, player):
        out = []
        if player.vehicle is not None or player.state != 'foot':
            return out
        p = player.pos
        for i, b in enumerate(self.data):
            bx, _, bz = b['pos']
            d = math.hypot(p.x - bx, p.z - bz)
            if d < 3.0:
                st = self.state[i]
                if st['owned']:
                    txt = 'Manage %s (safe $%d)' % (b['name'].title(), int(st['safe']))
                else:
                    txt = 'Buy %s ($%s)' % (b['name'].title(), format(b['price'], ','))
                out.append(dict(key='e', text=txt, dist=d, action=lambda i=i: BusinessMenu(self.game, self, i)))
        return out

    def update(self, dt):
        for i, st in enumerate(self.state):
            if st['owned']:
                st['safe'] = min(self.cap(i), st['safe'] + self.rate(i) / 60.0 * dt)


# =================================================================== tuning garage
class TuningMenu(Menu):
    def __init__(self, game, garage, vehicle):
        self.garage = garage
        self.v = vehicle
        super().__init__(game, 'E-TUNING GARAGE  -  %s' % vehicle.display_name, 1.55, 0.94)

    def _row(self, title, y, items):
        self.text(title, -0.74, y + 0.03, 1.15, UI_ACCENT)
        x = -0.38
        for (label, col, cb) in items:
            self.button(label, x, y, 0.255, 0.075, cb, col, 0.8)
            x += 0.275

    def build(self):
        v = self.v
        g = self.game
        cash = g.player.cash
        top = v.base_top() * 3.6
        self.text('Top speed %d km/h   |   Accel %.1f m/s2   |   Battery %d Wh (%d%%)   |   Range ~%.1f km   |   %s' % (
            top, v.accel_value(), v.capacity, v.battery_pct(), v.range_km(), v.susp_spec['name']), -0.74, 0.37, 0.9,
            rgb(200, 230, 255))

        def tier_items(tiers, current, owned_max, label_fn, setter):
            items = []
            for i, t in enumerate(tiers):
                if i == current:
                    items.append((label_fn(t) + '\nINSTALLED', BTN_GOOD, lambda: None))
                elif i <= owned_max:
                    items.append((label_fn(t) + '\nowned - install', BTN_OWNED, lambda i=i: setter(i, 0)))
                else:
                    items.append((label_fn(t) + '\n$%s' % format(t['price'], ','), BTN if cash >= t['price'] else BTN_BAD,
                                  lambda i=i, p=t['price']: setter(i, p)))
            return items

        self._row('MOTOR', 0.24, tier_items(v.motor_tiers(), v.motor_tier, getattr(v, 'motor_owned', v.motor_tier),
                                            lambda t: '%dW  (%d km/h)' % (t['watt'], v.tier_top_kmh(t)),
                                            self.set_motor))
        self._row('BATTERY', 0.12, tier_items(BATTERY_TIERS, v.battery_tier, getattr(v, 'battery_owned', v.battery_tier),
                                           lambda t: '%s  %dWh' % (t['name'], t['wh']), self.set_battery))
        self._row('SUSPENSION', 0.0, self._susp_items(cash))
        self.text('FRAME / BODY COLOUR  ($%d)' % PAINT_PRICE, -0.74, -0.1, 1.0, UI_ACCENT)
        for i, (name, c) in enumerate(PAINT_COLORS):
            self.swatch(-0.36 + i * 0.075, -0.17, 0.06, c, lambda i=i: self.paint(i, None), i == v.primary)
        self.text('ACCENT COLOUR  ($%d)' % PAINT_PRICE, -0.74, -0.23, 1.0, UI_ACCENT)
        for i, (name, c) in enumerate(ACCENT_COLORS):
            self.swatch(-0.36 + i * 0.075, -0.3, 0.06, c, lambda i=i: self.paint(None, i), i == v.accent)
        self.text('Primary: %s   Accent: %s' % (PAINT_COLORS[v.primary][0], ACCENT_COLORS[v.accent][0]), 0.33, -0.16, 0.9,
                  rgb(200, 200, 200))
        self.text('Higher wattage = more top speed + acceleration, but drains the battery faster.\n'
                  'Bigger battery = more range and longer boost (hold SHIFT while riding).\n'
                  'Suspension changes ride height, stiffness and how well curbs / speed bumps are absorbed.',
                  -0.74, -0.35, 0.8, rgb(170, 170, 170))

    def _susp_items(self, cash):
        v = self.v
        owned = getattr(v, 'susp_owned', {0})
        items = []
        for i, t in enumerate(SUSPENSION_TIERS):
            if i == v.susp_tier:
                items.append((t['name'] + '\nINSTALLED', BTN_GOOD, lambda: None))
            elif i in owned:
                items.append((t['name'] + '\nowned - install', BTN_OWNED, lambda i=i: self.set_susp(i, 0)))
            else:
                items.append((t['name'] + '\n$%d' % t['price'], BTN if cash >= t['price'] else BTN_BAD,
                              lambda i=i, p=t['price']: self.set_susp(i, p)))
        return items

    def _pay(self, cost):
        if cost <= 0:
            self.game.sound.play('blip', 0.6)
            self.v.tuned = True
            return True
        ok = self.game.player.spend(cost)
        if ok:
            self.v.tuned = True              # saved in savegame.json with its parts, paint and parking spot
        return ok

    def set_motor(self, i, cost):
        v = self.v
        if self._pay(cost):
            v.motor_tier = i
            v.motor_owned = max(getattr(v, 'motor_owned', 0), i)
            self.game.hud.notify('Motor: %dW installed' % v.motor_tiers()[i]['watt'], rgb(120, 230, 255))
        self.rebuild()

    def set_battery(self, i, cost):
        v = self.v
        if self._pay(cost):
            v.battery_tier = i
            v.battery_owned = max(getattr(v, 'battery_owned', 0), i)
            v.recharge()
            self.game.hud.notify('Battery: %s installed (charged)' % BATTERY_TIERS[i]['name'], rgb(120, 230, 255))
        self.rebuild()

    def set_susp(self, i, cost):
        v = self.v
        if self._pay(cost):
            v.susp_tier = i
            if not hasattr(v, 'susp_owned'):
                v.susp_owned = {0}
            v.susp_owned.add(i)
            v.susp_v -= 0.8
            self.game.hud.notify('Suspension: %s' % SUSPENSION_TIERS[i]['name'], rgb(120, 230, 255))
        self.rebuild()

    def paint(self, primary, accent):
        v = self.v
        if primary is not None and primary == v.primary:
            return
        if accent is not None and accent == v.accent:
            return
        if self.game.player.spend(PAINT_PRICE):
            v.repaint(primary, accent)
            v.tuned = True
        self.rebuild()

    def on_close(self):
        self.v.frozen = False
        self.game.save_progress()


class TuningGarage:
    def __init__(self, game):
        self.game = game
        self.data = game.world.garage
        self.visited = False
        self.menu = None

    def in_zone(self, x, z):
        x0, z0, x1, z1 = self.data['zone']
        return x0 <= x <= x1 and z0 <= z <= z1

    def open(self, v):
        if self.game.menu is not None:
            return
        v.frozen = True
        v.vx = v.vz = 0.0
        if v.battery_wh < v.capacity - 1:
            v.recharge()
            self.game.hud.notify('Battery fully charged (free)', rgb(120, 230, 255))
        self.menu = TuningMenu(self.game, self, v)

    def interactions(self, player):
        v = player.vehicle
        if v is None:
            return []
        if not self.in_zone(v.x, v.z):
            return []
        if isinstance(v, TwoWheeler):
            return [dict(key='q', text='Open the tuning menu', dist=0.5, action=lambda: self.open(v))]
        return [dict(key=None, text='This garage only tunes E-Scooters and E-Motorbikes', dist=0.5, action=None)]

    def update(self, dt):
        v = self.game.player.vehicle
        if v is None or not self.in_zone(v.x, v.z):
            self.visited = False
            return
        if isinstance(v, TwoWheeler) and not self.visited and v.speed < 4.0:
            self.visited = True
            self.open(v)


# =================================================================== dealer stand
class DealerStand:
    def __init__(self, game):
        self.game = game
        self.data = game.world.dealer

    def interactions(self, player):
        if player.vehicle is not None or player.state != 'foot':
            return []
        x, _, z = self.data['pos']
        d = math.hypot(player.pos.x - x, player.pos.z - z)
        if d > 2.8:
            return []
        if self.game.wanted.level > 0:
            return [dict(key=None, text='Dealer: "Not while the cops are on you!"', dist=d, action=None)]
        return [dict(key='e', text='Buy fireworks', dist=d, action=lambda: DealerMenu(self.game))]


# =================================================================== side activities
def _beacon(col, radius=1.4, height=14.0):
    """Tall glowing column marker (additive, see-through)."""
    mb = MeshBuilder()
    mb.cylinder((0, height / 2, 0), radius, height, Color(1, 1, 1, 1), seg=16, caps=False)
    e = mb.entity(emissive=1.0, transparent=True)
    e.setDepthWrite(False)
    e.setAttrib(ColorBlendAttrib.make(ColorBlendAttrib.MAdd, ColorBlendAttrib.OIncomingAlpha, ColorBlendAttrib.OOne))
    e.color = Color(col[0], col[1], col[2], 0.35)
    return e


def _ring_entity(radius=3.6, thick=0.35):
    """Vertical glowing checkpoint ring (faces local +z)."""
    mb = MeshBuilder()
    n = 28
    pts = [(math.cos(2 * math.pi * k / n) * radius, radius + 0.4 + math.sin(2 * math.pi * k / n) * radius, 0.0) for k in range(n)]
    for k in range(n):
        mb.beam(pts[k], pts[(k + 1) % n], thick, thick, Color(1, 1, 1, 1))
    e = mb.entity(emissive=1.0, transparent=True)
    e.setAttrib(ColorBlendAttrib.make(ColorBlendAttrib.MAdd, ColorBlendAttrib.OIncomingAlpha, ColorBlendAttrib.OOne))
    return e


class CourierJobs:
    """Pick up a package at the green beacon and deliver it to the yellow one before the timer runs out."""

    def __init__(self, game):
        self.game = game
        self.state = 'pickup'
        self.cooldown = 0.0
        self.timer = 0.0
        self.reward = 0
        self.pickup = None
        self.target = None
        self.beacon = _beacon((0.2, 1.0, 0.35))
        self.box = MeshBuilder()
        self.box.box((0, 0, 0), (0.5, 0.4, 0.5), rgb(170, 120, 70), bottom=True)
        self.box.box((0, 0, 0), (0.52, 0.06, 0.52), rgb(240, 200, 60), bottom=True)
        self.box = self.box.entity()
        self.spin = 0.0
        self.completed = 0
        self._new_pickup()

    def _random_spot(self, far_from=None, min_d=0.0):
        w = self.game.world
        for _ in range(60):
            i, j = random.randrange(N_BLOCKS), random.randrange(N_BLOCKS)
            c = w.sidewalk_corners(i, j, 1.6)
            a = random.randrange(4)
            p0 = c[a]
            p1 = c[(a + 1) % 4]
            t = random.uniform(0.25, 0.75)
            x, z = p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t
            if w.collision.inside(x, CURB_H + 0.9, z, 0.5):
                continue
            if far_from is not None and math.hypot(x - far_from[0], z - far_from[1]) < min_d:
                continue
            return (x, w.ground_height(x, z), z)
        return (0.0, CURB_H, 0.0)

    def _new_pickup(self):
        pp = self.game.world.player_spawn
        self.pickup = self._random_spot((pp[0], pp[2]), 25)
        self.state = 'pickup'
        self.beacon.position = self.pickup
        self.beacon.color = Color(0.2, 1.0, 0.35, 0.35)
        self.beacon.enabled = True
        self.box.enabled = True

    def status(self):
        if self.state == 'deliver':
            return 'COURIER: deliver the package to the yellow beacon   %ds   $%d' % (max(0, self.timer), self.reward)
        return None

    def marker(self):
        if self.state == 'deliver':
            return (self.target[0], self.target[2], 'deliver')
        if self.state == 'pickup':
            return (self.pickup[0], self.pickup[2], 'pickup')
        return None

    def update(self, dt):
        g = self.game
        pl = g.player
        pp = pl.pos
        self.spin += dt * 90
        if self.state == 'cooldown':
            self.cooldown -= dt
            if self.cooldown <= 0:
                self._new_pickup()
            return
        if self.state == 'pickup':
            x, y, z = self.pickup
            self.box.position = (x, y + 1.3 + math.sin(self.spin * 0.05) * 0.2, z)
            self.box.rotation_y = self.spin
            if pl.state in ('foot', 'vehicle') and math.hypot(pp.x - x, pp.z - z) < 2.8:
                self.target = self._random_spot((x, z), 120)
                d = math.hypot(self.target[0] - x, self.target[2] - z)
                self.timer = d / 8.5 + 18.0
                self.reward = int(120 + d * 2.2)
                self.state = 'deliver'
                self.box.enabled = False
                self.beacon.position = self.target
                self.beacon.color = Color(1.0, 0.85, 0.15, 0.35)
                g.sound.play('buy', 0.6)
                g.hud.notify('Package picked up!  Deliver it within %ds for $%d' % (self.timer, self.reward), rgb(255, 230, 90))
        elif self.state == 'deliver':
            self.timer -= dt
            x, y, z = self.target
            if math.hypot(pp.x - x, pp.z - z) < 3.2 and pl.state in ('foot', 'vehicle'):
                bonus = int(self.timer * 4)
                self.completed += 1
                pl.add_cash(self.reward + bonus, 'DELIVERY')
                g.hud.notify('Delivered!  $%d  (+$%d time bonus)' % (self.reward, bonus), rgb(120, 255, 140))
                self._finish(6.0)
            elif self.timer <= 0:
                g.hud.notify('Delivery failed - too slow!', rgb(255, 90, 90))
                g.sound.play('error', 0.6)
                self._finish(8.0)
            if pl.state in ('dead', 'busted'):
                self._finish(8.0)
        if self.beacon.enabled:
            p = self.beacon.position
            if math.hypot(p[0] - pp.x, p[2] - pp.z) < 70:
                g.world.lights.add((p[0], p[1] + 2.0, p[2]), (0.4, 1.2, 0.5) if self.state == 'pickup' else (1.4, 1.1, 0.3), 9.0)

    def _finish(self, cd):
        self.state = 'cooldown'
        self.cooldown = cd
        self.beacon.enabled = False
        self.box.enabled = False


# race routes follow the road grid (consecutive nodes share a row or column)
RACES = [
    dict(name='Outer Ring Sprint', prize=900,
         route=[(0, 0), (5, 0), (5, 5), (0, 5), (0, 0)]),
    dict(name='City Loop', prize=700,
         route=[(1, 1), (4, 1), (4, 4), (1, 4), (1, 2), (3, 2), (3, 3), (2, 3), (2, 1)]),
]


class TimeTrials:
    """Drive into a blue start beacon (in any vehicle), then hit every glowing ring before time runs out."""

    def __init__(self, game):
        self.game = game
        self.w = game.world
        self.active = None
        self.cooldown = 0.0
        self.starts = []
        for r in RACES:
            pts = self._expand(r['route'])
            x, z = pts[0]
            b = _beacon((0.3, 0.6, 1.0), 2.2, 18.0)
            b.position = (x + 3.0, 0, z + 3.0)
            self.starts.append(dict(race=r, pts=pts, beacon=b, pos=(x + 3.0, z + 3.0)))
        self.rings = [_ring_entity() for _ in range(2)]
        for e in self.rings:
            e.enabled = False
        self.best = {}

    def _expand(self, route):
        w = self.w
        out = [w.node_pos(*route[0])]
        for a, b in zip(route, route[1:]):
            di = (b[0] > a[0]) - (b[0] < a[0])
            dj = (b[1] > a[1]) - (b[1] < a[1])
            i, j = a
            while (i, j) != tuple(b):
                i += di
                j += dj
                out.append(w.node_pos(i, j))
        return out

    def status(self):
        if self.active is None:
            return None
        a = self.active
        return 'TIME TRIAL %s:  ring %d / %d   %.1fs' % (a['race']['name'], a['idx'], len(a['pts']) - 1, max(0.0, a['timer']))

    def marker(self):
        if self.active is not None:
            x, z = self.active['pts'][self.active['idx']]
            return (x, z, 'ring')
        return None

    def start_positions(self):
        return [s['pos'] for s in self.starts]

    def _place_rings(self):
        a = self.active
        pts = a['pts']
        for k, e in enumerate(self.rings):
            i = a['idx'] + k
            if i < len(pts):
                x, z = pts[i]
                px, pz = pts[i - 1]
                e.enabled = True
                e.position = (x, 0, z)
                e.rotation_y = yaw_towards(x - px, z - pz)
                e.color = Color(0.2, 0.9, 1.0, 0.85) if k == 0 else Color(0.2, 0.5, 1.0, 0.25)
            else:
                e.enabled = False

    def update(self, dt):
        g = self.game
        pl = g.player
        v = pl.vehicle
        self.cooldown = max(0.0, self.cooldown - dt)
        if self.active is None:
            for st in self.starts:
                st['beacon'].enabled = True
                if v is not None and self.cooldown <= 0 and g.menu is None:
                    if math.hypot(v.x - st['pos'][0], v.z - st['pos'][1]) < 5.0:
                        pts = st['pts']
                        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
                        self.active = dict(race=st['race'], pts=pts, idx=1, timer=length / 13.0 + 8.0, t=0.0)
                        for s2 in self.starts:
                            s2['beacon'].enabled = False
                        self._place_rings()
                        g.sound.play('buy', 0.8, 1.3)
                        g.hud.notify('TIME TRIAL: %s - %d rings, %.0f seconds. GO!' % (
                            st['race']['name'], len(pts) - 1, self.active['timer']), rgb(120, 220, 255))
                        break
            return
        a = self.active
        a['timer'] -= dt
        a['t'] += dt
        x, z = a['pts'][a['idx']]
        if v is not None and math.hypot(v.x - x, v.z - z) < 6.0:
            a['idx'] += 1
            g.sound.play('blip', 0.8, 1.0 + a['idx'] * 0.03)
            if a['idx'] >= len(a['pts']):
                left = a['timer']
                cash = int(a['race']['prize'] + left * 15)
                name = a['race']['name']
                rec = self.best.get(name)
                if rec is None or a['t'] < rec:
                    self.best[name] = a['t']
                    cash += 250
                    g.hud.notify('NEW RECORD %.1fs on %s! (+$250)' % (a['t'], name), rgb(255, 220, 80))
                pl.add_cash(cash, 'TIME TRIAL')
                g.hud.notify('Finished %s in %.1fs  =  $%d' % (name, a['t'], cash), rgb(120, 255, 140))
                self._stop(15.0)
                return
            self._place_rings()
            a['timer'] += 1.5
        if a['timer'] <= 0 or v is None:
            g.hud.notify('Time trial failed%s' % ('' if v is not None else ' - you left the vehicle'), rgb(255, 90, 90))
            g.sound.play('error', 0.6)
            self._stop(6.0)
            return
        g.world.lights.add((x, 3.5, z), (0.4, 1.2, 1.6), 12.0)

    def _stop(self, cd):
        self.active = None
        self.cooldown = cd
        for e in self.rings:
            e.enabled = False


class Activities:
    def __init__(self, game):
        self.courier = CourierJobs(game)
        self.trials = TimeTrials(game)

    def status(self):
        return self.trials.status() or self.courier.status()

    def markers(self):
        return [m for m in (self.courier.marker(), self.trials.marker()) if m is not None]

    def update(self, dt):
        self.courier.update(dt)
        self.trials.update(dt)


# =================================================================== aggregator
class ShopSystem:
    def __init__(self, game):
        self.game = game
        self.robbery = RobberySystem(game)
        self.business = BusinessSystem(game)
        self.tuning = TuningGarage(game)
        self.dealer = DealerStand(game)
        self.activities = Activities(game)

    def interactions(self, player):
        out = []
        for s in (self.robbery, self.business, self.tuning, self.dealer):
            out += s.interactions(player)
        return out

    def update(self, dt):
        self.robbery.update(dt)
        self.business.update(dt)
        self.tuning.update(dt)
        self.activities.update(dt)

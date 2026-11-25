"""
npcs.py  -  pedestrians, traffic, police and the wanted level
===============================================================

* Humanoid: procedural low-poly person with a swinging-limb walk/run cycle
  and poses (hands up, cower, seated, knocked down)
* Pedestrians walk loops around the sidewalks, cross at the zebra crossings,
  flee from crimes / explosions, get knocked over by cars and fireworks
  and get back up again
* Shop clerks and the fireworks dealer
* Traffic: NPC drivers follow the road graph on the right-hand lane,
  pick random turns, brake for cars / people in front, honk, unstick themselves
* Police: chase you with sirens and drifting turns, can box you in -> BUSTED
* WantedSystem: stars, alert timer that only counts down while no cop is near
"""
from ursina import *
import math
import random
from world import (Color, MeshBuilder, rgb, col_mul, clampf, lerp_angle, wrap_angle, yaw_towards, heading_vectors,
                   ROADS, CELL, N_BLOCKS, LANE_OFFSET, CURB_H, BOUNDARY)

SKIN = [rgb(244, 208, 178), rgb(226, 180, 146), rgb(196, 146, 108), rgb(150, 104, 72), rgb(104, 70, 48), rgb(74, 50, 36)]
HAIR = [rgb(30, 24, 20), rgb(70, 46, 30), rgb(150, 110, 60), rgb(220, 190, 120), rgb(120, 120, 120), rgb(160, 60, 30)]
SHIRTS = [rgb(200, 50, 50), rgb(40, 90, 170), rgb(240, 240, 240), rgb(40, 40, 44), rgb(70, 150, 80), rgb(240, 180, 40),
          rgb(150, 70, 160), rgb(250, 130, 60), rgb(90, 160, 200), rgb(220, 120, 160)]
PANTS = [rgb(40, 50, 80), rgb(30, 30, 34), rgb(90, 80, 60), rgb(60, 60, 64), rgb(120, 100, 70), rgb(50, 70, 110)]
SHOES = [rgb(20, 20, 22), rgb(240, 240, 240), rgb(90, 50, 30), rgb(30, 60, 140)]


# ================================================================== humanoid
class Humanoid:
    def __init__(self, shirt=None, pants=None, skin=None, hair=None, shoes=None, cap=None, parent=None):
        shirt = shirt or random.choice(SHIRTS)
        pants = pants or random.choice(PANTS)
        skin = skin or random.choice(SKIN)
        hair = hair or random.choice(HAIR)
        shoes = shoes or random.choice(SHOES)
        self.root = Entity(parent=parent if parent is not None else scene)
        style = random.random()
        sleeves_long = random.random() < 0.4
        hood = random.random() < 0.18 and cap is None
        hair_style = random.choice(('short', 'short', 'long', 'bun', 'buzz', 'curly'))
        up = MeshBuilder()
        # hips + belt
        up.hexa([(-0.17, 0.86, -0.1), (0.17, 0.86, -0.1), (0.17, 0.86, 0.1), (-0.17, 0.86, 0.1),
                 (-0.18, 1.06, -0.11), (0.18, 1.06, -0.11), (0.18, 1.06, 0.11), (-0.18, 1.06, 0.11)], pants, bottom=True)
        up.box((0, 1.04, 0), (0.37, 0.05, 0.23), rgb(30, 24, 20))
        up.box((0, 1.04, 0.117), (0.05, 0.04, 0.01), rgb(190, 170, 90))
        # torso: narrow waist, broad chest, sloped shoulders (lofted)
        def ring(y, hw, hd, inset=0.0):
            return [(-hw, y, -hd), (hw, y, -hd), (hw, y, hd), (-hw, y, hd)]
        rings = [ring(1.06, 0.175, 0.105), ring(1.22, 0.17, 0.11), ring(1.36, 0.205, 0.125), ring(1.44, 0.225, 0.12),
                 ring(1.5, 0.16, 0.1)]
        from vehicles import loft
        loft(up, rings, shirt)
        if style < 0.3:                                       # open jacket over a t-shirt
            inner = random.choice((rgb(240, 240, 240), rgb(30, 30, 34), rgb(180, 40, 40)))
            up.box((0, 1.27, 0.122), (0.12, 0.38, 0.012), inner)
            for sd in (-1, 1):
                up.box((sd * 0.07, 1.4, 0.128), (0.05, 0.12, 0.01), col_mul(shirt, 0.75))
        elif style < 0.5:                                     # chest stripe / print
            up.box((0, 1.3, 0.125), (0.36, 0.06, 0.01), random.choice((rgb(240, 240, 240), rgb(240, 200, 40), rgb(30, 30, 34))))
        if hood:
            up.sphere((0, 1.5, -0.12), 0.13, col_mul(shirt, 0.9), 4, 8, squash=(1.3, 0.6, 0.8))
        # neck + head
        up.cylinder((0, 1.535, 0), 0.055, 0.09, skin, seg=8)
        up.sphere((0, 1.665, 0.005), 0.12, skin, 6, 10, squash=(0.9, 1.08, 1.0))
        up.box((0, 1.6, 0.06), (0.15, 0.06, 0.08), skin)                                    # jaw
        for sd in (-1, 1):
            up.box((sd * 0.112, 1.66, -0.005), (0.025, 0.05, 0.04), col_mul(skin, 0.95))     # ears
            up.box((sd * 0.044, 1.688, 0.108), (0.034, 0.018, 0.008), rgb(245, 245, 245))   # eye white
            up.box((sd * 0.044, 1.688, 0.112), (0.016, 0.018, 0.006), rgb(30, 26, 22))      # pupil
            up.box((sd * 0.046, 1.716, 0.108), (0.042, 0.01, 0.01), col_mul(hair, 0.9))      # eyebrow
        up.hexa([(-0.014, 1.64, 0.112), (0.014, 1.64, 0.112), (0.014, 1.64, 0.125), (-0.014, 1.64, 0.125),
                 (-0.01, 1.68, 0.112), (0.01, 1.68, 0.112), (0.006, 1.68, 0.116), (-0.006, 1.68, 0.116)], col_mul(skin, 0.94))
        up.box((0, 1.615, 0.106), (0.05, 0.008, 0.01), col_mul(skin, 0.7))                   # mouth
        if cap is not None:
            up.sphere((0, 1.735, -0.005), 0.128, cap, 4, 10, squash=(1.0, 0.55, 1.05))
            up.box((0, 1.735, 0.14), (0.2, 0.02, 0.13), cap)                                 # peak
        elif hair_style != 'buzz':
            up.sphere((0, 1.71, -0.012), 0.13, hair, 4, 10, squash=(1.0, 0.62, 1.05))
            up.box((0, 1.665, -0.095), (0.22, 0.13, 0.06), hair)
            if hair_style == 'long':
                up.box((0, 1.56, -0.11), (0.24, 0.26, 0.05), hair)
                for sd in (-1, 1):
                    up.box((sd * 0.115, 1.62, -0.03), (0.03, 0.18, 0.1), hair)
            elif hair_style == 'bun':
                up.sphere((0, 1.75, -0.11), 0.055, hair, 3, 7)
            elif hair_style == 'curly':
                for k in range(7):
                    a = k / 7 * 2 * math.pi
                    up.sphere((math.cos(a) * 0.1, 1.73, math.sin(a) * 0.1 - 0.01), 0.045, hair, 3, 6)
        else:
            up.sphere((0, 1.7, -0.01), 0.124, col_mul(hair, 0.8), 4, 10, squash=(1.0, 0.6, 1.04))
        self.pelvis = Entity(parent=self.root)          # moves down when the knees bend
        self.upper = up.entity(parent=self.pelvis)
        self.arms = []
        for s in (-1, 1):
            m = MeshBuilder()
            m.sphere((0, 0.0, 0), 0.07, shirt, 3, 7)                                          # shoulder
            m.cylinder((0, -0.15, 0), 0.058, 0.3, shirt, seg=8, radius_top=0.064)            # upper arm
            if sleeves_long:
                m.cylinder((0, -0.43, 0), 0.048, 0.28, shirt, seg=8, radius_top=0.056)
                m.cylinder((0, -0.56, 0), 0.05, 0.03, col_mul(shirt, 0.8), seg=8)
            else:
                m.cylinder((0, -0.43, 0), 0.042, 0.28, skin, seg=8, radius_top=0.05)
            m.box((0, -0.62, 0.01), (0.075, 0.1, 0.09), skin)                                 # hand
            m.box((-s * 0.04, -0.6, 0.04), (0.025, 0.06, 0.03), skin)                         # thumb
            self.arms.append(m.entity(parent=self.upper, position=(s * 0.27, 1.43, 0)))
        self.legs = []
        self.shins = []
        for s in (-1, 1):
            m = MeshBuilder()
            m.cylinder((0, -0.22, 0), 0.078, 0.46, pants, seg=8, radius_top=0.092)           # thigh
            thigh = m.entity(parent=self.pelvis, position=(s * 0.1, 0.9, 0))
            m = MeshBuilder()
            m.cylinder((0, -0.19, 0), 0.06, 0.4, pants, seg=8, radius_top=0.074)             # shin
            m.cylinder((0, -0.36, 0), 0.062, 0.06, col_mul(pants, 0.85), seg=8)              # hem
            m.box((0, -0.41, 0.045), (0.11, 0.1, 0.26), shoes)                                # shoe
            m.box((0, -0.455, 0.05), (0.12, 0.025, 0.28), rgb(235, 235, 230) if shoes != rgb(240, 240, 240) else rgb(40, 40, 40))
            m.box((0, -0.39, 0.16), (0.1, 0.06, 0.06), shoes)                                 # toe cap
            shin = m.entity(parent=thigh, position=(0, -0.44, 0))
            self.legs.append(thigh)
            self.shins.append(shin)
        self.phase = random.uniform(0, 6.28)
        self.pose = 'walk'
        self.throw_t = 0.0
        self.jump_mode = None          # None / 'crouch' / 'air' / 'land' (driven by the Player)
        self.jump_t = 0.0
        self.air_vy = 0.0
        self.grips = None              # hand targets (root-local) for handlebar IK

    def set_pose(self, pose):
        self.pose = pose
        if pose != 'stand_ride':
            self.grips = None

    def _legs(self, t0, s0, t1, s1, grounded=True, follow=1.0, dt=None):
        self.legs[0].rotation_x, self.shins[0].rotation_x = t0, s0
        self.legs[1].rotation_x, self.shins[1].rotation_x = t1, s1
        if grounded:
            # keep the lowest foot on the floor: drop the pelvis by how much the legs fold.
            # `follow` < 1 softens it (walking) so the head glides instead of bobbing.
            ext = max(0.44 * math.cos(math.radians(t0)) + 0.46 * math.cos(math.radians(t0 + s0)),
                      0.44 * math.cos(math.radians(t1)) + 0.46 * math.cos(math.radians(t1 + s1)))
            target = -(0.9 - ext) * follow
        else:
            target = 0.0
        if dt is None:
            self.pelvis.y = target
        else:
            self.pelvis.y += (target - self.pelvis.y) * min(1.0, dt * 8.0)

    def _arms(self, a0, a1, z0=0.0, z1=0.0):
        self.arms[0].rotation = (a0, 0, z0)
        self.arms[1].rotation = (a1, 0, z1)

    def _aim_arms(self):
        """Simple 2-axis IK: point each arm from its shoulder at its handlebar grip."""
        for i, sx in enumerate((-1, 1)):
            tx, ty, tz = self.grips[i]
            dx = tx - sx * 0.27
            dy = ty - (1.43 + self.pelvis.y + self.upper.y)
            dz = tz
            rx = -math.degrees(math.atan2(dz, -dy))
            rz = -math.degrees(math.atan2(dx, math.hypot(dy, dz)))
            self.arms[i].rotation = (rx, 0, rz)

    def animate(self, dt, speed):
        p = self.pose
        if p == 'seated':
            self._legs(-80, 80, -80, 80, grounded=False)
            self._arms(-58, -58)
            self.upper.y = 0.0
            self.upper.rotation_x = 6
            return
        if p == 'stand_ride':
            # upright on the deck: one foot forward, knees soft, hands on the grips
            self._legs(-12, 16, 8, 10)
            self.upper.y = 0.0
            self.upper.rotation_x = 0
            if self.grips:
                self._aim_arms()
            else:
                self._arms(-28, -28)
            return
        if p == 'hands_up':
            t = self.phase = self.phase + dt * 9
            self._arms(-168 + math.sin(t) * 4, -168 - math.sin(t) * 4)
            self._legs(0, 0, 0, 0)
            self.upper.y = 0.0
            self.upper.rotation_x = -2
            return
        if p == 'cower':
            self._arms(-120, -120)
            self._legs(-70, 120, -70, 120)
            self.upper.rotation_x = 30
            self.upper.y = 0.0
            return
        if self.jump_mode is not None:
            self._animate_jump(dt)
        elif speed > 0.15:
            stride = 1.25 + speed * 0.22
            self.phase += dt * speed / stride * 2 * math.pi
            amp = min(48.0, 16.0 + speed * 5.0)
            s = math.sin(self.phase) * amp
            # knee bends while the leg is behind the body (heel lifts); the pelvis follows only
            # a little and smoothly, so the head moves ~2-4 cm instead of bouncing
            run = clampf((speed - 4.5) / 3.0, 0.0, 1.0)
            self._legs(s, max(0.0, s) * 1.0 + 4, -s, max(0.0, -s) * 1.0 + 4,
                       follow=0.18 + 0.17 * run, dt=dt)
            self._arms(-s * 0.7, s * 0.7)
            self.upper.y = (math.cos(self.phase * 2.0) * 0.5 + 0.5) * (0.012 + 0.018 * run)
            self.upper.rotation_x += (min(10.0, speed * 1.2) - self.upper.rotation_x) * min(1.0, dt * 6)
        else:
            k = min(1.0, dt * 8)
            t0 = self.legs[0].rotation_x * (1 - k)
            t1 = self.legs[1].rotation_x * (1 - k)
            self._legs(t0, self.shins[0].rotation_x * (1 - k), t1, self.shins[1].rotation_x * (1 - k))
            for e in self.arms:
                e.rotation = (e.rotation_x * (1 - k), 0, 0)
            self.phase += dt * 1.5
            self.upper.y = math.sin(self.phase) * 0.006
            self.upper.rotation_x += (0 - self.upper.rotation_x) * k
        if self.throw_t > 0:
            self.throw_t -= dt
            t = 1.0 - self.throw_t / 0.45
            self.arms[1].rotation_x = -160 + 200 * t if t > 0.35 else -160 * (t / 0.35)

    def _animate_jump(self, dt):
        m, t = self.jump_mode, self.jump_t
        if m == 'crouch':                         # anticipation: sink down, arms swing back
            k = min(1.0, t / 0.12)
            a = 34 * k
            self._legs(-a, 2 * a, -a, 2 * a)
            self._arms(28 * k, 28 * k)
            self.upper.rotation_x = 16 * k
            self.upper.y = 0.0
        elif m == 'air':                          # tuck the knees up, arms rise while going up
            up = clampf(self.air_vy / 6.0, -1.0, 1.0)
            tuck = 0.55 + 0.45 * (1.0 - abs(up))
            self._legs(-48 * tuck, 75 * tuck, -22 * tuck, 45 * tuck, grounded=False)
            arm = -60 - 80 * max(0.0, up)
            self._arms(arm, arm, -12, 12)
            self.upper.rotation_x = 6 - 8 * up
            self.upper.y = 0.0
        else:                                     # landing: absorb with the knees, recover
            k = max(0.0, 1.0 - t / 0.3)
            a = 42 * math.sin(k * math.pi * 0.5)
            self._legs(-a, 2 * a, -a, 2 * a)
            self._arms(-30 * k, -30 * k)
            self.upper.rotation_x = 20 * k
            self.upper.y = 0.0

    def throw(self):
        self.throw_t = 0.45

    def set_visible(self, v):
        self.root.enabled = v

    def destroy(self):
        destroy(self.root)


# ================================================================== pedestrians
CROSS = {1: (((1, 0), 0), ((0, -1), 2)), 2: (((1, 0), 3), ((0, 1), 1)),
         0: (((-1, 0), 1), ((0, -1), 3)), 3: (((-1, 0), 2), ((0, 1), 0))}


class Pedestrian:
    RADIUS = 0.3

    def __init__(self, mgr, lot, corner, dirn=1, x=None, z=None):
        self.mgr = mgr
        self.world = mgr.world
        self.h = Humanoid()
        self.lot = lot
        self.corner = corner
        self.dirn = dirn
        self.inset = 1.9 + random.uniform(0.0, 0.55)
        c = self._corner_pos(lot, corner)
        self.x, self.z = (c if x is None else (x, z))
        self.y = self.world.ground_height(self.x, self.z)
        self.yaw = 0.0
        self.walk_speed = random.uniform(1.15, 1.6)
        self.state = 'walk'
        self.target = self._corner_pos(lot, (corner + dirn) % 4)
        self.corner = (corner + dirn) % 4
        self.timer = 0.0
        self.vx = self.vy = self.vz = 0.0
        self.flee_dir = (0.0, 0.0)
        self.speed = 0.0
        self.fall = 0.0
        self.idle_t = 0.0

    def _corner_pos(self, lot, corner):
        return self.world.sidewalk_corners(lot[0], lot[1], self.inset)[corner]

    @property
    def pos(self):
        return Vec3(self.x, self.y, self.z)

    # ---- reactions
    def flee(self, src, duration):
        if self.state in ('down', 'getup'):
            return
        if self.state != 'flee':
            dx, dz = self.x - src[0], self.z - src[2]
            d = math.hypot(dx, dz) or 1.0
            self.flee_dir = (dx / d, dz / d)
        self.flee_src = src
        self.state = 'flee'
        self.timer = max(self.timer, duration)
        self.h.set_pose('walk')

    def knock(self, vx, vy, vz):
        self.state = 'down'
        self.vx, self.vy, self.vz = vx, vy, vz
        self.timer = random.uniform(2.2, 3.4)
        self.h.set_pose('walk')

    def _resume_walk(self):
        i = int(clampf((self.x - ROADS[0]) // CELL, 0, N_BLOCKS - 1))
        j = int(clampf((self.z - ROADS[0]) // CELL, 0, N_BLOCKS - 1))
        self.lot = (i, j)
        corners = self.world.sidewalk_corners(i, j, self.inset)
        k = min(range(4), key=lambda q: (corners[q][0] - self.x) ** 2 + (corners[q][1] - self.z) ** 2)
        self.corner = k
        self.target = corners[k]
        self.state = 'walk'

    # ---- per frame
    def update(self, dt, animate):
        w = self.world
        st = self.state
        moved = 0.0
        if st in ('walk', 'cross'):
            tx, tz = self.target
            dx, dz = tx - self.x, tz - self.z
            d = math.hypot(dx, dz)
            if self.idle_t > 0:
                self.idle_t -= dt
                self.speed = 0.0
            elif d < 0.35:
                self._arrive()
            else:
                sp = self.walk_speed * (1.35 if st == 'cross' else 1.0)
                step = min(d, sp * dt)
                self.x += dx / d * step
                self.z += dz / d * step
                self.speed = sp
                self.yaw = lerp_angle(self.yaw, yaw_towards(dx, dz), min(1.0, dt * 8))
                moved = step
        elif st == 'flee':
            self.timer -= dt
            src = self.flee_src
            ax, az = self.x - src[0], self.z - src[2]
            d = math.hypot(ax, az) or 1.0
            fx = self.flee_dir[0] * 0.92 + ax / d * 0.08
            fz = self.flee_dir[1] * 0.92 + az / d * 0.08
            l = math.hypot(fx, fz) or 1.0
            self.flee_dir = (fx / l, fz / l)
            sp = 5.0
            self.x += self.flee_dir[0] * sp * dt
            self.z += self.flee_dir[1] * sp * dt
            self.speed = sp
            self.yaw = lerp_angle(self.yaw, yaw_towards(*self.flee_dir), min(1.0, dt * 10))
            if abs(self.x) > BOUNDARY - 3 or abs(self.z) > BOUNDARY - 3:
                self.flee_dir = (-self.flee_dir[0], -self.flee_dir[1])
            if self.timer <= 0:
                self._resume_walk()
        elif st == 'down':
            self.timer -= dt
            self.vy -= 18.0 * dt
            self.x += self.vx * dt
            self.z += self.vz * dt
            self.y += self.vy * dt
            gh = w.ground_height(self.x, self.z)
            if self.y <= gh:
                self.y = gh
                self.vy = 0.0
                f = max(0.0, 1.0 - 6.0 * dt)
                self.vx *= f
                self.vz *= f
            self.fall = min(1.0, self.fall + dt * 4.0)
            self.speed = 0.0
            if self.timer <= 0:
                self.state = 'getup'
                self.timer = 0.7
        elif st == 'getup':
            self.timer -= dt
            self.fall = max(0.0, self.timer / 0.7)
            if self.timer <= 0:
                self.fall = 0.0
                self.flee((self.x + random.uniform(-1, 1), 0, self.z + random.uniform(-1, 1)), 6.0)
        # collisions with buildings (not while calmly walking the sidewalk path)
        if st in ('flee', 'down', 'getup'):
            nx, nz, n = w.collision.resolve_circle(self.x, self.z, self.RADIUS, self.y + 0.1, self.y + 1.7)
            if n is not None and st == 'flee':
                dot = self.flee_dir[0] * n[0] + self.flee_dir[1] * n[1]
                if dot < 0:
                    fx, fz = self.flee_dir[0] - n[0] * dot * 1.6, self.flee_dir[1] - n[1] * dot * 1.6
                    l = math.hypot(fx, fz) or 1.0
                    side = random.choice((-1, 1)) if l < 0.3 else 0
                    if side:
                        fx, fz = -n[1] * side, n[0] * side
                        l = 1.0
                    self.flee_dir = (fx / l, fz / l)
            if n is not None and st == 'down':
                vn = self.vx * n[0] + self.vz * n[1]
                if vn < 0:
                    self.vx -= 1.4 * vn * n[0]
                    self.vz -= 1.4 * vn * n[1]
            self.x, self.z = nx, nz
        if st != 'down':
            gh = w.ground_height(self.x, self.z)
            self.y += (gh - self.y) * min(1.0, dt * 15)
        # visuals (skipped while hidden far away)
        if getattr(self, 'culled', False):
            return
        r = self.h.root
        r.position = (self.x, self.y + 0.12 * self.fall, self.z)
        r.rotation_y = self.yaw
        r.rotation_x = -85.0 * self.fall
        if animate:
            self.h.animate(dt, self.speed if st != 'down' else 0.0)
        if moved > 0 and animate and self.mgr.game.sound.enabled:
            pass

    def _arrive(self):
        if self.state == 'cross':
            self.state = 'walk'
            self.corner = (self.corner + self.dirn) % 4
            self.target = self._corner_pos(self.lot, self.corner)
            return
        if random.random() < 0.08:
            self.idle_t = random.uniform(1.0, 4.0)
        options = []
        for (di, dj), nc in CROSS[self.corner]:
            ni, nj = self.lot[0] + di, self.lot[1] + dj
            if 0 <= ni < N_BLOCKS and 0 <= nj < N_BLOCKS:
                options.append(((ni, nj), nc))
        if options and random.random() < 0.28:
            lot, nc = random.choice(options)
            self.lot = lot
            self.corner = nc
            self.target = self._corner_pos(lot, nc)
            self.state = 'cross'
        else:
            if random.random() < 0.06:
                self.dirn = -self.dirn
            self.corner = (self.corner + self.dirn) % 4
            self.target = self._corner_pos(self.lot, self.corner)


class StaticNPC:
    """Shop clerk or the fireworks dealer."""

    def __init__(self, pos, yaw, **colors):
        self.h = Humanoid(**colors)
        self.h.root.position = pos
        self.h.root.rotation_y = yaw
        self.h.set_pose('idle')
        self.state = 'idle'
        self.timer = 0.0

    def update(self, dt):
        if self.timer > 0:
            self.timer -= dt
            if self.timer <= 0:
                self.state = 'idle'
                self.h.set_pose('idle')
        self.h.animate(dt, 0.0)

    def set_state(self, state, duration=0.0):
        self.state = state
        self.h.set_pose(state if state in ('hands_up', 'cower') else 'idle')
        self.timer = duration


class PedManager:
    def __init__(self, game, count=30):
        self.game = game
        self.world = game.world
        self.peds = []
        self.cull_dist = 120.0
        self.max_peds = count + 8
        for _ in range(count):
            lot = (random.randrange(N_BLOCKS), random.randrange(N_BLOCKS))
            p = Pedestrian(self, lot, random.randrange(4), random.choice((-1, 1)))
            # spread them along the edge
            t = random.random()
            nxt = p.target
            p.x = p.x + (nxt[0] - p.x) * t
            p.z = p.z + (nxt[1] - p.z) * t
            self.peds.append(p)
        self.clerks = []
        for shop in self.world.shops:
            npc = StaticNPC(shop['clerk'], shop['clerk_yaw'], shirt=rgb(40, 140, 70) if shop['kind'] == 'convenience'
                            else rgb(30, 80, 200) if shop['kind'] == 'electronics' else rgb(30, 30, 34))
            self.clerks.append(npc)
        d = self.world.dealer
        self.dealer = StaticNPC(d['npc'], d['npc_yaw'], shirt=rgb(30, 30, 34), cap=rgb(200, 30, 30), pants=rgb(30, 30, 34))

    def alarm(self, pos, radius, duration=7.0):
        r2 = radius * radius
        for p in self.peds:
            if (p.x - pos[0]) ** 2 + (p.z - pos[2]) ** 2 < r2:
                p.flee(pos, duration * random.uniform(0.8, 1.3))

    def knockback(self, pos, radius, force):
        for p in self.peds:
            dx, dz = p.x - pos[0], p.z - pos[2]
            d = math.hypot(dx, dz)
            if d < radius:
                k = force * (1.0 - d / radius)
                d = d or 0.1
                p.knock(dx / d * k, 3.0 + k * 0.5, dz / d * k)

    def spawn_fleeing(self, x, z, src):
        i = int(clampf((x - ROADS[0]) // CELL, 0, N_BLOCKS - 1))
        j = int(clampf((z - ROADS[0]) // CELL, 0, N_BLOCKS - 1))
        p = Pedestrian(self, (i, j), 0, 1, x, z)
        p.flee(src, 8.0)
        self.peds.append(p)
        if len(self.peds) > self.max_peds:
            cam = camera.world_position
            far = max(self.peds, key=lambda q: (q.x - cam.x) ** 2 + (q.z - cam.z) ** 2)
            far.h.destroy()
            self.peds.remove(far)
        return p

    def update(self, dt):
        cam = camera.world_position
        game = self.game
        player = game.player
        cd2 = self.cull_dist * self.cull_dist
        ad2 = min(95.0, self.cull_dist * 0.75) ** 2
        for p in self.peds:
            d2 = (p.x - cam.x) ** 2 + (p.z - cam.z) ** 2
            far = d2 > cd2
            if far != getattr(p, 'culled', False):
                p.culled = far
                p.h.root.enabled = not far
            p.update(dt, d2 < ad2)
        for c in self.clerks:
            c.update(dt)
        self.dealer.update(dt)
        # vehicles hitting pedestrians
        for v in game.vehicles.list:
            sp = v.speed
            if sp < 3.0:
                continue
            for p in self.peds:
                if p.state == 'down' or abs(p.x - v.x) > 4 or abs(p.z - v.z) > 4:
                    continue
                for (cx, cz) in v.circles():
                    if (p.x - cx) ** 2 + (p.z - cz) ** 2 < (v.radius + Pedestrian.RADIUS) ** 2:
                        p.knock(v.vx * 0.75 + random.uniform(-1, 1), 3.0 + sp * 0.18, v.vz * 0.75 + random.uniform(-1, 1))
                        v.vx *= 0.9
                        v.vz *= 0.9
                        game.sound.play('thud', 0.6, 1.2, (p.x, 1, p.z))
                        if v.driver == 'player':
                            self.alarm((p.x, 0, p.z), 26.0)
                            game.wanted.report(1, 'Hit-and-run')
                            game.camera_rig.shake(0.25)
                        break
        # people step aside for the player on foot
        if player.vehicle is None:
            for p in self.peds:
                if p.state in ('walk', 'cross'):
                    dx, dz = p.x - player.pos.x, p.z - player.pos.z
                    d2 = dx * dx + dz * dz
                    if 1e-6 < d2 < 0.42:
                        d = math.sqrt(d2)
                        p.x += dx / d * (0.65 - d) * 0.5
                        p.z += dz / d * (0.65 - d) * 0.5


# ================================================================== traffic
def lane_points(world, a, b):
    ax, az = world.node_pos(*a)
    bx, bz = world.node_pos(*b)
    dx, dz = bx - ax, bz - az
    l = math.hypot(dx, dz)
    dx, dz = dx / l, dz / l
    rx, rz = dz, -dx
    entry = (ax + dx * 9.5 + rx * LANE_OFFSET, az + dz * 9.5 + rz * LANE_OFFSET)
    exitp = (bx - dx * 9.5 + rx * LANE_OFFSET, bz - dz * 9.5 + rz * LANE_OFFSET)
    return entry, exitp, (dx, dz)


class TrafficDriver:
    siren = False

    def __init__(self, mgr, car, a, b):
        self.mgr = mgr
        self.game = mgr.game
        self.world = mgr.world
        self.car = car
        car.ai = self
        car.driver = 'npc'
        car.set_npc_driver(True)
        self.a, self.b = a, b
        self.nxt = None
        self.phase = 'seg'
        self.target = lane_points(self.world, a, b)[1]
        self.cruise = random.uniform(9.0, 12.5)
        self.stuck = 0.0
        self.stuck_total = 0.0
        self.reverse_t = 0.0
        self.blocked_t = 0.0
        self.honk_cd = 0.0
        self.panic = 0.0

    def obstacle_distance(self):
        car = self.car
        (fx, fz), (rx, rz) = heading_vectors(car.heading)
        best = None
        g = self.game
        for v in g.vehicles.list:
            if v is car or abs(v.x - car.x) > 20 or abs(v.z - car.z) > 20:
                continue
            dx, dz = v.x - car.x, v.z - car.z
            f = dx * fx + dz * fz
            l = dx * rx + dz * rz
            hd = abs(wrap_angle(v.heading - car.heading))
            limit = 16.0 if hd < 100 else 7.0
            if 0 < f < limit and abs(l) < (car.width + v.width) * 0.5 + 0.1:
                d = f - car.length / 2 - v.length / 2
                best = d if best is None else min(best, d)
        for p in g.npcs.peds:
            if abs(p.x - car.x) > 14 or abs(p.z - car.z) > 14:
                continue
            dx, dz = p.x - car.x, p.z - car.z
            f = dx * fx + dz * fz
            l = dx * rx + dz * rz
            if 0 < f < 12 and abs(l) < 1.6:
                d = f - car.length / 2
                best = d if best is None else min(best, d)
        pl = g.player
        if pl.vehicle is None:
            dx, dz = pl.pos.x - car.x, pl.pos.z - car.z
            f = dx * fx + dz * fz
            l = dx * rx + dz * rz
            if 0 < f < 12 and abs(l) < 1.6:
                d = f - car.length / 2
                best = d if best is None else min(best, d)
                if d < 4 and car.speed < 0.5:
                    self.blocked_t += time.dt
        return best

    def _advance(self):
        w = self.world
        if self.phase == 'seg':
            opts = [n for n in w.node_neighbors(*self.b) if n != self.a]
            self.nxt = random.choice(opts) if opts else self.a
            self.phase = 'turn'
            self.target = lane_points(w, self.b, self.nxt)[0]
        else:
            self.a, self.b = self.b, self.nxt
            self.phase = 'seg'
            self.target = lane_points(w, self.a, self.b)[1]

    def update(self, dt):
        car = self.car
        tx, tz = self.target
        dist = math.hypot(tx - car.x, tz - car.z)
        if dist < 3.5:
            self._advance()
            tx, tz = self.target
            dist = math.hypot(tx - car.x, tz - car.z)
        diff = wrap_angle(yaw_towards(tx - car.x, tz - car.z) - car.heading)
        steer = clampf(diff / 28.0, -1.0, 1.0)
        target_speed = self.cruise if self.phase == 'seg' else 6.0
        if self.panic > 0:
            self.panic -= dt
            target_speed *= 1.6
        if abs(diff) > 35:
            target_speed = min(target_speed, 5.0)
        if self.phase == 'seg' and dist < 14:
            target_speed = min(target_speed, 6.5 + dist * 0.3)
        block = self.obstacle_distance()
        if block is not None:
            target_speed = min(target_speed, max(0.0, (block - 2.5) * 1.3))
        else:
            self.blocked_t = 0.0
        vl = car.vl
        thr = clampf((target_speed - vl) * 0.6, -1.0, 1.0)
        if target_speed < 0.3 and abs(vl) < 0.4:
            thr = 0.0
        car.handbrake = False
        car.horn = False
        if target_speed > 3.0 and car.speed < 0.6:
            self.stuck += dt
            self.stuck_total += dt
        else:
            self.stuck = max(0.0, self.stuck - dt)
            if car.speed > 3:
                self.stuck_total = 0.0
        if self.stuck > 2.5 and self.reverse_t <= 0:
            self.reverse_t = 1.6
            self.stuck = 0.0
        if self.reverse_t > 0:
            self.reverse_t -= dt
            thr = -0.7
            steer = -steer
        self.honk_cd -= dt
        if self.blocked_t > 2.0 and self.honk_cd <= 0:
            self.game.sound.play('horn', 0.6, 1.0, (car.x, car.y, car.z), 20)
            self.honk_cd = 3.0
            self.blocked_t = 0.0
        car.throttle = thr
        car.steer = steer
        if self.stuck_total > 9.0:
            self.mgr.request_respawn(self)


class TrafficManager:
    def __init__(self, game, count=13):
        self.game = game
        self.world = game.world
        self.count = count
        self.drivers = []
        self.spawn_cd = 0.0
        kinds = ['sedan', 'hatch', 'sedan', 'taxi', 'van', 'hatch', 'sports', 'sedan']
        tries = 0
        while len(self.drivers) < count and tries < 200:
            tries += 1
            self._spawn(random.choice(kinds), min_dist=25)

    def _random_segment(self):
        a = (random.randint(0, N_BLOCKS), random.randint(0, N_BLOCKS))
        b = random.choice(self.world.node_neighbors(*a))
        return a, b

    def _spawn(self, kind, min_dist=60):
        a, b = self._random_segment()
        entry, exitp, d = lane_points(self.world, a, b)
        t = random.uniform(0.0, 0.7)
        x = entry[0] + (exitp[0] - entry[0]) * t
        z = entry[1] + (exitp[1] - entry[1]) * t
        pp = self.game.player.pos if getattr(self.game, 'player', None) else Vec3(*self.world.player_spawn)
        if math.hypot(x - pp.x, z - pp.z) < min_dist:
            return None
        for v in self.game.vehicles.list:
            if (v.x - x) ** 2 + (v.z - z) ** 2 < 64:
                return None
        car = self.game.vehicles.spawn_car(kind, x, z, yaw_towards(*d))
        drv = TrafficDriver(self, car, a, b)
        speed = drv.cruise * 0.6
        car.vx, car.vz = d[0] * speed, d[1] * speed
        self.drivers.append(drv)
        return drv

    def on_carjacked(self, car):
        drv = car.ai
        if drv in self.drivers:
            self.drivers.remove(drv)
        car.ai = None
        car.set_npc_driver(False)
        pts = car.exit_points()
        x, z = pts[0]
        self.game.npcs.spawn_fleeing(x, z, (car.x, 0, car.z))

    def request_respawn(self, drv):
        car = drv.car
        pp = self.game.player.pos
        if math.hypot(car.x - pp.x, car.z - pp.z) < 45:
            drv.stuck_total = 0.0
            return
        if drv in self.drivers:
            self.drivers.remove(drv)
        car.ai = None
        self.game.vehicles.remove(car)

    def alarm(self, pos, radius):
        for d in self.drivers:
            if (d.car.x - pos[0]) ** 2 + (d.car.z - pos[2]) ** 2 < radius * radius:
                d.panic = 6.0

    def update(self, dt):
        self.drivers = [d for d in self.drivers if d.car.ai is d]
        self.spawn_cd -= dt
        if len(self.drivers) < self.count and self.spawn_cd <= 0:
            self.spawn_cd = 2.0
            self._spawn(random.choice(['sedan', 'hatch', 'taxi', 'van', 'sports']), min_dist=70)


# ================================================================== police
class PoliceDriver:
    siren = True

    def __init__(self, wanted, car):
        self.w = wanted
        self.game = wanted.game
        self.car = car
        car.ai = self
        car.driver = 'npc'
        car.set_npc_driver(True)
        self.mode = 'chase'
        self.stuck = 0.0
        self.reverse_t = 0.0
        self.leave_t = 0.0
        self.leave_target = None
        self.wp = None
        self.los = True
        self.los_cd = 0.0

    def _nearest_node(self, x, z):
        i = int(round(clampf((x - ROADS[0]) / CELL, 0, N_BLOCKS)))
        j = int(round(clampf((z - ROADS[0]) / CELL, 0, N_BLOCKS)))
        return (i, j)

    def _route(self, dt, tx, tz):
        """Drive straight at the target when there is line of sight, otherwise follow the road grid."""
        car = self.car
        w = self.game.world
        self.los_cd -= dt
        if self.los_cd <= 0:
            self.los_cd = 0.3
            dx, dz = tx - car.x, tz - car.z
            d = math.hypot(dx, dz)
            if d < 1.0:
                self.los = True
            else:
                t = w.collision.raycast((car.x, car.y + 1.0, car.z), (dx / d, 0.0, dz / d), d)
                self.los = t >= d - 0.5
        if self.los:
            self.wp = None
            return tx, tz
        if self.wp is None:
            self.wp = self._nearest_node(car.x, car.z)
        wx, wz = w.node_pos(*self.wp)
        if math.hypot(wx - car.x, wz - car.z) < 7.0:
            opts = w.node_neighbors(*self.wp)
            self.wp = min(opts, key=lambda n: math.hypot(w.node_pos(*n)[0] - tx, w.node_pos(*n)[1] - tz))
            wx, wz = w.node_pos(*self.wp)
        return wx, wz

    def update(self, dt):
        car = self.car
        pl = self.game.player
        if self.mode == 'chase':
            tp = pl.pos
            if pl.vehicle is not None:
                tx, tz = pl.vehicle.x + pl.vehicle.vx * 0.6, pl.vehicle.z + pl.vehicle.vz * 0.6
            else:
                tx, tz = tp.x, tp.z
        else:
            self.leave_t += dt
            if self.leave_target is None:
                self.leave_target = (random.choice(ROADS), random.choice(ROADS))
            tx, tz = self.leave_target
        dist = math.hypot(tx - car.x, tz - car.z)
        tx, tz = self._route(dt, tx, tz)
        dx, dz = tx - car.x, tz - car.z
        diff = wrap_angle(yaw_towards(dx, dz) - car.heading)
        steer = clampf(diff / 22.0, -1.0, 1.0)
        target_speed = clampf(dist * 0.9, 0.0, 36.0 if self.mode == 'chase' else 14.0)
        if not self.los:
            target_speed = min(target_speed, 22.0)
        if self.mode == 'chase' and pl.vehicle is None and dist < 5.0:
            target_speed = 0.0
        thr = clampf((target_speed - car.vl) * 0.5, -1.0, 1.0)
        car.handbrake = abs(diff) > 55 and car.speed > 12 and self.mode == 'chase'
        if abs(diff) > 115 and dist < 30:
            thr = -0.7
            steer = -math.copysign(1.0, diff)
        if target_speed > 3 and car.speed < 0.8:
            self.stuck += dt
        else:
            self.stuck = max(0.0, self.stuck - dt)
        if self.stuck > 2.0 and self.reverse_t <= 0:
            self.reverse_t = 1.3
            self.stuck = 0.0
        if self.reverse_t > 0:
            self.reverse_t -= dt
            thr = -0.8
            steer = -steer
        car.throttle = thr
        car.steer = steer
        if self.mode == 'leave':
            self.siren = False


class WantedSystem:
    MAX = 3

    def __init__(self, game):
        self.game = game
        self.level = 0
        self.timer = 0.0
        self.police = []
        self.spawn_cd = 0.0
        self.busted_t = 0.0
        self.flash = 0.0

    def duration(self):
        return 22.0 + 12.0 * self.level

    def report(self, stars, reason=''):
        new = min(self.MAX, self.level + stars) if self.level > 0 else min(self.MAX, stars)
        if new > self.level:
            self.game.hud.notify('WANTED  %s  %s' % ('*' * new, reason), rgb(255, 80, 80))
            self.flash = 1.5
        self.level = max(self.level, new)
        self.timer = self.duration()

    def clear(self):
        self.level = 0
        self.timer = 0.0
        for p in self.police:
            p.mode = 'leave'

    def police_near(self, radius=45.0):
        pp = self.game.player.pos
        for p in self.police:
            if p.mode == 'chase' and math.hypot(p.car.x - pp.x, p.car.z - pp.z) < radius:
                return True
        return False

    def _spawn_police(self):
        w = self.game.world
        pp = self.game.player.pos
        nodes = [(i, j) for i in range(N_BLOCKS + 1) for j in range(N_BLOCKS + 1)]
        random.shuffle(nodes)
        for n in nodes:
            x, z = w.node_pos(*n)
            d = math.hypot(x - pp.x, z - pp.z)
            if 65 < d < 140:
                car = self.game.vehicles.spawn_car('police', x + LANE_OFFSET, z, yaw_towards(pp.x - x, pp.z - z))
                self.police.append(PoliceDriver(self, car))
                return

    def update(self, dt):
        g = self.game
        self.flash = max(0.0, self.flash - dt)
        if self.level > 0:
            if not self.police_near():
                self.timer -= dt
                if self.timer <= 0:
                    self.level -= 1
                    if self.level == 0:
                        g.hud.notify('You lost the cops.', rgb(120, 255, 140))
                        self.clear()
                    else:
                        self.timer = self.duration()
            chasing = [p for p in self.police if p.mode == 'chase']
            self.spawn_cd -= dt
            if len(chasing) < self.level and self.spawn_cd <= 0:
                self.spawn_cd = 4.0
                self._spawn_police()
        # busted check
        pp = g.player.pos
        close = False
        for p in self.police:
            if p.mode == 'chase' and math.hypot(p.car.x - pp.x, p.car.z - pp.z) < 8.0 and p.car.speed < 4:
                close = True
        pv = g.player.vehicle
        if self.level > 0 and close and (pv is None or pv.speed < 1.5) and g.player.state in ('foot', 'vehicle'):
            self.busted_t += dt
            if self.busted_t > (2.2 if pv is None else 3.5):
                self.busted_t = 0.0
                g.player.busted()
        else:
            self.busted_t = max(0.0, self.busted_t - dt * 2)
        # remove police that drove away
        for p in list(self.police):
            far = math.hypot(p.car.x - pp.x, p.car.z - pp.z) > 110
            if p.car.ai is not p:            # carjacked by the player!
                self.police.remove(p)
                continue
            if p.mode == 'leave' and (far or p.leave_t > 25):
                self.police.remove(p)
                p.car.ai = None
                g.vehicles.remove(p.car)

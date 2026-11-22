"""
player.py  -  the player character, camera and HUD
====================================================

* walk / sprint / jump with smooth acceleration, curb stepping, collisions
* third-person over-the-shoulder camera with wall collision, V toggles a
  smooth blend into first person (on foot AND in vehicles: cockpit / handlebar)
* entering / stealing / carjacking vehicles, riding two-wheelers seated
* health, regeneration, getting knocked down, WASTED / BUSTED + respawn
* HUD: cash, health bar, wanted stars + alert timer, clock, minimap,
  interaction prompts, notifications, speedometer + EV battery/range,
  drift score, equipped firework, robbery progress, screen flashes
"""
from ursina import *
import math
import random
from world import (Color, rgb, col_mul, clampf, lerpf, lerp_angle, wrap_angle, yaw_towards, heading_vectors, smoothstep,
                   ROADS, ROAD_W, BOUNDARY, ASPHALT_MIN, ASPHALT_MAX, N_BLOCKS, CURB_H)
from npcs import Humanoid

MOUSE_SENS = 40.0


# ================================================================== player
class Player:
    RADIUS = 0.35

    def __init__(self, game):
        self.game = game
        self.world = game.world
        sx, sy, sz = self.world.player_spawn
        self.pos = Vec3(sx, sy, sz)
        self.vel_x = self.vel_z = self.vel_y = 0.0
        self.body = Humanoid(shirt=rgb(245, 245, 245), pants=rgb(40, 60, 110), skin=rgb(226, 180, 146),
                             hair=rgb(40, 30, 24), shoes=rgb(240, 240, 240), cap=rgb(30, 30, 34))
        self.yaw = 0.0
        self.health = 100.0
        self.cash = 750
        self.state = 'foot'
        self.vehicle = None
        self.on_ground = True
        self.regen_cd = 0.0
        self.timer = 0.0
        self.step_sign = 1
        self.sprinting = False
        self.h_speed = 0.0
        self.body.root.position = self.pos

    # ---- money & health
    def add_cash(self, amount, reason='', sound=True):
        amount = int(amount)
        if amount == 0:
            return
        self.cash += amount
        self.game.hud.money_popup(amount, reason)
        if sound:
            self.game.sound.play('cash', 0.7)

    def spend(self, amount):
        if self.cash < amount:
            self.game.hud.notify('Not enough cash (need $%s)' % format(int(amount), ','), rgb(255, 90, 90))
            self.game.sound.play('error', 0.6)
            return False
        self.cash -= int(amount)
        self.game.hud.money_popup(-int(amount), '')
        self.game.sound.play('buy', 0.6)
        return True

    def damage(self, amount, silent=False):
        if self.state in ('dead', 'busted'):
            return
        self.health -= amount
        self.regen_cd = 7.0
        self.game.hud.hurt(min(1.0, amount / 40.0))
        if self.health <= 0:
            self.health = 0
            self.die()

    def knock(self, vx, vy, vz):
        if self.vehicle is not None or self.state != 'foot':
            return
        self.state = 'down'
        self.timer = 1.6
        self.body.jump_mode = None
        self.vel_x, self.vel_y, self.vel_z = vx, vy, vz
        self.on_ground = False

    # ---- vehicles
    def enter_vehicle(self, v):
        g = self.game
        if v.driver == 'npc':
            if v.ai is not None and v.ai in g.traffic.drivers:
                g.traffic.on_carjacked(v)
            else:
                v.ai = None
                v.set_npc_driver(False)
            g.npcs.alarm((v.x, 0, v.z), 25.0, 7.0)
            g.wanted.report(1, 'Carjacking')
            g.hud.notify('Carjacked!', rgb(255, 160, 80))
        v.driver = 'player'
        v.ai = None
        v.wake()
        if v.is_two_wheeler:
            v.lying = False
            v.wheelie = v.wheelie_w = 0.0
        v.throttle = v.steer = 0.0
        v.handbrake = False
        self.vehicle = v
        self.state = 'vehicle'
        self.body.jump_mode = None
        self.vel_x = self.vel_z = self.vel_y = 0.0
        if v.is_two_wheeler:
            self.body.root.parent = v.seat
            self.body.root.rotation = (0, 0, 0)
            if v.standing:
                self.body.root.position = (0, 0, 0)
                self.body.set_pose('stand_ride')
            else:
                self.body.root.position = (0, -0.93, 0.05)
                self.body.set_pose('seated')
            g.hud.notify('%s  %dW  |  SHIFT = boost  |  ride into the E-Tuning garage to upgrade' % (v.display_name, v.watt),
                         rgb(120, 230, 255))
        else:
            self.body.set_visible(False)
            v.set_npc_driver(True)
            g.hud.notify('SPACE = handbrake / drift   R = reset   H = horn', rgb(200, 200, 200))
        g.camera_rig.on_enter(v)
        g.sound.play('blip', 0.4, 0.8)

    def exit_vehicle(self):
        v = self.vehicle
        if v is None:
            return
        w = self.world
        spot = None
        for (x, z) in v.exit_points():
            if not w.collision.inside(x, w.ground_height(x, z) + 0.9, z, 0.35):
                spot = (x, z)
                break
        if spot is None:
            spot = (v.x, v.z)
        speed = v.speed
        v.driver = None
        v.throttle = 0.0
        v.steer = 0.0
        v.boost = False
        v.horn = False
        v.handbrake = speed < 2.0
        v.frozen = False
        if v.is_two_wheeler:
            self.body.root.parent = scene
            self.body.root.rotation = (0, 0, 0)
        else:
            v.set_npc_driver(False)
        self.body.set_pose('walk')
        self.body.set_visible(True)
        self.pos = Vec3(spot[0], w.ground_height(*spot), spot[1])
        self.yaw = v.heading
        self.vehicle = None
        self.state = 'foot'
        self.game.camera_rig.on_exit()
        if speed > 8.0:
            self.knock(v.vx * 0.5, 2.5, v.vz * 0.5)
            self.damage(speed * 0.8)

    def crash_off_bike(self, v):
        """Thrown off backwards after looping a wheelie."""
        (fx, fz), _ = heading_vectors(v.heading)
        sp = v.speed
        self.exit_vehicle()
        self.pos = Vec3(v.x - fx * 1.1, self.pos.y, v.z - fz * 1.1)
        self.state = 'foot'
        self.knock(-fx * 3.0 + v.vx * 0.4, 3.5, -fz * 3.0 + v.vz * 0.4)
        self.damage(8.0 if sp > 8.0 else 12.0)
        self.game.camera_rig.shake(0.6)
        self.game.hud.notify('You flipped the wheelie!  Feather CTRL to hold the balance point.', rgb(255, 120, 90))

    # ---- death / arrest
    def _go_down(self, state, text, loss, fine=None):
        g = self.game
        if self.vehicle is not None:
            self.exit_vehicle()
        self.state = state
        self.timer = 4.0
        lost = int(self.cash * loss) if fine is None else min(int(self.cash), int(fine))
        self.cash -= lost
        g.hud.big_text(text, '-$%s' % format(lost, ','))
        g.wanted.clear()
        g.wanted.level = 0

    def die(self):
        self._go_down('dead', 'WASTED', 0.1)

    def busted(self):
        self._go_down('busted', 'BUSTED', 0.0, fine=random.randint(45, 55))   # small bail fee

    def respawn(self):
        sx, sy, sz = self.world.hospital_spawn
        self.pos = Vec3(sx, sy, sz)
        self.health = 100.0
        self.state = 'foot'
        self.vel_x = self.vel_y = self.vel_z = 0.0
        self.body.root.rotation = (0, 0, 0)
        self.body.set_visible(True)
        self.game.hud.fade(1.0)

    # ---- per frame
    def controls_enabled(self):
        g = self.game
        return g.menu is None and not g.fireworks.wheel.open

    def update(self, dt):
        if self.regen_cd > 0:
            self.regen_cd -= dt
        elif self.health < 100 and self.state in ('foot', 'vehicle'):
            self.health = min(100.0, self.health + 3.0 * dt)
        if self.state == 'foot':
            self._foot(dt)
        elif self.state == 'vehicle':
            self._drive(dt)
        elif self.state == 'down':
            self._down(dt)
        elif self.state in ('dead', 'busted'):
            self.timer -= dt
            r = self.body.root
            if self.state == 'dead':
                r.rotation_x += (-85 - r.rotation_x) * min(1.0, dt * 4)
            else:
                self.body.set_pose('hands_up')
                self.body.animate(dt, 0)
            if self.timer <= 0:
                self.respawn()

    def _foot(self, dt):
        g = self.game
        rig = g.camera_rig
        ctrl = self.controls_enabled()
        fwd_in = (held_keys['w'] - held_keys['s']) if ctrl else 0
        side_in = (held_keys['d'] - held_keys['a']) if ctrl else 0
        self.sprinting = bool(held_keys['left shift'] or held_keys['shift']) and ctrl
        yaw = math.radians(rig.yaw)
        fx, fz = math.sin(yaw), math.cos(yaw)
        rx, rz = math.cos(yaw), -math.sin(yaw)
        mx = fx * fwd_in + rx * side_in
        mz = fz * fwd_in + rz * side_in
        ml = math.hypot(mx, mz)
        speed = 7.6 if self.sprinting else 4.1
        if ml > 0:
            mx, mz = mx / ml * speed, mz / ml * speed
        accel = 14.0 if self.on_ground else 3.0
        k = min(1.0, accel * dt)
        self.vel_x += (mx - self.vel_x) * k
        self.vel_z += (mz - self.vel_z) * k
        # multi-phase jump: anticipation crouch -> take-off -> airborne tuck -> landing absorb
        b = self.body
        if b.jump_mode is not None:
            b.jump_t += dt
        if self.on_ground and ctrl and held_keys['space'] and b.jump_mode in (None, 'land') and self.vel_y <= 0:
            b.jump_mode, b.jump_t = 'crouch', 0.0
        if b.jump_mode == 'crouch' and b.jump_t >= 0.12:
            self.vel_y = 6.6
            self.on_ground = False
            b.jump_mode, b.jump_t = 'air', 0.0
        was_air = not self.on_ground
        self.vel_y -= 20.0 * dt
        self._move(dt)
        if not self.on_ground and b.jump_mode is None and self.vel_y < -3.0:
            b.jump_mode, b.jump_t = 'air', 0.0            # walked off a ledge / got launched
        if b.jump_mode == 'air':
            b.air_vy = self.vel_y
            if self.on_ground and was_air:
                b.jump_mode, b.jump_t = 'land', 0.0
                self.game.sound.play('step', 0.45, 0.8)
        elif b.jump_mode == 'land' and b.jump_t >= 0.3:
            b.jump_mode = None
        self.h_speed = math.hypot(self.vel_x, self.vel_z)
        aiming = g.fireworks.equipped() != 'hands' or rig.fp_t > 0.5
        if aiming:
            self.yaw = lerp_angle(self.yaw, rig.yaw, min(1.0, dt * 14))
        elif self.h_speed > 0.3:
            self.yaw = lerp_angle(self.yaw, yaw_towards(self.vel_x, self.vel_z), min(1.0, dt * 10))
        r = self.body.root
        r.position = self.pos
        r.rotation_y = self.yaw
        self.body.animate(dt, self.h_speed)
        # footsteps
        s = 1 if math.sin(self.body.phase) >= 0 else -1
        if s != self.step_sign and self.on_ground and self.h_speed > 1.0:
            g.sound.play('step', 0.25 + 0.15 * self.sprinting, random.uniform(0.85, 1.15))
        self.step_sign = s
        # getting hit by vehicles
        for v in g.vehicles.list:
            if v.speed < 5.0 or abs(v.x - self.pos.x) > 4 or abs(v.z - self.pos.z) > 4:
                continue
            for (cx, cz) in v.circles():
                if (cx - self.pos.x) ** 2 + (cz - self.pos.z) ** 2 < (v.radius + self.RADIUS) ** 2:
                    self.damage(v.speed * 2.2)
                    self.knock(v.vx * 0.7, 3.5, v.vz * 0.7)
                    g.sound.play('thud', 0.8, 1.1)
                    g.camera_rig.shake(0.5)
                    return

    def _move(self, dt):
        w = self.world
        p = self.pos
        x = p.x + self.vel_x * dt
        z = p.z + self.vel_z * dt
        y = p.y + self.vel_y * dt
        x, z, n = w.collision.resolve_circle(x, z, self.RADIUS, y + 0.3, y + 1.75)
        for v in self.game.vehicles.list:
            if abs(v.x - x) > 4 or abs(v.z - z) > 4:
                continue
            for (cx, cz) in v.circles():
                dx, dz = x - cx, z - cz
                rr = v.radius + self.RADIUS
                d2 = dx * dx + dz * dz
                if 1e-8 < d2 < rr * rr:
                    d = math.sqrt(d2)
                    x += dx / d * (rr - d)
                    z += dz / d * (rr - d)
        for pr in w.props.items:
            dx, dz = pr.x - x, pr.z - z
            if dx * dx + dz * dz < (pr.r + self.RADIUS) ** 2 and math.hypot(self.vel_x, self.vel_z) > 2.0:
                pr.push(self.vel_x * 0.6, 1.5, self.vel_z * 0.6, 150)
        x = clampf(x, -BOUNDARY + 1, BOUNDARY - 1)
        z = clampf(z, -BOUNDARY + 1, BOUNDARY - 1)
        gh = w.ground_height(x, z)
        if y <= gh + (0.25 if self.on_ground else 0.0) and self.vel_y <= 0:
            y = gh
            self.vel_y = 0.0
            self.on_ground = True
        else:
            self.on_ground = False
        self.pos = Vec3(x, y, z)

    def _down(self, dt):
        self.timer -= dt
        f = max(0.0, 1.0 - (3.0 if self.on_ground else 0.4) * dt)
        self.vel_x *= f
        self.vel_z *= f
        self.vel_y -= 20.0 * dt
        self._move(dt)
        r = self.body.root
        r.position = self.pos
        target = -80.0 if self.timer > 0.5 else 0.0
        r.rotation_x += (target - r.rotation_x) * min(1.0, dt * 8)
        if self.timer <= 0:
            r.rotation_x = 0
            self.state = 'foot'

    def _drive(self, dt):
        v = self.vehicle
        ctrl = self.controls_enabled()
        thr = (held_keys['w'] - held_keys['s']) if ctrl else 0
        steer_in = (held_keys['d'] - held_keys['a']) if ctrl else 0
        rate = 4.5 if steer_in != 0 else 7.0
        v.steer += (steer_in - v.steer) * min(1.0, dt * rate)
        v.throttle = thr
        v.handbrake = bool(held_keys['space']) and ctrl
        v.boost = bool(held_keys['left shift'] or held_keys['shift']) and ctrl
        if v.is_two_wheeler:
            v.wheelie_key = bool(held_keys['control'] or held_keys['left control'] or held_keys['right control']) and ctrl
        v.horn = bool(held_keys['h']) and ctrl
        self.pos = Vec3(v.x, v.y, v.z)
        if v.is_two_wheeler:
            if v.standing:
                self.body.grips = v.grip_targets()
            self.body.animate(dt, 0)


# ================================================================== camera
class CameraRig:
    def __init__(self, game):
        self.game = game
        self.yaw = 0.0
        self.pitch = 12.0
        self.first_person = False
        self.fp_t = 0.0
        self.shake_amt = 0.0
        self.veh_yaw = 0.0
        self.look_off = 0.0
        self.look_pitch = 10.0
        self.idle = 0.0
        self.pos = None
        self.fov = 72.0
        self.base_fov = 72.0
        self.sens = MOUSE_SENS
        camera.fov = 72
        camera.clip_plane_near = 0.12
        camera.clip_plane_far = 1100

    def toggle(self):
        self.first_person = not self.first_person
        self.game.hud.notify('First-person view' if self.first_person else 'Third-person view', rgb(200, 200, 200))

    def shake(self, a):
        self.shake_amt = min(1.6, self.shake_amt + a)

    def forward(self):
        y, p = math.radians(self.yaw), math.radians(self.pitch)
        return (math.sin(y) * math.cos(p), -math.sin(p), math.cos(y) * math.cos(p))

    def on_enter(self, v):
        self.veh_yaw = v.heading
        self.look_off = 0.0
        self.look_pitch = 10.0

    def on_exit(self):
        self.pitch = 12.0

    def _collide(self, pivot, desired):
        d = (desired[0] - pivot[0], desired[1] - pivot[1], desired[2] - pivot[2])
        dist = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
        if dist < 1e-4:
            return desired
        n = (d[0] / dist, d[1] / dist, d[2] / dist)
        t = self.game.world.collision.raycast(pivot, n, dist + 0.35)
        t = max(0.25, min(dist, t - 0.35))
        return (pivot[0] + n[0] * t, pivot[1] + n[1] * t, pivot[2] + n[2] * t)

    def update(self, dt):
        g = self.game
        pl = g.player
        look = g.menu is None and not g.fireworks.wheel.open and not g.paused
        mdx = mouse.velocity[0] * self.sens if look else 0.0
        mdy = mouse.velocity[1] * self.sens if look else 0.0
        self.fp_t += ((1.0 if self.first_person else 0.0) - self.fp_t) * min(1.0, dt * 7.0)
        e = self.fp_t * self.fp_t * (3 - 2 * self.fp_t)
        v = pl.vehicle
        if v is None:
            self.yaw = (self.yaw + mdx) % 360.0
            self.pitch = clampf(self.pitch - mdy, -70.0, 75.0)
            p = pl.body.root.world_position if pl.state in ('dead', 'busted', 'down') else pl.pos
            pivot = (p.x, p.y + 1.55, p.z)
            fwd = self.forward()
            yr = math.radians(self.yaw)
            right = (math.cos(yr), 0.0, -math.sin(yr))
            dist = 4.1 if pl.sprinting else 3.6
            sh = 0.75 * (1.0 - e)
            desired = (pivot[0] - fwd[0] * dist + right[0] * sh, pivot[1] - fwd[1] * dist + 0.15, pivot[2] - fwd[2] * dist + right[2] * sh)
            tp = self._collide(pivot, desired)
            fp = (p.x + math.sin(yr) * 0.12, p.y + 1.66, p.z + math.cos(yr) * 0.12)
            cam = tuple(tp[i] + (fp[i] - tp[i]) * e for i in range(3))
            look_dir = fwd
            target_fov = self.base_fov + (5.0 if (pl.sprinting and pl.h_speed > 5) else 0.0)
            pl.body.set_visible(e < 0.7 or pl.state in ('dead', 'busted'))
        else:
            if abs(mdx) > 0.01 or abs(mdy) > 0.01:
                self.idle = 0.0
            else:
                self.idle += dt
            self.look_off = clampf(self.look_off + mdx, -150.0, 150.0)
            self.look_pitch = clampf(self.look_pitch - mdy, -15.0, 55.0)
            if self.idle > 1.4 and e < 0.5:
                self.look_off *= max(0.0, 1.0 - dt * 2.5)
                self.look_pitch += (10.0 - self.look_pitch) * min(1.0, dt * 2.0)
            self.veh_yaw = lerp_angle(self.veh_yaw, v.heading, min(1.0, dt * 3.5))
            yaw = self.veh_yaw + self.look_off
            pitch = self.look_pitch
            yr, pr = math.radians(yaw), math.radians(pitch)
            fwd = (math.sin(yr) * math.cos(pr), -math.sin(pr), math.cos(yr) * math.cos(pr))
            two = v.is_two_wheeler
            dist = (4.3 + v.speed * 0.05) if two else (6.6 + v.speed * 0.07)
            pivot = (v.x, v.y + (1.45 if two else 1.5), v.z)
            desired = (pivot[0] - fwd[0] * dist, pivot[1] - fwd[1] * dist + 0.5, pivot[2] - fwd[2] * dist)
            tp = self._collide(pivot, desired)
            (hx, hz), (rx, rz) = heading_vectors(v.heading)
            if two:
                head = v.seat.world_position
                fp = (head.x + hx * 0.15, head.y + v.head_height, head.z + hz * 0.15)
            else:
                lx, ly, lz = v.driver_head                     # eye point of the seated driver
                ly = min(ly + 0.03, v.height - 0.14)
                fp = (v.x + rx * lx + hx * (lz + 0.08), v.y + ly + v.susp, v.z + rz * lx + hz * (lz + 0.08))
            cam = tuple(tp[i] + (fp[i] - tp[i]) * e for i in range(3))
            fp_yaw = math.radians(v.heading + clampf(self.look_off, -120, 120))
            fp_dir = (math.sin(fp_yaw) * math.cos(pr * 0.6), -math.sin(pr * 0.6) - 0.08, math.cos(fp_yaw) * math.cos(pr * 0.6))
            tp_dir = (pivot[0] + hx * 2.0 - tp[0], pivot[1] + 0.3 - tp[1], pivot[2] + hz * 2.0 - tp[2])
            l = math.sqrt(sum(c * c for c in tp_dir)) or 1.0
            tp_dir = tuple(c / l for c in tp_dir)
            look_dir = tuple(tp_dir[i] + (fp_dir[i] - tp_dir[i]) * e for i in range(3))
            self.yaw = math.degrees(math.atan2(look_dir[0], look_dir[2]))
            self.pitch = -math.degrees(math.atan2(look_dir[1], math.hypot(look_dir[0], look_dir[2])))
            target_fov = self.base_fov + min(16.0, v.speed * 0.32)
            if two:
                pl.body.set_visible(e < 0.7)
            else:
                v.driver_ent.enabled = e < 0.7               # don't look out through your own head
        # shake
        self.shake_amt = max(0.0, self.shake_amt - dt * 1.8)
        s = self.shake_amt * self.shake_amt
        off = (random.uniform(-1, 1) * s * 0.35, random.uniform(-1, 1) * s * 0.35, random.uniform(-1, 1) * s * 0.35)
        cam = (cam[0] + off[0], max(cam[1] + off[1], g.world.ground_height(cam[0], cam[2]) + 0.15), cam[2] + off[2])
        camera.position = Vec3(*cam)
        ld = look_dir
        cam_yaw = math.degrees(math.atan2(ld[0], ld[2]))
        cam_pitch = -math.degrees(math.atan2(ld[1], math.hypot(ld[0], ld[2])))
        camera.rotation = Vec3(cam_pitch + random.uniform(-1, 1) * s * 2.0, cam_yaw, random.uniform(-1, 1) * s * 3.0)
        self.fov += (target_fov - self.fov) * min(1.0, dt * 3.0)
        camera.fov = self.fov
        g.sound.listener = cam


# ================================================================== HUD
def _triangle_mesh():
    return Mesh(vertices=[(0, 0.55, 0), (0.4, -0.45, 0), (0, -0.2, 0), (-0.4, -0.45, 0)], triangles=[0, 1, 2, 0, 2, 3])


class HUD:
    def __init__(self, game):
        self.game = game
        ar = window.aspect_ratio
        self.R = R = ar / 2.0
        self.root = Entity(parent=camera.ui)          # everything in the HUD hangs off this (menu hides it)
        ui = self.root
        self.cash_shadow = Text(text='$0', parent=ui, position=(R - 0.028, 0.477), origin=(0.5, 0.5), scale=2.3, color=rgb(0, 0, 0, 160))
        self.cash_txt = Text(text='$0', parent=ui, position=(R - 0.03, 0.48), origin=(0.5, 0.5), scale=2.3, color=rgb(130, 255, 150))
        self._cash_shown = None
        self.popups = []
        self.stars = []
        for k in range(3):
            self.stars.append(Entity(parent=ui, model='quad', position=(R - 0.05 - k * 0.045, 0.405), scale=0.026, rotation_z=45,
                                     color=rgb(60, 60, 60, 200)))
        self.wanted_bar_bg = Entity(parent=ui, model='quad', position=(R - 0.095, 0.372), scale=(0.14, 0.008), color=rgb(0, 0, 0, 140))
        self.wanted_bar = Entity(parent=ui, model='quad', position=(R - 0.165, 0.372), origin=(-0.5, 0), scale=(0.14, 0.008),
                                 color=rgb(255, 80, 80))
        self.income_txt = Text(text='', parent=ui, position=(R - 0.03, 0.355), origin=(0.5, 0.5), scale=0.9, color=rgb(150, 230, 160))
        # health
        self.hp_bg = Entity(parent=ui, model='quad', position=(-R + 0.03, -0.465), origin=(-0.5, 0), scale=(0.32, 0.022),
                            color=rgb(0, 0, 0, 170))
        self.hp_bar = Entity(parent=ui, model='quad', position=(-R + 0.034, -0.465), origin=(-0.5, 0), scale=(0.312, 0.014),
                             color=rgb(80, 220, 90))
        self.hp_txt = Text(text='HP', parent=ui, position=(-R + 0.03, -0.43), origin=(-0.5, 0.5), scale=0.9, color=rgb(220, 220, 220))
        # clock + help
        self.clock_txt = Text(text='', parent=ui, position=(-R + 0.03, 0.5 - 0.345), origin=(-0.5, 0.5), scale=1.0, color=rgb(230, 230, 230))
        self.help_hint = Text(text='F1 controls  |  T day/night  |  V camera', parent=ui, position=(-R + 0.03, -0.405),
                              origin=(-0.5, 0.5), scale=0.75, color=rgb(170, 170, 170))
        # prompt
        self.prompt_bg = Entity(parent=ui, model='quad', position=(0, -0.3), scale=(0.5, 0.05), color=rgb(0, 0, 0, 160), enabled=False)
        self.prompt_txt = Text(text='', parent=ui, position=(0, -0.3), origin=(0, 0), scale=1.15, color=rgb(255, 255, 255))
        self._prompt = None
        # notifications
        self.notes = []
        # vehicle panel
        self.speed_txt = Text(text='', parent=ui, position=(R - 0.03, -0.36), origin=(0.5, 0.5), scale=3.0, color=rgb(255, 255, 255))
        self.unit_txt = Text(text='', parent=ui, position=(R - 0.03, -0.43), origin=(0.5, 0.5), scale=0.9, color=rgb(190, 190, 190))
        self.ev_txt = Text(text='', parent=ui, position=(R - 0.03, -0.26), origin=(0.5, 0.5), scale=0.9, color=rgb(150, 230, 255))
        self.bat_bg = Entity(parent=ui, model='quad', position=(R - 0.13, -0.33), scale=(0.2, 0.012), color=rgb(0, 0, 0, 150), enabled=False)
        self.bat_bar = Entity(parent=ui, model='quad', position=(R - 0.23, -0.33), origin=(-0.5, 0), scale=(0.2, 0.012),
                              color=rgb(80, 220, 255), enabled=False)
        self.drift_txt = Text(text='', parent=ui, position=(0, 0.36), origin=(0, 0), scale=1.9, color=rgb(255, 200, 60))
        self.drift_bg = Entity(parent=ui, model='quad', position=(0, 0.33), scale=(0.3, 0.012), color=rgb(0, 0, 0, 150), enabled=False)
        self.drift_bar = Entity(parent=ui, model='quad', position=(-0.15, 0.33), origin=(-0.5, 0), scale=(0.3, 0.012),
                                color=rgb(255, 200, 60), enabled=False)
        self.activity_txt = Text(text='', parent=ui, position=(0, 0.3), origin=(0, 0), scale=1.15, color=rgb(140, 230, 255))
        self.weapon_txt = Text(text='', parent=ui, position=(R - 0.03, -0.205), origin=(0.5, 0.5), scale=1.1, color=rgb(255, 210, 140))
        self.cross = Entity(parent=ui, model='quad', scale=0.006, color=rgb(255, 255, 255, 220))
        # robbery progress
        self.rob_bg = Entity(parent=ui, model='quad', position=(0, -0.2), scale=(0.4, 0.024), color=rgb(0, 0, 0, 170), enabled=False)
        self.rob_bar = Entity(parent=ui, model='quad', position=(-0.196, -0.2), origin=(-0.5, 0), scale=(0.392, 0.016),
                              color=rgb(90, 230, 100), enabled=False)
        self.rob_txt = Text(text='', parent=ui, position=(0, -0.17), origin=(0, 0), scale=1.0, color=rgb(255, 255, 255))
        self.busted_txt = Text(text='', parent=ui, position=(0, -0.13), origin=(0, 0), scale=1.0, color=rgb(255, 120, 120))
        # overlays
        self.flash_q = Entity(parent=ui, model='quad', scale=(ar * 1.1, 1.1), color=Color(1, 0.95, 0.85, 0), z=-0.5)
        self.hurt_q = Entity(parent=ui, model='quad', scale=(ar * 1.1, 1.1), color=Color(0.7, 0, 0, 0), z=-0.49)
        self.fade_q = Entity(parent=ui, model='quad', scale=(ar * 1.1, 1.1), color=Color(0, 0, 0, 0), z=-0.48)
        self.big = Text(text='', parent=ui, position=(0, 0.06), origin=(0, 0), scale=5.0, color=rgb(220, 30, 30), z=-0.6)
        self.big_sub = Text(text='', parent=ui, position=(0, -0.04), origin=(0, 0), scale=1.6, color=rgb(255, 255, 255), z=-0.6)
        self.big_t = 0.0
        self.flash_a = self.hurt_a = self.fade_a = 0.0
        self._build_minimap()
        self.help_panel = None
        self.net_txt = Text(text='', parent=ui, position=(-R + 0.03, -0.37), origin=(-0.5, 0.5), scale=0.85, color=rgb(150, 220, 255))

    def set_visible(self, v):
        self.root.enabled = v

    # ---- minimap
    def _build_minimap(self):
        ui = self.root
        R = self.R
        self.map_size = s = 0.3
        self.map_c = (-R + 0.03 + s / 2, 0.5 - 0.03 - s / 2)
        self.map_ext = BOUNDARY + 6
        k = s / (2 * self.map_ext)
        self.map_k = k
        cx, cy = self.map_c
        self.map_ents = [Entity(parent=ui, model='quad', position=(cx, cy), scale=s + 0.008, color=rgb(255, 140, 30, 200), z=0.3),
                         Entity(parent=ui, model='quad', position=(cx, cy), scale=s, color=rgb(40, 66, 40, 235), z=0.29)]
        span = (ASPHALT_MAX - ASPHALT_MIN) * k
        self.map_ents.append(Entity(parent=ui, model='quad', position=(cx, cy), scale=span, color=rgb(120, 120, 118, 255), z=0.28))
        for rc in ROADS:
            self.map_ents.append(Entity(parent=ui, model='quad', position=(cx + rc * k, cy), scale=(ROAD_W * k, span), color=rgb(42, 44, 48), z=0.27))
            self.map_ents.append(Entity(parent=ui, model='quad', position=(cx, cy + rc * k), scale=(span, ROAD_W * k), color=rgb(42, 44, 48), z=0.27))
        poi_cols = {'shop': rgb(255, 220, 40), 'garage': rgb(0, 220, 255), 'dealer': rgb(255, 120, 20), 'business': rgb(200, 90, 255)}
        for (x, z, kind) in self.game.world.pois:
            self.map_ents.append(Entity(parent=ui, model='quad', position=(cx + x * k, cy + z * k), scale=0.012,
                                        color=poi_cols.get(kind, color.white), z=0.2, rotation_z=45 if kind == 'business' else 0))
        self.map_arrow = Entity(parent=ui, model=_triangle_mesh(), position=(cx, cy), scale=0.016, color=rgb(255, 255, 255), z=0.1,
                                double_sided=True)
        self.map_cops = [Entity(parent=ui, model='quad', scale=0.01, color=rgb(255, 40, 40), z=0.15, enabled=False) for _ in range(4)]
        self.map_cars = Entity(parent=ui, model='quad', scale=0.008, color=rgb(255, 255, 255), z=0.15, enabled=False)
        self.map_marks = [Entity(parent=ui, model='quad', scale=0.014, rotation_z=45, z=0.12, enabled=False) for _ in range(2)]

    def add_activity_blips(self):
        k = self.map_k
        cx, cy = self.map_c
        for (x, z) in self.game.shops.activities.trials.start_positions():
            self.map_ents.append(Entity(parent=self.root, model='quad', position=(cx + x * k, cy + z * k), scale=0.013,
                                        color=rgb(60, 130, 255), z=0.2))

    def _map_pos(self, x, z):
        cx, cy = self.map_c
        k = self.map_k
        return (cx + clampf(x, -self.map_ext, self.map_ext) * k, cy + clampf(z, -self.map_ext, self.map_ext) * k)

    # ---- big full-screen map (M)
    def toggle_bigmap(self):
        if getattr(self, 'bigmap', None):
            for e in self.bigmap:
                destroy(e)
            self.bigmap = None
            return
        if self.help_panel is not None:
            self.toggle_help()
        from world import LOT_SPECIAL, HALF_ROAD, N_BLOCKS
        g = self.game
        ui = camera.ui
        s = 0.86
        ext = BOUNDARY + 6
        k = s / (2 * ext)
        cx, cy = -0.17, 0.0
        self.bm_k, self.bm_c, self.bm_ext = k, (cx, cy), ext
        E = []

        def quad(x, y, sx, sy, col, z, **kw):
            e = Entity(parent=ui, model='quad', position=(x, y), scale=(sx, sy), color=col, z=z, **kw)
            E.append(e)
            return e

        quad(0, 0, 4, 2, rgb(0, 0, 0, 170), -0.40)                                     # dim the game
        quad(cx, cy, s + 0.012, s + 0.012, rgb(255, 140, 30), -0.41)
        quad(cx, cy, s, s, rgb(46, 92, 128), -0.42)                                    # water
        land = (BOUNDARY - 4) * 2 * k
        quad(cx, cy, land, land, rgb(58, 96, 52), -0.43)                               # dike / grass
        span = (ASPHALT_MAX - ASPHALT_MIN) * k
        quad(cx, cy, span, span, rgb(52, 54, 58), -0.44)                               # asphalt
        lot_cols = {'park': rgb(70, 140, 60), 'parking': rgb(88, 90, 96), 'shop': rgb(150, 130, 40),
                    'garage': rgb(20, 120, 140), 'business': rgb(110, 60, 150)}
        for i in range(N_BLOCKS):
            for j in range(N_BLOCKS):
                x0, z0 = ROADS[i] + HALF_ROAD, ROADS[j] + HALF_ROAD
                x1, z1 = ROADS[i + 1] - HALF_ROAD, ROADS[j + 1] - HALF_ROAD
                spec = LOT_SPECIAL.get((i, j))
                col = lot_cols.get(spec[0], rgb(120, 116, 110)) if spec else rgb(112, 108, 104)
                mx, mz = (x0 + x1) / 2, (z0 + z1) / 2
                quad(cx + mx * k, cy + mz * k, (x1 - x0) * k, (z1 - z0) * k, col, -0.45)
                if spec is None:                                                       # little building blocks
                    for (ox, oz) in ((-0.25, -0.25), (0.25, -0.25), (-0.25, 0.25), (0.25, 0.25)):
                        quad(cx + (mx + ox * (x1 - x0)) * k, cy + (mz + oz * (z1 - z0)) * k,
                             (x1 - x0) * 0.4 * k, (z1 - z0) * 0.4 * k, rgb(150, 144, 136), -0.46)
                elif len(spec) > 1:
                    name = str(spec[1]).replace('&', 'and')
                    t = Text(text=name, parent=ui, position=(cx + mx * k, cy + mz * k), origin=(0, 0), scale=0.62,
                             color=rgb(255, 255, 255), z=-0.47)
                    E.append(t)
                elif spec[0] in ('park', 'garage', 'parking'):
                    t = Text(text={'park': 'PARK', 'garage': 'E-TUNING', 'parking': 'PARKING'}[spec[0]], parent=ui,
                             position=(cx + mx * k, cy + mz * k), origin=(0, 0), scale=0.62, color=rgb(255, 255, 255), z=-0.47)
                    E.append(t)
        for rc in ROADS:                                                               # lane markings
            quad(cx + rc * k, cy, 0.0015, span, rgb(220, 210, 120, 140), -0.455)
            quad(cx, cy + rc * k, span, 0.0015, rgb(220, 210, 120, 140), -0.455)
        poi_cols = {'shop': rgb(255, 220, 40), 'garage': rgb(0, 220, 255), 'dealer': rgb(255, 120, 20), 'business': rgb(200, 90, 255)}
        for (x, z, kind) in g.world.pois:
            quad(cx + x * k, cy + z * k, 0.018, 0.018, poi_cols.get(kind, color.white), -0.48,
                 rotation_z=45 if kind == 'business' else 0)
        try:
            for (x, z) in g.shops.activities.trials.start_positions():
                quad(cx + x * k, cy + z * k, 0.018, 0.018, rgb(60, 130, 255), -0.48)
        except Exception:
            pass
        self.bm_marks = [quad(0, 0, 0.02, 0.02, color.white, -0.49, rotation_z=45, enabled=False) for _ in range(2)]
        self.bm_cops = [quad(0, 0, 0.014, 0.014, rgb(255, 40, 40), -0.49, enabled=False) for _ in range(4)]
        self.bm_arrow = Entity(parent=ui, model=_triangle_mesh(), scale=0.028, color=rgb(255, 255, 255), z=-0.5, double_sided=True)
        E.append(self.bm_arrow)
        # legend
        lx = cx + s / 2 + 0.05
        quad(lx + 0.16, 0.0, 0.36, s, rgb(12, 14, 20, 235), -0.41)
        E.append(Text(text='CITY MAP', parent=ui, position=(lx + 0.02, s / 2 - 0.04), origin=(-0.5, 0.5), scale=1.6,
                      color=rgb(255, 150, 40), z=-0.42))
        rows = [('You', rgb(255, 255, 255)), ('Shop - rob it', rgb(255, 220, 40)), ('Fireworks dealer', rgb(255, 120, 20)),
                ('E-Tuning garage', rgb(0, 220, 255)), ('Business for sale', rgb(200, 90, 255)),
                ('Time-trial start', rgb(60, 130, 255)), ('Courier pickup', rgb(60, 255, 100)),
                ('Courier drop-off', rgb(255, 220, 40)), ('Police', rgb(255, 40, 40))]
        y = s / 2 - 0.13
        for name, col in rows:
            quad(lx + 0.035, y, 0.016, 0.016, col, -0.42)
            E.append(Text(text=name, parent=ui, position=(lx + 0.06, y), origin=(-0.5, 0), scale=0.95, z=-0.42))
            y -= 0.045
        y -= 0.02
        own = [b['name'].title().replace('&', 'and') for b, st in zip(g.shops.business.data, g.shops.business.state) if st['owned']]
        E.append(Text(text='Your businesses:\n' + ('\n'.join('  ' + n for n in own) if own else '  none yet'),
                      parent=ui, position=(lx + 0.02, y), origin=(-0.5, 0.5), scale=0.9, color=rgb(190, 255, 190), z=-0.42))
        E.append(Text(text='M  close map', parent=ui, position=(lx + 0.02, -s / 2 + 0.04), origin=(-0.5, 0), scale=0.9,
                      color=rgb(160, 160, 160), z=-0.42))
        self.bigmap = E
        self._update_bigmap(0.0)

    def _update_bigmap(self, dt):
        g = self.game
        pl = g.player
        k, (cx, cy), ext = self.bm_k, self.bm_c, self.bm_ext

        def mp(x, z):
            return (cx + clampf(x, -ext, ext) * k, cy + clampf(z, -ext, ext) * k)

        v = pl.vehicle
        p = pl.pos
        self.bm_arrow.position = mp(p.x, p.z)
        self.bm_arrow.rotation_z = v.heading if v is not None else pl.yaw
        bl = int(getattr(self, 'blink_t', 0.0) * 3) % 2 == 0
        self.bm_arrow.scale = 0.028 if bl else 0.034
        marks = g.shops.activities.markers()
        mcol = {'pickup': rgb(60, 255, 100), 'deliver': rgb(255, 220, 40), 'ring': rgb(80, 230, 255)}
        for i, e in enumerate(self.bm_marks):
            if i < len(marks):
                x, z, kind = marks[i]
                e.enabled = True
                e.position = mp(x, z)
                e.color = mcol[kind]
            else:
                e.enabled = False
        cops = list(g.wanted.police)
        for i, e in enumerate(self.bm_cops):
            if i < len(cops):
                e.enabled = True
                e.position = mp(cops[i].car.x, cops[i].car.z)
            else:
                e.enabled = False

    # ---- api
    def notify(self, text, col=None, life=4.0):
        t = Text(text=text, parent=self.root, position=(0, 0.44), origin=(0, 0), scale=1.15,
                 color=col if col is not None else color.white)
        self.notes.insert(0, [t, life])
        while len(self.notes) > 5:
            destroy(self.notes.pop()[0])

    def money_popup(self, amount, reason=''):
        txt = ('+$%s' % format(amount, ',')) if amount > 0 else ('-$%s' % format(-amount, ','))
        if reason:
            txt = '%s  %s' % (reason, txt)
        t = Text(text=txt, parent=self.root, position=(self.R - 0.03, 0.43), origin=(0.5, 0.5), scale=1.3,
                 color=rgb(120, 255, 140) if amount > 0 else rgb(255, 120, 120))
        self.popups.append([t, 1.6])

    def flash(self, a):
        self.flash_a = max(self.flash_a, a)

    def hurt(self, a):
        self.hurt_a = max(self.hurt_a, 0.25 + a * 0.4)

    def fade(self, a):
        self.fade_a = max(self.fade_a, a)

    def big_text(self, title, sub=''):
        self.big.text = title
        self.big_sub.text = sub
        self.big_t = 3.8

    def toggle_help(self):
        if getattr(self, 'bigmap', None):
            self.toggle_bigmap()
        if self.help_panel is not None:
            for e in self.help_panel:
                destroy(e)
            self.help_panel = None
            return
        lines = [
            'CONTROLS', '',
            'WASD  move / drive          SHIFT  sprint / EV boost',
            'SPACE  jump / handbrake (drift!)   MOUSE  look',
            'E  enter / steal / carjack / exit / interact',
            'B  buy a snack in a shop         H  horn     R  reset vehicle',
            'CTRL  wheelie on scooters / KuKirin / e-motorbike - no auto-balance, feather it!',
            'Q  re-open the tuning menu while parked on the E-Tuning pad',
            'V  first / third person          T  toggle day / night',
            'LEFT CLICK  throw firework       TAB (hold)  weapon wheel',
            '1 / 2 / 3 / scroll  select hands / Cobra 6 / Scream 100',
            'ESC  pause / close menu          F9  one-time +5,000 coin bonus',
            'F12  screenshot (saved in the screenshots folder, without the HUD)',
            'M  full-screen city map',
            '',
            'Minimap:  yellow = shops (rob them)   orange = fireworks dealer',
            '          cyan = E-Tuning garage        purple = businesses for sale',
            '          blue = time-trial start       green / yellow = courier pickup / drop-off',
            'Courier: grab the package at the green beacon, deliver it before the timer ends.',
            'Time trials: drive into a blue beacon, then hit every glowing ring.',
            'Hold SPACE + steer at speed to drift - drifting pays cash.',
            'Hold SPACE + W standing still for a burnout / donuts.',
        ]
        bg = Entity(parent=camera.ui, model='quad', scale=(1.05, 0.62), color=rgb(10, 12, 18, 235), z=-0.2)
        t = Text(text='\n'.join(lines), parent=camera.ui, position=(-0.49, 0.28), origin=(-0.5, 0.5), scale=1.0, z=-0.3)
        self.help_panel = [bg, t]

    # ---- per frame
    def update(self, dt):
        g = self.game
        pl = g.player
        cash = int(pl.cash)
        if cash != self._cash_shown:
            self._cash_shown = cash
            s = '$%s' % format(cash, ',')
            self.cash_txt.text = s
            self.cash_shadow.text = s
        for p in list(self.popups):
            p[1] -= dt
            p[0].y += dt * 0.03
            p[0].alpha = clampf(p[1] / 0.6, 0, 1)
            if p[1] <= 0:
                destroy(p[0])
                self.popups.remove(p)
        # wanted
        wl = g.wanted.level
        blink = g.wanted.flash > 0 and int(g.wanted.flash * 8) % 2 == 0
        for k, st in enumerate(self.stars):
            on = k < wl
            st.color = (rgb(255, 255, 255) if blink else rgb(255, 200, 40)) if on else rgb(60, 60, 60, 160)
        if wl > 0:
            self.wanted_bar.scale_x = 0.14 * clampf(g.wanted.timer / g.wanted.duration(), 0, 1)
            self.wanted_bar.color = rgb(120, 160, 255) if g.wanted.police_near() else rgb(255, 80, 80)
            self.wanted_bar.enabled = self.wanted_bar_bg.enabled = True
        else:
            self.wanted_bar.enabled = self.wanted_bar_bg.enabled = False
        inc = g.shops.business.total_income()
        it = ('Businesses: +$%d / min' % inc) if inc else ''
        if self.income_txt.text != it:
            self.income_txt.text = it
        # health
        hp = clampf(pl.health / 100.0, 0, 1)
        self.hp_bar.scale_x = 0.312 * hp
        self.hp_bar.color = rgb(int(230 - 150 * hp), int(60 + 160 * hp), 80)
        ct = '%s   %s' % (g.world.clock_text(), 'DAY' if g.world.is_day() else 'NIGHT')
        if self.clock_txt.text != ct:
            self.clock_txt.text = ct
        # prompt
        prompt = None
        items = g.interactions
        if items and pl.state in ('foot', 'vehicle') and g.menu is None:
            seen = set()
            parts = []
            for it_ in sorted(items, key=lambda q: q['dist']):
                k = it_['key']
                if k in seen and k is not None:
                    continue
                seen.add(k)
                parts.append(('[%s] %s' % (k.upper(), it_['text'])) if k else it_['text'])
                if len(parts) >= 2:
                    break
            prompt = '     '.join(parts)
        if prompt != self._prompt:
            self._prompt = prompt
            self.prompt_txt.text = prompt or ''
            self.prompt_bg.enabled = bool(prompt)
            if prompt:
                self.prompt_bg.scale_x = max(0.3, self.prompt_txt.width + 0.06)
        # notifications
        for i, n in enumerate(list(self.notes)):
            n[1] -= dt
            n[0].y += (0.44 - i * 0.04 - n[0].y) * min(1.0, dt * 10)
            n[0].alpha = clampf(n[1], 0, 1)
            if n[1] <= 0:
                destroy(n[0])
                self.notes.remove(n)
        # vehicle panel
        v = pl.vehicle
        if v is not None:
            kmh = int(v.speed * 3.6)
            st = str(kmh)
            if self.speed_txt.text != st:
                self.speed_txt.text = st
            self.unit_txt.text = 'km/h' if not v.is_two_wheeler else 'km/h  %s' % v.display_name
            if v.is_ev:
                et = '%dW   BATTERY %d%%   ~%.1f km%s' % (v.watt, v.battery_pct(), v.range_km(), '   BOOST' if v.boost_active else '')
                if self.ev_txt.text != et:
                    self.ev_txt.text = et
                self.bat_bg.enabled = self.bat_bar.enabled = True
                b = v.battery_pct() / 100.0
                self.bat_bar.scale_x = 0.2 * b
                self.bat_bar.color = rgb(255, 80, 60) if b < 0.15 else rgb(80, 220, 255)
            else:
                self.ev_txt.text = ('HEALTH %d%%' % v.health) if v.health < 100 else ''
                self.bat_bg.enabled = self.bat_bar.enabled = False
        else:
            if self.speed_txt.text:
                self.speed_txt.text = ''
                self.unit_txt.text = ''
                self.ev_txt.text = ''
            self.bat_bg.enabled = self.bat_bar.enabled = False
        d = g.vehicles.drift
        dtxt = ('DRIFT  %d   x%d' % (int(d.points), d.mult)) if d.active and d.points > 20 else ''
        if v is not None and v.is_two_wheeler and v.wheelie > 1.0:
            dtxt = 'WHEELIE  %d deg   %.1fs' % (v.wheelie, v.wheelie_time)
        if self.drift_txt.text != dtxt:
            self.drift_txt.text = dtxt
        show_meter = bool(dtxt)
        self.drift_bg.enabled = self.drift_bar.enabled = show_meter
        if show_meter and v is not None and v.is_two_wheeler and v.wheelie > 1.0:
            k = v.wheelie / 88.0                      # full bar = flipping over
            self.drift_bar.scale_x = 0.3 * clampf(k, 0, 1)
            bal = v.BALANCE
            self.drift_bar.color = (rgb(255, 60, 40) if v.wheelie > bal - 4 else
                                    rgb(120, 255, 120) if v.wheelie > bal - 30 else rgb(255, 200, 60))
        elif show_meter:
            self.drift_bar.scale_x = 0.3 * d.meter()
            self.drift_bar.color = rgb(255, 80, 40) if d.mult >= 5 else rgb(255, 200, 60)
        nt = g.net.hud_text() if g.net is not None else ''
        if self.net_txt.text != nt:
            self.net_txt.text = nt
        act = g.shops.activities.status() or ''
        if self.activity_txt.text != act:
            self.activity_txt.text = act
        # weapon
        fw = g.fireworks
        key = fw.equipped()
        wt = 'Unarmed' if key == 'hands' else '%s  x%d' % ({'cobra6': 'Cobra 6', 'scream100': 'Scream 100'}[key], fw.inv[key])
        if self.weapon_txt.text != wt:
            self.weapon_txt.text = wt
        self.cross.enabled = key != 'hands' and pl.state == 'foot' and g.menu is None
        # robbery
        prog = g.shops.robbery.progress()
        if prog is not None:
            self.rob_bg.enabled = self.rob_bar.enabled = True
            self.rob_bar.scale_x = 0.392 * clampf(prog, 0, 1)
            self.rob_txt.text = 'EMPTYING THE REGISTER... stay close!'
        elif self.rob_bg.enabled:
            self.rob_bg.enabled = self.rob_bar.enabled = False
            self.rob_txt.text = ''
        bt = 'Police are arresting you - MOVE!' if g.wanted.busted_t > 0.3 else ''
        if self.busted_txt.text != bt:
            self.busted_txt.text = bt
        # overlays
        self.flash_a = max(0.0, self.flash_a - dt * 2.2)
        self.hurt_a = max(0.0, self.hurt_a - dt * 1.2)
        self.fade_a = max(0.0, self.fade_a - dt * 0.9)
        self.flash_q.alpha = self.flash_a
        self.hurt_q.alpha = self.hurt_a * 0.5 + (0.18 * (1 - pl.health / 100.0) if pl.health < 35 else 0)
        dead = pl.state in ('dead', 'busted')
        self.fade_q.alpha = max(self.fade_a, 0.45 if dead else 0.0)
        if self.big_t > 0:
            self.big_t -= dt
            if self.big_t <= 0:
                self.big.text = ''
                self.big_sub.text = ''
        # minimap
        p = pl.pos
        self.map_arrow.position = self._map_pos(p.x, p.z)
        self.map_arrow.rotation_z = v.heading if v is not None else pl.yaw
        self.blink_t = getattr(self, 'blink_t', 0.0) + dt
        marks = g.shops.activities.markers()
        mcol = {'pickup': rgb(60, 255, 100), 'deliver': rgb(255, 220, 40), 'ring': rgb(80, 230, 255)}
        for i, e in enumerate(self.map_marks):
            if i < len(marks):
                x, z, kind = marks[i]
                e.enabled = int(self.blink_t * 3) % 2 == 0 or kind == 'pickup'
                e.position = self._map_pos(x, z)
                e.color = mcol[kind]
            else:
                e.enabled = False
        if getattr(self, 'bigmap', None):
            self._update_bigmap(dt)
        cops = [q for q in g.wanted.police]
        for i, e in enumerate(self.map_cops):
            if i < len(cops):
                c = cops[i].car
                e.enabled = True
                e.position = self._map_pos(c.x, c.z)
                e.color = rgb(255, 40, 40) if int(self.blink_t * 6) % 2 == 0 else rgb(60, 120, 255)
            else:
                e.enabled = False

"""
menus.py  -  start screen, settings and the multiplayer room browser
======================================================================

* MenuCamera: slow cinematic flight over the city at dusk while traffic drives
  and fireworks pop in the sky
* MainMenu: left-side dark gradient with SINGLEPLAYER / MULTIPLAYER / SETTINGS /
  QUIT and the version number bottom-left
* SettingsMenu: mouse sensitivity, master volume, field of view, draw distance,
  fullscreen (saved in savegame.json)
* MultiplayerMenu: your name, LAN room list (name, players, lock icon for
  PRIVATE rooms), direct join (host IP + room code) and Create Room
  (room name, PUBLIC / PRIVATE toggle, custom or generated code)
"""
from ursina import *
import math
import random
from world import Color, rgb, col_mul, clampf, ROADS
import network

ACCENT = rgb(255, 140, 30)
FONT_DIM = rgb(170, 175, 185)


# ------------------------------------------------------------------ widgets
def gradient_panel(parent, x0, x1, alpha_left=0.9, alpha_right=0.0):
    verts = [(x0, -0.5, 0), (x1, -0.5, 0), (x1, 0.5, 0), (x0, 0.5, 0)]
    cl = Color(0.02, 0.03, 0.05, alpha_left)
    cr = Color(0.02, 0.03, 0.05, alpha_right)
    m = Mesh(vertices=verts, triangles=[0, 1, 2, 0, 2, 3], colors=[cl, cr, cr, cl])
    return Entity(parent=parent, model=m, z=0.5, double_sided=True)


def lock_icon(parent, x, y, s=1.0, col=None):
    c = col if col is not None else rgb(255, 200, 60)
    ents = [Entity(parent=parent, model='quad', position=(x, y - 0.004 * s), scale=(0.018 * s, 0.014 * s), color=c, z=-0.2)]
    for sx in (-1, 1):
        ents.append(Entity(parent=parent, model='quad', position=(x + sx * 0.0065 * s, y + 0.008 * s),
                           scale=(0.003 * s, 0.012 * s), color=c, z=-0.2))
    ents.append(Entity(parent=parent, model='quad', position=(x, y + 0.0135 * s), scale=(0.016 * s, 0.003 * s), color=c, z=-0.2))
    return ents


class TextField:
    """Minimal single-line text input (click to focus, type, Backspace)."""
    focused = None
    KEYMAP = {'space': ' ', 'minus': '-', 'period': '.', 'full stop': '.'}

    def __init__(self, parent, x, y, w, value='', limit=20, allowed=None, placeholder=''):
        self.value = value
        self.limit = limit
        self.allowed = allowed
        self.placeholder = placeholder
        self.bg = Button(parent=parent, position=(x, y), scale=(w, 0.05), color=rgb(30, 34, 44, 240),
                         highlight_color=rgb(44, 50, 64, 240), pressed_color=rgb(30, 34, 44, 240), z=-0.1)
        self.bg.on_click = self.focus
        self.txt = Text(text='', parent=parent, position=(x - w / 2 + 0.012, y), origin=(-0.5, 0), scale=1.0, z=-0.2)
        self.blink = 0.0
        self.enabled = True
        self.refresh()

    def focus(self):
        TextField.focused = self
        self.refresh()

    def refresh(self):
        caret = '|' if (TextField.focused is self and int(self.blink * 2) % 2 == 0) else ''
        if self.value or TextField.focused is self:
            self.txt.text = self.value + caret
            self.txt.color = color.white
        else:
            self.txt.text = self.placeholder
            self.txt.color = rgb(110, 115, 125)
        self.bg.color = rgb(40, 46, 60, 250) if TextField.focused is self else rgb(30, 34, 44, 240)

    def set_enabled(self, on):
        self.enabled = on
        self.bg.enabled = self.txt.enabled = on
        if not on and TextField.focused is self:
            TextField.focused = None

    def key(self, key):
        if key == 'backspace':
            self.value = self.value[:-1]
        elif key in ('enter', 'escape', 'tab'):
            TextField.focused = None
        else:
            ch = self.KEYMAP.get(key, key)
            if len(ch) == 1 and len(self.value) < self.limit:
                if held_keys['shift'] or held_keys['left shift']:
                    ch = ch.upper()
                if self.allowed is None or ch.upper() in self.allowed or ch in self.allowed:
                    self.value += ch
        self.refresh()

    def tick(self, dt):
        if TextField.focused is self:
            self.blink += dt
            self.refresh()


def menu_button(parent, label, x, y, w, h, cb, col=None, hl=None):
    c = col if col is not None else rgb(20, 24, 32, 200)
    b = Button(text=label, parent=parent, position=(x, y), scale=(w, h), color=c,
               highlight_color=hl if hl is not None else rgb(255, 140, 30, 235), pressed_color=rgb(200, 100, 20, 255), z=-0.1)
    b.on_click = cb
    return b


# ------------------------------------------------------------------ cinematic camera
class MenuCamera:
    def __init__(self, game):
        self.game = game
        self.a = random.uniform(0, 6.28)
        self.burst_cd = 1.5

    def update(self, dt):
        self.a += dt * 0.035
        a = self.a
        R = 115.0
        pos = (math.cos(a) * R, 34.0 + 8.0 * math.sin(a * 1.7), math.sin(a) * R)
        look = (math.cos(a + 0.9) * 45.0, 4.0, math.sin(a + 0.9) * 45.0)
        d = (look[0] - pos[0], look[1] - pos[1], look[2] - pos[2])
        camera.position = Vec3(*pos)
        camera.rotation = Vec3(-math.degrees(math.atan2(d[1], math.hypot(d[0], d[2]))),
                               math.degrees(math.atan2(d[0], d[2])), 0)
        camera.fov = 70
        self.game.sound.listener = pos
        self.burst_cd -= dt
        if self.burst_cd <= 0:
            self.burst_cd = random.uniform(1.2, 3.2)
            fx = random.uniform(-110, 110)
            fz = random.uniform(-110, 110)
            self.game.fireworks.sky_burst((fx, random.uniform(35, 60), fz))


# ------------------------------------------------------------------ screens
class Screen:
    def __init__(self, game):
        self.game = game
        self.root = Entity(parent=camera.ui)
        self.fields = []

    def tick(self, dt):
        for f in self.fields:
            f.tick(dt)

    def key(self, key):
        if TextField.focused is not None and TextField.focused in self.fields:
            TextField.focused.key(key)
            return True
        return False

    def close(self):
        TextField.focused = None
        destroy(self.root)


class MainMenu(Screen):
    def __init__(self, game):
        super().__init__(game)
        R = window.aspect_ratio / 2
        ui = self.root
        gradient_panel(ui, -R - 0.01, -R + 1.05, 0.92, 0.0)
        Entity(parent=ui, model='quad', position=(-R + 0.06, 0.25), scale=(0.006, 0.16), color=ACCENT, z=-0.1)
        Text(text='URSINA CITY', parent=ui, position=(-R + 0.08, 0.33), origin=(-0.5, 0.5), scale=3.6, color=color.white, z=-0.1)
        Text(text='crime  -  drifting  -  e-mobility  -  vuurwerk', parent=ui, position=(-R + 0.085, 0.215),
             origin=(-0.5, 0.5), scale=1.0, color=FONT_DIM, z=-0.1)
        items = (('SINGLEPLAYER', game.start_singleplayer), ('MULTIPLAYER', game.open_multiplayer),
                 ('SETTINGS', game.open_settings), ('QUIT', application.quit))
        for i, (label, cb) in enumerate(items):
            menu_button(ui, label, -R + 0.29, 0.07 - i * 0.085, 0.42, 0.065, cb)
        Text(text='v%s' % game.version, parent=ui, position=(-R + 0.03, -0.47), origin=(-0.5, -0.5), scale=0.9,
             color=FONT_DIM, z=-0.1)
        Text(text=random.choice(('Tip: hold SPACE while steering to drift for cash.',
                                 'Tip: the E-Tuning garage turns a KuKirin G2 into a 105 km/h rocket.',
                                 'Tip: Scream 100 screams for 2 seconds before it bangs.',
                                 'Tip: buy businesses - they earn while you play.',
                                 'Tip: cops only lose you once they are out of range.')),
             parent=ui, position=(-R + 0.08, -0.32), origin=(-0.5, 0.5), scale=0.85, color=FONT_DIM, z=-0.1)


class SettingsMenu(Screen):
    def __init__(self, game):
        super().__init__(game)
        self.build()

    def build(self):
        g = self.game
        st = g.settings
        for c in list(self.root.children):
            destroy(c)
        R = window.aspect_ratio / 2
        ui = self.root
        gradient_panel(ui, -R - 0.01, -R + 1.15, 0.94, 0.15)
        Text(text='SETTINGS', parent=ui, position=(-R + 0.08, 0.36), origin=(-0.5, 0.5), scale=2.6, z=-0.1)
        rows = (
            ('Mouse sensitivity', '%d' % st['sens'], 'sens', 5, 10, 100),
            ('Master volume', '%d%%' % st['volume'], 'volume', 10, 0, 100),
            ('Field of view', '%d' % st['fov'], 'fov', 5, 60, 95),
            ('Draw distance', ('LOW', 'MEDIUM', 'HIGH')[st['draw']], 'draw', 1, 0, 2),
            ('Fullscreen', 'ON' if st['fullscreen'] else 'OFF', 'fullscreen', 1, 0, 1),
        )
        for i, (label, val, key, step, lo, hi) in enumerate(rows):
            y = 0.2 - i * 0.08
            Text(text=label, parent=ui, position=(-R + 0.08, y), origin=(-0.5, 0), scale=1.15, z=-0.1)
            menu_button(ui, '<', -R + 0.55, y, 0.05, 0.05, lambda k=key, s=-step, a=lo, b=hi: self.change(k, s, a, b))
            Text(text=val, parent=ui, position=(-R + 0.665, y), origin=(0, 0), scale=1.15, color=ACCENT, z=-0.1)
            menu_button(ui, '>', -R + 0.78, y, 0.05, 0.05, lambda k=key, s=step, a=lo, b=hi: self.change(k, s, a, b))
        menu_button(ui, 'BACK', -R + 0.29, -0.28, 0.42, 0.065, self.game.back_to_main)

    def change(self, key, step, lo, hi):
        st = self.game.settings
        st[key] = int(clampf(st[key] + step, lo, hi))
        self.game.apply_settings()
        self.game.sound.play('blip', 0.5)
        self.build()


class MultiplayerMenu(Screen):
    ALNUM = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -_')
    IPCH = set('0123456789.abcdefghijklmnopqrstuvwxyz-ABCDEFGHIJKLMNOPQRSTUVWXYZ')

    def __init__(self, game):
        super().__init__(game)
        self.browser = network.LanBrowser()
        self.private = False
        self.room_ents = []
        self.room_cache = None
        self.refresh_t = 0.0
        R = window.aspect_ratio / 2
        self.R = R
        ui = self.root
        gradient_panel(ui, -R - 0.01, R + 0.01, 0.9, 0.75)
        Text(text='MULTIPLAYER', parent=ui, position=(-R + 0.08, 0.44), origin=(-0.5, 0.5), scale=2.6, z=-0.1)
        Text(text='Your name', parent=ui, position=(-R + 0.08, 0.31), origin=(-0.5, 0), scale=1.0, color=FONT_DIM, z=-0.1)
        self.name = TextField(ui, -R + 0.42, 0.31, 0.3, game.settings.get('name', 'Player'), 16, self.ALNUM)
        # ---- join column
        x0 = -R + 0.08
        Text(text='JOIN A ROOM  (LAN)', parent=ui, position=(x0, 0.23), origin=(-0.5, 0), scale=1.25, color=ACCENT, z=-0.1)
        self.rooms_hint = Text(text='Searching for rooms on your network ...', parent=ui, position=(x0, 0.18),
                               origin=(-0.5, 0), scale=0.9, color=FONT_DIM, z=-0.1)
        Text(text='DIRECT JOIN', parent=ui, position=(x0, -0.2), origin=(-0.5, 0), scale=1.15, color=ACCENT, z=-0.1)
        Text(text='Host IP', parent=ui, position=(x0, -0.26), origin=(-0.5, 0), scale=0.95, color=FONT_DIM, z=-0.1)
        self.ip = TextField(ui, x0 + 0.33, -0.26, 0.3, game.settings.get('last_ip', ''), 40, self.IPCH, '192.168.1.20')
        Text(text='Room code', parent=ui, position=(x0, -0.32), origin=(-0.5, 0), scale=0.95, color=FONT_DIM, z=-0.1)
        self.join_code = TextField(ui, x0 + 0.33, -0.32, 0.3, '', 6, self.ALNUM, 'only for PRIVATE')
        menu_button(ui, 'JOIN', x0 + 0.62, -0.29, 0.14, 0.11, self.direct_join, rgb(36, 120, 70, 230))
        # ---- create column
        cx = 0.12
        Text(text='CREATE ROOM', parent=ui, position=(cx, 0.23), origin=(-0.5, 0), scale=1.25, color=ACCENT, z=-0.1)
        Text(text='Room name', parent=ui, position=(cx, 0.16), origin=(-0.5, 0), scale=0.95, color=FONT_DIM, z=-0.1)
        self.room_name = TextField(ui, cx + 0.42, 0.16, 0.36, '%s\'s city' % self.name.value, 24, self.ALNUM)
        self.pub_btn = menu_button(ui, 'PUBLIC', cx + 0.12, 0.07, 0.22, 0.055, lambda: self.set_private(False))
        self.priv_btn = menu_button(ui, 'PRIVATE', cx + 0.36, 0.07, 0.22, 0.055, lambda: self.set_private(True))
        self.code_lbl = Text(text='Room code', parent=ui, position=(cx, -0.01), origin=(-0.5, 0), scale=0.95, color=FONT_DIM, z=-0.1)
        self.code = TextField(ui, cx + 0.33, -0.01, 0.2, network.make_code(), 6, self.ALNUM)
        self.gen_btn = menu_button(ui, 'GENERATE', cx + 0.53, -0.01, 0.16, 0.05, self.generate)
        menu_button(ui, 'CREATE & HOST', cx + 0.24, -0.1, 0.48, 0.07, self.create, rgb(36, 120, 70, 230))
        Text(text='Friends on the same Wi-Fi see the room automatically. Over the internet they need your\n'
                  'public IP (UPnP is tried automatically, otherwise forward TCP port 47500 in your router).\n'
                  'Allow Python through the Windows Firewall when asked.',
             parent=ui, position=(cx, -0.17), origin=(-0.5, 0.5), scale=0.78, color=FONT_DIM, z=-0.1)
        self.status = Text(text='', parent=ui, position=(-R + 0.08, -0.42), origin=(-0.5, 0), scale=1.05,
                           color=rgb(255, 200, 120), z=-0.1)
        menu_button(ui, 'BACK', R - 0.17, -0.44, 0.22, 0.06, self.back)
        self.fields = [self.name, self.ip, self.join_code, self.room_name, self.code]
        self.set_private(False)

    def set_private(self, on):
        self.private = on
        self.pub_btn.color = rgb(255, 140, 30, 235) if not on else rgb(20, 24, 32, 200)
        self.priv_btn.color = rgb(255, 140, 30, 235) if on else rgb(20, 24, 32, 200)
        self.code.set_enabled(on)
        self.gen_btn.enabled = on
        self.code_lbl.enabled = on

    def generate(self):
        self.code.value = network.make_code(random.choice((4, 5, 6)))
        self.code.refresh()

    def _player_name(self):
        n = self.name.value.strip() or 'Player'
        self.game.settings['name'] = n
        return n

    def say(self, msg):
        self.status.text = msg

    def create(self):
        code = self.code.value.strip().upper()
        if self.private and len(code) < 4:
            self.say('A private room needs a code of 4-6 characters (or press GENERATE).')
            return
        name = self.room_name.value.strip() or 'Ursina City'
        self.say('Starting server ...')
        invoke(self.game.host_multiplayer, name, self.private, code, self._player_name(), delay=0.05)

    def join(self, ip, code):
        self.game.settings['last_ip'] = ip
        self.say('Connecting to %s ...' % ip)
        invoke(self.game.join_multiplayer, ip, code, self._player_name(), delay=0.05)

    def direct_join(self):
        ip = self.ip.value.strip()
        if not ip:
            self.say('Type the host IP address first.')
            return
        self.join(ip, self.join_code.value.strip().upper())

    def pick_room(self, room):
        if room.get('private'):
            self.ip.value = room['ip']
            self.ip.refresh()
            self.join_code.focus()
            self.say('"%s" is PRIVATE - type the room code and press JOIN.' % room['name'])
        else:
            self.join(room['ip'], '')

    def _draw_rooms(self, rooms):
        for e in self.room_ents:
            destroy(e)
        self.room_ents = []
        x0 = -self.R + 0.08
        self.rooms_hint.text = ('%d room(s) found - click to join' % len(rooms)) if rooms else \
            'No rooms found on your network yet (searching ...)'
        for i, r in enumerate(rooms[:6]):
            y = 0.12 - i * 0.055
            label = '%s' % r.get('name', '?')
            b = menu_button(self.root, '', x0 + 0.32, y, 0.64, 0.048, lambda r=r: self.pick_room(r), rgb(26, 30, 40, 230),
                            rgb(60, 70, 90, 240))
            self.room_ents.append(b)
            self.room_ents.append(Text(text=label, parent=self.root, position=(x0 + 0.03, y), origin=(-0.5, 0), scale=1.0, z=-0.2))
            self.room_ents.append(Text(text='%d/%d' % (r.get('players', 1), r.get('max', 8)), parent=self.root,
                                       position=(x0 + 0.5, y), origin=(0, 0), scale=1.0, color=FONT_DIM, z=-0.2))
            if r.get('private'):
                self.room_ents += lock_icon(self.root, x0 + 0.6, y - 0.004, 1.4)
            else:
                self.room_ents.append(Text(text='OPEN', parent=self.root, position=(x0 + 0.6, y), origin=(0, 0), scale=0.8,
                                           color=rgb(120, 230, 140), z=-0.2))

    def tick(self, dt):
        super().tick(dt)
        self.refresh_t -= dt
        if self.refresh_t <= 0:
            self.refresh_t = 1.0
            rooms = self.browser.list()
            sig = [(r['ip'], r.get('port'), r.get('players'), r.get('name')) for r in rooms]
            if sig != self.room_cache:
                self.room_cache = sig
                self._draw_rooms(rooms)

    def back(self):
        self.game.back_to_main()

    def close(self):
        self.browser.stop()
        super().close()

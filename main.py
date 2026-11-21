"""
URSINA CITY  -  a GTA-style open-world crime & vehicle sandbox in pure Python
==============================================================================

    pip install ursina numpy
    python main.py            (or double-click START_GAME.bat)

Everything (models, shaders, sounds) is generated procedurally on startup.
On launch the game checks GitHub for a newer version (updater.py), then shows
the main menu over a live, slowly flying view of the city.

    world.py            city, lighting, day/night, particles, audio, collision
    player.py           player, camera, HUD
    vehicles.py         cars (drift physics), E-scooters / E-motorbikes / KuKirin G2
    npcs.py             pedestrians, traffic, police, wanted level
    items_and_shops.py  fireworks, robberies, businesses, tuning, courier, time trials
    menus.py            start screen, settings, multiplayer room browser
    network.py          LAN / direct-IP multiplayer (socket + threading)
    updater.py          GitHub self-updater
"""
import sys
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
if '--no-update' not in sys.argv:
    try:
        import updater
        updater.run(relaunch=True)          # relaunches the new version itself if it updated
    except SystemExit:
        raise
    except Exception as _ex:
        print('[updater] skipped:', _ex)

from ursina import *

SAVE_FILE = os.path.join(HERE, 'savegame.json')
VERSION_FILE = os.path.join(HERE, 'version.json')
DEFAULT_SETTINGS = {'sens': 40, 'volume': 80, 'fov': 72, 'draw': 1, 'fullscreen': 0, 'name': 'Player', 'last_ip': ''}


def load_save():
    try:
        with open(SAVE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def write_save(data):
    try:
        with open(SAVE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as ex:
        print('[save] could not write save file:', ex)


def read_version():
    try:
        with open(VERSION_FILE) as f:
            return json.load(f).get('version', '1.0.0')
    except Exception:
        return '1.0.0'


try:
    app = Ursina(title='Ursina City', borderless=False, vsync=True, development_mode=False)
except TypeError:                       # older Ursina versions
    app = Ursina(borderless=False, vsync=True)

from world import World, SoundBank, rgb, START_HOUR
from player import Player, CameraRig, HUD
from vehicles import VehicleManager
from npcs import PedManager, TrafficManager, WantedSystem
from items_and_shops import FireworksSystem, ShopSystem, Menu
from menus import MainMenu, SettingsMenu, MultiplayerMenu, MenuCamera, TextField
import network


def _quiet_window():
    window.title = 'Ursina City'
    for name in ('exit_button', 'cog_button', 'entity_counter', 'collider_counter', 'cog_menu'):
        try:
            getattr(window, name).enabled = False
        except Exception:
            pass
    try:
        window.fps_counter.enabled = True
    except Exception:
        pass
    window.color = rgb(150, 180, 220)


class PauseMenu(Menu):
    def __init__(self, game):
        super().__init__(game, 'PAUSED', 0.62, 0.56)

    def build(self):
        self.text('Ursina City v%s' % self.game.version, -0.28, 0.19, 1.0, rgb(200, 200, 200))
        self.button('Resume', 0, 0.09, 0.4, 0.07, self.close, rgb(36, 140, 70))
        self.button('Controls (F1)', 0, 0.0, 0.4, 0.07, self.help)
        if self.game.net is not None:
            self.button('Leave multiplayer', 0, -0.09, 0.4, 0.07, self.leave)
        self.button('Quit game', 0, -0.18, 0.4, 0.07, application.quit, rgb(140, 40, 40))

    def help(self):
        self.close()
        self.game.hud.toggle_help()

    def leave(self):
        self.close()
        self.game.end_multiplayer()
        self.game.hud.notify('Left the multiplayer room.', rgb(200, 200, 200))


class Game(Entity):
    def __init__(self):
        super().__init__()
        self.paused = False
        self.menu = None
        self.interactions = []
        self.net = None
        self.mode = 'menu'
        self.screen = None
        self.version = read_version()
        self.save = load_save()
        self.settings = dict(DEFAULT_SETTINGS)
        self.settings.update(self.save.get('settings', {}))
        print('[city] synthesizing audio ...')
        self.sound = SoundBank()
        print('[city] building the city ...')
        self.world = World(self)
        self.player = None
        self.camera_rig = CameraRig(self)
        self.hud = HUD(self)
        print('[city] spawning vehicles, people and traffic ...')
        self.vehicles = VehicleManager(self)
        self.npcs = PedManager(self)
        self.player = Player(self)
        self.traffic = TrafficManager(self)
        self.wanted = WantedSystem(self)
        self.fireworks = FireworksSystem(self)
        self.shops = ShopSystem(self)
        self.hud.add_activity_blips()
        self.menu_cam = MenuCamera(self)
        self.apply_settings()
        self.enter_main_menu()
        print('[city] ready.')

    # ---- settings / save
    def apply_settings(self):
        st = self.settings
        self.camera_rig.sens = float(st['sens'])
        self.camera_rig.base_fov = float(st['fov'])
        self.sound.master = st['volume'] / 100.0
        self.world.fog_scale = (1.7, 1.0, 0.6)[st['draw']]
        camera.clip_plane_far = (520, 1100, 1600)[st['draw']]
        try:
            if bool(window.fullscreen) != bool(st['fullscreen']):
                window.fullscreen = bool(st['fullscreen'])
        except Exception:
            pass
        self.save['settings'] = st
        write_save(self.save)

    # ---- main menu flow
    def _show(self, screen_cls):
        if self.screen is not None:
            self.screen.close()
        self.screen = screen_cls(self)

    def enter_main_menu(self):
        self.mode = 'menu'
        mouse.locked = False
        self.hud.set_visible(False)
        self.player.body.set_visible(False)
        self.world.hour = 19.4                    # dusk over the city
        self.world.time_scale = 0.25
        self._show(MainMenu)

    def back_to_main(self):
        self.write_settings_only()
        self._show(MainMenu)

    def write_settings_only(self):
        self.save['settings'] = self.settings
        write_save(self.save)

    def open_settings(self):
        self._show(SettingsMenu)

    def open_multiplayer(self):
        self._show(MultiplayerMenu)

    def start_singleplayer(self):
        self._start_play()

    def _start_play(self):
        if self.screen is not None:
            self.screen.close()
            self.screen = None
        self.write_settings_only()
        self.mode = 'play'
        self.world.hour = START_HOUR
        self.world.time_scale = 1.0
        self.hud.set_visible(True)
        self.player.body.set_visible(True)
        self.camera_rig.yaw = 0.0
        self.hud.fade(1.0)
        mouse.locked = True
        self.hud.notify('Welcome to Ursina City!  Press F1 for controls.', rgb(255, 200, 80), 6)
        self.hud.notify('Hop on the KuKirin G2, the E-scooter or the sports car right in front of you.', rgb(200, 200, 200), 6)

    # ---- multiplayer
    def host_multiplayer(self, room_name, private, code, name):
        try:
            host = network.Host(room_name, private, code, name)
        except OSError as ex:
            if isinstance(self.screen, MultiplayerMenu):
                self.screen.say('Could not start the server: %s' % ex)
            return
        self.net = network.NetSession(self, 'host', host, room_name, code, private)
        self._start_play()
        self.hud.notify('Room "%s" is %s%s' % (room_name, 'PRIVATE - code %s' % code if private else 'PUBLIC',
                                               '  |  LAN IP %s' % network.local_ip()), rgb(120, 220, 255), 8)

    def join_multiplayer(self, ip, code, name):
        try:
            client = network.Client(ip, name, code)
        except Exception as ex:
            if isinstance(self.screen, MultiplayerMenu):
                self.screen.say('Could not join: %s' % ex)
            return
        self.net = network.NetSession(self, 'client', client, client.room_name)
        self._start_play()
        self.hud.notify('Joined "%s"' % client.room_name, rgb(120, 220, 255), 6)

    def end_multiplayer(self):
        if self.net is not None:
            self.net.close()
            self.net = None

    # ---- in-game menus
    def open_menu(self, m):
        if self.menu is not None and self.menu is not m:
            self.menu.close()
        self.menu = m
        mouse.locked = False
        self.fireworks.wheel.hide()

    def close_menu(self, m):
        if self.menu is m:
            self.menu = None
            if not self.paused:
                mouse.locked = True
        if isinstance(m, PauseMenu):
            self.paused = False
            mouse.locked = True

    def claim_f9_bonus(self):
        """+5,000 coins, once per save (tracked in savegame.json)."""
        if self.save.get('f9_bonus_claimed'):
            self.hud.notify('F9 bonus already claimed!', rgb(255, 120, 90))
            self.sound.play('error', 0.6)
            return
        self.save['f9_bonus_claimed'] = True
        write_save(self.save)
        self.player.add_cash(5000, 'F9 BONUS')
        self.hud.notify('F9 bonus: +5,000 coins! (one time only)', rgb(120, 255, 140))

    def collect_interactions(self):
        if self.player.state not in ('foot', 'vehicle'):
            return []
        items = self.vehicles.interactions(self.player) + self.shops.interactions(self.player)
        items.sort(key=lambda q: q['dist'])
        return items

    # ---- loop
    def update(self):
        dt = min(time.dt, 1.0 / 20.0)
        if self.mode == 'menu':
            # live background: traffic, pedestrians, fireworks, slow cinematic camera
            self.traffic.update(dt)
            self.vehicles.update(dt)
            self.npcs.update(dt)
            self.fireworks.update(dt)
            self.menu_cam.update(dt)
            self.world.update(dt, camera.world_position)
            if self.screen is not None:
                self.screen.tick(dt)
            return
        if self.paused:
            self.vehicles.silence()
            if self.net is not None:
                self.net.update(dt)          # keep the connection alive while paused
            return
        self.player.update(dt)
        self.traffic.update(dt)
        self.wanted.update(dt)
        self.vehicles.update(dt)
        self.npcs.update(dt)
        self.fireworks.update(dt)
        self.shops.update(dt)
        if self.net is not None:
            self.net.update(dt)
        self.camera_rig.update(dt)
        self.world.update(dt, camera.world_position)
        self.interactions = self.collect_interactions()
        self.hud.update(dt)

    def input(self, key):
        if self.mode == 'menu':
            if self.screen is not None and self.screen.key(key):
                return
            if key == 'escape' and not isinstance(self.screen, MainMenu):
                self.back_to_main()
            return
        if key == 'escape':
            if self.hud.help_panel is not None:
                self.hud.toggle_help()
            elif self.menu is not None:
                self.menu.close()
            else:
                self.paused = True
                PauseMenu(self)
            return
        if self.paused or self.menu is not None:
            return
        pl = self.player
        fw = self.fireworks
        if key == 'f1':
            self.hud.toggle_help()
        elif key == 'v':
            self.camera_rig.toggle()
        elif key == 't':
            self.world.toggle_day_night()
            self.hud.notify('Time set to %s' % self.world.clock_text(), rgb(200, 220, 255))
        elif key == 'tab':
            fw.wheel.show()
        elif key == 'tab up':
            fw.wheel.hide()
        elif key in ('1', '2', '3'):
            fw.select(int(key) - 1)
        elif key == 'scroll up':
            fw.cycle(1)
        elif key == 'scroll down':
            fw.cycle(-1)
        elif key == 'left mouse down':
            if not fw.wheel.open:
                fw.throw()
        elif key == 'r':
            if pl.vehicle is not None:
                pl.vehicle.reset_upright()
        elif key == 'f9':
            self.claim_f9_bonus()
        elif key in ('e', 'b', 'q'):
            for it in self.interactions:
                if it['key'] == key and it['action'] is not None:
                    it['action']()
                    return
            if key == 'e' and pl.vehicle is not None:
                pl.exit_vehicle()


if __name__ == '__main__':
    _quiet_window()
    game = Game()
    app.run()

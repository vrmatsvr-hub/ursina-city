"""
network.py  -  LAN / direct-IP multiplayer for Ursina City
============================================================

Pure Python `socket` + `threading`, no extra libraries.

* The HOST runs a TCP server (port 47500). Every client sends its own state
  (character, vehicle, fireworks it throws) ~15x per second; the host relays
  everything to everybody. Sockets are read on background threads and all
  messages are handed to the game thread through a queue (Ursina is not
  thread-safe).
* LAN discovery: clients broadcast a UDP packet on port 47501, hosts answer with
  their room name, player count and whether the room is PRIVATE.
* PRIVATE rooms require the room code; PUBLIC rooms are open to everyone.
* Optional UPnP: the host asks the router to forward port 47500 so friends on
  the internet can join with the host's public IP + room code.

What is synced: player characters (walk / run / jump / ride poses), the cars,
E-scooters, E-motorbikes and KuKirin G2s they drive, and every Cobra 6 /
Scream 100 they throw (each client simulates the firework, so explosions knock
everyone around). Traffic, pedestrians and police stay local to each player.
"""
import json
import math
import queue
import random
import socket
import string
import threading
import time as _time
import urllib.request
import re

PORT = 47500
DISCOVERY_PORT = 47501
PROTOCOL = 1
MAGIC = b'URSINA_CITY_DISCOVER_V1'
SEND_RATE = 15.0
MAX_PLAYERS = 8


# ------------------------------------------------------------------ helpers
def make_code(n=5):
    return ''.join(random.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(n))


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))       # no packet is actually sent
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


class _Conn:
    """Newline-delimited JSON over a TCP socket."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b''
        self.lock = threading.Lock()
        self.alive = True
        self.last_rx = _time.time()

    def send(self, msg):
        if not self.alive:
            return
        data = (json.dumps(msg, separators=(',', ':')) + '\n').encode()
        try:
            with self.lock:
                self.sock.sendall(data)
        except OSError:
            self.alive = False

    def read_lines(self):
        try:
            chunk = self.sock.recv(65536)
        except socket.timeout:
            return []
        except OSError:
            self.alive = False
            return None
        if not chunk:
            self.alive = False
            return None
        self.last_rx = _time.time()
        self.buf += chunk
        out = []
        while b'\n' in self.buf:
            line, self.buf = self.buf.split(b'\n', 1)
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        return out

    def close(self):
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass


# ------------------------------------------------------------------ UPnP (best effort)
def upnp_forward(port, desc='Ursina City'):
    """Asks the router (UPnP IGD) to forward TCP `port` to this PC. Returns the public IP or None."""
    try:
        ssdp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        ssdp.settimeout(2.0)
        req = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\n'
               'ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n')
        ssdp.sendto(req.encode(), ('239.255.255.250', 1900))
        data, _ = ssdp.recvfrom(4096)
        ssdp.close()
        loc = re.search(r'(?i)location:\s*(\S+)', data.decode(errors='ignore')).group(1)
        xml = urllib.request.urlopen(loc, timeout=3).read().decode(errors='ignore')
        svc = None
        for st in ('WANIPConnection:1', 'WANIPConnection:2', 'WANPPPConnection:1'):
            m = re.search(r'<serviceType>urn:schemas-upnp-org:service:%s</serviceType>.*?<controlURL>(.*?)</controlURL>' % st,
                          xml, re.S)
            if m:
                svc = (st, m.group(1))
                break
        if svc is None:
            return None
        base = re.match(r'(https?://[^/]+)', loc).group(1)
        url = svc[1] if svc[1].startswith('http') else base + svc[1]
        stype = 'urn:schemas-upnp-org:service:' + svc[0]

        def soap(action, args):
            body = ''.join('<%s>%s</%s>' % (k, v, k) for k, v in args)
            env = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                   's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:%s xmlns:u="%s">%s</u:%s>'
                   '</s:Body></s:Envelope>') % (action, stype, body, action)
            r = urllib.request.Request(url, env.encode(), {'Content-Type': 'text/xml; charset="utf-8"',
                                                           'SOAPAction': '"%s#%s"' % (stype, action)})
            return urllib.request.urlopen(r, timeout=3).read().decode(errors='ignore')
        soap('AddPortMapping', [('NewRemoteHost', ''), ('NewExternalPort', port), ('NewProtocol', 'TCP'),
                                ('NewInternalPort', port), ('NewInternalClient', local_ip()), ('NewEnabled', 1),
                                ('NewPortMappingDescription', desc), ('NewLeaseDuration', 0)])
        res = soap('GetExternalIPAddress', [])
        m = re.search(r'<NewExternalIPAddress>(.*?)</NewExternalIPAddress>', res)
        return m.group(1) if m else 'unknown'
    except Exception:
        return None


# ------------------------------------------------------------------ host
class Host:
    def __init__(self, room_name, private, code, host_name, port=PORT):
        self.room_name = room_name or 'Ursina City Room'
        self.private = bool(private)
        self.code = (code or '').strip().upper()
        self.port = port
        self.inbox = queue.Queue()
        self.clients = {}           # id -> _Conn
        self.names = {0: host_name}
        self.next_id = 1
        self.running = True
        self.public_ip = None
        self.upnp_status = 'UPnP: trying ...'
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(('', port))
        self.server.listen(8)
        self.server.settimeout(0.5)
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._discovery_loop, daemon=True).start()
        threading.Thread(target=self._upnp, daemon=True).start()

    def player_count(self):
        return 1 + len(self.clients)

    def _upnp(self):
        ip = upnp_forward(self.port)
        if ip:
            self.public_ip = ip
            self.upnp_status = 'UPnP OK - internet IP %s' % ip
        else:
            self.upnp_status = 'UPnP unavailable (LAN / port-forward 47500)'

    def _discovery_loop(self):
        try:
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            u.bind(('', DISCOVERY_PORT))
            u.settimeout(0.5)
        except OSError:
            return
        while self.running:
            try:
                data, addr = u.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            if data == MAGIC:
                info = dict(name=self.room_name, players=self.player_count(), max=MAX_PLAYERS,
                            private=self.private, port=self.port, proto=PROTOCOL)
                try:
                    u.sendto(json.dumps(info).encode(), addr)
                except OSError:
                    pass
        u.close()

    def _accept_loop(self):
        while self.running:
            try:
                sock, addr = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sock.settimeout(5.0)
            threading.Thread(target=self._client_loop, args=(sock,), daemon=True).start()

    def _client_loop(self, sock):
        conn = _Conn(sock)
        cid = None
        # handshake
        deadline = _time.time() + 6
        while cid is None and conn.alive and _time.time() < deadline:
            msgs = conn.read_lines()
            if msgs is None:
                break
            for m in msgs:
                if m.get('t') != 'hello':
                    continue
                if m.get('proto') != PROTOCOL:
                    conn.send({'t': 'reject', 'reason': 'Different game version'})
                elif self.private and str(m.get('code', '')).strip().upper() != self.code:
                    conn.send({'t': 'reject', 'reason': 'Wrong room code'})
                elif self.player_count() >= MAX_PLAYERS:
                    conn.send({'t': 'reject', 'reason': 'Room is full'})
                else:
                    cid = self.next_id
                    self.next_id += 1
                    name = str(m.get('name', 'Player'))[:16] or 'Player'
                    self.names[cid] = name
                    self.clients[cid] = conn
                    conn.send({'t': 'welcome', 'id': cid, 'room': self.room_name,
                               'players': [{'id': k, 'name': v} for k, v in self.names.items()]})
                    self.broadcast({'t': 'join', 'id': cid, 'name': name}, exclude=cid)
                    self.inbox.put({'t': 'join', 'id': cid, 'name': name})
                break
        if cid is None:
            conn.close()
            return
        sock.settimeout(1.0)
        while self.running and conn.alive:
            msgs = conn.read_lines()
            if msgs is None:
                break
            for m in msgs:
                m['id'] = cid
                if m.get('t') in ('state', 'fw', 'chat'):
                    self.broadcast(m, exclude=cid)
                    self.inbox.put(m)
            if _time.time() - conn.last_rx > 10:
                break
        conn.close()
        self.clients.pop(cid, None)
        self.names.pop(cid, None)
        self.broadcast({'t': 'leave', 'id': cid})
        self.inbox.put({'t': 'leave', 'id': cid})

    def broadcast(self, msg, exclude=None):
        for cid, c in list(self.clients.items()):
            if cid != exclude:
                c.send(msg)

    def send(self, msg):
        """Messages from the host player itself."""
        msg['id'] = 0
        self.broadcast(msg)

    def close(self):
        self.running = False
        self.broadcast({'t': 'bye'})
        for c in list(self.clients.values()):
            c.close()
        try:
            self.server.close()
        except OSError:
            pass


# ------------------------------------------------------------------ client
class Client:
    def __init__(self, ip, name, code='', port=PORT):
        self.inbox = queue.Queue()
        self.running = True
        sock = socket.create_connection((ip, port), timeout=4.0)
        self.conn = _Conn(sock)
        self.conn.send({'t': 'hello', 'name': name, 'code': code, 'proto': PROTOCOL})
        deadline = _time.time() + 5.0
        self.id = None
        self.room_name = '?'
        self.players = []
        while self.id is None and _time.time() < deadline:
            msgs = self.conn.read_lines()
            if msgs is None:
                raise ConnectionError('Connection closed by host')
            for m in msgs:
                if m.get('t') == 'reject':
                    self.conn.close()
                    raise ConnectionError(m.get('reason', 'Rejected'))
                if m.get('t') == 'welcome':
                    self.id = m['id']
                    self.room_name = m.get('room', '?')
                    self.players = m.get('players', [])
        if self.id is None:
            self.conn.close()
            raise ConnectionError('No answer from host')
        sock.settimeout(1.0)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running and self.conn.alive:
            msgs = self.conn.read_lines()
            if msgs is None:
                break
            for m in msgs:
                self.inbox.put(m)
        self.inbox.put({'t': 'bye'})

    def send(self, msg):
        msg['id'] = self.id
        self.conn.send(msg)

    def close(self):
        self.running = False
        self.conn.close()


# ------------------------------------------------------------------ LAN room browser
class LanBrowser:
    """Broadcasts discovery pings every 2 s and keeps a list of rooms that answered."""

    def __init__(self):
        self.rooms = {}
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            found = {}
            try:
                u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                u.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                u.settimeout(0.4)
                for target in ('255.255.255.255', '127.0.0.1'):
                    try:
                        u.sendto(MAGIC, (target, DISCOVERY_PORT))
                    except OSError:
                        pass
                end = _time.time() + 0.9
                while _time.time() < end:
                    try:
                        data, addr = u.recvfrom(2048)
                    except socket.timeout:
                        continue
                    try:
                        info = json.loads(data)
                    except ValueError:
                        continue
                    ip = addr[0]
                    if ip.startswith('127.'):
                        ip = local_ip()
                    info['ip'] = ip
                    found['%s:%s' % (ip, info.get('port'))] = info
                u.close()
            except OSError:
                pass
            self.rooms = found
            for _ in range(12):
                if not self.running:
                    return
                _time.sleep(0.1)

    def list(self):
        return sorted(self.rooms.values(), key=lambda r: (r.get('private', False), r.get('name', '')))

    def stop(self):
        self.running = False


# ------------------------------------------------------------------ in-game session
PLAYER_COLORS = [(230, 60, 60), (60, 130, 240), (60, 200, 90), (240, 190, 40), (200, 80, 220), (40, 210, 210),
                 (250, 130, 40), (240, 240, 240)]


class RemotePlayer:
    def __init__(self, session, pid, name):
        from ursina import Text, scene, color
        from npcs import Humanoid
        from world import rgb
        self.s = session
        self.game = session.game
        self.id = pid
        self.name = name
        c = PLAYER_COLORS[pid % len(PLAYER_COLORS)]
        self.body = Humanoid(shirt=rgb(*c), pants=rgb(40, 40, 50), cap=rgb(*c))
        self.tag = Text(text=name, parent=scene, origin=(0, 0), scale=12, color=rgb(*c), billboard=True)
        self.target = None
        self.pos = [0.0, 0.0, 0.0]
        self.yaw = 0.0
        self.vehicle = None
        self.vkind = None
        self.last_rx = _time.time()

    def apply(self, st):
        self.target = st
        self.last_rx = _time.time()

    def _ensure_vehicle(self, vs):
        g = self.game
        kind = vs['k']
        if self.vehicle is not None and self.vkind == kind:
            return
        self._drop_vehicle()
        if kind in ('scooter', 'motorbike', 'kickscooter'):
            v = g.vehicles.spawn_two_wheeler(kind, vs['x'], vs['z'], vs['h'])
            v.primary, v.accent = vs.get('pr', v.primary), vs.get('ac', v.accent)
            v.build_model()
        else:
            from world import Color
            col = vs.get('c')
            v = g.vehicles.spawn_car(kind, vs['x'], vs['z'], vs['h'], Color(*col) if col else None)
        v.remote = True
        v.driver = 'remote'
        self.vehicle = v
        self.vkind = kind
        if v.is_two_wheeler:
            self.body.root.parent = v.seat
            self.body.root.rotation = (0, 0, 0)
            if v.standing:
                self.body.root.position = (0, 0, 0)
                self.body.set_pose('stand_ride')
            else:
                self.body.root.position = (0, -0.93, 0.05)
                self.body.set_pose('seated')
            self.body.set_visible(True)
        else:
            v.set_npc_driver(True)
            self.body.set_visible(False)

    def _drop_vehicle(self):
        from ursina import scene
        if self.vehicle is not None:
            self.body.root.parent = scene
            self.body.root.rotation = (0, 0, 0)
            self.game.vehicles.remove(self.vehicle)
            self.vehicle = None
            self.vkind = None
        self.body.set_pose('walk')
        self.body.set_visible(True)

    def update(self, dt):
        st = self.target
        if st is None:
            return
        vs = st.get('v')
        if vs:
            self._ensure_vehicle(vs)
            v = self.vehicle
            if v.is_two_wheeler and (v.primary != vs.get('pr', v.primary) or v.accent != vs.get('ac', v.accent)):
                v.repaint(vs.get('pr'), vs.get('ac'))
            v.net_target = vs
            if v.is_two_wheeler:
                if v.standing:
                    self.body.grips = v.grip_targets()
                self.body.animate(dt, 0)
            p = (v.x, v.y, v.z)
            self.tag.position = (v.x, v.y + 2.6, v.z)
            self.pos = list(p)
        else:
            if self.vehicle is not None:
                self._drop_vehicle()
            tx, ty, tz = st['p']
            k = 1.0 - math.exp(-dt * 14.0)
            for i, t in enumerate((tx, ty, tz)):
                self.pos[i] += (t - self.pos[i]) * k
            self.yaw += (((st.get('yaw', 0) - self.yaw + 180) % 360) - 180) * k
            b = self.body
            b.set_pose(st.get('pose', 'walk'))
            b.jump_mode = st.get('jm')
            b.air_vy = st.get('vy', 0.0)
            if b.jump_mode is not None:
                b.jump_t = st.get('jt', 0.0)
            r = b.root
            r.position = tuple(self.pos)
            r.rotation_y = self.yaw
            r.rotation_x = st.get('rx', 0.0)
            b.animate(dt, st.get('spd', 0.0))
            self.tag.position = (self.pos[0], self.pos[1] + 2.25, self.pos[2])

    def destroy(self):
        from ursina import destroy
        self._drop_vehicle()
        self.body.destroy()
        destroy(self.tag)


class NetSession:
    """Glue between the game and Host / Client."""

    def __init__(self, game, role, link, room_name, code='', private=False):
        self.game = game
        self.role = role                 # 'host' or 'client'
        self.link = link
        self.room_name = room_name
        self.code = code
        self.private = private
        self.remotes = {}
        self.send_t = 0.0
        self.my_id = 0 if role == 'host' else link.id
        if role == 'client':
            for p in link.players:
                if p['id'] != self.my_id:
                    self._add(p['id'], p['name'])

    # ---- outgoing
    def _state(self):
        pl = self.game.player
        st = {'t': 'state', 'p': [round(pl.pos.x, 3), round(pl.pos.y, 3), round(pl.pos.z, 3)],
              'yaw': round(pl.yaw, 1), 'spd': round(pl.h_speed, 2), 'pose': pl.body.pose,
              'jm': pl.body.jump_mode, 'jt': round(pl.body.jump_t, 3), 'vy': round(pl.vel_y, 2),
              'rx': round(pl.body.root.rotation_x, 1)}
        v = pl.vehicle
        if v is not None:
            vs = {'k': v.kind, 'x': round(v.x, 3), 'y': round(v.y, 3), 'z': round(v.z, 3), 'h': round(v.heading, 2),
                  'vx': round(v.vx, 2), 'vz': round(v.vz, 2), 'st': round(v.steer, 2), 'th': round(v.throttle, 2),
                  'hb': 1 if v.handbrake else 0}
            if v.is_two_wheeler:
                vs['pr'], vs['ac'] = v.primary, v.accent
                vs['wh'] = round(v.wheelie, 1)
            else:
                vs['c'] = [round(c, 3) for c in v.color]
            st['v'] = vs
        return st

    def send_firework(self, kind, pos, vel):
        self.link.send({'t': 'fw', 'kind': kind, 'pos': [round(c, 3) for c in pos], 'vel': [round(c, 3) for c in vel]})

    # ---- incoming
    def _add(self, pid, name):
        if pid not in self.remotes and pid != self.my_id:
            self.remotes[pid] = RemotePlayer(self, pid, name)

    def _remove(self, pid):
        r = self.remotes.pop(pid, None)
        if r is not None:
            r.destroy()
            return r.name
        return None

    def update(self, dt):
        from world import rgb
        g = self.game
        while True:
            try:
                m = self.link.inbox.get_nowait()
            except queue.Empty:
                break
            t = m.get('t')
            pid = m.get('id')
            if t == 'state':
                if pid not in self.remotes:
                    self._add(pid, (self.link.names.get(pid) if self.role == 'host' else None) or 'Player %d' % pid)
                if pid in self.remotes:
                    self.remotes[pid].apply(m)
            elif t == 'fw':
                g.fireworks.spawn_remote(m['kind'], m['pos'], m['vel'])
            elif t == 'join':
                self._add(pid, m.get('name', 'Player'))
                g.hud.notify('%s joined the room' % m.get('name', 'Player'), rgb(120, 220, 255))
                g.sound.play('blip', 0.6)
            elif t == 'leave':
                name = self._remove(pid)
                if name:
                    g.hud.notify('%s left the room' % name, rgb(200, 200, 200))
            elif t == 'bye' and self.role == 'client':
                g.hud.notify('Disconnected from the host - continuing in singleplayer', rgb(255, 120, 90), 6)
                g.end_multiplayer()
                return
        self.send_t += dt
        if self.send_t >= 1.0 / SEND_RATE:
            self.send_t = 0.0
            self.link.send(self._state())
        for r in list(self.remotes.values()):
            r.update(dt)
            if _time.time() - r.last_rx > 12:
                self._remove(r.id)

    def hud_text(self):
        n = 1 + len(self.remotes)
        if self.role == 'host':
            h = self.link
            txt = 'HOSTING "%s"  %d/%d players  LAN IP %s' % (self.room_name, n, MAX_PLAYERS, local_ip())
            if self.private:
                txt += '  CODE %s' % self.code
            return txt + '\n' + h.upnp_status
        return 'ONLINE "%s"  %d players' % (self.room_name, n)

    def close(self):
        for pid in list(self.remotes):
            self._remove(pid)
        self.link.close()

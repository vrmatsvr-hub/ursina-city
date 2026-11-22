"""
network.py  -  code-only multiplayer for Ursina City
======================================================

Players only ever type a ROOM CODE - no IP addresses, no port forwarding.

* Same Wi-Fi / LAN: the host answers UDP discovery pings (port 47501) and the
  game connects straight to it over TCP (port 47500) - fastest.
* Over the internet: host and players meet on a free public MQTT relay server
  (broker.hivemq.com, with fallbacks). All game messages for room ABC12 travel
  on the topics  ursinacity/v1/ABC12/... , so the code is the address.
* PUBLIC rooms are announced in the room list (LAN + internet); PRIVATE rooms
  are never listed - you can only join them if someone gives you the code.

Everything is pure Python `socket` + `threading`. Sockets are read on background
threads; all messages reach the game thread through a queue.

Synced: player characters (walk / run / jump / ride poses), the cars, scooters,
e-motorbikes and KuKirin G2s they drive (incl. wheelies) and every Cobra 6 /
Scream 100 they throw. Traffic, pedestrians and police stay local.
"""
import hashlib
import json
import math
import queue
import random
import socket
import struct
import threading
import time as _time

PORT = 47500
DISCOVERY_PORT = 47501
PROTOCOL = 2
MAGIC = b'URSINA_CITY_DISCOVER_V2'
SEND_RATE = 15.0
MAX_PLAYERS = 8
TOPIC_ROOT = 'ursinacity/v1'
BROKERS = [('broker.hivemq.com', 1883), ('broker.emqx.io', 1883), ('test.mosquitto.org', 1883)]
CODE_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


# ------------------------------------------------------------------ helpers
def make_code(n=5):
    return ''.join(random.choice(CODE_CHARS) for _ in range(n))


def clean_code(code):
    return ''.join(ch for ch in str(code).upper() if ch.isalnum())[:8]


def safe_text(s, n=24):
    """Ursina treats < and > as formatting tags - strip them from anything another player typed."""
    return ''.join(ch for ch in str(s) if ch not in '<>\n\r')[:n]


def code_hash(code):
    return hashlib.sha1(('ursinacity:' + clean_code(code)).encode()).hexdigest()[:12]


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


# ------------------------------------------------------------------ tiny MQTT 3.1.1 client (QoS 0)
def _mqtt_str(s):
    b = s.encode('utf-8')
    return struct.pack('!H', len(b)) + b


def _mqtt_len(n):
    out = b''
    while True:
        d = n % 128
        n //= 128
        out += bytes([d | (0x80 if n > 0 else 0)])
        if n == 0:
            return out


class MqttLink:
    """Just enough MQTT to use a public broker as a relay: connect, subscribe, publish, last will."""

    def __init__(self, on_message, will_topic=None, will_payload=b'', will_retain=False, brokers=None, timeout=5.0):
        self.on_message = on_message
        self.lock = threading.Lock()
        self.alive = False
        self.broker = None
        self.pid = 1
        err = None
        for host, port in (brokers or BROKERS):
            try:
                self._connect(host, port, will_topic, will_payload, will_retain, timeout)
                self.broker = host
                break
            except Exception as ex:
                err = ex
        if self.broker is None:
            raise ConnectionError('no relay server reachable (%s)' % err)
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._pinger, daemon=True).start()

    def _connect(self, host, port, will_topic, will_payload, will_retain, timeout):
        sock = socket.create_connection((host, port), timeout=timeout)
        cid = 'uc-' + ''.join(random.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(12))
        flags = 0x02
        payload = _mqtt_str(cid)
        if will_topic:
            flags |= 0x04 | (0x20 if will_retain else 0)
            payload += _mqtt_str(will_topic) + struct.pack('!H', len(will_payload)) + will_payload
        var = _mqtt_str('MQTT') + bytes([4, flags]) + struct.pack('!H', 30)
        body = var + payload
        sock.sendall(bytes([0x10]) + _mqtt_len(len(body)) + body)
        hdr = self._recv_exact(sock, 4)
        if hdr[0] != 0x20 or hdr[3] != 0:
            sock.close()
            raise ConnectionError('broker refused the connection')
        sock.settimeout(None)
        self.sock = sock
        self.alive = True

    @staticmethod
    def _recv_exact(sock, n):
        data = b''
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError('connection closed')
            data += chunk
        return data

    def _send(self, data):
        if not self.alive:
            return
        try:
            with self.lock:
                self.sock.sendall(data)
        except OSError:
            self.alive = False

    def subscribe(self, topic):
        self.pid = self.pid % 65000 + 1
        body = struct.pack('!H', self.pid) + _mqtt_str(topic) + b'\x00'
        self._send(bytes([0x82]) + _mqtt_len(len(body)) + body)

    def publish(self, topic, payload, retain=False):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, separators=(',', ':'))
        if isinstance(payload, str):
            payload = payload.encode()
        body = _mqtt_str(topic) + payload
        self._send(bytes([0x30 | (1 if retain else 0)]) + _mqtt_len(len(body)) + body)

    def _pinger(self):
        while self.alive:
            _time.sleep(15)
            self._send(b'\xc0\x00')

    def _loop(self):
        s = self.sock
        try:
            while self.alive:
                h = self._recv_exact(s, 1)[0]
                mult, length = 1, 0
                while True:
                    d = self._recv_exact(s, 1)[0]
                    length += (d & 127) * mult
                    mult *= 128
                    if not d & 128:
                        break
                body = self._recv_exact(s, length) if length else b''
                if h >> 4 == 3:                                   # PUBLISH
                    tl = struct.unpack('!H', body[:2])[0]
                    topic = body[2:2 + tl].decode('utf-8', 'ignore')
                    off = 2 + tl + (2 if (h >> 1) & 3 else 0)
                    try:
                        self.on_message(topic, body[off:])
                    except Exception as ex:
                        print('[net] message error:', ex)
        except Exception:
            pass
        self.alive = False
        try:
            self.on_message(None, None)                           # tell the owner we lost the relay
        except Exception:
            pass

    def close(self):
        if self.alive:
            self._send(b'\xe0\x00')                               # DISCONNECT (will is not sent)
        self.alive = False
        try:
            self.sock.close()
        except Exception:
            pass


def _decode(payload):
    try:
        return json.loads(payload)
    except Exception:
        return None


# ------------------------------------------------------------------ host
class Host:
    """Runs the room: LAN TCP server + internet relay bridge. Every player's messages go through here."""

    def __init__(self, room_name, private, code, host_name, port=PORT):
        self.room_name = safe_text(room_name or 'Ursina City', 24) or 'Ursina City'
        self.private = bool(private)
        self.code = clean_code(code) or make_code()
        self.hash = code_hash(self.code)
        self.port = port
        self.inbox = queue.Queue()
        self.lock = threading.Lock()
        self.tcp = {}              # id -> _Conn (LAN players)
        self.remote = {}           # id -> last seen time (internet players)
        self.tokens = {}           # relay token -> id
        self.names = {0: host_name}
        self.next_id = 1
        self.running = True
        self.lan_ok = False
        self.relay = None
        self.relay_status = 'Internet relay: connecting ...'
        self.base = '%s/%s/' % (TOPIC_ROOT, self.code)
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind(('', port))
            self.server.listen(8)
            self.server.settimeout(0.5)
            self.lan_ok = True
            threading.Thread(target=self._accept_loop, daemon=True).start()
            threading.Thread(target=self._discovery_loop, daemon=True).start()
        except OSError as ex:
            print('[net] LAN server unavailable:', ex)
        threading.Thread(target=self._start_relay, daemon=True).start()

    # ---- bookkeeping
    def player_count(self):
        return 1 + len(self.tcp) + len(self.remote)

    def _room_info(self):
        return dict(name=self.room_name, players=self.player_count(), max=MAX_PLAYERS, private=self.private,
                    hash=self.hash, code=None if self.private else self.code, proto=PROTOCOL, port=self.port)

    def _new_player(self, name):
        with self.lock:
            pid = self.next_id
            self.next_id += 1
            self.names[pid] = (safe_text(name, 16) or 'Player')
        return pid

    def _check_hello(self, m):
        if m.get('proto') != PROTOCOL:
            return 'Different game version - update the game'
        if self.player_count() >= MAX_PLAYERS:
            return 'Room is full'
        return None

    # ---- internet relay
    def _start_relay(self):
        try:
            will = '%s/rooms/%s' % (TOPIC_ROOT, self.code) if not self.private else None
            self.relay = MqttLink(self._on_relay, will_topic=will, will_payload=b'', will_retain=True)
            self.relay.subscribe(self.base + 'c2h')
            self.relay_status = 'Internet: ON (relay %s)' % self.relay.broker
            threading.Thread(target=self._announce_loop, daemon=True).start()
        except Exception as ex:
            self.relay = None
            self.relay_status = 'Internet relay unreachable - LAN only'
            print('[net]', ex)

    def _announce_loop(self):
        while self.running and self.relay is not None and self.relay.alive:
            if not self.private:
                self.relay.publish('%s/rooms/%s' % (TOPIC_ROOT, self.code), self._room_info(), retain=True)
            now = _time.time()
            for pid, seen in list(self.remote.items()):
                if now - seen > 12:
                    self._drop(pid)
            for _ in range(50):
                if not self.running:
                    return
                _time.sleep(0.1)

    def _on_relay(self, topic, payload):
        if topic is None:
            self.relay_status = 'Internet relay lost - LAN only'
            return
        m = _decode(payload)
        if not isinstance(m, dict):
            return
        if m.get('t') == 'hello':
            tok = str(m.get('tok', ''))
            if tok in self.tokens:                        # our welcome got lost - send it again
                pid = self.tokens[tok]
                self.relay.publish(self.base + 'h2c', {'t': 'welcome', 'to': tok, 'id': pid, 'room': self.room_name,
                                                       'players': [{'id': k, 'name': v} for k, v in self.names.items()]})
                return
            why = self._check_hello(m)
            if why:
                self.relay.publish(self.base + 'h2c', {'t': 'reject', 'to': tok, 'reason': why})
                return
            pid = self._new_player(m.get('name', 'Player'))
            self.tokens[tok] = pid
            self.remote[pid] = _time.time()
            self.relay.publish(self.base + 'h2c', {'t': 'welcome', 'to': tok, 'id': pid, 'room': self.room_name,
                                                   'players': [{'id': k, 'name': v} for k, v in self.names.items()]})
            self._joined(pid)
            return
        pid = m.get('id')
        if pid not in self.remote:
            return
        self.remote[pid] = _time.time()
        if m.get('t') == 'leave':
            self._drop(pid)
        elif m.get('t') in ('state', 'fw', 'fwl', 'fwx'):
            self.broadcast(m, exclude=pid)
            self.inbox.put(m)

    # ---- LAN
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
                try:
                    u.sendto(json.dumps(self._room_info()).encode(), addr)
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
            threading.Thread(target=self._tcp_loop, args=(sock,), daemon=True).start()

    def _tcp_loop(self, sock):
        conn = _Conn(sock)
        pid = None
        deadline = _time.time() + 6
        while pid is None and conn.alive and _time.time() < deadline:
            msgs = conn.read_lines()
            if msgs is None:
                break
            for m in msgs:
                if m.get('t') != 'hello':
                    continue
                why = self._check_hello(m)
                if not why and clean_code(m.get('code', '')) != self.code:
                    why = 'Wrong room code'
                if why:
                    conn.send({'t': 'reject', 'reason': why})
                else:
                    pid = self._new_player(m.get('name', 'Player'))
                    self.tcp[pid] = conn
                    conn.send({'t': 'welcome', 'id': pid, 'room': self.room_name,
                               'players': [{'id': k, 'name': v} for k, v in self.names.items()]})
                    self._joined(pid)
                break
        if pid is None:
            conn.close()
            return
        sock.settimeout(1.0)
        while self.running and conn.alive:
            msgs = conn.read_lines()
            if msgs is None:
                break
            for m in msgs:
                m['id'] = pid
                if m.get('t') in ('state', 'fw', 'fwl', 'fwx'):
                    self.broadcast(m, exclude=pid)
                    self.inbox.put(m)
            if _time.time() - conn.last_rx > 12:
                break
        conn.close()
        self._drop(pid)

    # ---- shared
    def _joined(self, pid):
        msg = {'t': 'join', 'id': pid, 'name': self.names.get(pid, 'Player')}
        self.broadcast(msg, exclude=pid)
        self.inbox.put(msg)

    def _drop(self, pid):
        with self.lock:
            existed = self.tcp.pop(pid, None) is not None or self.remote.pop(pid, None) is not None
            self.names.pop(pid, None)
            for tok, p in list(self.tokens.items()):
                if p == pid:
                    self.tokens.pop(tok, None)
        if existed:
            self.broadcast({'t': 'leave', 'id': pid})
            self.inbox.put({'t': 'leave', 'id': pid})

    def broadcast(self, msg, exclude=None):
        for pid, c in list(self.tcp.items()):
            if pid != exclude:
                c.send(msg)
        if self.relay is not None and self.remote:
            self.relay.publish(self.base + 'h2c', msg)       # internet players ignore their own id

    def send(self, msg):
        """Messages from the host player itself."""
        msg['id'] = 0
        self.broadcast(msg)

    def close(self):
        self.running = False
        self.broadcast({'t': 'bye'})
        for c in list(self.tcp.values()):
            c.close()
        if self.relay is not None:
            if not self.private:
                self.relay.publish('%s/rooms/%s' % (TOPIC_ROOT, self.code), b'', retain=True)
            self.relay.close()
        try:
            self.server.close()
        except Exception:
            pass


# ------------------------------------------------------------------ joining
def lan_lookup(code_or_hash, wait=1.0):
    """Asks the local network who hosts this code. Returns (ip, port) or None."""
    h = code_hash(code_or_hash)
    for room in lan_scan(wait):
        if room.get('hash') == h:
            return room['ip'], room.get('port', PORT)
    return None


def lan_scan(wait=0.9):
    found = {}
    try:
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        u.settimeout(0.3)
        for target in ('255.255.255.255', '127.0.0.1'):
            try:
                u.sendto(MAGIC, (target, DISCOVERY_PORT))
            except OSError:
                pass
        end = _time.time() + wait
        while _time.time() < end:
            try:
                data, addr = u.recvfrom(2048)
            except socket.timeout:
                continue
            info = _decode(data)
            if not isinstance(info, dict):
                continue
            ip = addr[0]
            if ip.startswith('127.'):
                ip = local_ip()
            info['ip'] = ip
            info['where'] = 'LAN'
            found[info.get('hash', ip)] = info
        u.close()
    except OSError:
        pass
    return list(found.values())


class Client:
    """Joins a room by code: tries the local network first, then the internet relay."""

    def __init__(self, code, name):
        self.code = clean_code(code)
        if len(self.code) < 4:
            raise ConnectionError('Room codes are 4-6 characters')
        self.inbox = queue.Queue()
        self.running = True
        self.id = None
        self.room_name = '?'
        self.players = []
        self.via = None
        self.conn = None
        self.relay = None
        target = lan_lookup(self.code, 1.0)
        if target is not None:
            self._join_lan(target, name)
        else:
            self._join_relay(name)

    # ---- LAN path
    def _join_lan(self, target, name):
        sock = socket.create_connection(target, timeout=4.0)
        self.conn = _Conn(sock)
        self.conn.send({'t': 'hello', 'name': name, 'code': self.code, 'proto': PROTOCOL})
        deadline = _time.time() + 5.0
        while self.id is None and _time.time() < deadline:
            msgs = self.conn.read_lines()
            if msgs is None:
                raise ConnectionError('Connection closed by host')
            for m in msgs:
                self._handshake(m)
        if self.id is None:
            self.conn.close()
            raise ConnectionError('No answer from host')
        self.via = 'LAN'
        sock.settimeout(1.0)
        threading.Thread(target=self._lan_loop, daemon=True).start()

    def _lan_loop(self):
        while self.running and self.conn.alive:
            msgs = self.conn.read_lines()
            if msgs is None:
                break
            for m in msgs:
                self.inbox.put(m)
        if self.running:
            self.inbox.put({'t': 'bye'})

    # ---- internet path
    def _join_relay(self, name):
        self.base = '%s/%s/' % (TOPIC_ROOT, self.code)
        self.tok = ''.join(random.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(10))
        self._hs = queue.Queue()
        self.relay = MqttLink(self._on_relay)
        self.relay.subscribe(self.base + 'h2c')
        hello = {'t': 'hello', 'tok': self.tok, 'name': name, 'proto': PROTOCOL}
        deadline = _time.time() + 7.0
        next_hello = 0.0
        while self.id is None and _time.time() < deadline:
            if _time.time() >= next_hello:
                self.relay.publish(self.base + 'c2h', hello)
                next_hello = _time.time() + 1.5
            try:
                m = self._hs.get(timeout=0.2)
            except queue.Empty:
                continue
            self._handshake(m)
        if self.id is None:
            self.relay.close()
            raise ConnectionError('No room with code %s is online' % self.code)
        self.via = 'internet'
        threading.Thread(target=self._relay_keepalive, daemon=True).start()

    def _on_relay(self, topic, payload):
        if topic is None:
            if self.running and self.id is not None:
                self.inbox.put({'t': 'bye'})
            return
        m = _decode(payload)
        if not isinstance(m, dict):
            return
        if self.id is None:
            if m.get('to') == self.tok:
                self._hs.put(m)
            return
        if m.get('t') in ('welcome', 'reject'):
            return
        if m.get('id') == self.id and m.get('t') != 'leave':
            return
        self.inbox.put(m)

    def _relay_keepalive(self):
        while self.running and self.relay is not None and self.relay.alive:
            _time.sleep(5)

    # ---- shared
    def _handshake(self, m):
        if m.get('t') == 'reject':
            raise ConnectionError(m.get('reason', 'Rejected'))
        if m.get('t') == 'welcome':
            self.id = m['id']
            self.room_name = m.get('room', '?')
            self.players = m.get('players', [])

    def send(self, msg):
        msg['id'] = self.id
        if self.conn is not None:
            self.conn.send(msg)
        elif self.relay is not None:
            self.relay.publish(self.base + 'c2h', msg)

    def close(self):
        self.running = False
        if self.relay is not None:
            self.relay.publish(self.base + 'c2h', {'t': 'leave', 'id': self.id})
            self.relay.close()
        if self.conn is not None:
            self.conn.close()


# ------------------------------------------------------------------ room list (LAN + internet)
class RoomBrowser:
    """Keeps a list of PUBLIC rooms: LAN discovery every 2 s + the internet room list on the relay."""

    def __init__(self):
        self.lan = {}
        self.online = {}
        self.running = True
        self.relay = None
        self.relay_ok = None
        threading.Thread(target=self._lan, daemon=True).start()
        threading.Thread(target=self._net, daemon=True).start()

    def _lan(self):
        while self.running:
            self.lan = {r.get('hash'): r for r in lan_scan(0.9)}
            for _ in range(12):
                if not self.running:
                    return
                _time.sleep(0.1)

    def _net(self):
        try:
            self.relay = MqttLink(self._on_room)
            self.relay.subscribe('%s/rooms/+' % TOPIC_ROOT)
            self.relay_ok = True
        except Exception:
            self.relay_ok = False

    def _on_room(self, topic, payload):
        if topic is None:
            return
        code = topic.rsplit('/', 1)[-1]
        info = _decode(payload) if payload else None
        if not isinstance(info, dict) or info.get('private') or info.get('proto') != PROTOCOL:
            self.online.pop(code, None)
            return
        info['code'] = code
        info['where'] = 'online'
        info['seen'] = _time.time()
        self.online[code] = info

    def list(self):
        rooms = {}
        now = _time.time()
        for code, r in list(self.online.items()):
            if now - r.get('seen', now) < 30:
                rooms[r.get('hash') or code] = r
        for h, r in list(self.lan.items()):
            if not r.get('private'):
                rooms[h] = r                                # LAN wins (faster connection)
        return sorted(rooms.values(), key=lambda r: (r.get('where') != 'LAN', r.get('name', '')))

    def stop(self):
        self.running = False
        if self.relay is not None:
            self.relay.close()


# ------------------------------------------------------------------ in-game session
PLAYER_COLORS = [(230, 60, 60), (60, 130, 240), (60, 200, 90), (240, 190, 40), (200, 80, 220), (40, 210, 210),
                 (250, 130, 40), (240, 240, 240)]


class RemotePlayer:
    def __init__(self, session, pid, name):
        from ursina import Text, scene
        from npcs import Humanoid
        from world import rgb
        self.s = session
        self.game = session.game
        self.id = pid
        self.name = safe_text(name, 16) or 'Player'
        name = self.name
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
            self.tag.position = (v.x, v.y + 2.6, v.z)
            self.pos = [v.x, v.y, v.z]
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

    def send_firework(self, kind, pos, vel, fid=None):
        self.link.send({'t': 'fw', 'kind': kind, 'fid': fid,
                        'pos': [round(c, 3) for c in pos], 'vel': [round(c, 3) for c in vel]})

    def send_firework_land(self, fid, pos, yaw):
        """Where my firework landed and stood up - everyone else snaps their copy to the same spot."""
        self.link.send({'t': 'fwl', 'fid': fid, 'pos': [round(c, 3) for c in pos], 'yaw': round(yaw, 1)})

    def send_firework_explode(self, fid, pos):
        """The bang happens at the same moment and place for every player."""
        self.link.send({'t': 'fwx', 'fid': fid, 'pos': [round(c, 3) for c in pos]})

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
            if pid == self.my_id and t != 'bye':
                continue
            if t == 'state':
                if pid not in self.remotes:
                    names = self.link.names if self.role == 'host' else {}
                    self._add(pid, names.get(pid) or 'Player %d' % pid)
                if pid in self.remotes:
                    self.remotes[pid].apply(m)
            elif t == 'fw':
                g.fireworks.spawn_remote(m.get('kind'), m['pos'], m['vel'], pid, m.get('fid'))
            elif t == 'fwl':
                g.fireworks.remote_land(pid, m.get('fid'), m.get('pos', (0, 0, 0)), float(m.get('yaw', 0.0)))
            elif t == 'fwx':
                g.fireworks.remote_explode(pid, m.get('fid'), m.get('pos', (0, 0, 0)))
            elif t == 'join':
                self._add(pid, m.get('name', 'Player'))
                g.hud.notify('%s joined the room' % m.get('name', 'Player'), rgb(120, 220, 255))
                g.sound.play('blip', 0.6)
            elif t == 'leave':
                name = self._remove(pid)
                if name:
                    g.hud.notify('%s left the room' % name, rgb(200, 200, 200))
            elif t == 'bye' and self.role == 'client':
                g.hud.notify('The host closed the room - continuing in singleplayer', rgb(255, 120, 90), 6)
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
            return 'ROOM CODE %s  -  "%s"  %s  %d/%d players\n%s' % (
                h.code, self.room_name, 'PRIVATE' if self.private else 'PUBLIC', n, MAX_PLAYERS, h.relay_status)
        return 'ONLINE "%s"  (%s)  %d players' % (self.room_name, self.link.via, n)

    def close(self):
        for pid in list(self.remotes):
            self._remove(pid)
        self.link.close()

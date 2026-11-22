"""
updater.py  -  automatic GitHub self-updater for Ursina City
==============================================================

On startup the game (and START_GAME.bat) calls this module:

1. reads the local  version.json   ->  {"version": "1.0.0", ...}
2. downloads        GITHUB_REPO_URL/version.json
3. if the remote version is newer, downloads every file listed in the remote
   version.json "files" list, checks that each .py file compiles, replaces the
   old files (savegame.json and other personal files are never touched),
   writes the new version.json and relaunches the game.

The remote version.json looks like:
    {"version": "1.0.1", "files": ["main.py", "world.py", ...]}

Change GITHUB_REPO_URL (or put "repo_url" in your local version.json) to point
at any public GitHub repository's raw files.
"""
import json
import os
import subprocess
import sys
import urllib.request

GITHUB_REPO_URL = 'https://raw.githubusercontent.com/vrmatsvr-hub/ursina-city/main'

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(HERE, 'version.json')
PROTECTED = {'savegame.json', 'version.json', 'START_GAME.bat', 'start_game.bat', 'UPDATE.bat', 'update.bat'}
ALLOWED_EXT = ('.py', '.md', '.txt', '.json')


def _parse(v):
    out = []
    for part in str(v).strip().lstrip('vV').split('.'):
        num = ''.join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def local_info():
    try:
        with open(VERSION_FILE) as f:
            return json.load(f)
    except Exception:
        return {'version': '0.0.0'}


def local_version():
    return local_info().get('version', '0.0.0')


def repo_url():
    return (local_info().get('repo_url') or GITHUB_REPO_URL).rstrip('/')


def _get(url, timeout):
    req = urllib.request.Request(url, headers={'User-Agent': 'UrsinaCity-Updater', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check(timeout=4.0):
    """Returns the remote version.json dict if it is newer than ours, else None."""
    base = repo_url()
    if 'OWNER/' in base:
        return None
    try:
        remote = json.loads(_get(base + '/version.json?nocache=1', timeout))
    except Exception as ex:
        print('[updater] could not check for updates:', ex)
        return None
    if _parse(remote.get('version', '0')) > _parse(local_version()):
        return remote
    return None


def apply(remote, timeout=15.0):
    base = repo_url()
    files = [f for f in remote.get('files', []) if f not in PROTECTED and f.endswith(ALLOWED_EXT)
             and '..' not in f and not os.path.isabs(f)]
    downloaded = {}
    for name in files:
        print('[updater] downloading', name)
        data = _get(base + '/' + name, timeout)
        if not data:
            raise RuntimeError('empty file: ' + name)
        if name.endswith('.py'):
            compile(data, name, 'exec')            # never install a broken file
        downloaded[name] = data
    for name, data in downloaded.items():
        path = os.path.join(HERE, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.new'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    info = local_info()
    info['version'] = remote['version']
    with open(VERSION_FILE, 'w') as f:
        json.dump(info, f, indent=2)
    return len(downloaded)


def run(relaunch=True):
    """Check + install. When relaunch is True the updated game is restarted. Returns True if updated."""
    print('[updater] local version', local_version(), '- checking', repo_url())
    remote = check()
    if remote is None:
        print('[updater] up to date.')
        return False
    print('[updater] new version %s available - updating ...' % remote['version'])
    try:
        n = apply(remote)
    except Exception as ex:
        print('[updater] update failed, keeping the current version:', ex)
        return False
    print('[updater] installed %d files, now at v%s' % (n, remote['version']))
    if relaunch:
        args = [a for a in sys.argv[1:] if a != '--no-update']
        subprocess.Popen([sys.executable, os.path.join(HERE, 'main.py'), '--no-update'] + args, cwd=HERE)
        sys.exit(0)
    return True


if __name__ == '__main__':
    # exit codes for UPDATE.bat:  0 = already up to date, 10 = updated, 2 = could not check / failed
    if 'OWNER/' in repo_url():
        print('[updater] no GitHub repository configured.')
        sys.exit(2)
    print('[updater] local version', local_version(), '- checking', repo_url())
    try:
        remote_info = json.loads(_get(repo_url() + '/version.json?nocache=1', 6.0))
    except Exception as ex:
        print('[updater] could not reach GitHub:', ex)
        sys.exit(2)
    print('[updater] newest version on GitHub:', remote_info.get('version'))
    if _parse(remote_info.get('version', '0')) <= _parse(local_version()):
        print('[updater] you already have the newest version.')
        sys.exit(0)
    try:
        n = apply(remote_info)
    except Exception as ex:
        print('[updater] update failed, nothing was changed:', ex)
        sys.exit(2)
    print('[updater] updated %d files -> v%s (savegame.json kept)' % (n, remote_info['version']))
    sys.exit(10)

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
import re
import subprocess
import sys
import time
import urllib.request

GITHUB_REPO_URL = 'https://raw.githubusercontent.com/vrmatsvr-hub/ursina-city/main'

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(HERE, 'version.json')
PROTECTED = {'savegame.json', 'version.json', 'START_GAME.bat', 'start_game.bat', 'UPDATE.bat', 'update.bat'}
ALLOWED_EXT = ('.py', '.md', '.txt', '.json')
LOG_FILE = os.path.join(HERE, 'update_log.txt')
_resolved_base = None


def log(*args):
    msg = ' '.join(str(a) for a in args)
    print(msg)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except Exception:
        pass


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


def _get(url, timeout, headers=None):
    h = {'User-Agent': 'UrsinaCity-Updater', 'Cache-Control': 'no-cache'}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def resolved_base(timeout=6.0):
    """raw.githubusercontent.com caches branch files for ~5 minutes, so a fresh upload can look old.
    Asking the GitHub API for the newest commit and downloading files *by commit* avoids that."""
    global _resolved_base
    if _resolved_base is not None:
        return _resolved_base
    base = repo_url()
    m = re.match(r'https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)$', base)
    if m:
        owner, repo, branch = m.groups()
        try:
            sha = _get('https://api.github.com/repos/%s/%s/commits/%s' % (owner, repo, branch), timeout,
                       {'Accept': 'application/vnd.github.sha'}).decode().strip()
            if re.fullmatch(r'[0-9a-f]{40}', sha):
                _resolved_base = 'https://raw.githubusercontent.com/%s/%s/%s' % (owner, repo, sha)
                return _resolved_base
        except Exception as ex:
            log('[updater] GitHub API not reachable (%s) - using the branch URL' % ex)
    _resolved_base = base
    return base


def fetch_remote_info(timeout=6.0):
    return json.loads(_get(resolved_base(timeout) + '/version.json?t=%d' % int(time.time()), timeout))


def check(timeout=4.0):
    """Returns the remote version.json dict if it is newer than ours, else None."""
    base = repo_url()
    if 'OWNER/' in base:
        return None
    try:
        remote = fetch_remote_info(timeout)
    except Exception as ex:
        log('[updater] could not check for updates:', ex)
        return None
    if _parse(remote.get('version', '0')) > _parse(local_version()):
        return remote
    return None


def apply(remote, timeout=15.0):
    base = resolved_base()
    files = [f for f in remote.get('files', []) if f not in PROTECTED and f.endswith(ALLOWED_EXT)
             and '..' not in f and not os.path.isabs(f)]
    downloaded = {}
    for name in files:
        log('[updater] downloading', name)
        data = _get(base + '/' + name + '?t=%d' % int(time.time()), timeout)
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
    log('[updater] local version', local_version(), '- checking', repo_url())
    remote = check()
    if remote is None:
        log('[updater] up to date.')
        return False
    log('[updater] new version %s available - updating ...' % remote['version'])
    try:
        n = apply(remote)
    except Exception as ex:
        log('[updater] update failed, keeping the current version:', ex)
        return False
    log('[updater] installed %d files, now at v%s' % (n, remote['version']))
    if relaunch:
        args = [a for a in sys.argv[1:] if a != '--no-update']
        subprocess.Popen([sys.executable, os.path.join(HERE, 'main.py'), '--no-update'] + args, cwd=HERE)
        sys.exit(0)
    return True


if __name__ == '__main__':
    # exit codes for UPDATE.bat:  0 = already up to date, 10 = updated, 2 = could not check / failed
    if 'OWNER/' in repo_url():
        log('[updater] no GitHub repository configured.')
        sys.exit(2)
    log('[updater] local version', local_version(), '- checking', repo_url())
    log('[updater] python', sys.version.split()[0], 'at', sys.executable)
    try:
        remote_info = fetch_remote_info()
    except Exception as ex:
        log('[updater] could not reach GitHub:', ex)
        sys.exit(2)
    log('[updater] newest version on GitHub:', remote_info.get('version'))
    if _parse(remote_info.get('version', '0')) <= _parse(local_version()):
        log('[updater] you already have the newest version.')
        sys.exit(0)
    try:
        n = apply(remote_info)
    except Exception as ex:
        log('[updater] update failed, nothing was changed:', ex)
        sys.exit(2)
    log('[updater] updated %d files -> v%s (savegame.json kept)' % (n, remote_info['version']))
    sys.exit(10)

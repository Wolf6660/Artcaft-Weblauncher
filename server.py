"""Artcraft Hub: standard-library-only release manager and static web host."""
import base64
from email.utils import parsedate_to_datetime
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

DATA = Path(os.getenv('DATA_DIR', '/data'))
PUBLIC = Path(os.getenv('PUBLIC_DIR', '/public'))
DASHBOARD = Path(__file__).parent / 'dashboard'
LOCK = threading.RLock()
STATUS = {'busy': False, 'message': '', 'checked': None, 'apps': [], 'error': None}
CSRF = secrets.token_urlsafe(32)
LIMIT = 512 * 1024 * 1024
ICON_SCHEMA = 4
ICON_LOCKS = {}


def atomic_json(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False, encoding='utf-8') as tmp:
        json.dump(value, tmp, ensure_ascii=False)
        temporary = Path(tmp.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class GitHubPaused(RuntimeError):
    pass


def rate_message(until):
    stamp = time.strftime('%d.%m.%Y %H:%M UTC', time.gmtime(until))
    return (f'GitHub-API-Limit erreicht. Weitere API-Abfragen sind bis {stamp} pausiert. '
            'Vorhandene Anwendungen bleiben nutzbar. Optional GITHUB_TOKEN in der .env setzen und den Container neu erstellen.')


def credential_id():
    return hashlib.sha256(os.getenv('GITHUB_TOKEN', '').encode()).hexdigest()


def api_pause():
    path = DATA / 'github-pause.json'
    if path.exists():
        pause = json.loads(path.read_text())
        if pause.get('credential') == credential_id() and pause['until'] > time.time():
            raise GitHubPaused(rate_message(pause['until']))


def request(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'api.github.com', 'github.com', 'raw.githubusercontent.com'}:
        raise ValueError('Unzulässige Download-Adresse')
    if parsed.hostname == 'api.github.com':
        api_pause()
    headers = {'User-Agent': 'Artcraft-Hub', 'Accept': 'application/vnd.github+json'}
    token = os.getenv('GITHUB_TOKEN')
    if token and parsed.hostname == 'api.github.com':
        headers['Authorization'] = 'Bearer ' + token
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)
    except urllib.error.HTTPError as error:
        if parsed.hostname == 'api.github.com' and error.code in (403, 429):
            body = error.read(8192).decode('utf-8', errors='replace').lower()
            limited = (error.code == 429 or error.headers.get('X-RateLimit-Remaining') == '0'
                       or error.headers.get('Retry-After') or 'rate limit' in body)
            if limited:
                until = time.time() + 60
                retry = error.headers.get('Retry-After')
                if retry:
                    try:
                        until = time.time() + float(retry)
                    except ValueError:
                        try:
                            until = parsedate_to_datetime(retry).timestamp()
                        except (ValueError, TypeError):
                            pass
                if error.headers.get('X-RateLimit-Remaining') == '0':
                    try:
                        until = max(until, float(error.headers.get('X-RateLimit-Reset', time.time() + 3600)))
                    except ValueError:
                        until = max(until, time.time() + 3600)
                DATA.mkdir(parents=True, exist_ok=True)
                atomic_json(DATA / 'github-pause.json', {'until': until, 'credential': credential_id()})
                raise GitHubPaused(rate_message(until)) from error
            raise RuntimeError('GitHub verweigert den API-Zugriff (HTTP 403). Token-Berechtigungen oder Netzwerkzugriff prüfen.') from error
        raise


def get_json(url):
    with request(url) as response:
        return json.load(response)


def valid_name(name):
    return bool(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}', name))


def select_asset(release):
    assets = [a for a in release.get('assets', []) if re.search(r'(?:^|[-_])web(?:[-_.]|$)', a['name'], re.I) and a['name'].lower().endswith('.zip')]
    return assets[0] if len(assets) == 1 else None


def manifest(name):
    path = DATA / 'apps' / name / 'manifest.json'
    return json.loads(path.read_text()) if path.exists() else {}


def hidden_manual():
    path = DATA / 'hidden-manual.json'
    return set(json.loads(path.read_text())) if path.exists() else set()


def discover_icon(repo):
    """The Craft apps publish their icons at this shared path; no API call needed."""
    name = repo['name']
    branch = repo.get('default_branch') or 'main'
    return ('https://raw.githubusercontent.com/storytold/' + urllib.parse.quote(name, safe='')
            + '/' + urllib.parse.quote(branch, safe='')
            + '/assets/app-icon/hicolor/64x64/apps/ai.storyteller.'
            + urllib.parse.quote(name.lower(), safe='') + '.png')


def default_apps():
    path = Path(__file__).parent / 'catalog-default.json'
    return json.loads(path.read_text()).get('apps', []) if path.exists() else []


def catalog():
    items = {a['id']: dict(a) for a in (STATUS['apps'] or default_apps())}
    hidden = hidden_manual()
    roots = [PUBLIC, DATA / 'apps']
    for root in roots:
        if root.exists():
            for p in root.iterdir():
                if p.is_dir() and valid_name(p.name) and (((p / 'index.html').is_file() and p.name not in hidden) or manifest(p.name)):
                    items.setdefault(p.name, {'id': p.name, 'description': 'Lokal vorhandene Anwendung', 'release': None})
    for name, item in items.items():
        m = manifest(name)
        item['installed'] = m.get('tag') or ('Manuell' if (PUBLIC / name / 'index.html').is_file() and name not in hidden else None)
        item['update'] = bool(item.get('release') and item['installed'] != item['release']['tag'])
        item['rollback'] = bool(m.get('previous'))
        item.setdefault('github', f'https://github.com/storytold/{name}#readme')
        item['icon'] = '/api/icon/' + urllib.parse.quote(name, safe='')
    return sorted(items.values(), key=lambda a: a['id'].lower())


def load_icon(name):
    if not valid_name(name):
        raise ValueError('Ungültige Anwendung')
    app = next((a for a in catalog() if a['id'] == name), None)
    if not app:
        raise ValueError('Unbekannte Anwendung')
    with LOCK:
        lock = ICON_LOCKS.setdefault(name, threading.Lock())
    with lock:
        folder = DATA / 'icons'
        folder.mkdir(parents=True, exist_ok=True)
        image = folder / (name + '.png')
        failure = folder / (name + '.error.json')
        if image.exists() and time.time() - image.stat().st_mtime < 7 * 86400:
            return image.read_bytes()
        if failure.exists() and time.time() - failure.stat().st_mtime < 600:
            if image.exists():
                return image.read_bytes()
            raise RuntimeError('Icon derzeit nicht erreichbar; erneuter Versuch in wenigen Minuten.')
        url = discover_icon({'name': name, 'default_branch': app.get('icon_branch', 'main')})
        try:
            # The server fetches the image. Browsers only contact their local Hub.
            with request(url) as response:
                content = response.read(2 * 1024 * 1024 + 1)
            if len(content) > 2 * 1024 * 1024 or not content.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('GitHub hat kein gültiges PNG-Icon geliefert')
            with tempfile.NamedTemporaryFile(dir=folder, delete=False) as tmp:
                tmp.write(content)
                temporary = Path(tmp.name)
            try:
                temporary.replace(image)
            finally:
                temporary.unlink(missing_ok=True)
            failure.unlink(missing_ok=True)
            return content
        except Exception as error:
            atomic_json(failure, {'error': str(error)})
            if image.exists():
                return image.read_bytes()
            raise RuntimeError('Icon konnte nicht von GitHub geladen werden. NAS-Zugriff auf raw.githubusercontent.com prüfen.') from error


def check():
    api_pause()
    if STATUS.get('checked') and time.time() - STATUS['checked'] < 600:
        return 'Der Katalog wurde vor weniger als zehn Minuten geprüft. Vorhandene Ergebnisse werden verwendet.'
    repositories = []
    for page in range(1, 21):
        batch = get_json(f'https://api.github.com/orgs/storytold/repos?per_page=100&page={page}')
        repositories.extend(batch)
        if len(batch) < 100:
            break
    failures = []
    previous = {a['id']: a for a in catalog()}
    items = dict(previous)
    for repo in repositories:
        name = repo['name']
        if not name.lower().endswith('craft') or not valid_name(name) or repo.get('archived'):
            continue
        try:
            release = get_json(f'https://api.github.com/repos/storytold/{name}/releases/latest')
            asset = select_asset(release)
            if asset:
                old = previous.get(name, {})
                icon = old.get('icon')
                icon_revision = old.get('icon_revision')
                items[name] = {'id': name, 'github': repo['html_url'] + '#readme', 'icon': icon, 'icon_revision': icon_revision, 'icon_schema': old.get('icon_schema'), 'description': repo.get('description') or '', 'release': {'tag': release['tag_name'], 'url': asset['browser_download_url'], 'digest': asset.get('digest'), 'size': asset['size'], 'page': release['html_url']}}
            else:
                items.pop(name, None)
        except GitHubPaused as error:
            failures.append(str(error))
            break
        except urllib.error.HTTPError as error:
            if error.code == 404:
                items.pop(name, None)
            else:
                failures.append(f'{name}: HTTP {error.code}')
        except Exception as error:
            failures.append(f'{name}: {error}')
    apps = list(items.values())
    repos_by_name = {r['name']: r for r in repositories}
    for app in apps:
        repo = repos_by_name.get(app['id'], {'name': app['id'], 'default_branch': app.get('icon_branch', 'main')})
        app['icon'] = discover_icon(repo)
        app['icon_branch'] = repo.get('default_branch') or 'main'
        app['icon_revision'] = repo.get('pushed_at')
        app['icon_schema'] = ICON_SCHEMA
    STATUS['apps'] = apps
    if not failures:
        STATUS['checked'] = time.time()
    atomic_json(DATA / 'catalog.json', {'apps': apps, 'checked': STATUS.get('checked')})
    if failures:
        raise RuntimeError('Prüfung unvollständig; erfolgreiche Ergebnisse wurden gespeichert. ' + '; '.join(failures[:5]))
    return f'{len(apps)} Anwendungen mit Web-Download gefunden.'


def app_details(name):
    if not valid_name(name):
        raise ValueError('Unbekannte Anwendung')
    app = next((a for a in catalog() if a['id'] == name), None)
    if not app:
        raise ValueError('Unbekannte Anwendung')
    cache_dir = DATA / 'details'
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / (name + '.json')
    previous = json.loads(cache.read_text()) if cache.exists() else None
    if previous and time.time() - previous['fetched'] < 3600:
        return previous
    try:
        branch = urllib.parse.quote(app.get('icon_branch') or 'main', safe='')
        url = f'https://raw.githubusercontent.com/storytold/{name}/{branch}/README.md'
        try:
            with request(url) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('README ist zu groß')
            content = raw.decode('utf-8', errors='replace')
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            # Unusual README names are resolved through the API only when needed.
            readme = get_json(f'https://api.github.com/repos/storytold/{name}/readme')
            if readme.get('encoding') != 'base64':
                raise ValueError('Unbekanntes README-Format')
            content = base64.b64decode(readme['content']).decode('utf-8', errors='replace')
        result = {'id': name, 'description': app.get('description') or '',
                  'readme': content, 'github': f'https://github.com/storytold/{name}',
                  'fetched': time.time(), 'cached': False}
        atomic_json(cache, result)
        return result
    except Exception as error:
        if previous:
            return {**previous, 'cached': True}
        raise RuntimeError('Beschreibung konnte nicht geladen werden. '
                           'Der Container benötigt Zugriff auf raw.githubusercontent.com. '
                           + str(error)) from error


def extract(archive, target):
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > LIMIT * 3 or len(z.infolist()) > 20000:
            raise ValueError('Archiv ist zu groß')
        for entry in z.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Unsicherer Archivpfad')
        z.extractall(target)
    candidates = [p for p in target.rglob('index.html') if '__MACOSX' not in p.parts]
    if not candidates:
        raise ValueError('Keine index.html im Webarchiv')
    depth = min(len(p.relative_to(target).parts) for p in candidates)
    candidates = [p for p in candidates if len(p.relative_to(target).parts) == depth]
    if len(candidates) != 1:
        raise ValueError('Web-Startverzeichnis ist nicht eindeutig')
    return candidates[0].parent


def install(name):
    app = next((a for a in catalog() if a['id'] == name), None)
    if not app:
        raise ValueError('Zuerst nach Updates suchen')
    release = app['release']
    if release['size'] > LIMIT:
        raise ValueError('Download ist zu groß')
    home = DATA / 'apps' / name
    home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DATA) as tmp:
        archive = Path(tmp) / 'download.zip'
        digest = hashlib.sha256()
        size = 0
        with request(release['url']) as response, archive.open('wb') as out:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > LIMIT:
                    raise ValueError('Download ist zu groß')
                out.write(chunk)
                digest.update(chunk)
        if release.get('digest') and release['digest'] != 'sha256:' + digest.hexdigest():
            raise ValueError('Prüfsumme stimmt nicht überein')
        if size != release['size']:
            raise ValueError('Download ist unvollständig')
        unpacked = Path(tmp) / 'unpacked'
        unpacked.mkdir()
        root = extract(archive, unpacked)
        version = secrets.token_hex(12)
        shutil.move(str(root), home / version)
        old = manifest(name)
        new = {'tag': release['tag'], 'current': version, 'previous': old.get('current'), 'previous_tag': old.get('tag')}
        atomic_json(home / 'manifest.json', new)
        # Only remove releases after the atomic pointer has been committed.
        for p in home.iterdir():
            if p.is_dir() and p.name not in {version, new['previous']}:
                shutil.rmtree(p)
    return f'{name} {release["tag"]} installiert.'


def rollback(name):
    m = manifest(name)
    if not m.get('previous'):
        raise ValueError('Keine vorherige verwaltete Version vorhanden')
    atomic_json(DATA / 'apps' / name / 'manifest.json', {'current': m['previous'], 'tag': m['previous_tag'], 'previous': m['current'], 'previous_tag': m['tag']})
    return f'{name}: vorherige Version wiederhergestellt.'


def uninstall(name):
    if not valid_name(name):
        raise ValueError('Ungültige Anwendung')
    m = manifest(name)
    manual = (PUBLIC / name / 'index.html').is_file()
    if not m and not manual:
        raise ValueError('Anwendung ist nicht installiert')
    # The legacy public mount is read-only: persistently disable it instead.
    hidden = hidden_manual()
    hidden.add(name)
    atomic_json(DATA / 'hidden-manual.json', sorted(hidden))
    home = DATA / 'apps' / name
    if m:
        shutil.rmtree(home)
    return f'{name} deinstalliert.'


def start_job(action, name):
    with LOCK:
        if STATUS['busy']:
            return False
        STATUS.update(busy=True, error=None, message='Bitte warten …')
    def work():
        try:
            STATUS['message'] = {'check': check, 'install': lambda: install(name), 'rollback': lambda: rollback(name), 'uninstall': lambda: uninstall(name)}[action]()
        except Exception as error:
            STATUS.update(error=str(error), message='Vorgang fehlgeschlagen')
        finally:
            STATUS['busy'] = False
    threading.Thread(target=work, daemon=True).start()
    return True


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.wasm': 'application/wasm', '.js': 'text/javascript'}

    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def authenticated(self):
        password = os.getenv('ADMIN_PASSWORD', '')
        expected = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()
        if password and not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Artcraft Hub", charset="UTF-8"')
            self.end_headers()
            return False
        return True

    def respond(self, code, value):
        payload = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if not self.authenticated():
            return
        if urllib.parse.urlsplit(self.path).path.startswith('/api/icon/'):
            name = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path.removeprefix('/api/icon/'))
            try:
                content = load_icon(name)
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except ValueError as error:
                self.respond(404, {'error': str(error)})
            except Exception as error:
                self.respond(502, {'error': str(error)})
            return
        if self.path.startswith('/api/details/'):
            name = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path.removeprefix('/api/details/'))
            try:
                return self.respond(200, app_details(name))
            except ValueError as error:
                return self.respond(404, {'error': str(error)})
            except Exception as error:
                return self.respond(502, {'error': str(error)})
        if self.path == '/api/status':
            return self.respond(200, {**STATUS, 'apps': catalog(), 'csrf': CSRF})
        return super().do_GET()

    def do_HEAD(self):
        if self.authenticated():
            super().do_HEAD()

    def do_POST(self):
        if not self.authenticated():
            return
        if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), CSRF):
            return self.respond(403, {'error': 'Ungültige Sitzung; Seite neu laden'})
        if self.path != '/api/action':
            return self.respond(404, {'error': 'Unbekannter Endpunkt'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length < 4096:
                raise ValueError('Ungültige Anfrage')
            data = json.loads(self.rfile.read(length))
            action, name = data.get('action'), data.get('id', '')
            if action not in {'check', 'install', 'rollback', 'uninstall'} or (action != 'check' and not valid_name(name)):
                raise ValueError('Ungültige Aktion')
            accepted = start_job(action, name)
            self.respond(202 if accepted else 409, {'accepted': accepted})
        except (ValueError, TypeError) as error:
            self.respond(400, {'error': str(error)})

    def translate_path(self, path):
        path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        parts = PurePosixPath(path).parts[1:]
        if any(p in {'.', '..'} or '\\' in p for p in parts):
            return str(DASHBOARD / '__missing__')
        if len(parts) == 2 and parts[0] == 'details' and valid_name(parts[1]):
            return str(DASHBOARD / 'details.html')
        if not parts:
            return str(DASHBOARD / 'index.html')
        if parts[0] in {'hub.js', 'hub.css', 'details.js'} and len(parts) == 1:
            return str(DASHBOARD / parts[0])
        name = parts[0]
        if not valid_name(name):
            return str(DASHBOARD / '__missing__')
        m = manifest(name)
        root = DATA / 'apps' / name / m['current'] if m else PUBLIC / name
        if not m and name in hidden_manual():
            return str(DASHBOARD / '__missing__')
        candidate = root.joinpath(*parts[1:])
        if not candidate.resolve().is_relative_to(root.resolve()):
            return str(DASHBOARD / '__missing__')
        return str(candidate)

    def list_directory(self, path):
        self.send_error(404)
        return None


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / 'apps').mkdir(exist_ok=True)
    cache = DATA / 'catalog.json'
    bundled = {a['id']: a for a in default_apps()}
    if cache.exists():
        saved = json.loads(cache.read_text())
        bundled.update({a['id']: a for a in saved.get('apps', [])})
        STATUS.update(saved)
    STATUS['apps'] = list(bundled.values())
    if not STATUS.get('checked'):
        STATUS['message'] = 'Mitgelieferter Web-App-Katalog geladen; aktuelle Versionen werden geprüft.'
    def schedule():
        while True:
            start_job('check', '')
            time.sleep(max(3600, int(os.getenv('CHECK_INTERVAL_HOURS', '12')) * 3600))
    threading.Thread(target=schedule, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', int(os.getenv('PORT', '8080'))), Handler).serve_forever()


if __name__ == '__main__':
    main()

"""Offline closeout harness. Launch as root under unshare --net and env -i."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
PG = Path('/usr/lib/postgresql/18/bin')
PYTHON = '/var/tmp/many-t0-20261028/venv/bin/python'
NODE = '/var/tmp/saas-closeout-tools/node-v24.22.1-linux-x64/bin'
os.environ.update(APP_ENV='test', TEST_DATABASE_URL='postgresql://dummy@/many_preflight')
assert os.getuid() == 0
subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True)
scratch = Path(tempfile.mkdtemp(prefix='many-r1-full-', dir='/var/tmp'))
scratch.chmod(0o755)
source = scratch / 'source'
source.mkdir()
git_dir = ROOT.parents[1] / '.git/worktrees/batch-b'
git = ['git', '-c', f'safe.directory={ROOT}', f'--git-dir={git_dir}', f'--work-tree={ROOT}']
sha = subprocess.check_output([*git, 'rev-parse', 'HEAD'], text=True).strip()
status = 'Windows Git preflight: clean. Reviewed session edit: backend/tests/conftest.py (Alembic setup). Linux Git status is unsuitable for this CRLF worktree.'
tracked = subprocess.check_output([*git, 'ls-files', '-z']).decode().split('\0')
manifest = []
for name in tracked:
    if not name:
        continue
    p = Path(name)
    # Only application, tests, configuration and frozen contract source.
    allowed = p.parts[0] in {'backend', 'dashboard', 'scripts', 'nginx'} or name in {
        'README.md', 'docker-compose.yml', 'compose.yaml', 'compose.prod.yaml',
        'docs/saas-delegation/CONTRACT.sha256',
        'docs/saas-delegation/CONTRACT-V1.md',
        'docs/saas-delegation/CONTRACT-V1.1-DELTA.md',
    }
    forbidden = any(part.lower() in {'backups', 'node_modules', '.next', '.git', '__pycache__'} for part in p.parts)
    forbidden |= p.name.startswith('.env') or p.suffix in {'.dump', '.zip', '.gz', '.pyc', '.tsbuildinfo'}
    forbidden |= 'popeye' in name.lower() or 'credential' in p.name.lower()
    if not allowed or forbidden:
        continue
    data = (ROOT / p).read_bytes()
    target = source / p
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    manifest.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest()})
(EVIDENCE / 'source-manifest.json').write_text(json.dumps({'head': sha, 'reviewed_worktree_status': status,
    'snapshot': str(source), 'files': manifest}, indent=2))
(EVIDENCE / 'reviewed-fixture.diff').write_bytes(subprocess.check_output([*git, 'diff', '--', 'backend/tests/conftest.py']))
for name in ('pg', 'socket'):
    (scratch / name).mkdir()
    shutil.chown(scratch / name, user='postgres', group='postgres')
env = dict(os.environ, PATH=f'{Path(PYTHON).parent}:{NODE}:/usr/sbin:/usr/bin:/sbin:/bin',
    HOME=str(scratch), APP_ENV='test', PGHOST=str(scratch / 'socket'), PGPORT='55439', PGUSER='postgres',
    REDIS_URL='redis://127.0.0.1:56390/2', META_APP_SECRET='full-synthetic-meta-secret',
    META_WEBHOOK_VERIFY_TOKEN='full-synthetic-verify', FACEBOOK_APP_SECRET='', META_WEBHOOK_SECRET='',
    JWT_SECRET='full-synthetic-jwt-secret-at-least-thirty-two-bytes',
    APP_SECRET_KEY='full-synthetic-app-secret-at-least-thirty-two-bytes',
    OPENAI_API_KEY='', SENTRY_DSN='', HTTP_PROXY='', HTTPS_PROXY='', ALL_PROXY='', NO_PROXY='*',
    NEXT_TELEMETRY_DISABLED='1', CI='1', PYTHONDONTWRITEBYTECODE='1')
# This is a fixed dummy Fernet key for synthetic fixtures only.
env['TOKEN_ENCRYPTION_KEY'] = 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='
results = []
redis = None
started = False

def raw(args, **kwargs):
    return subprocess.run(args, env=env, check=True, **kwargs)

def database(name):
    raw([str(PG / 'createdb'), name], stdout=subprocess.DEVNULL)
    return name

def run(label, args, db, cwd=None):
    if args[:3] == [PYTHON, '-m', 'alembic']:
        args = [str(Path(PYTHON).with_name('alembic')), *args[3:]]
    url = f'postgresql+psycopg://postgres@/{db}?host={scratch}/socket&port=55439'
    target_env = dict(env, APP_ENV='test', TEST_DATABASE_URL=url, DATABASE_URL=url)
    print(f'DB host={scratch}/socket name={db}', flush=True)
    check = subprocess.run([str(PG / 'psql'), '-d', db, '-Atc', 'select current_database()'],
                           env=target_env, check=True, capture_output=True, text=True)
    assert check.stdout.strip() == db
    command = 'APP_ENV=test TEST_DATABASE_URL=' + shlex.quote(url) + ' DATABASE_URL=' + shlex.quote(url) + ' ' + shlex.join(args)
    start = time.monotonic()
    with (EVIDENCE / f'{label}.log').open('w') as output:
        outcome = subprocess.run(args, cwd=cwd or source / 'backend', env=target_env, stdout=output, stderr=subprocess.STDOUT)
    result = {'label': label, 'cwd': str(cwd or source / 'backend'), 'command': command,
              'exit_code': outcome.returncode, 'seconds': round(time.monotonic() - start, 3)}
    results.append(result)
    (EVIDENCE / 'commands.json').write_text(json.dumps(results, indent=2))
    print(json.dumps({key: value for key, value in result.items() if key != 'command'}), flush=True)
    print('\n'.join((EVIDENCE / f'{label}.log').read_text(errors='replace').splitlines()[-8:]), flush=True)
    return outcome.returncode

try:
    with (EVIDENCE / 'initdb.log').open('w') as output:
        raw(['runuser', '-u', 'postgres', '--', str(PG / 'initdb'), '-D', str(scratch / 'pg'), '-A', 'trust'], stdout=output)
    raw(['runuser', '-u', 'postgres', '--', str(PG / 'pg_ctl'), '-D', str(scratch / 'pg'), '-l', str(scratch / 'pg/server.log'),
         '-o', f"-k {scratch}/socket -p 55439 -c listen_addresses=''", 'start'])
    started = True
    redis_log = (EVIDENCE / 'redis.log').open('w')
    redis = subprocess.Popen(['redis-server', '--bind', '127.0.0.1', '--port', '56390', '--save', '', '--appendonly', 'no'], env=env, stdout=redis_log, stderr=subprocess.STDOUT)
    for _ in range(100):
        if subprocess.run(['redis-cli', '-p', '56390', 'ping'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(.05)
    print(f'Fresh snapshot HEAD={sha}; files={len(manifest)}; namespace=loopback-only; scratch={scratch}', flush=True)
    test_db = database('many_test_r1')
    script_db = database('many_test_scripts')
    for index in (1, 2):
        assert run(f'fixture-regression-{index}', [PYTHON, '-m', 'pytest', 'tests/test_models.py', '-q', f'--junitxml={EVIDENCE}/fixture-regression-{index}.xml'], test_db) == 0
    backend_status = run('backend', [PYTHON, '-m', 'pytest', 'tests', '-q', f'--junitxml={EVIDENCE}/many-backend.xml'], test_db)
    if 'backend-only' in sys.argv:
        sys.exit(backend_status)
    modules = Path('/var/tmp/many-closeout-t-20261028-02/source/dashboard/node_modules')
    assert modules.is_dir(), 'cached locked dashboard dependencies missing'
    cached_lock = modules.parent / 'package-lock.json'
    assert json.loads(cached_lock.read_text()) == json.loads((source / 'dashboard/package-lock.json').read_text()), 'cache lock mismatch'
    (source / 'dashboard/node_modules').symlink_to(modules, target_is_directory=True)
    for db in (database('many_test_migrate_empty'), database('many_test_migrate_0022')):
        if db.endswith('0022'):
            run(db + '-baseline', [PYTHON, '-m', 'alembic', 'upgrade', '0022_whatsapp_opt_in'], db)
        run(db + '-upgrade', [PYTHON, '-m', 'alembic', 'upgrade', 'head'], db)
        run(db + '-current', [PYTHON, '-m', 'alembic', 'current'], db)
        run(db + '-downgrade', [PYTHON, '-m', 'alembic', 'downgrade', '0029_hash_processed_event_keys'], db)
        run(db + '-reupgrade', [PYTHON, '-m', 'alembic', 'upgrade', 'head'], db)
        run(db + '-drift', [PYTHON, '-m', 'alembic', 'check'], db)
    run('migration-heads', [PYTHON, '-m', 'alembic', 'heads'], script_db)
finally:
    if redis is not None:
        redis.terminate()
        redis.wait(timeout=15)
    if started:
        raw(['runuser', '-u', 'postgres', '--', str(PG / 'pg_ctl'), '-D', str(scratch / 'pg'), '-m', 'fast', 'stop'])
    (EVIDENCE / 'teardown.json').write_text(json.dumps({'scratch': str(scratch), 'postgres_stopped': started, 'redis_stopped': redis is not None}))

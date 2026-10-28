"""Install an official Node 24 tarball into disposable WSL test tooling."""
import hashlib
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen

target = Path('/var/tmp/saas-closeout-tools')
with urlopen('https://nodejs.org/dist/index.json', timeout=30) as response:
    releases = json.load(response)
release = next(row for row in releases if row['version'].startswith('v24.'))
version = release['version']
filename = f'node-{version}-linux-x64.tar.xz'
base = f'https://nodejs.org/dist/{version}/'
with urlopen(base + 'SHASUMS256.txt', timeout=30) as response:
    entries = response.read().decode().splitlines()
expected = next(line.split()[0] for line in entries if line.split()[-1] == filename)
with urlopen(base + filename, timeout=120) as response:
    payload = response.read()
assert hashlib.sha256(payload).hexdigest() == expected
archive = target / filename
archive.write_bytes(payload)
with tarfile.open(archive) as source:
    source.extractall(target, filter='data')
print(f'Installed {version} official Linux tarball; SHA256 {expected}')

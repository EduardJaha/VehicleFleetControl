#!/usr/bin/env python3
"""Archive tracked source at a commit, applying exclusions even to accidentally tracked artifacts."""
import argparse
import io
from pathlib import PurePosixPath
import subprocess
import tarfile

BLOCKED = {'.git', 'node_modules', '.next', '.next-dev', '.venv', 'venv', '__pycache__',
           'uploads', 'playwright-report', 'test-results', '.pytest_cache', 'backups', '.codex', '.agents'}


def allowed(name):
    path = PurePosixPath(name)
    return not (BLOCKED.intersection(path.parts) or
                any((part.startswith('.env') or '.env.' in part or part.endswith('.env')) and not part.endswith('.env.example') for part in path.parts) or
                path.suffix in {'.db', '.sqlite', '.sqlite3', '.pyc', '.pyo', '.tsbuildinfo'} or
                any(path.name.endswith(ext+suffix) for ext in ('.db','.sqlite','.sqlite3') for suffix in ('-wal','-shm','-journal')) or
                path.name.endswith('.env') or path.name.endswith('.env.local'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    commit = subprocess.check_output(['git', 'rev-parse', '--verify', args.ref+'^{commit}'], text=True).strip()
    archive = subprocess.check_output(['git', 'archive', '--format=tar', commit])
    with tarfile.open(fileobj=io.BytesIO(archive)) as source, tarfile.open(args.output, 'w:gz') as target:
        for entry in source:
            if allowed(entry.name) and not (entry.issym() or entry.islnk()):
                target.addfile(entry, source.extractfile(entry) if entry.isfile() else None)
    print(f'Created clean source archive from {commit}')


if __name__ == '__main__':
    main()

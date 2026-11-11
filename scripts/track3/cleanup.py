"""Remove only an explicitly named, marked test DB. Dry-run unless --confirm-delete."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.track3.paths import explicit_db


def cleanup(db, confirm=False, artifacts=()):
    path = explicit_db(db)
    marker = Path(str(path)+'.track3.json')
    if marker.is_symlink() or not marker.is_file():
        raise ValueError('Missing regular Track 3 test marker; refusing deletion')
    if json.loads(marker.read_text()).get('db') != str(path):
        raise ValueError('Marker does not match database')
    targets = [Path(str(path)+suffix) for suffix in ('','-wal','-shm','-journal','.track3.json')]
    for value in artifacts:
        artifact = Path(value)
        if not artifact.is_absolute() or '..' in artifact.parts:
            raise ValueError('Artifact path must be absolute without traversal')
        # Opt-in individual report files only in the same isolated directory, never recursive.
        if artifact.parent.resolve() != path.parent or artifact.suffix not in ('.json','.jsonl','.txt','.log'):
            raise ValueError('Artifact must be a report file beside the test DB')
        targets.append(artifact)
    if any(t.is_symlink() or t.is_dir() for t in targets):
        raise ValueError('Symlinks and directories cannot be deleted')
    existing = list(dict.fromkeys(t for t in targets if t.exists()))
    result = {'dry_run':not confirm,'paths':[str(t) for t in existing]}
    if confirm:
        for t in existing:
            t.unlink()
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True)
    p.add_argument('--artifact',action='append',default=[])
    p.add_argument('--confirm-delete',action='store_true')
    a = p.parse_args()
    print(json.dumps(cleanup(a.db,a.confirm_delete,a.artifact),indent=2))


if __name__ == '__main__':
    main()

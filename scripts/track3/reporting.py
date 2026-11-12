"""Exclusive, checkpointed JSON reports; existing evidence is never overwritten."""
import json
import os
from pathlib import Path


def report_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts or path.suffix != '.json':
        raise ValueError('Choose an absolute .json report path without parent traversal')
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Report paths cannot contain symlinks')
    if path.exists():
        raise ValueError('Report already exists; choose a new output to preserve evidence')
    return path


class ReportFile:
    """Reserve the output before inference; each checkpoint remains valid JSON."""
    def __init__(self, value):
        self.path = report_path(value)
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        self.file = os.fdopen(os.open(self.path, flags, 0o600), 'w', encoding='utf-8')
        return self

    def write(self, report):
        # Serialize before truncating the previous checkpoint.
        data = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        self.file.seek(0)
        self.file.write(data)
        self.file.truncate()
        self.file.flush()
        os.fsync(self.file.fileno())

    def __exit__(self, *_exc):
        self.file.close()

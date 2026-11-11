"""Check only Codex 3's release diff. Merged owner branches are reviewed separately."""
import argparse
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
BASE='cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3'
EXACT={'meetings/llm.py','scripts/seed_meetings_demo.py','scripts/live_meetings_check.py',
       'tests/test_track3_release__.py','tests/test_track3_llm__.py','.github/workflows/track3.yml',
       'README.md','MEETINGS.md','TEAM_DEVELOPMENT.md','docs/MEETINGS_API.md','docs/MEETINGS_HANDOFF.md',
       'docs/track3-handoffs/codex3.md'}
PREFIX=('scripts/track3/','evaluation/track3/','demo/track3/','docs/track3-team/','docs/track3-release/')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ref',default='codex/track3-release');a=p.parse_args()
    changed=subprocess.check_output(['git','diff','--name-only',BASE,a.ref],cwd=ROOT,text=True).splitlines()
    denied=[f for f in changed if f not in EXACT and not f.startswith(PREFIX)
            and not (f.startswith('requirements-track3') and f.endswith('.txt') and '/' not in f)]
    print(f'{len(changed)} release paths checked; forbidden={denied}')
    return int(bool(denied))


if __name__=='__main__': raise SystemExit(main())

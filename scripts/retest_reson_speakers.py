"""Replay the same 20 files; preserve baseline and publish before/after results."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import benchmark_reson20 as bench
bench.OUT=bench.ROOT/'data/reson-speaker-fix'
bench.PAGE=bench.ROOT/'static/qa/reson-speaker-fix.html'
bench.benchmark()
import report_speaker_fix  # Render the focused before/after view from saved results.

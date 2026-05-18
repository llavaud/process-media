import sys
from pathlib import Path

# Ensure src/ is on sys.path for imports like `process_media`
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

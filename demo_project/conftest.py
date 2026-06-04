import sys
from pathlib import Path

# Ensure demo_project/ is on sys.path so `app.*` imports resolve correctly
# whether pytest is invoked from inside demo_project/ or from the workspace root.
sys.path.insert(0, str(Path(__file__).parent))

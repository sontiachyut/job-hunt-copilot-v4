from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from job_hunt_copilot.db import initialize_database
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.profile_evidence import build_profile_evidence_corpus


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=None)
    args = parser.parse_args()

    paths = ProjectPaths.from_root(Path(args.project_root) if args.project_root else PROJECT_ROOT)
    initialize_database(paths.db_path)
    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    try:
        result = build_profile_evidence_corpus(connection, paths)
    finally:
        connection.close()
    print(
        json.dumps(
            {
                "status": "ok",
                "source_path": str(result.source_path),
                "mirror_path": str(result.mirror_path),
                "chunk_count": result.chunk_count,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

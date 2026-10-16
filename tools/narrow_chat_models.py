"""Publish only the selected SenseNova catalog, with normal backup and rollback."""
from pathlib import Path
import sys

from deploy_study import release


if __name__ == "__main__":
    release(
        Path(sys.argv[1]),
        files=["backend/sensenova_catalog.py"],
        required_paths=("/api/chat/providers", "/api/chat/stream"),
    )

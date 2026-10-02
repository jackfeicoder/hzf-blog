"""Targeted permission/admin release, with source and SQLite backup."""
from pathlib import Path
import sys
from deploy_study import release

FILES = [
    "backend/auth.py", "backend/schemas.py", "backend/main.py",
    "backend/routers/auth_router.py",
    "backend/routers/posts.py", "backend/routers/comments.py",
    "backend/routers/study.py", "backend/routers/admin.py",
    "frontend/src/api.js", "frontend/src/App.jsx", "frontend/src/components/Layout.jsx",
    "frontend/src/components/PasswordConfirm.jsx", "frontend/src/components/password-confirm.css",
    "frontend/src/pages/PostPage.jsx", "frontend/src/pages/Admin.jsx", "frontend/src/pages/admin.css",
]

if __name__ == "__main__":
    release(Path(sys.argv[1]), files=FILES,
            required_paths=("/api/admin/users", "/api/admin/posts", "/api/admin/categories", "/api/study/today", "/api/media/videos"))

"""Additive invitation/visitor release; never overwrite settings or music caches."""
from pathlib import Path
import sys
from deploy_study import release

FILES = [
    "backend/models.py", "backend/schemas.py", "backend/routers/auth_router.py",
    "backend/routers/visitors.py", "frontend/src/api.js", "frontend/src/AuthContext.jsx",
    "frontend/src/pages/Admin.jsx", "frontend/src/pages/Register.jsx",
    "frontend/src/pages/Visitors.jsx", "frontend/src/components/InviteManager.jsx",
]

if __name__ == "__main__":
    release(Path(sys.argv[1]), files=FILES, required_paths=("/api/auth/invitations", "/api/visitors"))

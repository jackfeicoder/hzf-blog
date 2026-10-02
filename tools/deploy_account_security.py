"""Backed-up account privacy, password and private music-source release."""
from pathlib import Path
import hashlib
import sys
from deploy_study import release, ROOT

FILES = [
    "backend/auth.py",
    "backend/models.py",
    "backend/schemas.py",
    "backend/public_identity.py",
    "backend/routers/auth_router.py",
    "backend/routers/users.py",
    "backend/routers/posts.py",
    "backend/routers/admin.py",
    "backend/routers/notifications.py",
    "backend/routers/visitors.py",
    "backend/routers/media.py",
    "backend/routers/music.py",
    "frontend/src/api.js",
    "frontend/src/AuthContext.jsx",
    "frontend/src/index.css",
    "frontend/src/components/Layout.jsx",
    "frontend/src/components/PasswordChange.jsx",
    "frontend/src/pages/Profile.jsx",
    "frontend/src/pages/PostPage.jsx",
    "frontend/src/pages/Admin.jsx",
    "frontend/src/pages/Videos.jsx",
    "frontend/src/pages/Music.jsx",
    "frontend/src/music/Sources.jsx",
    "frontend/src/music/PlayerBar.jsx",
    "frontend/src/music/labels.js"
]
EXPECTED = {
    "backend/routers/posts.py": "6487f673695f999c6b5b3cda4ab90ff9cd27692447ff895c4fdb601ab8683683",
    "backend/routers/users.py": "13eb57cebf1356e930f245bd48971eff539529faad5c830112085ea214dd0571",
    "backend/auth.py": "6b4d9bb0a59d8c6a0b1ff6d05792f46f14368a6504c4f3f7899ce8f283586ee1",
    "backend/routers/auth_router.py": "4a1fc8f52cb1901f4895931763aea966c86d487274f1ca68bb41fcdc4e23a8a4",
    "backend/schemas.py": "f2413858a0bb5831ace1afc91af04cdbb4f3004ba038759abf933bbf2c60e4a7",
    "frontend/src/pages/PostPage.jsx": "8f9df87a252dc3f70eb9656c75807a3d686daf6fd420002a2c7d84fffb864a5b",
    "backend/routers/notifications.py": "5955164566e3abe99d54d2ce4308db5556f05274fab20bb7881580fa739e4963",
    "frontend/src/index.css": "51043dce9eebbd5fe9c7d804697360b274c9ceb7bf5766c242ab9b144968c5cc",
    "backend/routers/visitors.py": "23364e9693b898eb77a5504ac313695b2ae37d55b43f286d04181d8ed972a396",
    "frontend/src/api.js": "c4bdf3ff682e70d01481afbf14d0af3a2f0325232cfc78bb63d941a127d32f12",
    "backend/routers/media.py": "a935c2713dfe7092b9f3cc3e06c21107b5bc725278231946cea58014b525dab8",
    "backend/models.py": "9c7cd9f5053d2640f36b50990bb4d5098e79872505ce413fb6c8933d89cc5cd6",
    "frontend/src/pages/Profile.jsx": "cda603d6f4fd50a0bfd92df42fb33dfae8013d73d7ead357763a2de5f5432991",
    "frontend/src/AuthContext.jsx": "e79fe75d90e39b2cbaf7e88bb290af449fecb607d25a10c02e13dd4ddba6c5a4",
    "frontend/src/components/Layout.jsx": "5880e5e78a8e658d07bbb051c7adb51076d59bc3407b027559728888c0664b60",
    "frontend/src/pages/Admin.jsx": "d1c11965407db47e4c88a05f0347c43eb4d86f04fd6cd8fca34735542db781f3",
    "backend/routers/admin.py": "902cfebf5af9c1529197611001ccff8d9b9463206f68094342b9f0cb9a25179f",
    "frontend/src/pages/Videos.jsx": "3e5ac2e056379d7dd5da7bd80ee2b7f355b8ec1f201c2d147de680f73d71bb2c",
    "frontend/src/music/Sources.jsx": "66a0ccfc0c3631635fd3a8f70db2d1fb693a6eba1ddb7516366fe9b5b95f8a32",
    "frontend/src/pages/Music.jsx": "b4a6fe458be76cc22d4405b9aefe94d64f8f7f8681618566f0b401dda07f4dc3",
    "backend/routers/music.py": "b31ccbd525166f61a4e69d0f3646095e101cce15a7f49d841a97c94680056328",
    "frontend/src/music/PlayerBar.jsx": "146b8508bd481d58f74abfe5dbcfafedb29e5c39e0ee0eb1089529dc7b83deae"
}
NEW_FILES = ["backend/public_identity.py", "frontend/src/components/PasswordChange.jsx", "frontend/src/music/labels.js"]

if __name__ == "__main__":
    for name, expected in EXPECTED.items():
        actual = hashlib.sha256(((ROOT / name).read_bytes().decode("utf-8-sig").rstrip() + "\n").encode()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Live file changed since inspection: {name}")
    for name in NEW_FILES:
        if (ROOT / name).exists():
            raise RuntimeError(f"Unexpected existing file: {name}")
    release(Path(sys.argv[1]), files=FILES, required_paths=(
        "/api/auth/password", "/api/auth/me", "/api/music/sources", "/api/users/{username}",
    ))

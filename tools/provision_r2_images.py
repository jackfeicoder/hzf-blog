"""Windows-side R2 setup. Credentials go to SSH stdin, never argv or local files.

Inspect first; prepare creates only a new image bucket/domain and a bucket-scoped
runtime token. Existing resources are never overwritten. State is ignored by Git.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import winreg

import httpx

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local-history/r2-images-provision.json"
BUCKET = "hzf-blog-images"
DOMAIN = "img.120115.xyz"


def variable(name):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        return winreg.QueryValueEx(key, name)[0]


def api(method, path, body=None):
    with httpx.Client(trust_env=False, proxy=os.getenv("HTTPS_PROXY"), timeout=30) as client:
        response = client.request(method, "https://api.cloudflare.com/client/v4/" + path,
            headers={"Authorization": "Bearer " + variable("CLOUDFLARE_API_TOKEN")}, json=body)
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(f"Cloudflare returned HTTP {response.status_code}") from None
    if not response.is_success or data.get("success") is False:
        raise RuntimeError(f"Cloudflare HTTP {response.status_code}, codes {[e.get('code') for e in data.get('errors', [])]}")
    return data["result"]


def save(state):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def inspect():
    account, zone = variable("CLOUDFLARE_ACCOUNT_ID"), variable("CLOUDFLARE_ZONE_ID_120115_XYZ")
    groups = api("GET", f"accounts/{account}/tokens/permission_groups")
    matching = [g for g in groups if g["name"] == "Workers R2 Storage Bucket Item Write"]
    buckets = api("GET", f"accounts/{account}/r2/buckets")["buckets"]
    dns = api("GET", f"zones/{zone}/dns_records?name={DOMAIN}")
    print(json.dumps({"buckets": [b["name"] for b in buckets], "domain_records": len(dns),
                      "object_write_group": matching}), flush=True)
    return account, zone, matching, buckets, dns


def prepare(stage):
    if not re.fullmatch(r"/tmp/hzf-images-[A-Za-z0-9]+", stage or ""):
        raise RuntimeError("Expected an explicit mktemp staging directory")
    if STATE.exists():
        raise RuntimeError("Existing provisioning state: inspect it before retrying")
    account, zone, groups, buckets, dns = inspect()
    if len(groups) != 1 or dns or any(b["name"] == BUCKET for b in buckets):
        raise RuntimeError("Existing/conflicting resource or missing scoped permission; no changes made")
    state = {"bucket": BUCKET, "domain": DOMAIN, "stage": stage}
    state["bucket_info"] = api("POST", f"accounts/{account}/r2/buckets", {"name": BUCKET, "storageClass": "Standard", "locationHint": "apac"})
    save(state)
    token = api("POST", f"accounts/{account}/tokens", {
        "name": "hzf-blog-images-runtime-20261003", "policies": [{"effect": "allow",
        "resources": {f"com.cloudflare.edge.r2.bucket.{account}_default_{BUCKET}": "*"},
        "permission_groups": [{"id": groups[0]["id"]}]}]})
    state["runtime_token_id"] = token["id"]
    save(state)
    env = {"IMAGE_STORAGE": "r2", "R2_ACCOUNT_ID": account, "R2_BUCKET": BUCKET,
           "R2_ACCESS_KEY_ID": token["id"], "R2_SECRET_ACCESS_KEY": hashlib.sha256(token["value"].encode()).hexdigest(),
           "R2_PUBLIC_BASE_URL": "https://" + DOMAIN}
    remote = '''import json, os, pathlib, sys
payload=json.load(sys.stdin)
stage=pathlib.Path(payload['stage']).resolve(strict=True)
assert stage.parent == pathlib.Path('/tmp') and stage.name.startswith('hzf-images-')
assert stage.is_dir() and not stage.is_symlink()
os.chmod(stage, 0o700)
fd=os.open(stage / '.r2.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    for key,value in payload['env'].items():
        assert '\\n' not in value and '\\r' not in value
        f.write(key+'='+value+'\\n')
print('CREDENTIALS_STAGED_0600')
'''
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "aliyun", "python3", "-c", shlex.quote(remote)],
        input=json.dumps({"stage": stage, "env": env}), capture_output=True, text=True, timeout=25)
    # Do not print remote stderr: a failure could echo credential-bearing input.
    if result.returncode or "CREDENTIALS_STAGED_0600" not in result.stdout:
        api("DELETE", f"accounts/{account}/tokens/{token['id']}")
        state["runtime_token_revoked"] = True
        save(state)
        raise RuntimeError("Credential delivery failed; new runtime token revoked")
    state["credentials_staged"] = True
    save(state)
    state["domain_info"] = api("POST", f"accounts/{account}/r2/buckets/{BUCKET}/domains/custom", {
        "domain": DOMAIN, "enabled": True, "zoneId": zone, "minTLS": "1.2"})
    save(state)
    print(json.dumps({"bucket": BUCKET, "domain": DOMAIN, "credentials": "bucket-scoped, staged on server only"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["inspect", "prepare", "status"])
    parser.add_argument("--stage")
    args = parser.parse_args()
    if args.mode == "inspect":
        inspect()
    elif args.mode == "prepare":
        prepare(args.stage)
    else:
        account = variable("CLOUDFLARE_ACCOUNT_ID")
        print(json.dumps(api("GET", f"accounts/{account}/r2/buckets/{BUCKET}/domains/custom/{DOMAIN}")), flush=True)

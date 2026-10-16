"""Short provider checks. Prints only model metadata and redacted results."""
import argparse
import ast
import json
import os
from pathlib import Path
import time
import httpx


def load_key():
    key = os.getenv('SENSENOVA_API_KEY', '').strip()
    if not key:
        from dotenv import dotenv_values
        root = Path('/www/wwwroot/blog.120115.xyz/backend')
        for name in ('sensenova.env', '.env'):
            path = root / name
            if path.is_file():
                key = (dotenv_values(path).get('SENSENOVA_API_KEY') or '').strip()
                if key:
                    break
        if not key:
            # Read the old deployed literal without executing or printing it.
            tree = ast.parse((root / 'routers/chat.py').read_text())
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == 'DEFAULT_FREE_KEY' for t in node.targets
                ) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    key = node.value.value.strip()
    if not key:
        raise RuntimeError('Provider credential is not configured')
    return key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', action='append', default=[])
    args = parser.parse_args()
    key = load_key()
    base = 'https://token.sensenova.cn/v1'
    with httpx.Client(trust_env=False, timeout=45) as client:
        headers = {'Authorization': f'Bearer {key}'}
        response = client.get(base + '/models', headers=headers)
        print('MODELS_STATUS=' + str(response.status_code), flush=True)
        if response.status_code != 200:
            print(response.text.replace(key, '[redacted]')[:400], flush=True)
            return
        rows = response.json().get('data', [])
        print(json.dumps([{'id': row.get('id'), 'output': row.get('output_modalities')}
                          for row in rows], ensure_ascii=False), flush=True)
        for model in args.probe:
            for streaming in (False, True):
                started = time.monotonic()
                limit_field = 'max_completion_tokens' if model.startswith('kimi-') else 'max_tokens'
                payload = {'model': model, 'messages': [{'role': 'user', 'content': '只回答：连接成功'}],
                           limit_field: 128, 'reasoning_effort': 'none', 'stream': streaming}
                response = client.post(base + '/chat/completions', headers=headers, json=payload)
                print(json.dumps({'model': model, 'stream': streaming, 'status': response.status_code,
                                  'seconds': round(time.monotonic() - started, 2),
                                  'body': response.text.replace(key, '[redacted]')[:1600]},
                                 ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

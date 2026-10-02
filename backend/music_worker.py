"""One disposable, offline non-root container at a time; HTTP via checked bridge."""
import asyncio
import json
import os
import uuid
from pathlib import Path
from music_http import fetch

GATE = asyncio.Semaphore(1)
IMAGE = 'hzf-music-node:20261002'
RUNTIME = Path(__file__).with_name('music_runtime.cjs')


async def run_source(script, name, action='probe', source='wy', info=None):
    if os.getenv('MUSIC_SANDBOX') != 'docker':
        raise ValueError('音源隔离服务尚未启用')
    async with GATE:
        container = 'hzf-music-' + uuid.uuid4().hex
        proc = None
        tasks = set()
        try:
            proc = await asyncio.create_subprocess_exec(
                '/usr/bin/docker', 'run', '--rm', '-i', '--name', container, '--network', 'none',
                '--read-only', '--user', '65534:65534', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--pids-limit', '24', '--memory', '128m', '--memory-swap', '128m', '--cpus', '0.5',
                '--mount', f'type=bind,source={RUNTIME},target=/runtime.cjs,readonly',
                IMAGE, '/node', '--max-old-space-size=64', '/runtime.cjs',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=2 * 1024 * 1024)
            proc.stdin.write((json.dumps(dict(script=script, name=name, action=action, source=source, info=info or {})) + '\n').encode())
            await proc.stdin.drain()
            count = 0

            async def reply(message):
                try:
                    response = await asyncio.to_thread(fetch, message['url'], message.get('options'))
                    value = dict(type='reply', id=message['id'], response=response)
                except Exception:
                    value = dict(type='reply', id=message['id'], error='上游请求失败')
                if proc.returncode is None:
                    proc.stdin.write((json.dumps(value) + '\n').encode())
                    await proc.stdin.drain()

            async with asyncio.timeout(12):
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        raise ValueError('音源进程已退出')
                    message = json.loads(line)
                    if message.get('type') == 'done':
                        # Capability output is data only; never evaluate returned scripts.
                        if len(json.dumps(message)) > 128 * 1024:
                            raise ValueError('音源输出过大')
                        return message
                    if message.get('type') != 'http':
                        raise ValueError('音源暂时不可用')
                    count += 1
                    if count > 24 or len(tasks) >= 8:
                        raise ValueError('音源请求过多')
                    task = asyncio.create_task(reply(message))
                    tasks.add(task); task.add_done_callback(tasks.discard)
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            cleanup = await asyncio.create_subprocess_exec('/usr/bin/docker', 'rm', '-f', container,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await cleanup.wait()
            if proc:
                await proc.wait()

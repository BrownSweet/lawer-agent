"""Run the local workspace API and worker without printing secrets."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-install', action='store_true')
    parser.add_argument('--external-mysql', action='store_true')
    parser.add_argument('--port', type=int, default=8891)
    args = parser.parse_args()
    uv = shutil.which('uv') or str(Path.home() / '.local/bin/uv')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', args.port)) == 0:
            raise SystemExit(f'Port {args.port} is already in use. Open that workspace or use --port.')
    subprocess.run([sys.executable, str(ROOT / 'scripts/setup.py')], check=True)
    if not args.external_mysql:
        subprocess.run(['docker', 'compose', 'up', '-d', '--wait', 'mysql'], cwd=ROOT, check=True)
    if not args.skip_install:
        subprocess.run([uv, 'sync', '--python', '3.12', '--locked'], cwd=ROOT / 'law_backend', check=True)
        subprocess.run(['npm', 'ci', '--cache', str(ROOT / '.local/npm-cache')], cwd=ROOT / 'frontend', check=True)
    # 本地 API 从根路径提供页面；不要复用为 Docker 构建的 /lawer/ 产物。
    subprocess.run(['npm', 'run', 'build'], cwd=ROOT / 'frontend',
                   env={**os.environ, 'VITE_BASE_PATH': '/'}, check=True)
    subprocess.run([uv, 'run', 'alembic', 'upgrade', 'head'], cwd=ROOT / 'law_backend', check=True)
    processes = []
    try:
        for command in ([uv, 'run', 'uvicorn', 'law_backend.api:app', '--host', '127.0.0.1', '--port', str(args.port)],
                        [uv, 'run', 'law-worker']):
            processes.append(subprocess.Popen(command, cwd=ROOT / 'law_backend', start_new_session=True))
        print(f'Workspace: http://127.0.0.1:{args.port} | 首次使用请在页面创建管理员', flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        print('API and worker stopped. MySQL and its data are preserved.')


if __name__ == '__main__':
    main()

"""Create local secrets once, without printing them or changing existing settings."""
from pathlib import Path
import secrets
import re

root = Path(__file__).resolve().parents[1]
env = root / '.env'
if env.exists():
    if not re.search(r'^\s*(?:export\s+)?APP_USERNAME\s*=', env.read_text(), re.MULTILINE):
        with env.open('a') as file:
            file.write('\nAPP_USERNAME=admin\n')
        print('Added APP_USERNAME=admin; existing password and other settings preserved.')
    else:
        print('.env already exists; left unchanged.')
else:
    password = secrets.token_urlsafe(24)
    env.write_text('\n'.join([
        f'MYSQL_PASSWORD={password}',
        f'MYSQL_ROOT_PASSWORD={secrets.token_urlsafe(32)}',
        'MYSQL_PORT=3318',
        f'DATABASE_URL=mysql+pymysql://law_workspace:{password}@127.0.0.1:3318/law_workspace?charset=utf8mb4',
        f'APP_SECRET={secrets.token_urlsafe(48)}',
        'APP_USERNAME=admin',
        f'APP_PASSWORD={secrets.token_urlsafe(16)}',
        'COOKIE_SECURE=false',
        'CREWAI_TELEMETRY_ENABLED=false',
        'OTEL_SDK_DISABLED=true',
        '',
    ]))
    env.chmod(0o600)
    print('Created .env with private credentials. Login uses APP_USERNAME and APP_PASSWORD.')

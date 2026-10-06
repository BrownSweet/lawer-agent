"""Create local secrets once, without printing them or changing existing settings."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
env = root / '.env'
if env.exists():
    print('.env already exists; left unchanged.')
else:
    password = secrets.token_urlsafe(24)
    env.write_text('\n'.join([
        f'MYSQL_PASSWORD={password}',
        f'MYSQL_ROOT_PASSWORD={secrets.token_urlsafe(32)}',
        'MYSQL_PORT=3318',
        f'DATABASE_URL=mysql+pymysql://law_workspace:{password}@127.0.0.1:3318/law_workspace?charset=utf8mb4',
        'COOKIE_SECURE=false',
        'CREWAI_TELEMETRY_ENABLED=false',
        'OTEL_SDK_DISABLED=true',
        '',
    ]))
    env.chmod(0o600)
    print('Created .env with database credentials. Create the administrator in the workspace web page.')

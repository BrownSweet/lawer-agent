"""Create an isolated test database without printing credentials."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
subprocess.run([
    'docker', 'compose', 'exec', '-T', 'mysql', 'sh', '-c',
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "'
    'CREATE DATABASE IF NOT EXISTS law_workspace_test CHARACTER SET utf8mb4; '
    'GRANT ALL ON law_workspace_test.* TO law_workspace;"',
], cwd=root, check=True)
print('Dedicated law_workspace_test database is ready.')

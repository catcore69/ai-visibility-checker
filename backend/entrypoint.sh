#!/bin/sh
set -e

echo "[entrypoint] Running DB grants..."
python3 -c "
import os, urllib.parse, subprocess
url = os.environ.get('DATABASE_URL_SYNC', '')
if not url:
    print('[entrypoint] No DATABASE_URL_SYNC, skipping grants')
else:
    parsed = urllib.parse.urlparse(url)
    user = parsed.username
    password = urllib.parse.unquote(parsed.password or '')
    host = parsed.hostname
    port = str(parsed.port or 5432)
    db = parsed.path.lstrip('/')
    sql = f'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {user}; GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {user}; GRANT USAGE ON SCHEMA public TO {user};'
    env = os.environ.copy()
    env['PGPASSWORD'] = password
    result = subprocess.run(
        ['psql', '-h', host, '-p', port, '-U', user, '-d', db, '-c', sql],
        env=env, capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print('[entrypoint] GRANT warning:', result.stderr)
    else:
        print('[entrypoint] Grants applied successfully')
"

echo "[entrypoint] Starting: $@"
exec "$@"

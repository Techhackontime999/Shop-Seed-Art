#!/usr/bin/env bash
# =============================================================================
# Build Script — runs during the build phase on Render
# =============================================================================
set -e

echo "=== Creating static directory ==="
mkdir -p static

echo "=== Installing dependencies ==="
pip install -r requirements.txt

echo "=== Running database migrations ==="
python manage.py migrate --noinput

echo "=== Creating cache table (DatabaseCache backend) ==="
python manage.py createcachetable 2>/dev/null || echo "No database cache backend configured; skipping."

echo "=== Collecting static files ==="
python manage.py collectstatic --noinput

echo "=== Compiling translation catalogs ==="
python manage.py compilemessages --ignore=env 2>/dev/null || echo "No catalogs to compile."

echo "=== Creating/updating superuser ==="
if [[ -n "$DJANGO_SUPERUSER_USERNAME" && -n "$DJANGO_SUPERUSER_EMAIL" && -n "$DJANGO_SUPERUSER_PASSWORD" ]]; then
    python manage.py createsuperuser --noinput 2>/dev/null || {
        echo "Superuser already exists. Updating password."
        python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
u = os.environ['DJANGO_SUPERUSER_USERNAME']
e = os.environ['DJANGO_SUPERUSER_EMAIL']
p = os.environ['DJANGO_SUPERUSER_PASSWORD']
try:
    user = User.objects.get(username=u)
    user.set_password(p); user.email = e; user.save()
    print(f'Superuser \"{u}\" password updated.')
except User.DoesNotExist:
    print(f'Could not create superuser \"{u}\".')
"
    }
fi

echo "=== Build complete ==="

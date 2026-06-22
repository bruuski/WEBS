web: gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --timeout 60 --access-logfile -
release: python -c "from pacer.db import init_db; from pacer.seed import seed_demo; init_db(); seed_demo()"

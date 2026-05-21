#!/bin/sh
set -e

case "${APP_ROLE:-web}" in
  web)
    exec gunicorn --bind 0.0.0.0:8000 wts.wsgi:application
    ;;
  worker)
    exec celery -A wts worker -l info
    ;;
  beat)
    exec celery -A wts beat -l info
    ;;
  *)
    echo "Unknown APP_ROLE: ${APP_ROLE} (expected web, worker, or beat)" >&2
    exit 1
    ;;
esac

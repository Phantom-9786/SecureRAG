#!/usr/bin/env bash
set -eu

public_port=${PORT:-10000}
[[ "$public_port" =~ ^[0-9]+$ ]]
if [[ -z "${FRONTEND_ORIGIN:-}" && -n "${RENDER_EXTERNAL_URL:-}" ]]; then
    export FRONTEND_ORIGIN="$RENDER_EXTERNAL_URL"
fi
sed -e 's/^user nginx;/user www-data;/' \
    -e 's/^worker_processes auto;/worker_processes 1;/' \
    -e "s/listen 80;/listen ${public_port};/" \
    -e 's|http://api:8000|http://127.0.0.1:8000|g' \
    -e 's|http://frontend:3000|http://127.0.0.1:3000|g' \
    -e 's|/var/log/nginx/access.log|/dev/stdout|' \
    /opt/securerag/nginx.conf > /tmp/securerag-nginx.conf
nginx -t -c /tmp/securerag-nginx.conf

setpriv --reuid app --regid app --init-groups \
    uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers &
api_pid=$!
# The frontend needs no backend secrets.
setpriv --reuid app --regid app --init-groups env -i \
    PATH=/usr/local/bin:/usr/bin:/bin NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=127.0.0.1 PORT=3000 node /web/server.js &
frontend_pid=$!
nginx -c /tmp/securerag-nginx.conf -g 'daemon off; error_log stderr;' &
gateway_pid=$!

stop() {
    kill "$api_pid" "$frontend_pid" "$gateway_pid" 2>/dev/null || true
    wait || true
}
trap 'stop; exit 0' TERM INT
wait -n "$api_pid" "$frontend_pid" "$gateway_pid" || true
stop
exit 1

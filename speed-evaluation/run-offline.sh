#!/bin/sh
# Run as the existing development owner on GCP, after copying this directory.
set -eu
task_source=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_owner_uid=$(id -u)
task_owner_gid=$(id -g)
timeout 90 docker run --rm \
    --name "caption-speed-67-evaluation-$$" \
    --network none --cpus 1 --memory 768m --pids-limit 160 --shm-size 128m \
    --read-only --tmpfs /tmp:rw,size=256m \
    --user "${task_owner_uid}:${task_owner_gid}" \
    -v "$task_source:/workspace:ro" \
    -v /tmp/caption-bridge-pr50-review.xydQoJ/combined/.venv:/opt/testvenv:ro \
    -w /workspace -e PYTHONDONTWRITEBYTECODE=1 \
    -e NO_PROXY=127.0.0.1,localhost \
    caption-bridge-gcp-validation:20260927 \
    /opt/testvenv/bin/python -m pytest -p no:cacheprovider -q --tb=short \
    browser_tests --browser chromium --browser webkit

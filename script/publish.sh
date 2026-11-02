#!/bin/sh
# Copy the integration (with its card) to the Home Assistant host.
# A restart of Home Assistant is needed after the first install and after
# Python changes; card-only changes need just a browser reload.
set -eu
cd "$(dirname "$0")/.."
HOST="${HA_SSH_HOST:-grigorii@server-home.lan}"
CONFIG="${HA_CONFIG:-Services/podman/homeassistant/config}"
python3 -I tests/test_model.py
rsync -av --delete --exclude __pycache__ custom_components/tranzy/ "$HOST:$CONFIG/custom_components/tranzy/"

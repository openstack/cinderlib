#!/usr/bin/env bash
# Script to ensure that calling commands added in the virtualenv with sudo will
# be able to find them during the functional tests, ie: cinder-rtstool

params=()
for arg in "$@"; do params+=("\"$arg\""); done
params="${params[@]}"
# Preserve user site-packages from the caller on the root user call in case
# it's a python program we are calling.
local_path=`python -c "import site; print(site.USER_SITE)"`
if [[ -n "$local_path" ]]; then
    if [[ -z "$PYTHONPATH" ]]; then
        PYTHONPATH="$local_path"
    else
        PYTHONPATH="$PYTHONPATH:$local_path"
    fi
fi
sudo -E --preserve-env=PATH,VIRTUAL_ENV,PYTHONPATH PYTHONPATH="$PYTHONPATH" /bin/bash -c "$params"

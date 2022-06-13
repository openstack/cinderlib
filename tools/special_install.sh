#!/bin/bash

# special-purpose pip installer, intended for tox use only

INSTALL_CMD="$*"

# need to know the toxinidir
if [[ -z "${TOX_INI_DIR:-}" ]] ; then
    echo "[error] This testenv must set the TOX_INI_DIR env var"
    exit 1
fi

if [[ -z "${CINDERLIB_CONSTRAINTS_FILE:-}" ]] ; then
    # generate the local constraints file without os_brick
    $TOX_INI_DIR/tools/generate_uc.sh -d $TOX_INI_DIR -n -x $CINDERLIB_RELEASE

    # use the absolute path to the generated file
    CINDERLIB_CONSTRAINTS_FILE="${TOX_INI_DIR}/local-upper-constraints.txt"
fi

# need to specify that we want the python in this testenv, not
# the default python bash would use
$TOX_ENV_DIR/bin/python -m pip install -c$CINDERLIB_CONSTRAINTS_FILE $INSTALL_CMD

#!/bin/bash

UC_LOC='https://releases.openstack.org/constraints/upper'
RELEASE='master'
OUTNAME='local-upper-constraints.txt'

print_usage() {
  cat <<EOF
usage: $(basename $0) [-o <outfile>] [<branch>]

Retrieve the upper-constraints for the specified release
and write them to the specified file.

positional arguments:
  branch           Release whose upper constraints you want.
                   Default is '$RELEASE'

optional arguments:
  -d, --directory  Directory to write the outfile to.
                   Default is the current directory
  -n, --no-error   Only warn if an error occurs when fetching updated
                   constraints.  (This allows a script to continue and
                   use an existing constraints file.)
  -o, --outfile    The file to write the upper constraints to.
                   Default is '$OUTNAME'
  -x, --exclude    Remove os-brick from the generated constraints file
                   (for when we want to install os-brick from source)
  -h, --help       Show this message and exit

EOF
}

get_constraints_file() {
    local C_FILE=$(mktemp)

    # if we use OUTFILE here, wget will destroy its content when the GET fails
    wget -q -O $C_FILE $UC_URL
    WGET_EXIT=$?

    if [[ "$WGET_EXIT" == "0" ]]; then
        cp $C_FILE $OUTFILE
    fi
    rm -f $C_FILE
    return $WGET_EXIT
}


# parse options
while [ "${1:0:1}" == "-" ] ; do
    if [[ "${1}" == '--help' || "${1}" == '-h' ]] ; then
        print_usage
        exit 0
    elif [[ "${1}" == '--directory' || "${1}" == '-d' ]] ; then
        shift
        OUTDIR="${1}"
    elif [[ "${1}" == '--no-error' || "${1}" == '-n' ]] ; then
        NO_ERROR=true
    elif [[ "${1}" == '--outfile' || "${1}" == '-o' ]] ; then
        shift
        OUTNAME="${1}"
    elif [[ "${1}" == '--exclude' || "${1}" == '-x' ]] ; then
        DO_EDIT=true
    else
        echo "[warning] ignoring unknown option '$1'"
    fi
    shift
done

# check for positional arg
if [[ -n ${1} ]]; then
    RELEASE="${1}"
fi

UC_URL="${UC_LOC}/${RELEASE}"

if [[ -n "${OUTDIR:-}" ]]; then
    OUTFILE="$OUTDIR/$OUTNAME"
else
    OUTFILE="$OUTNAME"
fi

get_constraints_file
RESULT=$?

if [[ "$RESULT" != "0" ]]; then
    if ${NO_ERROR:-false} ; then
        echo "[warning] wget error code $RESULT when getting new constraints"
    else
        echo "[error] could not get upper constraints file"
        exit $RESULT
    fi
fi

if ${DO_EDIT:-false}; then
    unset DO_EDIT
    sed -i -e '/^os-brick/d' $OUTFILE
fi

#!/bin/bash
# Docker/Podman entrypoint: bootstrap config files into the mounted volume, then run ector.
set -e

ECTOR_HOME="${ECTOR_HOME:-/opt/data}"
INSTALL_DIR="/opt/ector"

# --- Privilege dropping via gosu ---
# When started as root (the default for Docker, or fakeroot in rootless Podman),
# optionally remap the ector user/group to match host-side ownership, fix volume
# permissions, then re-exec as ector.
if [ "$(id -u)" = "0" ]; then
    if [ -n "$ECTOR_UID" ] && [ "$ECTOR_UID" != "$(id -u ector)" ]; then
        echo "Changing ector UID to $ECTOR_UID"
        usermod -u "$ECTOR_UID" ector
    fi

    if [ -n "$ECTOR_GID" ] && [ "$ECTOR_GID" != "$(id -g ector)" ]; then
        echo "Changing ector GID to $ECTOR_GID"
        # -o allows non-unique GID (e.g. macOS GID 20 "staff" may already exist
        # as "dialout" in the Debian-based container image)
        groupmod -o -g "$ECTOR_GID" ector 2>/dev/null || true
    fi

    # Fix ownership of the data volume. When ECTOR_UID remaps the ector user,
    # files created by previous runs (under the old UID) become inaccessible.
    # Always chown -R when UID was remapped; otherwise only if top-level is wrong.
    actual_ector_uid=$(id -u ector)
    needs_chown=false
    if [ -n "$ECTOR_UID" ] && [ "$ECTOR_UID" != "10000" ]; then
        needs_chown=true
    elif [ "$(stat -c %u "$ECTOR_HOME" 2>/dev/null)" != "$actual_ector_uid" ]; then
        needs_chown=true
    fi
    if [ "$needs_chown" = true ]; then
        echo "Fixing ownership of $ECTOR_HOME to ector ($actual_ector_uid)"
        # In rootless Podman the container's "root" is mapped to an unprivileged
        # host UID — chown will fail.  That's fine: the volume is already owned
        # by the mapped user on the host side.
        chown -R ector:ector "$ECTOR_HOME" 2>/dev/null || \
            echo "Warning: chown failed (rootless container?) — continuing anyway"
    fi

    # Ensure config.yaml is readable by the ector runtime user even if it was
    # edited on the host after initial ownership setup. Must run here (as root)
    # rather than after the gosu drop, otherwise a non-root caller like
    # `docker run -u $(id -u):$(id -g)` hits "Operation not permitted" (#15865).
    if [ -f "$ECTOR_HOME/config.yaml" ]; then
        chown ector:ector "$ECTOR_HOME/config.yaml" 2>/dev/null || true
        chmod 640 "$ECTOR_HOME/config.yaml" 2>/dev/null || true
    fi

    echo "Dropping root privileges"
    exec gosu ector "$0" "$@"
fi

# --- Running as ector from here ---
source "${INSTALL_DIR}/.venv/bin/activate"

# Create essential directory structure.  Cache and platform directories
# (cache/images, cache/audio, platforms/whatsapp, etc.) are created on
# demand by the application — don't pre-create them here so new installs
# get the consolidated layout from get_ector_dir().
# The "home/" subdirectory is a per-profile HOME for subprocesses (git,
# ssh, gh, npm …).  Without it those tools write to /root which is
# ephemeral and shared across profiles.  See issue #4426.
mkdir -p "$ECTOR_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}

# .env
if [ ! -f "$ECTOR_HOME/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$ECTOR_HOME/.env"
fi

# config.yaml
if [ ! -f "$ECTOR_HOME/config.yaml" ]; then
    cp "$INSTALL_DIR/cli-config.yaml.example" "$ECTOR_HOME/config.yaml"
fi

# SOUL.md
if [ ! -f "$ECTOR_HOME/SOUL.md" ]; then
    cp "$INSTALL_DIR/docker/SOUL.md" "$ECTOR_HOME/SOUL.md"
fi

# Final exec: two supported invocation patterns.
#
#   docker run <image>                 -> exec `ector` with no args (legacy default)
#   docker run <image> chat -q "..."   -> exec `ector chat -q "..."` (legacy wrap)
#   docker run <image> sleep infinity  -> exec `sleep infinity` directly
#   docker run <image> bash            -> exec `bash` directly
#
# If the first positional arg resolves to an executable on PATH, we assume the
# caller wants to run it directly (needed by the launcher which runs long-lived
# `sleep infinity` sandbox containers — see tools/environments/docker.py).
# Otherwise we treat the args as a ector subcommand and wrap with `ector`,
# preserving the documented `docker run <image> <subcommand>` behavior.
if [ $# -gt 0 ] && command -v "$1" >/dev/null 2>&1; then
    exec "$@"
fi
exec ector "$@"

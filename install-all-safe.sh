#!/usr/bin/env bash
# Deprecated: this entry point previously installed a SQLite historian.
# We deliberately fail before any filesystem, service or controller changes.
set -Eeuo pipefail
echo "DISABLED: full HaierPi core upgrade is intentionally blocked on this low-memory OverlayFS device." >&2
echo "Use install-diagnostics-light.sh for RAM-only cycle and circuit MQTT monitors." >&2
echo "The core HaierPi and its SD-card protections must not be modified by this package." >&2
exit 2

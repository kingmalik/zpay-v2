#!/usr/bin/env bash
# vault_moms_files.sh — copy mom's weekly payroll files to the zpay vault.
#
# Watches ~/Desktop for files matching:
#   W*_*_Payroll*.xlsx
#   W*_*_SPI.csv
#   W*_Master_Payroll*.xlsx
#
# Copies each matching file into:
#   ~/Library/Application Support/zpay-backups/moms-weekly/
#
# Never deletes from source.
# Skips if a file with identical content hash already exists in vault.
# Logs each copy to .vault.log in the vault directory.

set -euo pipefail

DESKTOP="${HOME}/Desktop"
VAULT="${HOME}/Library/Application Support/zpay-backups/moms-weekly"
LOG="${VAULT}/.vault.log"

mkdir -p "${VAULT}"

# Patterns to match
PATTERNS=(
    "W*_*_Payroll*.xlsx"
    "W*_*_SPI.csv"
    "W*_Master_Payroll*.xlsx"
)

copied=0
skipped=0

for pattern in "${PATTERNS[@]}"; do
    # Use nullglob-style: if no match, glob expands to literal — check with -f
    for src in "${DESKTOP}"/${pattern}; do
        [[ -f "${src}" ]] || continue

        filename="$(basename "${src}")"

        # Compute SHA-256 of source
        src_hash=$(shasum -a 256 "${src}" | awk '{print $1}')

        # Check if any file in vault has the same hash
        already_vaulted=false
        for existing in "${VAULT}/${filename}"*; do
            [[ -f "${existing}" ]] || continue
            existing_hash=$(shasum -a 256 "${existing}" | awk '{print $1}')
            if [[ "${src_hash}" == "${existing_hash}" ]]; then
                already_vaulted=true
                break
            fi
        done

        if [[ "${already_vaulted}" == "true" ]]; then
            skipped=$((skipped + 1))
            continue
        fi

        # Determine destination — use filename directly, no timestamp suffix
        # (idempotent: same filename + same hash = skip, handled above)
        dest="${VAULT}/${filename}"

        # If a file with same name but different content exists, add a timestamp suffix
        if [[ -f "${dest}" ]]; then
            ts="$(date +%Y%m%d_%H%M%S)"
            dest="${VAULT}/${filename%.xlsx}_${ts}.xlsx"
            [[ "${filename}" == *.csv ]] && dest="${VAULT}/${filename%.csv}_${ts}.csv"
        fi

        cp "${src}" "${dest}"
        copied=$((copied + 1))

        ts_log="$(date '+%Y-%m-%d %H:%M:%S')"
        echo "[${ts_log}] VAULTED: ${filename} → $(basename "${dest}") (sha256=${src_hash})" >> "${LOG}"
        echo "Vaulted: ${filename}"
    done
done

if [[ ${copied} -gt 0 || ${skipped} -gt 0 ]]; then
    echo "Done. Copied=${copied} Skipped=${skipped}"
else
    echo "No matching files found on Desktop."
fi

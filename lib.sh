# Shared helpers for DeckGrade dev scripts (sourced, not executed).
# Everything is derived from the script locations - no hardcoded paths.

# Repo root, based on the location of this file (lives in the root itself).
dg_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}

# Make node/pnpm available; sources nvm automatically for non-interactive
# shells where nvm's PATH entries are not loaded.
dg_load_node() {
  if command -v node >/dev/null 2>&1 && command -v pnpm >/dev/null 2>&1; then
    return 0
  fi
  if [ -z "${NVM_DIR:-}" ] && [ -s "$HOME/.nvm/nvm.sh" ]; then
    export NVM_DIR="$HOME/.nvm"
  fi
  if [ -n "${NVM_DIR:-}" ] && [ -s "$NVM_DIR/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "$NVM_DIR/nvm.sh" >/dev/null 2>&1 || true
  fi
  command -v node >/dev/null 2>&1 && command -v pnpm >/dev/null 2>&1
}

#!/usr/bin/env bash
# One-stop build for DeckGrade.
#
# Usage: build.sh [all|frontend|package|env]   (default: all)
#
#   all      frontend build + distribution zip
#   frontend pnpm install + rollup build (dist/index.js)
#   package  out/DeckGrade-v<version>.zip (+ .sha256), verified against the tree
#   env      print the detected toolchain
#
# Runs in any Linux shell (native or WSL); all paths are derived from the
# script location. On native Windows use build.bat instead.

set -eu
# shellcheck disable=SC1091
. "$(dirname "$0")/lib.sh"

ROOT="$(dg_root)"
step="${1:-all}"

frontend() {
  dg_load_node || {
    echo "error: node/pnpm not found (install them or set up nvm)" >&2
    exit 1
  }
  cd "$ROOT"
  echo "== pnpm install"
  pnpm install
  echo "== pnpm build"
  pnpm run build
  ls -la "$ROOT/dist"
}

package() {
  dg_load_node || command -v node >/dev/null 2>&1 || {
    echo "error: node not found (install it or set up nvm)" >&2
    exit 1
  }
  cd "$ROOT"
  node "$ROOT/make_zip.mjs"
}

env_info() {
  echo "repo root: $ROOT"
  if dg_load_node; then
    echo "node: $(command -v node) $(node --version)"
    echo "pnpm: $(command -v pnpm) $(pnpm --version)"
  else
    echo "node/pnpm: not found"
  fi
}

case "$step" in
  all)
    frontend
    package
    ;;
  frontend) frontend ;;
  package) package ;;
  env) env_info ;;
  *)
    echo "usage: $0 [all|frontend|package|env]" >&2
    exit 2
    ;;
esac

#!/usr/bin/env bash
set -euo pipefail

version="8.24.3"
install_dir="${1:-${RUNNER_TEMP:-/tmp}/creator-os-security-bin}"
architecture="$(uname -m)"

case "$architecture" in
  x86_64|amd64)
    archive="gitleaks_${version}_linux_x64.tar.gz"
    expected_sha256="9991e0b2903da4c8f6122b5c3186448b927a5da4deef1fe45271c3793f4ee29c"
    ;;
  arm64|aarch64)
    archive="gitleaks_${version}_linux_arm64.tar.gz"
    expected_sha256="5f2edbe1f49f7b920f9e06e90759947d3c5dfc16f752fb93aaafc17e9d14cf07"
    ;;
  *)
    echo "Unsupported gitleaks installer architecture: $architecture" >&2
    exit 1
    ;;
esac

mkdir -p "$install_dir"
chmod 700 "$install_dir"
temporary="$(mktemp -d "${RUNNER_TEMP:-/tmp}/creator-os-gitleaks.XXXXXX")"
trap 'rm -rf "$temporary"' EXIT

curl \
  --fail \
  --silent \
  --show-error \
  --location \
  --proto '=https' \
  --tlsv1.2 \
  --output "$temporary/$archive" \
  "https://github.com/gitleaks/gitleaks/releases/download/v${version}/${archive}"

printf '%s  %s\n' "$expected_sha256" "$temporary/$archive" | sha256sum --check -
tar -xzf "$temporary/$archive" -C "$temporary" gitleaks
install -m 0755 "$temporary/gitleaks" "$install_dir/gitleaks"
"$install_dir/gitleaks" version

if [[ -n "${GITHUB_PATH:-}" ]]; then
  printf '%s\n' "$install_dir" >>"$GITHUB_PATH"
fi

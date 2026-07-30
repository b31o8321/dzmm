#!/usr/bin/env bash
set -euo pipefail

mobile_root="$(cd "$(dirname "$0")" && pwd)"
android_root="$mobile_root/android"
keystore_path="$android_root/dzmm-internal-release.keystore"
properties_path="$android_root/key.properties"
alias_name="dzmm-internal"

if [[ -e "$keystore_path" || -e "$properties_path" ]]; then
  printf 'Refusing to overwrite existing signing files.\n' >&2
  exit 1
fi

command -v keytool >/dev/null
command -v openssl >/dev/null

umask 077
password="$(openssl rand -hex 32)"

keytool_args=(
  -genkeypair
  -keystore "$keystore_path"
  -storetype PKCS12
  -storepass "$password"
  -keypass "$password"
  -alias "$alias_name"
  -keyalg RSA
  -keysize 3072
  -validity 3650
  -dname "CN=dzmm Internal RC, OU=Internal Testing, O=dzmm, C=CN"
)
keytool "${keytool_args[@]}" >/dev/null

{
  printf 'storeFile=%s\n' "$keystore_path"
  printf 'storePassword=%s\n' "$password"
  printf 'keyAlias=%s\n' "$alias_name"
  printf 'keyPassword=%s\n' "$password"
} >"$properties_path"
chmod 600 "$keystore_path" "$properties_path"
unset password

printf 'Created ignored internal signing files:\n'
printf '  %s\n' "$keystore_path" "$properties_path"

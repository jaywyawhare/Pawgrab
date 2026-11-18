#!/usr/bin/env bash
# Regenerate every Pawgrab SDK from the live OpenAPI schema (F5).
#
# One source of truth: pawgrab/openapi.py dumps the schema, openapi-generator
# produces an idiomatic client per language. New endpoints (agent, interact,
# index, ranked map) land in all 9 SDKs automatically — nothing hand-written.
#
# Requirements: python3, and `openapi-generator-cli` on PATH
#   (https://openapi-generator.tech/docs/installation).
set -euo pipefail

cd "$(dirname "$0")/.."

OUT="sdk/openapi.json"
echo ">> dumping OpenAPI schema -> $OUT"
python3 -m pawgrab.openapi > "$OUT"

# generator-name : output dir
LANGS=(
  "python:sdk/python"
  "typescript-fetch:sdk/typescript"
  "go:sdk/go"
  "rust:sdk/rust"
  "java:sdk/java"
  "ruby:sdk/ruby"
  "php:sdk/php"
  "csharp:sdk/dotnet"
  "elixir:sdk/elixir"
)

for entry in "${LANGS[@]}"; do
  gen="${entry%%:*}"
  dir="${entry##*:}"
  echo ">> generating $gen -> $dir"
  openapi-generator-cli generate \
    -i "$OUT" \
    -g "$gen" \
    -o "$dir/generated" \
    --additional-properties=packageName=pawgrab,projectName=pawgrab,invokerPackage=dev.pawgrab
done

echo ">> done. Hand-written ergonomic wrappers live alongside each generated/ dir."

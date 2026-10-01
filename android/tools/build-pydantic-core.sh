#!/usr/bin/env bash
# Cross-compile pydantic-core for the DotDeck Android app (Chaquopy, cp313, android_24_arm64_v8a).
# See android/README.md and docs/adr/0011. Runs on Windows (Git Bash), Linux or macOS.
#
#   PYDANTIC_CORE=2.46.5 NDK=/path/to/ndk/27.x PYTARGET=/path/to/chaquopy-target-3.13 ./build-pydantic-core.sh
#
# PYTARGET is an unpacked com.chaquo.python:target:3.13.x (arm64-v8a zip → jniLibs/arm64-v8a/libpython3.13.so)
# with _sysconfigdata__android_aarch64-linux-android.py (from the matching -stdlib.zip) copied next to the .so.
# Needs: rustup target add aarch64-linux-android; pip install maturin; a host Python 3.13 (HOST_PYTHON).
set -euo pipefail
: "${PYDANTIC_CORE:?pydantic-core version, must match the pinned pydantic}"
: "${NDK:?path to the Android NDK}"
: "${PYTARGET:?path to the unpacked Chaquopy Python target}"
HOST_PYTHON="${HOST_PYTHON:-python3.13}"
OUT="${OUT:-$(cd "$(dirname "$0")/../app/wheels" && pwd)}"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) HOST=windows-x86_64; EXT=.cmd; AR=llvm-ar.exe ;;
  Darwin) HOST=darwin-x86_64; EXT=; AR=llvm-ar ;;
  *) HOST=linux-x86_64; EXT=; AR=llvm-ar ;;
esac
BIN="$NDK/toolchains/llvm/prebuilt/$HOST/bin"

export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$BIN/aarch64-linux-android24-clang$EXT"
export CC_aarch64_linux_android="$BIN/aarch64-linux-android24-clang$EXT"
export AR_aarch64_linux_android="$BIN/$AR"
export PYO3_CROSS=1
export PYO3_CROSS_PYTHON_VERSION=3.13
export PYO3_CROSS_LIB_DIR="$PYTARGET/jniLibs/arm64-v8a"
# modest memory use (a fat-LTO build of pydantic-core needs several GB)
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"
export CARGO_PROFILE_RELEASE_LTO="${CARGO_PROFILE_RELEASE_LTO:-off}"
export CARGO_PROFILE_RELEASE_CODEGEN_UNITS="${CARGO_PROFILE_RELEASE_CODEGEN_UNITS:-16}"

WORK="$(mktemp -d)"
cd "$WORK"
"$HOST_PYTHON" -m pip download --no-deps --no-binary :all: "pydantic-core==$PYDANTIC_CORE" -d .
tar xzf pydantic_core-*.tar.gz
cd "pydantic_core-$PYDANTIC_CORE"
maturin build --release --target aarch64-linux-android -i "$HOST_PYTHON" --out "$OUT"
echo "wheel written to $OUT"

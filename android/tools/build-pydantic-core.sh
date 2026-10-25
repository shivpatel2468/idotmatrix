#!/usr/bin/env bash
# Cross-compile pydantic-core for the DeskDot Android app (Chaquopy). Runs on Windows (Git Bash), Linux or macOS.
# See android/README.md and docs/adr/0011 (phone, cp313 arm64-v8a) and docs/adr/0012 (watch, cp311 armeabi-v7a).
#
#   # phone (arm64-v8a, cp313 — unchanged default):
#   PYDANTIC_CORE=2.46.5 NDK=/path/to/ndk/27.x PYTARGET=/path/to/chaquopy-target-3.13 ./build-pydantic-core.sh
#
#   # watch (armeabi-v7a, cp311):
#   PYDANTIC_CORE=2.46.5 NDK=/path/to/ndk/27.x PYTARGET=/path/to/chaquopy-target-3.11-armeabi-v7a \
#     ARCH=armv7 PY_VERSION=3.11 HOST_PYTHON=python3.11 ./build-pydantic-core.sh
#
# PYTARGET is an unpacked com.chaquo.python:target:<version> ABI zip (→ jniLibs/<abi>/libpython3.*.so) with its
# matching _sysconfigdata__android_<triple>.py (from the -stdlib.zip) copied next to the .so.
# Needs: rustup target add <rust-target-for-ARCH>; pip install maturin; a host Python matching PY_VERSION.
set -euo pipefail
: "${PYDANTIC_CORE:?pydantic-core version, must match the pinned pydantic}"
: "${NDK:?path to the Android NDK}"
: "${PYTARGET:?path to the unpacked Chaquopy Python target for this ABI}"
ARCH="${ARCH:-arm64}" # arm64 (phone, arm64-v8a) | armv7 (watch, armeabi-v7a)
PY_VERSION="${PY_VERSION:-3.13}"
HOST_PYTHON="${HOST_PYTHON:-python$PY_VERSION}"
OUT="${OUT:-$(cd "$(dirname "$0")/../app/wheels" && pwd)}"
API_LEVEL="${API_LEVEL:-24}" # arm64-v8a target; armv7 builds normally use 21/24 too (Chaquopy's armeabi-v7a floor)

case "$ARCH" in
  arm64) RUST_TARGET=aarch64-linux-android;  TRIPLE=aarch64-linux-android;    JNI_ABI=arm64-v8a ;;
  armv7) RUST_TARGET=armv7-linux-androideabi; TRIPLE=arm-linux-androideabi;    JNI_ABI=armeabi-v7a ;;
  *) echo "ARCH must be arm64 or armv7" >&2; exit 1 ;;
esac
RUST_ENV="$(echo "$RUST_TARGET" | tr 'a-z-' 'A-Z_')"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) HOST=windows-x86_64; EXT=.cmd; AR=llvm-ar.exe ;;
  Darwin) HOST=darwin-x86_64; EXT=; AR=llvm-ar ;;
  *) HOST=linux-x86_64; EXT=; AR=llvm-ar ;;
esac
BIN="$NDK/toolchains/llvm/prebuilt/$HOST/bin"
# armv7 clang wrappers are named with "eabi<api>-clang" (no thumb/soft-float suffix needed for pydantic-core)
CLANG="$BIN/${RUST_TARGET}${API_LEVEL}-clang$EXT"

export "CARGO_TARGET_${RUST_ENV}_LINKER"="$CLANG"
export "CC_${RUST_TARGET}"="$CLANG"
export "AR_${RUST_TARGET}"="$BIN/$AR"
export PYO3_CROSS=1
export PYO3_CROSS_PYTHON_VERSION="$PY_VERSION"
export PYO3_CROSS_LIB_DIR="$PYTARGET/jniLibs/$JNI_ABI"
# modest memory use (a fat-LTO build of pydantic-core needs several GB; armv7 codegen is also slower)
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"
export CARGO_PROFILE_RELEASE_LTO="${CARGO_PROFILE_RELEASE_LTO:-off}"
export CARGO_PROFILE_RELEASE_CODEGEN_UNITS="${CARGO_PROFILE_RELEASE_CODEGEN_UNITS:-16}"

WORK="$(mktemp -d)"
cd "$WORK"
"$HOST_PYTHON" -m pip download --no-deps --no-binary :all: "pydantic-core==$PYDANTIC_CORE" -d .
tar xzf pydantic_core-*.tar.gz
cd "pydantic_core-$PYDANTIC_CORE"
maturin build --release --target "$RUST_TARGET" -i "$HOST_PYTHON" --out "$OUT"
echo "wheel written to $OUT (ABI $JNI_ABI, cp$(echo "$PY_VERSION" | tr -d .))"

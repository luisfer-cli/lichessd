#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$PROJECT_DIR/dist"
BUILD_DIR="$PROJECT_DIR/build"
SPEC_FILE="$PROJECT_DIR/lichessd.spec"
ENTRY_POINT="$PROJECT_DIR/src/lichessd/__main__.py"
BINARY_NAME="lichessd"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python3"

clean() {
	echo "==> Cleaning previous builds..."
	rm -rf "$DIST_DIR" "$BUILD_DIR" "$SPEC_FILE"
}

ensure_venv() {
	if [ ! -f "$VENV_PYTHON" ]; then
		echo "ERROR: Virtual environment not found at .venv"
		echo "Run 'uv sync' first to create it."
		exit 1
	fi

	if ! "$VENV_PYTHON" -c "import PyInstaller" 2>/dev/null; then
		echo "==> Installing PyInstaller..."
		uv add --dev pyinstaller --directory "$PROJECT_DIR"
	fi
}

build() {
	echo "==> Building $BINARY_NAME..."
	"$VENV_PYTHON" -m PyInstaller \
		--onefile \
		--name "$BINARY_NAME" \
		--distpath "$DIST_DIR" \
		--workpath "$BUILD_DIR" \
		--specpath "$PROJECT_DIR" \
		--hidden-import httpx \
		"$ENTRY_POINT"
}

verify() {
	local bin="$DIST_DIR/$BINARY_NAME"
	if [ ! -f "$bin" ]; then
		echo "ERROR: Binary not found at $bin"
		exit 1
	fi

	echo "==> Stripping binary..."
	strip "$bin" 2>/dev/null || true

	echo ""
	echo "==> Binary info:"
	echo "    Path:   $bin"
	echo "    Size:   $(du -h "$bin" | cut -f1)"
	echo "    Type:   $(file -b "$bin")"
	echo ""
	echo "==> Testing --help..."
	"$bin" --help
	echo ""
	echo "Build complete: $bin"
}

case "${1:-all}" in
clean)
	clean
	;;
build-only)
	ensure_venv
	build
	echo "Binary: $DIST_DIR/$BINARY_NAME"
	;;
*)
	clean
	ensure_venv
	build
	verify
	;;
esac

# BioCSSwitch for Linux

BioCSSwitch Linux is built for x64 Ubuntu 22.04+ and Debian 12+. Each release
contains both a Debian package and an AppImage.

## Prerequisites

Install Claude Science for Linux first. Anthropic documents its supported Linux
distributions and installation instructions at <https://support.claude.com/en/articles/10065433-install-claude-desktop>.
After installation, `claude-science` must be available on `PATH`. For a
portable or non-standard installation, start BioCSSwitch with:

```bash
SCIENCE_BIN=/absolute/path/to/claude-science BioCSSwitch
```

BioCSSwitch keeps its own sandbox under `~/.csswitch/sandbox/home` and does
not copy, modify, or use the real `~/.claude-science` credentials directory.

## Install

### Debian or Ubuntu

Download the `.deb` asset from the relevant GitHub Release, then run:

```bash
sudo apt install ./BioCSSwitch_*.deb
```

Launch it from the desktop application menu or with `BioCSSwitch`.

### Other x64 Linux distributions

Download the `.AppImage` asset, make it executable, and launch it:

```bash
chmod +x BioCSSwitch_*.AppImage
./BioCSSwitch_*.AppImage
```

The AppImage may require FUSE to be installed by the host distribution.

## Building from source

Install the Linux Tauri system dependencies, Python 3.10+, Node.js, and Rust,
then run:

```bash
python3 -m pip install -e ".[dev]"
cd desktop
npm install
npm run tauri build
```

The generated installers are in `desktop/src-tauri/target/release/bundle/deb/`
and `desktop/src-tauri/target/release/bundle/appimage/`.

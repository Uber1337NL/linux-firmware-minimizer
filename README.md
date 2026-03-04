# linux-firmware-minimal

A Python script to build a minimal `linux-firmware` RPM containing only the firmware files needed for your specific hardware. Reduces the package size by up to 75% compared to the full `linux-firmware` package.

## Features

- Automatically downloads the latest `linux-firmware` RPM from your configured DNF repositories
- Filters firmware files based on a simple YAML configuration
- Supports wildcard patterns (e.g. `iwlwifi-*`, `rtl_nic/*`)
- Builds a proper RPM using `rpmbuild`, with `fpm` as fallback
- Each build gets a unique timestamp-based `Release` tag (e.g. `1.0-202603041831.el10`) for clean `dnf update` support
- Dry-run mode to preview which files would be kept or removed
- Automatically detects firmware path (`/lib/firmware` or `/usr/lib/firmware`)

## Requirements

### System packages

```bash
dnf install python3-pyyaml rpm-build rpmdevtools
```

### Python Virtual Environment (Optional)

If you prefer not to install `python3-pyyaml` globally:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Optional (fallback RPM builder)

```bash
gem install fpm
```

## Installation

```bash
git clone https://github.com/Uber1337NL/linux-firmware-minimal
cd linux-firmware-minimal
chmod +x firmware_minimizer.py
```

## Configuration

Create a `drivers.yaml` file in the same directory as the script. List the firmware files or patterns you want to keep:

```yaml
drivers:
  - iwlwifi-*           # Intel WiFi drivers
  - rtl_nic/*           # Realtek NIC firmware
  - i915/*              # Intel GPU (iGPU)
  - amdgpu/*            # AMD GPU
  - nvidia/*            # NVIDIA GPU
  - rtw88/*             # Realtek WiFi (rtw88)
  - intel/ibt-*         # Intel Bluetooth
  - qed/*               # Marvell/QLogic network
  - bnx2/*              # Broadcom NetXtreme II
```

Patterns are matched against the relative path inside the firmware directory. Both `*` (any characters) and `?` (single character) wildcards are supported.

## Usage

### Basic usage

```bash
./firmware_minimizer.py
```

### All options

```usage: firmware_minimizer.py [-h] [-d DRIVERS_FILE] [-o OUTPUT_RPM] [-V VERSION] [--dry-run] [--keep-temp]
options:
  -h, --help            Show this help message and exit
  -d, --drivers-file    YAML file with drivers to keep (default: drivers.yaml)
  -o, --output-rpm      Output RPM path/name (default: linux-firmware-minimal.rpm)
  -V, --version         RPM version number (default: 1.0)
  --dry-run             Preview which files would be kept/removed without making changes
  --keep-temp           Keep the temporary directory for debugging/inspection
```

### Examples

```bash
# Standard build
./firmware_minimizer.py

# Preview without making changes
./firmware_minimizer.py --dry-run

# Custom drivers file and output name
./firmware_minimizer.py --drivers-file my-server.yaml --output-rpm my-server-firmware.rpm

# Keep temp directory for inspection after build
./firmware_minimizer.py --keep-temp
```

## Output

The built RPM is placed in `~/rpmbuild/RPMS/noarch/` and follows the naming convention:

```linux-firmware-minimal-1.0-202603041831.el10.noarch.rpm```

The `Release` tag is a timestamp (`YYYYMMDDHHMM`), ensuring every build is treated as newer by `dnf`. This allows seamless updates via:

```bash
dnf install ~/rpmbuild/RPMS/noarch/linux-firmware-minimal-*.rpm
# or after adding to a local repo:
dnf update linux-firmware-minimal
```

## Example results

|                            | Size                |
| -------------------------- | ------------------- |
| Original `linux-firmware`  | 60.0 MB             |
| Minimal build (12 drivers) | 14.6 MB             |
| **Savings**                | **45.3 MB (75.6%)** |

## Project structure

```.
├── firmware_minimizer.py   # Main script
├── drivers.yaml            # Your driver configuration
└── tmp/                    # Temporary build directory (auto-cleaned)
```

## Authors

- **Randy** — Initial internal version (2014-02-18) — [github.com/Uber1337NL](https://github.com/Uber1337NL)
- Refactored 2026-02-26 for public GitHub release. Updated to Python 3.12+ and translated om 20260304.

## License

The script itself is MIT licensed. The firmware files packaged by this tool are subject to their own respective licenses as included in `/usr/share/licenses/linux-firmware/`.

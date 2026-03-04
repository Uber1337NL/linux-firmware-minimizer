#!/usr/bin/env python3
"""
Script to create a minimal linux-firmware RPM containing only the needed drivers.

Required Linux packages (Alma/RHEL/CentOS):
    dnf install python3-pyyaml rpm-build rpmdevtools

Examples:
    python3 firmware_minimizer.py
    python3 firmware_minimizer.py --drivers-file drivers.yaml --output-rpm custom-fw.rpm
    python3 firmware_minimizer.py --dry-run

Author: Randy ten Have - github.com/Uber1337NL
Version: 202603041631

Changelog:
2015mmdd - Oldtimer script found in internal repo when cleaning up.
20260226 - Refactor to newer Python when moving from internal repo to GitHub
20260304 - Added timestamp to Release for unique builds, translated to English.
           Also added more error handling and a dry-run mode.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml


class FirmwareMinimizerError(Exception):
    """Custom exception for errors in the firmware minimizer."""


def run_command(
    cmd: Sequence[str], cwd: Path | None = None
) -> subprocess.CompletedProcess:
    """Run a shell command and raise FirmwareMinimizerError on failure."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            check=True,
        )
        return result
    except subprocess.CalledProcessError as e:
        msg = [
            f"Command failed: {' '.join(cmd)}",
            f"Exit code: {e.returncode}",
        ]
        if e.stdout:
            msg.append(f"STDOUT:\n{e.stdout}")
        if e.stderr:
            msg.append(f"STDERR:\n{e.stderr}")
        raise FirmwareMinimizerError("\n".join(msg)) from e


def download_latest_firmware_rpm(download_dir: Path) -> Path:
    """Download the latest linux-firmware RPM from the repo using dnf."""
    print("Searching for the latest linux-firmware RPM...")

    run_command(
        [
            "dnf",
            "download",
            "--downloadonly",
            "--downloaddir",
            str(download_dir),
            "linux-firmware",
        ]
    )

    rpm_files = sorted(download_dir.glob("linux-firmware-*.rpm"))
    if not rpm_files:
        raise FirmwareMinimizerError(
            "No linux-firmware RPM file found in download directory."
        )

    rpm_path = rpm_files[0]
    print(f"Downloaded: {rpm_path}")
    return rpm_path


def read_drivers_yaml(yaml_file: Path) -> list[str]:
    """Read the drivers.yaml file with the drivers to keep."""
    print(f"Reading {yaml_file}...")

    if not yaml_file.exists():
        raise FirmwareMinimizerError(f"{yaml_file} not found.")

    try:
        with yaml_file.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise FirmwareMinimizerError(f"Error parsing YAML: {e}") from e

    drivers = config.get("drivers", [])
    if not isinstance(drivers, list):
        raise FirmwareMinimizerError("drivers.yaml: 'drivers' must be a list.")

    print(f"Found {len(drivers)} drivers to keep")
    return [str(d) for d in drivers]


def extract_rpm(rpm_file: Path, extract_dir: Path) -> None:
    """Extract the RPM to a temporary directory."""
    print(f"Extracting RPM to {extract_dir}...")

    # Use rpm2cpio and cpio to extract
    try:
        rpm2cpio = subprocess.Popen(
            ["rpm2cpio", str(rpm_file)],
            stdout=subprocess.PIPE,
        )
        subprocess.run(
            ["cpio", "-idmv"],
            stdin=rpm2cpio.stdout,
            cwd=str(extract_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        if rpm2cpio.stdout is not None:
            rpm2cpio.stdout.close()
        rpm2cpio.wait()
        if rpm2cpio.returncode != 0:
            raise FirmwareMinimizerError(
                f"rpm2cpio failed with return code {rpm2cpio.returncode}"
            )
    except subprocess.CalledProcessError as e:
        raise FirmwareMinimizerError(f"Error extracting RPM: {e}") from e
    except OSError as e:
        raise FirmwareMinimizerError(f"Error executing rpm2cpio/cpio: {e}") from e

    print("Extraction completed")


def _compile_patterns(
    drivers_to_keep: Sequence[str],
) -> list[re.Pattern]:
    """
    Convert driver patterns with wildcards to regex patterns,.

    matched against the relative path (string). Patterns are anchored (^...$).
    """
    patterns: list[re.Pattern] = []
    for driver in drivers_to_keep:
        pattern_str = re.escape(driver)
        pattern_str = pattern_str.replace(r"\*", ".*").replace(r"\?", ".")
        pattern_str = f"^{pattern_str}$"
        patterns.append(re.compile(pattern_str))
    return patterns


def filter_firmware_files(
    extract_dir: Path,
    drivers_to_keep: Sequence[str],
    dry_run: bool = False,
) -> None:
    """
    Remove all firmware files except the specified drivers.

    In dry_run mode, no files are actually removed.
    """
    print("Filtering firmware files...")

    # Find the firmware directory, it might be lib/firmware or usr/lib/firmware
    firmware_dir = None
    for candidate in extract_dir.rglob("firmware"):
        if candidate.is_dir():
            firmware_dir = candidate
            break

    if firmware_dir is None:
        raise FirmwareMinimizerError(f"Firmware directory not found in {extract_dir}")

    patterns = _compile_patterns(drivers_to_keep)

    kept_files: list[Path] = []
    removed_files: list[Path] = []

    for item in firmware_dir.rglob("*"):
        if not item.is_file():
            continue

        relative_path = item.relative_to(firmware_dir)
        rel_str = str(relative_path)

        keep = False
        for p in patterns:
            if p.search(rel_str):
                keep = True
                break

        if keep:
            kept_files.append(relative_path)
        else:
            removed_files.append(relative_path)
            if not dry_run:
                item.unlink()

    print(f"Kept: {len(kept_files)} files")
    print(f"Removed: {len(removed_files)} files")

    if dry_run:
        print("\nDry-run mode: no files were actually removed.")
    else:
        # Remove empty directories (bottom-up)
        for dir_path in sorted(firmware_dir.rglob("*"), reverse=True):
            if dir_path.is_dir() and not any(dir_path.iterdir()):
                dir_path.rmdir()

    # For additional insight, you can optionally display the lists:
    print("\nKept files:")
    for p in kept_files:
        print(f"  {p}")
    print("\nRemoved files:")
    for p in removed_files:
        print(f"  {p}")


def _get_timestamp() -> str:
    """Generate a timestamp for the Release tag."""
    return datetime.now().strftime("%Y%m%d%H%M")


def _generate_spec_content(version: str, extract_dir: Path, release: str) -> str:
    """Generate the content of the RPM spec file."""
    date_str = datetime.now().strftime("%a %b %d %Y")

    # Detect whether firmware lives under lib/firmware or usr/lib/firmware
    if (extract_dir / "usr" / "lib" / "firmware").is_dir():
        firmware_files_entry = "/usr/lib/firmware"
    else:
        firmware_files_entry = "/lib/firmware"

    return f"""%define _build_id_links none
%global debug_package %{{nil}}
%define __spec_install_pre /bin/true
%define _unpackaged_files_terminate_build 0

Name:           linux-firmware-minimal
Version:        {version}
Release:        {release}%{{?dist}}
Summary:        Minimal Linux firmware with only needed drivers
License:        Redistributable, no modification permitted
URL:            https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git
BuildArch:      noarch

%description
Minimal version of linux-firmware with only the needed drivers.

%prep

%build

%install
/bin/true

%files
{firmware_files_entry}
%license /usr/share/licenses/linux-firmware/*
%doc /usr/share/doc/linux-firmware/*

%changelog
* {date_str} Builder <builder@localhost> - {version}-{release}
- Minimal firmware build with timestamp release
"""


def create_rpm(
    extract_dir: Path,
    output_rpm: Path,
    version: str = "1.0",
    firmware_dir: str = "lib/firmware",
) -> Path:
    """Create a new RPM from the filtered files."""
    print("Creating new RPM...")

    build_root = extract_dir
    spec_file = extract_dir.parent / "linux-firmware-minimal.spec"
    rpm_output_dir = Path.home() / "rpmbuild" / "RPMS"

    release = _get_timestamp()

    # Write spec file
    spec_content = _generate_spec_content(version, extract_dir, release)
    spec_file.write_text(spec_content, encoding="utf-8")

    # Try rpmbuild
    try:
        run_command(
            [
                "rpmbuild",
                "-bb",
                "--buildroot",
                str(build_root),
                str(spec_file),
            ]
        )

        # Try to find the latest generated RPM in rpmbuild/RPMS
        if rpm_output_dir.exists():
            built_rpms = sorted(rpm_output_dir.rglob("linux-firmware-minimal-*.rpm"))
            if built_rpms:
                rpm_path = built_rpms[-1]
                print(f"RPM successfully created with rpmbuild: {rpm_path}")
                return rpm_path

        print(
            "rpmbuild seems to have completed, but no RPM found in rpmbuild/RPMS. "
            "Please check manually."
        )
        return output_rpm

    except FirmwareMinimizerError as e:
        print(f"Error creating RPM with rpmbuild:\n{e}")
        print("Trying fpm as a fallback (gem install fpm)...")

    # Fallback to fpm
    try:
        run_command(
            [
                "fpm",
                "-s",
                "dir",
                "-t",
                "rpm",
                "-n",
                "linux-firmware-minimal",
                "-v",
                version,
                "--iteration",
                release,
                "--prefix",
                "/",
                "-C",
                str(extract_dir),
                "-p",
                str(output_rpm),
                firmware_dir,
            ]
        )
        print(f"RPM created with fpm: {output_rpm}")
        return output_rpm
    except FirmwareMinimizerError as e:
        raise FirmwareMinimizerError(
            "Could not create RPM with rpmbuild or fpm. "
            "Consider installing fpm: gem install fpm"
        ) from e


def print_missing_yaml_help(yaml_name: str = "drivers.yaml") -> None:
    """Display example configuration if drivers.yaml is missing."""
    print(f"First, create a {yaml_name} file with this structure:")
    print(
        """
drivers:
  - iwlwifi-*           # Intel WiFi drivers
  - rtl_nic/*           # Realtek network drivers
  - i915/*              # Intel graphics
  - amdgpu/*            # AMD graphics
  - nvidia/*            # NVIDIA graphics
  - rtw88/*             # Realtek WiFi
"""
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Create a minimal linux-firmware RPM with only the necessary drivers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-d",
        "--drivers-file",
        type=Path,
        default=Path("drivers.yaml"),
        help="YAML file with drivers to keep.",
    )
    parser.add_argument(
        "-o",
        "--output-rpm",
        type=Path,
        default=Path("linux-firmware-minimal.rpm"),
        help="Path/name of the output RPM.",
    )
    parser.add_argument(
        "-V",
        "--version",
        type=str,
        default="1.0",
        help="Version number for the RPM.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which files would be kept/removed, "
        "but do not make any changes or build an RPM.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary directory for debugging/inspection.",
    )

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Main function."""
    args = parse_args(argv)

    print("=== Linux Firmware RPM Minimizer ===\n")

    yaml_file: Path = args.drivers_file
    desired_output_rpm: Path = args.output_rpm
    version: str = args.version
    dry_run: bool = args.dry_run
    keep_temp: bool = args.keep_temp

    if not yaml_file.exists():
        print_missing_yaml_help(yaml_file.name)
        sys.exit(1)

    temp_dir_obj: tempfile.TemporaryDirectory[str] | None = None
    rpm_file: Path | None = None
    built_rpm: Path | None = None

    # Create local temp base directory
    temp_base = Path("./tmp")
    temp_base.mkdir(parents=True, exist_ok=True)

    try:
        drivers_to_keep = read_drivers_yaml(yaml_file)

        # Use local temp directory instead of system /tmp
        temp_dir_obj = tempfile.TemporaryDirectory(
            dir=str(temp_base), delete=not keep_temp
        )
        temp_dir = Path(temp_dir_obj.name)

        download_dir = temp_dir / "download"
        extract_dir = temp_dir / "extract"
        download_dir.mkdir(parents=True, exist_ok=True)
        extract_dir.mkdir(parents=True, exist_ok=True)

        rpm_file = download_latest_firmware_rpm(download_dir)
        extract_rpm(rpm_file, extract_dir)
        filter_firmware_files(extract_dir, drivers_to_keep, dry_run=dry_run)

        if dry_run:
            print("\nDry-run completed. No RPM was built and no files were removed.")
            return

        built_rpm = create_rpm(extract_dir, desired_output_rpm, version=version)

        print(f"\n✓ Done! Compact RPM: {built_rpm}")

        # Show size comparison (if files exist)
        if rpm_file.exists() and built_rpm.exists():
            original_size_mb = rpm_file.stat().st_size / (1024 * 1024)
            new_size_mb = built_rpm.stat().st_size / (1024 * 1024)

            print(f"Original: {original_size_mb:.1f} MB")
            print(f"New:      {new_size_mb:.1f} MB")
            if original_size_mb > 0:
                saving_mb = original_size_mb - new_size_mb
                saving_pct = (1 - new_size_mb / original_size_mb) * 100
                print(f"Saving:   {saving_mb:.1f} MB ({saving_pct:.1f}%)")

    except FirmwareMinimizerError as e:
        print(f"\nError: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(1)
    finally:
        # Clean up temporary directory, unless --keep-temp is used
        if temp_dir_obj is not None and not keep_temp:
            temp_dir_obj.cleanup()
        elif keep_temp and temp_dir_obj is not None:
            print(f"Temporary directory retained: {temp_dir_obj.name}")


if __name__ == "__main__":
    main()

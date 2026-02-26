#!/usr/bin/env python3
"""
Script om een compacte linux-firmware RPM te maken met alleen de benodigde drivers.

Benodigde Linux packages (Alma/RHEL/CentOS):
    dnf install python3-pyyaml rpm-build rpmdevtools

Voorbeelden:
    python3 firmware_minimize.py
    python3 firmware_minimize.py --drivers-file drivers.yaml --output-rpm custom-fw.rpm
    python3 firmware_minimize.py --dry-run

20140218 - Randy - github.com/Uber1337NL
20260226 - Refactor LLM when moving fromn internal repo to GitHub
"""

from __future__ import annotations

import sys
import subprocess
import tempfile
import re
import argparse
from pathlib import Path
from typing import List, Sequence

import yaml


class FirmwareMinimizerError(Exception):
    """Custom exceptie voor fouten in de firmware minimizer."""


def run_command(cmd: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """
    Run a shell command and raise FirmwareMinimizerError on failure.
    """
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
            f"Commando mislukt: {' '.join(cmd)}",
            f"Exit code: {e.returncode}",
        ]
        if e.stdout:
            msg.append(f"STDOUT:\n{e.stdout}")
        if e.stderr:
            msg.append(f"STDERR:\n{e.stderr}")
        raise FirmwareMinimizerError("\n".join(msg)) from e


def download_latest_firmware_rpm(download_dir: Path) -> Path:
    """
    Download de laatste linux-firmware RPM van de repo met dnf.
    """
    print("Zoeken naar laatste linux-firmware RPM...")

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
        raise FirmwareMinimizerError("Geen linux-firmware RPM bestand gevonden in download directory.")

    rpm_path = rpm_files[0]
    print(f"Gedownload: {rpm_path}")
    return rpm_path


def read_drivers_yaml(yaml_file: Path) -> List[str]:
    """
    Lees de drivers.yaml file met te behouden modules.
    """
    print(f"Lezen van {yaml_file}...")

    if not yaml_file.exists():
        raise FirmwareMinimizerError(f"{yaml_file} niet gevonden.")

    try:
        with yaml_file.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise FirmwareMinimizerError(f"Fout bij parsen van YAML: {e}") from e

    drivers = config.get("drivers", [])
    if not isinstance(drivers, list):
        raise FirmwareMinimizerError("drivers.yaml: 'drivers' moet een lijst zijn.")

    print(f"Gevonden {len(drivers)} drivers om te behouden")
    return [str(d) for d in drivers]


def extract_rpm(rpm_file: Path, extract_dir: Path) -> None:
    """
    Extraheer de RPM naar een tijdelijke directory.
    """
    print(f"Extraheren van RPM naar {extract_dir}...")

    # Gebruik rpm2cpio en cpio om te extraheren
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
        rpm2cpio.wait()
    except subprocess.CalledProcessError as e:
        raise FirmwareMinimizerError(f"Fout bij extraheren van RPM: {e}") from e
    except OSError as e:
        raise FirmwareMinimizerError(f"Fout bij uitvoeren van rpm2cpio/cpio: {e}") from e

    print("Extractie voltooid")


def _compile_patterns(drivers_to_keep: Sequence[str]) -> List[re.Pattern]:
    """
    Converteer driver patronen met wildcards naar regex patronen,
    gematcht tegen het relative path (string). Patterns worden geankerd (^...$).
    """
    patterns: List[re.Pattern] = []
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
    Verwijder alle firmware bestanden behalve de opgegeven drivers.

    Bij dry_run worden geen bestanden daadwerkelijk verwijderd.
    """
    print("Filteren van firmware bestanden...")

    firmware_dir = extract_dir / "lib" / "firmware"
    if not firmware_dir.exists():
        raise FirmwareMinimizerError(f"Firmware directory niet gevonden: {firmware_dir}")

    patterns = _compile_patterns(drivers_to_keep)

    kept_files: list[Path] = []
    removed_files: list[Path] = []

    for item in firmware_dir.rglob("*"):
        if not item.is_file():
            continue

        relative_path = item.relative_to(firmware_dir)
        rel_str = str(relative_path)

        keep = any(p.search(rel_str) for p in patterns)

        if keep:
            kept_files.append(relative_path)
        else:
            removed_files.append(relative_path)
            if not dry_run:
                item.unlink()

    print(f"Behouden: {len(kept_files)} bestanden")
    print(f"Te verwijderen: {len(removed_files)} bestanden")

    if dry_run:
        print("\nDry-run modus: er zijn geen bestanden verwijderd.")
    else:
        # Verwijder lege directories (bottom-up)
        for dir_path in sorted(firmware_dir.rglob("*"), reverse=True):
            if dir_path.is_dir() and not any(dir_path.iterdir()):
                dir_path.rmdir()

    # Voor extra inzicht kun je desgewenst de lijsten tonen:
    # print("\nBehouden bestanden:")
    # for p in kept_files:
    #     print(f"  {p}")
    # print("\nVerwijderde bestanden:")
    # for p in removed_files:
    #     print(f"  {p}")


def _generate_spec_content(version: str, extract_dir: Path) -> str:
    """Genereer de inhoud van het RPM spec-bestand."""
    date_str = subprocess.check_output(["date", "+%a %b %d %Y"]).decode().strip()

    return f"""Name:           linux-firmware-minimal
Version:        {version}
Release:        1%{{?dist}}
Summary:        Minimale Linux firmware met alleen benodigde drivers
License:        Redistributable, no modification permitted
URL:            https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git
BuildArch:      noarch

%description
Minimale versie van linux-firmware met alleen de benodigde drivers.

%prep

%build

%install
mkdir -p %{{buildroot}}
cp -a {extract_dir}/* %{{buildroot}}/

%files
/lib/firmware

%changelog
* {date_str} Builder <builder@localhost> - {version}-1
- Minimale firmware build
"""


def create_rpm(extract_dir: Path, output_rpm: Path, version: str = "1.0") -> Path:
    """
    Maak een nieuwe RPM van de gefilterde bestanden.

    Probeert eerst rpmbuild, valt terug op fpm indien rpmbuild faalt.
    """
    print("Maken van nieuwe RPM...")

    build_root = extract_dir
    spec_file = extract_dir.parent / "linux-firmware-minimal.spec"
    rpm_output_dir = Path.home() / "rpmbuild" / "RPMS"

    # Schrijf spec file
    spec_content = _generate_spec_content(version, extract_dir)
    spec_file.write_text(spec_content, encoding="utf-8")

    # Probeer rpmbuild
    try:
        run_command(["rpmbuild", "-bb", "--buildroot", str(build_root), str(spec_file)])

        # Probeer de nieuwste gegenereerde RPM te vinden in rpmbuild/RPMS
        if rpm_output_dir.exists():
            built_rpms = sorted(rpm_output_dir.rglob("linux-firmware-minimal-*.rpm"))
            if built_rpms:
                rpm_path = built_rpms[-1]
                print(f"RPM succesvol gemaakt met rpmbuild: {rpm_path}")
                return rpm_path

        print("rpmbuild lijkt voltooid, maar geen RPM gevonden in rpmbuild/RPMS. "
              "Controleer handmatig.")
        return output_rpm

    except FirmwareMinimizerError as e:
        print(f"Fout bij maken RPM met rpmbuild:\n{e}")
        print("Probeer fpm als fallback (gem install fpm)...")

    # Fallback naar fpm
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
                "--prefix",
                "/",
                "-C",
                str(extract_dir),
                "-p",
                str(output_rpm),
                "lib/firmware",
            ]
        )
        print(f"RPM gemaakt met fpm: {output_rpm}")
        return output_rpm
    except FirmwareMinimizerError as e:
        raise FirmwareMinimizerError(
            "Kon geen RPM maken met rpmbuild of fpm. "
            "Installeer eventueel fpm: gem install fpm"
        ) from e


def print_missing_yaml_help(yaml_name: str = "drivers.yaml") -> None:
    """Geef voorbeeldconfiguratie weer als drivers.yaml ontbreekt."""
    print(f"Maak eerst een {yaml_name} bestand met deze structuur:")
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
    """Parseer command line argumenten."""
    parser = argparse.ArgumentParser(
        description="Maak een minimale linux-firmware RPM met alleen de benodigde drivers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-d",
        "--drivers-file",
        type=Path,
        default=Path("drivers.yaml"),
        help="YAML-bestand met drivers die behouden moeten blijven.",
    )
    parser.add_argument(
        "-o",
        "--output-rpm",
        type=Path,
        default=Path("linux-firmware-minimal.rpm"),
        help="Pad/naam van de output RPM.",
    )
    parser.add_argument(
        "-V",
        "--version",
        type=str,
        default="1.0",
        help="Versienummer voor de RPM.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Toon welke bestanden behouden/verwijderd zouden worden, "
             "maar voer geen wijzigingen uit en bouw geen RPM.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Bewaar de tijdelijke directory voor debug/inspectie.",
    )

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Hoofdfunctie."""
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

    try:
        drivers_to_keep = read_drivers_yaml(yaml_file)

        # Maak ofwel een tijdelijke directory, of gebruik er een die blijft bestaan
        if keep_temp:
            temp_dir_obj = tempfile.TemporaryDirectory()
            temp_dir = Path(temp_dir_obj.name)
            print(f"Tijdelijke directory (blijft bestaan): {temp_dir}")
        else:
            temp_dir_obj = tempfile.TemporaryDirectory()
            temp_dir = Path(temp_dir_obj.name)

        download_dir = temp_dir / "download"
        extract_dir = temp_dir / "extract"
        download_dir.mkdir(parents=True, exist_ok=True)
        extract_dir.mkdir(parents=True, exist_ok=True)

        rpm_file = download_latest_firmware_rpm(download_dir)
        extract_rpm(rpm_file, extract_dir)
        filter_firmware_files(extract_dir, drivers_to_keep, dry_run=dry_run)

        if dry_run:
            print("\nDry-run voltooid. Er is geen RPM gebouwd en er zijn geen bestanden verwijderd.")
            return

        built_rpm = create_rpm(extract_dir, desired_output_rpm, version=version)

        print(f"\n✓ Klaar! Compacte RPM: {built_rpm}")

        # Toon grootte vergelijking (indien bestanden bestaan)
        if rpm_file.exists() and built_rpm.exists():
            original_size_mb = rpm_file.stat().st_size / (1024 * 1024)
            new_size_mb = built_rpm.stat().st_size / (1024 * 1024)

            print(f"Origineel: {original_size_mb:.1f} MB")
            print(f"Nieuw:     {new_size_mb:.1f} MB")
            if original_size_mb > 0:
                saving_mb = original_size_mb - new_size_mb
                saving_pct = (1 - new_size_mb / original_size_mb) * 100
                print(f"Besparing: {saving_mb:.1f} MB ({saving_pct:.1f}%)")

    except FirmwareMinimizerError as e:
        print(f"\nFout: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAfgebroken door gebruiker.")
        sys.exit(1)
    finally:
        # Ruim tijdelijke directory op, behalve als --keep-temp is gebruikt
        if temp_dir_obj is not None and not keep_temp:
            temp_dir_obj.cleanup()
        elif keep_temp and temp_dir_obj is not None:
            print(f"Tijdelijke directory behouden: {temp_dir_obj.name}")


if __name__ == "__main__":
    main()

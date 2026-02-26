#!/usr/bin/env python3
"""
Script om een compacte linux-firmware RPM te maken met alleen de benodigde drivers.
Neeeded Linux Packages (Alma/RHEL/CentOS): dnf install python3-pyyaml rpm-build rpmdevtools
20140218 - Randy - github.com/Uber1337NL
"""

import sys
import yaml
import subprocess
import tempfile
from pathlib import Path
import re

def download_latest_firmware_rpm(download_dir):
    """Download de laatste linux-firmware RPM van de repo."""
    print("Zoeken naar laatste linux-firmware RPM...")
    
    try:
        # Alternatief: gebruik dnf/yum om te downloaden
        subprocess.run(
            ["dnf", "download", "--downloadonly", "--downloaddir", download_dir, "linux-firmware"],
            capture_output=True, text=True, check=True
        )
        
        # Vind het gedownloade RPM bestand
        rpm_files = list(Path(download_dir).glob("linux-firmware-*.rpm"))
        if rpm_files:
            print(f"Gedownload: {rpm_files[0]}")
            return rpm_files[0]
        else:
            raise FileNotFoundError("Geen RPM bestand gevonden")
            
    except subprocess.CalledProcessError:
        print("Fout bij downloaden met dnf. Probeer handmatig te downloaden.")
        sys.exit(1)

def read_drivers_yaml(yaml_file):
    """Lees de drivers.yaml file met te behouden modules."""
    print(f"Lezen van {yaml_file}...")
    
    try:
        with open(yaml_file, 'r') as f:
            config = yaml.safe_load(f)
        
        drivers = config.get('drivers', [])
        print(f"Gevonden {len(drivers)} drivers om te behouden")
        return drivers
        
    except FileNotFoundError:
        print(f"Fout: {yaml_file} niet gevonden!")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Fout bij parsen YAML: {e}")
        sys.exit(1)

def extract_rpm(rpm_file, extract_dir):
    """Extraheer de RPM naar een tijdelijke directory."""
    print(f"Extraheren van RPM naar {extract_dir}...")
    
    try:
        # Gebruik rpm2cpio en cpio om te extraheren
        with open(rpm_file, 'rb') as f:
            rpm2cpio = subprocess.Popen(
                ["rpm2cpio", str(rpm_file)],
                stdout=subprocess.PIPE
            )
            subprocess.run(
                ["cpio", "-idmv"],
                stdin=rpm2cpio.stdout,
                cwd=extract_dir,
                capture_output=True
            )
            rpm2cpio.wait()
        
        print("Extractie voltooid")
        return True
        
    except Exception as e:
        print(f"Fout bij extraheren: {e}")
        return False

def filter_firmware_files(extract_dir, drivers_to_keep):
    """Verwijder alle firmware bestanden behalve de opgegeven drivers."""
    print("Filteren van firmware bestanden...")
    
    firmware_dir = Path(extract_dir) / "lib" / "firmware"
    if not firmware_dir.exists():
        print(f"Firmware directory niet gevonden: {firmware_dir}")
        return
    
    kept_files = []
    removed_count = 0
    
    # Converteer driver namen naar patronen
    patterns = []
    for driver in drivers_to_keep:
        # Ondersteun wildcards
        pattern = driver.replace('*', '.*').replace('?', '.')
        patterns.append(re.compile(pattern))
    
    # Loop door alle bestanden in firmware directory
    for item in firmware_dir.rglob('*'):
        if item.is_file():
            relative_path = item.relative_to(firmware_dir)
            keep = False
            
            # Check of bestand matcht met een van de patronen
            for pattern in patterns:
                if pattern.search(str(relative_path)):
                    keep = True
                    break
            
            if keep:
                kept_files.append(relative_path)
            else:
                item.unlink()
                removed_count += 1
    
    print(f"Behouden: {len(kept_files)} bestanden")
    print(f"Verwijderd: {removed_count} bestanden")
    
    # Verwijder lege directories
    for item in sorted(firmware_dir.rglob('*'), reverse=True):
        if item.is_dir() and not any(item.iterdir()):
            item.rmdir()

def create_rpm(extract_dir, output_rpm, version="1.0"):
    """Maak een nieuwe RPM van de gefilterde bestanden."""
    print("Maken van nieuwe RPM...")
    
    spec_content = f"""
Name:           linux-firmware-minimal
Version:        {version}
Release:        1%{{?dist}}
Summary:        Minimale Linux firmware met alleen benodigde drivers
License:        Redistributable, no modification permitted
URL:            https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git

%description
Minimale versie van linux-firmware met alleen de benodigde drivers.

%prep

%build

%install
cp -a {extract_dir}/* %{{buildroot}}/

%files
/lib/firmware/*

%changelog
* {subprocess.check_output(['date', '+%a %b %d %Y']).decode().strip()} Builder <builder@localhost> - {version}-1
- Minimale firmware build
"""
    
    # Schrijf spec file
    spec_file = Path(extract_dir).parent / "linux-firmware-minimal.spec"
    with open(spec_file, 'w') as f:
        f.write(spec_content)
    
    try:
        # Build RPM met rpmbuild
        subprocess.run(
            ["rpmbuild", "-bb", "--buildroot", extract_dir, str(spec_file)],
            check=True
        )
        print(f"RPM succesvol gemaakt: {output_rpm}")
        
    except subprocess.CalledProcessError as e:
        print(f"Fout bij maken RPM: {e}")
        print("Alternatief: gebruik fpm (gem install fpm)")
        
        # Fallback naar fpm
        try:
            subprocess.run([
                "fpm", "-s", "dir", "-t", "rpm",
                "-n", "linux-firmware-minimal",
                "-v", version,
                "--prefix", "/",
                "-C", extract_dir,
                "-p", output_rpm,
                "lib/firmware"
            ], check=True)
            print(f"RPM gemaakt met fpm: {output_rpm}")
        except Exception:
            print("Installeer fpm: gem install fpm")
            sys.exit(1)

def main():
    """Hoofdfunctie."""
    print("=== Linux Firmware RPM Minimizer ===\n")
    
    # Configuratie
    yaml_file = "drivers.yaml"
    output_rpm = "linux-firmware-minimal.rpm"
    
    # Check of drivers.yaml bestaat
    if not Path(yaml_file).exists():
        print(f"Maak eerst een {yaml_file} bestand met deze structuur:")
        print("""
drivers:
  - iwlwifi-*           # Intel WiFi drivers
  - rtl_nic/*           # Realtek network drivers
  - i915/*              # Intel graphics
  - amdgpu/*            # AMD graphics
  - nvidia/*            # NVIDIA graphics
  - rtw88/*             # Realtek WiFi
""")
        sys.exit(1)
    
    # Lees configuratie
    drivers_to_keep = read_drivers_yaml(yaml_file)
    
    # Maak tijdelijke directories
    with tempfile.TemporaryDirectory() as temp_dir:
        download_dir = Path(temp_dir) / "download"
        extract_dir = Path(temp_dir) / "extract"
        download_dir.mkdir()
        extract_dir.mkdir()
        
        # Download RPM
        rpm_file = download_latest_firmware_rpm(download_dir)
        
        # Extraheer RPM
        if not extract_rpm(rpm_file, extract_dir):
            sys.exit(1)
        
        # Filter bestanden
        filter_firmware_files(extract_dir, drivers_to_keep)
        
        # Maak nieuwe RPM
        create_rpm(extract_dir, output_rpm)
    
    print(f"\n✓ Klaar! Compacte RPM: {output_rpm}")
    
    # Toon grootte vergelijking
    if Path(output_rpm).exists():
        original_size = Path(rpm_file).stat().st_size / (1024*1024)
        new_size = Path(output_rpm).stat().st_size / (1024*1024)
        print(f"Origineel: {original_size:.1f} MB")
        print(f"Nieuw: {new_size:.1f} MB")
        print(f"Besparing: {original_size - new_size:.1f} MB ({(1-new_size/original_size)*100:.1f}%)")

if __name__ == "__main__":
    main()

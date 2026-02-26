Why download 600+ Mb every other month with firmware and kernel drivers if you only need the content of a Floppy disk with a handfull drivers. Or even a single one. In particular interesting for remote systems without broadband connection like LTE. What this sctipt does:
- Download the latest linux-firmware.noarch.rpp
- Unpack it
- Lookup the json file and keel the drivers you want
- Re-pack it in an usualy sinle digit Mb ROP
- Put it in your custom repo and distrinute it.

** Howto: 

In your custom repo, create an empty RPM. The sole purpose of this RPM is to put dependacies on it. This RPM needs to be installed on all systems one time only. 

Afterwards, update the initisal rpm (COMPANY-custom.rpm). Update the version and add dependacies. 

Exclude linux-firmware in your dnf.conf (exclude=linux-firmware-20*).

Add linux-firmware-custom.noarch to your repository.

Your custom file will be downloaded ad kernel dependacy instead. But.. keep in mind this package is unsigned. 

Or disable gpgchecks (Would not advise this) Or sign it yourself. Keep in mind your public PGP key needs to be known on the systems. See the first steps when installing your COMPANY-custom package initial. 

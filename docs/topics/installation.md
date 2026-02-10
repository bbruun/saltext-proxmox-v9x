# Installation

Generally, extensions need to be installed into the same Python environment Salt uses.

:::{tab} State
```yaml
Install Salt Proxmox-v9x extension:
  pip.installed:
    - name: saltext-proxmox-v9x
```
:::

:::{tab} Onedir installation
```bash
salt-pip install saltext-proxmox-v9x
```
:::

:::{tab} Regular installation
```bash
pip install saltext-proxmox-v9x
```
:::

:::{hint}
Saltexts are not distributed automatically via the fileserver like custom modules, they need to be installed
on each node you want them to be available on.
:::

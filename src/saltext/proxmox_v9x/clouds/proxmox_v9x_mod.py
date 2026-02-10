"""
Salt cloud module
"""

import logging

log = logging.getLogger(__name__)

__virtualname__ = "proxmox_v9x"


def __virtual__():
    # To force a module not to load return something like:
    #   return (False, "The proxmox-v9x cloud module is not implemented yet")
    return __virtualname__

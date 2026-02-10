import pytest

import saltext.proxmox_v9x.clouds.proxmox_v9x_mod as proxmox_v9x_cloud


@pytest.fixture
def configure_loader_modules():
    module_globals = {
        "__salt__": {"this_does_not_exist.please_replace_it": lambda: True},
    }
    return {
        proxmox_v9x_cloud: module_globals,
    }


def test_replace_this_this_with_something_meaningful():
    assert "this_does_not_exist.please_replace_it" in proxmox_v9x_cloud.__salt__
    assert proxmox_v9x_cloud.__salt__["this_does_not_exist.please_replace_it"]() is True

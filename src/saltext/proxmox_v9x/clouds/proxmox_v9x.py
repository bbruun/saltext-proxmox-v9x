"""
Salt cloud module
"""

import logging
import sys
import time
from ipaddress import ip_interface
from pprint import pprint

from salt import config
from salt.exceptions import SaltCloudExecutionTimeout
from salt.exceptions import SaltCloudNotFound
from salt.exceptions import SaltCloudSystemExit

# from salt.utils.minions import HAS_RANGE  # pylint disable=unused-import
try:
    import requests  # pylint: disable=import-error

    HAS_REQUESTS = True
except:  # pylint: disable=bare-except
    HAS_REQUESTS = False
# Disable InsecureRequestWarning generated on python > 2.6
try:
    from requests.packages.urllib3 import disable_warnings  # pylint: disable=no-name-in-module

    disable_warnings()
except ImportError:
    pass

log = logging.getLogger(__name__)

__virtualname__ = "proxmox_v9x"


def __virtual__():
    if get_configured_provider() is False:
        return False
    if get_dependencies() is False:
        return False

    return __virtualname__


def _get_active_provider_name():
    try:
        return __active_provider_name__.value()
    except AttributeError:
        return __active_provider_name__


def get_configured_provider():
    """
    Return the first configured instance.
    """
    return config.is_provider_configured(
        __opts__,
        _get_active_provider_name() or __virtualname__,
        ("user", "tokenid", "token", "url"),
    )


def get_cloud_config():
    """
    Return the cloud configuration.
    """
    return config.is_provider_configured(
        __opts__,
        _get_active_provider_name() or __virtualname__,
        (
            "user",
            "tokenid",
            "token",
            "url",
        ),
    )


def get_dependencies():
    """
    Return the dependencies for this cloud provider.
    """
    deps = {"requests": HAS_REQUESTS}

    return config.check_driver_dependencies(__virtualname__, deps)


def clone(kwargs=None, call=None):  # pylint: disable=unused-argument
    """
    Clone a VM

    kwargs
        Parametres to be passed as dict

    For required and optional parameters please check the Proxmox API documentation:
           * ``https://<PROXMOX_URL>/pve-docs/api-viewer/index.html#/nodes/{node}/qemu/{vmid}/clone``
           * ``https://<PROXMOX_URL>/pve-docs/api-viewer/index.html#/nodes/{node}/lxc/{vmid}/clone``


    **Required**
        || Name || Type || Default || Format || Description ||
        | newid | integer |  | <integer> (100 - 999999999) | VMID for the clone. |
        | node  | string  |  | <string> | The cluster node name. |
        | vmid  | integer |  | <integer> (100 - 999999999) | The (unique) ID of the VM. |
    **Optional**
        || Name       || Type  || Default || Format || Description ||
        | description | string | | <string>     | Description for the new VM. |
        | full        | boolean| | <boolean>    | Create a full copy of all disks. This is always done when you clone a normal VM. For VM templates, we try to create a linked clone by default. |
        | name        | string | | <string>     | Set a name for the new VM. |
        | pool        | string | | <string>     | Add the new VM to the specified pool. |
        | snapname    | string | | <string>     | The name of the snapshot. |
        | storage     | string | | <storage ID> | Target storage for full clone. |
        | target      | string | | <string>     |   Target node. Only allowed if the original VM is on shared storage. |
        | format      | enum   | | <raw|qcow2|vmdk> | Target format for file storage. Only valid for full clone. |
        | bwlimit     | integer| <clone limit from datacenter or storage config> | <integer> (0 - N) | Override I/O bandwidth limit (in KiB/s). |

    Eg.:
        {
            "newid": 1999,        # vmid for the new VM
            "node": "pm1",        # Proxmox node to clone to
            "vmid": 100,          # template to clone from
            "name": "new-server", # Name of new server
            "description": "A clone of vmid 100",
        }

    CLI Example:

    .. code-block:: bash

        raise SaltCloudSystemExit(
            "The clone function must be called with -f or --function"
        )
    """
    if not isinstance(kwargs, dict):
        kwargs = {}

    # vmid to clone from (int)
    vmid = kwargs.get("vmid")

    # Linter issue
    if call is None:
        call = None

    # Get the VM Name from Proxmox by vmid (int)
    vm = _get_vm_by_id(vmid)

    _query("POST", f"nodes/{vm['node']}/{vm['type']}/{vmid}/clone", kwargs)

    raise SaltCloudExecutionTimeout("Timeout to wait for VM cloning reached")


def reconfigure(name=None, kwargs=None):
    """
    Reconfigure a Proxmox VM

     name
        The name of VM to be be reconfigured.

    kwargs
        Addtional parameters to be passed as dict.

    For additional parameters please check the Proxmox API documentation:
        * ``https://<PROXMOX_URL>/pve-docs/api-viewer/index.html#/nodes/{node}/lxc/{vmid}/config``
        * ``https://<PROXMOX_URL>/pve-docs/api-viewer/index.html#/nodes/{node}/qemu/{vmid}/config``

    CLI Example:

    .. code-block:: bash

        raise SaltCloudSystemExit(
            "The reconfigure action must be called with -a or --action."
        )
    """

    vm = _get_vm_by_name(name)

    _query("PUT", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/config", kwargs)

    return {
        "success": True,
        "action": "reconfigure",
    }


def destroy(name=None, kwargs=None, call=None):
    """
    Destroy a Proxmox VM by name

    name
        The name of VM to be be destroyed.

    CLI Example:

    .. code-block:: bash

        salt-cloud -d vm_name
    """
    if call == "function":
        raise SaltCloudSystemExit(
            "The destroy action must be called with -d, --destroy, -a or --action."
        )

    stop(name, kwargs, call)

    __utils__["cloud.fire_event"](  # pylint: disable=undefined-variable
        "event",
        "destroying instance",
        f"salt/cloud/{name}/destroying",
        args={"name": name},
        sock_dir=__opts__["sock_dir"],
        transport=__opts__["transport"],  # pylint: disable=undefined-variable
    )

    vm = _get_vm_by_name(name)

    _wait_for_vm_status(name, "stopped", timeout=20, interval=2)

    _query("DELETE", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}", kwargs)

    __utils__["cloud.fire_event"](  # pylint: disable=undefined-variable
        "event",
        "destroyed instance",
        f"salt/cloud/{name}/destroyed",
        args={"name": name},
        sock_dir=__opts__["sock_dir"],  # pylint: disable=undefined-variable
        transport=__opts__["transport"],  # pylint: disable=undefined-variable
    )


def avail_locations(call=None):
    """
    Return available Proxmox datacenter locations

    CLI Example:

    .. code-block:: bash

        salt-cloud --list-locations my-proxmox-config
    """
    if call == "action":
        raise SaltCloudSystemExit(
            "The avail_locations function must be called with "
            "-f or --function, or with the --list-locations option"
        )

    locations = _query("GET", "nodes")

    ret = {}
    for location in locations:
        name = location["node"]
        if location.get("status") == "online":
            ret[name] = location
        else:
            log.warning("Ignoring Proxmox node '%s' because it is not online.", name)

    return ret


def avail_images(kwargs=None, call=None):
    """
    Return available Proxmox images

    storage
        Name of the storage location that should be searched.

    kwargs
        Addtional parameters to be passed as dict.

    CLI Example:

    .. code-block:: bash

        salt-cloud --list-images my-proxmox-config
        salt-cloud -f avail_images my-proxmox-config storage="storage1"
    """
    if call == "action":
        raise SaltCloudSystemExit(
            "The avail_images function must be called with "
            "-f or --function, or with the --list-images option"
        )

    if not isinstance(kwargs, dict):
        kwargs = {}

    storage = kwargs.get("storage", "local")

    ret = {}
    for location in avail_locations():
        print("location: ", location)
        ret[location] = {}
        for item in _query("GET", f"nodes/{location}/storage/{storage}/content"):
            ret[location][item["volid"]] = item
            # TODO: filter to actual images. what is an imagetype? images, vztmpl, iso
    print("ret[...]:", ret)
    return ret


def list_nodes(call=None):
    """
    Return a list of the VMs that are managed by the provider

    CLI Example:

    .. code-block:: bash

        raise SaltCloudSystemExit(
            "The list_nodes function must be called with -f or --function."
        )
    """
    # Linter issue
    if call is None:
        call = None

    vms = _query("GET", "cluster/resources?type=vm", None)

    ret = {}
    for vm in vms:
        if not "name" in vm or vm["name"] is not None or vm["name"] == "":
            print("VM name", f"{vm}", "not found")
            continue
        name = vm["name"]

        ret[name] = {}
        ret[name]["id"] = str(vm["vmid"])
        ret[name]["image"] = ""  # proxmox does not carry that information
        ret[name]["size"] = ""  # proxmox does not have VM sizes like AWS (e.g: t2-small)
        ret[name]["state"] = str(vm["status"])

        config = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/config")
        private_ips, public_ips = _parse_ips(config, vm["type"])

        ret[name]["private_ips"] = private_ips
        ret[name]["public_ips"] = public_ips

    return ret


def list_nodes_full(call=None):
    """
    Return a list of the VMs that are managed by the provider, with full configuration details

    CLI Example:

    .. code-block:: bash

        salt-cloud -F
        salt-cloud -f list_nodes_full my-proxmox-config
    """
    if call == "action":
        raise SaltCloudSystemExit(
            "The list_nodes_full function must be called with -f or --function."
        )

    # vms = _query("GET", "cluster/resources", data={"type": "vm"})
    vms = _query("GET", "cluster/resources?type=vm", None)

    ret = {}
    for vm in vms:
        name = vm["name"]
        config = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/config")

        ret[name] = vm
        ret[name]["config"] = config

    return ret


def list_nodes_select(call=None):
    """
    Return a list of the VMs that are managed by the provider, with select fields
    """
    return __utils__["cloud.list_nodes_select"](  # pylint: disable=undefined-variable
        list_nodes_full(),
        __opts__["query.selection"],
        call,
    )


def show_instance(name=None, call=None):
    """
    Show the details from Proxmox concerning an instance

    name
        The name of the VM for which to display details.

    CLI Example:

    .. code-block:: bash

        salt-cloud -a show_instance vm_name
    """
    if call != "action":
        raise SaltCloudSystemExit("The show_instance action must be called with -a or --action.")

    for k, v in list_nodes_full().items():
        if k == name:
            return v

    raise SaltCloudNotFound(f"The specified VM named '{name}' could not be found.")


def start(name=None, kwargs=None, call=None):
    """
    Start a node.

    name
        The name of the VM. Required.

    kwargs
        Addtional parameters to be passed as dict.

    For additional parameters please check the Proxmox API documentation:
        * ``https://<PROXMOX_URL>/pve-docs/api-viewer/index.html#/nodes/{node}/lxc/{vmid}/status/start``
        * ``https://<PROXMOX_URL>/pve-docs/api-viewer/index.html#/nodes/{node}/qemu/{vmid}/status/start``

    CLI Example:

    .. code-block:: bash

        salt-cloud -a start vm_name
    """

    if call != "action":
        raise SaltCloudSystemExit("The start action must be called with -a or --action.")

    print("start(): ", f"name={name} kwargs={kwargs}")
    _set_vm_status(name, "start", kwargs)

    _wait_for_vm_status(name, "running", timeout=300, interval=1)

    return {
        "success": True,
        "state": "running",
        "action": "start",
    }


def stop(name=None, kwargs=None, call=None):
    """
    Stop a node.

    For additional parameters please check the Proxmox API documentation:
        * ``https://<PROXMOX_URL>/pve-docs/api-viewer/index.html#/nodes/{node}/lxc/{vmid}/status/stop``
        * ``https://<PROXMOX_URL>/pve-docs/api-viewer/index.html#/nodes/{node}/qemu/{vmid}/status/stop``

    name
        The name of the VM. Required.

    kwargs
        Addtional parameters to be passed as dict.

    CLI Example:

    .. code-block:: bash

        salt-cloud -a stop vm_name
    """
    if call != "action":
        raise SaltCloudSystemExit("The stop action must be called with -a or --action.")

    print('_set_vm_status(name, "stop", kwargs)')
    _set_vm_status(name, "stop", kwargs)

    return {
        "success": True,
        "state": "stopped",
        "action": "stop",
    }


def shutdown(name=None, kwargs=None, call=None):
    """
    Shutdown a node.

    name
        The name of the VM. Required.

    kwargs
        Addtional parameters to be passed as dict.

    For additional parameters please check the Proxmox API documentation:
        * ``https://<PROXMOX_URL>/pve-docs/api-viewer/index.html#/nodes/{node}/lxc/{vmid}/status/shutdown``
        * ``https://<PROXMOX_URL>/pve-docs/api-viewer/index.html#/nodes/{node}/qemu/{vmid}/status/shutdown``

    CLI Example:

    .. code-block:: bash

        salt-cloud -a shutdown vm_name
    """
    if call != "action":
        raise SaltCloudSystemExit("The shutdown action must be called with -a or --action.")

    _set_vm_status(name, "shutdown", kwargs)

    _wait_for_vm_status(name, "stopped", timeout=300, interval=1)

    return {
        "success": True,
        "state": "stopped",
        "action": "shutdown",
    }


def _query(method, path, data=None):
    """
    Query the Proxmox API
    """

    base_url = _get_url()
    api_token = _get_api_token()

    url = f"{base_url}/api2/json/{path}"

    headers = {
        "Accept": "application/json",
        "User-Agent": "salt-cloud-proxmox",
        "Authorization": f"PVEAPIToken={api_token}",
    }

    response = None

    if method == "RAWGET":
        # This method is used to check if Proxmox'es VM features are working, but response with 500 until they do
        print("_query RAW GET: ", f"{url} headers={headers} data={data}")
        response = requests.get(
            url=url,
            headers=headers,
            data=data,
            timeout=10,
        )
        if response.status_code != 500:
            return response
        else:
            return response.status_code

    if method == "GET":
        # print("_query GET: ", f"{url} headers={headers} data={data}")
        try:
            response = requests.get(
                url=url,
                headers=headers,
                data=data,
                timeout=10,
            )
        except requests.exceptions.HTTPError as http_error_code:
            print("_query response status: ", pprint(response))
            print("error: ", http_error_code)
        except requests.exceptions.RequestException:
            log.error("Error in query to %s\n%s\n%s\n", url, response, data)
            return None

    else:  # for POST, DELETE etc.
        # print("_query: ", f"method={method} headers={headers} data={data}")
        try:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            response = requests.request(
                method=method, url=url, headers=headers, data=data, timeout=10
            )
        except requests.exceptions.RequestException:
            log.error("Error in query to %s\n%s\n%s\n", url, response, data)
            return None

    response.raise_for_status()
    returned_data = response.json()
    return returned_data.get("data")


def _get_url():
    """
    Returns the configured Proxmox URL
    """
    return config.get_cloud_config_value(
        "url", get_configured_provider(), __opts__, search_global=False
    )


def _get_api_token():
    """
    Returns the API token for the Proxmox API
    """
    username = config.get_cloud_config_value(
        "user", get_configured_provider(), __opts__, search_global=False
    )
    token = config.get_cloud_config_value(
        "token", get_configured_provider(), __opts__, search_global=False
    )
    tokenid = config.get_cloud_config_value(
        "tokenid", get_configured_provider(), __opts__, search_global=False
    )
    # return f"{username}!{token}"
    return f"{username}!{tokenid}={token}"


def _get_vm_by_name(name, interval=1, max=2, message=None):
    """
    Return VM identified by name

    name
        The name of the VM. Required.

    interval
        The time in seconds to wait between each check

    max
        The max number of interval's to run

    message
        A message to display during each wait

    .. note:

        This function will return the first occurrence of a VM matching the given name.
    """
    counter = 0
    max = 60
    while counter < max:
        # vms = _query("GET", "cluster/resources", {"type": "vm"})
        vms = _query("GET", "cluster/resources?type=vm", None)

        for vm in vms:
            if vm["name"] == name:
                return vm
        if message is not None:
            log.info("Waiting for cloning to finish [%d/%d]", counter + 1, max)
        time.sleep(interval)
        counter += 1

    raise SaltCloudNotFound(f"The specified VM with name '{name}' could not be found.")


def _set_vm_status(name, status, kwargs=None):
    """
    Set the VM status

    name
        The name of the VM. Required.

    status
        The target status of the VM. Required.

    kwargs
        Addtional parameters to be passed as dict.
    """
    vm = _get_vm_by_name(name)

    res = _query("POST", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/{status}", kwargs)
    pprint(res)


def _wait_for_ip(name, timeout=300, interval=5):
    """
    Wait for the VM's agent to register an IP address for bootstrapping

    name
        The name of the VM. Required

    timeout
        The timeout in seconds on how long to wait for the task. Default: 300 seconds

    interval
        The interval in seconds at which the API should be queried for updates. Default: 0.2 seconds
    """

    vm = _get_vm_by_name(name)
    start_time = time.time()
    log.info("Waiting for VM to get IP address assigned")
    _wait_for_vm_status(name, "running", timeout=300, interval=5)
    while time.time() < start_time + timeout:
        response = _query(
            "RAWGET",
            f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/agent/network-get-interfaces",
        )
        if response != 500:
            res = _query(
                "GET",
                f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/agent/network-get-interfaces",
            )
            if "result" in res:
                log.info("Found running qemu guest agent on VM and it has an IP address")
            else:
                print(
                    "No IP address found - perhaps qemu guest agent isn't running on VM template?"
                )
            return res
        time.sleep(interval)

    raise SaltCloudExecutionTimeout("Timeout to wait for VM status reached.")


def _wait_for_vm_status(name, status, timeout=300, interval=0.2):
    """
    Wait for the VM to reach a given status

    name
        The name of the VM. Required.

    status
        The expected status of the VM. Required.

    timeout
        The timeout in seconds on how long to wait for the task. Default: 300 seconds

    interval
        The interval in seconds at which the API should be queried for updates. Default: 0.2 seconds
    """
    vm = _get_vm_by_name(name, interval=5, max=12, message="Waiting for VM to be ready")

    start_time = time.time()
    while time.time() < start_time + timeout:
        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")

    start_time = time.time()
    while time.time() < start_time + timeout:
        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")

    start_time = time.time()
    while time.time() < start_time + timeout:
        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")
        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")

    start_time = time.time()
    response = None
    while time.time() < start_time + timeout:
        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")

    start_time = time.time()
    while time.time() < start_time + timeout:
        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")

    start_time = time.time()
    while time.time() < start_time + timeout:
        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")

    start_time = time.time()
    while time.time() < start_time + timeout:
        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")

    start_time = time.time()
    while time.time() < start_time + timeout:
        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")

        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")
    while time.time() < start_time + timeout:
        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")

        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")
    while time.time() < start_time + timeout:
        response = _query("GET", f"nodes/{vm['node']}/{vm['type']}/{vm['vmid']}/status/current")
        print("status for", f"name={vm['vmid']} vmid={vm['vmid']} status={status}")
        if response["status"] == status:
            return True

        time.sleep(interval)

    raise SaltCloudExecutionTimeout("Timeout to wait for VM status reached.")


def _stringlist_to_dictionary(input_string):
    """
    Convert a stringlist (comma separated settings) to a dictionary

    The result of the string "setting1=value1,setting2=value2" will be a python dictionary:

    {'setting1':'value1','setting2':'value2'}
    """
    return dict(item.strip().split("=") for item in input_string.split(",") if item)


def _parse_ips(vm_config, vm_type):
    """
    Parse IPs from a Proxmox VM config
    """
    private_ips = []
    public_ips = []

    ip_configs = []
    if vm_type == "lxc":
        ip_configs = [v for k, v in vm_config.items() if k.startswith("net")]
    else:
        ip_configs = [v for k, v in vm_config.items() if k.startswith("ipconfig")]

    for ip_config in ip_configs:
        try:
            ip_with_netmask = _stringlist_to_dictionary(ip_config).get("ip")
            ip = ip_interface(ip_with_netmask).ip

            if ip.is_private:
                private_ips.append(str(ip))
            else:
                public_ips.append(str(ip))
        except ValueError:
            log.error("Ignoring '%s' because it is not a valid IP", ip_with_netmask)

    return private_ips, public_ips


def _get_vm_by_id(vmid):
    """
    Return VM identified by vmid.

    vmid
        The vmid of the VM. Required.
    """
    # vms = _query("GET", "cluster/resources", {"type": "vm"})
    vms = _query("GET", "cluster/resources?type=vm", None)
    for vm in vms:
        if vm["vmid"] == vmid:
            return vm

    raise SaltCloudNotFound(f"The specified VM with vmid '{vmid}' could not be found.")


def create(vm_):
    """
    Create a new VM
    """
    image = _get_vm_by_name(vm_.get("image"))
    vm = vm_
    vm["create"] = {}
    vm["create"]["node"] = image["node"]
    vm["create"]["vmid"] = image["vmid"]
    vm["create"]["newid"] = _query("GET", "/cluster/nextid", None)
    vm["create"]["full"] = True
    # vm_["name"] = image["name"]
    newname = vm_["name"]
    vm["create"]["name"] = newname

    __utils__["cloud.fire_event"](  # pylint: disable=undefined-variable
        "event",
        "starting create",
        f"salt/cloud/{vm_['name']}/creating",
        args=__utils__["cloud.filter_event"](  # pylint: disable=undefined-variable
            "creating", vm_, ["name", "profile", "provider", "driver"]
        ),
        sock_dir=__opts__["sock_dir"],  # pylint: disable=undefined-variable
        transport=__opts__["transport"],  # pylint: disable=undefined-variable
    )

    clone_options = vm_.get("clone")
    should_clone = bool(clone_options)

    if should_clone:
        clone(call="function", kwargs=clone_options)
    else:
        newvmname = vm_["name"]
        vm_["name"] = vm_["image"]
        # vm_["create"].pop("name")
        vm_["create"]["name"] = newvmname
        vm_["create"].pop("full")
        # TODO: Calculate vmid automatcially
        vmlist = _query("GET", "cluster/resources?type=vm", None)
        tmpvmid = []
        for x in vmlist:
            tmpvmid.append(x["vmid"])
        sorted(tmpvmid)
        vm_["create"]["newid"] = tmpvmid[-1] + 1
        # _query("POST", f"nodes/{vm_['create']['node']}/{type}", vm_["create"])
        res = _query(
            "POST",
            f"nodes/{vm_['create']['node']}/qemu/{vm_['create']['vmid']}/clone",
            vm_["create"],
        )
        if res is None:
            sys.exit()

    start(call="action", name=vm_["create"]["name"])

    if vm_.get("ssh_private_key") is None:
        # SSH_USE_PRIVATE_KEY = False
        # SSH_USE_PRIVATE_KEY = True
        vm_["username"] = vm_.get("ssh_username")
        vm_["hostname"] = vm_.get("ssh_host")
    else:
        # SSH_USE_PRIVATE_KEY = True
        vm_["private_key"] = vm_.get("ssh_key")
        vm_["username"] = vm_.get("ssh_username")
        vm_["hostname"] = vm_.get("ssh_host")

    # Wait for VM to be running (after clone)
    _wait_for_vm_status(vm_["create"]["name"], "running", timeout=60, interval=2)

    # Wait for VM to have IP address - readable from qemu-guest-agent
    res = _wait_for_ip(vm_["create"]["name"], timeout=10, interval=2)

    if not "result" in res:
        log.error(
            "No IP address found on new VM - Is qemu guest agent installed and set to run on VM template?"
        )
        raise SaltCloudNotFound(
            f"The specified VM with vmid '{vm_['create']['name']}' does not have an IP - cannot bootstrap."
        )

    # Return first non localhost IP for bootstrap process to SSH to
    for nic in res["result"]:
        if nic["hardware-address"] != "00:00:00:00:00:00":
            ip = nic["ip-addresses"]
            for i in ip:
                print("i: ", i)
                if "ip-address-type" in i and i["ip-address-type"] == "ipv4":
                    __opts__["ssh_host"] = i["ip-address"]

    # Check/test if SSH is working and wait until it does
    for x in [1, 2, 3, 4, 5]:
        ssh_answers = __utils__["cloud.wait_for_port"](  # pylint: disable=undefined-variable
            host=__opts__["ssh_host"],
            port=22,
            timeout=300,  # pylint: disable=undefined-variable
        )
        if ssh_answers is True:
            break
        time.Sleep(1)

    # Override the default map config setting so new VM's salt minion id is not the templates
    vm_["name"] = vm_["create"]["name"]

    # Bootstrap the new VM
    ret = __utils__["cloud.bootstrap"](vm_, __opts__)  # pylint: disable=undefined-variable

    ret.update(show_instance(call="action", name=vm_["create"]["name"]))

    __utils__["cloud.fire_event"](  # pylint: disable=undefined-variable
        "event",
        "created instance",
        f"salt/cloud/{vm_['name']}/created",
        args=__utils__["cloud.filter_event"](  # pylint: disable=undefined-variable
            "created", vm_, ["name", "profile", "provider", "driver"]
        ),
        sock_dir=__opts__["sock_dir"],
        transport=__opts__["transport"],
    )

    return ret

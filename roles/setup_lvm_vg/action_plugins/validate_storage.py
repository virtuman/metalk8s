'''
Validate the storage configuration with the following items

- All the drives specified in the configuration (if any)
  are existing devices

- If a drive is specified, and it is not part of the desired LVM
  VG already, it means it will be created. As a result we need to
  check if it doesn't contain a partition, otherwise the *pvcreate*
  command will fail

- If a LVM VG already exists, verify that all the drives specified
  match the one currently being owned by the VG plus possibly new ones.
  Since the lvg ansible module can reduce a VG automatically, raise an
  error, asking the operator to manually fix the storage configuration
  before proceeding

  the following situation need to be handled

  1. Initial setup with 2 disks

  .. code:: shell

    metalk8s_lvm_drives_vg_metalk8s: ['/dev/vdb', '/dev/vdc']

  2. Change the disks with removing a previous one

  .. code:: shell

    metalk8s_lvm_drives_vg_metalk8s: ['/dev/vdb', '/dev/vdd']

  3. Exit with the following error

  ::

    that "/dev/vdc" is part of the VG "vg_metalk8s" and would be removed.
    Please, either add back "/dev/vdc" to "metalk8s_lvm_drives_vg_metalk8s"
    or resolve manually the conflict and relaunch the playbooks/deploy.yml
    playbook like this

    .. code::

      ansible-playbook -i {inventory} -t storage playbooks/deploy.yml
'''

# Note: to add mode checks/validations, simply add a top-level function whose
# name starts with `check_`. The function will receive a `task_vars` dictionary
# as defined by Ansible.
# Within a `check_*` function, use `assert` to validate values found in
# `task_vars`, or raise `AssertionError` explicitly. A single check can, of
# course, contain multiple assertions.
# Alternatively, for checks which can result in multiple errors, a check can
# return a list of (or yield) error messages.

from ansible.plugins.action import ActionBase

import inspect
import sys


def is_device_present(device, ansible_devices):
    '''
    Check that the device passed in parameters exists

    The device can be either a raw device or a partition but nothing else.

    Params:
        device (string): The name of the device
            i.e: 'sdb' or 'sdb1'
        ansible_devices (dict): The dictionary of devices gather by the 'setup'
            ansible module

    Returns:
        bool: True if the device is in ansible_device.
            False otherwise
    '''

    # if the device is a raw device, check its presence
    if device in ansible_devices:
        return True

    # otherwise, check if it's a partition in other devices
    for ansible_device, device_attr in ansible_devices.items():
        if device in device_attr['partitions']:
            return True

    return False


def check_devices_presence(hostvars):
    '''
    Check that the devices specified in metalk8S_lvm_drives_<vg name>
    exists on the server

    Params:
        hostvars (dict): The dictionary 'hostvars' from 'setup' ansible module
            for a specific host

    Raises:
        AssertionError: if the device is not present on the host
    '''

    for lvm_vg in \
        hostvars.get(
            'metalk8s_lvm_all_vgs', {}).keys():
        mk8s_vg_drives_var = 'metalk8s_lvm_drives_' + lvm_vg
        for device in hostvars.get(mk8s_vg_drives_var):
            device_name = device.split('/')[-1]
            assert is_device_present(
                device_name, hostvars['ansible_devices']), \
                "The device {} is not present".format(device)


class ActionModule(ActionBase):
    '''
    Check storage configuration against the current setup for MetalK8s
    '''

    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = dict()

        result = super(ActionModule, self).run(tmp, task_vars)
        del tmp  # tmp no longer has any effect

        def collect_checks():
            for (name, obj) in inspect.getmembers(sys.modules[__name__]):
                if name.startswith('check_') and inspect.isfunction(obj):
                    yield (name, obj)

        errors = []
        failed = False

        for (name, check) in collect_checks():
            for host in task_vars['hostvars'].keys():
                try:
                    results = check(task_vars['hostvars'][host])
                    if not results:
                        # Simple `assert`-check, passed and returned `None`
                        results = []

                    for message in results:
                        failed = True
                        errors.append('[{}]: {} [{}]'.format(
                            host, message, name))

                except AssertionError as exc:
                    failed = True
                    errors.append(
                        '[{}]: {} [{}]'.format(
                            host,
                            exc.args[0] if len(exc.args) >= 1
                            else 'Unknown failure',
                            name)
                    )

        result['failed'] = failed
        result['errors'] = errors

        return result

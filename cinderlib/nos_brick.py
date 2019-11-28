# Copyright (c) 2018, Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""Helper code to attach/detach out of OpenStack

OS-Brick is meant to be used within OpenStack, which means that there are some
issues when using it on non OpenStack systems.

Here we take care of:

- Making sure we can work without privsep and using sudo directly
- Replacing an unlink privsep method that would run python code privileged
- Local attachment of RBD volumes using librados

Some of these changes may be later moved to OS-Brick. For now we just copied it
from the nos-brick repository.
"""
from __future__ import absolute_import
import errno
import functools
import os
import traceback

from os_brick import exception
from os_brick.initiator import connector
from os_brick.initiator import connectors
from os_brick.privileged import rootwrap
from oslo_concurrency import processutils as putils
from oslo_log import log as logging
from oslo_privsep import priv_context
from oslo_utils import fileutils
from oslo_utils import strutils
import six

import cinderlib


LOG = logging.getLogger(__name__)


class RBDConnector(connectors.rbd.RBDConnector):
    """"Connector class to attach/detach RBD volumes locally.

    OS-Brick's implementation covers only 2 cases:

    - Local attachment on controller node.
    - Returning a file object on non controller nodes.

    We need a third one, local attachment on non controller node.
    """
    def connect_volume(self, connection_properties):
        # NOTE(e0ne): sanity check if ceph-common is installed.
        self._setup_rbd_class()

        # Extract connection parameters and generate config file
        try:
            user = connection_properties['auth_username']
            pool, volume = connection_properties['name'].split('/')
            cluster_name = connection_properties.get('cluster_name')
            monitor_ips = connection_properties.get('hosts')
            monitor_ports = connection_properties.get('ports')
            keyring = connection_properties.get('keyring')
        except IndexError:
            msg = 'Malformed connection properties'
            raise exception.BrickException(msg)

        conf = self._create_ceph_conf(monitor_ips, monitor_ports,
                                      str(cluster_name), user,
                                      keyring)

        link_name = self.get_rbd_device_name(pool, volume)
        real_path = os.path.realpath(link_name)

        try:
            # Map RBD volume if it's not already mapped
            if not os.path.islink(link_name) or not os.path.exists(real_path):
                cmd = ['rbd', 'map', volume, '--pool', pool, '--conf', conf]
                cmd += self._get_rbd_args(connection_properties)
                stdout, stderr = self._execute(*cmd,
                                               root_helper=self._root_helper,
                                               run_as_root=True)
                real_path = stdout.strip()
                # The host may not have RBD installed, and therefore won't
                # create the symlinks, ensure they exist
                if self.containerized:
                    self._ensure_link(real_path, link_name)
        except Exception as exec_exception:
            try:
                try:
                    self._unmap(real_path, conf, connection_properties)
                finally:
                    fileutils.delete_if_exists(conf)
            except Exception:
                exc = traceback.format_exc()
                LOG.error('Exception occurred while cleaning up after '
                          'connection error\n%s', exc)
            finally:
                raise exception.BrickException('Error connecting volume: %s' %
                                               six.text_type(exec_exception))

        return {'path': real_path,
                'conf': conf,
                'type': 'block'}

    def _ensure_link(self, source, link_name):
        self._ensure_dir(os.path.dirname(link_name))
        if self.im_root:
            # If the link exists, remove it in case it's a leftover
            if os.path.exists(link_name):
                os.remove(link_name)
            try:
                os.symlink(source, link_name)
            except OSError as exc:
                # Don't fail if symlink creation fails because it exists.
                # It means that ceph-common has just created it.
                if exc.errno != errno.EEXIST:
                    raise
        else:
            self._execute('ln', '-s', '-f', source, link_name,
                          run_as_root=True)

    def check_valid_device(self, path, run_as_root=True):
        """Verify an existing RBD handle is connected and valid."""
        if self.im_root:
            try:
                with open(path, 'r') as f:
                    f.read(4096)
            except Exception:
                return False
            return True

        try:
            self._execute('dd', 'if=' + path, 'of=/dev/null', 'bs=4096',
                          'count=1', root_helper=self._root_helper,
                          run_as_root=True)
        except putils.ProcessExecutionError:
            return False
        return True

    def _get_vol_data(self, connection_properties):
        self._setup_rbd_class()
        pool, volume = connection_properties['name'].split('/')
        link_name = self.get_rbd_device_name(pool, volume)
        real_dev_path = os.path.realpath(link_name)
        return link_name, real_dev_path

    def _unmap(self, real_dev_path, conf_file, connection_properties):
        if os.path.exists(real_dev_path):
            cmd = ['rbd', 'unmap', real_dev_path, '--conf', conf_file]
            cmd += self._get_rbd_args(connection_properties)
            self._execute(*cmd, root_helper=self._root_helper,
                          run_as_root=True)

    def disconnect_volume(self, connection_properties, device_info,
                          force=False, ignore_errors=False):
        conf_file = device_info['conf']
        link_name, real_dev_path = self._get_vol_data(connection_properties)

        self._unmap(real_dev_path, conf_file, connection_properties)
        if self.containerized:
            unlink_root(link_name)
        fileutils.delete_if_exists(conf_file)

    def _ensure_dir(self, path):
        if self.im_root:
            try:
                os.makedirs(path, 0o755)
            except OSError as exc:
                # Don't fail if directory already exists, as our job is done.
                if exc.errno != errno.EEXIST:
                    raise
        else:
            self._execute('mkdir', '-p', '-m0755', path, run_as_root=True)

    def _setup_class(self):
        try:
            self._execute('which', 'rbd')
        except putils.ProcessExecutionError:
            msg = 'ceph-common package not installed'
            raise exception.BrickException(msg)

        RBDConnector.im_root = os.getuid() == 0
        # Check if we are running containerized
        RBDConnector.containerized = os.stat('/proc').st_dev > 4

        # Don't check again to speed things on following connections
        RBDConnector._setup_rbd_class = lambda *args: None

    def extend_volume(self, connection_properties):
        """Refresh local volume view and return current size in bytes."""
        # Nothing to do, RBD attached volumes are automatically refreshed, but
        # we need to return the new size for compatibility
        link_name, real_dev_path = self._get_vol_data(connection_properties)

        device_name = os.path.basename(real_dev_path)  # ie: rbd0
        device_number = device_name[3:]  # ie: 0
        # Get size from /sys/devices/rbd/0/size instead of
        # /sys/class/block/rbd0/size because the latter isn't updated
        with open('/sys/devices/rbd/' + device_number + '/size') as f:
            size_bytes = f.read().strip()
        return int(size_bytes)

    _setup_rbd_class = _setup_class


ROOT_HELPER = 'sudo'


def unlink_root(*links, **kwargs):
    no_errors = kwargs.get('no_errors', False)
    raise_at_end = kwargs.get('raise_at_end', False)
    exc = exception.ExceptionChainer()
    catch_exception = no_errors or raise_at_end

    error_msg = 'Some unlinks failed for %s'
    if os.getuid() == 0:
        for link in links:
            with exc.context(catch_exception, error_msg, links):
                try:
                    os.unlink(link)
                except OSError as exc:
                    # Ignore file doesn't exist errors
                    if exc.errno != errno.ENOENT:
                        raise
    else:
        with exc.context(catch_exception, error_msg, links):
            # Ignore file doesn't exist errors
            putils.execute('rm', *links, run_as_root=True,
                           check_exit_code=(0, errno.ENOENT),
                           root_helper=ROOT_HELPER)

    if not no_errors and raise_at_end and exc:
        raise exc


def _execute(*cmd, **kwargs):
    try:
        return rootwrap.custom_execute(*cmd, **kwargs)
    except OSError as e:
        sanitized_cmd = strutils.mask_password(' '.join(cmd))
        raise putils.ProcessExecutionError(
            cmd=sanitized_cmd, description=six.text_type(e))


def init(root_helper='sudo'):
    global ROOT_HELPER
    ROOT_HELPER = root_helper
    priv_context.init(root_helper=[root_helper])

    brick_get_connector_properties = connector.get_connector_properties
    brick_connector_factory = connector.InitiatorConnector.factory

    def my_get_connector_properties(*args, **kwargs):
        if len(args):
            args = list(args)
            args[0] = ROOT_HELPER
        else:
            kwargs['root_helper'] = ROOT_HELPER
        kwargs['execute'] = _execute
        return brick_get_connector_properties(*args, **kwargs)

    def my_connector_factory(protocol, *args, **kwargs):
        if len(args):
            # args is a tuple and we cannot do assignments
            args = list(args)
            args[0] = ROOT_HELPER
        else:
            kwargs['root_helper'] = ROOT_HELPER
        kwargs['execute'] = _execute

        # OS-Brick's implementation for RBD is not good enough for us
        if protocol == 'rbd':
            factory = RBDConnector
        else:
            factory = functools.partial(brick_connector_factory, protocol)

        return factory(*args, **kwargs)

    # Replace OS-Brick method and the reference we have to it
    connector.get_connector_properties = my_get_connector_properties
    cinderlib.get_connector_properties = my_get_connector_properties
    connector.InitiatorConnector.factory = staticmethod(my_connector_factory)
    if hasattr(rootwrap, 'unlink_root'):
        rootwrap.unlink_root = unlink_root

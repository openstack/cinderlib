# Copyright (c) 2019, Red Hat, Inc.
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

import errno
from unittest import mock

import ddt
from os_brick import exception
from oslo_concurrency import processutils as putils

from cinderlib import nos_brick
from cinderlib.tests.unit import base


@ddt.ddt
class TestRBDConnector(base.BaseTest):
    def setUp(self):
        self.connector = nos_brick.RBDConnector('sudo')
        self.connector.im_root = False
        self.connector.containerized = False
        self.connector._setup_rbd_class = lambda *args: None

    @mock.patch.object(nos_brick, 'open')
    @mock.patch('os.stat')
    def test__in_container_stat(self, mock_stat, mock_open):
        mock_stat.return_value.st_dev = 4
        res = self.connector._in_container()
        self.assertFalse(res)
        mock_stat.assert_called_once_with('/proc')
        mock_open.assert_not_called()

    @mock.patch.object(nos_brick, 'open')
    @mock.patch('os.stat')
    def test__in_container_mounts_no_container(self, mock_stat, mock_open):
        mock_stat.return_value.st_dev = 5
        mock_read = mock_open.return_value.__enter__.return_value.readlines
        mock_read.return_value = [
            'sysfs /sys sysfs rw,seclabel,nosuid,nodev,noexec,relatime 0 0',
            'proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0',
            '/dev/mapper/fedora_think2-root / ext4 rw,seclabel,relatime 0 0',
            'selinuxfs /sys/fs/selinux selinuxfs rw,relatime 0 0',
        ]

        res = self.connector._in_container()
        self.assertFalse(res)
        mock_stat.assert_called_once_with('/proc')
        mock_open.assert_called_once_with('/proc/1/mounts', 'r')
        mock_read.assert_called_once_with()

    @mock.patch.object(nos_brick.LOG, 'warning')
    @mock.patch.object(nos_brick, 'open')
    @mock.patch('os.stat')
    def test__in_container_mounts_in_container(self, mock_stat, mock_open,
                                               mock_warning):
        mock_stat.return_value.st_dev = 5
        mock_read = mock_open.return_value.__enter__.return_value.readlines
        mock_read.return_value = [
            'sysfs /sys sysfs rw,seclabel,nosuid,nodev,noexec,relatime 0 0',
            'proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0',
            'overlay / overlay rw,lowerdir=/var/lib/containers/...',
            'selinuxfs /sys/fs/selinux selinuxfs rw,relatime 0 0',
        ]

        res = self.connector._in_container()
        self.assertTrue(res)
        mock_stat.assert_called_once_with('/proc')
        mock_open.assert_called_once_with('/proc/1/mounts', 'r')
        mock_read.assert_called_once_with()
        mock_warning.assert_not_called()

    @mock.patch.object(nos_brick.RBDConnector, '_get_rbd_args')
    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch('os.path.exists', return_value=True)
    def test__unmap_exists(self, exists_mock, exec_mock, args_mock):
        args_mock.return_value = [mock.sentinel.args]
        self.connector._unmap(mock.sentinel.path, mock.sentinel.conf,
                              mock.sentinel.conn_props)
        exists_mock.assert_called_once_with(mock.sentinel.path)
        exec_mock.assert_called_once_with(
            'rbd', 'unmap', mock.sentinel.path, '--conf', mock.sentinel.conf,
            mock.sentinel.args, root_helper='sudo', run_as_root=True)

    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch('os.path.exists', return_value=False)
    def test__unmap_doesnt_exist(self, exists_mock, exec_mock):
        self.connector._unmap(mock.sentinel.path, mock.sentinel.conf,
                              mock.sentinel.conn_props)
        exists_mock.assert_called_once_with(mock.sentinel.path)
        exec_mock.assert_not_called()

    @ddt.data(True, False)
    @mock.patch('oslo_utils.fileutils.delete_if_exists')
    @mock.patch('cinderlib.nos_brick.unlink_root')
    @mock.patch('os.path.realpath')
    @mock.patch.object(nos_brick.RBDConnector, 'get_rbd_device_name')
    @mock.patch.object(nos_brick.RBDConnector, '_unmap')
    def test_disconnect_volume(self, is_containerized, unmap_mock,
                               dev_name_mock, path_mock, unlink_mock,
                               delete_mock):
        self.connector.containerized = is_containerized
        conn_props = {'name': 'pool/volume'}
        dev_info = {'conf': mock.sentinel.conf_file}
        self.connector.disconnect_volume(conn_props, dev_info)
        dev_name_mock.assert_called_once_with('pool', 'volume')
        path_mock.assert_called_once_with(dev_name_mock.return_value)
        unmap_mock.assert_called_once_with(path_mock.return_value,
                                           mock.sentinel.conf_file,
                                           conn_props)
        if is_containerized:
            unlink_mock.assert_called_once_with(dev_name_mock.return_value)
        else:
            unlink_mock.assert_not_called()
        delete_mock.assert_called_once_with(mock.sentinel.conf_file)

    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch('os.path.islink')
    @mock.patch('os.path.exists')
    @mock.patch('os.path.realpath')
    @mock.patch.object(nos_brick.RBDConnector, 'get_rbd_device_name')
    @mock.patch.object(nos_brick.RBDConnector, '_create_ceph_conf')
    def test_connect_volume_exists(self, conf_mock, dev_name_mock, path_mock,
                                   exists_mock, islink_mock, exec_mock):
        conn_props = {'auth_username': mock.sentinel.username,
                      'name': 'pool/volume',
                      'cluster_name': mock.sentinel.cluster_name,
                      'hosts': mock.sentinel.hosts,
                      'ports': mock.sentinel.ports,
                      'keyring': mock.sentinel.keyring}
        result = self.connector.connect_volume(conn_props)
        conf_mock.assert_called_once_with(mock.sentinel.hosts,
                                          mock.sentinel.ports,
                                          'sentinel.cluster_name',
                                          mock.sentinel.username,
                                          mock.sentinel.keyring)
        dev_name_mock.assert_called_once_with('pool', 'volume')
        path_mock.assert_called_once_with(dev_name_mock.return_value)
        islink_mock.assert_called_with(dev_name_mock.return_value)
        exists_mock.assert_called_once_with(path_mock.return_value)
        exec_mock.assert_not_called()

        expected = {'path': path_mock.return_value,
                    'conf': conf_mock.return_value,
                    'type': 'block'}
        self.assertEqual(expected, result)

    @ddt.data(True, False)
    @mock.patch.object(nos_brick.RBDConnector, '_ensure_link')
    @mock.patch.object(nos_brick.RBDConnector, '_get_rbd_args')
    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch('os.path.islink')
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('os.path.realpath')
    @mock.patch.object(nos_brick.RBDConnector, 'get_rbd_device_name')
    @mock.patch.object(nos_brick.RBDConnector, '_create_ceph_conf')
    def test_connect_volume(self, is_containerized, conf_mock, dev_name_mock,
                            path_mock, exists_mock, islink_mock, exec_mock,
                            args_mock, link_mock):
        exec_mock.return_value = (' a ', '')
        args_mock.return_value = [mock.sentinel.args]
        self.connector.containerized = is_containerized
        conn_props = {'auth_username': mock.sentinel.username,
                      'name': 'pool/volume',
                      'cluster_name': mock.sentinel.cluster_name,
                      'hosts': mock.sentinel.hosts,
                      'ports': mock.sentinel.ports,
                      'keyring': mock.sentinel.keyring}
        result = self.connector.connect_volume(conn_props)
        conf_mock.assert_called_once_with(mock.sentinel.hosts,
                                          mock.sentinel.ports,
                                          'sentinel.cluster_name',
                                          mock.sentinel.username,
                                          mock.sentinel.keyring)
        dev_name_mock.assert_called_once_with('pool', 'volume')
        path_mock.assert_called_once_with(dev_name_mock.return_value)
        islink_mock.assert_called_with(dev_name_mock.return_value)
        exists_mock.assert_called_once_with(path_mock.return_value)
        exec_mock.assert_called_once_with(
            'rbd', 'map', 'volume', '--pool', 'pool', '--conf',
            conf_mock.return_value, mock.sentinel.args,
            root_helper='sudo', run_as_root=True)
        if is_containerized:
            link_mock.assert_called_once_with('a', dev_name_mock.return_value)
        else:
            link_mock.assert_not_called()
        expected = {'path': 'a',
                    'conf': conf_mock.return_value,
                    'type': 'block'}
        self.assertEqual(expected, result)

    @mock.patch('oslo_utils.fileutils.delete_if_exists')
    @mock.patch.object(nos_brick.RBDConnector, '_unmap')
    @mock.patch.object(nos_brick.RBDConnector, '_ensure_link')
    @mock.patch.object(nos_brick.RBDConnector, '_get_rbd_args')
    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch('os.path.islink')
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('os.path.realpath')
    @mock.patch.object(nos_brick.RBDConnector, 'get_rbd_device_name')
    @mock.patch.object(nos_brick.RBDConnector, '_create_ceph_conf')
    def test_connect_volume_map_fail(self, conf_mock, dev_name_mock, path_mock,
                                     exists_mock, islink_mock, exec_mock,
                                     args_mock, link_mock, unmap_mock,
                                     delete_mock):
        exec_mock.side_effect = Exception
        unmap_mock.side_effect = Exception
        args_mock.return_value = [mock.sentinel.args]
        conn_props = {'auth_username': mock.sentinel.username,
                      'name': 'pool/volume',
                      'cluster_name': mock.sentinel.cluster_name,
                      'hosts': mock.sentinel.hosts,
                      'ports': mock.sentinel.ports,
                      'keyring': mock.sentinel.keyring}
        with self.assertRaises(exception.BrickException):
            self.connector.connect_volume(conn_props)
        link_mock.assert_not_called()
        conf_mock.assert_called_once_with(mock.sentinel.hosts,
                                          mock.sentinel.ports,
                                          'sentinel.cluster_name',
                                          mock.sentinel.username,
                                          mock.sentinel.keyring)
        dev_name_mock.assert_called_once_with('pool', 'volume')
        path_mock.assert_called_once_with(dev_name_mock.return_value)
        islink_mock.assert_called_with(dev_name_mock.return_value)
        exists_mock.assert_called_once_with(path_mock.return_value)
        exec_mock.assert_called_once_with(
            'rbd', 'map', 'volume', '--pool', 'pool', '--conf',
            conf_mock.return_value, mock.sentinel.args, root_helper='sudo',
            run_as_root=True)
        unmap_mock.assert_called_once_with(path_mock.return_value,
                                           conf_mock.return_value,
                                           conn_props)
        delete_mock.assert_called_once_with(conf_mock.return_value)

    @mock.patch('oslo_utils.fileutils.delete_if_exists')
    @mock.patch.object(nos_brick.RBDConnector, '_unmap')
    @mock.patch.object(nos_brick.RBDConnector, '_ensure_link')
    @mock.patch.object(nos_brick.RBDConnector, '_get_rbd_args')
    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch('os.path.islink')
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('os.path.realpath')
    @mock.patch.object(nos_brick.RBDConnector, 'get_rbd_device_name')
    @mock.patch.object(nos_brick.RBDConnector, '_create_ceph_conf')
    def test_connect_volume_link_fail(self, conf_mock, dev_name_mock,
                                      path_mock, exists_mock, islink_mock,
                                      exec_mock, args_mock, link_mock,
                                      unmap_mock, delete_mock):
        exec_mock.return_value = (' a ', '')
        link_mock.side_effect = Exception
        self.connector.containerized = True
        args_mock.return_value = [mock.sentinel.args]
        conn_props = {'auth_username': mock.sentinel.username,
                      'name': 'pool/volume',
                      'cluster_name': mock.sentinel.cluster_name,
                      'hosts': mock.sentinel.hosts,
                      'ports': mock.sentinel.ports,
                      'keyring': mock.sentinel.keyring}
        with self.assertRaises(exception.BrickException):
            self.connector.connect_volume(conn_props)
        link_mock.assert_called_once_with('a', dev_name_mock.return_value)
        conf_mock.assert_called_once_with(mock.sentinel.hosts,
                                          mock.sentinel.ports,
                                          'sentinel.cluster_name',
                                          mock.sentinel.username,
                                          mock.sentinel.keyring)
        dev_name_mock.assert_called_once_with('pool', 'volume')
        path_mock.assert_called_once_with(dev_name_mock.return_value)
        islink_mock.assert_called_with(dev_name_mock.return_value)
        exists_mock.assert_called_once_with(path_mock.return_value)
        exec_mock.assert_called_once_with(
            'rbd', 'map', 'volume', '--pool', 'pool', '--conf',
            conf_mock.return_value, mock.sentinel.args, root_helper='sudo',
            run_as_root=True)
        unmap_mock.assert_called_once_with('a',
                                           conf_mock.return_value,
                                           conn_props)
        delete_mock.assert_called_once_with(conf_mock.return_value)

    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch('os.makedirs')
    def test__ensure_dir(self, mkdir_mock, exec_mock):
        self.connector._ensure_dir(mock.sentinel.path)
        exec_mock.assert_called_once_with(
            'mkdir', '-p', '-m0755', mock.sentinel.path,
            root_helper=self.connector._root_helper, run_as_root=True)
        mkdir_mock.assert_not_called()

    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch('os.makedirs')
    def test__ensure_dir_root(self, mkdir_mock, exec_mock):
        self.connector.im_root = True
        self.connector._ensure_dir(mock.sentinel.path)
        mkdir_mock.assert_called_once_with(mock.sentinel.path, 0o755)
        exec_mock.assert_not_called()

    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch('os.makedirs', side_effect=OSError(errno.EEXIST, ''))
    def test__ensure_dir_root_exists(self, mkdir_mock, exec_mock):
        self.connector.im_root = True
        self.connector._ensure_dir(mock.sentinel.path)
        mkdir_mock.assert_called_once_with(mock.sentinel.path, 0o755)
        exec_mock.assert_not_called()

    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch('os.makedirs', side_effect=OSError(errno.EPERM, ''))
    def test__ensure_dir_root_fails(self, mkdir_mock, exec_mock):
        self.connector.im_root = True
        with self.assertRaises(OSError) as exc:
            self.connector._ensure_dir(mock.sentinel.path)
        self.assertEqual(mkdir_mock.side_effect, exc.exception)
        mkdir_mock.assert_called_once_with(mock.sentinel.path, 0o755)
        exec_mock.assert_not_called()

    @mock.patch('os.path.exists')
    @mock.patch('os.remove')
    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch.object(nos_brick.RBDConnector, '_ensure_dir')
    @mock.patch('os.symlink')
    def test__ensure_link(self, link_mock, dir_mock, exec_mock, remove_mock,
                          exists_mock):
        source = '/dev/rbd0'
        link = '/dev/rbd/rbd/volume-xyz'
        self.connector._ensure_link(source, link)
        dir_mock.assert_called_once_with('/dev/rbd/rbd')
        exec_mock.assert_called_once_with(
            'ln', '-s', '-f', source, link,
            root_helper=self.connector._root_helper, run_as_root=True)
        exists_mock.assert_not_called()
        remove_mock.assert_not_called()
        link_mock.assert_not_called()

    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('os.remove')
    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch.object(nos_brick.RBDConnector, '_ensure_dir')
    @mock.patch('os.symlink')
    def test__ensure_link_root(self, link_mock, dir_mock, exec_mock,
                               remove_mock, exists_mock):
        self.connector.im_root = True
        source = '/dev/rbd0'
        link = '/dev/rbd/rbd/volume-xyz'
        self.connector._ensure_link(source, link)
        dir_mock.assert_called_once_with('/dev/rbd/rbd')
        exec_mock.assert_not_called()
        remove_mock.assert_not_called()
        exists_mock.assert_called_once_with(link)
        link_mock.assert_called_once_with(source, link)

    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('os.remove')
    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch.object(nos_brick.RBDConnector, '_ensure_dir')
    @mock.patch('os.symlink', side_effect=OSError(errno.EEXIST, ''))
    def test__ensure_link_root_appears(self, link_mock, dir_mock, exec_mock,
                                       remove_mock, exists_mock):
        self.connector.im_root = True
        source = '/dev/rbd0'
        link = '/dev/rbd/rbd/volume-xyz'
        self.connector._ensure_link(source, link)
        dir_mock.assert_called_once_with('/dev/rbd/rbd')
        exec_mock.assert_not_called()
        exists_mock.assert_called_once_with(link)
        remove_mock.assert_not_called()
        link_mock.assert_called_once_with(source, link)

    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('os.remove')
    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch.object(nos_brick.RBDConnector, '_ensure_dir')
    @mock.patch('os.symlink', side_effect=OSError(errno.EPERM, ''))
    def test__ensure_link_root_fails(self, link_mock, dir_mock, exec_mock,
                                     remove_mock, exists_mock):
        self.connector.im_root = True
        source = '/dev/rbd0'
        link = '/dev/rbd/rbd/volume-xyz'

        with self.assertRaises(OSError) as exc:
            self.connector._ensure_link(source, link)

        self.assertEqual(link_mock.side_effect, exc.exception)
        dir_mock.assert_called_once_with('/dev/rbd/rbd')
        exec_mock.assert_not_called()
        exists_mock.assert_called_once_with(link)
        remove_mock.assert_not_called()
        link_mock.assert_called_once_with(source, link)

    @mock.patch('os.path.exists')
    @mock.patch('os.remove')
    @mock.patch('os.path.realpath')
    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    @mock.patch.object(nos_brick.RBDConnector, '_ensure_dir')
    @mock.patch('os.symlink', side_effect=[OSError(errno.EEXIST, ''), None])
    def test__ensure_link_root_replace(self, link_mock, dir_mock, exec_mock,
                                       path_mock, remove_mock, exists_mock):
        self.connector.im_root = True
        source = '/dev/rbd0'
        path_mock.return_value = '/dev/rbd1'
        link = '/dev/rbd/rbd/volume-xyz'
        self.connector._ensure_link(source, link)
        dir_mock.assert_called_once_with('/dev/rbd/rbd')
        exec_mock.assert_not_called()
        exists_mock.assert_called_once_with(link)
        remove_mock.assert_called_once_with(link)
        link_mock.assert_called_once_with(source, link)

    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(nos_brick.RBDConnector, '_get_vol_data')
    def test_extend_volume(self, get_data_mock, open_mock):
        get_data_mock.return_value = (
            '/dev/rbd/rbd/volume-56539d26-2b78-49b8-8b96-160a62b0831f',
            '/dev/rbd10')

        cm_open = open_mock.return_value.__enter__.return_value
        cm_open.read.return_value = '5368709120'
        res = self.connector.extend_volume(mock.sentinel.connector_properties)

        self.assertEqual(5 * (1024 ** 3), res)  # 5 GBi
        get_data_mock.assert_called_once_with(
            mock.sentinel.connector_properties)
        open_mock.assert_called_once_with('/sys/devices/rbd/10/size')

    @mock.patch('six.moves.builtins.open')
    def test_check_valid_device_root(self, open_mock):
        self.connector.im_root = True
        res = self.connector.check_valid_device(mock.sentinel.path)
        self.assertTrue(res)
        open_mock.assert_called_once_with(mock.sentinel.path, 'rb')
        read_mock = open_mock.return_value.__enter__.return_value.read
        read_mock.assert_called_once_with(4096)

    @mock.patch('six.moves.builtins.open')
    def test_check_valid_device_root_fail_open(self, open_mock):
        self.connector.im_root = True
        open_mock.side_effect = OSError
        res = self.connector.check_valid_device(mock.sentinel.path)
        self.assertFalse(res)
        open_mock.assert_called_once_with(mock.sentinel.path, 'rb')
        read_mock = open_mock.return_value.__enter__.return_value.read
        read_mock.assert_not_called()

    @mock.patch('six.moves.builtins.open')
    def test_check_valid_device_root_fail_read(self, open_mock):
        self.connector.im_root = True
        read_mock = open_mock.return_value.__enter__.return_value.read
        read_mock.side_effect = IOError
        res = self.connector.check_valid_device(mock.sentinel.path)
        self.assertFalse(res)
        open_mock.assert_called_once_with(mock.sentinel.path, 'rb')
        read_mock.assert_called_once_with(4096)

    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    def test_check_valid_device_non_root(self, exec_mock):
        res = self.connector.check_valid_device('/tmp/path')
        self.assertTrue(res)
        exec_mock.assert_called_once_with(
            'dd', 'if=/tmp/path', 'of=/dev/null', 'bs=4096', 'count=1',
            root_helper=self.connector._root_helper, run_as_root=True)

    @mock.patch.object(nos_brick.RBDConnector, '_execute')
    def test_check_valid_device_non_root_fail(self, exec_mock):
        exec_mock.side_effect = putils.ProcessExecutionError
        res = self.connector.check_valid_device('/tmp/path')
        self.assertFalse(res)
        exec_mock.assert_called_once_with(
            'dd', 'if=/tmp/path', 'of=/dev/null', 'bs=4096', 'count=1',
            root_helper=self.connector._root_helper, run_as_root=True)

    @mock.patch.object(nos_brick.os, 'unlink')
    @mock.patch.object(nos_brick.os, 'getuid', return_value=0)
    def test_unlink_root_being_root(self, mock_getuid, mock_unlink):
        mock_unlink.side_effect = [None, OSError(errno.ENOENT, '')]
        nos_brick.unlink_root(mock.sentinel.file1, mock.sentinel.file2)
        mock_getuid.assert_called_once()
        mock_unlink.assert_has_calls([mock.call(mock.sentinel.file1),
                                      mock.call(mock.sentinel.file2)])

    @mock.patch.object(nos_brick.putils, 'execute')
    @mock.patch.object(nos_brick.os, 'getuid', return_value=1000)
    def test_unlink_root_non_root(self, mock_getuid, mock_exec):
        nos_brick.unlink_root(mock.sentinel.file1, mock.sentinel.file2)
        mock_getuid.assert_called_once()
        mock_exec.assert_called_once_with('rm', '-f', mock.sentinel.file1,
                                          mock.sentinel.file2,
                                          run_as_root=True,
                                          root_helper=nos_brick.ROOT_HELPER)

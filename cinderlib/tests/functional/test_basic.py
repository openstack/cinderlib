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

import os
import random

import ddt

import cinderlib
from cinderlib.tests.functional import base_tests


@ddt.ddt
class BaseFunctTestCase(base_tests.unittest.TestCase):
    @ddt.data([], [1], [2])
    def test_list_supported_drivers(self, args):
        is_v2 = args == [2]
        expected_type = dict if is_v2 else str
        expected_keys = {'version', 'class_name', 'supported', 'ci_wiki_name',
                         'driver_options', 'class_fqn', 'desc'}

        drivers = cinderlib.Backend.list_supported_drivers(*args)
        self.assertNotEqual(0, len(drivers))
        for name, driver_info in drivers.items():
            self.assertEqual(expected_keys, set(driver_info.keys()))

            # Ensure that the RBDDriver has the rbd_keyring_conf option and
            # it's not deprecated
            if name == 'RBDDriver':
                keyring_conf = [conf for conf in driver_info['driver_options']
                                if conf['dest'] == 'rbd_keyring_conf']
                self.assertEqual(1, len(keyring_conf))
                expected_value = False if is_v2 else 'False'
                self.assertEqual(expected_value,
                                 keyring_conf[0]['deprecated_for_removal'])

            for option in driver_info['driver_options']:
                self.assertIsInstance(option['type'], expected_type)
                if is_v2:
                    self.assertIn('type_class', option['type'])
                else:
                    for v in option.values():
                        self.assertIsInstance(v, str)


@base_tests.test_all_backends
class BackendFunctBasic(base_tests.BaseFunctTestCase):

    def test_stats(self):
        stats = self.backend.stats()
        self.assertIn('vendor_name', stats)
        self.assertIn('volume_backend_name', stats)
        pools_info = self._pools_info(stats)
        for pool_info in pools_info:
            self.assertIn('free_capacity_gb', pool_info)
            self.assertIn('total_capacity_gb', pool_info)

    def _volumes_in_pools(self, pools_info):
        if not any('total_volumes' in p for p in pools_info):
            return None
        return sum(p.get('total_volumes', 0) for p in pools_info)

    def test_stats_with_creation(self):
        initial_stats = self.backend.stats(refresh=True)
        initial_pools_info = self._pools_info(initial_stats)
        initial_volumes = self._volumes_in_pools(initial_pools_info)
        initial_size = sum(p.get('allocated_capacity_gb',
                                 p.get('provisioned_capacity_gb', 0))
                           for p in initial_pools_info)

        size = random.randint(1, 5)
        vol = self._create_vol(self.backend, size=size)

        # Check that without refresh we get the same data
        duplicate_stats = self.backend.stats(refresh=False)
        self.assertEqual(initial_stats, duplicate_stats)

        new_stats = self.backend.stats(refresh=True)
        new_pools_info = self._pools_info(new_stats)
        new_volumes = self._volumes_in_pools(new_pools_info)
        new_size = sum(p.get('allocated_capacity_gb',
                             p.get('provisioned_capacity_gb', vol.size))
                       for p in new_pools_info)

        # We could be sharing the pool with other CI jobs or with parallel
        # executions of this same one, so we cannot check that we have 1 more
        # volume and 1 more GB used, so we just check that the values have
        # changed.  This could still fail if another job just deletes 1 volume
        # of the same size, that's why we randomize the size, to reduce the
        # risk of the volumes having the same size.

        # If the backend is reporting the number of volumes, check them
        if initial_volumes is not None:
            self.assertNotEqual(initial_volumes, new_volumes)

        self.assertNotEqual(initial_size, new_size)

    def test_create_volume(self):
        vol = self._create_vol(self.backend)
        vol_size = self._get_vol_size(vol)
        self.assertSize(vol.size, vol_size)
        # We are not testing delete, so leave the deletion to the tearDown

    def test_create_delete_volume(self):
        vol = self._create_vol(self.backend)

        vol.delete()
        self.assertEqual('deleted', vol.status)
        self.assertTrue(vol.deleted)
        self.assertNotIn(vol, self.backend.volumes)

        # Confirm idempotency of the operation by deleting it again
        vol._ovo.status = 'error'
        vol._ovo.deleted = False
        vol.delete()
        self.assertEqual('deleted', vol.status)
        self.assertTrue(vol.deleted)

    def test_create_snapshot(self):
        vol = self._create_vol(self.backend)
        self._create_snap(vol)
        # We are not testing delete, so leave the deletion to the tearDown

    def test_create_delete_snapshot(self):
        vol = self._create_vol(self.backend)
        snap = self._create_snap(vol)

        snap.delete()
        self.assertEqual('deleted', snap.status)
        self.assertTrue(snap.deleted)
        self.assertNotIn(snap, vol.snapshots)

        # Confirm idempotency of the operation by deleting it again
        snap._ovo.status = 'error'
        snap._ovo.deleted = False
        snap.delete()
        self.assertEqual('deleted', snap.status)
        self.assertTrue(snap.deleted)

    def test_attach_volume(self):
        vol = self._create_vol(self.backend)

        attach = vol.attach()
        path = attach.path

        self.assertIs(attach, vol.local_attach)
        self.assertIn(attach, vol.connections)

        self.assertTrue(os.path.exists(path))
        # We are not testing detach, so leave it to the tearDown

    def test_attach_detach_volume(self):
        vol = self._create_vol(self.backend)

        attach = vol.attach()
        self.assertIs(attach, vol.local_attach)
        self.assertIn(attach, vol.connections)

        vol.detach()
        self.assertIsNone(vol.local_attach)
        self.assertNotIn(attach, vol.connections)

    def test_attach_detach_volume_via_attachment(self):
        vol = self._create_vol(self.backend)

        attach = vol.attach()
        self.assertTrue(attach.attached)
        path = attach.path

        self.assertTrue(os.path.exists(path))

        attach.detach()
        self.assertFalse(attach.attached)
        self.assertIsNone(vol.local_attach)

        # We haven't disconnected the volume, just detached it
        self.assertIn(attach, vol.connections)

        attach.disconnect()
        self.assertNotIn(attach, vol.connections)

    def test_disk_io(self):
        vol = self._create_vol(self.backend)
        data = self._write_data(vol)

        read_data = self._read_data(vol, len(data))

        self.assertEqual(data, read_data)

    def test_extend(self):
        vol = self._create_vol(self.backend)
        original_size = vol.size
        result_original_size = self._get_vol_size(vol)
        self.assertSize(original_size, result_original_size)

        new_size = vol.size + 1
        # Retrieve the volume from the persistence storage to ensure lazy
        # loading works. Prevent regression after fixing bug #1852629
        vol_from_db = self.backend.persistence.get_volumes(vol.id)[0]
        vol_from_db.extend(new_size)

        self.assertEqual(new_size, vol.size)
        result_new_size = self._get_vol_size(vol)
        self.assertSize(new_size, result_new_size)

    def test_extend_attached(self):
        vol = self._create_vol(self.backend)
        original_size = vol.size
        # Attach, get size, and leave volume attached
        result_original_size = self._get_vol_size(vol, do_detach=False)
        self.assertSize(original_size, result_original_size)

        new_size = vol.size + 1
        # Extending the volume should also extend the local view of the volume
        reported_size = vol.extend(new_size)

        # The instance size must have been updated
        self.assertEqual(new_size, vol.size)
        self.assertEqual(new_size, vol._ovo.size)

        # Returned size must match the requested one
        self.assertEqual(new_size * (1024 ** 3), reported_size)

        # Get size of attached volume on the host and detach it
        result_new_size = self._get_vol_size(vol)
        self.assertSize(new_size, result_new_size)

    def test_clone(self):
        vol = self._create_vol(self.backend)
        original_size = self._get_vol_size(vol, do_detach=False)
        data = self._write_data(vol)

        new_vol = vol.clone()
        self.assertEqual(vol.size, new_vol.size)
        self.assertEqual(vol.id, new_vol.source_volid)

        cloned_size = self._get_vol_size(new_vol, do_detach=False)
        read_data = self._read_data(new_vol, len(data))
        self.assertEqual(original_size, cloned_size)
        self.assertEqual(data, read_data)

    def test_create_volume_from_snapshot(self):
        # Create a volume and write some data
        vol = self._create_vol(self.backend)
        original_size = self._get_vol_size(vol, do_detach=False)
        data = self._write_data(vol)

        # Take a snapshot
        snap = vol.create_snapshot()
        self.assertEqual(vol.size, snap.volume_size)

        # Change the data in the volume
        reversed_data = data[::-1]
        self._write_data(vol, data=reversed_data)

        # Create a new volume from the snapshot with the original data
        new_vol = snap.create_volume()
        self.assertEqual(vol.size, new_vol.size)

        created_size = self._get_vol_size(new_vol, do_detach=False)
        read_data = self._read_data(new_vol, len(data))
        self.assertEqual(original_size, created_size)
        self.assertEqual(data, read_data)

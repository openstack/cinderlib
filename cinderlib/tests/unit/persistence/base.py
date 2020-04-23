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

from unittest import mock

from oslo_config import cfg

import cinderlib
from cinderlib.persistence import base as persistence_base
from cinderlib.tests.unit.persistence import helper
from cinderlib.tests.unit import utils


class BasePersistenceTest(helper.TestHelper):

    def setUp(self):
        super(BasePersistenceTest, self).setUp()

    def assertListEqualObj(self, expected, actual):
        exp = [self._convert_to_dict(e) for e in expected]
        act = [self._convert_to_dict(a) for a in actual]
        self.assertListEqual(exp, act)

    def assertEqualObj(self, expected, actual):
        exp = self._convert_to_dict(expected)
        act = self._convert_to_dict(actual)
        self.assertDictEqual(exp, act)

    def test_db(self):
        raise NotImplementedError('Test class must implement this method')

    def test_set_volume(self):
        raise NotImplementedError('Test class must implement this method')

    def test_get_volumes_all(self):
        vols = self.create_n_volumes(2)
        res = self.persistence.get_volumes()
        self.assertListEqualObj(vols, self.sorted(res))

    def test_get_volumes_by_id(self):
        vols = self.create_n_volumes(2)
        res = self.persistence.get_volumes(volume_id=vols[1].id)
        # Use res instead of res[0] in case res is empty list
        self.assertListEqualObj([vols[1]], res)

    def test_get_volumes_by_id_not_found(self):
        self.create_n_volumes(2)
        res = self.persistence.get_volumes(volume_id='fake-uuid')
        self.assertListEqualObj([], res)

    def test_get_volumes_by_name_single(self):
        vols = self.create_n_volumes(2)
        res = self.persistence.get_volumes(volume_name=vols[1].name)
        self.assertListEqualObj([vols[1]], res)

    def test_get_volumes_by_name_multiple(self):
        volume_name = 'disk'
        vols = self.create_volumes([{'size': 1, 'name': volume_name},
                                    {'size': 2, 'name': volume_name}])
        res = self.persistence.get_volumes(volume_name=volume_name)
        self.assertListEqualObj(vols, self.sorted(res))

    def test_get_volumes_by_name_not_found(self):
        self.create_n_volumes(2)
        res = self.persistence.get_volumes(volume_name='disk3')
        self.assertListEqualObj([], res)

    def test_get_volumes_by_backend(self):
        vols = self.create_n_volumes(2)
        backend2 = utils.FakeBackend(volume_backend_name='fake2')
        vol = self.create_volumes([{'backend_or_vol': backend2, 'size': 3}])

        res = self.persistence.get_volumes(backend_name=self.backend.id)
        self.assertListEqualObj(vols, self.sorted(res))

        res = self.persistence.get_volumes(backend_name=backend2.id)
        self.assertListEqualObj(vol, res)

    def test_get_volumes_by_backend_not_found(self):
        self.create_n_volumes(2)
        res = self.persistence.get_volumes(backend_name='fake2')
        self.assertListEqualObj([], res)

    def test_get_volumes_by_multiple(self):
        volume_name = 'disk'
        vols = self.create_volumes([{'size': 1, 'name': volume_name},
                                    {'size': 2, 'name': volume_name}])
        res = self.persistence.get_volumes(backend_name=self.backend.id,
                                           volume_name=volume_name,
                                           volume_id=vols[0].id)
        self.assertListEqualObj([vols[0]], res)

    def test_get_volumes_by_multiple_not_found(self):
        vols = self.create_n_volumes(2)
        res = self.persistence.get_volumes(backend_name=self.backend.id,
                                           volume_name=vols[1].name,
                                           volume_id=vols[0].id)
        self.assertListEqualObj([], res)

    def _check_volume_type(self, extra_specs, qos_specs, vol):
        self.assertEqual(vol.id, vol.volume_type.id)
        self.assertEqual(vol.id, vol.volume_type.name)
        self.assertTrue(vol.volume_type.is_public)
        self.assertEqual(extra_specs, vol.volume_type.extra_specs)

        if qos_specs:
            self.assertEqual(vol.id, vol.volume_type.qos_specs_id)
            self.assertEqual(vol.id, vol.volume_type.qos_specs.id)
            self.assertEqual(vol.id, vol.volume_type.qos_specs.name)
            self.assertEqual('back-end', vol.volume_type.qos_specs.consumer)
            self.assertEqual(qos_specs, vol.volume_type.qos_specs.specs)
        else:
            self.assertIsNone(vol.volume_type.qos_specs_id)

    def test_get_volumes_extra_specs(self):
        extra_specs = [{'k1': 'v1', 'k2': 'v2'},
                       {'kk1': 'vv1', 'kk2': 'vv2', 'kk3': 'vv3'}]
        vols = self.create_volumes(
            [{'size': 1, 'extra_specs': extra_specs[0]},
             {'size': 2, 'extra_specs': extra_specs[1]}],
            sort=False)

        # Check the volume type and the extra specs on created volumes
        for i in range(len(vols)):
            self._check_volume_type(extra_specs[i], None, vols[i])

        # Check that we get what we stored
        res = self.persistence.get_volumes(backend_name=self.backend.id)
        vols = self.sorted(vols)
        self.assertListEqualObj(vols, self.sorted(res))
        for i in range(len(vols)):
            self._check_volume_type(vols[i].volume_type.extra_specs, {},
                                    vols[i])

    def test_get_volumes_qos_specs(self):
        qos_specs = [{'q1': 'r1', 'q2': 'r2'},
                     {'qq1': 'rr1', 'qq2': 'rr2', 'qq3': 'rr3'}]
        vols = self.create_volumes(
            [{'size': 1, 'qos_specs': qos_specs[0]},
             {'size': 2, 'qos_specs': qos_specs[1]}],
            sort=False)

        # Check the volume type and the extra specs on created volumes
        for i in range(len(vols)):
            self._check_volume_type({}, qos_specs[i], vols[i])

        # Check that we get what we stored
        res = self.persistence.get_volumes(backend_name=self.backend.id)
        vols = self.sorted(vols)
        res = self.sorted(res)
        self.assertListEqualObj(vols, res)
        for i in range(len(vols)):
            self._check_volume_type({}, vols[i].volume_type.qos_specs.specs,
                                    vols[i])

    def test_get_volumes_extra_and_qos_specs(self):
        qos_specs = [{'q1': 'r1', 'q2': 'r2'},
                     {'qq1': 'rr1', 'qq2': 'rr2', 'qq3': 'rr3'}]
        extra_specs = [{'k1': 'v1', 'k2': 'v2'},
                       {'kk1': 'vv1', 'kk2': 'vv2', 'kk3': 'vv3'}]
        vols = self.create_volumes(
            [{'size': 1, 'qos_specs': qos_specs[0],
              'extra_specs': extra_specs[0]},
             {'size': 2, 'qos_specs': qos_specs[1],
              'extra_specs': extra_specs[1]}],
            sort=False)

        # Check the volume type and the extra specs on created volumes
        for i in range(len(vols)):
            self._check_volume_type(extra_specs[i], qos_specs[i], vols[i])

        # Check that we get what we stored
        res = self.persistence.get_volumes(backend_name=self.backend.id)
        vols = self.sorted(vols)
        self.assertListEqualObj(vols, self.sorted(res))
        for i in range(len(vols)):
            self._check_volume_type(vols[i].volume_type.extra_specs,
                                    vols[i].volume_type.qos_specs.specs,
                                    vols[i])

    def test_delete_volume(self):
        vols = self.create_n_volumes(2)
        self.persistence.delete_volume(vols[0])
        res = self.persistence.get_volumes()
        self.assertListEqualObj([vols[1]], res)

    def test_delete_volume_not_found(self):
        vols = self.create_n_volumes(2)
        fake_vol = cinderlib.Volume(backend_or_vol=self.backend)
        self.persistence.delete_volume(fake_vol)
        res = self.persistence.get_volumes()
        self.assertListEqualObj(vols, self.sorted(res))

    def test_set_snapshot(self):
        raise NotImplementedError('Test class must implement this method')

    def get_snapshots_all(self):
        snaps = self.create_snapshots()
        res = self.persistence.get_snapshots()
        self.assertListEqualObj(snaps, self.sorted(res))

    def test_get_snapshots_by_id(self):
        snaps = self.create_snapshots()
        res = self.persistence.get_snapshots(snapshot_id=snaps[1].id)
        self.assertListEqualObj([snaps[1]], res)

    def test_get_snapshots_by_id_not_found(self):
        self.create_snapshots()
        res = self.persistence.get_snapshots(snapshot_id='fake-uuid')
        self.assertListEqualObj([], res)

    def test_get_snapshots_by_name_single(self):
        snaps = self.create_snapshots()
        res = self.persistence.get_snapshots(snapshot_name=snaps[1].name)
        self.assertListEqualObj([snaps[1]], res)

    def test_get_snapshots_by_name_multiple(self):
        snap_name = 'snap'
        vol = self.create_volumes([{'size': 1}])[0]
        snaps = [cinderlib.Snapshot(vol, name=snap_name) for i in range(2)]
        [self.persistence.set_snapshot(snap) for snap in snaps]
        res = self.persistence.get_snapshots(snapshot_name=snap_name)
        self.assertListEqualObj(self.sorted(snaps), self.sorted(res))

    def test_get_snapshots_by_name_not_found(self):
        self.create_snapshots()
        res = self.persistence.get_snapshots(snapshot_name='snap3')
        self.assertListEqualObj([], res)

    def test_get_snapshots_by_volume(self):
        snaps = self.create_snapshots()
        vol = snaps[0].volume
        expected_snaps = [snaps[0], cinderlib.Snapshot(vol)]
        self.persistence.set_snapshot(expected_snaps[1])
        res = self.persistence.get_snapshots(volume_id=vol.id)
        self.assertListEqualObj(self.sorted(expected_snaps), self.sorted(res))

    def test_get_snapshots_by_volume_not_found(self):
        self.create_snapshots()
        res = self.persistence.get_snapshots(volume_id='fake_uuid')
        self.assertListEqualObj([], res)

    def test_get_snapshots_by_multiple(self):
        snap_name = 'snap'
        vol = self.create_volumes([{'size': 1}])[0]
        snaps = [cinderlib.Snapshot(vol, name=snap_name) for i in range(2)]
        [self.persistence.set_snapshot(snap) for snap in snaps]
        res = self.persistence.get_snapshots(volume_id=vol.id,
                                             snapshot_name=snap_name,
                                             snapshot_id=snaps[0].id)
        self.assertListEqualObj([snaps[0]], self.sorted(res))

    def test_get_snapshots_by_multiple_not_found(self):
        snaps = self.create_snapshots()
        res = self.persistence.get_snapshots(snapshot_name=snaps[1].name,
                                             volume_id=snaps[0].volume.id)
        self.assertListEqualObj([], res)

    def test_delete_snapshot(self):
        snaps = self.create_snapshots()
        self.persistence.delete_snapshot(snaps[0])
        res = self.persistence.get_snapshots()
        self.assertListEqualObj([snaps[1]], res)

    def test_delete_snapshot_not_found(self):
        snaps = self.create_snapshots()
        fake_snap = cinderlib.Snapshot(snaps[0].volume)
        self.persistence.delete_snapshot(fake_snap)
        res = self.persistence.get_snapshots()
        self.assertListEqualObj(snaps, self.sorted(res))

    def test_set_connection(self):
        raise NotImplementedError('Test class must implement this method')

    def get_connections_all(self):
        conns = self.create_connections()
        res = self.persistence.get_connections()
        self.assertListEqual(conns, self.sorted(res))

    def test_get_connections_by_id(self):
        conns = self.create_connections()
        res = self.persistence.get_connections(connection_id=conns[1].id)
        self.assertListEqualObj([conns[1]], res)

    def test_get_connections_by_id_not_found(self):
        self.create_connections()
        res = self.persistence.get_connections(connection_id='fake-uuid')
        self.assertListEqualObj([], res)

    def test_get_connections_by_volume(self):
        conns = self.create_connections()
        vol = conns[0].volume
        expected_conns = [conns[0], cinderlib.Connection(
            self.backend, volume=vol, connection_info={'conn': {'data': {}}})]
        self.persistence.set_connection(expected_conns[1])
        res = self.persistence.get_connections(volume_id=vol.id)
        self.assertListEqualObj(self.sorted(expected_conns), self.sorted(res))

    def test_get_connections_by_volume_not_found(self):
        self.create_connections()
        res = self.persistence.get_connections(volume_id='fake_uuid')
        self.assertListEqualObj([], res)

    def test_get_connections_by_multiple(self):
        vol = self.create_volumes([{'size': 1}])[0]
        conns = [cinderlib.Connection(self.backend, volume=vol,
                                      connection_info={'conn': {'data': {}}})
                 for i in range(2)]
        [self.persistence.set_connection(conn) for conn in conns]
        res = self.persistence.get_connections(volume_id=vol.id,
                                               connection_id=conns[0].id)
        self.assertListEqualObj([conns[0]], self.sorted(res))

    def test_get_connections_by_multiple_not_found(self):
        conns = self.create_connections()
        res = self.persistence.get_connections(volume_id=conns[0].volume.id,
                                               connection_id=conns[1].id)
        self.assertListEqualObj([], res)

    def test_delete_connection(self):
        conns = self.create_connections()
        self.persistence.delete_connection(conns[1])
        res = self.persistence.get_connections()
        self.assertListEqualObj([conns[0]], res)

    def test_delete_connection_not_found(self):
        conns = self.create_connections()
        fake_conn = cinderlib.Connection(
            self.backend,
            volume=conns[0].volume,
            connection_info={'conn': {'data': {}}})
        self.persistence.delete_connection(fake_conn)
        res = self.persistence.get_connections()
        self.assertListEqualObj(conns, self.sorted(res))

    def test_set_key_values(self):
        raise NotImplementedError('Test class must implement this method')

    def assertKVsEqual(self, expected, actual):
        if len(expected) == len(actual):
            for (key, value), actual in zip(expected, actual):
                self.assertEqual(key, actual.key)
                self.assertEqual(value, actual.value)
            return
        assert False, '%s is not equal to %s' % (expected, actual)

    def get_key_values_all(self):
        kvs = self.create_key_values()
        res = self.persistence.get_key_values()
        self.assertListEqual(kvs, self.sorted(res, 'key'))

    def test_get_key_values_by_key(self):
        kvs = self.create_key_values()
        res = self.persistence.get_key_values(key=kvs[1].key)
        self.assertListEqual([kvs[1]], res)

    def test_get_key_values_by_key_not_found(self):
        self.create_key_values()
        res = self.persistence.get_key_values(key='fake-uuid')
        self.assertListEqual([], res)

    def test_delete_key_value(self):
        kvs = self.create_key_values()
        self.persistence.delete_key_value(kvs[1])
        res = self.persistence.get_key_values()
        self.assertListEqual([kvs[0]], res)

    def test_delete_key_not_found(self):
        kvs = self.create_key_values()
        fake_key = cinderlib.KeyValue('fake-key')
        self.persistence.delete_key_value(fake_key)
        res = self.persistence.get_key_values()
        self.assertListEqual(kvs, self.sorted(res, 'key'))

    @mock.patch('cinderlib.persistence.base.DB.volume_type_get')
    def test__volume_type_get_by_name(self, get_mock):
        # Only test when using our fake DB class.  We cannot use
        # unittest.skipUnless because persistence is configure in setUpClass,
        # which is called after the decorator.
        if not isinstance(cinderlib.objects.Backend.persistence.db,
                          persistence_base.DB):
            return

        # Volume type id and name are the same, so method must be too
        res = self.persistence.db._volume_type_get_by_name(self.context,
                                                           mock.sentinel.name)
        self.assertEqual(get_mock.return_value, res)
        get_mock.assert_called_once_with(self.context, mock.sentinel.name)

    def test_volume_type_get_by_id(self):
        extra_specs = [{'k1': 'v1', 'k2': 'v2'},
                       {'kk1': 'vv1', 'kk2': 'vv2', 'kk3': 'vv3'}]
        vols = self.create_volumes(
            [{'size': 1, 'extra_specs': extra_specs[0]},
             {'size': 2, 'extra_specs': extra_specs[1]}],
            sort=False)

        res = self.persistence.db.volume_type_get(self.context, vols[0].id)

        self.assertEqual(vols[0].id, res['id'])
        self.assertEqual(vols[0].id, res['name'])
        self.assertEqual(extra_specs[0], res['extra_specs'])

    def test_volume_get_all_by_host(self):
        # Only test when using our fake DB class.  We cannot use
        # unittest.skipUnless because persistence is configure in setUpClass,
        # which is called after the decorator.
        if not isinstance(cinderlib.objects.Backend.persistence.db,
                          persistence_base.DB):
            return

        persistence_db = self.persistence.db
        host = '%s@%s' % (cfg.CONF.host, self.backend.id)

        vols = [v._ovo for v in self.create_n_volumes(2)]
        backend2 = utils.FakeBackend(volume_backend_name='fake2')
        vol = self.create_volumes([{'backend_or_vol': backend2, 'size': 3}])

        # We should be able to get it using the host@backend
        res = persistence_db.volume_get_all_by_host(self.context, host)
        self.assertListEqualObj(vols, self.sorted(res))

        # Confirm it also works when we pass a host that includes the pool
        res = persistence_db.volume_get_all_by_host(self.context, vols[0].host)
        self.assertListEqualObj(vols, self.sorted(res))

        # Check we also get the other backend's volume
        host = '%s@%s' % (cfg.CONF.host, backend2.id)
        res = persistence_db.volume_get_all_by_host(self.context, host)
        self.assertListEqualObj(vol[0]._ovo, res[0])

    def test__volume_admin_metadata_get(self):
        # Only test when using our fake DB class.  We cannot use
        # unittest.skipUnless because persistence is configure in setUpClass,
        # which is called after the decorator.
        if not isinstance(cinderlib.objects.Backend.persistence.db,
                          persistence_base.DB):
            return

        admin_metadata = {'k': 'v'}
        vols = self.create_volumes([{'size': 1,
                                     'admin_metadata': admin_metadata}])
        result = self.persistence.db._volume_admin_metadata_get(self.context,
                                                                vols[0].id)
        self.assertDictEqual(admin_metadata, result)

    def test__volume_admin_metadata_update(self):
        # Only test when using our fake DB class.  We cannot use
        # unittest.skipUnless because persistence is configure in setUpClass,
        # which is called after the decorator.
        if not isinstance(cinderlib.objects.Backend.persistence.db,
                          persistence_base.DB):
            return

        create_admin_metadata = {'k': 'v', 'k2': 'v2'}
        admin_metadata = {'k2': 'v2.1', 'k3': 'v3'}
        vols = self.create_volumes([{'size': 1,
                                     'admin_metadata': create_admin_metadata}])

        self.persistence.db._volume_admin_metadata_update(self.context,
                                                          vols[0].id,
                                                          admin_metadata,
                                                          delete=True,
                                                          add=True,
                                                          update=True)
        result = self.persistence.db._volume_admin_metadata_get(self.context,
                                                                vols[0].id)
        self.assertDictEqual({'k2': 'v2.1', 'k3': 'v3'}, result)

    def test__volume_admin_metadata_update_do_nothing(self):
        # Only test when using our fake DB class.  We cannot use
        # unittest.skipUnless because persistence is configure in setUpClass,
        # which is called after the decorator.
        if not isinstance(cinderlib.objects.Backend.persistence.db,
                          persistence_base.DB):
            return

        create_admin_metadata = {'k': 'v', 'k2': 'v2'}
        admin_metadata = {'k2': 'v2.1', 'k3': 'v3'}
        vols = self.create_volumes([{'size': 1,
                                     'admin_metadata': create_admin_metadata}])

        # Setting delete, add, and update to False means we don't do anything
        self.persistence.db._volume_admin_metadata_update(self.context,
                                                          vols[0].id,
                                                          admin_metadata,
                                                          delete=False,
                                                          add=False,
                                                          update=False)
        result = self.persistence.db._volume_admin_metadata_get(self.context,
                                                                vols[0].id)
        self.assertDictEqual(create_admin_metadata, result)

    def test_volume_admin_metadata_delete(self):
        # Only test when using our fake DB class.  We cannot use
        # unittest.skipUnless because persistence is configure in setUpClass,
        # which is called after the decorator.
        if not isinstance(cinderlib.objects.Backend.persistence.db,
                          persistence_base.DB):
            return

        admin_metadata = {'k': 'v', 'k2': 'v2'}
        vols = self.create_volumes([{'size': 1,
                                     'admin_metadata': admin_metadata}])

        self.persistence.db.volume_admin_metadata_delete(self.context,
                                                         vols[0].id,
                                                         'k2')
        result = self.persistence.db._volume_admin_metadata_get(self.context,
                                                                vols[0].id)
        self.assertDictEqual({'k': 'v'}, result)

    @mock.patch('cinderlib.objects.Volume.get_by_id')
    @mock.patch('cinderlib.objects.Volume.snapshots',
                new_callable=mock.PropertyMock)
    @mock.patch('cinderlib.objects.Volume.connections',
                new_callable=mock.PropertyMock)
    def test_volume_refresh(self, get_conns_mock, get_snaps_mock, get_mock):
        vol = self.create_n_volumes(1)[0]
        vol_id = vol.id
        # This is to simulate situation where the persistence does lazy loading
        vol._snapshots = vol._connections = None
        get_mock.return_value = cinderlib.Volume(vol)

        vol.refresh()

        get_mock.assert_called_once_with(vol_id)
        get_conns_mock.assert_not_called()
        get_snaps_mock.assert_not_called()
        self.assertIsNone(vol.local_attach)

    @mock.patch('cinderlib.objects.Volume.get_by_id')
    @mock.patch('cinderlib.objects.Volume.snapshots',
                new_callable=mock.PropertyMock)
    @mock.patch('cinderlib.objects.Volume.connections',
                new_callable=mock.PropertyMock)
    def test_volume_refresh_with_conn_and_snaps(self, get_conns_mock,
                                                get_snaps_mock, get_mock):
        vol = self.create_n_volumes(1)[0]
        vol_id = vol.id
        vol.local_attach = mock.sentinel.local_attach
        get_mock.return_value = cinderlib.Volume(vol)

        vol.refresh()

        get_mock.assert_called_once_with(vol_id)
        get_conns_mock.assert_called_once_with()
        get_snaps_mock.assert_called_once_with()
        self.assertIs(mock.sentinel.local_attach, vol.local_attach)

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

import tempfile
from unittest import mock

from cinder.db.sqlalchemy import api as sqla_api
from cinder.db.sqlalchemy import models as sqla_models
from cinder import objects as cinder_ovos
from oslo_db import api as oslo_db_api

import cinderlib
from cinderlib.persistence import dbms
from cinderlib.tests.unit.persistence import base


class TestDBPersistence(base.BasePersistenceTest):
    CONNECTION = 'sqlite:///' + tempfile.NamedTemporaryFile().name
    PERSISTENCE_CFG = {'storage': 'db',
                       'connection': CONNECTION}

    def tearDown(self):
        with sqla_api.main_context_manager.writer.using(self.context):
            sqla_api.model_query(self.context, sqla_models.Snapshot).delete()
            sqla_api.model_query(self.context,
                                 sqla_models.VolumeAttachment).delete()
            sqla_api.model_query(self.context, sqla_models.Volume).delete()
            self.context.session.query(dbms.KeyValue).delete()
        # FIXME: should this be inside or outside the context manager?
        # Doesn't seem to matter for our current tests.
        super(TestDBPersistence, self).tearDown()

    def test_db(self):
        self.assertIsInstance(self.persistence.db,
                              oslo_db_api.DBAPI)

    def test_set_volume(self):
        res = sqla_api.volume_get_all(self.context)
        self.assertListEqual([], res)

        vol = cinderlib.Volume(self.backend, size=1, name='disk')
        expected = {'availability_zone': vol.availability_zone,
                    'size': vol.size, 'name': vol.name}

        self.persistence.set_volume(vol)

        db_vol = sqla_api.volume_get(self.context, vol.id)
        actual = {'availability_zone': db_vol.availability_zone,
                  'size': db_vol.size, 'name': db_vol.display_name}

        self.assertDictEqual(expected, actual)

    def test_set_snapshot(self):
        vol = cinderlib.Volume(self.backend, size=1, name='disk')
        # This will assign a volume type, which is necessary for the snapshot
        vol.save()
        snap = cinderlib.Snapshot(vol, name='disk')

        self.assertEqual(0, len(sqla_api.snapshot_get_all(self.context)))

        self.persistence.set_snapshot(snap)

        db_entries = sqla_api.snapshot_get_all(self.context)
        self.assertEqual(1, len(db_entries))

        ovo_snap = cinder_ovos.Snapshot(self.context)
        ovo_snap._from_db_object(ovo_snap._context, ovo_snap, db_entries[0])
        cl_snap = cinderlib.Snapshot(vol, __ovo=ovo_snap)

        self.assertEqualObj(snap, cl_snap)

    def test_set_connection(self):
        vol = cinderlib.Volume(self.backend, size=1, name='disk')
        conn = cinderlib.Connection(self.backend, volume=vol, connector={},
                                    connection_info={'conn': {'data': {}}})

        self.assertEqual(0,
                         len(sqla_api.volume_attachment_get_all(self.context)))

        self.persistence.set_connection(conn)

        db_entries = sqla_api.volume_attachment_get_all(self.context)
        self.assertEqual(1, len(db_entries))

        ovo_conn = cinder_ovos.VolumeAttachment(self.context)
        ovo_conn._from_db_object(ovo_conn._context, ovo_conn, db_entries[0])
        cl_conn = cinderlib.Connection(vol.backend, volume=vol, __ovo=ovo_conn)

        self.assertEqualObj(conn, cl_conn)

    def test_set_key_values(self):
        with sqla_api.main_context_manager.reader.using(self.context):
            res = self.context.session.query(dbms.KeyValue).all()
        self.assertListEqual([], res)

        expected = [dbms.KeyValue(key='key', value='value')]
        with sqla_api.main_context_manager.writer.using(self.context):
            self.persistence.set_key_value(expected[0])

        with sqla_api.main_context_manager.reader.using(self.context):
            actual = self.context.session.query(dbms.KeyValue).all()
        self.assertListEqualObj(expected, actual)

    def test_create_volume_with_default_volume_type(self):
        vol = cinderlib.Volume(self.backend, size=1, name='disk')
        self.persistence.set_volume(vol)
        self.assertEqual(self.persistence.DEFAULT_TYPE.id, vol.volume_type_id)
        self.assertIs(self.persistence.DEFAULT_TYPE, vol.volume_type)
        res = sqla_api.volume_type_get(self.context, vol.volume_type_id)
        self.assertIsNotNone(res)
        self.assertEqual('__DEFAULT__', res['name'])

    def test_default_volume_type(self):
        self.assertIsInstance(self.persistence.DEFAULT_TYPE,
                              cinder_ovos.VolumeType)
        self.assertEqual('__DEFAULT__', self.persistence.DEFAULT_TYPE.name)

    def test_delete_volume_with_metadata(self):
        # FIXME: figure out why this sometimes (often enough to skip)
        # raises sqlite3.OperationalError: database is locked
        if not isinstance(self, TestMemoryDBPersistence):
            self.skipTest("FIXME!")

        vols = self.create_volumes([{'size': i, 'name': 'disk%s' % i,
                                     'metadata': {'k': 'v', 'k2': 'v2'},
                                     'admin_metadata': {'k': '1'}}
                                    for i in range(1, 3)])
        with sqla_api.main_context_manager.writer.using(self.context):
            self.persistence.delete_volume(vols[0])
        with sqla_api.main_context_manager.reader.using(self.context):
            res = self.persistence.get_volumes()
        self.assertListEqualObj([vols[1]], res)

        for model in (dbms.models.VolumeMetadata,
                      dbms.models.VolumeAdminMetadata):
            with sqla_api.main_context_manager.reader.using(self.context):
                query = dbms.sqla_api.model_query(self.context, model)
            res = query.filter_by(volume_id=vols[0].id).all()
            self.assertEqual([], res)

    def test_delete_volume(self):
        vols = self.create_n_volumes(2)
        with sqla_api.main_context_manager.writer.using(self.context):
            self.persistence.delete_volume(vols[0])
        res = self.persistence.get_volumes()
        self.assertListEqualObj([vols[1]], res)

    def test_delete_volume_not_found(self):
        vols = self.create_n_volumes(2)
        fake_vol = cinderlib.Volume(backend_or_vol=self.backend)
        with sqla_api.main_context_manager.writer.using(self.context):
            self.persistence.delete_volume(fake_vol)
        res = self.persistence.get_volumes()
        self.assertListEqualObj(vols, self.sorted(res))

    def test_get_snapshots_by_multiple_not_found(self):
        with sqla_api.main_context_manager.writer.using(self.context):
            snaps = self.create_snapshots()
        with sqla_api.main_context_manager.reader.using(self.context):
            res = self.persistence.get_snapshots(snapshot_name=snaps[1].name,
                                                 volume_id=snaps[0].volume.id)
        self.assertListEqualObj([], res)

    def test_delete_snapshot(self):
        with sqla_api.main_context_manager.writer.using(self.context):
            snaps = self.create_snapshots()
            self.persistence.delete_snapshot(snaps[0])
        with sqla_api.main_context_manager.reader.using(self.context):
            res = self.persistence.get_snapshots()
        self.assertListEqualObj([snaps[1]], res)

    def test_delete_snapshot_not_found(self):
        with sqla_api.main_context_manager.writer.using(self.context):
            snaps = self.create_snapshots()
        fake_snap = cinderlib.Snapshot(snaps[0].volume)
        with sqla_api.main_context_manager.writer.using(self.context):
            self.persistence.delete_snapshot(fake_snap)
        with sqla_api.main_context_manager.reader.using(self.context):
            res = self.persistence.get_snapshots()
        self.assertListEqualObj(snaps, self.sorted(res))

    def test_delete_connection(self):
        conns = self.create_connections()
        with sqla_api.main_context_manager.writer.using(self.context):
            self.persistence.delete_connection(conns[1])
        with sqla_api.main_context_manager.reader.using(self.context):
            res = self.persistence.get_connections()
        self.assertListEqualObj([conns[0]], res)

    def test_delete_connection_not_found(self):
        conns = self.create_connections()
        fake_conn = cinderlib.Connection(
            self.backend,
            volume=conns[0].volume,
            connection_info={'conn': {'data': {}}})
        with sqla_api.main_context_manager.writer.using(self.context):
            self.persistence.delete_connection(fake_conn)
        with sqla_api.main_context_manager.reader.using(self.context):
            res = self.persistence.get_connections()
        self.assertListEqualObj(conns, self.sorted(res))

    def test_get_key_values_by_key(self):
        with sqla_api.main_context_manager.writer.using(self.context):
            kvs = self.create_key_values()
        with sqla_api.main_context_manager.reader.using(self.context):
            res = self.persistence.get_key_values(key=kvs[1].key)
        self.assertListEqual([kvs[1]], res)

    def test_get_key_values_by_key_not_found(self):
        with sqla_api.main_context_manager.writer.using(self.context):
            self.create_key_values()
        with sqla_api.main_context_manager.reader.using(self.context):
            res = self.persistence.get_key_values(key='fake-uuid')
        self.assertListEqual([], res)

    def test_delete_key_value(self):
        kvs = self.create_key_values()
        with sqla_api.main_context_manager.writer.using(self.context):
            self.persistence.delete_key_value(kvs[1])
        with sqla_api.main_context_manager.reader.using(self.context):
            res = self.persistence.get_key_values()
        self.assertListEqual([kvs[0]], res)

    def test_delete_key_not_found(self):
        kvs = self.create_key_values()
        fake_key = cinderlib.KeyValue('fake-key')
        with sqla_api.main_context_manager.writer.using(self.context):
            self.persistence.delete_key_value(fake_key)
        with sqla_api.main_context_manager.reader.using(self.context):
            res = self.persistence.get_key_values()
        self.assertListEqual(kvs, self.sorted(res, 'key'))


class TestDBPersistenceNewerSchema(base.helper.TestHelper):
    """Test DBMS plugin can start when the DB has a newer schema."""
    CONNECTION = 'sqlite:///' + tempfile.NamedTemporaryFile().name
    PERSISTENCE_CFG = {'storage': 'db',
                       'connection': CONNECTION}

    @classmethod
    def setUpClass(cls):
        pass

    def _raise_exc(self):
        inner_exc = dbms.migrate.exceptions.VersionNotFoundError()
        exc = dbms.exception.DBMigrationError(inner_exc)
        self.original_db_sync()
        raise(exc)

    def test_newer_db_schema(self):
        self.original_db_sync = dbms.migration.db_sync
        with mock.patch.object(dbms.migration, 'db_sync',
                               side_effect=self._raise_exc) as db_sync_mock:
            super(TestDBPersistenceNewerSchema, self).setUpClass()
            db_sync_mock.assert_called_once()
            self.assertIsInstance(cinderlib.Backend.persistence,
                                  dbms.DBPersistence)


class TestMemoryDBPersistence(TestDBPersistence):
    PERSISTENCE_CFG = {'storage': 'memory_db'}

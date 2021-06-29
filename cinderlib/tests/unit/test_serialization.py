# Copyright (c) 2021, Red Hat, Inc.
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

from cinderlib import objects
from cinderlib.tests.unit import base


class TestSerialization(base.BaseTest):
    def test_vol_to_and_from(self):
        vol = objects.Volume(self.backend, size=10)
        snap = objects.Snapshot(vol, name='disk')

        # Associate the snapshot with the volume
        vol._snapshots = None
        with mock.patch.object(vol.persistence, 'get_snapshots',
                               return_value=[snap]):
            vol.snapshots
        self.assertEqual(1, len(vol.snapshots))

        json_data = vol.json

        # Confirm vol.json property is equivalent to the non simplified version
        self.assertEqual(json_data, vol.to_json(simplified=False))
        vol2 = objects.Volume.load(json_data)
        # Check snapshots are recovered as well
        self.assertEqual(1, len(vol2.snapshots))
        self.assertEqual(vol.json, vol2.json)

    def test_snap_to_and_from(self):
        vol = objects.Volume(self.backend, size=10)
        snap = objects.Snapshot(vol, name='disk')
        json_data = snap.json

        # Confirm vol.json property is equivalent to the non simplified version
        self.assertEqual(json_data, snap.to_json(simplified=False))
        snap2 = objects.Snapshot.load(json_data)
        self.assertEqual(snap.json, snap2.json)

    def test_conn_to_and_from(self):
        vol = objects.Volume(self.backend, size=1, name='disk')
        conn = objects.Connection(self.backend, volume=vol, connector={},
                                  connection_info={'conn': {'data': {}}})
        json_data = conn.json

        # Confirm vol.json property is equivalent to the non simplified version
        self.assertEqual(json_data, conn.to_json(simplified=False))
        conn2 = objects.Connection.load(json_data)
        self.assertEqual(conn.json, conn2.json)

    def test_datetime_subsecond(self):
        """Test microsecond serialization of DateTime fields."""
        microsecond = 123456
        vol = objects.Volume(self.backend, size=1, name='disk')
        vol._ovo.created_at = vol.created_at.replace(microsecond=microsecond)
        created_at = vol.created_at

        json_data = vol.json
        vol2 = objects.Volume.load(json_data)
        self.assertEqual(created_at, vol2.created_at)
        self.assertEqual(microsecond, vol2.created_at.microsecond)

    def test_datetime_non_subsecond(self):
        """Test rehydration of DateTime field without microsecond."""
        vol = objects.Volume(self.backend, size=1, name='disk')
        vol._ovo.created_at = vol.created_at.replace(microsecond=123456)

        with mock.patch.object(vol._ovo.fields['created_at'], 'to_primitive',
                               return_value='2021-06-28T17:14:59Z'):
            json_data = vol.json
        vol2 = objects.Volume.load(json_data)
        self.assertEqual(0, vol2.created_at.microsecond)

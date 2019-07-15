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

import cinderlib
from cinderlib.tests.unit.persistence import helper


class TestBasePersistence(helper.TestHelper):
    PERSISTENCE_CFG = {'storage': 'memory'}

    def tearDown(self):
        self.persistence.volumes.clear()
        self.persistence.snapshots.clear()
        self.persistence.connections.clear()
        self.persistence.key_values.clear()
        super(TestBasePersistence, self).tearDown()

    def test_get_changed_fields_volume(self):
        vol = cinderlib.Volume(self.backend, size=1, extra_specs={'k': 'v'})
        self.persistence.set_volume(vol)
        vol._ovo.display_name = "abcde"
        result = self.persistence.get_changed_fields(vol)
        self.assertEqual(result, {'display_name': vol._ovo.display_name})

    def test_get_changed_fields_snapshot(self):
        vol = cinderlib.Volume(self.backend, size=1, extra_specs={'k': 'v'})
        snap = cinderlib.Snapshot(vol)
        self.persistence.set_snapshot(snap)
        snap._ovo.display_name = "abcde"
        result = self.persistence.get_changed_fields(snap)
        self.assertEqual(result, {'display_name': snap._ovo.display_name})

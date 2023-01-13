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


import unittest
from unittest import mock

import cinderlib
from cinderlib.tests.unit import utils


cinderlib.setup(persistence_config={'storage': utils.get_mock_persistence()})


class BaseTest(unittest.TestCase):
    PERSISTENCE_CFG = None

    def setUp(self):
        if not self.PERSISTENCE_CFG:
            cfg = {'storage': utils.get_mock_persistence()}
            cinderlib.Backend.set_persistence(cfg)
        self.backend_name = 'fake_backend'
        self.backend = utils.FakeBackend(volume_backend_name=self.backend_name)
        self.persistence = self.backend.persistence
        cinderlib.Backend._volumes_inflight = {}

    def tearDown(self):
        # Clear all existing backends
        cinderlib.Backend.backends = {}

    def patch(self, path, *args, **kwargs):
        """Use python mock to mock a path with automatic cleanup."""
        patcher = mock.patch(path, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

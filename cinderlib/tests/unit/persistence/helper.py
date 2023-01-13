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

from cinder.cmd import volume as volume_cmd
from cinder.db.sqlalchemy import api
from cinder.db.sqlalchemy import models
from cinder import objects
from cinder.objects import base as cinder_base_ovo
from oslo_versionedobjects import fields

import cinderlib
from cinderlib.tests.unit import base


class TestHelper(base.BaseTest):

    @classmethod
    def setUpClass(cls):
        # Save OVO methods that some persistence plugins mess up
        cls.ovo_methods = {}
        for ovo_name in cinder_base_ovo.CinderObjectRegistry.obj_classes():
            ovo_cls = getattr(objects, ovo_name)
            cls.ovo_methods[ovo_name] = {
                'save': getattr(ovo_cls, 'save', None),
                'get_by_id': getattr(ovo_cls, 'get_by_id', None),
            }

        cls.original_impl = volume_cmd.session.IMPL
        cinderlib.Backend.global_initialization = False
        cinderlib.setup(persistence_config=cls.PERSISTENCE_CFG)

    @classmethod
    def tearDownClass(cls):
        volume_cmd.session.IMPL = cls.original_impl
        cinderlib.Backend.global_initialization = False

        # Cannot just replace the context manager itself because it is already
        # decorating cinder DB methods and those would continue accessing the
        # old database, so we replace the existing CM'sinternal transaction
        # factory, efectively "reseting" the context manager.
        cm = api.main_context_manager
        if cm.is_started:
            cm._root_factory = api.enginefacade._TransactionFactory()

        for ovo_name, methods in cls.ovo_methods.items():
            ovo_cls = getattr(objects, ovo_name)
            for method_name, method in methods.items():
                if method:
                    setattr(ovo_cls, method_name, method)

    def setUp(self):
        super(TestHelper, self).setUp()
        self.context = cinderlib.objects.CONTEXT

    def sorted(self, resources, key='id'):
        return sorted(resources, key=lambda x: getattr(x, key))

    def create_n_volumes(self, n):
        return self.create_volumes([{'size': i, 'name': 'disk%s' % i}
                                    for i in range(1, n + 1)])

    def create_volumes(self, data, sort=True):
        vols = []
        for d in data:
            d.setdefault('backend_or_vol', self.backend)
            vol = cinderlib.Volume(**d)
            vols.append(vol)
            self.persistence.set_volume(vol)
        if sort:
            return self.sorted(vols)
        return vols

    def create_snapshots(self):
        vols = self.create_n_volumes(2)
        snaps = []
        for i, vol in enumerate(vols):
            snap = cinderlib.Snapshot(vol, name='snaps%s' % (i + i))
            snaps.append(snap)
            self.persistence.set_snapshot(snap)
        return self.sorted(snaps)

    def create_connections(self):
        vols = self.create_n_volumes(2)
        conns = []
        for i, vol in enumerate(vols):
            conn = cinderlib.Connection(self.backend, volume=vol,
                                        connection_info={'conn': {'data': {}}})
            conns.append(conn)
            self.persistence.set_connection(conn)
        return self.sorted(conns)

    def create_key_values(self):
        kvs = []
        for i in range(2):
            kv = cinderlib.KeyValue(key='key%i' % i, value='value%i' % i)
            kvs.append(kv)
            self.persistence.set_key_value(kv)
        return kvs

    def _convert_to_dict(self, obj):
        if isinstance(obj, models.BASE):
            return dict(obj)

        if not isinstance(obj, cinderlib.objects.Object):
            return obj

        res = dict(obj._ovo)
        for key, value in obj._ovo.fields.items():
            if isinstance(value, fields.ObjectField):
                res.pop(key, None)
        res.pop('glance_metadata', None)
        res.pop('metadata', None)
        return res

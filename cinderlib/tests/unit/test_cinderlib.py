# Copyright (c) 2017, Red Hat, Inc.
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

import collections
import os

import ddt
import mock
from oslo_config import cfg

import cinderlib
from cinderlib import objects
from cinderlib.tests.unit import base


@ddt.ddt
class TestCinderlib(base.BaseTest):
    def test_list_supported_drivers(self):
        expected_keys = {'version', 'class_name', 'supported', 'ci_wiki_name',
                         'driver_options', 'class_fqn', 'desc'}

        drivers = cinderlib.Backend.list_supported_drivers()
        self.assertNotEqual(0, len(drivers))
        for name, driver_info in drivers.items():
            self.assertEqual(expected_keys, set(driver_info.keys()))

    def test_lib_assignations(self):
        self.assertEqual(cinderlib.setup, cinderlib.Backend.global_setup)
        self.assertEqual(cinderlib.Backend, cinderlib.objects.Backend)
        self.assertEqual(cinderlib.Backend,
                         cinderlib.objects.Object.backend_class)

    @mock.patch('cinderlib.Backend._apply_backend_workarounds')
    @mock.patch('oslo_utils.importutils.import_object')
    @mock.patch('cinderlib.Backend._get_backend_config')
    @mock.patch('cinderlib.Backend.global_setup')
    def test_init(self, mock_global_setup, mock_config, mock_import,
                  mock_workarounds):
        cfg.CONF.set_override('host', 'host')
        driver_cfg = {'k': 'v', 'k2': 'v2', 'volume_backend_name': 'Test'}
        cinderlib.Backend.global_initialization = False
        driver = mock_import.return_value
        driver.capabilities = {'pools': [{'pool_name': 'default'}]}

        backend = objects.Backend(**driver_cfg)

        mock_global_setup.assert_called_once_with()
        self.assertIn('Test', objects.Backend.backends)
        self.assertEqual(backend, objects.Backend.backends['Test'])
        mock_config.assert_called_once_with(driver_cfg)

        conf = mock_config.return_value
        mock_import.assert_called_once_with(conf.volume_driver,
                                            configuration=conf,
                                            db=self.persistence.db,
                                            host='host@Test',
                                            cluster_name=None,
                                            active_backend_id=None)
        self.assertEqual(backend.driver, driver)
        driver.do_setup.assert_called_once_with(objects.CONTEXT)
        driver.check_for_setup_error.assert_called_once_with()
        driver.init_capabilities.assert_called_once_with()
        driver.set_throttle.assert_called_once_with()
        driver.set_initialized.assert_called_once_with()
        self.assertEqual(driver_cfg, backend._driver_cfg)
        self.assertIsNone(backend._volumes)
        driver.get_volume_stats.assert_not_called()
        self.assertEqual(('default',), backend.pool_names)
        mock_workarounds.assert_called_once_with(mock_config.return_value)

    @mock.patch('cinderlib.Backend._validate_options')
    @mock.patch.object(cfg, 'CONF')
    def test__set_cinder_config(self, conf_mock, validate_mock):
        cinder_cfg = {'debug': True}

        objects.Backend._set_cinder_config('host', 'locks_path', cinder_cfg)

        self.assertEqual(2, conf_mock.set_default.call_count)
        conf_mock.set_default.assert_has_calls(
            [mock.call('state_path', os.getcwd()),
             mock.call('lock_path', '$state_path', 'oslo_concurrency')])

        self.assertEqual(cinderlib.__version__, cfg.CONF.version)

        self.assertEqual('locks_path', cfg.CONF.oslo_concurrency.lock_path)
        self.assertEqual('file://locks_path',
                         cfg.CONF.coordination.backend_url)
        self.assertEqual('host', cfg.CONF.host)

        validate_mock.assert_called_once_with(cinder_cfg)

        self.assertEqual(True, cfg.CONF.debug)

        self.assertIsNone(cfg._CachedArgumentParser().parse_args())

    @mock.patch('cinderlib.Backend._set_cinder_config')
    @mock.patch('urllib3.disable_warnings')
    @mock.patch('cinder.coordination.COORDINATOR')
    @mock.patch('cinderlib.Backend._set_priv_helper')
    @mock.patch('cinderlib.Backend._set_logging')
    @mock.patch('cinderlib.cinderlib.serialization')
    @mock.patch('cinderlib.Backend.set_persistence')
    def test_global_setup(self, mock_set_pers, mock_serial, mock_log,
                          mock_sudo, mock_coord, mock_disable_warn,
                          mock_set_config):
        cls = objects.Backend
        cls.global_initialization = False
        cinder_cfg = {'k': 'v', 'k2': 'v2'}

        cls.global_setup(mock.sentinel.locks_path,
                         mock.sentinel.root_helper,
                         mock.sentinel.ssl_warnings,
                         mock.sentinel.disable_logs,
                         mock.sentinel.non_uuid_ids,
                         mock.sentinel.backend_info,
                         mock.sentinel.project_id,
                         mock.sentinel.user_id,
                         mock.sentinel.pers_cfg,
                         mock.sentinel.fail_missing_backend,
                         mock.sentinel.host,
                         **cinder_cfg)

        mock_set_config.assert_called_once_with(mock.sentinel.host,
                                                mock.sentinel.locks_path,
                                                cinder_cfg)

        self.assertEqual(mock.sentinel.fail_missing_backend,
                         cls.fail_on_missing_backend)
        self.assertEqual(mock.sentinel.root_helper, cls.root_helper)
        self.assertEqual(mock.sentinel.project_id, cls.project_id)
        self.assertEqual(mock.sentinel.user_id, cls.user_id)
        self.assertEqual(mock.sentinel.non_uuid_ids, cls.non_uuid_ids)
        mock_set_pers.assert_called_once_with(mock.sentinel.pers_cfg)

        mock_serial.setup.assert_called_once_with(cls)
        mock_log.assert_called_once_with(mock.sentinel.disable_logs)
        mock_sudo.assert_called_once_with(mock.sentinel.root_helper)
        mock_coord.start.assert_called_once_with()

        self.assertEqual(2, mock_disable_warn.call_count)
        self.assertTrue(cls.global_initialization)
        self.assertEqual(mock.sentinel.backend_info,
                         cls.output_all_backend_info)

    @mock.patch('cinderlib.cinderlib.LOG.warning')
    def test__validate_options(self, warning_mock):
        # Validate default group config with Boolean and MultiStrOpt
        self.backend._validate_options(
            {'debug': True,
             'osapi_volume_extension': ['a', 'b', 'c'],
             })
        # Test driver options with String, ListOpt, PortOpt
        self.backend._validate_options(
            {'volume_driver': 'cinder.volume.drivers.lvm.LVMVolumeDriver',
             'volume_group': 'cinder-volumes',
             'iscsi_secondary_ip_addresses': ['w.x.y.z', 'a.b.c.d'],
             'target_port': 12345,
             })

        warning_mock.assert_not_called()

    @ddt.data(
        ('debug', 'sure', None),
        ('target_port', 'abc', 'cinder.volume.drivers.lvm.LVMVolumeDriver'))
    @ddt.unpack
    def test__validate_options_failures(self, option, value, driver):
        self.assertRaises(
            ValueError,
            self.backend._validate_options,
            {'volume_driver': driver,
             option: value})

    @mock.patch('cinderlib.cinderlib.LOG.warning')
    def test__validate_options_unkown(self, warning_mock):
        self.backend._validate_options(
            {'volume_driver': 'cinder.volume.drivers.lvm.LVMVolumeDriver',
             'vmware_cluster_name': 'name'})
        self.assertEqual(1, warning_mock.call_count)

    def test_pool_names(self):
        pool_names = [mock.sentinel._pool_names]
        self.backend._pool_names = pool_names
        self.assertEqual(pool_names, self.backend.pool_names)

    def test_volumes(self):
        self.backend._volumes = None
        res = self.backend.volumes
        self.assertEqual(self.persistence.get_volumes.return_value, res)
        self.assertEqual(self.persistence.get_volumes.return_value,
                         self.backend._volumes)
        self.persistence.get_volumes.assert_called_once_with(
            backend_name=self.backend.id)

    def test_id(self):
        self.assertEqual(self.backend._driver_cfg['volume_backend_name'],
                         self.backend.id)

    def test_volumes_filtered(self):
        res = self.backend.volumes_filtered(mock.sentinel.vol_id,
                                            mock.sentinel.vol_name)
        self.assertEqual(self.persistence.get_volumes.return_value, res)
        self.assertEqual([], self.backend._volumes)
        self.persistence.get_volumes.assert_called_once_with(
            backend_name=self.backend.id,
            volume_id=mock.sentinel.vol_id,
            volume_name=mock.sentinel.vol_name)

    def test_stats(self):
        expect = {'pools': [mock.sentinel.data]}
        with mock.patch.object(self.backend.driver, 'get_volume_stats',
                               return_value=expect) as mock_stat:
            res = self.backend.stats(mock.sentinel.refresh)
            self.assertEqual(expect, res)
            mock_stat.assert_called_once_with(refresh=mock.sentinel.refresh)

    def test_stats_single(self):
        stat_value = {'driver_version': 'v1', 'key': 'value'}
        expect = {'driver_version': 'v1', 'key': 'value',
                  'pools': [{'key': 'value', 'pool_name': 'fake_backend'}]}
        with mock.patch.object(self.backend.driver, 'get_volume_stats',
                               return_value=stat_value) as mock_stat:
            res = self.backend.stats(mock.sentinel.refresh)
            self.assertEqual(expect, res)
            mock_stat.assert_called_once_with(refresh=mock.sentinel.refresh)

    @mock.patch('cinderlib.objects.Volume')
    def test_create_volume(self, mock_vol):
        kwargs = {'k': 'v', 'k2': 'v2'}
        res = self.backend.create_volume(mock.sentinel.size,
                                         mock.sentinel.name,
                                         mock.sentinel.desc,
                                         mock.sentinel.boot,
                                         **kwargs)
        self.assertEqual(mock_vol.return_value, res)
        mock_vol.assert_called_once_with(self.backend, size=mock.sentinel.size,
                                         name=mock.sentinel.name,
                                         description=mock.sentinel.desc,
                                         bootable=mock.sentinel.boot,
                                         **kwargs)
        mock_vol.return_value.create.assert_called_once_with()

    def test__volume_removed_no_list(self):
        vol = cinderlib.objects.Volume(self.backend, size=10)
        self.backend._volume_removed(vol)

    def test__volume_removed(self):
        vol = cinderlib.objects.Volume(self.backend, size=10)
        vol2 = cinderlib.objects.Volume(self.backend, id=vol.id, size=10)
        self.backend._volumes.append(vol)
        self.backend._volume_removed(vol2)
        self.assertEqual([], self.backend.volumes)

    def test__volume_created(self):
        vol = cinderlib.objects.Volume(self.backend, size=10)
        self.backend._volume_created(vol)
        self.assertEqual([vol], self.backend.volumes)

    def test__volume_created_is_none(self):
        vol = cinderlib.objects.Volume(self.backend, size=10)
        self.backend._volume_created(vol)
        self.assertEqual([vol], self.backend.volumes)

    def test_validate_connector(self):
        self.backend.validate_connector(mock.sentinel.connector)
        self.backend.driver.validate_connector.assert_called_once_with(
            mock.sentinel.connector)

    @mock.patch('cinderlib.objects.setup')
    @mock.patch('cinderlib.persistence.setup')
    def test_set_persistence(self, mock_pers_setup, mock_obj_setup):
        cinderlib.Backend.global_initialization = True

        cinderlib.Backend.set_persistence(mock.sentinel.pers_cfg)

        mock_pers_setup.assert_called_once_with(mock.sentinel.pers_cfg)
        self.assertEqual(mock_pers_setup.return_value,
                         cinderlib.Backend.persistence)
        mock_obj_setup.assert_called_once_with(mock_pers_setup.return_value,
                                               cinderlib.Backend,
                                               self.backend.project_id,
                                               self.backend.user_id,
                                               self.backend.non_uuid_ids)
        self.assertEqual(mock_pers_setup.return_value.db,
                         self.backend.driver.db)

    def test_config(self):
        self.backend.output_all_backend_info = False
        res = self.backend.config
        self.assertEqual({'volume_backend_name': self.backend.id}, res)

    def test_config_full(self):
        self.backend.output_all_backend_info = True
        with mock.patch.object(self.backend, '_driver_cfg') as mock_driver:
            res = self.backend.config
            self.assertEqual(mock_driver, res)

    def test_refresh(self):
        self.backend.refresh()
        self.persistence.get_volumes.assert_called_once_with(
            backend_name=self.backend.id)

    def test_refresh_no_call(self):
        self.backend._volumes = None
        self.backend.refresh()
        self.persistence.get_volumes.assert_not_called()

    @staticmethod
    def odict(*args):
        res = collections.OrderedDict()
        for i in range(0, len(args), 2):
            res[args[i]] = args[i + 1]
        return res

    @mock.patch('cinderlib.cinderlib.cfg.CONF')
    def test__apply_backend_workarounds(self, mock_conf):
        cfg = mock.Mock(volume_driver='cinder.volume.drivers.netapp...')
        self.backend._apply_backend_workarounds(cfg)
        self.assertEqual(cfg.volume_backend_name,
                         mock_conf.list_all_sections())

    @mock.patch('cinderlib.cinderlib.cfg.CONF')
    def test__apply_backend_workarounds_do_nothing(self, mock_conf):
        cfg = mock.Mock(volume_driver='cinder.volume.drivers.lvm...')
        self.backend._apply_backend_workarounds(cfg)
        self.assertEqual(mock_conf.list_all_sections.return_value,
                         mock_conf.list_all_sections())

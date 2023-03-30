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
import configparser
import os
from unittest import mock

from cinder import utils
import ddt
from oslo_config import cfg
from oslo_privsep import priv_context

import cinderlib
from cinderlib import objects
from cinderlib.tests.unit import base


@ddt.ddt
class TestCinderlib(base.BaseTest):
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

    @mock.patch('cinderlib.Backend._apply_backend_workarounds')
    @mock.patch('oslo_utils.importutils.import_object')
    @mock.patch('cinderlib.Backend._get_backend_config')
    @mock.patch('cinderlib.Backend.global_setup')
    def test_init_setup(self, mock_global_setup, mock_config, mock_import,
                        mock_workarounds):
        """Test initialization with the new 'setup' driver method."""
        cfg.CONF.set_override('host', 'host')
        driver_cfg = {'k': 'v', 'k2': 'v2', 'volume_backend_name': 'Test'}
        cinderlib.Backend.global_initialization = False
        driver = mock_import.return_value
        driver.do_setup.side_effect = AttributeError
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
        driver.check_for_setup_error.assert_not_called()
        driver.setup.assert_called_once_with(objects.CONTEXT)
        driver.init_capabilities.assert_called_once_with()
        driver.set_throttle.assert_called_once_with()
        driver.set_initialized.assert_called_once_with()
        self.assertEqual(driver_cfg, backend._driver_cfg)
        self.assertIsNone(backend._volumes)
        driver.get_volume_stats.assert_not_called()
        self.assertEqual(('default',), backend.pool_names)
        mock_workarounds.assert_called_once_with(mock_config.return_value)

    @mock.patch.object(objects.Backend, 'global_initialization', True)
    @mock.patch.object(objects.Backend, '_apply_backend_workarounds')
    @mock.patch('oslo_utils.importutils.import_object')
    @mock.patch.object(objects.Backend, '_get_backend_config')
    def test_init_call_twice(self, mock_config, mock_import, mock_workarounds):
        cinderlib.Backend.global_initialization = False
        driver_cfg = {'k': 'v', 'k2': 'v2', 'volume_backend_name': 'Test'}
        driver = mock_import.return_value
        driver.capabilities = {'pools': [{'pool_name': 'default'}]}

        backend = objects.Backend(**driver_cfg)
        self.assertEqual(1, mock_config.call_count)
        self.assertEqual(1, mock_import.call_count)
        self.assertEqual(1, mock_workarounds.call_count)

        # When initiallizing a Backend with the same configuration the Backend
        # class must behave as a singleton and we won't initialize it again
        backend_second = objects.Backend(**driver_cfg)
        self.assertIs(backend, backend_second)
        self.assertEqual(1, mock_config.call_count)
        self.assertEqual(1, mock_import.call_count)
        self.assertEqual(1, mock_workarounds.call_count)

    @mock.patch.object(objects.Backend, 'global_initialization', True)
    @mock.patch.object(objects.Backend, '_apply_backend_workarounds')
    @mock.patch('oslo_utils.importutils.import_object')
    @mock.patch.object(objects.Backend, '_get_backend_config')
    def test_init_call_twice_different_config(self, mock_config, mock_import,
                                              mock_workarounds):
        cinderlib.Backend.global_initialization = False
        driver_cfg = {'k': 'v', 'k2': 'v2', 'volume_backend_name': 'Test'}
        driver = mock_import.return_value
        driver.capabilities = {'pools': [{'pool_name': 'default'}]}

        objects.Backend(**driver_cfg)
        self.assertEqual(1, mock_config.call_count)
        self.assertEqual(1, mock_import.call_count)
        self.assertEqual(1, mock_workarounds.call_count)

        # It should fail if we reuse the backend name but change the config
        self.assertRaises(ValueError, objects.Backend, k3='v3', **driver_cfg)
        self.assertEqual(1, mock_config.call_count)
        self.assertEqual(1, mock_import.call_count)
        self.assertEqual(1, mock_workarounds.call_count)

    @mock.patch('cinderlib.Backend._validate_and_set_options')
    @mock.patch.object(cfg, 'CONF')
    def test__set_cinder_config(self, conf_mock, validate_mock):
        objects.Backend._set_cinder_config('host', 'locks_path',
                                           mock.sentinel.cfg)

        self.assertEqual(2, conf_mock.set_default.call_count)
        conf_mock.set_default.assert_has_calls(
            [mock.call('state_path', os.getcwd()),
             mock.call('lock_path', '$state_path', 'oslo_concurrency')])

        self.assertEqual(cinderlib.__version__, cfg.CONF.version)

        self.assertEqual('locks_path', cfg.CONF.oslo_concurrency.lock_path)
        self.assertEqual('file://locks_path',
                         cfg.CONF.coordination.backend_url)
        self.assertEqual('host', cfg.CONF.host)

        validate_mock.assert_called_once_with(mock.sentinel.cfg)

        self.assertIsNone(cfg._CachedArgumentParser().parse_args())

    @mock.patch('cinderlib.Backend._set_priv_helper')
    @mock.patch('cinderlib.Backend._set_cinder_config')
    @mock.patch('urllib3.disable_warnings')
    @mock.patch('cinder.coordination.COORDINATOR')
    @mock.patch('cinderlib.Backend._set_logging')
    @mock.patch('cinderlib.cinderlib.serialization')
    @mock.patch('cinderlib.Backend.set_persistence')
    def test_global_setup(self, mock_set_pers, mock_serial, mock_log,
                          mock_coord, mock_disable_warn, mock_set_config,
                          mock_priv_helper):
        cls = objects.Backend
        cls.global_initialization = False
        cinder_cfg = {'k': 'v', 'k2': 'v2'}

        # Save the current class configuration
        saved_cfg = vars(cls).copy()

        try:
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
            self.assertEqual(mock.sentinel.project_id, cls.project_id)
            self.assertEqual(mock.sentinel.user_id, cls.user_id)
            self.assertEqual(mock.sentinel.non_uuid_ids, cls.non_uuid_ids)
            mock_set_pers.assert_called_once_with(mock.sentinel.pers_cfg)

            mock_serial.setup.assert_called_once_with(cls)
            mock_log.assert_called_once_with(mock.sentinel.disable_logs)
            mock_coord.start.assert_called_once_with()

            mock_priv_helper.assert_called_once_with(mock.sentinel.root_helper)

            self.assertEqual(2, mock_disable_warn.call_count)
            self.assertTrue(cls.global_initialization)
            self.assertEqual(mock.sentinel.backend_info,
                             cls.output_all_backend_info)
        finally:
            # Restore the class configuration
            for k, v in saved_cfg.items():
                if not k.startswith('__'):
                    setattr(cls, k, v)

    @mock.patch('cinderlib.cinderlib.LOG.warning')
    def test__validate_and_set_options(self, warning_mock):
        self.addCleanup(cfg.CONF.clear_override, 'osapi_volume_extension')
        self.addCleanup(cfg.CONF.clear_override, 'debug')
        # Validate default group config with Boolean and MultiStrOpt
        self.backend._validate_and_set_options(
            {'debug': True,
             'osapi_volume_extension': ['a', 'b', 'c'],
             })
        # Global values overrides are left
        self.assertIs(True, cfg.CONF.debug)
        self.assertEqual(['a', 'b', 'c'], cfg.CONF.osapi_volume_extension)

        cinder_cfg = {
            'volume_driver': 'cinder.volume.drivers.lvm.LVMVolumeDriver',
            'volume_group': 'lvm-volumes',
            'target_secondary_ip_addresses': ['w.x.y.z', 'a.b.c.d'],
            'target_port': 12345,
        }
        expected_cfg = cinder_cfg.copy()

        # Test driver options with String, ListOpt, PortOpt
        self.backend._validate_and_set_options(cinder_cfg)
        # Non global value overrides have been cleaned up
        self.assertEqual('cinder-volumes',
                         cfg.CONF.backend_defaults.volume_group)
        self.assertEqual(
            [], cfg.CONF.backend_defaults.target_secondary_ip_addresses)
        self.assertEqual(3260, cfg.CONF.backend_defaults.target_port)
        self.assertEqual(expected_cfg, cinder_cfg)

        warning_mock.assert_not_called()

    @mock.patch('cinderlib.cinderlib.LOG.warning')
    def test__validate_and_set_options_rbd(self, warning_mock):
        original_override = cfg.CONF.set_override
        original_getattr = cfg.ConfigOpts.GroupAttr.__getattr__

        def my_override(option, value, *args):
            original_override(option, value, *args)
            # Simulate that the config option is missing if it's not
            if option == 'rbd_keyring_conf':
                raise cfg.NoSuchOptError('rbd_keyring_conf')

        def my_getattr(self, name):
            res = original_getattr(self, name)
            # Simulate that the config option is missing if it's not
            if name == 'rbd_keyring_conf':
                raise AttributeError()
            return res

        self.patch('oslo_config.cfg.ConfigOpts.GroupAttr.__getattr__',
                   my_getattr)
        self.patch('oslo_config.cfg.CONF.set_override',
                   side_effect=my_override)

        cinder_cfg = {'volume_driver': 'cinder.volume.drivers.rbd.RBDDriver',
                      'rbd_keyring_conf': '/etc/ceph/ceph.client.adm.keyring',
                      'rbd_user': 'adm',
                      'rbd_pool': 'volumes'}
        expected_cfg = cinder_cfg.copy()
        # Test driver options with String, ListOpt, PortOpt
        self.backend._validate_and_set_options(cinder_cfg)
        self.assertEqual(expected_cfg, cinder_cfg)
        # Non global value overrides have been cleaned up
        self.assertEqual(None, cfg.CONF.backend_defaults.rbd_user)
        self.assertEqual('rbd', cfg.CONF.backend_defaults.rbd_pool)
        warning_mock.assert_not_called()

    @ddt.data(
        ('debug', 'sure', None),
        ('target_port', 'abc', 'cinder.volume.drivers.lvm.LVMVolumeDriver'))
    @ddt.unpack
    def test__validate_and_set_options_failures(self, option, value,
                                                driver):
        self.assertRaises(
            ValueError,
            self.backend._validate_and_set_options,
            {'volume_driver': driver,
             option: value})

    @mock.patch('cinderlib.cinderlib.LOG.warning')
    def test__validate_and_set_options_unknown(self, warning_mock):
        self.backend._validate_and_set_options(
            {'volume_driver': 'cinder.volume.drivers.lvm.LVMVolumeDriver',
             'vmware_cluster_name': 'name'})
        self.assertEqual(1, warning_mock.call_count)

    def test_validate_and_set_options_templates(self):
        self.addCleanup(cfg.CONF.clear_override, 'my_ip')
        cfg.CONF.set_override('my_ip', '127.0.0.1')

        config_options = dict(
            volume_driver='cinder.volume.drivers.lvm.LVMVolumeDriver',
            volume_backend_name='lvm_iscsi',
            volume_group='my-${backend_defaults.volume_backend_name}-vg',
            target_ip_address='$my_ip',
        )
        expected = dict(
            volume_driver='cinder.volume.drivers.lvm.LVMVolumeDriver',
            volume_backend_name='lvm_iscsi',
            volume_group='my-lvm_iscsi-vg',
            target_ip_address='127.0.0.1',
        )
        self.backend._validate_and_set_options(config_options)

        self.assertDictEqual(expected, config_options)

        # Non global value overrides have been cleaned up
        self.assertEqual('cinder-volumes',
                         cfg.CONF.backend_defaults.volume_group)

    @mock.patch('cinderlib.cinderlib.Backend._validate_and_set_options')
    def test__get_backend_config(self, mock_validate):
        def my_validate(*args):
            # Simulate the cache clear happening in _validate_and_set_options
            cfg.CONF.clear_override('my_ip')

        mock_validate.side_effect = my_validate
        config_options = dict(
            volume_driver='cinder.volume.drivers.lvm.LVMVolumeDriver',
            volume_backend_name='lvm_iscsi',
            volume_group='volumes',
        )
        res = self.backend._get_backend_config(config_options)
        mock_validate.assert_called_once_with(config_options)
        self.assertEqual('lvm_iscsi', res.config_group)
        for opt in config_options.keys():
            self.assertEqual(config_options[opt], getattr(res, opt))

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
                  'pools': [{'key': 'value', 'pool_name': self.backend_name}]}
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

    def _check_privsep_root_helper_opt(self, is_changed):
        for opt in priv_context.OPTS:
            if opt.name == 'helper_command':
                break
        helper_path = os.path.join(os.path.dirname(cinderlib.__file__),
                                   'bin/venv-privsep-helper')
        self.assertIs(is_changed,
                      f'mysudo {helper_path}' == opt.default)

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch('os.path.exists')
    @mock.patch('configparser.ConfigParser')
    @mock.patch('oslo_privsep.priv_context.init')
    def test__set_priv_helper_no_venv_sudo(self, mock_ctxt_init, mock_parser,
                                           mock_exists):
        original_helper_func = utils.get_root_helper

        original_rootwrap_config = cfg.CONF.rootwrap_config
        rootwrap_config = '/etc/cinder/rootwrap.conf'
        # Not using set_override because it's not working as it should
        cfg.CONF.rootwrap_config = rootwrap_config

        try:
            self.backend._set_priv_helper('sudo')

            mock_exists.assert_not_called()
            mock_parser.assert_not_called()
            mock_ctxt_init.assert_not_called()
            self.assertIs(original_helper_func, utils.get_root_helper)
            self.assertIs(rootwrap_config, cfg.CONF.rootwrap_config)
            self._check_privsep_root_helper_opt(is_changed=False)
        finally:
            cfg.CONF.rootwrap_config = original_rootwrap_config

    @mock.patch('configparser.ConfigParser.read', mock.Mock())
    @mock.patch('configparser.ConfigParser.write', mock.Mock())
    @mock.patch('cinderlib.cinderlib.utils.__file__',
                '/.venv/lib/python3.7/site-packages/cinder')
    @mock.patch('cinderlib.cinderlib.os.environ', {'VIRTUAL_ENV': '/.venv'})
    @mock.patch('cinderlib.cinderlib.open')
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('oslo_privsep.priv_context.init')
    def test__set_priv_helper_venv_no_sudo(self, mock_ctxt_init, mock_exists,
                                           mock_open):

        file_contents = {'DEFAULT': {'filters_path': '/etc/cinder/rootwrap.d',
                                     'exec_dirs': '/dir1,/dir2'}}
        parser = configparser.ConfigParser()

        venv_wrap_cfg = '/.venv/etc/cinder/rootwrap.conf'

        original_helper_func = utils.get_root_helper
        original_rootwrap_config = cfg.CONF.rootwrap_config
        # Not using set_override because it's not working as it should
        default_wrap_cfg = '/etc/cinder/rootwrap.conf'
        cfg.CONF.rootwrap_config = default_wrap_cfg

        try:
            with mock.patch('cinder.utils.get_root_helper',
                            return_value='sudo wrapper') as mock_helper, \
                    mock.patch.dict(parser, file_contents, clear=True), \
                    mock.patch('configparser.ConfigParser') as mock_parser:
                mock_parser.return_value = parser
                self.backend._set_priv_helper('mysudo')

                mock_exists.assert_called_once_with(default_wrap_cfg)

                mock_parser.assert_called_once_with()
                parser.read.assert_called_once_with(venv_wrap_cfg)

                self.assertEqual('/.venv/etc/cinder/rootwrap.d',
                                 parser['DEFAULT']['filters_path'])
                self.assertEqual('/.venv/bin,/dir1,/dir2',
                                 parser['DEFAULT']['exec_dirs'])

                mock_open.assert_called_once_with(venv_wrap_cfg, 'w')
                parser.write.assert_called_once_with(
                    mock_open.return_value.__enter__.return_value)

                self.assertEqual('mysudo wrapper', utils.get_root_helper())

                mock_helper.assert_called_once_with()
                mock_ctxt_init.assert_called_once_with(root_helper=['mysudo'])

            self.assertIs(original_helper_func, utils.get_root_helper)
            self.assertEqual(venv_wrap_cfg, cfg.CONF.rootwrap_config)
            self._check_privsep_root_helper_opt(is_changed=True)
        finally:
            cfg.CONF.rootwrap_config = original_rootwrap_config
            utils.get_root_helper = original_helper_func

    @mock.patch('configparser.ConfigParser.read', mock.Mock())
    @mock.patch('configparser.ConfigParser.write', mock.Mock())
    @mock.patch('cinderlib.cinderlib.utils.__file__', '/opt/stack/cinder')
    @mock.patch('cinderlib.cinderlib.os.environ', {'VIRTUAL_ENV': '/.venv'})
    @mock.patch('shutil.copytree')
    @mock.patch('glob.glob',)
    @mock.patch('cinderlib.cinderlib.open')
    @mock.patch('os.path.exists', return_value=False)
    @mock.patch('oslo_privsep.priv_context.init')
    def test__set_priv_helper_venv_editable_no_sudo(self, mock_ctxt_init,
                                                    mock_exists, mock_open,
                                                    mock_glob, mock_copy):

        link_file = '/.venv/lib/python3.7/site-packages/cinder.egg-link'
        cinder_source_path = '/opt/stack/cinder'
        link_file_contents = cinder_source_path + '\n.'
        mock_glob.return_value = [link_file]
        open_fd = mock_open.return_value.__enter__.return_value
        open_fd.read.return_value = link_file_contents

        file_contents = {'DEFAULT': {'filters_path': '/etc/cinder/rootwrap.d',
                                     'exec_dirs': '/dir1,/dir2'}}
        parser = configparser.ConfigParser()

        venv_wrap_cfg = '/.venv/etc/cinder/rootwrap.conf'

        original_helper_func = utils.get_root_helper
        original_rootwrap_config = cfg.CONF.rootwrap_config
        # Not using set_override because it's not working as it should
        default_wrap_cfg = '/etc/cinder/rootwrap.conf'
        cfg.CONF.rootwrap_config = default_wrap_cfg

        try:
            with mock.patch('cinder.utils.get_root_helper',
                            return_value='sudo wrapper') as mock_helper, \
                    mock.patch.dict(parser, file_contents, clear=True), \
                    mock.patch('configparser.ConfigParser') as mock_parser:
                mock_parser.return_value = parser

                self.backend._set_priv_helper('mysudo')

                mock_glob.assert_called_once_with(
                    '/.venv/lib/python*/site-packages/cinder.egg-link')

                self.assertEqual(2, mock_exists.call_count)
                mock_exists.assert_has_calls([mock.call(default_wrap_cfg),
                                              mock.call(venv_wrap_cfg)])

                self.assertEqual(2, mock_open.call_count)
                mock_open.assert_any_call(link_file, 'r')
                mock_copy.assert_called_once_with(
                    cinder_source_path + '/etc/cinder', '/.venv/etc/cinder')

                mock_parser.assert_called_once_with()
                parser.read.assert_called_once_with(venv_wrap_cfg)

                self.assertEqual('/.venv/etc/cinder/rootwrap.d',
                                 parser['DEFAULT']['filters_path'])
                self.assertEqual('/.venv/bin,/dir1,/dir2',
                                 parser['DEFAULT']['exec_dirs'])

                mock_open.assert_any_call(venv_wrap_cfg, 'w')
                parser.write.assert_called_once_with(open_fd)

                self.assertEqual('mysudo wrapper', utils.get_root_helper())

                mock_helper.assert_called_once_with()
                mock_ctxt_init.assert_called_once_with(root_helper=['mysudo'])

            self.assertIs(original_helper_func, utils.get_root_helper)
            self.assertEqual(venv_wrap_cfg, cfg.CONF.rootwrap_config)
            self._check_privsep_root_helper_opt(is_changed=True)
        finally:
            cfg.CONF.rootwrap_config = original_rootwrap_config
            utils.get_root_helper = original_helper_func

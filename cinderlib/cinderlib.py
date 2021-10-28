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
import configparser
import glob
import json as json_lib
import logging
import multiprocessing
import os
import shutil

from cinder import coordination
from cinder.db import api as db_api
from cinder import objects as cinder_objects

# We need this here until we remove from cinder/volume/manager.py:
# VA_LIST = objects.VolumeAttachmentList
cinder_objects.register_all()  # noqa

from cinder.interface import util as cinder_interface_util
import cinder.privsep
from cinder import utils
from cinder.volume import configuration
from cinder.volume import manager  # noqa We need to import config options
import os_brick.privileged
from oslo_config import cfg
from oslo_log import log as oslo_logging
from oslo_privsep import priv_context
from oslo_utils import importutils
import urllib3

import cinderlib
from cinderlib import objects
from cinderlib import persistence
from cinderlib import serialization
from cinderlib import utils as cinderlib_utils


__all__ = ['setup', 'Backend']

LOG = logging.getLogger(__name__)


class Backend(object):
    """Representation of a Cinder Driver.

    User facing attributes are:

    - __init__
    - json
    - jsons
    - load
    - stats
    - create_volume
    - global_setup
    - validate_connector
    """
    backends = {}
    global_initialization = False
    # Some drivers try access the DB directly for extra specs on creation.
    # With this dictionary the DB class can get the necessary data
    _volumes_inflight = {}

    def __new__(cls, volume_backend_name, **driver_cfg):
        # Prevent redefinition of an already initialized backend on the same
        # persistence storage with a different configuration.
        backend = Backend.backends.get(volume_backend_name)
        if backend:
            # If we are instantiating the same backend return the one we have
            # saved (singleton pattern).
            if driver_cfg == backend._original_driver_cfg:
                return backend
            raise ValueError('Backend named %s already exists with a different'
                             ' configuration' % volume_backend_name)

        return super(Backend, cls).__new__(cls)

    def __init__(self, volume_backend_name, **driver_cfg):
        if not self.global_initialization:
            self.global_setup()
        # Instance already initialized
        if volume_backend_name in Backend.backends:
            return
        # Save the original config before we add the backend name and template
        # the values.
        self._original_driver_cfg = driver_cfg.copy()
        driver_cfg['volume_backend_name'] = volume_backend_name

        conf = self._get_backend_config(driver_cfg)
        self._apply_backend_workarounds(conf)
        self.driver = importutils.import_object(
            conf.volume_driver,
            configuration=conf,
            db=self.persistence.db,
            host='%s@%s' % (cfg.CONF.host, volume_backend_name),
            cluster_name=None,  # We don't use cfg.CONF.cluster for now
            active_backend_id=None)  # No failover for now

        # do_setup and check_for_setup errors were merged into setup in Yoga.
        # First try the old interface, and if it fails, try the new one.
        try:
            self.driver.do_setup(objects.CONTEXT)
            self.driver.check_for_setup_error()
        except AttributeError:
            self.driver.setup(objects.CONTEXT)

        self.driver.init_capabilities()
        self.driver.set_throttle()
        self.driver.set_initialized()
        self._driver_cfg = driver_cfg
        self._volumes = None

        # Some drivers don't implement the caching correctly. Populate cache
        # with data retrieved in init_capabilities.
        stats = self.driver.capabilities.copy()
        stats.pop('properties', None)
        stats.pop('vendor_prefix', None)
        self._stats = self._transform_legacy_stats(stats)

        self._pool_names = tuple(pool['pool_name'] for pool in stats['pools'])
        Backend.backends[volume_backend_name] = self

    @property
    def pool_names(self):
        return self._pool_names

    def __repr__(self):
        return '<cinderlib.Backend %s>' % self.id

    def __getattr__(self, name):
        return getattr(self.driver, name)

    @property
    def id(self):
        return self._driver_cfg['volume_backend_name']

    @property
    def volumes(self):
        if self._volumes is None:
            self._volumes = self.persistence.get_volumes(backend_name=self.id)
        return self._volumes

    def volumes_filtered(self, volume_id=None, volume_name=None):
        return self.persistence.get_volumes(backend_name=self.id,
                                            volume_id=volume_id,
                                            volume_name=volume_name)

    def _transform_legacy_stats(self, stats):
        """Convert legacy stats to new stats with pools key."""
        # Fill pools for legacy driver reports
        if stats and 'pools' not in stats:
            pool = stats.copy()
            pool['pool_name'] = self.id
            for key in ('driver_version', 'shared_targets',
                        'sparse_copy_volume', 'storage_protocol',
                        'vendor_name', 'volume_backend_name'):
                pool.pop(key, None)
            stats['pools'] = [pool]
        return stats

    def stats(self, refresh=False):
        # Some drivers don't implement the caching correctly, so we implement
        # it ourselves.
        if refresh:
            stats = self.driver.get_volume_stats(refresh=refresh)
            self._stats = self._transform_legacy_stats(stats)

        return self._stats

    def create_volume(self, size, name='', description='', bootable=False,
                      **kwargs):
        vol = objects.Volume(self, size=size, name=name,
                             description=description, bootable=bootable,
                             **kwargs)
        vol.create()
        return vol

    def _volume_removed(self, volume):
        i, vol = cinderlib_utils.find_by_id(volume.id, self._volumes)
        if vol:
            del self._volumes[i]

    @classmethod
    def _start_creating_volume(cls, volume):
        cls._volumes_inflight[volume.id] = volume

    def _volume_created(self, volume):
        if self._volumes is not None:
            self._volumes.append(volume)
        self._volumes_inflight.pop(volume.id, None)

    def validate_connector(self, connector_dict):
        """Raise exception if missing info for volume's connect call."""
        self.driver.validate_connector(connector_dict)

    @classmethod
    def set_persistence(cls, persistence_config):
        if not hasattr(cls, 'project_id'):
            raise Exception('set_persistence can only be called after '
                            'cinderlib has been configured')
        cls.persistence = persistence.setup(persistence_config)
        objects.setup(cls.persistence, Backend, cls.project_id, cls.user_id,
                      cls.non_uuid_ids)
        for backend in cls.backends.values():
            backend.driver.db = cls.persistence.db

        # Replace the standard DB implementation instance with the one from
        # the persistence plugin.
        db_api.IMPL = cls.persistence.db

    @classmethod
    def _set_cinder_config(cls, host, locks_path, cinder_config_params):
        """Setup the parser with all the known Cinder configuration."""
        cfg.CONF.set_default('state_path', os.getcwd())
        cfg.CONF.set_default('lock_path', '$state_path', 'oslo_concurrency')
        cfg.CONF.version = cinderlib.__version__

        if locks_path:
            cfg.CONF.oslo_concurrency.lock_path = locks_path
            cfg.CONF.coordination.backend_url = 'file://' + locks_path

        if host:
            cfg.CONF.host = host

        cls._validate_and_set_options(cinder_config_params)

        # Replace command line arg parser so we ignore caller's args
        cfg._CachedArgumentParser.parse_args = lambda *a, **kw: None

    @classmethod
    def _validate_and_set_options(cls, kvs, group=None):
        """Validate options and substitute references."""
        # Dynamically loading the driver triggers adding the specific
        # configuration options to the backend_defaults section
        if kvs.get('volume_driver'):
            driver_ns = kvs['volume_driver'].rsplit('.', 1)[0]
            __import__(driver_ns)
            group = group or 'backend_defaults'

        for k, v in kvs.items():
            try:
                # set_override does the validation
                cfg.CONF.set_override(k, v, group)
            except cfg.NoSuchOptError:
                # RBD keyring may be removed from the Cinder RBD driver, but
                # the functionality will remain for cinderlib usage only, so we
                # do the validation manually in that case.
                # NOTE: Templating won't work on the rbd_keyring_conf, but it's
                # unlikely to be needed.
                if k == 'rbd_keyring_conf':
                    if v and not isinstance(v, str):
                        raise ValueError('%s must be a string' % k)
                else:
                    # Don't fail on unknown variables, behave like cinder
                    LOG.warning('Unknown config option %s', k)

        oslo_group = getattr(cfg.CONF, str(group), cfg.CONF)
        # Now that we have validated/templated everything set updated values
        for k, v in kvs.items():
            kvs[k] = getattr(oslo_group, k, v)

        # For global configuration we leave the overrides, but for drivers we
        # don't to prevent cross-driver config polination.  The cfg will be
        # set as an attribute of the configuration that's passed to the driver.
        if group:
            for k in kvs.keys():
                try:
                    cfg.CONF.clear_override(k, group, clear_cache=True)
                except cfg.NoSuchOptError:
                    pass

    def _get_backend_config(self, driver_cfg):
        # Create the group for the backend
        backend_name = driver_cfg['volume_backend_name']
        cfg.CONF.register_group(cfg.OptGroup(backend_name))

        # Validate and set config options
        self._validate_and_set_options(driver_cfg)
        backend_group = getattr(cfg.CONF, backend_name)
        for key, value in driver_cfg.items():
            setattr(backend_group, key, value)

        # Return the Configuration that will be passed to the driver
        config = configuration.Configuration([], config_group=backend_name)
        return config

    @classmethod
    def global_setup(cls, file_locks_path=None, root_helper='sudo',
                     suppress_requests_ssl_warnings=True, disable_logs=True,
                     non_uuid_ids=False, output_all_backend_info=False,
                     project_id=None, user_id=None, persistence_config=None,
                     fail_on_missing_backend=True, host=None,
                     **cinder_config_params):
        # Global setup can only be set once
        if cls.global_initialization:
            raise Exception('Already setup')

        cls.im_root = os.getuid() == 0
        cls.fail_on_missing_backend = fail_on_missing_backend
        cls.project_id = project_id
        cls.user_id = user_id
        cls.non_uuid_ids = non_uuid_ids

        cls.set_persistence(persistence_config)
        cls._set_cinder_config(host, file_locks_path, cinder_config_params)

        serialization.setup(cls)

        cls._set_logging(disable_logs)
        cls._set_priv_helper(root_helper)
        coordination.COORDINATOR.start()

        if suppress_requests_ssl_warnings:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            urllib3.disable_warnings(
                urllib3.exceptions.InsecurePlatformWarning)

        cls.global_initialization = True
        cls.output_all_backend_info = output_all_backend_info

    def _apply_backend_workarounds(self, config):
        """Apply workarounds for drivers that do bad stuff."""
        if 'netapp' in config.volume_driver:
            # Workaround NetApp's weird replication stuff that makes it reload
            # config sections in get_backend_configuration.  OK since we don't
            # support replication.
            cfg.CONF.list_all_sections = lambda: config.volume_backend_name

    @classmethod
    def _set_logging(cls, disable_logs):
        if disable_logs:
            logging.Logger.disabled = property(lambda s: True,
                                               lambda s, x: None)
            return

        oslo_logging.setup(cfg.CONF, 'cinder')
        logging.captureWarnings(True)

    @classmethod
    def _set_priv_helper(cls, root_helper):
        # If we are using a virtual environment then the rootwrap config files
        # Should be within the environment and not under /etc/cinder/
        venv = os.environ.get('VIRTUAL_ENV')
        if (venv and not cfg.CONF.rootwrap_config.startswith(venv) and
                not os.path.exists(cfg.CONF.rootwrap_config)):

            # We need to remove the absolute path (initial '/') to generate the
            # config path under the virtualenv
            # for the join to work.
            wrap_path = cfg.CONF.rootwrap_config[1:]
            venv_wrap_file = os.path.join(venv, wrap_path)
            venv_wrap_dir = os.path.dirname(venv_wrap_file)

            # In virtual environments our rootwrap config file is no longer
            # '/etc/cinder/rootwrap.conf'.  We have 2 possible roots,  it's
            # either the virtualenv's directory or our where our sources are if
            # we have installed cinder as editable.

            # For editable we need to copy the files into the virtualenv if we
            # haven't copied them before.
            if not utils.__file__.startswith(venv):
                # If we haven't copied the files yet
                if not os.path.exists(venv_wrap_file):
                    editable_link = glob.glob(os.path.join(
                        venv, 'lib/python*/site-packages/cinder.egg-link'))
                    with open(editable_link[0], 'r') as f:
                        cinder_source_path = f.read().split('\n')[0]
                    cinder_source_etc = os.path.join(cinder_source_path,
                                                     'etc/cinder')

                    shutil.copytree(cinder_source_etc, venv_wrap_dir)

            # For venvs we need to update configured filters_path and exec_dirs
            parser = configparser.ConfigParser()
            parser.read(venv_wrap_file)
            # Change contents if we haven't done it already
            if not parser['DEFAULT']['filters_path'].startswith(venv_wrap_dir):
                parser['DEFAULT']['filters_path'] = os.path.join(venv_wrap_dir,
                                                                 'rootwrap.d')
                parser['DEFAULT']['exec_dirs'] = (
                    os.path.join(venv, 'bin,') +
                    parser['DEFAULT']['exec_dirs'])

                with open(venv_wrap_file, 'w') as f:
                    parser.write(f)

            # Don't use set_override because it doesn't work as it should
            cfg.CONF.rootwrap_config = venv_wrap_file

        # The default Cinder roothelper in Cinder and privsep is sudo, so
        # nothing to do in those cases.
        if root_helper != 'sudo':
            # Get the current helper (usually 'sudo cinder-rootwrap
            # <CONF.rootwrap_config>') and replace the sudo part
            original_helper = utils.get_root_helper()

            # If we haven't already set the helper
            if root_helper not in original_helper:
                new_helper = original_helper.replace('sudo', root_helper)
                utils.get_root_helper = lambda: new_helper

                # Initialize privsep's context to not use 'sudo'
                priv_context.init(root_helper=[root_helper])

        # When using privsep from the system we need to replace the
        # privsep-helper with our own to use the virtual env libraries.
        if venv and not priv_context.__file__.startswith(venv):
            # Use importlib.resources to support PEP 302-based import hooks
            # Can only use importlib.resources on 3.10 because it was added to
            # 3.7, but files to 3.9 and namespace packages only to 3.10
            import sys
            if sys.version_info[:2] >= (3, 10):
                from importlib.resources import files
            else:
                from importlib_resources import files
            privhelper = files('cinderlib.bin').joinpath('venv-privsep-helper')
            cmd = f'{root_helper} {privhelper}'

            # Change default of the option instead of the value of the
            # different contexts
            for opt in priv_context.OPTS:
                if opt.name == 'helper_command':
                    opt.default = cmd
                    break

        # Don't use server/client mode when running as root
        client_mode = not cls.im_root
        cinder.privsep.sys_admin_pctxt.set_client_mode(client_mode)
        os_brick.privileged.default.set_client_mode(client_mode)

    @property
    def config(self):
        if self.output_all_backend_info:
            return self._driver_cfg
        return {'volume_backend_name': self._driver_cfg['volume_backend_name']}

    def _serialize(self, property_name):
        result = [getattr(volume, property_name) for volume in self.volumes]
        # We only need to output the full backend configuration once
        if self.output_all_backend_info:
            backend = {'volume_backend_name': self.id}
            for volume in result:
                volume['backend'] = backend
        return {'class': type(self).__name__,
                'backend': self.config,
                'volumes': result}

    @property
    def json(self):
        return self._serialize('json')

    @property
    def dump(self):
        return self._serialize('dump')

    @property
    def jsons(self):
        return json_lib.dumps(self.json)

    @property
    def dumps(self):
        return json_lib.dumps(self.dump)

    @classmethod
    def load(cls, json_src, save=False):
        backend = Backend.load_backend(json_src['backend'])
        volumes = json_src.get('volumes')
        if volumes:
            backend._volumes = [objects.Volume.load(v, save) for v in volumes]
        return backend

    @classmethod
    def load_backend(cls, backend_data):
        backend_name = backend_data['volume_backend_name']
        if backend_name in cls.backends:
            return cls.backends[backend_name]

        if len(backend_data) > 1:
            return cls(**backend_data)

        if cls.fail_on_missing_backend:
            raise Exception('Backend not present in system or json.')

        return backend_name

    def refresh(self):
        if self._volumes is not None:
            self._volumes = None
            self.volumes

    @staticmethod
    def list_supported_drivers(output_version=1):
        """Returns dictionary with driver classes names as keys.

        The output of the method changes from version to version, so we can
        pass the output_version parameter to specify which version we are
        expecting.

        Version 1: Original output intended for human consumption, where all
                   dictionary values are strings.
        Version 2: Improved version intended for automated consumption.
                   - type is now a dictionary with detailed information
                   - Values retain their types, so we'll no longer get 'None'
                      or 'False'.
        """
        def get_vars(obj):
            return {k: v for k, v in vars(obj).items()
                    if not k.startswith('_')}

        def get_strs(obj):
            return {k: str(v) for k, v in vars(obj).items()
                    if not k.startswith('_')}

        def convert_oslo_config(oslo_option, output_version):
            if output_version != 2:
                return get_strs(oslo_option)

            res = get_vars(oslo_option)
            type_class = res['type']
            res['type'] = get_vars(oslo_option.type)
            res['type']['type_class'] = type_class
            return res

        def fix_cinderlib_options(driver_dict, output_version):
            # The rbd_keyring_conf option is deprecated and will be removed for
            # Cinder, because it's a security vulnerability there (OSSN-0085),
            # but it isn't for cinderlib, since the user of the library already
            # has access to all the credentials, and cinderlib needs it to work
            # with RBD, so we need to make sure that the config option is
            # there whether it's reported as deprecated or removed from Cinder.
            RBD_KEYRING_CONF = cfg.StrOpt('rbd_keyring_conf',
                                          default='',
                                          help='Path to the ceph keyring file')

            if driver_dict['class_name'] != 'RBDDriver':
                return
            rbd_opt = convert_oslo_config(RBD_KEYRING_CONF, output_version)
            for opt in driver_dict['driver_options']:
                if opt['dest'] == 'rbd_keyring_conf':
                    opt.clear()
                    opt.update(rbd_opt)
                    break
            else:
                driver_dict['driver_options'].append(rbd_opt)

        def list_drivers(queue, output_version):
            cwd = os.getcwd()
            # Go to the parent directory directory where Cinder is installed
            os.chdir(utils.__file__.rsplit(os.sep, 2)[0])
            try:
                drivers = cinder_interface_util.get_volume_drivers()
                mapping = {d.class_name: vars(d) for d in drivers}
                for driver in mapping.values():
                    driver.pop('cls', None)
                    if 'driver_options' in driver:
                        driver['driver_options'] = [
                            convert_oslo_config(opt, output_version)
                            for opt in driver['driver_options']
                        ]
                        fix_cinderlib_options(driver, output_version)
            finally:
                os.chdir(cwd)
            queue.put(mapping)

        if not (1 <= output_version <= 2):
            raise ValueError('Acceptable versions are 1 and 2')

        # Use a different process to avoid having all driver classes loaded in
        # memory during our execution.
        queue = multiprocessing.Queue()
        p = multiprocessing.Process(target=list_drivers,
                                    args=(queue, output_version))
        p.start()
        result = queue.get()
        p.join()
        return result


setup = Backend.global_setup
# Used by serialization.load
objects.Backend = Backend
# Needed if we use serialization.load before initializing cinderlib
objects.Object.backend_class = Backend

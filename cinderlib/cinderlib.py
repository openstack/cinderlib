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

from __future__ import absolute_import
import json as json_lib
import logging
import multiprocessing
import os

from cinder import coordination
from cinder.db import api as db_api
from cinder import objects as cinder_objects

# We need this here until we remove from cinder/volume/manager.py:
# VA_LIST = objects.VolumeAttachmentList
cinder_objects.register_all()  # noqa

from cinder.interface import util as cinder_interface_util
from cinder import utils
from cinder.volume import configuration
from cinder.volume import manager  # noqa We need to import config options
from oslo_config import cfg
from oslo_log import log as oslo_logging
from oslo_utils import importutils
import urllib3

import cinderlib
from cinderlib import nos_brick
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

    def __init__(self, volume_backend_name, **driver_cfg):
        if not self.global_initialization:
            self.global_setup()
        driver_cfg['volume_backend_name'] = volume_backend_name
        Backend.backends[volume_backend_name] = self

        conf = self._get_backend_config(driver_cfg)
        self._apply_backend_workarounds(conf)
        self.driver = importutils.import_object(
            conf.volume_driver,
            configuration=conf,
            db=self.persistence.db,
            host='%s@%s' % (cfg.CONF.host, volume_backend_name),
            cluster_name=None,  # We don't use cfg.CONF.cluster for now
            active_backend_id=None)  # No failover for now
        self.driver.do_setup(objects.CONTEXT)
        self.driver.check_for_setup_error()

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

        cls._validate_options(cinder_config_params)
        for k, v in cinder_config_params.items():
            setattr(cfg.CONF, k, v)

        # Replace command line arg parser so we ignore caller's args
        cfg._CachedArgumentParser.parse_args = lambda *a, **kw: None

    @classmethod
    def _validate_options(cls, kvs, group=None):
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
                # for correctness, don't leave it there
                cfg.CONF.clear_override(k, group)
            except cfg.NoSuchOptError:
                # Don't fail on unknown variables, behave like cinder
                LOG.warning('Unknown config option %s', k)

    def _get_backend_config(self, driver_cfg):
        # Create the group for the backend
        backend_name = driver_cfg['volume_backend_name']
        cfg.CONF.register_group(cfg.OptGroup(backend_name))

        # Validate and set config options
        backend_group = getattr(cfg.CONF, backend_name)
        self._validate_options(driver_cfg)
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

        cls.fail_on_missing_backend = fail_on_missing_backend
        cls.root_helper = root_helper
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
        utils.get_root_helper = lambda: root_helper
        nos_brick.init(root_helper)

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
    def list_supported_drivers():
        """Returns dictionary with driver classes names as keys."""

        def convert_oslo_config(oslo_options):
            options = []
            for opt in oslo_options:
                tmp_dict = {k: str(v) for k, v in vars(opt).items()
                            if not k.startswith('_')}
                options.append(tmp_dict)
            return options

        def list_drivers(queue):
            cwd = os.getcwd()
            # Go to the parent directory directory where Cinder is installed
            os.chdir(utils.__file__.rsplit(os.sep, 2)[0])
            try:
                drivers = cinder_interface_util.get_volume_drivers()
                mapping = {d.class_name: vars(d) for d in drivers}
                # Drivers contain class instances which are not serializable
                for driver in mapping.values():
                    driver.pop('cls', None)
                    if 'driver_options' in driver:
                        driver['driver_options'] = convert_oslo_config(
                            driver['driver_options'])
            finally:
                os.chdir(cwd)
            queue.put(mapping)

        # Use a different process to avoid having all driver classes loaded in
        # memory during our execution.
        queue = multiprocessing.Queue()
        p = multiprocessing.Process(target=list_drivers, args=(queue,))
        p.start()
        result = queue.get()
        p.join()
        return result


setup = Backend.global_setup
# Used by serialization.load
objects.Backend = Backend
# Needed if we use serialization.load before initializing cinderlib
objects.Object.backend_class = Backend

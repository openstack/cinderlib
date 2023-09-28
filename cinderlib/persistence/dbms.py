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

import logging

import alembic.script.revision
import alembic.util.exc
from cinder.db import api as db_api
from cinder.db import migration
from cinder.db.sqlalchemy import api as sqla_api
from cinder.db.sqlalchemy import models
from cinder import exception as cinder_exception
from cinder import objects as cinder_objs
from oslo_config import cfg
from oslo_db import exception
from oslo_db.sqlalchemy import models as oslo_db_models
from oslo_log import log
import sqlalchemy as sa

from cinderlib import objects
from cinderlib.persistence import base as persistence_base

LOG = log.getLogger(__name__)


def db_writer(func):
    """Decorator to start a DB writing transaction.

    With the new Oslo DB Transaction Sessions everything needs to use the
    sessions of the enginefacade using the function decorator or the context
    manager approach: https://docs.openstack.org/oslo.db/ocata/usage.html

    This plugin cannot use the decorator form because its fuctions don't
    receive a Context objects that the decorator can find and use, so we use
    this decorator instead.

    Cinder DB API methods already have a decorator, so methods calling them
    don't require this decorator, but methods that directly call the DB using
    sqlalchemy or using the model_query method do.

    Using this decorator at this level also allows us to enclose everything in
    a single transaction, and it doesn't have any problems with the existing
    Cinder decorators.
    """
    def wrapper(*args, **kwargs):
        with sqla_api.main_context_manager.writer.using(objects.CONTEXT):
            return func(*args, **kwargs)
    return wrapper


class KeyValue(models.BASE, oslo_db_models.ModelBase, objects.KeyValue):
    __tablename__ = 'cinderlib_persistence_key_value'
    key = sa.Column(sa.String(255), primary_key=True)
    value = sa.Column(sa.Text)


class DBPersistence(persistence_base.PersistenceDriverBase):
    GET_METHODS_PER_DB_MODEL = {
        cinder_objs.VolumeType.model: 'volume_type_get',
        cinder_objs.QualityOfServiceSpecs.model: 'qos_specs_get',
    }

    def __init__(self, connection, sqlite_synchronous=True,
                 soft_deletes=False):
        self.soft_deletes = soft_deletes
        cfg.CONF.set_override('connection', connection, 'database')
        cfg.CONF.set_override('sqlite_synchronous',
                              sqlite_synchronous,
                              'database')

        # Suppress logging for alembic
        alembic_logger = logging.getLogger('alembic.runtime.migration')
        alembic_logger.setLevel(logging.WARNING)

        self._clear_facade()
        self.db_instance = db_api.oslo_db_api.DBAPI.from_config(
            conf=cfg.CONF, backend_mapping=db_api._BACKEND_MAPPING,
            lazy=True)

        # We need to wrap some get methods that get called before the volume is
        # actually created.
        self.original_vol_type_get = self.db_instance.volume_type_get
        self.db_instance.volume_type_get = self.vol_type_get
        self.original_qos_specs_get = self.db_instance.qos_specs_get
        self.db_instance.qos_specs_get = self.qos_specs_get
        self.original_get_by_id = self.db_instance.get_by_id
        self.db_instance.get_by_id = self.get_by_id

        try:
            migration.db_sync()
        except alembic.util.exc.CommandError as exc:
            # We can be running 2 Cinder versions at the same time on the same
            # DB while we upgrade, so we must ignore the fact that the DB is
            # now on a newer version.
            if not isinstance(
                exc.__cause__, alembic.script.revision.ResolutionError,
            ):
                raise

        self._create_key_value_table()

        # NOTE : At this point, the persistence isn't ready so we need to use
        # db_instance instead of sqlalchemy API or DB API.
        orm_obj = self.db_instance.volume_type_get_by_name(objects.CONTEXT,
                                                           '__DEFAULT__')
        cls = cinder_objs.VolumeType
        expected_attrs = cls._get_expected_attrs(objects.CONTEXT)
        self.DEFAULT_TYPE = cls._from_db_object(
            objects.CONTEXT, cls(objects.CONTEXT), orm_obj,
            expected_attrs=expected_attrs)
        super(DBPersistence, self).__init__()

    def vol_type_get(self, context, id, inactive=False,
                     expected_fields=None):
        if id not in objects.Backend._volumes_inflight:
            return self.original_vol_type_get(context, id, inactive)

        vol = objects.Backend._volumes_inflight[id]._ovo
        if not vol.volume_type_id:
            return None
        return persistence_base.vol_type_to_dict(vol.volume_type)

    def qos_specs_get(self, context, qos_specs_id, inactive=False):
        if qos_specs_id not in objects.Backend._volumes_inflight:
            return self.original_qos_specs_get(context, qos_specs_id, inactive)

        vol = objects.Backend._volumes_inflight[qos_specs_id]._ovo
        if not vol.volume_type_id:
            return None
        return persistence_base.vol_type_to_dict(vol.volume_type)['qos_specs']

    def get_by_id(self, context, model, id, *args, **kwargs):
        if model not in self.GET_METHODS_PER_DB_MODEL:
            return self.original_get_by_id(context, model, id, *args, **kwargs)
        method = getattr(self, self.GET_METHODS_PER_DB_MODEL[model])
        return method(context, id)

    def _clear_facade(self):
        # This is for Pike
        if hasattr(sqla_api, '_FACADE'):
            sqla_api._FACADE = None
        # This is for Queens or later
        elif hasattr(sqla_api, 'main_context_manager'):
            sqla_api.main_context_manager.configure(**dict(cfg.CONF.database))

    def _create_key_value_table(self):
        models.BASE.metadata.create_all(sqla_api.get_engine(),
                                        tables=[KeyValue.__table__])

    @property
    def db(self):
        return self.db_instance

    @staticmethod
    def _build_filter(**kwargs):
        return {key: value for key, value in kwargs.items() if value}

    def get_volumes(self, volume_id=None, volume_name=None, backend_name=None):
        # Use the % wildcard to ignore the host name on the backend_name search
        host = '%@' + backend_name if backend_name else None
        filters = self._build_filter(id=volume_id, display_name=volume_name,
                                     host=host)
        LOG.debug('get_volumes for %s', filters)
        ovos = cinder_objs.VolumeList.get_all(objects.CONTEXT, filters=filters)
        result = []
        for ovo in ovos:
            backend = ovo.host.split('@')[-1].split('#')[0]

            # Trigger lazy loading of specs
            if ovo.volume_type_id:
                ovo.volume_type.extra_specs
                ovo.volume_type.qos_specs

            result.append(objects.Volume(backend, __ovo=ovo))

        return result

    def get_snapshots(self, snapshot_id=None, snapshot_name=None,
                      volume_id=None):
        filters = self._build_filter(id=snapshot_id, volume_id=volume_id,
                                     display_name=snapshot_name)
        LOG.debug('get_snapshots for %s', filters)
        ovos = cinder_objs.SnapshotList.get_all(objects.CONTEXT,
                                                filters=filters)
        result = [objects.Snapshot(None, __ovo=ovo) for ovo in ovos.objects]
        return result

    def get_connections(self, connection_id=None, volume_id=None):
        filters = self._build_filter(id=connection_id, volume_id=volume_id)
        LOG.debug('get_connections for %s', filters)
        ovos = cinder_objs.VolumeAttachmentList.get_all(objects.CONTEXT,
                                                        filters)
        # Leverage lazy loading of the volume and backend in Connection
        result = [objects.Connection(None, volume=None, __ovo=ovo)
                  for ovo in ovos.objects]
        return result

    def _get_kv(self, session, key=None):
        query = session.query(KeyValue)
        if key is not None:
            query = query.filter_by(key=key)
        res = query.all()
        # If we want to use the result as an ORM
        if session:
            return res
        return [objects.KeyValue(r.key, r.value) for r in res]

    def get_key_values(self, key=None):
        with sqla_api.main_context_manager.reader.using(objects.CONTEXT) as s:
            return self._get_kv(s, key)

    @db_writer
    def set_volume(self, volume):
        changed = self.get_changed_fields(volume)
        if not changed:
            changed = self.get_fields(volume)

        extra_specs = changed.pop('extra_specs', None)
        qos_specs = changed.pop('qos_specs', None)

        # Since OVOs are not tracking QoS or Extra specs dictionary changes,
        # we only support setting QoS or Extra specs on creation or add them
        # later.
        vol_type_id = changed.get('volume_type_id')
        if vol_type_id == self.DEFAULT_TYPE.id:
            if extra_specs or qos_specs:
                raise cinder_exception.VolumeTypeUpdateFailed(
                    id=self.DEFAULT_TYPE.name)
        elif vol_type_id:
            vol_type_fields = {'id': volume.volume_type_id,
                               'name': volume.volume_type_id,
                               'extra_specs': extra_specs,
                               'is_public': True}
            if qos_specs:
                res = self.db.qos_specs_create(objects.CONTEXT,
                                               {'name': volume.volume_type_id,
                                                'consumer': 'back-end',
                                                'specs': qos_specs})
                # Cinder is automatically generating an ID, replace it
                query = sqla_api.model_query(objects.CONTEXT,
                                             models.QualityOfServiceSpecs)
                query.filter_by(id=res['id']).update(
                    {'id': volume.volume_type.qos_specs_id})

            self.db.volume_type_create(objects.CONTEXT, vol_type_fields)
        else:
            if extra_specs is not None:
                self.db.volume_type_extra_specs_update_or_create(
                    objects.CONTEXT, volume.volume_type_id, extra_specs)

                self.db.qos_specs_update(objects.CONTEXT,
                                         volume.volume_type.qos_specs_id,
                                         {'name': volume.volume_type_id,
                                          'consumer': 'back-end',
                                          'specs': qos_specs})
            else:
                volume._ovo.volume_type = self.DEFAULT_TYPE
                volume._ovo.volume_type_id = self.DEFAULT_TYPE.id
                changed['volume_type_id'] = self.DEFAULT_TYPE.id

        # Create the volume
        if 'id' in changed:
            LOG.debug('set_volume creating %s', changed)
            try:
                self.db.volume_create(objects.CONTEXT, changed)
                changed = None
            except exception.DBDuplicateEntry:
                del changed['id']

        if changed:
            LOG.debug('set_volume updating %s', changed)
            self.db.volume_update(objects.CONTEXT, volume.id, changed)
        super(DBPersistence, self).set_volume(volume)

    @db_writer
    def set_snapshot(self, snapshot):
        changed = self.get_changed_fields(snapshot)
        if not changed:
            changed = self.get_fields(snapshot)

        # Create
        if 'id' in changed:
            LOG.debug('set_snapshot creating %s', changed)
            try:
                self.db.snapshot_create(objects.CONTEXT, changed)
                changed = None
            except exception.DBDuplicateEntry:
                del changed['id']

        if changed:
            LOG.debug('set_snapshot updating %s', changed)
            self.db.snapshot_update(objects.CONTEXT, snapshot.id, changed)
        super(DBPersistence, self).set_snapshot(snapshot)

    @db_writer
    def set_connection(self, connection):
        changed = self.get_changed_fields(connection)
        if not changed:
            changed = self.get_fields(connection)

        if 'connection_info' in changed:
            connection._convert_connection_info_to_db_format(changed)

        if 'connector' in changed:
            connection._convert_connector_to_db_format(changed)

        # Create
        if 'id' in changed:
            LOG.debug('set_connection creating %s', changed)
            try:
                sqla_api.volume_attach(objects.CONTEXT, changed)
                changed = None
            except exception.DBDuplicateEntry:
                del changed['id']

        if changed:
            LOG.debug('set_connection updating %s', changed)
            self.db.volume_attachment_update(objects.CONTEXT, connection.id,
                                             changed)
        super(DBPersistence, self).set_connection(connection)

    @db_writer
    def set_key_value(self, key_value):
        session = objects.CONTEXT.session
        kv = self._get_kv(session, key_value.key)
        kv = kv[0] if kv else KeyValue(key=key_value.key)
        kv.value = key_value.value
        session.add(kv)

    @db_writer
    def delete_volume(self, volume):
        delete_type = (volume.volume_type_id != self.DEFAULT_TYPE.id
                       and volume.volume_type_id)
        if self.soft_deletes:
            LOG.debug('soft deleting volume %s', volume.id)
            self.db.volume_destroy(objects.CONTEXT, volume.id)
            if delete_type:
                LOG.debug('soft deleting volume type %s',
                          volume.volume_type_id)
                self.db.volume_destroy(objects.CONTEXT, volume.volume_type_id)
                if volume.volume_type.qos_specs_id:
                    self.db.qos_specs_delete(objects.CONTEXT,
                                             volume.volume_type.qos_specs_id)
        else:
            LOG.debug('hard deleting volume %s', volume.id)
            for model in (models.VolumeMetadata, models.VolumeAdminMetadata):
                query = sqla_api.model_query(objects.CONTEXT, model)
                query.filter_by(volume_id=volume.id).delete()

            query = sqla_api.model_query(objects.CONTEXT, models.Volume)
            query.filter_by(id=volume.id).delete()
            if delete_type:
                LOG.debug('hard deleting volume type %s',
                          volume.volume_type_id)
                query = sqla_api.model_query(objects.CONTEXT,
                                             models.VolumeTypeExtraSpecs)
                query.filter_by(volume_type_id=volume.volume_type_id).delete()

                query = sqla_api.model_query(objects.CONTEXT,
                                             models.VolumeType)
                query.filter_by(id=volume.volume_type_id).delete()

                query = sqla_api.model_query(objects.CONTEXT,
                                             models.QualityOfServiceSpecs)
                qos_id = volume.volume_type.qos_specs_id
                if qos_id:
                    query.filter(sqla_api.or_(
                        models.QualityOfServiceSpecs.id == qos_id,
                        models.QualityOfServiceSpecs.specs_id == qos_id
                    )).delete()
        super(DBPersistence, self).delete_volume(volume)

    @db_writer
    def delete_snapshot(self, snapshot):
        if self.soft_deletes:
            LOG.debug('soft deleting snapshot %s', snapshot.id)
            self.db.snapshot_destroy(objects.CONTEXT, snapshot.id)
        else:
            LOG.debug('hard deleting snapshot %s', snapshot.id)
            query = sqla_api.model_query(objects.CONTEXT, models.Snapshot)
            query.filter_by(id=snapshot.id).delete()
        super(DBPersistence, self).delete_snapshot(snapshot)

    @db_writer
    def delete_connection(self, connection):
        if self.soft_deletes:
            LOG.debug('soft deleting connection %s', connection.id)
            self.db.attachment_destroy(objects.CONTEXT, connection.id)
        else:
            LOG.debug('hard deleting connection %s', connection.id)
            query = sqla_api.model_query(objects.CONTEXT,
                                         models.VolumeAttachment)
            query.filter_by(id=connection.id).delete()
        super(DBPersistence, self).delete_connection(connection)

    @db_writer
    def delete_key_value(self, key_value):
        session = objects.CONTEXT.session
        query = session.query(KeyValue)
        query.filter_by(key=key_value.key).delete()


class MemoryDBPersistence(DBPersistence):
    def __init__(self):
        super(MemoryDBPersistence, self).__init__(connection='sqlite://')

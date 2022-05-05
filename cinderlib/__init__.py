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

try:
    # For python 3.8 and later
    import importlib.metadata as importlib_metadata
except ImportError:
    # For everyone else
    import importlib_metadata

from os_brick.initiator import connector

from cinderlib import _fake_packages  # noqa F401
from cinderlib import cinderlib
from cinderlib import objects
from cinderlib import serialization

try:
    __version__ = importlib_metadata.version('cinderlib')
except importlib_metadata.PackageNotFoundError:
    __version__ = '0.0.0'

DEFAULT_PROJECT_ID = objects.DEFAULT_PROJECT_ID
DEFAULT_USER_ID = objects.DEFAULT_USER_ID
Volume = objects.Volume
Snapshot = objects.Snapshot
Connection = objects.Connection
KeyValue = objects.KeyValue

load = serialization.load
json = serialization.json
jsons = serialization.jsons
dump = serialization.dump
dumps = serialization.dumps

setup = cinderlib.setup
Backend = cinderlib.Backend

# This gets reassigned on initialization by nos_brick.init
get_connector_properties = connector.get_connector_properties
list_supported_drivers = cinderlib.Backend.list_supported_drivers

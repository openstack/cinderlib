# Copyright (c) 2019, Red Hat, Inc.
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
"""Fake unnecessary packages

There are many packages that are automatically imported when loading cinder
modules, and are used for normal Cinder operation, but they are not necessary
for cinderlib's execution.  One example of this happening is when cinderlib
loads a module to get configuration options but won't execute any of the code
present in that module.

This module fakes these packages providing the following benefits:

- Faster load times
- Reduced memory footprint
- Distributions can create a cinderlib package with fewer dependencies.
"""
try:
    # Only present and needed in Python >= 3.4
    from importlib import machinery
except ImportError:
    pass
import logging
import sys
import types

from oslo_config import cfg


__all__ = ['faker']
PACKAGES = [
    'glanceclient', 'novaclient', 'swiftclient', 'barbicanclient', 'cursive',
    'keystoneauth1', 'keystonemiddleware', 'keystoneclient', 'castellan',
    'oslo_reports', 'oslo_policy', 'oslo_messaging', 'osprofiler', 'paste',
    'oslo_middleware', 'webob', 'pyparsing', 'routes', 'jsonschema', 'os_win',
    'oauth2client', 'oslo_upgradecheck', 'googleapiclient', 'pastedeploy',
]
_DECORATOR_CLASSES = (types.FunctionType, types.MethodType)
LOG = logging.getLogger(__name__)


class _FakeObject(object):
    """Generic fake object: Iterable, Class, decorator, etc."""
    def __init__(self, *args, **kwargs):
        self.__key_value__ = {}

    def __len__(self):
        return len(self.__key_value__)

    def __contains__(self, key):
        return key in self.__key_value__

    def __iter__(self):
        return iter(self.__key_value__)

    def __mro_entries__(self, bases):
        return (self.__class__,)

    def __setitem__(self, key, value):
        self.__key_value__[key] = value

    def _new_instance(self, class_name):
        attrs = {'__module__': self.__module__ + '.' + self.__class__.__name__}
        return type(class_name, (self.__class__,), attrs)()

    # No need to define __class_getitem__, as __getitem__ has the priority
    def __getitem__(self, key):
        if key in self.__key_value__.get:
            return self.__key_value__.get[key]
        return self._new_instance(key)

    def __getattr__(self, key):
        return self._new_instance(key)

    def __call__(self, *args, **kw):
        # If we are a decorator return the method that we are decorating
        if args and isinstance(args[0], _DECORATOR_CLASSES):
            return args[0]
        return self

    def __repr__(self):
        return self.__qualname__


class Faker(object):
    """Fake Finder and Loader for whole packages."""
    def __init__(self, packages):
        self.faked_modules = []
        self.packages = packages

    def _fake_module(self, name):
        """Dynamically create a module as close as possible to a real one."""
        LOG.debug('Faking %s', name)
        attributes = {
            '__doc__': None,
            '__name__': name,
            '__file__': name,
            '__loader__': self,
            '__builtins__': __builtins__,
            '__package__': name.rsplit('.', 1)[0] if '.' in name else None,
            '__repr__': lambda self: self.__name__,
            '__getattr__': lambda self, name: (
                type(name, (_FakeObject,), {'__module__': self.__name__})()),
        }

        keys = ['__doc__', '__name__', '__file__', '__builtins__',
                '__package__']

        # Path only present at the package level
        if '.' not in name:
            attributes['__path__'] = [name]
            keys.append('__path__')

        # We only want to show some of our attributes
        attributes.update(__dict__={k: attributes[k] for k in keys},
                          __dir__=lambda self: keys)

        # Create the class and instantiate it
        module_class = type(name, (types.ModuleType,), attributes)
        self.faked_modules.append(name)
        return module_class(name)

    def find_module(self, fullname, path=None):
        """Find a module and return a Loader if it's one of ours or None."""
        package = fullname.split('.')[0]
        # If it's one of ours, then we are the loader
        if package in self.packages:
            return self
        return None

    def load_module(self, fullname):
        """Create a new Fake module if it's not already present."""
        if fullname in sys.modules:
            return sys.modules[fullname]

        sys.modules[fullname] = self._fake_module(fullname)
        return sys.modules[fullname]

    def find_spec(self, fullname, path=None, target=None):
        """Return our spec it it's one of our packages or None."""
        if self.find_module(fullname):
            return machinery.ModuleSpec(fullname,
                                        self,
                                        is_package='.' not in fullname)
        return None

    def create_module(self, spec):
        """Fake a module."""
        return self._fake_module(spec.name)


# cinder.quota_utils manually imports keystone_authtoken config group, so we
# create a fake one to avoid failure.
cfg.CONF.register_opts([cfg.StrOpt('fake')], group='keystone_authtoken')

# Create faker and add it to the list of Finders
faker = Faker(PACKAGES)
sys.meta_path.insert(0, faker)

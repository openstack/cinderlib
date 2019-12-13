Run cinderlib tests

**Role Variables**

.. zuul:rolevar:: cinderlib_base_dir
   :default: /opt/stack/cinderlib

   The cinderlib base directory.

.. zuul:rolevar:: cinderlib_config_file
   :default: /etc/cinder/cinder.conf

   The cinder configuration file used by the tests.

.. zuul:rolevar:: cinderlib_envlist
   :default: functional

   The tox environment used to run the tests.

.. zuul:rolevar:: cinderlib_root_helper
   :default: sudo

   The command used by the tests to gain root capabilities.

.. zuul:rolevar:: cinderlib_pool_name
   :default: The first pool reported by the backend

   Pool name used to create volumes.

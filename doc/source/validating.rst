===================
Validating a driver
===================

This is a guide for *Cinder* driver maintainers to validate that their drivers
are fully supported by *cinderlib* and therefore by projects like Ember-CSI_
and oVirt_ that rely on it for storage backend management.

Validation steps include initial manual validation as well as automatic testing
at the gate as part of *Cinder*'s 3rd party CI jobs.

With DevStack
-------------

There are many ways we can install *cinderlib* for the initial validation
phase, such as using pip from master repositories or PyPi or using packaged
versions of the project, but the official recommendation is to use DevStack_.

We believe that, as a *Cinder* driver maintainer, you will be already familiar
with DevStack_ and know how to configure and use it to work with your storage
backend, so this will most likely be the easiest way for you to do an initial
validation of the driver.

*Cinderlib* has a `DevStack plugin`_ that automatically installs the library as
during the stacking process when running the ``./stach.sh`` script, so we will
be adding this plugin to our ``local.conf`` file.

To use *cinderlib*'s master code we will add the line ``enable_plugin cinderlib
https://git.openstack.org/openstack/cinderlib`` after the ``[[local|localrc]]``
header the in our normal ``local.conf`` file that already configures our
backend.  The result will look like this::

  [[local|localrc]]
  enable_plugin cinderlib https://opendev.org/openstack/cinderlib

After adding this we can proceed to run the ``stack.sh`` script.

Once the script has finished executing we will have *cinderlib* installed from
Git in our system and we will also have sample Python code of how to use our
backend in *cinderlib* using the same backend configuration that exists in our
``cinder.conf``.  The sample Python code is generated in file ``cinderlib.py``
in the same directory as our ``cinder.conf`` file.

The tool generating the ``cinderlib.py`` file supports ``cinder.conf`` files
with multiple backends, so there's no need to make any additional changes to
your ``local.conf`` if you usually deploy DevStack_ with multiple backends.

The generation of the sample code runs at the very end of the stacking process
(the ``extra`` stage), so we can use other DevStack storage plugins, such as
the Ceph plugin, and the sample code will still be properly generated.

For the LVM default backend the contents of the ``cinderlib.py`` file are:

.. code-block:: shell

   $ cat /etc/cinder/cinderlib.py
   import cinderlib as cl

   lvmdriver_1 = cl.Backend(volume_clear="zero", lvm_type="auto",
                            volume_backend_name="lvmdriver-1",
                            target_helper="lioadm",
                            volume_driver="cinder.volume.drivers.lvm.LVMVolumeDriver",
                            image_volume_cache_enabled=True,
                            volume_group="stack-volumes-lvmdriver-1")

To confirm that this automatically generated configuration is correct we can
do:

.. code-block:: shell

   $ cd /etc/cinder
   $ mv cinderlib.py example.py
   $ python
   [GCC 4.8.5 20150623 (Red Hat 4.8.5-36)] on linux2
   Type "help", "copyright", "credits" or "license" for more information.
   >>> from pprint import pprint as pp
   >>> import cinderlib
   >>> pp(example.lvmdriver_1.stats())
   {'driver_version': '3.0.0',
    'pools': [{'QoS_support': False,
               'backend_state': 'up',
               'filter_function': None,
               'free_capacity_gb': 4.75,
               'goodness_function': None,
               'location_info': 'LVMVolumeDriver:localhost.localdomain:stack-volumes-lvmdriver-1:thin:0',
               'max_over_subscription_ratio': '20.0',
               'multiattach': True,
               'pool_name': 'lvmdriver-1',
               'provisioned_capacity_gb': 0.0,
               'reserved_percentage': 0,
               'thick_provisioning_support': False,
               'thin_provisioning_support': True,
               'total_capacity_gb': 4.75,
               'total_volumes': 1}],
    'shared_targets': False,
    'sparse_copy_volume': True,
    'storage_protocol': 'iSCSI',
    'vendor_name': 'Open Source',
    'volume_backend_name': 'lvmdriver-1'}
   >>>


Here the name of the variable is `lvmdriver_1`, but in your case the name will
be different, as it uses the ``volume_backend_name`` from the different driver
section in the ``cinder.conf`` file.  One way to see the backends that have
been initialized by importing the example code is looking into the
`example.cl.Backend.backends` dictionary.

Some people deploy DevStack_ with the default backend and then manually modify
the ``cinder.conf`` file afterwards and restart the *Cinder* services to use
their configuration.  This is fine as well, as you can easily recreate the
Python code to include you backend using the `cinder-cfg-to-cinderlib-code`
tool that's installed with *cinderlib*.

Generating the example code manually can be done like this::

  $ cinder-cfg-to-cinderlib-code /etc/cinder/cinder.conf example.py

Now that we know that *cinderlib* can access our backend we will proceed to run
*cinderlib*'s functional tests to confirm that all the operations work as
expected.

The functional tests use the contents of the existing
``/etc/cinder/cinder.conf`` file to get the backend configuration. The
functional test runner also supports ``cinder.conf`` files with multiple
backends.  Test methods have meaningful names ending in the backend name as per
the ``volume_backend_name`` values in the configuration file.

The functional tests are quite fast, as they usually take about 1 minute to
run:

.. code-block:: shell

   $ python -m unittest discover -v cinderlib.tests.functional

   test_attach_detach_volume_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_attach_detach_volume_via_attachment_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_attach_volume_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_clone_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_create_delete_snapshot_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_create_delete_volume_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_create_snapshot_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_create_volume_from_snapshot_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_create_volume_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_disk_io_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_extend_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_stats_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok
   test_stats_with_creation_on_lvmdriver-1 (cinderlib.tests.functional.test_basic.BackendFunctBasic) ... ok

   ----------------------------------------------------------------------
   Ran 13 tests in 54.179s

   OK

There are a couple of interesting options we can use when the running
functional tests using environmental variables:

- ``CL_FTEST_LOGGING``: If set it will enable the *Cinder* code to log to
  stdout during the testing.  Undefined by default, which means no output.

- ``CL_FTEST_PRECISION``: Integer value describing how much precision we must
  use when comparing volume sizes.  Due to cylinder sizes some storage arrays
  don't abide 100% to the requested size of the volume.  With this option we
  can define how many decimals will be correct when testing sizes.  A value of
  2 means that the backend could create a 1.0015869140625GB volume when we
  request a 1GB volume and the tests wouldn't fail.  Default is zero, which
  means that it must be perfect or it will fail.

- ``CL_FTEST_CFG```: Location of the configuration file. Defaults to
  ``/etc/cinder/cinder.conf``.

- ``CL_FTEST_POOL_NAME``: If our backend has multi-pool support and we have
  configured multiple pools we can use this parameter to define which pool to
  use for the functional tests.  If not defined it will use the first reported
  pool.

If we encounter problems while running the functional tests, but the *Cinder*
service is running just fine, we can go to the #openstack-cinder IRC channel in
OFTC, or send an email to the `discuss-openstack mailing list`_ starting
the subject with *[cinderlib]*.

Cinder 3rd party CI
-------------------

Once we have been able to successfully run the functional tests it's time to
make the CI jobs run them on every patch submitted to *Cinder* to ensure the
driver keeps being compatible.

There are multiples ways we can accomplish this:

1. Create a 3rd party CI job listening to *cinderlib* patches

2. Create an additional 3rd party CI job in *Cinder*, similar to the one we
   already have.

3. Reusing our existing 3rd party CI job making it also run the *cinderlib*
   functional tests.

Options #1 and #2 require more work, as we have to create new jobs, but they
make it easier to know that our driver is compatible with *cinderlib*.  Option
#3 is the opposite, it is easy to setup, but it doesn't make it so obvious that
our driver is supported by *cinderlib*.

Configuration
^^^^^^^^^^^^^

When reusing existing 3rd party CI jobs, the normal setup will generate a valid
configuration file on ``/etc/cinder/cinder.conf`` and *cinderlib* functional
tests will use it by default, so we don't have to do anything, but when running
a custom CI job we will have to write the configuration ourselves.  Though we
don't have to do this dynamically.  We can write it once and use it in all the
*cinderlib* jobs.

To get our backend configuration file for the functional tests we can:

- Use the ``cinder.conf`` file from one of your `DevStack`_ deployments.
- Manually create a minimal ``cinder.conf`` file.
- Create a custom YAML file.

We can create the minimal ``cinder.conf`` file using one generated by
`DevStack`_.  Having a minimal configuration has the advantage of being easy to
read.

For an LVM backend could look like this::

   [DEFAULT]
   enabled_backends = lvm

   [lvm]
   volume_clear = none
   target_helper = lioadm
   volume_group = cinder-volumes
   volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name = lvm

Besides the *INI* style configuration files, we can also use YAML configuration
files for the functional tests.

The YAML file has 3 key-value pairs that are of interest to us. Only one of
them is mandatory, the other 2 are optional.

- ``logs``: Boolean value defining whether we want the *Cinder* code to log to
  stdout during the testing.  Defaults to ``false``.  Takes precedence over
  environmental variable ``CL_TESTING_LOGGING``.

- `size_precision`: Integer value describing how much precision we must use
  when comparing volume sizes.  Due to cylinder sizes some storage arrays don't
  abide 100% to the requested size of the volume.  With this option we can
  define how many decimals will be correct when testing sizes.  A value of 2
  means that the backend could create a 1.0015869140625GB volume when we
  request a 1GB volume and the tests wouldn't fail.  Default is zero, which for
  us means that it must be perfect or it will fail.  Takes precedence over
  environmental variable ``CL_FTEST_PRECISION``.

- `backends`: This is a list of dictionaries, each with the configuration
  parameters that are set in the backend section of the ``cinder.conf`` file in
  *Cinder*.  This is a mandatory field.

The same configuration we presented for the LVM backend as a minimal
``cinder.conf`` file would look like this in the YAML format:

.. code-block:: yaml

   logs: false
   venv_sudo: false
   backends:
       - volume_backend_name: lvm
         volume_driver: cinder.volume.drivers.lvm.LVMVolumeDriver
         volume_group: cinder-volumes
         target_helper: lioadm
         volume_clear: none

To pass the location of the configuration file to the functional test runner we
must use the ``CL_FTEST_CFG`` environmental variable to point to the location
of our file.  If we are using a ``cinder.conf`` file and we save it in
``etc/cinder`` then we don't need to pass it to the tests runner, since that's
the default location.

Use independent job
^^^^^^^^^^^^^^^^^^^

Creating new jobs is mostly identical to `what you already did for the Cinder
job <https://docs.openstack.org/infra/system-config/third_party.html>`_ with
the difference that here we don't need to do a full DevStack_ installation, as
it would take too long.  We only need the *cinderlib*, *Cinder*, and *OS-Brick*
projects from master and then run *cinderlib*'s functional tests.

As an example here's the Ceph job in the *cinderlib* project that takes
approximately 8 minutes to run at the gate.  In the ``pre-run`` phase it starts
a Ceph demo container to run a Ceph toy cluster as the backend.  Then
provides a custom configuration YAML file with the backend configuration::

   - job:
       name: cinderlib-ceph-functional
       parent: openstack-tox-functional-with-sudo
       required-projects:
         - openstack/os-brick
         - openstack/cinder
       pre-run: playbooks/setup-ceph.yaml
       nodeset: ubuntu-bionic
       vars:
         tox_environment:
           CL_FTEST_CFG: "cinderlib/tests/functional/ceph.yaml"
           CL_FTEST_ROOT_HELPER: sudo
           # These come from great-great-grandparent tox job
           NOSE_WITH_HTML_OUTPUT: 1
           NOSE_HTML_OUT_FILE: nose_results.html
           NOSE_WITH_XUNIT: 1

For jobs in the *cinderlib* project you can use the
``openstack-tox-functional-with-sudo`` parent, but for jobs in the *Cinder*
project you'll have to call this yourself by calling tox or using the same
command we used during our manual testing:  ``python -m unittest discover -v
cinderlib.tests.functional``.

Use existing job
^^^^^^^^^^^^^^^^

The easiest way to run the *cinderlib* functional tests is to reuse an
existing *Cinder* CI job, since we don't need to setup anything.  We just need
to modify our job to run an additional command at the end.

Running the *cinderlib* functional tests after tempest will only add about 1
minute to the job's current runtime.

You will need to add ``openstack/cinderlib`` to the ``required-projects``
configuration of the Zuul job.  This will ensure not only that *cinderlib* is
installed, but also that is using the right patch when a patch has
cross-repository dependencies.

For example, the LVM lio job called ``cinder-tempest-dsvm-lvm-lio-barbican``
has the following required projects::

   required-projects:
     - openstack-infra/devstack-gate
     - openstack/barbican
     - openstack/cinderlib
     - openstack/python-barbicanclient
     - openstack/tempest
     - openstack/os-brick

To facilitate running the *cinderlib* functional tests in existing CI jobs the
*Cinder* project includes 2 playbooks:

- ``playbooks/tempest-and-cinderlib-run.yaml``
- ``playbooks/cinderlib-run.yaml``

These 2 playbooks support the ``cinderlib_ignore_errors`` boolean variable to
allow CI jobs to run the functional tests and ignore the results so that
*cinderlib* failures won't block patches.  You can think of it as running the
*cinderlib* tests as non voting.  We don't recommend setting it, as it would
defeat the purpose of running the jobs at the gate and the *cinderlib* tests
are very consistent and reliable and don't raise false failures.

Which one of these 2 playbook to use depends on how we are defining our CI job.
For example the LVM job uses the ``cinderlib-run.yaml`` job in it's `run.yaml
file
<http://git.openstack.org/cgit/openstack/cinder/tree/playbooks/legacy/cinder-tempest-dsvm-lvm-lio-barbican/run.yaml>`_,
and the Ceph job uses the ``tempest-and-cinderlib-run.yaml`` as its `run job
command <http://git.openstack.org/cgit/openstack/cinder/tree/.zuul.yaml>`_.

If you are running tempest tests using a custom script you can also add the
running of the *cinderlib* tests at the end.

Notes
-----

Additional features
^^^^^^^^^^^^^^^^^^^

The validation process we've discussed tests the basic functionality, but some
*Cinder* drivers have additional functionality such as backend QoS, multi-pool
support, and support for extra specs parameters that modify advanced volume
characteristics -such as compression, deduplication, and thin/thick
provisioning- on a per volume basis.

*Cinderlib* supports these features, but since they are driver specific, there
is no automated testing in *cinderlib*'s functional tests; but we can test them
manually ourselves using the ``extra_specs``, ``qos_specs`` and ``pool_name``
parameters in the ``create_volume`` and ``clone`` methods.

We can see the list of available pools in multi-pool drivers on the
``pool_names`` property in the Backend instance.

Configuration options
^^^^^^^^^^^^^^^^^^^^^

One of the difficulties in the *Cinder* project is determining which options
are valid for a specific driver on a specific release.  This is usually handled
by users checking the *OpenStack* or vendor documentation, which makes it
impossible to automate.

There was a recent addition to the *Cinder* driver interface that allowed
drivers to report exactly which configuration options were relevant for them
via the ``get_driver_options`` method.

On the initial patch some basic values were added to the drivers, but we urge
all driver maintainers to have a careful look at the values currently being
returned and make sure they are returning all relevant options, because this
will not only be useful for some *Cinder* installers, but also for projects
using *cinderlib*, as they will be able to automatically build GUIs to
configure backends and to validate provided parameters.  Having incorrect or
missing values there will result in undesired behavior in those systems.


Reporting results
-----------------

Once you have completed the process described in this guide you will have a
*Cinder* driver that is supported not only in *OpenStack*, but also by
*cinderlib* and its related projects, and it is time to make it visible.

For this you just need to submit a patch to the *cinderlib* project modifying
the ``doc/source/validated.rst`` file with the information from your backend.

The information that must be added to the documentation is:

- *Storage*: The make and model of the hardware used.
- *Versions*: Firmware versions used for the manual testing.
- *Connection type*: iSCSI, FC, RBD, etc.  Can add multiple types on the same
  line.
- *Requirements*: Required packages, Python libraries, configuration files,
  etc. for the driver to work.
- *Automated testing*: Accepted values are:

  - No
  - On *cinderlib* jobs.
  - On *cinder* jobs.
  - On *cinderlib* and *Cinder* jobs.

- *Notes*: Any additional information relevant for *cinderlib* usage.
- *Configuration*: The contents of the YAML file or the driver section in the
  ``cinder.conf``, with masked sensitive data.


.. _Ember-CSI: https://ember-csi.io
.. _oVirt: https://ovirt.org
.. _DevStack: https://docs.openstack.org/devstack
.. _DevStack plugin: http://git.openstack.org/cgit/openstack/cinderlib/tree/devstack
.. _discuss-openstack mailing list: http://lists.openstack.org/cgi-bin/mailman/listinfo/openstack-discuss

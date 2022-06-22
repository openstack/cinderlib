============================
So You Want to Contribute...
============================

For general information on contributing to OpenStack, please check out the
`contributor guide <https://docs.openstack.org/contributors/>`_ to get started.
It covers all the basics that are common to all OpenStack projects: the
accounts you need, the basics of interacting with our Gerrit review system, how
we communicate as a community, etc.

The cinderlib library is maintained by the OpenStack Cinder project.  To
understand our development process and how you can contribute to it, please
look at the Cinder project's general contributor's page:
http://docs.openstack.org/cinder/latest/contributor/contributing.html

Some cinderlib specific information is below.

cinderlib release model
-----------------------

The OpenStack release model for cinderlib is `cycle-with-intermediary
<https://releases.openstack.org/reference/release_models.html#cycle-with-intermediary>`__.
This means that there can be multiple full releases of cinderlib from master
during a development cycle.  The deliverable type of cinderlib is 'trailing'
which means that the final release of cinderlib for a development cycle must
occur within 3 months after the official OpenStack coordinated release.

At the time of the final release, the stable branch is cut, and cinderlib
releases from that branch follow the normal OpenStack stable release policy.

The primary thing to keep in mind here is that there is a period at the
beginning of each OpenStack development cycle (for example, Zed) when the
master branch in cinder and os-brick is open for Zed development, but
cinderlib's master branch is still being used for Yoga development.

cinderlib development model
---------------------------

Because cinderlib depends on cinder and os-brick, its ``tox.ini`` file is set
up to use cinder and os-brick from source (not from released versions)
so that changes in cinder and os-brick are immediately available for testing
cinderlib.

We follow this practice both for cinderlib master and for the cinderlib stable
branches.

cinderlib tox and zuul configuration maintenance
------------------------------------------------

As mentioned above, cinderlib's release schedule is offset from the OpenStack
coordinated release schedule by about 3 months.  Thus, once cinder and os-brick
have had their final release for a cycle, their master branches become the
development branch for the *next* cycle, whereas cinderlib's master branch is
still the development branch for the *previous* cycle.

This has an impact on both ``tox.ini``, which controls your local development
testing environment, and ``.zuul.yaml``, which controls cinderlib's CI
environment.  These files require manual maintenance at two points during
each OpenStack development cycle:

#. When the cinder (not cinderlib) master branch opens for n+1 cycle
   development.  This happens when the first release candidate for release
   n is made and the stable branch for release n is created.  At this time,
   cinderlib master is still being used for release n development, so cinderlib
   master is out of phase with cinder/os-brick master branch, and we must make
   adjustments to cinderlib master's ``tox.ini`` and ``.zuul.yaml`` files.

#. When the cinderlib release n is made, cinderlib master opens for release
   n+1 development.  Thus, cinderlib's master branch is back in phase with
   cinder/os-brick master branch, and  we must make adjustments to cinderlib
   master's ``tox.ini`` and ``.zuul.yaml`` files.

Although cinderlib's ``requirements.txt`` file is not used by tox (and hence
not by Zuul, either), we must maintain it for people who install cinderlib via
pypi.  Thus it must be checked for correctness before cinderlib is released.

Throughout this section, we'll be talking about release 'n' and release
'n+1'.  The example we'll use is 'n' is yoga and 'n+1' is zed.

cinderlib tox.ini maintenance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The items are listed below in the order you'll find them in ``tox.ini``.

[testenv]setenv
```````````````

The environment variable ``CINDERLIB_RELEASE`` must be set to the name of
the release that this is the development branch for.

* What is this used by?  It's used by ``tools/special_install.sh`` to figure
  out what the appropriate upper-constraints file is.

* When should it be changed?  The requirements team has been setting up the
  redirect for https://releases.openstack.org/constraints/upper/{release}
  at the beginning of each OpenStack development cycle (that is, when master
  is Zed development, for example, the url
  https://releases.openstack.org/constraints/upper/zed
  redirects to the ``upper-constraints.txt`` in requirements master).  Thus,
  you should only have to change the value of ``CINDERLIB_RELEASE`` in
  cinderlib master at the time it opens for release 'n+1'.

[testenv]deps
`````````````

* While both the cinder and cinderlib master branches are the development
  branches for the 'n' release cycle (yoga, for example), the base testenv
  in ``tox.ini`` in master should look like this:

  .. code-block::

     # Use cinder and os-brick from the appropriate development branch instead of
     # from PyPi.  Defining the egg name we won't overwrite the package installed
     # by Zuul on jobs supporting cross-project dependencies (include Cinder in
     # required-projects).  This allows us to also run local tests against the
     # latest cinder/brick code instead of released code.
     # NOTE: Functional tests may fail if host is missing bindeps from deps projects
     deps= -r{toxinidir}/test-requirements.txt
           git+https://opendev.org/openstack/os-brick#egg=os-brick
           git+https://opendev.org/openstack/cinder#egg=cinder

* When the coordinated release for cycle 'n' has occurred, cinderlib's
  ``tox.ini`` in master must be modified so that cinderlib is being tested
  against cinder and os-brick from the stable branches for the 'n' release (in
  this example, stable/yoga):

  .. code-block::

     deps = -r{toxinidir}/test-requirements.txt
            git+https://opendev.org/openstack/os-brick@stable/yoga#egg=os-brick
            git+https://opendev.org/openstack/cinder@stable/yoga#egg=cinder

* After the 'n' release of cinderlib occurs (and the stable/n branch is cut),
  all of cinder, os-brick, and cinderlib master branches are all 'n+1' cycle
  development branches, so:

  * The base testenv in ``tox.ini`` in master must be modified to use cinder
    and os-brick from master for testing, reverting the first code block change
    above.

[testenv:py{3,36,38}]install_command
````````````````````````````````````

Note: the actual list of versions may be different from what's listed in the
documentation heading above.

This testenv inherits from the base testenv and is the parent for all the
unit tests.  At the time cinderlib master opens for release 'n+1' development,
check that all supported python versions for the release are listed between
the braces (that is, ``{`` and ``}``).

* The tox term for this is "Generative section names".  See the `tox docs
  <https://tox-gaborbernat.readthedocs.io/en/latest/config.html#generative-envlist>`_
  for more information and the proper syntax.

* The list of supported python runtimes can be found in the `OpenStack
  governance documentation
  <https://governance.openstack.org/tc/reference/runtimes/>`_.

[testenv:docs]install_command
`````````````````````````````

* The ``docs`` testenv sets a default value for ``TOX_CONSTRAINTS_FILE`` as
  part of the ``install_command``.  This only needs to be changed at the time
  cinderlib master opens for release 'n+1'.  See the discussion above about
  setting the value for ``CINDERLIB_RELEASE``; the same considerations apply
  here.

  The ``[testenv:docs]install_command`` is referred to by the other
  documentation-like testenvs, so you should only have to change the value
  of ``TOX_CONSTRAINTS_FILE`` in one place.  (But do a scan of ``tox.ini``
  to be sure, and if you find another, please update this page.)

cinderlib .zuul.yaml maintenance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A few things to note about the cinderlib ``.zuul.yaml`` file.

* The OpenStack QA team defines "templates" that can be used for testing.
  A template defines a set of jobs that are run in the check and the gate,
  and the QA team takes the responsibility to make sure that the template
  for a release includes all the appropriate tests.

  We don't use the 'openstack-python3-{release}-jobs' template; instead, we
  directly configure the jobs that are listed in the template.  The reason for
  this is that during cinderlib's trailing development phase (when cinderlib
  master is the development branch for release 'n' while cinder and os-brick
  master is the development branch for release 'n+1', we need to make sure that
  zuul installs the correct cinder and os-brick branch to test against.  We
  can do this by specifying an 'override-checkout' for cinder, os-brick, and
  requirements in the job definitions.

  We need to do this even though the zuul jobs will ultimately call cinderlib's
  tox.ini, where we have already configured the correct branches to use.
  That's because Zuul doesn't simply call tox; it does a bunch of setup work
  to download packages and configure the environment, and if we don't
  specifically tell Zuul what branches to use, when we run a job on a cinderlib
  master patch, Zuul figures that all components are supposed to be installed
  from their master branch -- including openstack requirements, which specifies
  the upper-constraints for the release.

cinderlib requirements.txt maintenance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* When the coordinated release for cycle 'n' has occurred, cinderlib's
  ``requirements.txt`` in master must be updated to use only 'n' deliverables
  (in this example, yoga):

  .. code-block::

     # restrict cinder to the yoga release only
     cinder>=20.0.0.0,<21.0.0  # Apache-2.0
     # brick upper bound is controlled by yoga/upper-constraints
     os-brick>=5.2.0  # Apache-2.0

* After the 'n' release of cinderlib, when cinderlib master has become
  the 'n+1' development branch, ``requirements.txt`` can again be updated:

  * Remove the upper bound from cinder.

  * The release team likes to push an early release of os-brick from master
    early in the development cycle.  Check to see if that has happened
    already, and if so, update the minimum version of os-brick to the latest
    release and make appropriate adjustments to the comments in the file.

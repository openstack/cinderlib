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

cinderlib releases
------------------

The OpenStack release model for cinderlib is `cycle-with-intermediary
<https://releases.openstack.org/reference/release_models.html#cycle-with-intermediary>`__.
This means that there can be multiple full releases of cinderlib from master
during a development cycle.  The deliverable type of cinderlib is 'trailing'
which means that the final release of cinderlib for a development cycle must
occur within 3 months after the official OpenStack coordinated release.

At the time of the final release, the stable branch is cut, and cinderlib
releases from that branch follow the normal OpenStack stable release policy.

Because cinderlib depends on cinder and os-brick, during the development
cycle it uses cinder and os-brick from master (not from released versions)
so that changes in cinder and os-brick are immediately available for testing
cinderlib.  Once cinder and os-brick have had their final release for a
cycle, however, their master branches become the development branch for the
*next* cycle, whereas cinderlib's master branch is still the development branch
for the *previous* cycle.  Thus, cinderlib's tox.ini requires some manual
maintenance:

* While both the cinder and cinderlib master branches are the development
  branches for the 'n' release cycle (ussuri, for example), the base testenv
  in tox.ini in master should look like this:

  .. code-block::

     # Use cinder from master instead of from PyPi. Defining the egg name we won't
     # overwrite the package installed by Zuul on jobs supporting cross-project
     # dependencies (include Cinder in required-projects).  This allows us to also
     # run local tests against master.
     # NOTE: Functional tests may fail if host is missing bindeps from deps projects
     deps= -r{toxinidir}/test-requirements.txt
           git+https://opendev.org/openstack/os-brick#egg=os-brick
           git+https://opendev.org/openstack/cinder#egg=cinder

* When the coordinated release for cycle 'n' has occurred, cinderlib's
  requirements.txt in master must be updated to use only 'n' deliverables (in
  this example, ussuri):

  .. code-block::

     # restrict cinder to the ussuri series only
     cinder>=16.0.0,<17.0.0
     # brick upper bound is controlled by ussuri/upper-constraints
     os-brick>=3.0.1

  and cinderlib's tox.ini must be modified in three places.  First, we need to
  make sure that cinderlib is being tested against cinder and os-brick from the
  stable branches for the 'n' release (in this example, stable/ussuri):

  .. code-block::

     deps = -r{toxinidir}/test-requirements.txt
            git+https://opendev.org/openstack/os-brick@stable/ussuri#egg=os-brick
            git+https://opendev.org/openstack/cinder@stable/ussuri#egg=cinder

  The other two places are in the testenvs for ``releasenotes`` and ``docs``.
  Both must have the ``deps`` modified so that the default value for the
  ``TOX_CONSTRAINTS_FILE`` is changed to reflect the 'n' release (in this
  example, stable/ussuri):

  .. code-block::

     deps =
       -c {env:TOX_CONSTRAINTS_FILE:https://releases.openstack.org/constraints/upper/ussuri}
       -r {toxinidir}/doc/requirements.txt

* After the 'n' release of cinderlib occurs (and the stable/n branch is cut),
  all of cinder, os-brick, and cinderlib master branches are all n+1 cycle
  development branches, so:

  * The base testenv in tox.ini in master must be modified to use cinder and
    os-brick from master for testing, reverting the first code block change
    above.

  * The testenvs for ``releasenotes`` and ``docs`` must be reset to use upper
    constraints from the ``master`` branch.

    .. code-block::

       deps =
         -c {env:TOX_CONSTRAINTS_FILE:https://releases.openstack.org/constraints/upper/master}
         -r {toxinidir}/doc/requirements.txt

  * Although tox.ini is no longer referring to requirements.txt, that file
    should be updated as well:

    * Remove the upper bound from cinder.

    * The release team likes to push an early release of os-brick from master
      early in the development cycle.  Check to see if that has happened
      already, and if so, update the minimum version of os-brick to the latest
      release and make appropriate adjustments to the comments in the file.

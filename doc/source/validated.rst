=================
Validated drivers
=================

We are in the process of validating the *cinderlib* support of more *Cinder*
drivers and adding more automated testing of drivers on *Cinder*'s gate.

For now we have 2 backends, LVM and Ceph, that are tested on every *Cinder* and
*cinderlib* patch that is submitted and merged.

We have also been able to manually test multiple backends ourselves and
received reports of other backends that have been successfully tested.

In this document we present the list of all these drivers, and for each one we
include the storage array that was used, the configuration (with masked
sensitive data), any necessary external requirements -such as packages or
libraries-, whether it is being automatically tested on the OpenStack gates
or not, and any additional notes.

Currently the following backends have been verified:

- `LVM`_ with LIO
- `Ceph`_
- Dell EMC `XtremIO`_
- Dell EMC `VMAX`_
- `Kaminario`_ K2
- NetApp `SolidFire`_
- HPE `3PAR`_
- `Synology`_
- `QNAP`_


LVM
---

- *Storage*: LVM with LIO
- *Connection type*: iSCSI
- *Requirements*:  None
- *Automated testing*: On *cinderlib* and *Cinder* jobs.

*Configuration*:

.. code-block:: YAML

   backends:
       - volume_backend_name: lvm
         volume_driver: cinder.volume.drivers.lvm.LVMVolumeDriver
         volume_group: cinder-volumes
         target_protocol: iscsi
         target_helper: lioadm


Ceph
----

- *Storage*: Ceph/RBD
- *Versions*: Luminous v12.2.5
- *Connection type*: RBD
- *Requirements*:

  - ``ceph-common`` package
  - ``ceph.conf`` file
  - Ceph keyring file

- *Automated testing*: On *cinderlib* and *Cinder* jobs.
- *Notes*:

  - If we don't define the ``keyring`` configuration parameter (must use an
    absolute path) in our ``rbd_ceph_conf`` to point to our
    ``rbd_keyring_conf`` file, we'll need the ``rbd_keyring_conf`` to be in
    ``/etc/ceph/``.
  - ``rbd_keyring_confg`` must always be present and must follow the naming
     convention of ``$cluster.client.$rbd_user.conf``.
  - Current driver cannot delete a snapshot if there's a dependent volume
    (a volume created from it exists).

*Configuration*:

.. code-block:: YAML

   backends:
       - volume_backend_name: ceph
         volume_driver: cinder.volume.drivers.rbd.RBDDriver
         rbd_user: cinder
         rbd_pool: volumes
         rbd_ceph_conf: tmp/ceph.conf
         rbd_keyring_conf: /etc/ceph/ceph.client.cinder.keyring


XtremIO
-------

- *Storage*: Dell EMC XtremIO
- *Versions*: v4.0.15-20_hotfix_3
- *Connection type*: iSCSI, FC
- *Requirements*: None
- *Automated testing*: No

*Configuration* for iSCSI:

.. code-block:: YAML

   backends:
       - volume_backend_name: xtremio
         volume_driver: cinder.volume.drivers.dell_emc.xtremio.XtremIOISCSIDriver
         xtremio_cluster_name: CLUSTER_NAME
         use_multipath_for_image_xfer: true
         san_ip: w.x.y.z
         san_login: user
         san_password: toomanysecrets

*Configuration* for FC:

.. code-block:: YAML

   backends:
       - volume_backend_name: xtremio
         volume_driver: cinder.volume.drivers.dell_emc.xtremio.XtremIOFCDriver
         xtremio_cluster_name: CLUSTER_NAME
         use_multipath_for_image_xfer: true
         san_ip: w.x.y.z
         san_login: user
         san_password: toomanysecrets


Kaminario
---------

- *Storage*: Kaminario K2
- *Versions*: VisionOS v6.0.72.10
- *Connection type*: iSCSI
- *Requirements*:

  - ``krest`` Python package from PyPi

- *Automated testing*: No

*Configuration*:

.. code-block:: YAML

   backends:
       - volume_backend_name: kaminario
         volume_driver: cinder.volume.drivers.kaminario.kaminario_iscsi.KaminarioISCSIDriver
         san_ip: w.x.y.z
         san_login: user
         san_password: toomanysecrets
         use_multipath_for_image_xfer: true


SolidFire
---------

- *Storage*: NetApp SolidFire
- *Versions*: Unknown
- *Connection type*: iSCSI
- *Requirements*: None
- *Automated testing*: No

*Configuration*:

.. code-block:: YAML

   backends:
       - volume_backend_name: solidfire
         volume_driver: cinder.volume.drivers.solidfire.SolidFireDriver
         san_ip: w.x.y.z
         san_login: admin
         san_password: toomanysecrets
         sf_allow_template_caching = false
         image_volume_cache_enabled = True
         volume_clear = zero


VMAX
----

- *Storage*: Dell EMC VMAX
- *Versions*: Unknown
- *Connection type*: iSCSI
- *Automated testing*: No

.. code-block:: YAML

   size_precision: 2
   backends:
       - image_volume_cache_enabled: True
         volume_clear: zero
         volume_backend_name: VMAX_ISCSI_DIAMOND
         volume_driver: cinder.volume.drivers.dell_emc.vmax.iscsi.VMAXISCSIDriver
         san_ip: w.x.y.z
         san_rest_port: 8443
         san_login: user
         san_password: toomanysecrets
         vmax_srp: SRP_1
         vmax_array: 000197800128
         vmax_port_groups: [os-iscsi-pg]


3PAR
----

- *Storage*: HPE 3PAR 8200
- *Versions*: 3.3.1.410 (MU2)+P32,P34,P37,P40,P41,P45
- *Connection type*: iSCSI
- *Requirements*:

  - ``python-3parclient>=4.1.0`` Python package from PyPi

- *Automated testing*: No
- *Notes*:

  - Features work as expected, but due to a `bug in the 3PAR driver
    <https://bugs.launchpad.net/cinder/+bug/1824371>`_ the stats test
    (``test_stats_with_creation_on_3par``) fails.

*Configuration*:

.. code-block:: YAML

   backends:
        - volume_backend_name: 3par
          hpe3par_api_url: https://w.x.y.z:8080/api/v1
          hpe3par_username: user
          hpe3par_password: toomanysecrets
          hpe3par_cpg: [CPG_name]
          san_ip: w.x.y.z
          san_login: user
          san_password: toomanysecrets
          volume_driver: cinder.volume.drivers.hpe.hpe_3par_iscsi.HPE3PARISCSIDriver
          hpe3par_iscsi_ips: [w.x.y2.z2,w.x.y2.z3,w.x.y2.z4,w.x.y2.z4]
          hpe3par_debug: false
          hpe3par_iscsi_chap_enabled: false
          hpe3par_snapshot_retention: 0
          hpe3par_snapshot_expiration: 1
          use_multipath_for_image_xfer: true

Synology
--------

- *Storage*: Synology DS916+
- *Versions*: DSM 6.2.1-23824 Update 6
- *Connection type*: iSCSI
- *Requirements*: None
- *Automated testing*: No

*Configuration*:

.. code-block:: YAML

   backends:
        - volume_backend_name: synology
          volume_driver: cinder.volume.drivers.synology.synology_iscsi.SynoISCSIDriver
          iscs_protocol: iscsi
          target_ip_address: synology.example.com
          synology_admin_port: 5001
          synology_username: admin
          synology_password: toomanysecrets
          synology_pool_name: volume1
          driver_use_ssl: true


QNAP
----

- *Storage*: QNAP TS-831X
- *Versions*: 4.3.5.0728
- *Connection type*: iSCSI
- *Requirements*: None
- *Automated testing*: No

*Configuration*:

.. code-block:: YAML

   backends:
        - volume_backend_name: qnap
          volume_driver: cinder.volume.drivers.qnap.QnapISCSIDriver
          use_multipath_for_image_xfer: true
          qnap_management_url: https://w.x.y.z:443
          iscsi_ip_address: w.x.y.z
          qnap_storage_protocol: iscsi
          qnap_poolname: Storage Pool 1
          san_login: admin
          san_password: toomanysecrets

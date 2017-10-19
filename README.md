# Cloudlet-dashboard
Horizon plugin for Cloudlet.


## Tested Platform
We have tested `Cloudlet-dashboard` on **Ubuntu 16.04 LTS** using the **Devstack stable/newton** branch.

## Installation
This repository is OpenStack extension for cloudlet. Therefore, you need to install OpenStack and [cloudlet library](https://github.com/cmusatyalab/elijah-provisioning) before installing this extension.

### 1. Install cloudlet library
Download the `elijah-provisioning` repository：
```sh
$ git clone https://github.com/ellis-wu/elijah-provisioning.git
```

Install the `fabric` and `openssh-server`：
```sh
$ sudo apt-get install -y fabric openssh-server
```

Install `cloudlet library`：
```sh
$ cd elijah-provisioning/
$ fab install
(Type your Ubuntu account password when it is asked)
```

## 2. Install cloudlet-dashboard
Download the `cloudlet-dashboard` repository and change the `dev` branch：
```sh
$ git clone https://github.com/ellis-wu/cloudlet-dashboard.git
$ git checkout dev
```

Move the files to the correct folder：
```sh
$ cd cloudlet-dashboard
$ cp -r cloudlet/ /opt/stack/horizon/openstack_dashboard/dashboards/project/
$ cp enabled/_1080_project_cloudlet_panel.py /opt/stack/horizon/openstack_dashboard/enabled/
```

Restart `apache2` service：
```sh
$ sudo service apache2 restart
```

If your finished, you can open the OpenStack Dashboard and see the Cloudlet add to Dashboard.

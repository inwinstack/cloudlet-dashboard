# Cloudlet-dashboard
Custom Cloudlet OpenStack Dashboard

## 事前安裝
1. OpenStack (目前 Newton)

## 安裝 elijah-provisioning
下載 elijah-provisioning：
```sh
$ git clone https://github.com/ellis-wu/elijah-provisioning.git
```

安裝 fabric openssh-server package：
```sh
$ sudo apt-get install -y fabric openssh-server
```

安裝 elijah-provisioning
```sh
$ cd elijah-provisioning/
$ fab install
(Type your Ubuntu account password when it is asked)
```

## 安裝 cloudlet-dashboard
下載 cloudlet-dashboard：
```sh
$ git clone https://github.com/ellis-wu/cloudlet-dashboard.git
```

放置檔案至正確目錄：
```sh
$ cd cloudlet-dashboard
$ cp -r cloudlet/ /opt/stack/horizon/openstack_dashboard/dashboards/project/
$ cp enabled/_1080_project_cloudlet_panel.py /opt/stack/horizon/openstack_dashboard/enabled/
```

重啟 `apache2`：
```sh
$ sudo service apache2 restart
```

重新整理 OpenStack Dashboard 就會看到 Cloudlet 已加入其中。

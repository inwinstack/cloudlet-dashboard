# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import httplib
import json

from urlparse import urlparse

from openstack_dashboard.api.base import url_for


def request_create_overlay(request, instance_id):
    token = request.user.token.id
    management_url = url_for(request, 'compute')
    end_point = urlparse(management_url)

    overlay_name = "overlay-" + str(instance_id)
    params = json.dumps({
        "cloudlet-overlay-finish": {
            "overlay-name": overlay_name
        }
    })
    headers = {"X-Auth-Token": token, "Content-type": "application/json"}

    conn = httplib.HTTPConnection(end_point[1])
    command = "%s/servers/%s/action" % (end_point[2], instance_id)
    conn.request("POST", command, params, headers)
    response = conn.getresponse()
    data = response.read()
    dd = json.loads(data)
    conn.close()
    return dd


def request_handoff(request, instance_id, handoff_url,
                    glance_url, neutron_url, dest_token,
                    dest_vmname, dest_network):
    token = request.user.token.id
    management_url = url_for(request, 'compute')
    end_point = urlparse(management_url)

    params = json.dumps({
        "cloudlet-handoff": {
            "handoff_url": handoff_url,
            "glance_url": glance_url,
            "neutron_url": neutron_url,
            "dest_token": dest_token,
            "dest_vmname": dest_vmname,
            "dest_network": dest_network,
        }
    })
    headers = {"X-Auth-Token": token, "Content-type": "application/json"}

    conn = httplib.HTTPConnection(end_point[1])
    command = "%s/servers/%s/action" % (end_point[2], instance_id)
    conn.request("POST", command, params, headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    dd = json.loads(data)
    return dd

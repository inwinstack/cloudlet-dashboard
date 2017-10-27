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

from django.utils.translation import ugettext_lazy as _

from horizon import exceptions
from horizon import forms

from openstack_dashboard.dashboards.project.cloudlet import cloudlet_api


class HandoffInstanceForm(forms.SelfHandlingForm):
    dest_addr = forms.CharField(
        max_length=255,
        required=True,
        label=_("Keystone endpoint for destination OpenStack"),
        widget=forms.TextInput(attrs={
            'placeholder': 'destination_openstack_ipaddress:5000'}
        ))
    dest_account = forms.CharField(
        max_length=255, required=True,
        label=_("Destination Account"),
        widget=forms.TextInput(attrs={
            'placeholder': 'admin'}
        ))
    dest_password = forms.CharField(
        widget=forms.PasswordInput(),
        required=True,
        label=_("Destination Password"))
    dest_tenant = forms.CharField(
        max_length=255, required=True,
        label=_("Destination Tenant"),
        widget=forms.TextInput(attrs={
            'placeholder': 'demo'}
        ))
    dest_vmname = forms.CharField(
        max_length=255,
        label=_("Instance Name at the destination"),
        widget=forms.TextInput(attrs={
            'placeholder': 'handoff-vm'}
        ))
    dest_network = forms.CharField(
        max_length=255,
        label=_("Network Name at the destination"),
        widget=forms.TextInput(attrs={
            'placeholder': 'default'}
        ))

    def __init__(self, request, *args, **kwargs):
        super(HandoffInstanceForm, self).__init__(request, *args, **kwargs)
        self.instance_id = kwargs.get('initial', {}).get('instance_id')

    @staticmethod
    def _get_token(dest_addr, user, password, tenant_name):
        if dest_addr.endswith("/"):
            dest_addr = dest_addr[:-1]
        params = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": user,
                            "domain": {"id": "default"},
                            "password": password
                        }
                    }
                },
                "scope": {
                    "project": {
                        "name": tenant_name,
                        "domain": {"id": "default"}
                    }
                }
            }
        }
        headers = {"Content-Type": "application/json"}

        # HTTP connection
        conn = httplib.HTTPConnection(dest_addr)
        conn.request("POST", "/v3/auth/tokens", json.dumps(params), headers)

        # HTTP response
        response = conn.getresponse()
        api_token = response.getheader('x-subject-token')
        data = response.read()
        dd = json.loads(data)
        conn.close()
        try:
            project_id = dd['token']['project']['id']
            nova_endpoint = None
            glance_endpoint = None
            neutron_endpoint = None
            service_list = dd['token']['catalog']
            for service in service_list:
                if service['name'] == "nova":
                    for endpoint in service['endpoints']:
                        if endpoint['interface'] == "public":
                            nova_endpoint = endpoint['url']
                elif service['name'] == "glance":
                    for endpoint in service['endpoints']:
                        if endpoint['interface'] == "public":
                            glance_endpoint = endpoint['url']
                elif service['name'] == "neutron":
                    for endpoint in service['endpoints']:
                        if endpoint['interface'] == "public":
                            neutron_endpoint = endpoint['url']
        except KeyError as e:
            raise
        return api_token, project_id, nova_endpoint, glance_endpoint, neutron_endpoint

    def clean(self):
        cleaned_data = super(HandoffInstanceForm, self).clean()
        dest_addr = cleaned_data.get('dest_addr', None)
        dest_account = cleaned_data.get('dest_account', None)
        dest_password = cleaned_data.get('dest_password', None)
        dest_tenant = cleaned_data.get('dest_tenant', None)
        dest_network = cleaned_data.get('dest_network', None)

        # check fields
        if cleaned_data.get('dest_vmname', None) is None:
            msg = "Need name for VM at the destination"
            raise forms.ValidationError(_(msg))
        if dest_addr is None:
            msg = "Need URL to fetch VM overlay"
            raise forms.ValidationError(_(msg))
        if dest_network is None:
            msg = "Need Network for VM at the destination"
            raise forms.ValidationError(_(msg))

        # get token of the destination
        try:
            dest_token, dest_project_id, dest_nova_endpoint, dest_glance_endpoint, dest_neutron_endpoint = \
                self._get_token(dest_addr, dest_account, dest_password, dest_tenant)
            cleaned_data['dest_token'] = dest_token
            cleaned_data['dest_project_id'] = dest_project_id
            cleaned_data['dest_nova_endpoint'] = dest_nova_endpoint
            cleaned_data['dest_glance_endpoint'] = dest_glance_endpoint
            cleaned_data['dest_network_endpoint'] = dest_neutron_endpoint
            cleaned_data['instance_id'] = self.instance_id
        except Exception as e:
            msg = "Cannot get Auth-token from %s" % dest_addr
            raise forms.ValidationError(_(msg))
        return cleaned_data

    def handle(self, request, context):
        try:
            # (Change) This is not the correct way to use the Handoff API.
            #          And no add neutorn network with cloudlet_api.
            ret_json = cloudlet_api.request_handoff(
                request,
                context['instance_id'],
                context['dest_nova_endpoint'],
                context['dest_glance_endpoint'],
                context['dest_network_endpoint'],
                context['dest_token'],
                context['dest_project_id'],
                context['dest_vmname'],
                context['dest_network']
            )
            error_msg = ret_json.get("badRequest", None)
            if error_msg is not None:
                msg = error_msg.get(
                    "message",
                    "Failed to request VM synthesis")
                raise Exception(msg)
            return True
        except:
            exceptions.handle(request)
            return False

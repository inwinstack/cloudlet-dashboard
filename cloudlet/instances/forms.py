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

from django.utils.translation import ugettext_lazy as _

from horizon import exceptions
from horizon import forms

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

    def __init__(self, request, *args, **kwargs):
        super(HandoffInstanceForm, self).__init__(request, *args, **kwargs)
        self.instance_id = kwargs.get('initial', {}).get('instance_id')

    # @staticmethod
    # def _get_token(dest_addr, user, password, tenant_name):
    #     if dest_addr.endswith("/"):
    #         dest_addr = dest_addr[-1:]

    def clean(self):
        cleaned_data = super(HandoffInstanceForm, self).clean()
        dest_addr = cleaned_data.get('dest_addr', None)
        dest_account = cleaned_data.get('dest_account', None)
        dest_password = cleaned_data.get('dest_password', None)
        dest_tenant = cleaned_data.get('dest_tenant', None)

        # check fields
        if cleaned_data.get('dest_vmname', None) is None:
            msg = "Need name for VM at the destination"
            raise forms.ValidationError(_(msg))
        if dest_addr is None:
            msg = "Need URL to fetch VM overlay"
            raise forms.ValidationError(_(msg))

        return cleaned_data

    def get_help_text(self):
        return super(HandoffInstanceForm, self).get_help_text()

    def handle(self, request, context):
        try:
            print "Start Handoff"
            return True
        except:
            exceptions.handle(request)
            return False

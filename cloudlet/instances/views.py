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

from django.core.urlresolvers import reverse_lazy
from django.utils.translation import ugettext_lazy as _

from horizon import forms
from horizon import workflows

from openstack_dashboard import api
from openstack_dashboard.dashboards.project.cloudlet.instances \
    import forms as project_forms
from openstack_dashboard.dashboards.project.cloudlet.workflows \
    import create_instance as project_workflows


class ResumeInstanceView(workflows.WorkflowView):
    workflow_class = project_workflows.ResumeInstance

    def get_initial(self):
        initial = super(ResumeInstanceView, self).get_initial()
        initial['project_id'] = self.request.user.tenant_id
        initial['user_id'] = self.request.user.id
        # defaults = getattr(settings, 'LAUNCH_INSTANCE_DEFAULTS', {})
        # initial['config_drive'] = defaults.get('config_drive', False)
        return initial


class SynthesisInstanceView(workflows.WorkflowView):
    workflow_class = project_workflows.SynthesisInstance

    def get_initial(self):
        initial = super(SynthesisInstanceView, self).get_initial()
        initial['project_id'] = self.request.user.tenant_id
        initial['user_id'] = self.request.user.id
        return initial


class HandoffInstanceView(forms.ModalFormView):
    form_class = project_forms.HandoffInstanceForm
    template_name = 'project/cloudlet/instance/handoff.html'
    success_url = reverse_lazy("horizon:project:cloudlet:index")
    page_title = _("Handoff Instance")
    submit_label = page_title

    def get_context_data(self, **kwargs):
        context = super(HandoffInstanceView, self).get_context_data(**kwargs)
        context['instance_id'] = self.kwargs['instance_id']
        context['can_set_server_password'] = api.nova.can_set_server_password()
        return context

    def get_initial(self):
        return {'instance_id': self.kwargs['instance_id']}

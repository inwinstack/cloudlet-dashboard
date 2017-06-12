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


from django.conf import settings
from django.core.urlresolvers import reverse
from django.core.urlresolvers import reverse_lazy
from django import http
from django import shortcuts
from django.utils.translation import ugettext_lazy as _

from horizon import exceptions
from horizon import forms
from horizon import messages
from horizon import workflows
from horizon.utils import memoized

from openstack_dashboard import api

from openstack_dashboard.dashboards.project.cloudlet.images \
    import forms as project_forms
from openstack_dashboard.dashboards.project.cloudlet \
    import workflows as project_workflows



class ImportBaseView(forms.ModalFormView):
    form_class = project_forms.ImportBaseForm
    form_id = "import_basevm_form"
    modal_header = _("Import Base VM")
    submit_label = _("Import")
    submit_url = reverse_lazy('horizon:project:cloudlet:images:import')
    template_name = 'project/cloudlet/images/import.html'
    context_object_name = 'image'
    success_url = reverse_lazy("horizon:project:cloudlet:index")
    page_title = _("Import Base VM")

    def get_initial(self):
        initial = {}
        for name in [
            'name',
            'description',
            'image_url',
            'source_type',
            'architecture',
            'disk_format',
            'minimum_disk',
            'minimum_ram'
        ]:
            tmp = self.request.GET.get(name)
            if tmp:
                initial[name] = tmp
        return initial

    def get_context_data(self, **kwargs):
        context = super(ImportBaseView, self).get_context_data(**kwargs)
        upload_mode = api.glance.get_image_upload_mode()
        context['image_upload_enabled'] = upload_mode != 'off'
        return context


class ResumeInstanceView(workflows.WorkflowView):
    workflow_class = project_workflows.ResumeInstance

    def get_initial(self):
        initial = super(ResumeInstanceView, self).get_initial()
        initial['project_id'] = self.request.user.tenant_id
        initial['user_id'] = self.request.user.id
        # defaults = getattr(settings, 'LAUNCH_INSTANCE_DEFAULTS', {})
        # initial['config_drive'] = defaults.get('config_drive', False)
        return initial


class UpdateView(forms.ModalFormView):
    form_class = project_forms.UpdateImageForm
    form_id = "update_image_form"
    modal_header = _("Edit Image")
    submit_label = _("Edit Image")
    submit_url = "horizon:project:cloudlet:images:update"
    template_name = 'project/cloudlet/images/update.html'
    success_url = reverse_lazy("horizon:project:cloudlet:index")
    page_title = _("Edit Image")

    @memoized.memoized_method
    def get_object(self):
        try:
            return api.glance.image_get(self.request, self.kwargs['image_id'])
        except Exception:
            msg = _('Unable to retrieve image.')
            url = reverse('horizon:project:cloudlet:index')
            exceptions.handle(self.request, msg, redirect=url)

    def get_context_data(self, **kwargs):
        context = super(UpdateView, self).get_context_data(**kwargs)
        context['image'] = self.get_object()
        args = (self.kwargs['image_id'],)
        context['submit_url'] = reverse(self.submit_url, args=args)
        return context

    def get_initial(self):
        image = self.get_object()
        properties = getattr(image, 'properties', {})
        data = {'image_id': self.kwargs['image_id'],
                'name': getattr(image, 'name', None) or image.id,
                'description': properties.get('description', ''),
                'kernel': properties.get('kernel_id', ''),
                'ramdisk': properties.get('ramdisk_id', ''),
                'architecture': properties.get('architecture', ''),
                'minimum_ram': getattr(image, 'min_ram', None),
                'minimum_disk': getattr(image, 'min_disk', None),
                'public': getattr(image, 'is_public', None),
                'protected': getattr(image, 'protected', None)}
        disk_format = getattr(image, 'disk_format', None)
        if (disk_format == 'raw' and
                getattr(image, 'container_format') == 'docker'):
            disk_format = 'docker'
        data['disk_format'] = disk_format
        return data


def download_vm_overlay(request):
    try:
        image_id = request.GET.get('image_id', None)
        image_name = request.GET.get('image_name', None)
        if image_id is None:
            raise
        client = api.glance.glanceclient(request)

        body = client.images.data(image_id)
        response = http.HttpResponse(body, content_type="application/octet-stream")
        response['Content-Disposition'] = 'attachment; filename="%s"' % image_name
        return response
    except Exception, e:
        messages.error(request, _('Error Downloading VM overlay: %s') % e)
        return shortcuts.redirect(request.build_absolute_uri())

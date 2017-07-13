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

import json
import logging
import requests

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.template.defaultfilters import filesizeformat
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.debug import sensitive_variables

from horizon import exceptions
from horizon import forms
from horizon import workflows

from openstack_dashboard import api
from openstack_dashboard.api import base
from openstack_dashboard.api import glance
from openstack_dashboard.usage import quotas

from openstack_dashboard.dashboards.project.cloudlet import cloudlet_api
from openstack_dashboard.dashboards.project.cloudlet import utils
from openstack_dashboard.dashboards.project.instances \
    import utils as instance_utils

from elijah.provisioning.configuration import Const as Cloudlet_Const
from elijah.provisioning.package import VMOverlayPackage
try:
    from elijah.provisioning import msgpack
except ImportError as e:
    import msgpack


LOG = logging.getLogger(__name__)


class SelectProjectUserAction(workflows.Action):
    project_id = forms.ThemableChoiceField(label=_("Project"))
    user_id = forms.ThemableChoiceField(label=_("User"))

    def __init__(self, request, *args, **kwargs):
        super(SelectProjectUserAction, self).__init__(request, *args, **kwargs)
        # Set our project choices
        projects = [(tenant.id, tenant.name)
                    for tenant in request.user.authorized_tenants]
        self.fields['project_id'].choices = projects

        # Set our user options
        users = [(request.user.id, request.user.username)]
        self.fields['user_id'].choices = users

    class Meta(object):
        name = _("Project & User")
        # Unusable permission so this is always hidden. However, we
        # keep this step in the workflow for validation/verification purposes.
        permissions = ("!",)


class SelectProjectUser(workflows.Step):
    action_class = SelectProjectUserAction
    contributes = ("project_id", "user_id")


class SetResumeDetailAction(workflows.Action):
    image_id = forms.ChoiceField(
        label=_("Image Name"),
        required=True,
        widget=forms.ThemableSelectWidget(
            data_attrs=('volume_size',),
            transform=lambda x: ("%s (%s)" % (x.name,
                                              filesizeformat(x.bytes)))))

    name = forms.CharField(max_length=80,
                           label=_("Instance Name"),
                           initial="resumed_vm")

    flavor = forms.ChoiceField(
        label=_("Flavor"),
        required=True,
        help_text=_("Size of image to launch."))

    class Meta:
        name = _("Base VM Info")
        help_text_template = ("project/cloudlet/instance/"
                              "_resume_details_help.html")

    def clean(self):
        cleaned_data = super(SetResumeDetailAction, self).clean()
        return cleaned_data

    def _get_available_images(self, request, context):
        if not hasattr(self, '_images_cache'):
            images_cache = {}

        if images_cache is None:
            images_cache = {}

        public_images = images_cache.get('public_images', [])
        images_by_project = images_cache.get('images_by_project', {})
        if 'public_images' not in images_cache:
            public = {"is_public": True,
                      "status": "active"}

            try:
                images, _more, _prev = glance.image_list_detailed(
                    request, filters=public)
                [public_images.append(image) for image in images]
                images_cache['public_images'] = public_images
            except Exception:
                exceptions.handle(request,
                                  _("Unable to retrieve public images."))

        # Preempt if we don't have a project_id yet.
        project_id = context.get('project_id', None)
        if project_id is None:
            images_by_project[project_id] = []

        if project_id not in images_by_project:
            owner = {"property-owner_id": project_id,
                     "status": "active"}
            try:
                owned_images, _more, _prev = glance.image_list_detailed(
                    request, filters=owner)
                images_by_project[project_id] = owned_images
            except Exception:
                owned_images = []
                exceptions.handle(request,
                                  _("Unable to retrieve images for "
                                    "the current project."))
        else:
            owned_images = images_by_project[project_id]

        if 'images_by_project' not in images_cache:
            images_cache['images_by_project'] = images_by_project

        images = owned_images + public_images
        base_vms = list()
        for image in images:
            if hasattr(image, 'properties') == True:
                properties = getattr(image, 'properties')
                cloudlet_type = properties.get('cloudlet_type', None)
                if cloudlet_type == 'cloudlet_base_disk':
                    base_vms.append(image)

        image_ids = []
        final_images = []
        for image in base_vms:
            if image.id not in image_ids:
                image_ids.append(image.id)
                final_images.append(image)
        return [image for image in final_images
                if image.container_format not in ('aki', 'ari')]

    def populate_image_id_choices(self, request, context):
        images = self._get_available_images(request, context)
        choices = [(image.id, image.name)
                   for image in images
                   if image.properties.get("image_type", '') == "snapshot"]
        if choices:
            choices.insert(0, ("", _("Select Base VM")))
        else:
            choices.insert(0, ("", _("No Base VM is available.")))
        return choices

    def populate_flavor_choices(self, request, context):
        # return all flavors of Base VM image
        try:
            matching_flavors = set()
            flavors = api.nova.flavor_list(request)
            basevm_images = self._get_available_images(request, context)
            for basevm_image in basevm_images:
                if basevm_image.properties is None or \
                                len(basevm_image.properties) == 0:
                    continue
                libvirt_xml_str = basevm_image.properties.get(
                    'base_resource_xml_str', None)
                if libvirt_xml_str is None:
                    continue
                qemu_mem = utils.QemuMemory()
                cpu_count, memory_mb = qemu_mem.get_resource_size(libvirt_xml_str)
                disk_gb = basevm_image.min_disk
                ret_flavors = utils.find_matching_flavor(flavors,
                                                   cpu_count,
                                                   memory_mb,
                                                   disk_gb)
                matching_flavors.update(ret_flavors)
            if len(matching_flavors) > 0:
                self.fields['flavor'].initial = list(matching_flavors)[0]
            else:
                self.fields['flavor'].initial = (0, "No valid flavor")
        except Exception as e:
            matching_flavors = set()
            exceptions.handle(request,
                              _('Unable to retrieve instance flavors.'))
        return sorted(list(matching_flavors))

    def get_help_text(self):
        extra = {}
        try:
            extra['usages'] = quotas.tenant_quota_usages(self.request)
            extra['usages_json'] = json.dumps(extra['usages'])
            flavors = json.dumps([f._info for f in
                                  api.nova.flavor_list(self.request)])
            extra['flavors'] = flavors
        except Exception:
            exceptions.handle(self.request,
                              _("Unable to retrieve quota information."))
        return super(SetResumeDetailAction, self).get_help_text(extra)


class SetResumeAction(workflows.Step):
    action_class = SetResumeDetailAction
    contributes = ("image_id", "name", "flavor")

    def prepare_action_context(self, request, context):
        if 'source_type' in context and 'source_id' in context:
            context[context['source_type']] = context['source_id']
        return context


KEYPAIR_IMPORT_URL = "horizon:project:access_and_security:keypairs:import"


class SetAccessControlsAction(workflows.Action):
    keypair = forms.ThemableDynamicChoiceField(
        label=_("Key Pair"),
        help_text=_("Key pair to use for "
                    "authentication."),
        add_item_link=KEYPAIR_IMPORT_URL)

    groups = forms.MultipleChoiceField(
        label=_("Security Groups"),
        required=True,
        initial=["default"],
        widget=forms.ThemableCheckboxSelectMultiple(),
        help_text=_("Launch instance in these "
                    "security groups."))

    class Meta(object):
        name = _("Access & Security")
        help_text = _("Control access to your instance via key pairs, "
                      "security groups, and other mechanisms.")

    def __init__(self, request, *args, **kwargs):
        super(SetAccessControlsAction, self).__init__(request, *args, **kwargs)
        # if not api.nova.can_set_server_password():
        #     del self.fields['admin_pass']
        #     del self.fields['confirm_admin_pass']
        self.fields['keypair'].required = api.nova.requires_keypair()

    def populate_keypair_choices(self, request, context):
        keypairs = instance_utils.keypair_field_data(request, True)
        if len(keypairs) == 2:
            self.fields['keypair'].initial = keypairs[1][0]
        return keypairs

    def populate_groups_choices(self, request, context):
        try:
            groups = api.network.security_group_list(request)
            if base.is_service_enabled(request, 'network'):
                security_group_list = [(sg.id, sg.name) for sg in groups]
            else:
                # Nova-Network requires the groups to be listed by name
                security_group_list = [(sg.name, sg.name) for sg in groups]
        except Exception:
            exceptions.handle(request,
                              _('Unable to retrieve list of security groups'))
            security_group_list = []
        return security_group_list

    def clean(self):
        '''Check to make sure password fields match.'''
        cleaned_data = super(SetAccessControlsAction, self).clean()
        if 'admin_pass' in cleaned_data:
            if cleaned_data['admin_pass'] != cleaned_data.get(
                    'confirm_admin_pass', None):
                raise forms.ValidationError(_('Passwords do not match.'))
        return cleaned_data


class SetAccessControls(workflows.Step):
    action_class = SetAccessControlsAction
    depends_on = ("project_id", "user_id")
    contributes = ("keypair_id", "security_group_ids")

    def contribute(self, data, context):
        if data:
            post = self.workflow.request.POST
            context['security_group_ids'] = post.getlist("groups")
            context['keypair_id'] = data.get("keypair", "")
        return context


class SetNetworkAction(workflows.Action):
    network = forms.MultipleChoiceField(
        label=_("Networks"),
        widget=forms.ThemableCheckboxSelectMultiple(),
        error_messages={
            'required': _(
                "At least one network must"
                " be specified.")},
        help_text=_("Launch instance with"
                    " these networks"))
    if api.neutron.is_port_profiles_supported():
        widget = None
    else:
        widget = forms.HiddenInput()
    profile = forms.ChoiceField(label=_("Policy Profiles"),
                                required=False,
                                widget=widget,
                                help_text=_("Launch instance with "
                                            "this policy profile"))

    def __init__(self, request, *args, **kwargs):
        super(SetNetworkAction, self).__init__(request, *args, **kwargs)
        network_list = self.fields["network"].choices
        if len(network_list) == 1:
            self.fields['network'].initial = [network_list[0][0]]
        if api.neutron.is_port_profiles_supported():
            self.fields['profile'].choices = (
                self.get_policy_profile_choices(request))

    class Meta(object):
        name = _("Networking")
        permissions = ('openstack.services.network',)
        help_text = _("Select networks for your instance.")

    def populate_network_choices(self, request, context):
        return instance_utils.network_field_data(request)

    def get_policy_profile_choices(self, request):
        profile_choices = [('', _("Select a profile"))]
        for profile in self._get_profiles(request, 'policy'):
            profile_choices.append((profile.id, profile.name))
        return profile_choices

    def _get_profiles(self, request, type_p):
        profiles = []
        try:
            profiles = api.neutron.profile_list(request, type_p)
        except Exception:
            msg = _('Network Profiles could not be retrieved.')
            exceptions.handle(request, msg)
        return profiles


class SetNetwork(workflows.Step):
    action_class = SetNetworkAction
    # Disabling the template drag/drop only in the case port profiles
    # are used till the issue with the drag/drop affecting the
    # profile_id detection is fixed.
    if api.neutron.is_port_profiles_supported():
        contributes = ("network_id", "profile_id",)
    else:
        template_name = "project/instances/_update_networks.html"
        contributes = ("network_id",)

    def contribute(self, data, context):
        if data:
            networks = self.workflow.request.POST.getlist("network")
            # If no networks are explicitly specified, network list
            # contains an empty string, so remove it.
            networks = [n for n in networks if n != '']
            if networks:
                context['network_id'] = networks

            if api.neutron.is_port_profiles_supported():
                context['profile_id'] = data.get('profile', None)
        return context


class ResumeInstance(workflows.Workflow):
    slug = "cloudlet_resume_base_instance"
    name = _("Cloudlet Resume Base VM")
    finalize_button_name = _("Launch")
    success_message = _('Cloudlet launched %(count)s named "%(name)s".')
    failure_message = _('Cloudlet is unable to launch %(count)s named "%(name)s".')
    success_url = "horizon:project:cloudlet:index"
    multipart = True
    default_steps = (SelectProjectUser,
                     SetResumeAction,
                     SetAccessControls,
                     SetNetwork)

    def format_status_message(self, message):
        name = self.context.get('name', 'unknown instance')
        count = self.context.get('count', 1)
        if int(count) > 1:
            return message % {"count": _("%s instances") % count,
                              "name": name}
        else:
            return message % {"count": _("instance"), "name": name}

    @sensitive_variables('context')
    def handle(self, request, context):
        dev_mapping = None
        user_script = None

        netids = context.get('network_id', None)
        if netids:
            nics = [{"net-id": netid, "v4-fixed-ip": ""}
                    for netid in netids]
        else:
            nics = None

        port_profiles_supported = api.neutron.is_port_profiles_supported()

        if port_profiles_supported:
            nics = self.set_network_port_profiles(request,
                                                  context['network_id'],
                                                  context['profile_id'])

        ports = context.get('ports')
        if ports:
            if nics is None:
                nics = []
            nics.extend([{'port-id': port} for port in ports])

        try:
            api.nova.server_create(request,
                                   context['name'],
                                   context['image_id'],
                                   context['flavor'],
                                   context['keypair_id'],
                                   user_script,
                                   context['security_group_ids'],
                                   dev_mapping,
                                   nics=nics,
                                   instance_count=1,)
            return True
        except:
            exceptions.handle(request)
            return False


class SetSynthesizeDetailsAction(workflows.Action):
    overlay_url = forms.CharField(max_length=200,
                                  required=True,
                                  label=_("URL for VM overlay"),
                                  initial="http://")

    name = forms.CharField(max_length=80,
                           label=_("Instance Name"),
                           initial="synthesized_vm")

    flavor = forms.ChoiceField(label=_("Flavor"),
                               required=True,
                               help_text=_("Size of image to launch."))

    class Meta:
        name = _("VM overlay Info")
        help_text_template = ("project/cloudlet/instance/"
                              "_synthesis_details_help.html")

    def clean(self):
        cleaned_data = super(SetSynthesizeDetailsAction, self).clean()

        overlay_url = cleaned_data.get('overlay_url', None)
        if overlay_url is None:
            raise forms.ValidationError(_("Need URL to fetch VM overlay"))

        # check url format
        val = URLValidator()
        try:
            val(overlay_url)
        except ValidationError, e:
            raise forms.ValidationError(_("Malformed URL for VM overlay"))

        # check url accessibility
        try:
            header_ret = requests.head(overlay_url)
            if header_ret.ok == False:
                raise
        except Exception as e:
            msg = "URL is not accessible : %s" % overlay_url
            raise forms.ValidationError(_(msg))

        if cleaned_data.get('name', None) is None:
            raise forms.ValidationError(_("Need name for the synthesized VM"))

        # finally check the header file of VM overlay
        # to make sure that associated Base VM exists
        matching_image = None
        # requested_basevm_sha256 = ''
        try:
            overlay_package = VMOverlayPackage(overlay_url)
            metadata = overlay_package.read_meta()
            overlay_meta = msgpack.unpackb(metadata)
            requested_basevm_sha256 = overlay_meta.get(Cloudlet_Const.META_BASE_VM_SHA256, None)
            # matching_image = utils.find_basevm_by_sha256(self.request, requested_basevm_sha256)
            basevms = utils.BaseVMs()
            matching_image = basevms.is_exist(self.request, requested_basevm_sha256)
        except Exception:
            msg = "Error while finding matching Base VM with %s" % (requested_basevm_sha256)
            raise forms.ValidationError(_(msg))

        if matching_image is None:
            msg = "Cannot find matching base VM with UUID(%s)" % (requested_basevm_sha256)
            raise forms.ValidationError(_(msg))
        else:
            # specify associated base VM from the metadata
            cleaned_data['image_id'] = str(matching_image.id)
            return cleaned_data

    def _get_available_images(self, request, context):
        if not hasattr(self, '_images_cache'):
            images_cache = {}

        if images_cache is None:
            images_cache = {}

        public_images = images_cache.get('public_images', [])
        images_by_project = images_cache.get('images_by_project', {})
        if 'public_images' not in images_cache:
            public = {"is_public": True,
                      "status": "active"}

            try:
                images, _more, _prev = glance.image_list_detailed(
                    request, filters=public)
                [public_images.append(image) for image in images]
                images_cache['public_images'] = public_images
            except Exception:
                exceptions.handle(request,
                                  _("Unable to retrieve public images."))

        # Preempt if we don't have a project_id yet.
        project_id = context.get('project_id', None)
        if project_id is None:
            images_by_project[project_id] = []

        if project_id not in images_by_project:
            owner = {"property-owner_id": project_id,
                     "status": "active"}
            try:
                owned_images, _more, _prev = glance.image_list_detailed(
                    request, filters=owner)
                images_by_project[project_id] = owned_images
            except Exception:
                owned_images = []
                exceptions.handle(request,
                                  _("Unable to retrieve images for "
                                    "the current project."))
        else:
            owned_images = images_by_project[project_id]

        if 'images_by_project' not in images_cache:
            images_cache['images_by_project'] = images_by_project

        images = owned_images + public_images
        base_vms = list()
        for image in images:
            if hasattr(image, 'properties') == True:
                properties = getattr(image, 'properties')
                cloudlet_type = properties.get('cloudlet_type', None)
                if cloudlet_type == 'cloudlet_base_disk':
                    base_vms.append(image)

        image_ids = []
        final_images = []
        for image in base_vms:
            if image.id not in image_ids:
                image_ids.append(image.id)
                final_images.append(image)
        return [image for image in final_images
                if image.container_format not in ('aki', 'ari')]

    def populate_flavor_choices(self, request, context):
        # return all flavors of Base VM image
        try:
            matching_flavors = set()
            flavors = api.nova.flavor_list(request)
            basevm_images = self._get_available_images(request, context)
            for basevm_image in basevm_images:
                if basevm_image.properties is None or \
                                len(basevm_image.properties) == 0:
                    continue
                libvirt_xml_str = basevm_image.properties.get(
                    'base_resource_xml_str', None)
                if libvirt_xml_str is None:
                    continue
                qemu_mem = utils.QemuMemory()
                cpu_count, memory_mb = qemu_mem.get_resource_size(libvirt_xml_str)
                disk_gb = basevm_image.min_disk
                ret_flavors = utils.find_matching_flavor(flavors,
                                                         cpu_count,
                                                         memory_mb,
                                                         disk_gb)
                matching_flavors.update(ret_flavors)
            if len(matching_flavors) > 0:
                self.fields['flavor'].initial = list(matching_flavors)[0]
            else:
                self.fields['flavor'].initial = (0, "No valid flavor")
        except Exception as e:
            matching_flavors = set()
            exceptions.handle(request,
                              _('Unable to retrieve instance flavors.'))
        return sorted(list(matching_flavors))

    def get_help_text(self):
        extra = {}
        try:
            extra['usages'] = quotas.tenant_quota_usages(self.request)
            extra['usages_json'] = json.dumps(extra['usages'])
            flavors = json.dumps([f._info for f in
                                  api.nova.flavor_list(self.request)])
            extra['flavors'] = flavors
        except:
            exceptions.handle(self.request,
                              _("Unable to retrieve quota information."))
        return super(SetSynthesizeDetailsAction, self).get_help_text(extra)


class SetSynthesizeAction(workflows.Step):
    action_class = SetSynthesizeDetailsAction
    contributes = ("image_id", "overlay_url", "name", "flavor")


class SynthesisInstance(workflows.Workflow):
    slug = "cloudlet_syntehsize_VM"
    name = _("Cloudlet Synthesize VM")
    finalize_button_name = _("Synthesize")
    success_message = _('Cloudlet synthesized %(count)s named "%(name)s".')
    failure_message = _('Cloudlet is unable to synthesize %(count)s named "%(name)s".')
    success_url = "horizon:project:cloudlet:index"
    default_steps = (SelectProjectUser,
                     SetSynthesizeAction,
                     SetAccessControls,
                     SetNetwork)

    def format_status_message(self, message):
        name = self.context.get('name', 'unknown instance')
        count = self.context.get('count', 1)
        if int(count) > 1:
            return message % {"count": _("%s instances") % count,
                              "name": name}
        else:
            return message % {"count": _("instance"), "name": name}

    @sensitive_variables('context')
    def handle(self, request, context):
        dev_mapping = None
        user_script = None

        netids = context.get('network_id', None)
        if netids:
            nics = [{"net-id": netid, "v4-fixed-ip": ""}
                    for netid in netids]
        else:
            nics = None

        port_profiles_supported = api.neutron.is_port_profiles_supported()

        if port_profiles_supported:
            nics = self.set_network_port_profiles(request,
                                                  context['network_id'],
                                                  context['profile_id'])

        ports = context.get('ports')
        if ports:
            if nics is None:
                nics = []
            nics.extend([{'port-id': port} for port in ports])

        meta = {"overlay_url": context['overlay_url']}
        try:
            api.nova.server_create(request,
                                   context['name'],
                                   context['image_id'],
                                   context['flavor'],
                                   context['keypair_id'],
                                   user_script,
                                   context['security_group_ids'],
                                   dev_mapping,
                                   nics=nics,
                                   instance_count=1,
                                   meta=meta)
            return True
        except:
            exceptions.handle(request)
            return False

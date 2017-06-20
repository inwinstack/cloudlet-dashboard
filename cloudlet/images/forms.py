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

import logging
import os
import shutil

from django.conf import settings
from django.forms import ValidationError
from django.forms.widgets import HiddenInput
from django.utils.translation import ugettext_lazy as _

from horizon import exceptions
from horizon import forms
from horizon import messages

from openstack_dashboard import api
from openstack_dashboard import policy

from openstack_dashboard.dashboards.project.cloudlet import utils


LOG = logging.getLogger(__name__)


def create_image_metadata(data, name, path, glance_ref=None):
    meta = {'name': name,
            'data': open(path, "rb"),
            'disk_format': 'raw',
            'container_format': 'bare',
            'min_disk': (data['minimum_disk'] or 0),
            'min_ram': (data['minimum_ram'] or 0)}

    is_public = data.get('is_public', data.get('public', False))
    cloudlet_types = {
        'disk': 'cloudlet_base_disk',
        'memory': 'cloudlet_base_memory',
        'diskhash': 'cloudlet_base_disk_hash',
        'memhash': 'cloudlet_base_memory_hash'
    }

    base_type = cloudlet_types.get(name.split("-")[1])
    properties = {
        'image_type': 'snapshot',
        'image_location': 'snapshot',
        'is_cloudlet': 'True',
        'cloudlet_type': base_type,
        'base_sha256_uuid': data['base_hashvalue']
    }

    if glance_ref is not None:
        properties.update(glance_ref)

    if api.glance.VERSIONS.active < 2:
        meta.update({'is_public': is_public, 'properties': properties})
    else:
        meta['visibility'] = 'public' if is_public else 'private'
        meta.update(properties)

    return meta


class ImportBaseForm(forms.SelfHandlingForm):
    name = forms.CharField(
        max_length=255,
        label=_("Name"),
        widget=forms.TextInput(attrs={
            'placeholder': 'ubuntu-base'}),
        required=True)
    image_file = forms.FileField(
        label=_("Image File"),
        help_text=("A local image to upload."),
        required=False)
    is_public = forms.BooleanField(
        label=_("Public"),
        required=False,
        initial=True)

    def __init__(self, request, *args, **kwargs):
        super(ImportBaseForm, self).__init__(request, *args, **kwargs)

        if (api.glance.get_image_upload_mode() == 'off' or
                not policy.check((("image", "upload_image"),), request)):
            self._hide_file_source_type()

        # GlanceV2 feature removals
        if api.glance.VERSIONS.active >= 2:
            # NOTE: GlanceV2 doesn't support copy-from feature, sorry!
            if not getattr(settings, 'IMAGES_ALLOW_LOCATION', False):
                if (api.glance.get_image_upload_mode() == 'off' or not
                policy.check((("image", "upload_image"),), request)):
                    # Neither setting a location nor uploading image data is
                    # allowed, so throw an error.
                    msg = _('The current Horizon settings indicate no valid '
                            'image creation methods are available. Providing '
                            'an image location and/or uploading from the '
                            'local file system must be allowed to support '
                            'image creation.')
                    messages.error(request, msg)
                    raise ValidationError(msg)
        if not policy.check((("image", "publicize_image"),), request):
            self._hide_is_public()

    def _hide_file_source_type(self):
        self.fields['image_file'].widget = HiddenInput()
        source_type = self.fields['source_type']
        source_type.choices = [choice for choice in source_type.choices
                               if choice[0] != 'file']
        if len(source_type.choices) == 1:
            source_type.widget = HiddenInput()

    def _hide_is_public(self):
        self.fields['is_public'].widget = HiddenInput()
        self.fields['is_public'].initial = False

    def clean(self):
        data = super(ImportBaseForm, self).clean()

        # The image_file key can be missing based on particular upload
        # conditions. Code defensively for it here...
        image_file = data.get('image_file', None)
        if not image_file:
            msg = _("An image file or an external location must be specified.")
            raise ValidationError({'image_file': [msg, ]})
        else:
            # TODO: Useing Cloudlet APIs not using Class.
            basevms = utils.BaseVMs()
            if basevms.zipfile(data['image_file']):
                tree = basevms.xml_data()
                if tree is None:
                    msg = _('Image File is not valid, no manifest file')
                    raise ValidationError({'image_file': [msg, ]})
                else:
                    base_hashvalue = tree.get('hash_value')
                    data['base_hashvalue'] = base_hashvalue
                    matching_base = basevms.is_exist(self.request, base_hashvalue)
                    if matching_base is not None:
                        msg = _("Base VM exists : UUID(%s)" % matching_base.id)
                        raise ValidationError(msg)

                    return data
            else:
                msg = _("Image File is not valid, not a zipped base VM")
                raise ValidationError({'image_file': [msg, ]})

    def handle(self, request, data):
        # TODO: Useing Cloudlet APIs not using Class.
        basevms = utils.BaseVMs()
        if basevms.zipfile(data['image_file']):
            tree = basevms.xml_data()
            basevms_path = basevms.path(tree)
            temp_dir = basevms.unzip()
        # Get Base VM CPU count, memory size(MB) and disk size(GB)
        qemu_mem = utils.QemuMemory()
        libvirt_xml_str = qemu_mem.libvirt_xml(os.path.join(temp_dir, basevms_path['memory']))
        cpu_count, memory_size_mb = qemu_mem.get_resource_size(libvirt_xml_str)
        disk_gb = basevms.min_disk(os.path.join(temp_dir, basevms_path['disk']))
        data['minimum_ram'] = memory_size_mb
        data['minimum_disk'] = disk_gb
        # Check Base VM spec (CPU core, memory size and disk size) is exitsing Flavor list
        if cpu_count is None or memory_size_mb is None:
            msg = "Cannot find memory size or CPU number of Base VM"
            raise ValidationError(_(msg))
        else:
            flavors = api.nova.flavor_list(request)
            ref_flavors = utils.find_matching_flavor(flavors, cpu_count, memory_size_mb, disk_gb)
            if len(ref_flavors) == 0:
                flavor_name = "cloudlet-flavor-%s" % data['name']
                api.nova.flavor_create(self.request,
                                       flavor_name,
                                       memory_size_mb,
                                       cpu_count,
                                       disk_gb,
                                       is_public=True)
                msg = "Create new flavor %s with (cpu:%d, memory:%d, disk:%d)" % \
                      (flavor_name, cpu_count, memory_size_mb, disk_gb)
                LOG.info(msg)

        try:
            # Create image metadata and Upload image to glance without disk image
            glance_ref = {'base_resource_xml_str': libvirt_xml_str.replace("\n", "")}
            for key, value in basevms_path.iteritems():
                name = data['name'] + "-" + key
                path = os.path.join(temp_dir, value)
                if key == 'disk':
                    continue
                meta = create_image_metadata(data, name, path)
                image = api.glance.image_create(request, **meta)
                glance_ref[image.properties.get("cloudlet_type", None)] = image.id

            # Create disk image metadata and Upload image
            disk_name = data['name'] + "-disk"
            disk_path = os.path.join(temp_dir, basevms_path['disk'])
            meta = create_image_metadata(data, disk_name, disk_path, glance_ref)
            image = api.glance.image_create(request, **meta)
            # All Base VM zip file upload to glance success
            messages.info(request,
                          _('Your image %s has been queued for creation.') %
                          meta['name'])
            # Delete Base VM unzip temp directory
            dirpath = os.path.dirname(os.path.join(temp_dir, basevms_path['disk']))
            if os.path.exists(dirpath):
                shutil.rmtree(dirpath)
            return image
        except Exception as e:
            msg = _('Unable to create new image')
            if hasattr(e, 'code') and e.code == 400:
                if "Invalid disk format" in e.details:
                    msg = _('Unable to create new image: Invalid disk format '
                            '%s for image.') % meta['disk_format']
                elif "Image name too long" in e.details:
                    msg = _('Unable to create new image: Image name too long.')
                elif "not supported" in e.details:
                    msg = _('Unable to create new image: URL scheme not '
                            'supported.')

            exceptions.handle(request, msg)

            return False


class UpdateImageForm(forms.SelfHandlingForm):
    image_id = forms.CharField(widget=forms.HiddenInput())
    name = forms.CharField(max_length=255, label=_("Name"))
    public = forms.BooleanField(label=_("Public"), required=False)

    def __init__(self, request, *args, **kwargs):
        super(UpdateImageForm, self).__init__(request, *args, **kwargs)

        if not policy.check((("image", "publicize_image"),), request):
            self.fields['public'].widget = forms.CheckboxInput(
                attrs={'readonly': 'readonly', 'disabled': 'disabled'})
            self.fields['public'].help_text = _(
                'Non admin users are not allowed to make images public.')

    def handle(self, request, data):
        image_id = data['image_id']
        error_updating = _('Unable to update image "%s".')
        meta = create_image_metadata(data)

        try:
            image = api.glance.image_update(request, image_id, **meta)
            messages.success(request, _('Image was successfully updated.'))
            return image
        except Exception:
            exceptions.handle(request, error_updating % image_id)

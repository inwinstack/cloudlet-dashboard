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

from collections import OrderedDict
import logging

from django.utils.translation import ugettext_lazy as _

from horizon import exceptions
from horizon import messages
from horizon import tables

from openstack_dashboard import api
from openstack_dashboard import policy

from openstack_dashboard.dashboards.project.cloudlet import utils
from openstack_dashboard.dashboards.project.cloudlet.images \
    import tables as images_tables
from openstack_dashboard.dashboards.project.cloudlet.instances \
    import tables as instances_tables


LOG = logging.getLogger(__name__)


class IndexView(tables.MultiTableView):
    table_classes = (images_tables.BaseVMsTable,
                     images_tables.VMOverlaysTable,
                     instances_tables.InstancesTable)
    template_name = 'project/cloudlet/index.html'
    page_title = _("Cloudlet")

    def has_prev_data(self, table):
        return getattr(self, "_prev", False)

    def has_more_data(self, table):
        return getattr(self, "_more", False)

    def get_images_data(self):
        if not policy.check((("image", "get_images"),), self.request):
            msg = _("Insufficient privilege level to retrieve image list.")
            messages.info(self.request, msg)
            return []
        prev_marker = self.request.GET.get(
            images_tables.BaseVMsTable._meta.prev_pagination_param, None)

        if prev_marker is not None:
            marker = prev_marker
        else:
            marker = self.request.GET.get(
                images_tables.BaseVMsTable._meta.pagination_param, None)
        reversed_order = prev_marker is not None
        try:
            all_images, self._more, self._prev = api.glance.image_list_detailed(
                self.request,
                marker=marker,
                paginate=True,
                sort_dir='asc',
                sort_key='name',
                reversed_order=reversed_order)
            images = [im for im in all_images
                      if im.properties.get("cloudlet_type", None) == 'cloudlet_base_disk']
        except Exception:
            images = []
            self._prev = self._more = False
            exceptions.handle(self.request, _("Unable to retrieve images."))
        return images

    def get_overlays_data(self):
        if not policy.check((("image", "get_images"),), self.request):
            msg = _("Insufficient privilege level to retrieve image list.")
            messages.info(self.request, msg)
            return []
        prev_marker = self.request.GET.get(
            images_tables.VMOverlaysTable._meta.prev_pagination_param, None)

        if prev_marker is not None:
            marker = prev_marker
        else:
            marker = self.request.GET.get(
                images_tables.VMOverlaysTable._meta.pagination_param, None)
        reversed_order = prev_marker is not None
        try:
            images, self._more, self._prev = api.glance.image_list_detailed(
                self.request,
                marker=marker,
                paginate=True,
                sort_dir='asc',
                sort_key='name',
                reversed_order=reversed_order)
        except Exception:
            images = []
            self._prev = self._more = False
            exceptions.handle(self.request, _("Unable to retrieve images."))
        return images

    def get_instances_data(self):
        try:
            instances, self._more = api.nova.server_list(self.request)
        except Exception:
            self._more = False
            instances = []
            exceptions.handle(self.request,
                              _('Unable to retrieve instances.'))

        if instances:
            try:
                api.network.servers_update_addresses(self.request, instances)
            except Exception:
                exceptions.handle(
                    self.request,
                    message=_('Unable to retrieve IP addresses from Neutron.'),
                    ignore=True)

            # Gather our flavors and images and correlate our instances to them
            filtered_instances = list()
            try:
                flavors = api.nova.flavor_list(self.request)
            except Exception:
                flavors = []
                exceptions.handle(self.request, ignore=True)

            try:
                # TODO(gabriel): Handle pagination.
                images, more, prev = api.glance.image_list_detailed(
                    self.request)
            except Exception:
                images = []
                exceptions.handle(self.request, ignore=True)

            full_flavors = OrderedDict([(str(flavor.id), flavor)
                                        for flavor in flavors])
            image_map = OrderedDict([(str(image.id), image)
                                     for image in images])

            # Loop through instances to get flavor info.
            for instance in instances:
                if hasattr(instance, 'image'):
                    # Instance from image returns dict
                    if isinstance(instance.image, dict):
                        if instance.image.get('id') in image_map:
                            instance.image = image_map[instance.image['id']]

                try:
                    flavor_id = instance.flavor["id"]
                    if flavor_id in full_flavors:
                        instance.full_flavor = full_flavors[flavor_id]
                    else:
                        # If the flavor_id is not in full_flavors list,
                        # get it via nova api.
                        instance.full_flavor = api.nova.flavor_get(
                            self.request, flavor_id)
                except Exception:
                    msg = ('Unable to retrieve flavor "%s" for instance "%s".'
                           % (flavor_id, instance.id))
                    LOG.info(msg)

            for instance in instances:
                instance_type = utils.get_cloudlet_type(instance)
                if instance_type == 'cloudlet_base_disk':
                    filtered_instances.append(instance)
                    setattr(instance, 'cloudlet_type', "Resumed Base VM")
                if instance_type == 'cloudlet_overlay':
                    filtered_instances.append(instance)
                    setattr(instance, 'cloudlet_type', "Provisioned VM")

        return filtered_instances

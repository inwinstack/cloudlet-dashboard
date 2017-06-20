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
from django.template import defaultfilters as filters
from django.utils.http import urlencode
from django.utils.translation import pgettext_lazy
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from horizon import tables
from horizon.utils.memoized import memoized

from openstack_dashboard import api


class DownloadImage(tables.LinkAction):
    name = "download_overlay"
    verbose_name = _("Download VM overlay")
    verbose_name_plural = _("Download VM overlays")
    classes = ("btn-download",)
    url = "horizon:project:cloudlet:images:download"

    def allowed(self, request, image=None):
        if image:
            return image.owner == request.user.tenant_id
        return True

    def get_link_url(self, datum):
        base_url = reverse(self.url)
        params = urlencode({"image_id": self.table.get_object_id(datum),
                            "image_name": getattr(datum, "name", "vm-overlay")})
        return "?".join([base_url, params])


class EditImage(tables.LinkAction):
    name = "edit"
    verbose_name = _("Edit Image")
    url = "horizon:project:cloudlet:images:update"
    classes = ("ajax-modal",)
    icon = "pencil"
    policy_rules = (("image", "modify_image"),)

    def allowed(self, request, image=None):
        if image:
            return image.status in ("active",) and \
                image.owner == request.user.tenant_id
        return False


class ImportBaseVM(tables.LinkAction):
    name = "import"
    verbose_name = _("Import Base VM")
    url = "horizon:project:cloudlet:images:import"
    classes = ("ajax-modal", "btn-create")
    icon = "plus"


class ResumeBaseVM(tables.LinkAction):
    name = "resume_base_vm"
    verbose_name = _("Resume Base VM")
    url = "horizon:project:cloudlet:instances:resume"
    classes = ("btn-launch", "ajax-modal")

    def get_link_url(self, datum):
        base_url = reverse(self.url)
        params = urlencode({"source_type": "image_id",
                            "source_id": self.table.get_object_id(datum)})
        return "?".join([base_url, params])


class DeleteImage(tables.DeleteAction):
    # NOTE: The bp/add-batchactions-help-text
    # will add appropriate help text to some batch/delete actions.
    help_text = _("Deleted images are not recoverable.")

    @staticmethod
    def action_present(count):
        return ungettext_lazy(
            u"Delete Image",
            u"Delete Images",
            count
        )

    @staticmethod
    def action_past(count):
        return ungettext_lazy(
            u"Deleted Image",
            u"Deleted Images",
            count
        )

    policy_rules = (("image", "delete_image"),)

    def allowed(self, request, image=None):
        # Protected images can not be deleted.
        if image and image.protected:
            return False
        if image:
            return image.owner == request.user.tenant_id
        # Return True to allow table-level bulk delete action to appear.
        return True

    def delete(self, request, obj_id):
        api.glance.image_delete(request, obj_id)


def filter_tenants():
    return getattr(settings, 'IMAGES_LIST_FILTER_TENANTS', [])


@memoized
def filter_tenant_ids():
    return map(lambda ft: ft['tenant'], filter_tenants())


def get_image_categories(im, user_tenant_id):
    categories = []
    if im.is_public:
        categories.append('public')
    if im.owner == user_tenant_id:
        categories.append('project')
    elif im.owner in filter_tenant_ids():
        categories.append(im.owner)
    elif not im.is_public:
        categories.append('shared')
    return categories


def get_image_type(image):
    return getattr(image, "properties", {}).get("image_type", _("Image"))


class UpdateRow(tables.Row):
    ajax = True

    def get_data(self, request, image_id):
        image = api.glance.image_get(request, image_id)
        return image

    def load_cells(self, image=None):
        super(UpdateRow, self).load_cells(image)
        # Tag the row with the image category for client-side filtering.
        image = self.datum
        my_tenant_id = self.table.request.user.tenant_id
        image_categories = get_image_categories(image, my_tenant_id)
        for category in image_categories:
            self.classes.append('category-' + category)


class BaseVMsTable(tables.DataTable):
    STATUS_CHOICES = (
        ("active", True),
        ("saving", None),
        ("queued", None),
        ("pending_delete", None),
        ("killed", False),
        ("resume", False),
    )
    STATUS_DISPLAY_CHOICES = (
        ("active", pgettext_lazy("Current status of an Image", u"Active")),
        ("saving", pgettext_lazy("Current status of an Image", u"Saving")),
        ("queued", pgettext_lazy("Current status of an Image", u"Queued")),
        ("pending_delete", pgettext_lazy("Current status of an Image",
                                         u"Pending Delete")),
        ("killed", pgettext_lazy("Current status of an Image", u"Killed")),
        ("deleted", pgettext_lazy("Current status of an Image", u"Deleted")),
        ("deactivated", pgettext_lazy("Current status of an Image",
                                      u"Deactivated")),
    )
    name = tables.Column("name",
                         link=("horizon:project:images:images:detail"),
                         verbose_name=_("Base VM Images"))
    # image_type = tables.Column(get_image_type,
    #                            verbose_name=_("Type"),
    #                            filters=(filters.title,))
    status = tables.Column("status",
                           verbose_name=_("Status"),
                           status=True,
                           status_choices=STATUS_CHOICES,
                           display_choices=STATUS_DISPLAY_CHOICES)
    public = tables.Column("is_public",
                           verbose_name=_("Public"),
                           empty_value=False,
                           filters=(filters.yesno, filters.capfirst))

    class Meta:
        name = "images"
        row_class = UpdateRow
        status_columns = ["status"]
        verbose_name = _("Base VMs")
        hidden_title = False
        table_actions = (ImportBaseVM, DeleteImage,)
        row_actions = (ResumeBaseVM, EditImage, DeleteImage,)


class VMOverlaysTable(tables.DataTable):
    STATUS_CHOICES = (
        ("active", True),
        ("saving", None),
        ("queued", None),
        ("pending_delete", None),
        ("killed", False),
        ("resume", False),
    )
    STATUS_DISPLAY_CHOICES = (
        ("active", pgettext_lazy("Current status of an Image", u"Active")),
        ("saving", pgettext_lazy("Current status of an Image", u"Saving")),
        ("queued", pgettext_lazy("Current status of an Image", u"Queued")),
        ("pending_delete", pgettext_lazy("Current status of an Image",
                                         u"Pending Delete")),
        ("killed", pgettext_lazy("Current status of an Image", u"Killed")),
        ("deleted", pgettext_lazy("Current status of an Image", u"Deleted")),
        ("deactivated", pgettext_lazy("Current status of an Image",
                                      u"Deactivated")),
    )
    name = tables.Column("name",
                         link=("horizon:project:images:images:detail"),
                         verbose_name=_("VM Overlays"))
    # image_type = tables.Column(get_image_type,
    #                            verbose_name=_("Type"),
    #                            filters=(filters.title,))
    status = tables.Column("status",
                           verbose_name=_("Status"),
                           status=True,
                           status_choices=STATUS_CHOICES,
                           display_choices=STATUS_DISPLAY_CHOICES)
    public = tables.Column("is_public",
                           verbose_name=_("Public"),
                           empty_value=False,
                           filters=(filters.yesno, filters.capfirst))

    class Meta:
        name = "overlays"
        row_class = UpdateRow
        status_columns = ["status"]
        verbose_name = _("VM Overlays")
        hidden_title = False
        table_actions = (DeleteImage,)
        row_actions = (DownloadImage, EditImage, DeleteImage,)

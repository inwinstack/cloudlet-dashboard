import logging

from django import template
from django.core import urlresolvers
from django.template.defaultfilters import title
from django.utils.http import urlencode
from django.utils.translation import pgettext_lazy
from django.utils.translation import string_concat
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy
import six

from horizon import tables
from horizon import exceptions
from horizon import messages
from horizon.templatetags import sizeformat
from horizon.utils import filters

from openstack_dashboard import api
from openstack_dashboard import policy
from openstack_dashboard.dashboards.project.cloudlet import cloudlet_api
from openstack_dashboard.dashboards.project.cloudlet import utils
from openstack_dashboard.dashboards.project.instances.workflows \
    import update_instance


LOG = logging.getLogger(__name__)

ACTIVE_STATES = ("ACTIVE",)

POWER_STATES = {
    0: "NO STATE",
    1: "RUNNING",
    2: "BLOCKED",
    3: "PAUSED",
    4: "SHUTDOWN",
    5: "SHUTOFF",
    6: "CRASHED",
    7: "SUSPENDED",
    8: "FAILED",
    9: "BUILDING",
}

PAUSE = 0
UNPAUSE = 1
SUSPEND = 0
RESUME = 1


def is_deleting(instance):
    task_state = getattr(instance, "OS-EXT-STS:task_state", None)
    if not task_state:
        return False
    return task_state.lower() == "deleting"


class DeleteInstance(policy.PolicyTargetMixin, tables.DeleteAction):
    policy_rules = (("compute", "compute:delete"),)
    help_text = _("Deleted instances are not recoverable.")

    @staticmethod
    def action_present(count):
        return ungettext_lazy(
            u"Delete Instance",
            u"Delete Instances",
            count
        )

    @staticmethod
    def action_past(count):
        return ungettext_lazy(
            u"Scheduled deletion of Instance",
            u"Scheduled deletion of Instances",
            count
        )

    def allowed(self, request, instance=None):
        """Allow delete action if instance is in error state or not currently
        being deleted.
        """
        error_state = False
        if instance:
            error_state = (instance.status == 'ERROR')
        return error_state or not is_deleting(instance)

    def action(self, request, obj_id):
        api.nova.server_delete(request, obj_id)


class CreateOverlayAction(tables.BatchAction):
    name = "overlay"
    verbose_name = _("CreateVMOverlay")

    @staticmethod
    def action_present(count):
        return ungettext_lazy(
            u"Create VM overlay",
            u"Create VM overlays",
            count
        )

    @staticmethod
    def action_past(count):
        return ungettext_lazy(
            u"Scheduled Creation of VM Overlay ",
            u"Scheduled Creation of VM Overlays ",
            count
        )

    def allowed(self, request, instance=None):
        is_active = instance.status in ACTIVE_STATES
        is_resumed_base = False
        cloudlet_type = utils.get_cloudlet_type(instance)
        if cloudlet_type == 'cloudlet_base_disk':
            is_resumed_base = True

        return is_active and is_resumed_base

    def action(self, request, obj_id):
        # TODO: call cloudlet api to create overlay
        ret_dict = cloudlet_api.request_create_overlay(request, obj_id)


class VMSynthesisLink(tables.LinkAction):
    name = "synthesis"
    verbose_name = _("Start VM Synthesis")
    url = "horizon:project:cloudlet:instances:synthesis"
    classes = ("btn-launch", "ajax-modal")
    icon = "plus"

    def __init__(self, attrs=None, **kwargs):
        kwargs['preempt'] = True
        super(VMSynthesisLink, self).__init__(attrs, **kwargs)

    def allowed(self, request, datum):
        try:
            limits = api.nova.tenant_absolute_limits(request, reserved=True)

            instances_available = limits['maxTotalInstances'] \
                - limits['totalInstancesUsed']
            cores_available = limits['maxTotalCores'] \
                - limits['totalCoresUsed']
            ram_available = limits['maxTotalRAMSize'] - limits['totalRAMUsed']

            if instances_available <= 0 or cores_available <= 0 \
                    or ram_available <= 0:
                if "disabled" not in self.classes:
                    self.classes = [c for c in self.classes] + ['disabled']
                    self.verbose_name = string_concat(self.verbose_name, ' ',
                                                      _("(Quota exceeded)"))
            else:
                self.verbose_name = _("Start VM Synthesis")
                classes = [c for c in self.classes if c != "disabled"]
                self.classes = classes
        except Exception:
            LOG.exception("Failed to retrieve quota information")
            # If we can't get the quota information, leave it to the
            # API to check when launching
        return True  # The action should always be displayed


class EditInstance(policy.PolicyTargetMixin, tables.LinkAction):
    name = "edit"
    verbose_name = _("Edit Instance")
    url = "horizon:project:instances:update"
    classes = ("ajax-modal",)
    icon = "pencil"
    policy_rules = (("compute", "compute:update"),)

    def get_link_url(self, project):
        return self._get_link_url(project, 'instance_info')

    def _get_link_url(self, project, step_slug):
        base_url = urlresolvers.reverse(self.url, args=[project.id])
        next_url = self.table.get_full_url()
        params = {"step": step_slug,
                  update_instance.UpdateInstance.redirect_param_name: next_url}
        param = urlencode(params)
        return "?".join([base_url, param])

    def allowed(self, request, instance):
        return not is_deleting(instance)


class VMHandoffLink(tables.LinkAction):
    name = "handoff"
    verbose_name = _("VM Handoff")
    url = "horizon:project:cloudlet:instances:handoff"
    classes = ("btn-danger", "btn-terminate", "ajax-modal",)
    icon = "pencil"

    def allowed(self, request, instance=None):
        is_active = instance.status in ACTIVE_STATES
        is_synthesized = False
        cloudlet_type = utils.get_cloudlet_type(instance)
        if cloudlet_type == 'cloudlet_overlay':
            is_synthesized = True
        return is_synthesized

    def get_link_url(self, datum):
        instance_id = self.table.get_object_id(datum)
        return urlresolvers.reverse(self.url, args=[instance_id])


def instance_fault_to_friendly_message(instance):
    fault = getattr(instance, 'fault', {})
    message = fault.get('message', _("Unknown"))
    default_message = _("Please try again later [Error: %s].") % message
    fault_map = {
        'NoValidHost': _("There is not enough capacity for this "
                         "flavor in the selected availability zone. "
                         "Try again later or select a different availability "
                         "zone.")
    }
    return fault_map.get(message, default_message)


def get_instance_error(instance):
    if instance.status.lower() != 'error':
        return None
    message = instance_fault_to_friendly_message(instance)
    preamble = _('Failed to perform requested operation on instance "%s", the '
                 'instance has an error status') % instance.name or instance.id
    message = string_concat(preamble, ': ', message)
    return message


class UpdateRow(tables.Row):
    ajax = True

    def get_data(self, request, instance_id):
        instance = api.nova.server_get(request, instance_id)
        try:
            instance.full_flavor = api.nova.flavor_get(request,
                                                       instance.flavor["id"])
        except Exception:
            exceptions.handle(request,
                              _('Unable to retrieve flavor information '
                                'for instance "%s".') % instance_id,
                              ignore=True)
        try:
            api.network.servers_update_addresses(request, [instance])
        except Exception:
            exceptions.handle(request,
                              _('Unable to retrieve Network information '
                                'for instance "%s".') % instance_id,
                              ignore=True)
        error = get_instance_error(instance)
        if error:
            messages.error(request, error)
        return instance


def cloudlet_type(instance):
    if hasattr(instance, "cloudlet_type"):
        cloudlet_type = getattr(instance, "cloudlet_type")
        return cloudlet_type
    return _("VM instance")


def get_ips(instance):
    template_name = 'project/instances/_instance_ips.html'
    ip_groups = {}

    for ip_group, addresses in six.iteritems(instance.addresses):
        ip_groups[ip_group] = {}
        ip_groups[ip_group]["floating"] = []
        ip_groups[ip_group]["non_floating"] = []

        for address in addresses:
            if ('OS-EXT-IPS:type' in address and
               address['OS-EXT-IPS:type'] == "floating"):
                ip_groups[ip_group]["floating"].append(address)
            else:
                ip_groups[ip_group]["non_floating"].append(address)

    context = {
        "ip_groups": ip_groups,
    }
    return template.loader.render_to_string(template_name, context)


def get_size(instance):
    if hasattr(instance, "full_flavor"):
        template_name = 'project/instances/_instance_flavor.html'
        size_ram = sizeformat.mb_float_format(instance.full_flavor.ram)
        if instance.full_flavor.disk > 0:
            size_disk = sizeformat.diskgbformat(instance.full_flavor.disk)
        else:
            size_disk = _("%s GB") % "0"
        context = {
            "name": instance.full_flavor.name,
            "id": instance.id,
            "size_disk": size_disk,
            "size_ram": size_ram,
            "vcpus": instance.full_flavor.vcpus,
            "flavor_id": instance.full_flavor.id
        }
        return template.loader.render_to_string(template_name, context)
    return _("Not available")


def get_power_state(instance):
    return POWER_STATES.get(getattr(instance, "OS-EXT-STS:power_state", 0), '')


STATUS_DISPLAY_CHOICES = (
    ("deleted", pgettext_lazy("Current status of an Instance", u"Deleted")),
    ("active", pgettext_lazy("Current status of an Instance", u"Active")),
    ("shutoff", pgettext_lazy("Current status of an Instance", u"Shutoff")),
    ("suspended", pgettext_lazy("Current status of an Instance",
                                u"Suspended")),
    ("paused", pgettext_lazy("Current status of an Instance", u"Paused")),
    ("error", pgettext_lazy("Current status of an Instance", u"Error")),
    ("resize", pgettext_lazy("Current status of an Instance",
                             u"Resize/Migrate")),
    ("verify_resize", pgettext_lazy("Current status of an Instance",
                                    u"Confirm or Revert Resize/Migrate")),
    ("revert_resize", pgettext_lazy(
        "Current status of an Instance", u"Revert Resize/Migrate")),
    ("reboot", pgettext_lazy("Current status of an Instance", u"Reboot")),
    ("hard_reboot", pgettext_lazy("Current status of an Instance",
                                  u"Hard Reboot")),
    ("password", pgettext_lazy("Current status of an Instance", u"Password")),
    ("rebuild", pgettext_lazy("Current status of an Instance", u"Rebuild")),
    ("migrating", pgettext_lazy("Current status of an Instance",
                                u"Migrating")),
    ("build", pgettext_lazy("Current status of an Instance", u"Build")),
    ("rescue", pgettext_lazy("Current status of an Instance", u"Rescue")),
    ("soft-delete", pgettext_lazy("Current status of an Instance",
                                  u"Soft Deleted")),
    ("shelved", pgettext_lazy("Current status of an Instance", u"Shelved")),
    ("shelved_offloaded", pgettext_lazy("Current status of an Instance",
                                        u"Shelved Offloaded")),
    # these vm states are used when generating CSV usage summary
    ("building", pgettext_lazy("Current status of an Instance", u"Building")),
    ("stopped", pgettext_lazy("Current status of an Instance", u"Stopped")),
    ("rescued", pgettext_lazy("Current status of an Instance", u"Rescued")),
    ("resized", pgettext_lazy("Current status of an Instance", u"Resized")),
)

TASK_DISPLAY_NONE = pgettext_lazy("Task status of an Instance", u"None")

# Mapping of task states taken from Nova's nova/compute/task_states.py
TASK_DISPLAY_CHOICES = (
    ("scheduling", pgettext_lazy("Task status of an Instance",
                                 u"Scheduling")),
    ("block_device_mapping", pgettext_lazy("Task status of an Instance",
                                           u"Block Device Mapping")),
    ("networking", pgettext_lazy("Task status of an Instance",
                                 u"Networking")),
    ("spawning", pgettext_lazy("Task status of an Instance", u"Spawning")),
    ("image_snapshot", pgettext_lazy("Task status of an Instance",
                                     u"Snapshotting")),
    ("image_snapshot_pending", pgettext_lazy("Task status of an Instance",
                                             u"Image Snapshot Pending")),
    ("image_pending_upload", pgettext_lazy("Task status of an Instance",
                                           u"Image Pending Upload")),
    ("image_uploading", pgettext_lazy("Task status of an Instance",
                                      u"Image Uploading")),
    ("image_backup", pgettext_lazy("Task status of an Instance",
                                   u"Image Backup")),
    ("updating_password", pgettext_lazy("Task status of an Instance",
                                        u"Updating Password")),
    ("resize_prep", pgettext_lazy("Task status of an Instance",
                                  u"Preparing Resize or Migrate")),
    ("resize_migrating", pgettext_lazy("Task status of an Instance",
                                       u"Resizing or Migrating")),
    ("resize_migrated", pgettext_lazy("Task status of an Instance",
                                      u"Resized or Migrated")),
    ("resize_finish", pgettext_lazy("Task status of an Instance",
                                    u"Finishing Resize or Migrate")),
    ("resize_reverting", pgettext_lazy("Task status of an Instance",
                                       u"Reverting Resize or Migrate")),
    ("resize_confirming", pgettext_lazy("Task status of an Instance",
                                        u"Confirming Resize or Migrate")),
    ("rebooting", pgettext_lazy("Task status of an Instance", u"Rebooting")),
    ("reboot_pending", pgettext_lazy("Task status of an Instance",
                                     u"Reboot Pending")),
    ("reboot_started", pgettext_lazy("Task status of an Instance",
                                     u"Reboot Started")),
    ("rebooting_hard", pgettext_lazy("Task status of an Instance",
                                     u"Hard Rebooting")),
    ("reboot_pending_hard", pgettext_lazy("Task status of an Instance",
                                          u"Hard Reboot Pending")),
    ("reboot_started_hard", pgettext_lazy("Task status of an Instance",
                                          u"Hard Reboot Started")),
    ("pausing", pgettext_lazy("Task status of an Instance", u"Pausing")),
    ("unpausing", pgettext_lazy("Task status of an Instance", u"Resuming")),
    ("suspending", pgettext_lazy("Task status of an Instance",
                                 u"Suspending")),
    ("resuming", pgettext_lazy("Task status of an Instance", u"Resuming")),
    ("powering-off", pgettext_lazy("Task status of an Instance",
                                   u"Powering Off")),
    ("powering-on", pgettext_lazy("Task status of an Instance",
                                  u"Powering On")),
    ("rescuing", pgettext_lazy("Task status of an Instance", u"Rescuing")),
    ("unrescuing", pgettext_lazy("Task status of an Instance",
                                 u"Unrescuing")),
    ("rebuilding", pgettext_lazy("Task status of an Instance",
                                 u"Rebuilding")),
    ("rebuild_block_device_mapping", pgettext_lazy(
        "Task status of an Instance", u"Rebuild Block Device Mapping")),
    ("rebuild_spawning", pgettext_lazy("Task status of an Instance",
                                       u"Rebuild Spawning")),
    ("migrating", pgettext_lazy("Task status of an Instance", u"Migrating")),
    ("deleting", pgettext_lazy("Task status of an Instance", u"Deleting")),
    ("soft-deleting", pgettext_lazy("Task status of an Instance",
                                    u"Soft Deleting")),
    ("restoring", pgettext_lazy("Task status of an Instance", u"Restoring")),
    ("shelving", pgettext_lazy("Task status of an Instance", u"Shelving")),
    ("shelving_image_pending_upload", pgettext_lazy(
        "Task status of an Instance", u"Shelving Image Pending Upload")),
    ("shelving_image_uploading", pgettext_lazy("Task status of an Instance",
                                               u"Shelving Image Uploading")),
    ("shelving_offloading", pgettext_lazy("Task status of an Instance",
                                          u"Shelving Offloading")),
    ("unshelving", pgettext_lazy("Task status of an Instance",
                                 u"Unshelving")),
)


class InstancesTable(tables.DataTable):
    TASK_STATUS_CHOICES = (
        (None, True),
        ("none", True)
    )
    STATUS_CHOICES = (
        ("active", True),
        ("shutoff", True),
        ("suspended", True),
        ("paused", True),
        ("error", False),
        ("rescue", True),
        ("shelved", True),
        ("shelved_offloaded", True),
    )
    name = tables.WrappingColumn("name",
                                 link="horizon:project:instances:detail",
                                 verbose_name=_("Instance Name"))
    cloudlet_type = tables.Column(cloudlet_type, verbose_name=_("Type"))
    ip = tables.Column(get_ips,
                       verbose_name=_("IP Address"),
                       attrs={'data-type': "ip"})
    size = tables.Column(get_size, sortable=False, verbose_name=_("Size"))
    status = tables.Column("status",
                           filters=(title, filters.replace_underscores),
                           verbose_name=_("Status"),
                           status=True,
                           status_choices=STATUS_CHOICES,
                           display_choices=STATUS_DISPLAY_CHOICES)
    task = tables.Column("OS-EXT-STS:task_state",
                         verbose_name=_("Task"),
                         empty_value=TASK_DISPLAY_NONE,
                         status=True,
                         status_choices=TASK_STATUS_CHOICES,
                         display_choices=TASK_DISPLAY_CHOICES)
    state = tables.Column(get_power_state,
                          filters=(title, filters.replace_underscores),
                          verbose_name=_("Power State"))

    class Meta:
        name = "instances"
        verbose_name = _("Instances")
        status_columns = ["status", "task"]
        hidden_title = False
        row_class = UpdateRow
        table_actions = (VMSynthesisLink,)
        row_actions = (CreateOverlayAction, EditInstance,
                       VMHandoffLink, DeleteInstance)

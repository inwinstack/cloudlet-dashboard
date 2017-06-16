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

import math
import os
import zipfile

from xml.etree import ElementTree
from lxml import etree
from tempfile import mkdtemp

from openstack_dashboard import api

import elijah.provisioning.memory_util as elijah_memory_util
import glanceclient.exc as glance_exceptions
from elijah.provisioning.package import BaseVMPackage


def get_cloudlet_type(instance):
    request = instance.request
    image_id = getattr(instance.image, 'id', None)
    metadata = instance.metadata
    try:
        if image_id is not None:
            image = api.glance.image_get(request, image_id)
            if hasattr(image, 'properties') != True:
                return None
            properties = getattr(image, 'properties')
            if properties == None or \
                properties.get('is_cloudlet') == None:
                return None

            # now it's either resumed base instance or synthesized instance
            # synthesized instance has meta that for overlay URL
            if (metadata.get('overlay_url') is not None) or \
                    (metadata.get('handoff_info') is not None):
                return 'cloudlet_overlay'
            else:
                return 'cloudlet_base_disk'
        else:
            return None
    except glance_exceptions.ClientException:
        return None


def find_matching_flavor(flavor_list, cpu_count, memory_mb, disk_gb):
    ret = set()
    for flavor in flavor_list:
        vcpu = int(flavor.vcpus)
        ram_mb = int(flavor.ram)
        block_gb = int(flavor.disk)
        flavor_name = flavor.name
        if vcpu == cpu_count and ram_mb == memory_mb and disk_gb == block_gb:
            flavor_ref = flavor.links[0]['href']
            flavor_id = flavor.id
            ret.add((flavor_id, "%s" % flavor_name))
    return ret


class BaseVMs():
    def zipfile(self, imagefile):
        is_zipfile = False
        if zipfile.is_zipfile(imagefile):
            self.zipbase = zipfile.ZipFile(imagefile)
            is_zipfile = True
        return is_zipfile

    def xml_data(self):
        if BaseVMPackage.MANIFEST_FILENAME in self.zipbase.namelist():
            xml = self.zipbase.read(BaseVMPackage.MANIFEST_FILENAME)
            tree = etree.fromstring(xml,
                                    etree.XMLParser(
                                        schema=BaseVMPackage.schema
                                    ))
            return tree
        return None

    def path(self, tree):
        data = dict()
        if tree is not None:
            data['disk'] = tree.find(BaseVMPackage.NSP + 'disk').get('path')
            data['memory'] = tree.find(BaseVMPackage.NSP + 'memory').get('path')
            data['diskhash'] = tree.find(BaseVMPackage.NSP + 'disk_hash').get('path')
            data['memhash'] = tree.find(BaseVMPackage.NSP + 'memory_hash').get('path')
        return data

    def is_exist(self, request, base_hashvalue):
        image_detail = api.glance.image_list_detailed(request,
                                                      filters={
                                                          "is_public": True,
                                                          "status": "active"})[0]

        for image in image_detail:
            properties = getattr(image, "properties")
            base_sha256_uuid = properties.get("base_sha256_uuid")
            if base_sha256_uuid == base_hashvalue:
                return image
        return None

    def unzip(self):
        temp_dir = mkdtemp(prefix="cloudlet-base-")
        self.zipbase.extractall(temp_dir)
        return temp_dir

    def min_disk(self, disk_path):
        return int(math.ceil(os.path.getsize(disk_path)/1024/1024/1024))


class QemuMemory():
    def libvirt_xml(self, memory_path):
        return elijah_memory_util._QemuMemoryHeader(open(memory_path)).xml

    def get_resource_size(self, libvirt_xml_str):
        libvirt_xml = ElementTree.fromstring(libvirt_xml_str)
        memory_element = libvirt_xml.find("memory")
        cpu_element = libvirt_xml.find("vcpu")
        if memory_element is not None and cpu_element is not None:
            memory_size = int(memory_element.text)
            memory_unit = memory_element.get("unit").lower()
            if memory_unit != 'mib' and memory_unit != 'mb' and memory_unit != "m":
                if memory_unit == 'kib' or memory_unit == 'kb' or memory_unit == 'k':
                    memory_size = memory_size / 1024
                elif memory_unit == 'gib' or memory_unit == 'gg' or memory_unit == 'g':
                    memory_size = memory_size * 1024
            cpu_count = cpu_element.text
            return int(cpu_count), int(memory_size)
        return None, None

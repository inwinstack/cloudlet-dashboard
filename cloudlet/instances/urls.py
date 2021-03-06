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

from django.conf.urls import url

from openstack_dashboard.dashboards.project.cloudlet.instances import views


INSTANCES = r'^(?P<instance_id>[^/]+)/%s$'

urlpatterns = [
    url(r'^resume/$', views.ResumeInstanceView.as_view(), name='resume'),
    url(r'^synthesis/$', views.SynthesisInstanceView.as_view(), name='synthesis'),
    url(INSTANCES % 'handoff', views.HandoffInstanceView.as_view(), name='handoff'),
]

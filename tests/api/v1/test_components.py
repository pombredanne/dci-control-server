# -*- coding: utf-8 -*-
#
# Copyright (C) 2015-2016 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from __future__ import unicode_literals
import mock
import uuid
from dci.stores.swift import Swift
from dci.common import utils

SWIFT = 'dci.stores.swift.Swift'


def test_create_components(admin, topic_id):
    data = {
        'name': 'pname',
        'type': 'gerrit_review',
        'url': 'http://example.com/',
        'topic_id': topic_id,
        'export_control': True,
        'state': 'active'}
    pc = admin.post('/api/v1/components', data=data).data
    pc_id = pc['component']['id']
    gc = admin.get('/api/v1/components/%s' % pc_id).data
    assert gc['component']['name'] == 'pname'
    assert gc['component']['state'] == 'active'


def test_create_components_already_exist(admin, topic_id):
    data = {'name': 'pname', 'type': 'gerrit_review', 'topic_id': topic_id}
    pstatus_code = admin.post('/api/v1/components', data=data).status_code
    assert pstatus_code == 201

    data = {'name': 'pname', 'type': 'gerrit_review', 'topic_id': topic_id}
    pstatus_code = admin.post('/api/v1/components', data=data).status_code
    assert pstatus_code == 409


def test_create_components_with_same_name_on_different_topics(admin, topic_id):
    data = {'name': 'pname', 'type': 'gerrit_review', 'topic_id': topic_id}
    pstatus_code = admin.post('/api/v1/components', data=data).status_code
    assert pstatus_code == 201

    topic2 = admin.post('/api/v1/topics', data={'name': 'tname'}).data
    topic_id2 = topic2['topic']['id']

    data = {'name': 'pname', 'type': 'gerrit_review', 'topic_id': topic_id2}
    pstatus_code = admin.post('/api/v1/components', data=data).status_code
    assert pstatus_code == 201


def test_create_components_with_same_name_on_same_topics(admin, topic_id):
    data = {'name': 'pname', 'type': 'gerrit_review', 'topic_id': topic_id}
    pstatus_code = admin.post('/api/v1/components', data=data).status_code
    assert pstatus_code == 201

    data = {'name': 'pname', 'type': 'gerrit_review', 'topic_id': topic_id}
    pstatus_code = admin.post('/api/v1/components', data=data).status_code
    assert pstatus_code == 409


def test_get_all_components(admin, topic_id):
    created_c_ids = []
    for i in range(5):
        pc = admin.post('/api/v1/components',
                        data={'name': 'pname%s' % uuid.uuid4(),
                              'type': 'gerrit_review',
                              'topic_id': topic_id}).data
        created_c_ids.append(pc['component']['id'])
    created_c_ids.sort()

    db_all_cs = admin.get('/api/v1/topics/%s/components' % topic_id).data
    db_all_cs = db_all_cs['components']
    db_all_cs_ids = [db_ct['id'] for db_ct in db_all_cs]
    db_all_cs_ids.sort()

    assert db_all_cs_ids == created_c_ids


def test_get_all_components_not_in_topic(admin, user):
    topic = admin.post('/api/v1/topics', data={'name': 'topic_test'}).data
    topic_id = topic['topic']['id']
    status_code = user.get(
        '/api/v1/topics/%s/components' % topic_id).status_code
    assert status_code == 412


def test_get_all_components_with_pagination(admin, topic_id):
    # create 20 component types and check meta data count
    for i in range(20):
        admin.post('/api/v1/components',
                   data={'name': 'pname%s' % uuid.uuid4(),
                         'type': 'gerrit_review',
                         'topic_id': topic_id})
    cs = admin.get('/api/v1/topics/%s/components' % topic_id).data
    assert cs['_meta']['count'] == 20

    # verify limit and offset are working well
    for i in range(4):
        cs = admin.get(
            '/api/v1/topics/%s/components?limit=5&offset=%s' %
            (topic_id, (i * 5))).data
        assert len(cs['components']) == 5

    # if offset is out of bound, the api returns an empty list
    cs = admin.get(
        '/api/v1/topics/%s/components?limit=5&offset=300' % topic_id)
    assert cs.status_code == 200
    assert cs.data['components'] == []


def test_get_all_components_with_where(admin, topic_id):
    pc = admin.post('/api/v1/components',
                    data={'name': 'pname1',
                          'type': 'gerrit_review',
                          'topic_id': topic_id}).data
    pc_id = pc['component']['id']

    db_c = admin.get(
        '/api/v1/topics/%s/components?where=id:%s' % (topic_id, pc_id)).data
    db_c_id = db_c['components'][0]['id']
    assert db_c_id == pc_id

    db_c = admin.get(
        '/api/v1/topics/%s/components?where=name:pname1' % topic_id).data
    db_c_id = db_c['components'][0]['id']
    assert db_c_id == pc_id


def test_where_invalid(admin, topic_id):
    err = admin.get('/api/v1/topics/%s/components?where=id' % topic_id)

    assert err.status_code == 400
    assert err.data == {
        'status_code': 400,
        'message': 'Invalid where key: "id"',
        'payload': {
            'error': 'where key must have the following form "key:value"'
        }
    }


def test_get_component_by_id_or_name(admin, topic_id):
    data = {'name': 'pname',
            'type': 'gerrit_review',
            'topic_id': topic_id,
            'export_control': True
            }
    pc = admin.post('/api/v1/components', data=data).data
    pc_id = pc['component']['id']

    # get by uuid
    created_ct = admin.get('/api/v1/components/%s' % pc_id)
    assert created_ct.status_code == 200

    created_ct = created_ct.data
    assert created_ct['component']['id'] == pc_id


def test_get_component_export_control(admin, user, topic_user_id):
    data = {'name': 'pname',
            'type': 'gerrit_review',
            'topic_id': topic_user_id,
            'export_control': False
            }
    ncomp = admin.post('/api/v1/components', data=data)
    created_ct = admin.get('/api/v1/components/%s'
                           % ncomp.data['component']['id'])
    assert created_ct.status_code == 200
    created_ct = user.get('/api/v1/components/%s'
                          % ncomp.data['component']['id'])
    assert created_ct.status_code == 401


def test_get_component_not_found(admin):
    result = admin.get('/api/v1/components/ptdr')
    assert result.status_code == 404


def test_delete_component_by_id(admin, topic_id):
    data = {'name': 'pname',
            'type': 'gerrit_review',
            'topic_id': topic_id,
            'export_control': True}
    pc = admin.post('/api/v1/components', data=data)
    pc_id = pc.data['component']['id']
    assert pc.status_code == 201

    created_ct = admin.get('/api/v1/components/%s' % pc_id)
    assert created_ct.status_code == 200

    deleted_ct = admin.delete('/api/v1/components/%s' % pc_id)
    assert deleted_ct.status_code == 204

    gct = admin.get('/api/v1/components/%s' % pc_id)
    assert gct.status_code == 404


def test_get_all_components_with_sort(admin, topic_id):
    # create 4 components ordered by created time
    data = {'name': "pname1", 'title': 'aaa',
            'type': 'gerrit_review',
            'topic_id': topic_id}
    ct_1_1 = admin.post('/api/v1/components', data=data).data['component']
    data = {'name': "pname2", 'title': 'aaa',
            'type': 'gerrit_review',
            'topic_id': topic_id}
    ct_1_2 = admin.post('/api/v1/components', data=data).data['component']
    data = {'name': "pname3", 'title': 'bbb',
            'type': 'gerrit_review',
            'topic_id': topic_id}
    ct_2_1 = admin.post('/api/v1/components', data=data).data['component']
    data = {'name': "pname4", 'title': 'bbb',
            'type': 'gerrit_review',
            'topic_id': topic_id}
    ct_2_2 = admin.post('/api/v1/components', data=data).data['component']

    cts = admin.get(
        '/api/v1/topics/%s/components?sort=created_at' % topic_id).data
    cts_id = [db_cts['id'] for db_cts in cts['components']]
    assert cts_id == [ct_1_1['id'], ct_1_2['id'], ct_2_1['id'], ct_2_2['id']]

    # sort by title first and then reverse by created_at
    cts = admin.get(
        '/api/v1/topics/%s/components?sort=title,-created_at' % topic_id).data
    cts_id = [db_cts['id'] for db_cts in cts['components']]
    assert cts_id == [ct_1_2['id'], ct_1_1['id'], ct_2_2['id'], ct_2_1['id']]


def test_delete_component_not_found(admin):
    result = admin.delete('/api/v1/components/%s' % uuid.uuid4(),
                          headers={'If-match': 'mdr'})
    assert result.status_code == 404


def test_put_component(admin, user, topic_id):
    data = {'name': "pname1", 'title': 'aaa',
            'type': 'gerrit_review',
            'topic_id': topic_id}

    ct_1 = admin.post('/api/v1/components', data=data).data['component']

    # Active component
    url = '/api/v1/components/%s' % ct_1['id']
    data = {'export_control': True}
    headers = {'If-match': ct_1['etag']}
    admin.put(url, data=data, headers=headers)

    ct_2 = admin.get('/api/v1/components/%s' % ct_1['id']).data['component']

    assert ct_1['etag'] != ct_2['etag']
    assert not(ct_1['export_control'])
    assert ct_2['export_control']


def test_export_control(admin, user, team_user_id, topic_id):
    # Subscribe user to topic
    url = '/api/v1/topics/%s/teams' % topic_id
    data = {'team_id': team_user_id}
    admin.post(url, data=data)

    # Create two component in the topic
    data = {'name': "pname1", 'title': 'aaa',
            'type': 'gerrit_review',
            'topic_id': topic_id,
            'export_control': True}
    ct_1 = admin.post('/api/v1/components', data=data).data['component']
    data = {'name': "pname2", 'title': 'bbb',
            'type': 'gerrit_review',
            'topic_id': topic_id}
    ct_2 = admin.post('/api/v1/components', data=data).data['component']

    # Test if user can access or not component
    req = user.get('/api/v1/components/%s' % ct_1['id'])
    assert req.status_code == 200
    req = user.get('/api/v1/components/%s' % ct_2['id'])
    assert req.status_code == 401


def test_export_control_filter(admin, user, team_user_id, topic_user_id):
    # Subscribe user to topic
    url = '/api/v1/topics/%s/teams' % topic_user_id
    data = {'team_id': team_user_id}
    admin.post(url, data=data)

    # Create two component in the topic
    data = {'name': "pname1", 'title': 'aaa',
            'type': 'gerrit_review',
            'topic_id': topic_user_id,
            'export_control': True}
    admin.post('/api/v1/components', data=data).data['component']
    data = {'name': "pname2", 'title': 'bbb',
            'type': 'gerrit_review',
            'topic_id': topic_user_id}
    admin.post('/api/v1/components', data=data).data['component']
    data = {'name': "pname3", 'title': 'ccc',
            'type': 'gerrit_review',
            'topic_id': topic_user_id,
            'export_control': True}
    admin.post('/api/v1/components', data=data).data['component']

    req = user.get('/api/v1/topics/%s/components' % topic_user_id)
    assert len(req.data['components']) == 2

    req = admin.get('/api/v1/topics/%s/components' % topic_user_id)
    assert len(req.data['components']) == 3


def test_add_file_to_component(admin, topic_id):
    with mock.patch(SWIFT, spec=Swift) as mock_swift:

        mockito = mock.MagicMock()

        head_result = {
            'etag': utils.gen_etag(),
            'content-type': "stream",
            'content-length': 1
        }

        mockito.head.return_value = head_result
        mock_swift.return_value = mockito

        def create_ct(name):
            data = {'name': name, 'title': 'aaa',
                    'type': 'gerrit_review',
                    'topic_id': topic_id,
                    'export_control': True}
            return admin.post(
                '/api/v1/components',
                data=data).data['component']

        ct_1 = create_ct('pname1')
        ct_2 = create_ct('pname2')

        cts = admin.get(
            '/api/v1/components/%s?embed=files' % ct_1['id']).data
        assert len(cts['component']['files']) == 0

        url = '/api/v1/components/%s/files' % ct_1['id']
        c_file = admin.post(url, data='lol')
        c_file_1_id = c_file.data['component_file']['id']
        url = '/api/v1/components/%s/files' % ct_2['id']
        c_file = admin.post(url, data='lol2')
        c_file_2_id = c_file.data['component_file']['id']

        assert c_file.status_code == 201
        l_file = admin.get(url)
        assert l_file.status_code == 200
        assert l_file.data['_meta']['count'] == 1
        assert l_file.data['component_files'][0]['component_id'] == ct_2['id']
        cts = admin.get(
            '/api/v1/components/%s?embed=files' % ct_1['id']).data
        assert len(cts['component']['files']) == 1
        assert cts['component']['files'][0]['size'] == 1

        cts = admin.get('/api/v1/components/%s/files' % ct_1['id']).data
        assert cts['component_files'][0]['id'] == c_file_1_id

        cts = admin.get('/api/v1/components/%s/files' % ct_2['id']).data
        assert cts['component_files'][0]['id'] == c_file_2_id


def test_download_file_from_component(admin, topic_id):
    with mock.patch(SWIFT, spec=Swift) as mock_swift:

        mockito = mock.MagicMock()

        mockito.get.return_value = ["test", "lol lol lel".split(" ")]
        mockito.get_object.return_value = "lollollel"
        head_result = {
            'etag': utils.gen_etag(),
            'content-type': "stream",
            'content-length': 3
        }
        mockito.head.return_value = head_result

        mock_swift.return_value = mockito

        data = {'name': "pname1", 'title': 'aaa',
                'type': 'gerrit_review',
                'topic_id': topic_id,
                'export_control': True}
        ct_1 = admin.post('/api/v1/components', data=data).data['component']

        url = '/api/v1/components/%s/files' % ct_1['id']
        data = "lol"
        c_file = admin.post(url, data=data).data['component_file']

        url = '/api/v1/components/%s/files/%s/content' % (ct_1['id'],
                                                          c_file['id'])
        d_file = admin.get(url)
        assert d_file.status_code == 200
        assert d_file.data == "lollollel"


def test_delete_file_from_component(admin, topic_id):
    with mock.patch(SWIFT, spec=Swift) as mock_swift:

        mockito = mock.MagicMock()

        head_result = {
            'etag': utils.gen_etag(),
            'content-type': "stream",
            'content-length': 1
        }

        mockito.head.return_value = head_result
        mock_swift.return_value = mockito

        data = {'name': "pname1", 'title': 'aaa',
                'type': 'gerrit_review',
                'topic_id': topic_id,
                'export_control': True}
        ct_1 = admin.post('/api/v1/components', data=data).data['component']

        url = '/api/v1/components/%s/files' % ct_1['id']
        data = "lol"
        c_file = admin.post(url, data=data).data['component_file']
        url = '/api/v1/components/%s/files' % ct_1['id']
        g_file = admin.get(url)
        assert g_file.data['_meta']['count'] == 1

        url = '/api/v1/components/%s/files/%s' % (ct_1['id'], c_file['id'])
        d_file = admin.delete(url)
        assert d_file.status_code == 204

        url = '/api/v1/components/%s/files' % ct_1['id']
        g_file = admin.get(url)
        assert g_file.data['_meta']['count'] == 0


def test_change_component_state(admin, topic_id):
    data = {
        'name': 'pname',
        'type': 'gerrit_review',
        'url': 'http://example.com/',
        'topic_id': topic_id,
        'export_control': True,
        'state': 'active'}
    pc = admin.post('/api/v1/components', data=data).data
    pc_id = pc['component']['id']

    t = admin.get('/api/v1/components/' + pc_id).data['component']
    data = {'state': 'inactive'}
    r = admin.put('/api/v1/components/' + pc_id,
                  data=data,
                  headers={'If-match': t['etag']})
    assert r.status_code == 204
    cpt = admin.get('/api/v1/components/' + pc_id).data['component']
    assert cpt['state'] == 'inactive'


def test_change_component_to_invalid_state(admin, topic_id):
    data = {
        'name': 'pname',
        'type': 'gerrit_review',
        'url': 'http://example.com/',
        'topic_id': topic_id,
        'export_control': True,
        'state': 'active'}
    pc = admin.post('/api/v1/components', data=data).data
    pc_id = pc['component']['id']

    t = admin.get('/api/v1/components/' + pc_id).data['component']
    data = {'state': 'kikoolol'}
    r = admin.put('/api/v1/components/' + pc_id,
                  data=data,
                  headers={'If-match': t['etag']})
    assert r.status_code == 400
    current_component = admin.get('/api/v1/components/' + pc_id)
    assert current_component.status_code == 200
    assert current_component.data['component']['state'] == 'active'


def test_component_success_update_field_by_field(admin, topic_id):
    data = {
        'name': 'pname',
        'type': 'gerrit_review',
        'topic_id': topic_id
    }
    c = admin.post('/api/v1/components', data=data).data['component']

    admin.put('/api/v1/components/%s' % c['id'],
              data={'state': 'inactive'},
              headers={'If-match': c['etag']})

    c = admin.get('/api/v1/components/%s' % c['id']).data['component']

    assert c['name'] == 'pname'
    assert c['state'] == 'inactive'
    assert c['title'] is None

    admin.put('/api/v1/components/%s' % c['id'],
              data={'name': 'pname2'},
              headers={'If-match': c['etag']})

    c = admin.get('/api/v1/components/%s' % c['id']).data['component']

    assert c['name'] == 'pname2'
    assert c['state'] == 'inactive'
    assert c['title'] is None

    admin.put('/api/v1/components/%s' % c['id'],
              data={'title': 'a new title'},
              headers={'If-match': c['etag']})

    c = admin.get('/api/v1/components/%s' % c['id']).data['component']

    assert c['name'] == 'pname2'
    assert c['state'] == 'inactive'
    assert c['title'] == 'a new title'

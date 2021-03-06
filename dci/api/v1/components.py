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

import datetime

import flask
from flask import json
from sqlalchemy import exc as sa_exc
from sqlalchemy import sql

from dci import dci_config
from dci.api.v1 import api
from dci.api.v1 import base
from dci.api.v1 import issues
from dci.api.v1 import utils as v1_utils
from dci import auth
from dci.common import exceptions as dci_exc
from dci.common import schemas
from dci.common import utils
from dci.db import embeds
from dci.db import models

# associate column names with the corresponding SA Column object
_TABLE = models.COMPONENTS
_JJC = models.JOIN_JOBS_COMPONENTS
_VALID_EMBED = embeds.components()
_C_COLUMNS = v1_utils.get_columns_name_with_objects(_TABLE)
_CF_COLUMNS = v1_utils.get_columns_name_with_objects(models.COMPONENTFILES)
_JOBS_C_COLUMNS = v1_utils.get_columns_name_with_objects(models.JOBS)
_EMBED_MANY = {
    'files': True,
    'jobs': True
}


@api.route('/components', methods=['POST'])
@auth.login_required
def create_components(user):
    if not auth.is_admin(user):
        raise auth.UNAUTHORIZED

    values = v1_utils.common_values_dict(user)
    values.update(schemas.component.post(flask.request.json))

    query = _TABLE.insert().values(**values)

    try:
        flask.g.db_conn.execute(query)
    except sa_exc.IntegrityError:
        raise dci_exc.DCICreationConflict(_TABLE.name, 'name')

    result = json.dumps({'component': values})
    return flask.Response(result, 201, content_type='application/json')


@api.route('/components/<uuid:c_id>', methods=['PUT'])
@auth.login_required
def update_components(user, c_id):
    if not auth.is_admin(user):
        raise auth.UNAUTHORIZED

    v1_utils.verify_existence_and_get(c_id, _TABLE)
    if_match_etag = utils.check_and_get_etag(flask.request.headers)

    values = schemas.component.put(flask.request.json)
    values['etag'] = utils.gen_etag()

    where_clause = sql.and_(
        _TABLE.c.etag == if_match_etag,
        _TABLE.c.id == c_id
    )

    query = _TABLE.update().where(where_clause).values(**values)

    result = flask.g.db_conn.execute(query)
    if not result.rowcount:
        raise dci_exc.DCIConflict('Component', c_id)

    return flask.Response(None, 204, headers={'ETag': values['etag']},
                          content_type='application/json')


def get_all_components(user, topic_id):
    """Get all components of a topic."""

    args = schemas.args(flask.request.args.to_dict())

    v1_utils.verify_team_in_topic(user, topic_id)

    query = v1_utils.QueryBuilder(_TABLE, args, _C_COLUMNS)

    query.add_extra_condition(sql.and_(
        _TABLE.c.topic_id == topic_id,
        _TABLE.c.state != 'archived'))

    nb_rows = query.get_number_of_rows()
    rows = query.execute(fetchall=True)
    rows = v1_utils.format_result(rows, _TABLE.name, args['embed'],
                                  _EMBED_MANY)

    # Return only the component which have the export_control flag set to true
    #
    if not (auth.is_admin(user)):
        rows = [row for row in rows if row['export_control']]

    return flask.jsonify({'components': rows, '_meta': {'count': nb_rows}})


@api.route('/components/<uuid:c_id>', methods=['GET'])
@auth.login_required
def get_component_by_id(user, c_id):
    component = v1_utils.verify_existence_and_get(c_id, _TABLE)
    v1_utils.verify_team_in_topic(user, component['topic_id'])
    auth.check_export_control(user, component)
    return base.get_resource_by_id(user, component, _TABLE, _EMBED_MANY)


@api.route('/components/<uuid:c_id>', methods=['DELETE'])
@auth.login_required
def delete_component_by_id(user, c_id):
    # get If-Match header
    if not auth.is_admin(user):
        raise auth.UNAUTHORIZED

    v1_utils.verify_existence_and_get(c_id, _TABLE)

    values = {'state': 'archived'}
    where_clause = sql.and_(
        _TABLE.c.id == c_id
    )
    query = _TABLE.update().where(where_clause).values(**values)

    result = flask.g.db_conn.execute(query)

    if not result.rowcount:
        raise dci_exc.DCIDeleteConflict('Component', c_id)

    return flask.Response(None, 204, content_type='application/json')


@api.route('/components/purge', methods=['GET'])
@auth.login_required
def get_to_purge_archived_components(user):
    return base.get_to_purge_archived_resources(user, _TABLE)


@api.route('/components/purge', methods=['POST'])
@auth.login_required
def purge_archived_components(user):
    return base.purge_archived_resources(user, _TABLE)


@api.route('/components/<uuid:c_id>/files', methods=['GET'])
@auth.login_required
def list_components_files(user, c_id):
    component = v1_utils.verify_existence_and_get(c_id, _TABLE)
    v1_utils.verify_team_in_topic(user, component['topic_id'])

    args = schemas.args(flask.request.args.to_dict())

    query = v1_utils.QueryBuilder(models.COMPONENTFILES, args, _CF_COLUMNS)
    query.add_extra_condition(models.COMPONENTFILES.c.component_id == c_id)

    nb_rows = query.get_number_of_rows(models.COMPONENTFILES,
                                       models.COMPONENTFILES.c.component_id == c_id)  # noqa
    rows = query.execute(fetchall=True)
    rows = v1_utils.format_result(rows, models.COMPONENTFILES.name, None, None)

    return flask.jsonify({'component_files': rows,
                          '_meta': {'count': nb_rows}})


@api.route('/components/<uuid:c_id>/files/<uuid:f_id>', methods=['GET'])
@auth.login_required
def list_component_file(user, c_id, f_id):
    component = v1_utils.verify_existence_and_get(c_id, _TABLE)
    auth.check_export_control(user, component)
    v1_utils.verify_team_in_topic(user, component['topic_id'])

    COMPONENT_FILES = models.COMPONENT_FILES
    where_clause = sql.and_(COMPONENT_FILES.c.id == f_id,
                            COMPONENT_FILES.c.component_id == c_id)

    query = sql.select([COMPONENT_FILES]).where(where_clause)

    component_f = flask.g.db_conn.execute(query).fetchone()

    if component_f is None:
        raise dci_exc.DCINotFound('Component File', f_id)

    res = flask.jsonify({'component_file': component_f})
    return res


@api.route('/components/<uuid:c_id>/files/<uuid:f_id>/content',
           methods=['GET'])
@auth.login_required
def download_component_file(user, c_id, f_id):
    swift = dci_config.get_store('components')
    component = v1_utils.verify_existence_and_get(c_id, _TABLE)
    v1_utils.verify_team_in_topic(user, component['topic_id'])
    v1_utils.verify_existence_and_get(f_id, models.COMPONENT_FILES)
    auth.check_export_control(user, component)
    file_path = swift.build_file_path(component['topic_id'], c_id, f_id)

    # Check if file exist on the storage engine
    swift.head(file_path)

    return flask.Response(swift.get_object(file_path))


@api.route('/components/<uuid:c_id>/files', methods=['POST'])
@auth.login_required
def upload_component_file(user, c_id):
    if not auth.is_admin(user):
        raise auth.UNAUTHORIZED

    COMPONENT_FILES = models.COMPONENT_FILES

    component = v1_utils.verify_existence_and_get(c_id, _TABLE)

    swift = dci_config.get_store('components')

    file_id = utils.gen_uuid()
    file_path = swift.build_file_path(component['topic_id'], c_id, file_id)

    swift = dci_config.get_store('components')
    swift.upload(file_path, flask.request.stream)
    s_file = swift.head(file_path)

    values = dict.fromkeys(['md5', 'mime', 'component_id', 'name'])

    values.update({
        'id': file_id,
        'component_id': c_id,
        'name': file_id,
        'created_at': datetime.datetime.utcnow().isoformat(),
        'md5': s_file['etag'],
        'mime': s_file['content-type'],
        'size': s_file['content-length']
    })

    query = COMPONENT_FILES.insert().values(**values)

    flask.g.db_conn.execute(query)
    result = json.dumps({'component_file': values})
    return flask.Response(result, 201, content_type='application/json')


@api.route('/components/<uuid:c_id>/files/<uuid:f_id>', methods=['DELETE'])
@auth.login_required
def delete_component_file(user, c_id, f_id):
    if not auth.is_admin(user):
        raise auth.UNAUTHORIZED

    COMPONENT_FILES = models.COMPONENT_FILES
    component = v1_utils.verify_existence_and_get(c_id, _TABLE)
    v1_utils.verify_existence_and_get(f_id, COMPONENT_FILES)

    where_clause = COMPONENT_FILES.c.id == f_id

    query = COMPONENT_FILES.delete().where(where_clause)

    result = flask.g.db_conn.execute(query)

    if not result.rowcount:
        raise dci_exc.DCIDeleteConflict('Component File', f_id)

    swift = dci_config.get_store('components')
    file_path = swift.build_file_path(component['topic_id'], c_id, f_id)
    swift.delete(file_path)

    return flask.Response(None, 204, content_type='application/json')


@api.route('/components/<c_id>/issues', methods=['GET'])
@auth.login_required
def retrieve_issues_from_component(user, c_id):
    """Retrieve all issues attached to a component."""
    return issues.get_all_issues(c_id, _TABLE)


@api.route('/components/<c_id>/issues', methods=['POST'])
@auth.login_required
def attach_issue_to_component(user, c_id):
    """Attach an issue to a component."""
    return issues.attach_issue(c_id, _TABLE, user['id'])


@api.route('/components/<c_id>/issues/<i_id>', methods=['DELETE'])
@auth.login_required
def unattach_issue_from_component(user, c_id, i_id):
    """Unattach an issue to a component."""
    return issues.unattach_issue(c_id, i_id, _TABLE)

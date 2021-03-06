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
import flask
from flask import json
from sqlalchemy import exc as sa_exc
from sqlalchemy import sql, func

from dci.api.v1 import api
from dci.api.v1 import base
from dci.api.v1 import components
from dci.api.v1 import jobdefinitions
from dci.api.v1 import utils as v1_utils
from dci import auth
from dci.common import exceptions as dci_exc
from dci.common import schemas
from dci.common import utils
from dci.db import embeds
from dci.db import models

# associate column names with the corresponding SA Column object
_TABLE = models.TOPICS
_VALID_EMBED = embeds.topics()
_T_COLUMNS = v1_utils.get_columns_name_with_objects(_TABLE)
_EMBED_MANY = {
    'teams': True
}


@api.route('/topics', methods=['POST'])
@auth.login_required
def create_topics(user):
    if not auth.is_admin(user):
        raise auth.UNAUTHORIZED

    values = v1_utils.common_values_dict(user)
    values.update(schemas.topic.post(flask.request.json))

    query = _TABLE.insert().values(**values)

    try:
        flask.g.db_conn.execute(query)
    except sa_exc.IntegrityError:
        raise dci_exc.DCICreationConflict(_TABLE.name, 'name')

    result = json.dumps({'topic': values})
    return flask.Response(result, 201, headers={'ETag': values['etag']},
                          content_type='application/json')


@api.route('/topics/<uuid:topic_id>', methods=['GET'])
@auth.login_required
def get_topic_by_id(user, topic_id):
    args = schemas.args(flask.request.args.to_dict())
    topic = v1_utils.verify_existence_and_get(topic_id, _TABLE)
    v1_utils.verify_team_in_topic(user, topic_id)
    if not auth.is_admin(user):
        if 'teams' in args['embed']:
            raise dci_exc.DCIException('embed=teams not authorized.',
                                       status_code=401)

    return base.get_resource_by_id(user, topic, _TABLE, _EMBED_MANY)


@api.route('/topics', methods=['GET'])
@auth.login_required
def get_all_topics(user):
    args = schemas.args(flask.request.args.to_dict())
    # if the user is an admin then he can get all the topics
    query = v1_utils.QueryBuilder(_TABLE, args, _T_COLUMNS)

    if not auth.is_admin(user):
        if 'teams' in args['embed']:
            raise dci_exc.DCIException('embed=teams not authorized.',
                                       status_code=401)
        query.add_extra_condition(_TABLE.c.id.in_(v1_utils.user_topic_ids(user)))  # noqa
    query.add_extra_condition(_TABLE.c.state != 'archived')

    # get the number of rows for the '_meta' section
    nb_rows = query.get_number_of_rows()
    rows = query.execute(fetchall=True)
    rows = v1_utils.format_result(rows, _TABLE.name, args['embed'],
                                  _EMBED_MANY)

    return flask.jsonify({'topics': rows, '_meta': {'count': nb_rows}})


@api.route('/topics/<uuid:topic_id>', methods=['PUT'])
@auth.login_required
def put_topic(user, topic_id):
    # get If-Match header
    if_match_etag = utils.check_and_get_etag(flask.request.headers)

    values = schemas.topic.put(flask.request.json)

    if not auth.is_admin(user):
        raise auth.UNAUTHORIZED

    def _verify_team_in_topic(user, topic_id):
        topic_id = v1_utils.verify_existence_and_get(topic_id, _TABLE,
                                                     get_id=True)
        # verify user's team in the topic
        v1_utils.verify_team_in_topic(user, topic_id)
        return topic_id

    topic_id = _verify_team_in_topic(user, topic_id)

    if 'next_topic' in values and values['next_topic']:
        _verify_team_in_topic(user, values['next_topic'])

    values['etag'] = utils.gen_etag()
    where_clause = sql.and_(
        _TABLE.c.etag == if_match_etag,
        _TABLE.c.id == topic_id
    )
    query = _TABLE.update().where(where_clause).values(**values)

    result = flask.g.db_conn.execute(query)
    if not result.rowcount:
        raise dci_exc.DCIConflict('Topic', topic_id)

    return flask.Response(None, 204, headers={'ETag': values['etag']},
                          content_type='application/json')


@api.route('/topics/<uuid:topic_id>', methods=['DELETE'])
@auth.login_required
def delete_topic_by_id(user, topic_id):
    if not(auth.is_admin(user)):
        raise auth.UNAUTHORIZED

    topic_id = v1_utils.verify_existence_and_get(topic_id, _TABLE, get_id=True)

    with flask.g.db_conn.begin():
        values = {'state': 'archived'}
        where_clause = sql.and_(_TABLE.c.id == topic_id)
        query = _TABLE.update().where(where_clause).values(**values)

        result = flask.g.db_conn.execute(query)

        if not result.rowcount:
            raise dci_exc.DCIDeleteConflict('Topic', topic_id)

        for model in [models.COMPONENTS, models.JOBDEFINITIONS]:
            query = model.update().where(model.c.topic_id == topic_id).values(
                **values
            )
            flask.g.db_conn.execute(query)

    return flask.Response(None, 204, content_type='application/json')


# components, jobdefinitions, tests GET
@api.route('/topics/<uuid:topic_id>/components', methods=['GET'])
@auth.login_required
def get_all_components(user, topic_id):
    topic_id = v1_utils.verify_existence_and_get(topic_id, _TABLE, get_id=True)
    v1_utils.verify_team_in_topic(user, topic_id)
    return components.get_all_components(user, topic_id=topic_id)


@api.route('/topics/<uuid:topic_id>/type/<type_id>/status',
           methods=['GET'])
@auth.login_required
def get_jobs_status_from_components(user, topic_id, type_id):

    # List of job meaningfull job status for global overview
    #
    # ie. If current job status is running, we should retrieve status
    # from prior job.
    valid_status = ['failure', 'product-failure', 'deployment-failure',
                    'success']

    topic_id = v1_utils.verify_existence_and_get(topic_id, _TABLE, get_id=True)
    v1_utils.verify_team_in_topic(user, topic_id)

    # if the user is not the admin then filter by team_id
    team_id = user['team_id'] if not auth.is_admin(user) else None

    # Get list of all remotecis that are attached to a topic this type belongs
    # to
    fields = [models.REMOTECIS.c.id.label('remoteci_id'),
              models.REMOTECIS.c.name.label('remoteci_name'),
              models.TEAMS.c.id.label('team_id'),
              models.TEAMS.c.name.label('team_name'),
              models.TOPICS.c.name.label('topic_name'),
              models.COMPONENTS.c.id.label('component_id'),
              models.COMPONENTS.c.name.label('component_name'),
              models.COMPONENTS.c.type.label('component_type'),
              models.JOBS.c.id.label('job_id'),
              models.JOBS.c.status.label('job_status'),
              models.JOBS.c.created_at.label('job_created_at')]
    query = (sql.select(fields)
             .select_from(
                 sql.join(
                     models.REMOTECIS,
                     models.JOBS,
                     models.REMOTECIS.c.id == models.JOBS.c.remoteci_id,
                     isouter=True)
             .join(
                 models.JOIN_JOBS_COMPONENTS,
                 models.JOIN_JOBS_COMPONENTS.c.job_id == models.JOBS.c.id)
             .join(
                 models.COMPONENTS,
                 models.COMPONENTS.c.id == models.JOIN_JOBS_COMPONENTS.c.component_id)  # noqa
             .join(
                 models.TOPICS,
                 models.TOPICS.c.id == models.COMPONENTS.c.topic_id)
             .join(
                 models.TEAMS,
                 models.TEAMS.c.id == models.JOBS.c.team_id))
             .where(
                 sql.and_(
                     models.REMOTECIS.c.state == 'active',
                     models.JOBS.c.status.in_(valid_status),
                     models.JOBS.c.state != 'archived',
                     models.COMPONENTS.c.type == type_id,
                     models.TOPICS.c.id == topic_id))
             .order_by(
                 models.REMOTECIS.c.name,
                 models.JOBS.c.created_at.desc())
             .distinct(models.REMOTECIS.c.name))

    if team_id:
        query.append_whereclause(models.TEAMS.c.id == team_id)
    rcs = flask.g.db_conn.execute(query).fetchall()
    nb_row = len(rcs)

    return flask.jsonify({'jobs': rcs,
                          '_meta': {'count': nb_row}})


@api.route('/topics/<uuid:topic_id>/jobdefinitions', methods=['GET'])
@auth.login_required
def get_all_jobdefinitions_by_topic(user, topic_id):
    topic_id = v1_utils.verify_existence_and_get(topic_id, _TABLE, get_id=True)
    v1_utils.verify_team_in_topic(user, topic_id)
    return jobdefinitions.list_jobdefinitions(user, [topic_id], by_topic=True)


@api.route('/topics/<uuid:topic_id>/tests', methods=['GET'])
@auth.login_required
def get_all_tests(user, topic_id):
    args = schemas.args(flask.request.args.to_dict())
    if not(auth.is_admin(user)):
        v1_utils.verify_team_in_topic(user, topic_id)
    v1_utils.verify_existence_and_get(topic_id, _TABLE)

    query = sql.select([models.TESTS]).\
        select_from(models.JOIN_TOPICS_TESTS.join(models.TESTS)).\
        where(models.JOIN_TOPICS_TESTS.c.topic_id == topic_id)

    T_COLUMNS = v1_utils.get_columns_name_with_objects(models.TESTS)
    sort_list = v1_utils.sort_query(args['sort'], T_COLUMNS)
    where_list = v1_utils.where_query(args['where'], models.TESTS, T_COLUMNS)

    query = v1_utils.add_sort_to_query(query, sort_list)
    query = v1_utils.add_where_to_query(query, where_list)
    if args.get('limit', None):
        query = query.limit(args.get('limit'))
    if args.get('offset', None):
        query = query.offset(args.get('offset'))

    rows = flask.g.db_conn.execute(query).fetchall()

    query_nb_rows = sql.select([func.count(models.TESTS.c.id)]). \
        select_from(models.JOIN_TOPICS_TESTS.join(models.TESTS)). \
        where(models.JOIN_TOPICS_TESTS.c.topic_id == topic_id)
    nb_rows = flask.g.db_conn.execute(query_nb_rows).scalar()

    res = flask.jsonify({'tests': rows,
                         '_meta': {'count': nb_rows}})
    res.status_code = 200
    return res


@api.route('/topics/<uuid:topic_id>/tests', methods=['POST'])
@auth.login_required
def add_test_to_topic(user, topic_id):
    if not auth.is_admin(user):
        raise auth.UNAUTHORIZED
    data_json = flask.request.json
    values = {'topic_id': topic_id,
              'test_id': data_json.get('test_id', None)}

    v1_utils.verify_existence_and_get(topic_id, _TABLE)

    query = models.JOIN_TOPICS_TESTS.insert().values(**values)
    try:
        flask.g.db_conn.execute(query)
    except sa_exc.IntegrityError:
        raise dci_exc.DCICreationConflict(_TABLE.name,
                                          'topic_id, test_id')
    result = json.dumps(values)
    return flask.Response(result, 201, content_type='application/json')


@api.route('/topics/<uuid:t_id>/tests/<uuid:test_id>', methods=['DELETE'])
@auth.login_required
def delete_test_from_topic(user, t_id, test_id):
    if not auth.is_admin(user):
        v1_utils.verify_team_in_topic(user, t_id)
    v1_utils.verify_existence_and_get(test_id, _TABLE)

    JDC = models.JOIN_REMOTECIS_TESTS
    where_clause = sql.and_(JDC.c.topic_id == t_id,
                            JDC.c.test_id == test_id)
    query = JDC.delete().where(where_clause)
    result = flask.g.db_conn.execute(query)

    if not result.rowcount:
        raise dci_exc.DCIConflict('Test', test_id)

    return flask.Response(None, 204, content_type='application/json')


# teams set apis
@api.route('/topics/<uuid:topic_id>/teams', methods=['POST'])
@auth.login_required
def add_team_to_topic(user, topic_id):
    if not auth.is_admin(user):
        raise auth.UNAUTHORIZED
    # TODO(yassine): use voluptuous schema
    data_json = flask.request.json
    team_id = data_json.get('team_id')

    topic_id = v1_utils.verify_existence_and_get(topic_id, _TABLE, get_id=True)
    team_id = v1_utils.verify_existence_and_get(team_id, models.TEAMS,
                                                get_id=True)

    values = {'topic_id': topic_id,
              'team_id': team_id}
    query = models.JOINS_TOPICS_TEAMS.insert().values(**values)
    try:
        flask.g.db_conn.execute(query)
    except sa_exc.IntegrityError:
        raise dci_exc.DCICreationConflict(models.JOINS_TOPICS_TEAMS.name,
                                          'team_id, topic_id')

    result = json.dumps(values)
    return flask.Response(result, 201, content_type='application/json')


@api.route('/topics/<uuid:topic_id>/teams/<uuid:team_id>', methods=['DELETE'])
@auth.login_required
def delete_team_from_topic(user, topic_id, team_id):
    if not auth.is_admin(user):
        raise auth.UNAUTHORIZED
    topic_id = v1_utils.verify_existence_and_get(topic_id, _TABLE, get_id=True)
    team_id = v1_utils.verify_existence_and_get(team_id, models.TEAMS,
                                                get_id=True)

    JTT = models.JOINS_TOPICS_TEAMS
    where_clause = sql.and_(JTT.c.topic_id == topic_id,
                            JTT.c.team_id == team_id)
    query = JTT.delete().where(where_clause)
    result = flask.g.db_conn.execute(query)

    if not result.rowcount:
        raise dci_exc.DCIConflict('Topics_teams', team_id)

    return flask.Response(None, 204, content_type='application/json')


@api.route('/topics/<uuid:topic_id>/teams', methods=['GET'])
@auth.login_required
def get_all_teams_from_topic(user, topic_id):
    if not auth.is_admin(user):
        raise auth.UNAUTHORIZED

    topic_id = v1_utils.verify_existence_and_get(topic_id, _TABLE, get_id=True)

    # Get all teams which belongs to a given topic
    JTT = models.JOINS_TOPICS_TEAMS
    query = (sql.select([models.TEAMS])
             .select_from(JTT.join(models.TEAMS))
             .where(JTT.c.topic_id == topic_id))
    rows = flask.g.db_conn.execute(query)

    res = flask.jsonify({'teams': rows,
                         '_meta': {'count': rows.rowcount}})
    return res


@api.route('/topics/purge', methods=['GET'])
@auth.login_required
def get_to_purge_archived_topics(user):
    return base.get_to_purge_archived_resources(user, _TABLE)


@api.route('/topics/purge', methods=['POST'])
@auth.login_required
def purge_archived_topics(user):
    return base.purge_archived_resources(user, _TABLE)

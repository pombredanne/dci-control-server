#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2015 Red Hat, Inc.
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

import client
import requests
import six


def sha_walker(sha_to_walks, dci_client, repository, product_id, test_id):
    sha = sha_to_walks.pop()
    if not sha:
        return
    commit = gh_s.get(
        'https://api.github.com/'
        'repos/%s/git/commits/%s' % (repository, sha)).json()
    if 'parents' in commit:
        for parent in commit['parents']:
            print(parent['sha'])
            sha_to_walks.append(parent['sha'])

    # NOTE(Gonéri): Is the commit already here?
    r = dci_client.get("/versions", where={'sha': sha})
    if r.status_code == 404:
        message = commit['message']
        title = message.split('\n')[0]
        print('%s - %s' % (sha, title))
        r = dci_client.post("/versions", {
            "product_id": product_id,
            "name": title,
            "title": title,
            "message": message,
            "sha": sha,
            "data": {
                "sha2": sha
            }
        })
        version_id = r.json()['id']
        dci_client.post("/testversions", {
            "test_id": test_id,
            "version_id": version_id,
        })


def fetch(gh_s, dci_client, product, repositories):
    r = dci_client.get('/tests/tox')
    if r.status_code == 404:
        r = dci_client.post("/tests", {
            "name": "tox",
        })
    try:
        test_id = r.json()['id']
    except KeyError as e:
        print(r.text)
        raise e

    for repository in repositories:
        r = dci_client.get("/products", where={
            'name': "%s-%s" % (product, repository)})
        if r.status_code == 200 and r.json()['_meta']['total'] == 1:
            product_id = r.json()['_items'][0]['id']
        else:
            r = dci_client.post("/products", {
                "name": "%s-%s" % (product, repository),
                "data": {
                    "git_url": "https://github.com/%s" % repository}}
            )
            product_id = r.json()['id']
        r = gh_s.get(
            'https://api.github.com/repos/' +
            repository +
            '/branches')
        if r.status_code == 404:
            print("Repository not found: %s" % repository)
            continue
        branches = {a['name']: a['commit'] for a in r.json()}
        sha_to_walks = [branches['master']['sha']]
        while sha_to_walks:
            sha_walker(sha_to_walks, dci_client,
                       repository, product_id, test_id)

products = {
    'dci-control-server': [
        'enovance/dci-control-server', 'goneri/dci-control-server']}
gh_s = requests.Session()
# gh_s.auth = ('user', 'xxx')
dci_client = client.DCIClient()


for product, repositories in six.iteritems(products):
    fetch(gh_s, dci_client, product, repositories)

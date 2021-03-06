#
# Copyright (C) 2016 Red Hat, Inc
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

"""Add jobdefinition type

Revision ID: 8894b3479c98
Revises: 8a7009f03f13
Create Date: 2016-03-30 18:10:27.367950

"""

# revision identifiers, used by Alembic.
revision = '8894b3479c98'
down_revision = '463d8023ce19'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('jobdefinitions', sa.Column('type', sa.String(255)))


def downgrade():
    pass

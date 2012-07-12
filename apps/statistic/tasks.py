# Amara, universalsubtitles.org
#
# Copyright (C) 2012 Participatory Culture Foundation
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see
# http://www.gnu.org/licenses/agpl-3.0.html.
from datetime import timedelta

from celery.decorators import periodic_task
from celery.task import task
from statistic import (
    st_sub_fetch_handler, st_video_view_handler, st_widget_view_statistic
)

from django.db.models import Count, Sum
from apps.statistic.models import (
    EmailShareStatistic, TweeterShareStatistic, FBShareStatistic,
    SubtitleFetchCounters
)
from utils.metrics import Gauge


@periodic_task(run_every=timedelta(seconds=5))
def gauge_statistic():
    Gauge('statistic.shares.twitter').report(TweeterShareStatistic.objects.count())
    Gauge('statistic.shares.facebook').report(FBShareStatistic.objects.count())
    Gauge('statistic.shares.email').report(EmailShareStatistic.objects.count())
    Gauge('statistic.views.subtitles').report(int(st_sub_fetch_handler.total_key.get()))

def graphite_slugify(s):
    for c in ' -.,:':
        s = s.replace(c, '_')
    return s

@periodic_task(run_every=timedelta(minutes=5))
def gauge_statistic_languages():
    from apps.videos.models import SubtitleLanguage, ALL_LANGUAGES

    lang_names = dict(ALL_LANGUAGES)
    lang_names[u''] = 'Unknown'

    ls = SubtitleLanguage.objects.values('language').annotate(count=Count('language'))

    for l in ls:
        language_code = l['language']
        language_name = lang_names.get(language_code, 'Unknown')
        count = l['count']
        name = graphite_slugify(language_name)

        Gauge('statistic.languages.%s.count' % name).report(count)


@periodic_task(run_every=timedelta(hours=6))
def update_statistic(*args, **kwargs):
    st_sub_fetch_handler.migrate(verbosity=kwargs.get('verbosity', 1))
    st_video_view_handler.migrate(verbosity=kwargs.get('verbosity', 1))
    st_widget_view_statistic.migrate(verbosity=kwargs.get('verbosity', 1))


@task
def st_sub_fetch_handler_update(**kwargs):
    st_sub_fetch_handler.update(**kwargs)


@task
def st_video_view_handler_update(**kwargs):
    st_video_view_handler.update(**kwargs)


@task
def st_widget_view_statistic_update(**kwargs):
    st_widget_view_statistic.update(**kwargs)

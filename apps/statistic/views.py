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
from datetime import datetime, timedelta

from django.views.decorators.cache import cache_page
from django.views.generic.list_detail import object_list

from auth.models import CustomUser as User
from utils import render_to, render_to_json
from videos.models import Video


@cache_page(60 * 60 * 24)
@render_to('statistic/index.html')
def index(request):
    return {}

@render_to_json
def update_share_statistic(request, cls):
    st = cls()
    if request.user.is_authenticated():
        st.user = request.user
    st.save()
    return {}

@cache_page(60 * 60 * 24)
def videos_statistic(request):
    today = datetime.today()
    month_ago = today - timedelta(days=31)
    week_ago = today - timedelta(weeks=1)
    day_ago = today - timedelta(days=1)

    tn = 'statistic_subtitlefetchcounters'

    qs = Video.objects.distinct().extra(select={
        'month_activity': ('SELECT SUM(count) FROM %s WHERE %s.video_id = videos_video.id '+
        'AND %s.date BETWEEN "%s" and "%s"') % (tn, tn, tn, month_ago, today),
        'week_activity': ('SELECT SUM(count) FROM %s WHERE %s.video_id = videos_video.id '+
        'AND %s.date BETWEEN "%s" and "%s"') % (tn, tn, tn, week_ago, today),
        'day_activity': ('SELECT SUM(count) FROM %s WHERE %s.video_id = videos_video.id '+
        'AND %s.date BETWEEN "%s" and "%s"') % (tn, tn, tn, day_ago, today)
    })

    ordering = request.GET.get('o')
    order_type = request.GET.get('ot')

    extra_context = {}
    order_fields = ['title', 'subtitles_fetched_count', 'month_activity', 'week_activity', 'day_activity']
    if ordering in order_fields and order_type in ['asc', 'desc']:
        qs = qs.order_by(('-' if order_type == 'desc' else '')+ordering)
        extra_context['ordering'] = ordering
        extra_context['order_type'] = order_type
    else:
        qs = qs.order_by('-subtitles_fetched_count')

    return object_list(request, queryset=qs,
                       paginate_by=30,
                       template_name='statistic/videos_statistic.html',
                       template_object_name='video',
                       extra_context=extra_context)

@cache_page(60 * 60 * 24)
def users_statistic(request):
    today = datetime.today()
    month_ago = today - timedelta(days=31)
    week_ago = today - timedelta(weeks=1)
    day_ago = today - timedelta(days=1)

    qs = User.objects.distinct().extra(select={
        'total_activity': 'SELECT COUNT(id) FROM videos_action WHERE videos_action.user_id = auth_user.id',
        'month_activity': 'SELECT COUNT(id) FROM videos_action WHERE videos_action.user_id = auth_user.id '+
        'AND videos_action.created BETWEEN "%s" and "%s"' % (month_ago, today),
        'week_activity': 'SELECT COUNT(id) FROM videos_action WHERE videos_action.user_id = auth_user.id '+
        'AND videos_action.created BETWEEN "%s" and "%s"' % (week_ago, today),
        'day_activity': 'SELECT COUNT(id) FROM videos_action WHERE videos_action.user_id = auth_user.id '+
        'AND videos_action.created BETWEEN "%s" and "%s"' % (day_ago, today)
    })

    ordering = request.GET.get('o')
    order_type = request.GET.get('ot')

    extra_context = {}
    order_fields = ['username', 'total_activity', 'month_activity', 'week_activity', 'day_activity']
    if ordering in order_fields and order_type in ['asc', 'desc']:
        qs = qs.order_by(('-' if order_type == 'desc' else '')+ordering)
        extra_context['ordering'] = ordering
        extra_context['order_type'] = order_type
    else:
        qs = qs.order_by('-total_activity')
    return object_list(request, queryset=qs,
                       paginate_by=30,
                       template_name='statistic/users_statistic.html',
                       template_object_name='user',
                       extra_context=extra_context)

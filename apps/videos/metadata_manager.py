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

from teams.models import TeamVideo
from datetime import datetime
from utils.metrics import Meter, Timer

def update_metadata(video_pk):
    from videos.models import Video
    with Timer('metadata-update-time'):
        video = Video.objects.get(pk=video_pk)
        video.edited = datetime.now()
        video.save()
        _update_is_public(video)
        _update_forked(video)
        _update_changes(video)
        _update_subtitle_counts(video)
        _update_percent_done(video)
        _update_has_had_version(video)
        _update_is_was_subtitled(video)
        _update_languages_count(video)
        _update_complete_date(video)
        _invalidate_cache(video)

def _update_forked(video):
    for sl in video.subtitlelanguage_set.all():
        # This metrics is incremented here arbitrarily.  It could be done in any
        # of the other many _update_* functions that loop over the language set.
        Meter('language-metadata-update').inc()
        if sl.latest_version() and \
                sl.latest_version().is_forked != sl.is_forked:
            sl.is_forked = sl.latest_version().is_forked
            sl.save()

def _update_changes(video):
    from videos.models import SubtitleVersion
    for sl in video.subtitlelanguage_set.all():
        last_version = None
        versions = sl.subtitleversion_set.order_by('version_no').all()
        for version in versions:
            if version.text_change is None or version.time_change is None:
                time_change, text_change = _update_changes_on_version(version, last_version)
                SubtitleVersion.objects.filter(pk=version.pk).update(
                        time_change=time_change, text_change=text_change)
            last_version = version

def _update_changes_on_version(version, last_version):
    new_subtitles = version.subtitles()
    subs_length = len(new_subtitles)

    if not last_version:
        return 1, 1
    elif subs_length == 0:
        old_subs_length = last_version.subtitle_set.count()
        time_change = 0 if old_subs_length == 0 else 1
        text_change = version.time_change
        return time_change, text_change
    else:
        return _update_changes_on_nonzero_version(version, last_version)

def _update_changes_on_nonzero_version(version, last_version):
    subtitles = version.subtitles()
    last_subtitles = dict([(item.subtitle_id, item)
                           for item in last_version.subtitles()])
    time_count_changed, text_count_changed = 0, 0
    new_subtitles_ids = set()

    for subtitle in subtitles:
        new_subtitles_ids.add(subtitle.subtitle_id)
        if subtitle.subtitle_id in last_subtitles:
            last_subtitle = last_subtitles[subtitle.subtitle_id]
            if not last_subtitle.text == subtitle.text:
                text_count_changed += 1
            if not subtitle.has_same_timing(last_subtitle):
                time_count_changed += 1
        else:
            time_count_changed += 1
            text_count_changed += 1

    for subtitle_id in last_subtitles.keys():
        if subtitle_id not in new_subtitles_ids:
            text_count_changed += 1
            time_count_changed += 1

    subs_length = len(subtitles)
    time_change = min(time_count_changed / 1. / subs_length, 1)
    text_change = min(text_count_changed / 1. / subs_length, 1)

    return time_change, text_change

def _update_subtitle_counts(video):
    from videos.models import Subtitle
    for sl in video.subtitlelanguage_set.all():
        original_value = sl.subtitle_count
        new_value = sl.nonblank_subtitle_count() or 0

        if original_value != new_value:
            sl.subtitle_count = new_value
            sl.save()

def _update_percent_done(video):
    for sl in video.subtitlelanguage_set.all():
        percent_done = sl.calculate_percent_done()

        if percent_done is None:
            continue

        if percent_done != sl.percent_done:
            sl.percent_done = percent_done
            sl.is_complete = percent_done == 100
            sl.save()

def _update_has_had_version(video):
    for sl in video.subtitlelanguage_set.all():
        version = sl.latest_version()
        if not version:
            sl.had_version = False
            sl.has_version = False
            sl.save()
        elif len(version.subtitles()) == 0:
            if sl.has_version:
                sl.has_version = False
                sl.save()
        else:
            if not sl.has_version or not sl.had_version:
                sl.had_version = True
                sl.has_version = True
                sl.save()

def _update_is_was_subtitled(video):
    language = video.subtitle_language()
    if not language or not language.has_version:
        if video.is_subtitled:
            video.is_subtitled = False
            video.save()
    else:
        if not video.is_subtitled or not video.was_subtitled:
            video.is_subtitled = True
            video.was_subtitled = True
            video.save()

def _update_languages_count(video):
    video.languages_count = video.subtitlelanguage_set.filter(had_version=True, has_version=True).count()
    video.save()

def _update_complete_date(video):
    is_complete = video.is_complete
    if is_complete and video.complete_date is None:
        video.complete_date = datetime.now()
        video.save()
    elif not is_complete and video.complete_date is not None:
        video.complete_date = None
        video.save()

def _invalidate_cache(video):
    from widget import video_cache
    video_cache.invalidate_cache(video.video_id)


def _update_is_public(video):
    team_video = video.get_team_video()
    if team_video:
        video.is_public = team_video.team.is_visible
    else:
        video.is_public = True
    video.save()

from datetime import datetime

from celery.decorators import periodic_task
from celery.schedules import crontab, timedelta
from celery.task import task
from django.conf import settings
from django.contrib.sites.models import Site
from django.db.models import F
from django.utils.translation import ugettext_lazy as _
from haystack import site

from utils import send_templated_email
from utils.metrics import Gauge, Meter
from widget.video_cache import (
    invalidate_cache as invalidate_video_cache,
    invalidate_video_moderation,
    invalidate_video_visibility
)

from utils.metrics import Timer

@task()
def invalidate_video_caches(team_id):
    """Invalidate all TeamVideo caches for all the given team's videos."""
    from apps.teams.models import Team
    team = Team.objects.get(pk=team_id)
    for video_id in team.teamvideo_set.values_list('video__video_id', flat=True):
        invalidate_video_cache(video_id)

@task()
def invalidate_video_moderation_caches(team):
    """Invalidate the moderation status caches for all the given team's videos."""
    for video_id in team.teamvideo_set.values_list('video__video_id', flat=True):
        invalidate_video_moderation(video_id)

@task()
def update_video_moderation(team):
    """Set the moderated_by field for all the given team's videos."""
    from apps.videos.models import Video

    moderated_by = team if team.moderates_videos() else None
    Video.objects.filter(teamvideo__team=team).update(moderated_by=moderated_by)

@task()
def invalidate_video_visibility_caches(team):
    for video_id in team.teamvideo_set.values_list("video__video_id", flat=True):
        invalidate_video_visibility(video_id)

@task()
def update_video_public_field(team_id):
    from apps.teams.models import Team, TeamVideo

    with Timer("update-video-public-field-time"):
        team = Team.objects.get(pk=team_id)
        tv_index = site.get_index(TeamVideo)

        for team_video in team.teamvideo_set.all():
            video = team_video.video
            video.is_public = team.is_visible
            video.save()
            tv_index.update_object(team_video)

@periodic_task(run_every=crontab(minute=0, hour=7))
def expire_tasks():
    """Find any tasks that are past their expiration date and unassign them.

    We currently run this once per day (at 7 AM server time).

    """
    from teams.models import Task

    expired_tasks = Task.objects.incomplete().filter(
        expiration_date__isnull=False,
        expiration_date__lt=datetime.now(),
    )
    for task in expired_tasks:
        task.assignee = task.expiration_date = None
        task.save()


@periodic_task(run_every=crontab(minute=0, hour=23))
def add_videos_notification(*args, **kwargs):
    from teams.models import TeamVideo, Team
    domain = Site.objects.get_current().domain

    qs = Team.objects.filter(teamvideo__created__gt=F('last_notification_time')).distinct()

    for team in qs:
        team_videos = TeamVideo.objects.filter(team=team, created__gt=team.last_notification_time)

        team.last_notification_time = datetime.now()
        team.save()
        members = team.users.filter( notify_by_email=True, is_active=True) \
            .distinct()

        subject = _(u'New %(team)s videos ready for subtitling!') % dict(team=team)

        for user in members:
            if not user.email:
                continue

            context = {
                'domain': domain,
                'user': user,
                'team': team,
                'team_videos': team_videos,
                "STATIC_URL": settings.STATIC_URL,
            }

            Meter('templated-emails-sent-by-type.team.new-videos-ready').inc()
            send_templated_email(user, subject,
                                 'teams/email_new_videos.html',
                                 context, fail_silently=not settings.DEBUG)


@task()
def update_one_team_video(team_video_id):
    """Update the Solr index for the given team video."""
    from teams.models import TeamVideo
    try:
        team_video = TeamVideo.objects.get(id=team_video_id)
    except TeamVideo.DoesNotExist:
        return

    tv_search_index = site.get_index(TeamVideo)
    tv_search_index.backend.update(
        tv_search_index, [team_video])


@task()
def api_notify_on_subtitles_activity(team_pk, version_pk, event_name):
    from teams.models import Team
    from videos.models import SubtitleVersion
    version = SubtitleVersion.objects.select_related("language", "language__video").get(pk=version_pk)
    team = Team.objects.select_related("notification_settings").get(pk=team_pk)
    team.notification_settings.notify(
           version.language.video,
           event_name,
           version.language.pk,
           version_pk)

@task()
def api_notify_on_language_activity(team_pk, language_pk, event_name):
    from teams.models import TeamNotificationSetting
    from videos.models import SubtitleLanguage
    language = SubtitleLanguage.objects.select_related("video").get(pk=language_pk)
    TeamNotificationSetting.objects.notify_team(
        team_pk, language.video.video_id, event_name, language_pk)

@task()
def api_notify_on_video_activity(team_pk, video_id,event_name):
    from teams.models import TeamNotificationSetting
    TeamNotificationSetting.objects.notify_team(
        team_pk, video_id, event_name)


@periodic_task(run_every=timedelta(seconds=5))
def gauge_teams():
    from teams.models import Task, Team, TeamMember
    Gauge('teams.Task').report(Task.objects.count())
    Gauge('teams.Team').report(Team.objects.count())
    Gauge('teams.TeamMember').report(TeamMember.objects.count())

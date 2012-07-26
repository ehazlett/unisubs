import re

from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponseForbidden
from django.shortcuts import  get_object_or_404
from django.utils.functional import  wraps

from videos.models import Video, SubtitleVersion


SHA1_RE = re.compile('^[a-f0-9]{40}$')
def get_video_from_code(func):
    """
    Wraps a view with a signature such as view(request, video_id, ...)
    to -> view(request, video, ...), where video is a Video instance
    and authorization credentials for viewing have been checked
    for the user on that request.
    """
    def wrapper(request, video_id, *args, **kwargs):
        video = get_object_or_404(Video, video_id=video_id)

        if not video.can_user_see(request.user):
            return HttpResponseForbidden("You cannot see this video")

        # Hack to pass through the ID (which may be the secret version) in case
        # the view wants to redirect.
        video._video_id_used = video_id

        return func(request, video, *args, **kwargs)
    return wraps(func)(wrapper)

def get_video_revision(func):
    """
    Wraps a view with a signature such as view(request, pk, ...)
    to -> view(request, version, ...), where version is a SubtitleVersion instance
    and authorization credentials for viewing have been checked
    for the user on that request.
    """
    def wrapper(request, video_id=None, pk=None, *args, **kwargs):
        version = get_object_or_404(SubtitleVersion, pk=pk)
        id = video_id if video_id else version.video.video_id
        video = get_object_or_404(Video, video_id=id)

        if not video.can_user_see(request.user):
            raise SuspiciousOperation("You cannot see this video")
        
        return func(request, version, *args, **kwargs)
    return wraps(func)(wrapper)

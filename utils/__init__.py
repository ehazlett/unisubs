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

import sys
from django.shortcuts import render_to_response, get_object_or_404
from django.template.context import RequestContext
from django.http import HttpResponse, Http404
from django.utils import simplejson
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.functional import update_wrapper
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.contrib.sites.models import Site
from utils.metrics import Meter
from utils.subtitles import (
    SubtitleParserError, SubtitleParser, TxtSubtitleParser,
    YoutubeSubtitleParser, TtmlSubtitleParser, SrtSubtitleParser,
    SbvSubtitleParser, SsaSubtitleParser, YoutubeXMLParser, DfxpSubtitleParser
)

DEFAULT_PROTOCOL = getattr(settings, "DEFAULT_PROTOCOL", 'https')

try:
    import oboe
except ImportError:
    oboe = None

def is_staff(user):
    return user.is_authenticated() and user.is_staff and user.is_active

check_is_staff = user_passes_test(is_staff)

def render_to(template):
    """
    Decorator for Django views that sends returned dict to render_to_response function
    with given template and RequestContext as context instance.

    If view doesn't return dict then decorator simply returns output.
    Additionally view can return two-tuple, which must contain dict as first
    element and string with template name as second. This string will
    override template name, given as parameter

    Parameters:

     - template: template name to use
    """
    def renderer(func):
        def wrapper(request, *args, **kw):
            output = func(request, *args, **kw)
            if isinstance(output, (list, tuple)):
                return render_to_response(output[1], output[0], RequestContext(request))
            elif isinstance(output, dict):
                return render_to_response(template, output, RequestContext(request))
            return output
        return update_wrapper(wrapper, func)
    return renderer

def render_to_json(func):
    def wrapper(request, *args, **kwargs):
        result = func(request, *args, **kwargs)

        if isinstance(result, HttpResponse):
            return result

        json = simplejson.dumps(result, cls=DjangoJSONEncoder)
        return HttpResponse(json, mimetype="application/json")
    return update_wrapper(wrapper, func)

def get_object_or_none(*args, **kwargs):
    try:
        return get_object_or_404(*args, **kwargs)
    except Http404:
        return None

def send_templated_email(to, subject, body_template, body_dict,
                         from_email=None, ct="html", fail_silently=False, check_user_preference=True):
    """
    Sends an html email with a template name and a rendering context.
    Parameters:
        to: a list of email addresses of User objects
        check_user_preferences: If set to false will send the email regardless
             of the user's notification preferences. This is useful in
             situations where you must send the email, for example on
             password retrivals.
    """
    from auth.models import CustomUser
    from django.contrib.auth.models import User
    to_unchecked = to
    if not isinstance(to_unchecked, list):
        to_unchecked = [to]
    to = []
    # if passed a User, check that he has opted in for email notification
    # unless check_user_preference is False (useful for example for password)
    # retrivals, else users that have opted out of email notifications
    # can never recover their passowrd
    for recipient in to_unchecked:
        if isinstance(recipient, User) or isinstance(recipient, CustomUser):
            if not bool(recipient.email):
                continue
            if check_user_preference is False or  recipient.notify_by_email:
                to.append(recipient.email)
        else:
            to.append(recipient)
    if not from_email: from_email = settings.DEFAULT_FROM_EMAIL

    body_dict['STATIC_URL_BASE'] = settings.STATIC_URL_BASE
    body_dict['domain'] = Site.objects.get_current().domain
    body_dict['url_base'] = "%s://%s" % (DEFAULT_PROTOCOL,  Site.objects.get_current().domain)
    message = render_to_string(body_template, body_dict)
    bcc = settings.EMAIL_BCC_LIST
    email = EmailMessage(subject, message, from_email, to, bcc=bcc)
    email.content_subtype = ct
    if oboe:
        try:
            oboe.Context.log('email', 'info', backtrace=False,**{"template":body_template})
        except Exception, e:
            print >> sys.stderr, "Oboe error: %s" % e

    Meter('templated-emails-sent').inc()

    return email.send(fail_silently)


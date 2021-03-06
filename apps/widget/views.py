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
import re
import time
import traceback

import simplejson as json
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.sites.models import Site
from django.core.urlresolvers import reverse
from django.db.models import ObjectDoesNotExist
from django.http import HttpResponse, Http404, HttpResponseServerError, HttpResponseRedirect
from django.shortcuts import render_to_response, redirect, get_object_or_404
from django.template import RequestContext
from django.template.defaultfilters import urlize, linebreaks, force_escape
from django.utils.encoding import iri_to_uri
from django.utils.http import cookie_date
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from simplejson.decoder import JSONDecodeError

import widget
from auth.models import CustomUser
from teams.models import Task
from teams.permissions import get_member
from uslogging.models import WidgetDialogCall
from utils import DEFAULT_PROTOCOL
from utils.metrics import Meter
from videos import models
from widget.models import SubtitlingSession
from widget.null_rpc import NullRpc
from widget.rpc import add_general_settings, Rpc
from widget.srt_subs import captions_and_translations_to_srt, captions_to_srt, SSASubtitles


rpc_views = Rpc()
null_rpc_views = NullRpc()

def embed(request, version_no=''):
    """
    This is for serving embed when in development since the compilation
    with the media url hasn't taken place.
    Public clients will use the url : SITE_MEDIA/embed.js
    """
    context = widget.embed_context()

    if bool(version_no) is False:
        version_no = ""
    return render_to_response(
        'widget/embed{0}.js'.format(version_no),
        context,
        context_instance=RequestContext(request),
        mimetype='text/javascript')

def widget_public_demo(request):
    context = widget.add_onsite_js_files({})
    return render_to_response('widget/widget_public_demo.html', context,
                              context_instance=RequestContext(request))

def widgetizerbootloader(request):
    context = {
        "gatekeeper": "UnisubsWidgetizerLoaded",
        "script_src": widget.full_path("js/widgetizer/dowidgetize.js")
        }
    return render_to_response(
        "widget/widgetizerbootloader.js",
        context,
        mimetype='text/javascript',
        context_instance=RequestContext(request))

def onsite_widget(request):
    """Used for subtitle dialog"""

    context = widget.add_config_based_js_files(
        {}, settings.JS_API, 'unisubs-api.js')
    config = request.GET.get('config', '{}')
    # strip any query string parama as that chokes the json string
    match = re.search(r'(?P<qs>}\?.*)', config)
    if match:
        config = config[:match.start() +1 ]
    try:
        config = json.loads(config)
    except (ValueError, KeyError):
        raise Http404

    if config.get('task'):
        task = get_object_or_404(Task, pk=config.get('task'))
        if task.completed:
            messages.error(request, _(u'That task has already been completed.'))
            return HttpResponseRedirect(reverse('teams:team_tasks',
                                                kwargs={'slug': task.team.slug}))

    if 'HTTP_REFERER' in request.META:
        config['returnURL'] = request.META['HTTP_REFERER']

    if not config.get('nullWidget'):
        video_id = config.get('videoID')

        if not video_id:
            raise Http404

        video = get_object_or_404(models.Video, video_id=video_id)

        if not 'returnURL' in config:
            config['returnURL'] = video.get_absolute_url()

        if not 'effectiveVideoURL' in config:
            config['effectiveVideoURL'] = video.get_video_url()

        tv = video.get_team_video()
        if tv:
            team = tv.team

            config['guidelines'] = dict(
                    [(s.key_name.split('_', 1)[-1],
                      linebreaks(urlize(force_escape(s.data))))
                     for s in team.settings.guidelines()
                     if s.data.strip()])

            # TODO: Go to the tasks panel once the history stuff is implemented
            config['team_url'] = reverse('teams:settings_basic',
                                         kwargs={'slug': team.slug})
        else:
            config['guidelines'] = {}

    context['widget_params'] = json.dumps(config)
    general_settings = {}
    add_general_settings(request, general_settings)
    context['general_settings'] = json.dumps(general_settings)
    response = render_to_response('widget/onsite_widget.html',
                              context,
                              context_instance=RequestContext(request))
    response['X-XSS-Protection'] = '0'
    return response

def onsite_widget_resume(request):
    context = widget.add_config_based_js_files(
        {}, settings.JS_API, 'unisubs-api.js')
    config = request.GET.get('config', '{}')

    try:
        config = json.loads(config)
    except (ValueError, KeyError):
        raise Http404

    video_id = config.get('videoID')
    if not video_id:
        raise Http404

    get_object_or_404(models.Video, video_id=video_id)

    context['widget_params'] = json.dumps(config)
    general_settings = {}
    add_general_settings(request, general_settings)
    context['general_settings'] = json.dumps(general_settings)
    return render_to_response('widget/onsite_widget_resume.html',
                              context,
                              context_instance=RequestContext(request))

def widget_demo(request):
    context = {}
    context['js_use_compiled'] = settings.COMPRESS_MEDIA
    context['site_url'] = '{0}://{1}'.format( DEFAULT_PROTOCOL,
        request.get_host())
    if 'video_url' not in request.GET:
        context['help_mode'] = True
    else:
        context['help_mode'] = False
        params = base_widget_params(request)
        context['embed_js_url'] = \
            "http://{0}/embed{1}.js".format(
            Site.objects.get_current().domain,
            settings.EMBED_JS_VERSION)
        context['widget_params'] = params
    return render_to_response('widget/widget_demo.html',
                              context,
                              context_instance=RequestContext(request))

def video_demo(request, template):
    context = widget.add_config_based_js_files(
        {}, settings.JS_WIDGETIZER, 'unisubs-widgetizer.js')
    context['embed_js_url'] = \
        "http://{0}/embed{1}.js".format(
        Site.objects.get_current().domain,
        settings.EMBED_JS_VERSION)
    return render_to_response(
        'widget/{0}_demo.html'.format(template),
        context,
        context_instance=RequestContext(request))


def widgetize_demo(request, page_name):
    context = widget.add_config_based_js_files(
        {}, settings.JS_WIDGETIZER, 'unisubs-widgetizer.js')
    return render_to_response('widget/widgetize_demo/{0}.html'.format(page_name),
                              context,
                              context_instance=RequestContext(request))

def statwidget_demo(request):
    js_files = ['http://{0}/widget/statwidgetconfig.js'.format(
            Site.objects.get_current().domain)]
    js_files.append('{0}js/statwidget/statwidget.js'.format(
            settings.STATIC_URL))
    context = widget.add_js_files({}, settings.COMPRESS_MEDIA,
                               settings.JS_OFFSITE,
                               'unisubs-statwidget.js',
                               full_path_js_files=js_files)
    return render_to_response('widget/statwidget_demo.html',
                              context,
                              context_instance=RequestContext(request))

@staff_member_required
def save_emailed_translations(request):
    if request.method == "GET":
        return render_to_response(
            'widget/save_emailed_translations.html',
            context_instance=RequestContext(request))
    else:
        session = SubtitlingSession.objects.get(pk=request.POST['session_pk'])
        user = CustomUser.objects.get(pk=request.POST['user_pk'])
        subs = json.loads(request.POST['sub_text'])
        rpc_views.save_finished(user, session, subs)
        return redirect(reverse('videos:history', [session.language.video.video_id]))

def base_widget_params(request, extra_params={}):
    params = {}
    params['video_url'] = request.GET.get('video_url')
    if request.GET.get('streamer') == 'true':
        params['streamer'] = True
    if request.GET.get('null_widget') == 'true':
        params['null_widget'] = True
    if request.GET.get('debug_js') == 'true':
        params['debug_js'] = True
    if request.GET.get('subtitle_immediately') == 'true':
        params['subtitle_immediately'] = True
    if request.GET.get('translate_immediately') == 'true':
        params['translate_immediately'] = True
    if request.GET.get('base_state') is not None:
        params['base_state'] = json.loads(request.GET['base_state'])
    if request.GET.get('video_config') is not None:
        params['video_config'] = json.loads(request.GET['video_config'])
    params.update(extra_params)
    return json.dumps(params)[1:-1]

def download_subtitles(request, handler=SSASubtitles):
    #FIXME: use GenerateSubtitlesHandler
    video_id = request.GET.get('video_id')
    lang_id = request.GET.get('lang_pk')
    revision = request.GET.get('revision', None)

    if not video_id:
        #if video_id == None, Video.objects.get raise exception. Better show 404
        #because video_id is required
        raise Http404

    video = get_object_or_404(models.Video, video_id=video_id)

    if not lang_id:
        # if no language is passed, assume it's the original one
        language = video.subtitle_language()
    else:
        try:
            language = video.subtitlelanguage_set.get(pk=lang_id)
        except ObjectDoesNotExist:
            raise Http404

    team_video = video.get_team_video()

    if not team_video:
        # Non-team videos don't require moderation
        version = language and language.version(public_only=False, version_no=revision)
    else:
        # Members can see all versions
        member = get_member(request.user, team_video.team)
        if member:
            version = language and language.version(public_only=False, version_no=revision)
        else:
            version = language and language.version(version_no=revision)

    if not version:
        raise Http404

    h = handler.create(version, video, language)
    subs_text = unicode(h)
    # since this is a downlaod, we can afford not to escape tags, specially true
    # since speaker change is denoted by '>>' and that would get entirely stripped out
    response = HttpResponse(subs_text, mimetype="text/plain")
    original_filename = '%s.%s' % (video.lang_filename(language), h.file_type)

    if not 'HTTP_USER_AGENT' in request.META or u'WebKit' in request.META['HTTP_USER_AGENT']:
        # Safari 3.0 and Chrome 2.0 accepts UTF-8 encoded string directly.
        filename_header = 'filename=%s' % original_filename.encode('utf-8')
    elif u'MSIE' in request.META['HTTP_USER_AGENT']:
        try:
            original_filename.encode('ascii')
        except UnicodeEncodeError:
            original_filename = 'subtitles.' + h.file_type

        filename_header = 'filename=%s' % original_filename
    else:
        # For others like Firefox, we follow RFC2231 (encoding extension in HTTP headers).
        filename_header = 'filename*=UTF-8\'\'%s' % iri_to_uri(original_filename.encode('utf-8'))

    response['Content-Disposition'] = 'attachment; ' + filename_header
    return response

def null_srt(request):
    # FIXME: possibly note duplication with srt, and fix that.
    video = models.Video.objects.get(video_id=request.GET['video_id'])
    if 'lang_code' in request.GET:
        lang_code = request.GET['lang_code']
        response_text = captions_and_translations_to_srt(
            video.null_captions_and_translations(request.user, lang_code))
    else:
        response_text = captions_to_srt(
            list(video.null_captions(request.user).videocaption_set.all()))
    response = HttpResponse(response_text, mimetype="text/plain")
    response['Content-Disposition'] = \
        'attachment; filename={0}'.format(video.srt_filename)
    return response

def _is_loggable(method):
    return method in ['start_editing', 'fork', 'save_subtitles', 'finished_subtitles']

@csrf_exempt
def rpc(request, method_name, null=False):
    Meter('widget-rpc-calls').inc()
    if method_name[:1] == '_':
        return HttpResponseServerError('cant call private method')
    _log_call(request.browser_id, method_name, request.POST.copy())
    args = { 'request': request }
    try:
        for k, v in request.POST.items():
            try:
                args[k.encode('ascii')] = json.loads(v)
            except JSONDecodeError:
                pass
    except UnicodeEncodeError:
        return HttpResponseServerError('non-ascii chars received')
    except JSONDecodeError:
        return HttpResponseServerError('invalid json')
    rpc_module = null_rpc_views if null else rpc_views
    try:
        func = getattr(rpc_module, method_name)
    except AttributeError:
        return HttpResponseServerError('no method named ' + method_name)

    try:
        result = func(**args)
    except TypeError:
        result = {'error': 'Incorrect number of arguments',
                  'traceback': traceback.format_exc()}

    user_message = result and result.pop("_user_message", None)
    response = HttpResponse(json.dumps(result), "application/json")
    if user_message is not None:
        response.set_cookie( "_user_message", user_message["body"], expires= cookie_date(time.time() +6), path="/")
    return response

@csrf_exempt
def xd_rpc(request, method_name, null=False):
    _log_call(request.browser_id, method_name, request.POST.copy())
    args = { 'request' : request }
    for k, v in request.POST.items():
        if k[0:4] == 'xdp:':
            try:
                args[k[4:].encode('ascii')] = json.loads(v)
            except JSONDecodeError:
                pass
    rpc_module = null_rpc_views if null else rpc_views
    func = getattr(rpc_module, method_name)
    result = func(**args)
    params = {
        'request_id' : request.POST['xdpe:request-id'],
        'dummy_uri' : request.POST['xdpe:dummy-uri'],
        'response_json' : json.dumps(result) }
    return render_to_response('widget/xd_rpc_response.html',
                              widget.add_offsite_js_files(params),
                              context_instance = RequestContext(request))

def jsonp(request, method_name, null=False):
    Meter('widget-jsonp-calls').inc()
    _log_call(request.browser_id, method_name, request.GET.copy())
    callback = request.GET.get('callback', 'callback')
    args = { 'request' : request }
    for k, v in request.GET.items():
        if k != 'callback':
            args[k.encode('ascii')] = json.loads(v)
    rpc_module = null_rpc_views if null else rpc_views
    func = getattr(rpc_module, method_name)
    result = func(**args)
    return HttpResponse(
        "{0}({1});".format(callback, json.dumps(result)),
        "text/javascript")

def _log_call(browser_id, method_name, request_args):
    if method_name in ['start_editing', 'fork', 'set_title',
                       'save_subtitles', 'finished_subtitles']:
        call = WidgetDialogCall(
            browser_id=browser_id,
            method=method_name,
            request_args=request_args)
        call.save()

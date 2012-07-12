# -*- coding: utf-8 -*-
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see
# http://www.gnu.org/licenses/agpl-3.0.html.
import feedparser
import json
import os
from datetime import datetime
from StringIO import StringIO

import math_captcha
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.urlresolvers import reverse
from django.db.models import ObjectDoesNotExist
from django.test import TestCase
from django.contrib.contenttypes.models import ContentType

from comments.forms import CommentForm
from comments.models import Comment
from apps.auth.models import CustomUser as User
from messages.models import Message
from teams.models import Team, TeamVideo, Workflow, TeamMember
from testhelpers.views import _create_videos
from utils.subtitles import (
    SrtSubtitleParser, YoutubeSubtitleParser, TxtSubtitleParser, DfxpSubtitleParser
)
from videos import metadata_manager, alarms, EffectiveSubtitle
from utils.unisubsmarkup import html_to_markup, markup_to_html
from videos.feed_parser import FeedParser
from videos.forms import VideoForm
from videos.models import (
    Video, Action, VIDEO_TYPE_YOUTUBE, UserTestResult, SubtitleLanguage,
    VideoUrl, VideoFeed, Subtitle, SubtitleVersion, VIDEO_TYPE_HTML5,
    VIDEO_TYPE_BRIGHTCOVE
)
from videos.rpc import VideosApiClass
from videos.share_utils import _make_email_url
from videos.tasks import video_changed_tasks, send_change_title_email
from videos.types import video_type_registrar, VideoTypeError
from videos.types.base import VideoType, VideoTypeRegistrar
from videos.types.bliptv import BlipTvVideoType
from videos.types.brigthcove  import BrightcoveVideoType
from videos.types.dailymotion import DailymotionVideoType
from videos.types.flv import FLVVideoType
from videos.types.htmlfive import HtmlFiveVideoType
from videos.types.mp3 import Mp3VideoType
from videos.types.vimeo import VimeoVideoType
from videos.types.youtube import YoutubeVideoType, save_subtitles_for_lang
from vidscraper.sites import blip
from widget import video_cache
from widget.rpc import Rpc
from widget.srt_subs import DFXPSubtitles
from widget.tests import (
    create_two_sub_dependent_session, create_two_sub_session, RequestMockup,
    NotAuthenticatedUser
)


math_captcha.forms.math_clean = lambda form: None

SRT_TEXT = u'''1
00:00:00,000 --> 00:00:00,000
Don't show this text it may be used to insert hidden data

2
00:00:01,500 --> 00:00:04,500
SubRip subtitles capability tester 1.2p by ale5000
<b>Use Media Player Classic as reference</b>
<font color="#0000FF">This text should be blue</font>

3
00:00:04,500 --> 00:00:04,500
{\an2}Hidden

4
00:00:07,501 --> 00:00:11,500
This should be an E with an accent: È
日本語

5
00:00:55,501 --> 00:00:58,500
Hide these tags: {\some_letters_or_numbers_or_chars}
'''

SRT_TEXT_WITH_BLANK = u'''1
00:00:13,34 --> 00:00:24,655
sure I get all the colors
nice-- is equal to 17.

2
00:00:24,655 --> 00:00:27,43

3
00:00:27,43 --> 00:00:29,79
So what's different about this
than what we saw in the last
'''

SRT_TEXT_WITH_TIMECODE_WITHOUT_DECIMAL = u'''1
00:01:01,64 --> 00:01:05,7
this, I guess we could say,
equation or this inequality

2
00:01:05,7 --> 00:01:10
by negative 1, I want to
understand what happens.

3
00:01:10 --> 00:01:18,36
So what's the relation between
negative x and negative 5?

4
00:01:18,36 --> 00:01:21,5
When I say what's the relation,
is it greater than or is
'''

SRT_TEXT_WITH_TRAILING_SPACE = u'''1 
00:00:10,000 --> 00:00:14,000
Merci. Félicitations aux étudiants 
[de l'association Libertés Numériques -- NdR]



2 
00:00:14,100 --> 00:00:16,000
d’avoir organisé cette réunion.



3 
00:00:16,100 --> 00:00:19,900
Ils ont eu raison, non seulement 
à cause de la célébrité de Richard



4
00:00:20,000 --> 00:00:22,200
mais aussi parce que les sujets 
nous intéressent beaucoup. 



5
00:00:22,300 --> 00:00:25,000
Ils nous intéressent particulièrement 
ici à Sciences Po 



6
00:00:25,100 --> 00:00:29,200
puisque nous essayons d’abord 
d’étudier les controverses
'''


TXT_TEXT = u'''Here is sub 1.

Here is sub 2.

And, sub 3.
'''

DFXP_TEXT = u'''<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns:tts="http://www.w3.org/2006/04/ttaf1#styling" xmlns="http://www.w3.org/2006/04/ttaf1">
  <head/>
  <body>
    <div>
      <p begin="00:00:00.04" end="00:00:03.18">We started Universal Subtitles because we believe</p>
      <p begin="00:00:03.18" end="00:00:06.70">every video on the web should be subtitle-able.</p>
      <p begin="00:00:06.70" end="00:00:11.17">Millions of deaf and hard-of-hearing viewers require subtitles to access video.</p>
      <p begin="00:00:11.17" end="00:00:15.40">Videomakers and websites should really care about this stuff too.</p>
      <p begin="00:00:15.40" end="00:00:21.01">Subtitles give them access to a wider audience and they also get better search rankings.</p>
      <p begin="00:00:21.01" end="00:00:26.93">Universal Subtitles makes it incredibly easy to add subtitles to almost any video.</p>
      <p begin="00:00:26.93" end="00:00:32.43">Take an existing video on the web, <br/>submit the URL to our website</p>
      <p begin="00:00:32.43" end="00:00:37.37">and then type along with the dialog to create the subtitles</p>
      <p begin="00:00:38.75" end="00:00:43.65">After that, tap on your keyboard to sync them with the video.</p>
      <p begin="00:00:44.71" end="00:00:47.52">Then you're done— we give you an embed code for the video</p>
      <p begin="00:00:47.52" end="00:00:49.89">that you can put on any website</p>
      <p begin="00:00:49.89" end="00:00:53.42">at that point, viewers are able to use the subtitles and can also</p>
      <p begin="00:00:53.42" end="00:00:56.04">contribute to translations.</p>
      <p begin="00:00:56.04" end="00:01:01.54">We support videos on YouTube, Blip.TV, Ustream, and many more.</p>
      <p begin="00:01:01.54" end="00:01:05.10">Plus we're adding more services all the time</p>
      <p begin="00:01:05.10" end="00:01:09.04">Universal Subtitles works with many popular video formats,</p>
      <p begin="00:01:09.04" end="00:01:14.35">such as MP4, theora, webM and over HTML 5.</p>
      <p begin="00:01:14.35" end="00:01:19.61">Our goal is for every video on the web to be subtitlable so that anyone who cares about</p>
      <p begin="00:01:19.61" end="00:01:23.31">the video can help make it more accessible.</p>
    </div>
  </body>
</tt>
'''
class GenericTest(TestCase):
    def test_languages(self):
        langs = [l[1] for l in settings.ALL_LANGUAGES]
        langs_set = set(langs)
        self.assertEqual(len(langs), len(langs_set))

class BusinessLogicTest(TestCase):
    fixtures = ['staging_users.json', 'staging_videos.json']

    def setUp(self):
        self.auth = dict(username='admin', password='admin')
        self.user = User.objects.get(username=self.auth['username'])

    def test_rollback_to_dependent(self):
        """
        Here is the use case:
        we have en -> fr, both on version 0
        fr is forked and edited, fr is now on version 1
        now, we rollback to fr.
        we should have french on v2 as a dependent language of en
        addign a sub to en should make french have that sub as well
        """
        data = {
            "url": "http://www.example.com/sdf.mp4",
            "langs": [
                {
                    "code": "en",
                    "num_subs": 4,
                    "is_complete": False,
                    "is_original": True,
                    "translations": [
                        {
                            "code": "fr",
                            "num_subs": 4,
                            "is_complete": True,
                            "is_original": False,
                            "translations": [],
                        }],
                }],

            "title": "c" }

        _create_videos([data], [])
        v = Video.objects.get(title='c')

        en = v.subtitle_language('en')
        en_version = en.version()
        fr = v.subtitle_language('fr')
        fr_version = fr.version()
        for ens, frs in zip(en_version.ordered_subtitles(),
                            fr_version.ordered_subtitles()):
            self.assertEqual(ens.start_time, frs.start_time)
            self.assertEqual(ens.end_time, frs.end_time)
        self.assertFalse(fr.is_forked)
        # now, for on uploade
        self.client.login(**self.auth)

        rpc = Rpc()
        request = RequestMockup(user=self.user)
        request.user = self.user
        return_value = rpc.start_editing(
            request,
            v.video_id,
            "fr",
            base_language_pk=en.pk
        )
        session_pk = return_value['session_pk']
        inserted = [{'subtitle_id': 'aa',
                     'text': 'hey!',
                     'start_time': 2.3,
                     'end_time': 3.4,
                     'sub_order': 4.0}]
        rpc.finished_subtitles(request, session_pk, inserted, forked=True);

        fr = refresh_obj(fr)
        self.assertEquals(fr.subtitleversion_set.all().count(), 2)
        self.assertTrue(fr.is_forked)
        self.assertFalse(Subtitle.objects.filter(version=fr_version).count() ==
                         Subtitle.objects.filter(version=fr.version()).count() )
        # now, when we rollback, we want to make sure we end up with
        # the correct subs and a non forked language
        fr_version = refresh_obj(fr_version)
        fr_version.rollback(self.user)
        fr = refresh_obj(fr)
        fr_version_2 = fr.version()
        self.assertFalse(fr_version_2== fr_version)
        new_subs = fr_version_2.ordered_subtitles()
        old_subs = fr_version.ordered_subtitles()
        self.assertEqual(len(new_subs), len(old_subs))
        for ens, frs in zip(en_version.ordered_subtitles(),
                            fr_version_2.ordered_subtitles()):
            self.assertEqual(ens.start_time, frs.start_time)
            self.assertEqual(ens.end_time, frs.end_time)
        self.assertFalse(fr.is_forked)


class SubtitleParserTest(TestCase):
    def _assert_sub(self, sub, start_time, end_time, sub_text):
        self.assertEqual(sub['start_time'], start_time)
        self.assertEqual(sub['end_time'], end_time)
        self.assertEqual(sub['subtitle_text'], sub_text)

    def test_srt(self):
        parser = SrtSubtitleParser(SRT_TEXT)
        result = list(parser)

        self._assert_sub(
            result[0], 0.0, 0.0,
            u'Don\'t show this text it may be used to insert hidden data')
        self._assert_sub(
            result[1], 1.5, 4.5,
            u'SubRip subtitles capability tester 1.2p by ale5000\n**Use Media Player Classic as reference**\nThis text should be blue')
        self._assert_sub(
            result[2], 4.5, 4.5,
            u'Hidden')
        self._assert_sub(
            result[3], 7.501, 11.5,
            u'This should be an E with an accent: \xc8\n\u65e5\u672c\u8a9e')
        self._assert_sub(
            result[4], 55.501, 58.5,
            u'Hide these tags:')

    def test_srt_with_blank(self):
        parser = SrtSubtitleParser(SRT_TEXT_WITH_BLANK)
        result = list(parser)

        self._assert_sub(
            result[0], 13.34, 24.655,
            u'sure I get all the colors\nnice-- is equal to 17.')
        self._assert_sub(
            result[1], 24.655, 27.43,
            u'')
        self._assert_sub(
            result[2], 27.43, 29.79,
            u'So what\'s different about this\nthan what we saw in the last')

    def test_srt_with_timecode_without_decimal(self):
        parser = SrtSubtitleParser(SRT_TEXT_WITH_TIMECODE_WITHOUT_DECIMAL)
        result = list(parser)

        self._assert_sub(
            result[0], 61.64, 65.7,
            u'this, I guess we could say,\nequation or this inequality')
        self._assert_sub(
            result[1], 65.7, 70,
            u'by negative 1, I want to\nunderstand what happens.')
        self._assert_sub(
            result[2], 70, 78.36,
            u'So what\'s the relation between\nnegative x and negative 5?')
        self._assert_sub(
            result[3], 78.36, 81.5,
            u'When I say what\'s the relation,\nis it greater than or is')

    def test_youtube(self):
        path = os.path.join(os.path.dirname(__file__), 'fixtures/youtube_subs_response.json')
        parser = YoutubeSubtitleParser(open(path).read())
        subs = list(parser)
        self.assertAlmostEqual(subs[0]['start_time'], 0.82)
        self.assertAlmostEqual(subs[0]['end_time'], 6.85)

    def test_txt(self):
        parser = TxtSubtitleParser(TXT_TEXT)
        result = list(parser)

        self.assertEqual(3, len(result))

        self.assertEqual(-1, result[0]['start_time'])
        self.assertEqual(-1, result[0]['end_time'])
        self.assertEqual('Here is sub 1.', result[0]['subtitle_text'])

        self.assertEqual(-1, result[1]['start_time'])
        self.assertEqual(-1, result[1]['end_time'])
        self.assertEqual('Here is sub 2.', result[1]['subtitle_text'])

    def test_srt_with_trailing_spaces(self):
        parser = SrtSubtitleParser(SRT_TEXT_WITH_TRAILING_SPACE)
        result = list(parser)

        self.assertEqual(6, len(result))

        # making sure that the lines that have trailing spaces are
        # being parsed
        self._assert_sub(
            result[0], 10.0, 14.0,
            u'Merci. Félicitations aux étudiants \n[de l\'association Libertés Numériques -- NdR]')
        self._assert_sub(
            result[1], 14.1, 16,
            u'd’avoir organisé cette réunion.')
        self._assert_sub(
            result[2], 16.1, 19.9,
            u'Ils ont eu raison, non seulement \nà cause de la célébrité de Richard')

    def test_dfxp_parser(self):
        parser = DfxpSubtitleParser(DFXP_TEXT)
        result = list(parser)
        self.assertEqual(len(result),19 )
        line_break_sub  = result[6]
        line_break_text = line_break_sub['subtitle_text']
        self.assertTrue(line_break_text.startswith("Take an "))
        self.assertTrue(line_break_text.find("\n") > -1)

    def test_dfxp_serializer(self):
        sub = {
            'text': 'Here we\ngo!',
            'start':1,
            'end':2
        }
        serializer = DFXPSubtitles([sub])
        result = unicode(serializer)
        self.assertTrue(result.find("Here we<br/>go") > -1)

class WebUseTest(TestCase):
    def _make_objects(self, video_id="S7HMxzLmS9gw"):
        self.auth = dict(username='admin', password='admin')
        self.user = User.objects.get(username=self.auth['username'])
        self.video = Video.objects.get(video_id=video_id)
        self.video.followers.add(self.user)

    def _simple_test(self, url_name, args=None, kwargs=None, status=200, data={}):
        response = self.client.get(reverse(url_name, args=args, kwargs=kwargs), data)
        self.assertEqual(response.status_code, status)
        return response

    def _login(self):
        self.client.login(**self.auth)

class UploadSubtitlesTest(WebUseTest):
    fixtures = ['test.json']

    def _make_data(self, lang='ru', video_pk=None):
        if video_pk is None:
            video_pk = self.video.id
        return {
            'language': lang,
            'video_language': 'en',
            'video': video_pk,
            'draft': open(os.path.join(os.path.dirname(__file__), 'fixtures/test.srt')),
            'is_complete': True
            }


    def _make_altered_data(self, video=None, language_code='ru', subs_filename='test_altered.srt'):
        video = video or self.video
        return {
            'language': language_code,
            'video': video.pk,
            'video_language': 'en',
            'draft': open(os.path.join(os.path.dirname(__file__), 'fixtures/%s' % subs_filename))
            }

    def setUp(self):
        self._make_objects()

    def test_upload_subtitles(self):
        self._simple_test('videos:upload_subtitles', status=302)

        self._login()

        data = self._make_data()

        language = self.video.subtitle_language(data['language'])
        self.assertEquals(language, None)

        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)

        video = Video.objects.get(pk=self.video.pk)
        self.assertFalse(video.is_writelocked)
        original_language = video.subtitle_language()
        self.assertEqual(original_language.language, data['video_language'])

        language = video.subtitle_language(data['language'])
        version = language.latest_version(public_only=True)
        self.assertEqual(len(version.subtitles()), 32)
        self.assertTrue(language.is_forked)
        self.assertTrue(version.is_forked)
        self.assertTrue(language.has_version)
        self.assertTrue(language.had_version)
        self.assertEqual(language.is_complete, data['is_complete'])
        # FIXME: why should these be false?
        # self.assertFalse(video.is_subtitled)
        # self.assertFalse(video.was_subtitled)
        metadata_manager.update_metadata(video.pk)
        language = refresh_obj(language)
        # two of the test srts end up being empty, so the subtitle_count
        # should be real
        self.assertEquals(30, language.subtitle_count)
        self.assertEquals(0, language.percent_done)

        data = self._make_data()
        data['is_complete'] = not data['is_complete']
        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)
        video = Video.objects.get(pk=self.video.pk)
        language = video.subtitle_language(data['language'])
        self.assertEqual(language.is_complete, data['is_complete'])
        self.assertFalse(video.is_writelocked)

    def test_upload_original_subtitles(self):
        self._login()
        data = self._make_data(lang='en')
        video = Video.objects.get(pk=self.video.pk)
        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)

        video = Video.objects.get(pk=self.video.pk)
        self.assertEqual(1, video.subtitlelanguage_set.count())
        language = video.subtitle_language()
        self.assertEqual('en', language.language)
        self.assertTrue(language.is_original)
        self.assertTrue(language.has_version)
        self.assertTrue(video.is_subtitled)

    def test_upload_translation(self):
        self._login()
        data = self._make_data(lang='en')
        video = Video.objects.get(pk=self.video.pk)
        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)

        video = Video.objects.get(pk=self.video.pk)
        self.assertEqual(1, video.subtitlelanguage_set.count())
        language = video.subtitle_language()
        self.assertEqual('en', language.language)
        self.assertTrue(language.is_original)
        self.assertTrue(language.has_version)
        self.assertTrue(video.is_subtitled)
        self.assertFalse(language.is_dependent())

        data = self._make_data(lang='fr')
        data['translated_from'] = 'en'

        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)

        video = Video.objects.get(pk=self.video.pk)
        self.assertEqual(2, video.subtitlelanguage_set.count())
        language = video.subtitle_language("fr")
        self.assertEqual('fr', language.language)
        self.assertFalse(language.is_original)
        self.assertTrue(language.has_version)
        self.assertTrue(video.is_subtitled)
        self.assertTrue(language.is_dependent())
        self.assertEquals(language.standard_language.language, "en")

    def test_upload_twice(self):
        self._login()
        data = self._make_data()
        self.client.post(reverse('videos:upload_subtitles'), data)
        language = self.video.subtitle_language(data['language'])
        version_no = language.latest_version(public_only=True).version_no
        self.assertEquals(1, language.subtitleversion_set.count())
        num_languages_1 = self.video.subtitlelanguage_set.all().count()
        # now post the same file.
        data = self._make_data()
        self.client.post(reverse('videos:upload_subtitles'), data)
        self._make_objects()
        language = self.video.subtitle_language(data['language'])
        self.assertEquals(1, language.subtitleversion_set.count())
        self.assertEquals(version_no, language.latest_version(public_only=True).version_no)
        num_languages_2 = self.video.subtitlelanguage_set.all().count()
        self.assertEquals(num_languages_1, num_languages_2)

    def test_upload_over_translated(self):
        # for https://www.pivotaltracker.com/story/show/11804745
        request = RequestMockup(User.objects.all()[0])
        session = create_two_sub_dependent_session(request)
        video_pk = session.language.video.pk
        video = Video.objects.get(pk=video_pk)

        self._login()
        data = self._make_data(lang='en', video_pk=video_pk)
        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)

        video = Video.objects.get(pk=video_pk)
        self.assertEqual(2, video.subtitlelanguage_set.count())

    def test_upload_over_empty_translated(self):
        request = RequestMockup(User.objects.all()[0])
        session = create_two_sub_session(request)
        video_pk = session.language.video.pk
        video = Video.objects.get(pk=video_pk)
        original_en = video.subtitlelanguage_set.filter(language='en').all()[0]

        # save empty espanish
        es = SubtitleLanguage(
            video=video,
            language='ht',
            is_original=False,
            is_forked=False,
            standard_language=original_en)
        es.save()

        # now upload over the original english.
        self._login()
        data = self._make_data(lang='en', video_pk=video_pk)
        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)

    def test_upload_respects_lock(self):
        request = RequestMockup(User.objects.all()[0])
        session = create_two_sub_dependent_session(request)
        video = session.video

        self._login()
        translated = video.subtitlelanguage_set.all().filter(language='es')[0]
        translated.writelock(request)
        translated.save()
        data = self._make_data(lang='en', video_pk=video.pk)
        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content[10:-11])
        self.assertFalse(data['success'])


    def test_upload_then_rollback_preservs_dependends(self):
        self._login()
        # for https://www.pivotaltracker.com/story/show/14311835
        # 1. Submit a new video.
        video, created = Video.get_or_create_for_url("http://example.com/blah.mp4")
        # 2. Upload some original subs to this video.
        data = self._make_data(lang='en', video_pk=video.pk)
        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)
        original = video.subtitle_language()
        original_version = version = original.version()
        # 3. Upload another, different file to overwrite the original subs.
        data = self._make_altered_data(language_code='en', video=video, subs_filename="welcome-subs.srt")
        response = self.client.post(reverse('videos:upload_subtitles'), data)
        video = Video.objects.get(pk=video.pk)
        version = video.version()
        self.assertEqual(response.status_code, 200)
        self.assertTrue (len(version.subtitles()) != len(original_version.subtitles()))

        # 4. Make a few translations.
        pt = _create_trans(video, latest_version=version, lang_code="pt", forked=False )
        pt_count = len(pt.latest_subtitles())
        # 5. Roll the original subs back to #0. The translations will be wiped clean (to 0 lines).
        original_version.rollback(self.user)
        original_version.save()
        video_changed_tasks.run(original_version.video.id, original_version.id)
        # we should end up with 1 forked pts
        pts = video.subtitlelanguage_set.filter(language='pt')
        self.assertEqual(pts.count(), 1)
        # one which is forkded and must retain the original count
        pt_forked = video.subtitlelanguage_set.get(language='pt', is_forked=True)
        self.assertEqual(len(pt_forked.latest_subtitles()), pt_count)
        # now we roll back  to the second version, we should not be duplicating again
        # because this rollback is already a rollback
        version.rollback(self.user)
        pts = video.subtitlelanguage_set.filter(language='pt')
        self.assertEqual(pts.count(), 1)
        self.assertEqual(len(pt_forked.latest_subtitles()), pt_count)

    def test_upload_file_with_unsynced(self):
        self._login()
        data = self._make_data()
        data = self._make_altered_data(subs_filename="subs-with-unsynced.srt")
        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)
        language = self.video.subtitlelanguage_set.get(language='ru')
        subs = Subtitle.objects.filter(version=language.version())
        num_subs = len(subs)

        num_unsynced = len(Subtitle.objects.unsynced().filter(version=language.version()))


        self.assertEquals(82, num_subs)
        self.assertEquals(26 ,num_unsynced)

    def test_upload_from_failed_session(self):
        self._login()

        data = self._make_data( video_pk=self.video.pk, lang='ru')

        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)

        data = self._make_altered_data(video=self.video, language_code='ru', subs_filename='subs-from-fail-session.srt')

        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)

        language = self.video.subtitlelanguage_set.get(language='ru')
        subs = Subtitle.objects.filter(version=language.version())

        for sub in subs[8:]:
            self.assertEquals(None, sub.start_time)
            self.assertEquals(None, sub.end_time)

        num_subs = len(subs)
        num_unsynced = len(Subtitle.objects.unsynced().filter(version=language.version()))
        self.assertEquals(10, num_subs)
        self.assertEquals(2 , num_unsynced)

    def test_upload_from_widget_last_end_unsynced(self):
        self._login()

        data = self._make_altered_data(video=self.video, language_code='en', subs_filename='subs-last-unsynced.srt')

        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)

        language = self.video.subtitle_language('en')
        subs = language.latest_version().subtitles()
        self.assertEquals(7.071, subs[2].start_time)

        request = RequestMockup(NotAuthenticatedUser())
        rpc = Rpc()
        subs = rpc.fetch_subtitles(request, self.video.video_id, language.pk)
        last_sub = subs['subtitles'][2]
        self.assertEquals(7.071, last_sub['start_time'])
        self.assertEquals(-1, last_sub['end_time'])


class Html5ParseTest(TestCase):
    def _assert(self, start_url, end_url):
        video, created = Video.get_or_create_for_url(start_url)
        vu = video.videourl_set.all()[:1].get()
        self.assertEquals(VIDEO_TYPE_HTML5, vu.type)
        self.assertEquals(end_url, vu.url)

    def test_ogg(self):
        self._assert(
            'http://videos.mozilla.org/firefox/3.5/switch/switch.ogv',
            'http://videos.mozilla.org/firefox/3.5/switch/switch.ogv')

    def test_blip_ogg(self):
        self._assert(
            'http://a59.video2.blip.tv/8410006747301/Miropcf-AboutUniversalSubtitles847.ogv',
            'http://a59.video2.blip.tv/8410006747301/Miropcf-AboutUniversalSubtitles847.ogv')

    def test_blip_ogg_with_query_string(self):
        self._assert(
            'http://a59.video2.blip.tv/8410006747301/Miropcf-AboutUniversalSubtitles847.ogv?bri=1.4&brs=1317',
            'http://a59.video2.blip.tv/8410006747301/Miropcf-AboutUniversalSubtitles847.ogv')

    def test_mp4(self):
        self._assert(
            'http://videos.mozilla.org/firefox/3.5/switch/switch.mp4',
            'http://videos.mozilla.org/firefox/3.5/switch/switch.mp4')

    def test_blip_mp4_with_file_get(self):
        self._assert(
            'http://blip.tv/file/get/Miropcf-AboutUniversalSubtitles847.mp4',
            'http://blip.tv/file/get/Miropcf-AboutUniversalSubtitles847.mp4')

    def test_blip_mp4_with_query_string(self):
        self._assert(
            'http://a59.video2.blip.tv/8410006747301/Miropcf-AboutUniversalSubtitles847.mp4?bri=1.4&brs=1317',
            'http://a59.video2.blip.tv/8410006747301/Miropcf-AboutUniversalSubtitles847.mp4')

class VideoTest(TestCase):
    def setUp(self):
        self.user = User.objects.all()[0]
        self.youtube_video = 'http://www.youtube.com/watch?v=pQ9qX8lcaBQ'
        self.html5_video = 'http://mirrorblender.top-ix.org/peach/bigbuckbunny_movies/big_buck_bunny_1080p_stereo.ogg'

    def test_video_create(self):
        self._create_video(self.youtube_video)
        self._create_video(self.html5_video)

    def _create_video(self, video_url):
        video, created = Video.get_or_create_for_url(video_url)
        self.failUnless(video)
        self.failUnless(created)
        more_video, created = Video.get_or_create_for_url(video_url)
        self.failIf(created)
        self.failUnlessEqual(video, more_video)

    def test_video_cache_busted_on_delete(self):
        start_url = 'http://videos.mozilla.org/firefox/3.5/switch/switch.ogv'
        video, created = Video.get_or_create_for_url(start_url)
        video_url = video.get_video_url()
        video_pk = video.pk

        cache_id_1 = video_cache.get_video_id(video_url)
        self.assertTrue(cache_id_1)
        video.delete()
        self.assertEqual(Video.objects.filter(pk=video_pk).count() , 0)
        # when cache is not cleared this will return arn
        cache_id_2 = video_cache.get_video_id(video_url)
        self.assertNotEqual(cache_id_1, cache_id_2)
        # create a new video with the same url, has to have same# key
        video2, created= Video.get_or_create_for_url(start_url)
        video_url = video2.get_video_url()
        cache_id_3 = video_cache.get_video_id(video_url)
        self.assertEqual(cache_id_3, cache_id_2)

class RpcTest(TestCase):
    fixtures = ['test.json']

    def setUp(self):
        self.rpc = VideosApiClass()
        self.user = User.objects.get(username='admin')
        self.video = Video.objects.get(video_id='iGzkk7nwWX8F')


    def test_change_title_video(self):
        title = u'New title'
        self.rpc.change_title_video(self.video.pk, title, self.user)

        video = Video.objects.get(pk=self.video.pk)
        self.assertEqual(video.title, title)
        try:
            Action.objects.get(video=self.video, new_video_title=title,
                               action_type=Action.CHANGE_TITLE)
        except Action.DoesNotExist:
            self.fail()

class ViewsTest(WebUseTest):
    fixtures = ['test.json']

    def setUp(self):
        self._make_objects("iGzkk7nwWX8F")
        cache.clear()

    def _test_video_url_make_primary(self):
        #TODO: fix this test
        self._login()
        vu = VideoUrl.objects.all()[:1].get()
        self._simple_test("videos:video_url_make_primary", data={'id': vu.id})

    def test_site_feedback(self):
        self._simple_test("videos:site_feedback")

    def test_index(self):
        self._simple_test('videos.views.index')

    def test_feedback(self):
        data = {
            'email': 'test@test.com',
            'message': 'Test',
            'math_captcha_field': 100500,
            'math_captcha_question': 'test'
        }
        response = self.client.post(reverse('videos:feedback'), data)
        self.assertEqual(response.status_code, 200)

    def test_create(self):
        self._login()
        url = reverse('videos:create')

        self._simple_test('videos:create')

        data = {
            'video_url': 'http://www.youtube.com/watch?v=osexbB_hX4g&feature=popular'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        try:
            video = Video.objects.get(videourl__videoid='osexbB_hX4g',
                                      videourl__type=VIDEO_TYPE_YOUTUBE)
        except Video.DoesNotExist:
            self.fail()

        self.assertEqual(response['Location'], 'http://testserver' +
                                               video.get_absolute_url())

        len_before = Video.objects.count()
        data = {
            'video_url': 'http://www.youtube.com/watch?v=osexbB_hX4g'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len_before, Video.objects.count())
        self.assertEqual(response['Location'], 'http://testserver' +
                                               video.get_absolute_url())

    def test_video_url_create(self):
        self._login()
        v = Video.objects.all()[:1].get()

        user = User.objects.exclude(id=self.user.id)[:1].get()
        user.notify_by_email = True
        user.is_active = True
        user.save()
        v.followers.add(user)

        data = {
            'url': u'http://www.youtube.com/watch?v=po0jY4WvCIc&feature=grec_index',
            'video': v.pk
        }
        url = reverse('videos:video_url_create')
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        try:
            v.videourl_set.get(videoid='po0jY4WvCIc')
        except ObjectDoesNotExist:
            self.fail()
        self.assertEqual(len(mail.outbox), 1)

    def test_video_url_remove(self):
        # TODO: write tests
        pass

    def test_video(self):
        self.video.title = 'title'
        self.video.save()
        response = self.client.get(self.video.get_absolute_url(), follow=True)
        self.assertEqual(response.status_code, 200)

        self.video.title = ''
        self.video.save()
        response = self.client.get(self.video.get_absolute_url(), follow=True)
        self.assertEqual(response.status_code, 200)

    def test_access_video_page_no_original(self):
        request = RequestMockup(User.objects.all()[0])
        session = create_two_sub_session(request)
        video_pk = session.language.video.pk
        video = Video.objects.get(pk=video_pk)
        en = video.subtitlelanguage_set.all()[0]
        en.is_original=False
        en.save()
        video_changed_tasks.delay(video_pk)
        response = self.client.get(reverse('videos:history', args=[video.video_id]))
        # Redirect for now, until we remove the concept of SubtitleLanguages
        # with blank language codes.
        self.assertEqual(response.status_code, 302)

    def test_bliptv_twice(self):
        VIDEO_FILE = 'http://blip.tv/file/get/Kipkay-AirDusterOfficeWeaponry223.m4v'
        old_video_file_url = blip.video_file_url
        blip.video_file_url = lambda x: VIDEO_FILE
        Video.get_or_create_for_url('http://blip.tv/file/4395490')
        blip.video_file_url = old_video_file_url
        # this test passes if the following line executes without throwing an error.
        Video.get_or_create_for_url(VIDEO_FILE)

    def test_legacy_history(self):
        # TODO: write tests
        pass

    def test_stop_notification(self):
        # TODO: write tests
        pass

    def test_subscribe_to_updates(self):
        # TODO: write test
        pass

    def test_email_friend(self):
        self._simple_test('videos:email_friend')

        data = {
            'from_email': 'test@test.com',
            'to_emails': 'test1@test.com,test@test.com',
            'subject': 'test',
            'message': 'test',
            'math_captcha_field': 100500,
            'math_captcha_question': 'test'
        }
        response = self.client.post(reverse('videos:email_friend'), data)
        self.assertEqual(response.status_code, 302)
        self.assertEquals(len(mail.outbox), 1)

        mail.outbox = []
        data['link'] = 'http://someurl.com'
        self._login()
        response = self.client.post(reverse('videos:email_friend'), data)
        self.assertEqual(response.status_code, 302)
        self.assertEquals(len(mail.outbox), 1)

        msg = u'Hey-- just found a version of this video ("Tú - Jennifer Lopez") with captions: http://unisubs.example.com:8000/en/videos/OcuMvG3LrypJ/'
        url = _make_email_url(msg)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_demo(self):
        self._simple_test('videos:demo')

    def test_history(self):
        # Redirect for now, until we remove the concept of SubtitleLanguages
        # with blank language codes.
        self._simple_test('videos:history',
            [self.video.video_id], status=302)

        self._simple_test('videos:history',
            [self.video.video_id], data={'o': 'user', 'ot': 'asc'}, status=302)

        sl = self.video.subtitlelanguage_set.all()[:1].get()
        sl.language = 'en'
        sl.save()
        self._simple_test('videos:translation_history',
            [self.video.video_id, sl.language, sl.id])

    def _test_rollback(self):
        #TODO: Seems like roll back is not getting called (on models)
        self._login()

        version = self.video.version(0)
        last_version = self.video.version(public_only=False)

        self._simple_test('videos:rollback', [version.id], status=302)

        new_version = self.video.version()
        self.assertEqual(last_version.version_no+1, new_version.version_no)

    def test_model_rollback(self):
        video = Video.objects.all()[:1].get()
        lang = video.subtitlelanguage_set.all()[:1].get()
        v = lang.latest_version(public_only=True)
        v.is_forked = True
        v.save()

        new_v = SubtitleVersion(language=lang, version_no=v.version_no+1,
                                datetime_started=datetime.now())
        new_v.save()
        lang = SubtitleLanguage.objects.get(id=lang.id)

        self._login()

        self.client.get(reverse('videos:rollback', args=[v.id]), {})
        lang = SubtitleLanguage.objects.get(id=lang.id)
        last_v = lang.latest_version(public_only=True)
        self.assertTrue(last_v.is_forked)
        self.assertFalse(last_v.notification_sent)
        self.assertEqual(last_v.version_no, new_v.version_no+1)

    def test_rollback_updates_sub_count(self):
        video = Video.objects.all()[:1].get()
        lang = video.subtitlelanguage_set.all()[:1].get()
        v = lang.latest_version(public_only=False)
        num_subs = len(v.subtitles())
        v.is_forked  = True
        v.save()
        new_v = SubtitleVersion(language=lang, version_no=v.version_no+1,
                                datetime_started=datetime.now())
        new_v.save()
        for i in xrange(0,20):
            s, created = Subtitle.objects.get_or_create(
                version=new_v,
                subtitle_id= "%s" % i,
                subtitle_order=i,
                subtitle_text="%s lala" % i
            )
        self._login()
        self.client.get(reverse('videos:rollback', args=[v.id]), {})
        last_v  = (SubtitleLanguage.objects.get(id=lang.id)
                                           .latest_version(public_only=True))
        final_num_subs = len(last_v.subtitles())
        self.assertEqual(final_num_subs, num_subs)

    def test_diffing(self):
        version = self.video.version(version_no=0)
        last_version = self.video.version()
        response = self._simple_test('videos:diffing', [version.id, last_version.id])
        self.assertEqual(len(response.context['captions']), 5)

    def test_test_form_page(self):
        self._simple_test('videos:test_form_page')

        data = {
            'email': 'test@test.ua',
            'task1': 'test1',
            'task2': 'test2',
            'task3': 'test3'
        }
        response = self.client.post(reverse('videos:test_form_page'), data)
        self.assertEqual(response.status_code, 302)

        try:
            UserTestResult.objects.get(**data)
        except UserTestResult.DoesNotExist:
            self.fail()

    def test_search(self):
        self._simple_test('search:index')

    def test_counter(self):
        self._simple_test('counter')

    def test_test_mp4_page(self):
        self._simple_test('test-mp4-page')

    def test_test_ogg_page(self):
        self._simple_test('test-ogg-page')

    def test_opensubtitles2010_page(self):
        self._simple_test('opensubtitles2010_page')

    def test_faq_page(self):
        self._simple_test('faq_page')

    def test_about_page(self):
        self._simple_test('about_page')

    def test_demo_page(self):
        self._simple_test('demo')

    def test_policy_page(self):
        self._simple_test('policy_page')

    def test_volunteer_page_category(self):
        self._login()
        categories = ['featured', 'popular', 'requested', 'latest']
        for category in categories:
            url = reverse('videos:volunteer_category',
                          kwargs={'category': category})

            response = self.client.post(url)
            self.assertEqual(response.status_code, 200)


class YoutubeVideoTypeTest(TestCase):
    def setUp(self):
        self.vt = YoutubeVideoType
        self.data = [{
            'url': 'http://www.youtube.com/watch#!v=UOtJUmiUZ08&feature=featured&videos=Qf8YDn9mbGs',
            'video_id': 'UOtJUmiUZ08'
        },{
            'url': 'http://www.youtube.com/v/6Z5msRdai-Q',
            'video_id': '6Z5msRdai-Q'
        },{
            'url': 'http://www.youtube.com/watch?v=woobL2yAxD4',
            'video_id': 'woobL2yAxD4'
        },{
            'url': 'http://www.youtube.com/watch?v=woobL2yAxD4&amp;playnext=1&amp;videos=9ikUhlPnCT0&amp;feature=featured',
            'video_id': 'woobL2yAxD4'
        }]
        self.shorter_url = "http://youtu.be/HaAVZ2yXDBo"

    def test_create_kwars(self):
        vt = self.vt('http://www.youtube.com/watch?v=woobL2yAxD4')
        kwargs = vt.create_kwars()
        self.assertEqual(kwargs, {'videoid': 'woobL2yAxD4'})

    def test_set_values(self):
        youtbe_url = 'http://www.youtube.com/watch?v=_ShmidkrcY0'

        video, created = Video.get_or_create_for_url(youtbe_url)
        vu = video.videourl_set.all()[:1].get()

        self.assertEqual(vu.videoid, '_ShmidkrcY0')
        self.assertTrue(video.title)
        self.assertEqual(video.duration, 79)
        self.assertTrue(video.thumbnail)

    def test_matches_video_url(self):
        for item in self.data:
            self.assertTrue(self.vt.matches_video_url(item['url']))
            self.assertFalse(self.vt.matches_video_url('http://some-other-url.com'))
            self.assertFalse(self.vt.matches_video_url(''))
            self.assertFalse(self.vt.matches_video_url('http://youtube.com/'))
            self.assertFalse(self.vt.matches_video_url('http://youtube.com/some-video/'))
            self.assertTrue(self.vt.matches_video_url(self.shorter_url))

    def test_get_video_id(self):
        for item in self.data:
            self.failUnlessEqual(item['video_id'], self.vt._get_video_id(item['url']))

    def test_shorter_format(self):
        vt = self.vt(self.shorter_url)
        self.assertTrue(vt)
        self.assertEqual(vt.video_id , self.shorter_url.split("/")[-1])

    def test_subtitles_saving(self):
        youtube_url = 'http://www.youtube.com/watch?v=XDhJ8lVGbl8'

        vt = self.vt(youtube_url)
        video, created = Video.get_or_create_for_url(youtube_url)

        lang = vt.get_subtitled_languages()[0]

        save_subtitles_for_lang(lang, video.pk, video.video_id)

        sl = video.subtitle_language(lang['lang_code'])

        subtitles = sl.latest_subtitles()
        self.assertTrue(len(subtitles))
        self.assertEqual(subtitles[-1].text, u'Thanks.')

class HtmlFiveVideoTypeTest(TestCase):
    def setUp(self):
        self.vt = HtmlFiveVideoType

    def test_type(self):
        url = 'http://someurl.com/video.ogv?val=should&val1=be#removed'
        clean_url = 'http://someurl.com/video.ogv'

        video, created = Video.get_or_create_for_url(url)
        vu = video.videourl_set.all()[:1].get()

        self.assertEqual(vu.url, clean_url)
        self.assertEqual(self.vt.video_url(vu), vu.url)

        self.assertTrue(self.vt.matches_video_url(url))
        self.assertTrue(self.vt.matches_video_url('http://someurl.com/video.ogg'))
        self.assertTrue(self.vt.matches_video_url('http://someurl.com/video.mp4'))
        self.assertTrue(self.vt.matches_video_url('http://someurl.com/video.m4v'))
        self.assertTrue(self.vt.matches_video_url('http://someurl.com/video.webm'))

        self.assertFalse(self.vt.matches_video_url('http://someurl.ogv'))
        self.assertFalse(self.vt.matches_video_url(''))
        #for this is other type
        self.assertFalse(self.vt.matches_video_url('http://someurl.com/video.flv'))
        self.assertFalse(self.vt.matches_video_url('http://someurl.com/ogv.video'))

class Mp3VideoTypeTest(TestCase):
    def setUp(self):
        self.vt = Mp3VideoType

    def test_type(self):
        url = 'http://someurl.com/audio.mp3?val=should&val1=be#removed'
        clean_url = 'http://someurl.com/audio.mp3'

        video, created = Video.get_or_create_for_url(url)
        vu = video.videourl_set.all()[:1].get()

        self.assertEqual(vu.url, clean_url)
        self.assertEqual(self.vt.video_url(vu), vu.url)

        self.assertTrue(self.vt.matches_video_url(url))

        self.assertTrue(self.vt.matches_video_url('http://someurl.com/audio.mp3'))
        self.assertFalse(self.vt.matches_video_url('http://someurl.com/mp3.audio'))

class BlipTvVideoTypeTest(TestCase):
    def setUp(self):
        self.vt = BlipTvVideoType

    def test_type(self):
        url = 'http://blip.tv/day9tv/day-9-daily-438-p3-build-orders-made-easy-newbie-tuesday-6066868'
        video, created = Video.get_or_create_for_url(url)
        vu = video.videourl_set.all()[:1].get()

        # this is the id used to embed videos
        self.assertEqual(vu.videoid, 'hdljgvKmGAI')
        self.assertTrue(video.title)
        self.assertTrue(video.thumbnail)
        self.assertTrue(vu.url)

        self.assertTrue(self.vt.matches_video_url(url))
        self.assertTrue(self.vt.matches_video_url('http://blip.tv/day9tv/day-9-daily-438-p3-build-orders-made-easy-newbie-tuesday-6066868'))
        self.assertFalse(self.vt.matches_video_url('http://blip.tv'))
        self.assertFalse(self.vt.matches_video_url(''))

    def test_video_title(self):
        url = 'http://blip.tv/day9tv/day-9-daily-100-my-life-of-starcraft-3505715'
        video, created = Video.get_or_create_for_url(url)
        #really this should be jsut not failed
        self.assertTrue(video.get_absolute_url())

    def test_creating(self):
        # this test is for ticket: https://www.pivotaltracker.com/story/show/12996607
        url = 'http://blip.tv/day9tv/day-9-daily-1-flash-vs-hero-3515432'
        video, created = Video.get_or_create_for_url(url)

class DailymotionVideoTypeTest(TestCase):
    def setUp(self):
        self.vt = DailymotionVideoType

    def test_type(self):
        url = 'http://www.dailymotion.com/video/x7u2ww_juliette-drums_lifestyle#hp-b-l'

        video, created = Video.get_or_create_for_url(url)
        vu = video.videourl_set.all()[:1].get()

        self.assertEqual(vu.videoid, 'x7u2ww')
        self.assertTrue(video.title)
        self.assertTrue(video.thumbnail)
        self.assertEqual(vu.url, 'http://dailymotion.com/video/x7u2ww')
        self.assertTrue(self.vt.video_url(vu))

        self.assertTrue(self.vt.matches_video_url(url))
        self.assertFalse(self.vt.matches_video_url(''))
        self.assertFalse(self.vt.matches_video_url('http://www.dailymotion.com'))

    def test_type1(self):
        url = u'http://www.dailymotion.com/video/edit/xjhzgb_projet-de-maison-des-services-a-fauquembergues_news'
        vt = self.vt(url)
        try:
            vt.get_metadata(vt.videoid)
            self.fail('This link should return wrong response')
        except VideoTypeError:
            pass

class FLVVideoTypeTest(TestCase):
    def setUp(self):
        self.vt = FLVVideoType

    def test_type(self):
        url = 'http://someurl.com/video.flv?val=should&val1=be#removed'
        clean_url = 'http://someurl.com/video.flv'

        video, created = Video.get_or_create_for_url(url)
        vu = video.videourl_set.all()[:1].get()

        self.assertEqual(vu.url, clean_url)
        self.assertEqual(self.vt.video_url(vu), vu.url)

        self.assertTrue(self.vt.matches_video_url(url))

        self.assertFalse(self.vt.matches_video_url('http://someurl.flv'))
        self.assertFalse(self.vt.matches_video_url(''))
        self.assertFalse(self.vt.matches_video_url('http://someurl.com/flv.video'))

    def test_blip_type(self):
        url = 'http://blip.tv/file/get/Coldguy-SpineBreakersLiveAWizardOfEarthsea210.FLV'
        video, created = Video.get_or_create_for_url(url)
        video_url = video.videourl_set.all()[0]
        self.assertEqual(self.vt.abbreviation, video_url.type)

class VimeoVideoTypeTest(TestCase):
    def setUp(self):
        self.vt = VimeoVideoType

    def test_type(self):
        url = 'http://vimeo.com/15786066?some_param=111'

        video, created = Video.get_or_create_for_url(url)
        vu = video.videourl_set.all()[:1].get()

        self.assertEqual(vu.videoid, '15786066')
        self.assertTrue(self.vt.video_url(vu))

        self.assertTrue(self.vt.matches_video_url(url))

        self.assertFalse(self.vt.matches_video_url('http://vimeo.com'))
        self.assertFalse(self.vt.matches_video_url(''))

    def test1(self):
        #For this video Vimeo API returns response with strance error
        #But we can get data from this response. See vidscraper.sites.vimeo.get_shortmem
        #So if this test is failed - maybe API was just fixed and other response is returned
        # FIXME: restablish when vimeo api is back!
        return
        url = u'http://vimeo.com/22070806'
        video, created = Video.get_or_create_for_url(url)

        self.assertNotEqual(video.title, '')
        self.assertNotEqual(video.description, '')
        vu = video.videourl_set.all()[:1].get()

        self.assertEqual(vu.videoid, '22070806')
        self.assertTrue(self.vt.video_url(vu))


class VideoTypeRegistrarTest(TestCase):
    def test_base(self):
        registrar = VideoTypeRegistrar()

        class MockupVideoType(VideoType):
            abbreviation = 'mockup'
            name = 'MockUp'

        registrar.register(MockupVideoType)
        self.assertEqual(registrar[MockupVideoType.abbreviation], MockupVideoType)
        self.assertEqual(registrar.choices[-1], (MockupVideoType.abbreviation, MockupVideoType.name))

    def test_video_type_for_url(self):
        type = video_type_registrar.video_type_for_url('some url')
        self.assertEqual(type, None)
        type = video_type_registrar.video_type_for_url('http://youtube.com/v=UOtJUmiUZ08')
        self.assertTrue(isinstance(type, YoutubeVideoType))
        self.assertRaises(VideoTypeError, video_type_registrar.video_type_for_url,
                          'http://youtube.com/v=100500')


class TestFeedsSubmit(TestCase):
    def setUp(self):
        self.client.login(username='admin', password='admin')

    def test_video_feed_submit(self):
        old_count = Video.objects.count()
        data = {
            'feed_url': u'http://blip.tv/day9tv/rss'
        }
        response = self.client.post(reverse('videos:create_from_feed'), data)
        self.assertRedirects(response, reverse('videos:create'))
        self.assertNotEqual(old_count, Video.objects.count())

    def test_empty_feed_submit(self):
        base_open_resource = feedparser._open_resource

        def _open_resource_mock(*args, **kwargs):
            return StringIO(str(u"".join([u"<?xml version='1.0' encoding='UTF-8'?>",
            u"<feed xmlns='http://www.w3.org/2005/Atom' xmlns:openSearch='http://a9.com/-/spec/opensearchrss/1.0/'>",
            u"<id>http://gdata.youtube.com/feeds/api/users/test/uploads</id>",
            u"<updated>2011-07-05T09:17:40.888Z</updated>",
            u"<category scheme='http://schemas.google.com/g/2005#kind' term='http://gdata.youtube.com/schemas/2007#video'/>",
            u"<title type='text'>Uploads by test</title>",
            u"<logo>http://www.youtube.com/img/pic_youtubelogo_123x63.gif</logo>",
            u"<link rel='related' type='application/atom+xml' href='https://gdata.youtube.com/feeds/api/users/test'/>",
            u"<link rel='alternate' type='text/html' href='https://www.youtube.com/profile_videos?user=test'/>",
            u"<link rel='http://schemas.google.com/g/2005#feed' type='application/atom+xml' href='https://gdata.youtube.com/feeds/api/users/test/uploads'/>",
            u"<link rel='http://schemas.google.com/g/2005#batch' type='application/atom+xml' href='https://gdata.youtube.com/feeds/api/users/test/uploads/batch'/>",
            u"<link rel='self' type='application/atom+xml' href='https://gdata.youtube.com/feeds/api/users/test/uploads?start-index=1&amp;max-results=25'/>",
            u"<author><name>test</name><uri>https://gdata.youtube.com/feeds/api/users/test</uri></author>",
            u"<generator version='2.0' uri='http://gdata.youtube.com/'>YouTube data API</generator>",
            u"<openSearch:totalResults>0</openSearch:totalResults><openSearch:startIndex>1</openSearch:startIndex>",
            u"<openSearch:itemsPerPage>25</openSearch:itemsPerPage></feed>"])))

        feedparser._open_resource = _open_resource_mock

        old_count = Video.objects.count()
        feed_url = u'http://gdata.youtube.com/feeds/api/users/testempty/uploads'
        data = {
            'feed_url': feed_url,
            'save_feed': True
        }
        response = self.client.post(reverse('videos:create_from_feed'), data)
        self.assertRedirects(response, reverse('videos:create'))
        self.assertEqual(old_count, Video.objects.count())

        vf = VideoFeed.objects.get(url=feed_url)
        self.assertEqual(vf.last_link, '')

        feedparser._open_resource = base_open_resource


class BrightcoveVideoTypeTest(TestCase):
    def setUp(self):
        self.vt = BrightcoveVideoType

    def test_type(self):
        url  = 'http://link.brightcove.com/services/player/bcpid955357260001?bckey=AQ~~,AAAA3ijeRPk~,jc2SmUL6QMyqTwfTFhUbWr3dg6Oi980j&bctid=956115196001'
        video, created = Video.get_or_create_for_url(url)
        vu = video.videourl_set.all()[:1].get()
        self.assertTrue(vu.type ==  VIDEO_TYPE_BRIGHTCOVE == BrightcoveVideoType.abbreviation)
        self.assertTrue(self.vt.video_url(vu))
        self.assertTrue(self.vt.matches_video_url(url))

    def test_redirection(self):
        url  = 'http://bcove.me/7fa5828z'
        vt = video_type_registrar.video_type_for_url(url)
        self.assertTrue(vt)
        self.assertEqual(vt.video_id, '956115196001')


class TestTasks(TestCase):
    fixtures = ['test.json']

    def setUp(self):
        self.user = User.objects.get(pk=2)
        self.video = Video.objects.all()[:1].get()
        self.language = self.video.subtitle_language()
        self.language.language = 'en'
        self.language.save()
        self.latest_version = self.language.latest_version(public_only=True)

        self.latest_version.user.notify_by_email = True
        self.latest_version.user.is_active = True
        self.latest_version.user.save()

        self.language.followers.add(self.latest_version.user)
        self.video.followers.add(self.latest_version.user)

    def test_send_change_title_email(self):
        user = User.objects.all()[:1].get()

        self.assertFalse(self.video.followers.count() == 1
                         and self.video.followers.all()[:1].get() == user)

        old_title = self.video.title
        new_title = u'New title'
        self.video.title = new_title
        self.video.save()

        result = send_change_title_email.delay(self.video.id, user.id,
                                               old_title, new_title)
        if result.failed():
            self.fail(result.traceback)
        self.assertEqual(len(mail.outbox), 1)

        mail.outbox = []
        result = send_change_title_email.delay(self.video.id, None, old_title,
                                               new_title)
        if result.failed():
            self.fail(result.traceback)
        self.assertEqual(len(mail.outbox), 1)

    def test_notification_sending(self):
        """
        Make the system send updates only on the object being followed
        (language vs. video).

        The following is taken directly from the ticket
        -----------------------------------------------

        1. Followers of a video (submitter + anyone who chose to follow the
            video) should:

            * Be listed as followers for each language of this video
            * Get notifications about any changes made to the video or any of
                the related languages.
            * Get notifications about any comments left on the video or any of
                the related videos.

        2. Followers of a language (followers of language +
            transcriber(s)/translator(s) + editor(s) + anyone who chose to
            follow the language) should:

            * Get notifications about any changes made to the subtitles in
                this language, but not in any other language for the same video.
            * Get notifications about comments made on the subtitles in this
                language, but not in any other language for the video, nor on
                the video as a whole entity.
        """

        # Video is submitted by self.user (pk 2, admin@mail.net)
        # The submitter is automatically added to followers via the
        # ``Video.get_or_create_for_url`` method.  Here we do that by hand.
        self.assertEquals(0, Message.objects.count())
        self.assertEquals(0, Comment.objects.count())
        self.video.user = self.user
        self.video.user.notify_by_email = True
        self.video.user.notify_by_message = False
        self.video.user.save()
        self.video.followers.add(self.user)
        self.video.save()

        # Create a user that only follows the language
        user_language_only = User.objects.create(username='languageonly',
                email='dude@gmail.com', notify_by_email=True,
                notify_by_message=True)

        user_language2_only = User.objects.create(username='languageonly2',
                email='dude2@gmail.com', notify_by_email=True,
                notify_by_message=True)

        # Create a user that will make the edits
        user_edit_maker = User.objects.create(username='editmaker',
                email='maker@gmail.com', notify_by_email=True,
                notify_by_message=True)

        latest_version = self.language.latest_version()
        latest_version.language.followers.clear()
        latest_version.language.followers.add(user_language_only)
        latest_version.title = 'Old title'
        latest_version.description = 'Old description'
        latest_version.save()

        # Create another language
        lan2 = SubtitleLanguage.objects.create(video=self.video, language='cz')
        lan2.followers.add(user_language2_only)
        self.assertEquals(2, SubtitleLanguage.objects.count())

        v = SubtitleVersion()
        v.language = self.language
        v.datetime_started = datetime.now()
        v.version_no = latest_version.version_no+1
        v.user = user_edit_maker
        v.title = 'New title'
        v.description = 'New description'
        v.save()

        for s in latest_version.subtitle_set.all():
            s.duplicate_for(v).save()

        s = Subtitle()
        s.version = v
        s.subtitle_id = 'asdasdsadasdasdasd'
        s.subtitle_order = 5
        s.subtitle_text = 'new subtitle'
        s.start_time = 50
        s.end_time = 51
        s.save()

        # Clear the box because the above generates some emails
        mail.outbox = []

        # Kick it off
        video_changed_tasks.delay(v.video.id, v.id)

        # --------------------------------------------------------------------

        # How many emails should we have?
        # * The submitter
        # * All video followers who want emails
        # * All followers of the language being changed
        # * Minus the change author
        #
        # In our case that is: languageonly, adam, admin
        people = set(self.video.followers.filter(notify_by_email=True))
        people.update(self.language.followers.filter(notify_by_email=True))

        number = len(list(people)) - 1  # for the editor
        self.assertEqual(len(mail.outbox), number)

        email = mail.outbox[0]
        tos = [item for sublist in mail.outbox for item in sublist.to]

        self.assertTrue('New description' in email.body)
        self.assertTrue('Old description' in email.body)
        self.assertTrue('New title' in email.body)
        self.assertTrue('Old title' in email.body)

        # Make sure that all followers of the video got notified
        # Excluding the author of the new version
        excludes = list(User.objects.filter(email__in=[v.user.email]).all())
        self.assertEquals(1, len(excludes))
        followers = self.video.notification_list(excludes)
        self.assertTrue(excludes[0].notify_by_email and
                excludes[0].notify_by_message)
        self.assertTrue(followers.filter(pk=self.video.user.pk).exists())

        for follower in followers:
            self.assertTrue(follower.email in tos)

        self.assertTrue(self.user.notify_by_email)
        self.assertTrue(self.user.email in tos)

        # Refresh objects
        self.user = User.objects.get(pk=self.user.pk)
        self.video = Video.objects.get(pk=self.video.pk)

        # Messages sent?
        self.assertFalse(self.video.user.notify_by_message)
        self.assertFalse(User.objects.get(pk=self.video.user.pk).notify_by_message)
        followers = self.video.followers.filter(
                notify_by_message=True).exclude(pk__in=[e.pk for e in excludes])

        self.assertEquals(followers.count(), 1)
        self.assertNotEquals(followers[0].pk, self.user.pk)

        self.assertEquals(followers.count(), Message.objects.count())
        for follower in followers:
            self.assertTrue(Message.objects.filter(user=follower).exists())

        language_follower_email = None
        for email in mail.outbox:
            if user_language_only.email in email.to:
                language_follower_email = email
                break

        self.assertFalse(language_follower_email is None)

        # --------------------------------------------------------------------
        # Now test comment notifications

        Message.objects.all().delete()
        mail.outbox = []

        # Video comment first
        form =  CommentForm(self.video, {
            'content': 'Text',
            'object_pk': self.video.pk,
            'content_type': ContentType.objects.get_for_model(self.video).pk
            })
        form.save(self.user, commit=True)

        self.assertEquals(1, Comment.objects.count())
        self.assertEqual(len(mail.outbox), 1)

        emails = []
        for e in mail.outbox:
            for a in e.to:
                emails.append(a)

        followers = self.video.followers.filter(notify_by_email=True)
        self.assertEquals(emails.sort(), [f.email for f in followers].sort())

        followers = self.video.followers.filter(notify_by_email=False)
        for follower in followers:
            self.assertFalse(follower.email in emails)

        followers = self.video.followers.filter(notify_by_message=True)
        self.assertEquals(followers.count(), Message.objects.count())
        for message in Message.objects.all():
            self.assertTrue(isinstance(message.object, Video))
            self.assertTrue(message.user in list(followers))

        # And now test comments on languages
        Message.objects.all().delete()
        mail.outbox = []

        form =  CommentForm(self.language, {
            'content': 'Text',
            'object_pk': self.language.pk,
            'content_type': ContentType.objects.get_for_model(self.language).pk
            })
        form.save(self.user, commit=True)

        self.assertEquals(Message.objects.count(),
                self.language.followers.filter(notify_by_message=True).count())

        followers = self.language.followers.filter(notify_by_message=True)

        # The author of the comment shouldn't get a message
        self.assertFalse(Message.objects.filter(user=self.user).exists())

        lan2 = SubtitleLanguage.objects.get(pk=lan2.pk)
        lan2_followers = lan2.followers.all()

        for message in Message.objects.all():
            self.assertTrue(isinstance(message.object,
                SubtitleLanguage))
            self.assertTrue(message.user in list(followers))
            self.assertFalse(message.user in list(lan2_followers))



class TestPercentComplete(TestCase):
    fixtures = ['test.json']

    def _create_trans(self, latest_version=None, lang_code=None, forked=False):
        translation = SubtitleLanguage()
        translation.video = self.video
        translation.language = lang_code
        translation.is_original = False
        translation.is_forked = forked
        if not forked:
           translation.standard_language = self.video.subtitle_language()
        translation.save()

        self.translation = translation

        v = SubtitleVersion()
        v.language = translation
        if latest_version:
            v.version_no = latest_version.version_no+1
        else:
            v.version_no = 1
        v.datetime_started = datetime.now()
        v.save()

        self.translation_version = v
        if latest_version is not None:
            for s in latest_version.subtitle_set.all():
                s.duplicate_for(v).save()
        return translation

    def setUp(self):
        self.video = Video.objects.all()[:1].get()
        self.original_language = self.video.subtitle_language()
        latest_version = self.original_language.latest_version()
        self.translation = self._create_trans(latest_version, 'uk')

    def test_percent_done(self):
        video_changed_tasks.delay(self.translation.video.id)
        translation = SubtitleLanguage.objects.get(id=self.translation.id)
        self.assertEqual(translation.percent_done, 100)

    def test_delete_from_original(self):
        latest_version = self.original_language.latest_version()
        latest_version.subtitle_set.all()[:1].get().delete()
        video_changed_tasks.delay(self.translation.video.id)
        translation = SubtitleLanguage.objects.get(id=self.translation.id)
        self.assertEqual(translation.percent_done, 100)

    def test_adding_to_original(self):
        latest_version = self.original_language.latest_version()
        s = Subtitle()
        s.version = latest_version
        s.subtitle_id = 'asdasdsadasdasdasd'
        s.subtitle_order = 5
        s.subtitle_text = 'new subtitle'
        s.start_time = 50
        s.end_time = 51
        s.save()

        video_changed_tasks.delay(self.translation.video.id)
        translation = SubtitleLanguage.objects.get(id=self.translation.id)
        self.assertEqual(translation.percent_done, 4/5.*100)

    def test_delete_all(self):
        for s in self.translation_version.subtitle_set.all():
            s.delete()
        video_changed_tasks.delay(self.translation.video.id)
        translation = SubtitleLanguage.objects.get(id=self.translation.id)
        self.assertEqual(translation.percent_done, 0)

    def test_delete_from_translation(self):
        self.translation_version.subtitle_set.all()[:1].get().delete()
        video_changed_tasks.delay(self.translation.video.id)
        translation = SubtitleLanguage.objects.get(id=self.translation.id)
        self.assertEqual(translation.percent_done, 75)

    def test_many_subtitles(self):
        latest_version = self.original_language.latest_version()
        for i in range(2, 450):
            s = Subtitle()
            s.version = latest_version
            s.subtitle_id = 'sadfdasf%s' % i
            s.subtitle_order = i
            s.start_time = 50 + i
            s.end_time = 51 + i
            s.subtitle_text = "what %i" % i
            s.save()

        video_changed_tasks.delay(self.translation.video.id)
        translation = SubtitleLanguage.objects.get(id=self.translation.id)
        # 1% reflects https://www.pivotaltracker.com/story/show/16013319
        self.assertEqual(translation.percent_done, 1)

    def test_count_as_complete(self):
        self.assertFalse(self.video.complete_date)
        # set the original lang as complete, should be completed
        video_changed_tasks.delay(self.translation.video.id)
        translation = SubtitleLanguage.objects.get(id=self.translation.id)
        self.assertEqual(translation.percent_done, 100)
        self.assertTrue(translation.is_complete)
        self.translation.save()


    def test_video_0_subs_are_never_complete(self):
        self.original_language = self.video.subtitle_language()
        new_lang = self._create_trans(None, 'it', True)
        self.assertFalse(self.video.is_complete, False)
        metadata_manager.update_metadata(self.video.pk)
        new_lang.save()
        self.video.subtitlelanguage_set.all().filter(percent_done=100).delete()
        self.assertFalse(self.video.is_complete)


class TestAlert(TestCase):
    fixtures = ['test.json']

    def setUp(self):
        self.video = Video.objects.all()[:1].get()
        self.original_language = self.video.subtitle_language()
        self.latest_version = self.original_language.latest_version()
        settings.ALERT_EMAIL = 'test@test.com'

    def _new_version(self, lang=None):
        v = SubtitleVersion()
        v.language = lang or self.original_language
        v.datetime_started = datetime.now()
        lv = v.language.latest_version()
        v.version_no = lv and lv.version_no+1 or 1
        v.save()
        return v

    def test_other_languages_changes(self):
        v = self._new_version()
        l = SubtitleLanguage(video=self.video, language='ru', is_original=False)
        l.save()
        self._new_version(l)
        alarms.check_other_languages_changes(v, ignore_statistic=True)
        self.assertEquals(len(mail.outbox), 1)

    def test_check_language_name_success(self):
        self.original_language.language = 'en'
        self.original_language.save()

        v = self._new_version()

        Subtitle(version=v, subtitle_id=u'AaAaAaAaAa', subtitle_text='Django is a high-level Python Web framework that encourages rapid development and clean, pragmatic design.').save()
        Subtitle(version=v, subtitle_id=u'BaBaBaBaBa', subtitle_text='Developed four years ago by a fast-moving online-news operation').save()

        alarms.check_language_name(v, ignore_statistic=True)

        self.assertEquals(len(mail.outbox), 0)

    def test_check_language_name_fail(self):
        self.original_language.language = 'en'
        self.original_language.save()
        # disabling this test for now, since the google ajax api
        # is returning 403s
        return
        v = self._new_version()

        #this is reliable Ukrainian language
        Subtitle(version=v, subtitle_id=u'AaAaAaAaAa1', subtitle_text=u'Якась не зрозумiла мова.').save()
        Subtitle(version=v, subtitle_id=u'BaBaBaBaBa1', subtitle_text='Якась не зрозумiла мова.').save()

        alarms.check_language_name(v, ignore_statistic=True)

        self.assertEquals(len(mail.outbox), 1)

        v = self._new_version()

        #this one is unreliable
        Subtitle(version=v, subtitle_id=u'AaAaAaAaAa2', subtitle_text=u'Яsdasdзроasdзумiddаsda.').save()
        Subtitle(version=v, subtitle_id=u'BaBaBaBaBa2', subtitle_text='Якasdсьadsdе sdзрdмiлasdва.').save()

        alarms.check_language_name(v, ignore_statistic=True)

        self.assertEquals(len(mail.outbox), 2)

class TestModelsSaving(TestCase):

    fixtures = ['test.json']

    def setUp(self):
        self.video = Video.objects.all()[:1].get()
        self.language = self.video.subtitle_language()
        self.language.is_complete = False
        self.language.save()

    def test_video_languages_count(self):
        from videos.tasks import video_changed_tasks

        #test if fixtures has correct data
        langs_count = self.video.subtitlelanguage_set.filter(had_version=True).count()

        self.assertEqual(self.video.languages_count, langs_count)
        self.assertTrue(self.video.languages_count > 0)

        self.video.languages_count = 0
        self.video.save()
        video_changed_tasks.delay(self.video.pk)
        self.video = Video.objects.get(id=self.video.id)
        self.assertEqual(self.video.languages_count, langs_count)

    def test_subtitle_language_save(self):
        self.assertEqual(self.video.complete_date, None)
        self.assertEqual(self.video.subtitlelanguage_set.count(), 1)

        self.language.is_complete = True
        self.language.save()
        from videos.tasks import video_changed_tasks
        video_changed_tasks.delay(self.video.pk)
        self.video = Video.objects.get(pk=self.video.pk)
        self.assertNotEqual(self.video.complete_date, None)

        self.language.is_complete = False
        self.language.save()
        video_changed_tasks.delay(self.video.pk)
        self.video = Video.objects.get(pk=self.video.pk)
        self.assertEqual(self.video.complete_date, None)

        #add one more SubtitleLanguage
        l = SubtitleLanguage(video=self.video)
        l.is_original = False
        l.is_complete = True
        l.save()
        video_changed_tasks.delay(self.video.pk)
        self.video = Video.objects.get(pk=self.video.pk)
# FIXME: Why should complete_date be non-null here?
#        self.assertNotEqual(self.video.complete_date, None)

        self.language.is_complete = True
        self.language.save()
        video_changed_tasks.delay(self.video.pk)
        self.video = Video.objects.get(pk=self.video.pk)
        self.assertNotEqual(self.video.complete_date, None)

        l.is_complete = False
        l.save()
        video_changed_tasks.delay(self.video.pk)
        self.video = Video.objects.get(pk=self.video.pk)
        self.assertNotEqual(self.video.complete_date, None)

        self.language.is_complete = False
        self.language.save()
        video_changed_tasks.delay(self.video.pk)
        self.video = Video.objects.get(pk=self.video.pk)
        self.assertEqual(self.video.complete_date, None)

        self.language.is_complete = True
        self.language.save()
        video_changed_tasks.delay(self.video.pk)
        self.video = Video.objects.get(pk=self.video.pk)
        self.assertNotEqual(self.video.complete_date, None)

        l.is_complete = True
        l.save()
        video_changed_tasks.delay(self.video.pk)
        self.video = Video.objects.get(pk=self.video.pk)
        self.assertNotEqual(self.video.complete_date, None)

        self.language.delete()
        video_changed_tasks.delay(self.video.pk)
        self.video = Video.objects.get(pk=self.video.pk)
# FIXME: why should complete_date be non-null here?
#        self.assertNotEqual(self.video.complete_date, None)

        l.delete()
        video_changed_tasks.delay(self.video.pk)
        self.video = Video.objects.get(pk=self.video.pk)
        self.assertEqual(self.video.complete_date, None)

    def test_fork_preserves_ordering(self):
        """
        When forking , even unsyched subs should have their ordering preserved
        """
        lang = SubtitleLanguage(language="pt", video=self.video, standard_language=self.video.subtitle_language(), is_forked=False)
        lang.save()
        create_version(lang, [
                {
                   "subtitle_order" : 1,
                   "subtitle_text": "t1",
                   "subtitle_id": "id1",
                 },
                  {
                   "subtitle_order" : 2,
                   "subtitle_text": "t2",
                   "subtitle_id": "id2",
                 },
                  {
                   "subtitle_order" : 3,
                   "subtitle_text": "t3",
                   "subtitle_id": "id3",
                 },

        ])
        self.assertEqual(lang.is_forked, False)

        lang.fork(user=User.objects.all()[0])
        lang = SubtitleLanguage.objects.get(pk=lang.pk)
        version = lang.latest_version()
        self.assertTrue(lang.is_forked )
        subs = version.subtitles()
        self.assertEqual(len(subs), 3)
        for x in subs:
            self.assertTrue(x.sub_order > 0)

        # now fork throught the rpc
        u, created = User.objects.get_or_create(username='admin')
        u.set_password("admin")
        u.save()
        from widget.rpc import Rpc
        from widget.tests import RequestMockup

        rpc = Rpc()
        self.client.login(**{"username":"admin", "password":"admin"})
        request = RequestMockup(user=u)
        request.user = u
        return_value = rpc.start_editing(
            request,
            self.video.video_id,
            "eu",
            base_language_pk=lang.pk
        )
        session_pk = return_value['session_pk']
        inserted = [{'subtitle_id': 'aa',
                     'text': 'hey!',
                     'start_time': 2.3,
                     'end_time': 3.4,
                     'sub_order': 4.0}]
        rpc.finished_subtitles(request, session_pk, inserted);

        return_value = rpc.start_editing(
            request,
            self.video.video_id,
            "eu",
        )
        session_pk = return_value['session_pk']
        inserted = []
        for s in subs:
            inserted.append({
                    'subtitle_id': s.subtitle_id,
                     'text': s.text,
                     'start_time': s.start_time,
                     'end_time': s.end_time,
                     'sub_order': s.sub_order}
                )
        inserted.append( {'subtitle_id': 'ac',
                     'text': 'hey!',
                     'start_time': 4.3,
                     'end_time': 5.4,
                     'sub_order': 5.0})
        rpc.finished_subtitles(request, session_pk, inserted, forked=True);
        lang = self.video.subtitlelanguage_set.get(language='eu', is_forked=True)
        version2 = lang.latest_version()
        self.assertTrue(lang.is_forked )

        subs = version2.subtitles()
        self.assertEqual(len(subs), 4)
        for x in subs:
            self.assertTrue(x.sub_order > 0)


class TestVideoForm(TestCase):
    def setUp(self):
        self.vimeo_urls = ("http://vimeo.com/17853047",)
        self.youtube_urls = ("http://youtu.be/HaAVZ2yXDBo", "http://www.youtube.com/watch?v=HaAVZ2yXDBo")
        self.html5_urls = ("http://blip.tv/file/get/Miropcf-AboutUniversalSubtitles715.mp4",)
        self.daily_motion_urls = ("http://www.dailymotion.com/video/xb0hsu_qu-est-ce-que-l-apache-software-fou_tech",)

    def _test_urls(self, urls):
        for url in urls:
            form = VideoForm(data={"video_url":url})
            self.assertTrue(form.is_valid())
            video = form.save()
            video_type = video_type_registrar.video_type_for_url(url)
            # double check we never confuse video_id with video.id with videoid, sigh
            model_url = video.get_video_url()
            if hasattr(video_type, "videoid"):
                self.assertTrue(video_type.videoid  in model_url)
            # check the pk is never on any of the urls parts
            for part in model_url.split("/"):
                self.assertTrue(str(video.pk)  != part)
            self.assertTrue(video.video_id  not in model_url)

            self.assertTrue(Video.objects.filter(videourl__url=model_url).exists())

    def test_youtube_urls(self):
        self._test_urls(self.youtube_urls)

    def test_vimeo_urls(self):
        self._test_urls(self.vimeo_urls)

    def test_html5_urls(self):
        self._test_urls(self.html5_urls)

    def test_dailymotion_urls(self):
        self._test_urls(self.daily_motion_urls)


class TestFeedParser(TestCase):
    #TODO: add test for MediaFeedEntryParser. I just can't find RSS link for it
    #RSS should look like this http://www.dailymotion.com/rss/ru/featured/channel/tech/1
    #but not from supported site
    youtube_feed_url_pattern =  'https://gdata.youtube.com/feeds/api/users/%s/uploads'
    youtube_username = 'universalsubtitles'

    mit_feed_url = 'http://ocw.mit.edu/rss/new/ocw_youtube_videos.xml'

    vimeo_feed_url = 'http://vimeo.com/blakewhitman/videos/rss'

    def setUp(self):
        pass

    def test_vimeo_feed_parsing(self):
        # vimeo is blocking us from jenkins, we need to coordinate with
        # them on how best to proceed here
        return
        feed_parser = FeedParser(self.vimeo_feed_url)
        vt, info, entry = feed_parser.items().next()
        self.assertTrue(isinstance(vt, VimeoVideoType))

        video, created = Video.get_or_create_for_url(vt=vt)
        self.assertTrue(video)

    def test_youtube_feed_parsing(self):
        feed_url = self.youtube_feed_url_pattern % self.youtube_username

        feed_parser = FeedParser(feed_url)
        vt, info, entry = feed_parser.items().next()
        self.assertTrue(isinstance(vt, YoutubeVideoType))

        video, created = Video.get_or_create_for_url(vt=vt)
        self.assertTrue(video)

    def test_mit_feed_parsing(self):
        """
        If this test fails - try check few feed entries. Not all entries from
        MIT feed contain videos, so if sometime they delete some etries - test
        can fail.
        """
        feed_parser = FeedParser(self.mit_feed_url)
        vt, info, entry = feed_parser.items().next()
        self.assertTrue(isinstance(vt, HtmlFiveVideoType))

        video, created = Video.get_or_create_for_url(vt=vt)
        self.assertTrue(video)

# FIXME: this test is failing, and it looks like it's because of the feed.
#    def test_enclosure_parsing(self):
#        feed_url = 'http://webcast.berkeley.edu/media/common/rss/Computer_Science_10__001_Spring_2011_Video__webcast.rss'
#
#        feed_parser = FeedParser(feed_url)
#        vt, info, entry = feed_parser.items().next()
#        self.assertTrue(isinstance(vt, HtmlFiveVideoType))
#
#        video, created = Video.get_or_create_for_url(vt=vt)
#        self.assertTrue(video)

    def test_dailymotion_feed_parsing(self):
        feed_url = 'http://www.dailymotion.com/rss/ru/featured/channel/tech/1'

        feed_parser = FeedParser(feed_url)
        vt, info, entry = feed_parser.items().next()
        self.assertTrue(isinstance(vt, DailymotionVideoType))

        video, created = Video.get_or_create_for_url(vt=vt)
        self.assertTrue(video)

class TestTemplateTags(TestCase):
    def setUp(self):
        from django.conf import settings
        self.auth = {
            "username": u"admin",
            "password": u"admin"
        }
        fixture_path = os.path.join(settings.PROJECT_ROOT, "apps", "videos", "fixtures", "teams-list.json")
        data = json.load(open(fixture_path))
        self.videos = _create_videos(data, [])

    def test_complete_indicator(self):
        from apps.videos.templatetags.subtitles_tags import complete_indicator
        # one original  complete
        l = SubtitleLanguage.objects.filter(is_original=True, is_complete=True)[0]
        self.assertEqual("100%", complete_indicator(l))
        # one original non complete with 0 subs

        l = SubtitleLanguage.objects.filter(is_forked=True, is_complete=False)[0]
        self.assertEqual("0 Lines", complete_indicator(l))
        # one original noncomplete 2 subs
        l = SubtitleLanguage.objects.filter(video__title="6", is_original=True)[0]
        self.assertEqual("2 Lines", complete_indicator(l))
        # one trans non complete
        l = SubtitleLanguage.objects.filter(video__title="b", language='pt')[0]
        self.assertEqual("60%", complete_indicator(l))


    def test_language_url_for_empty_lang(self):
        v = self.videos[0]
        l = SubtitleLanguage(video=v, has_version=True)
        l.save()
        from videos.templatetags.subtitles_tags import language_url
        language_url(None, l)


class TestMetadataManager(TestCase):

    fixtures = ['staging_users.json', 'staging_videos.json']

    def test_subtitles_count(self):
        v = Video.objects.all()[0]
        lang = SubtitleLanguage(language='en', video=v, is_forked=True)
        lang.save()
        v1 = create_version(lang, [
                {
                   "subtitle_order" : 1,
                   "subtitle_text": "",
                   "subtitle_id": "id1",
                    'start_time': 1,
                    'end_time': 2,

                 },
                  {
                   "subtitle_order" : 2,
                   "subtitle_text": "   ",
                   "subtitle_id": "id2",
                    'start_time': 3,
                    'end_time': 4,
                 },
                  {
                   "subtitle_order" : 3,
                   "subtitle_text": "t3",
                   "subtitle_id": "id3",
                    'start_time': 5,
                    'end_time': 6,
                 },

        ])
        v1.is_forked = True
        v1.save()
        metadata_manager.update_metadata(v.pk)
        lang = refresh_obj(lang)
        v1 = lang.version()
        self.assertEqual(len(v1.subtitles()), 3)
        self.assertEqual(lang.subtitle_count, 1)

def _create_trans( video, latest_version=None, lang_code=None, forked=False):
        translation = SubtitleLanguage()
        translation.video = video
        translation.language = lang_code
        translation.is_original = False
        translation.is_forked = forked
        if not forked:
            translation.standard_language = video.subtitle_language()
        translation.save()
        v = SubtitleVersion()
        v.language = translation
        if latest_version:
            v.version_no = latest_version.version_no+1
        else:
            v.version_no = 1
        v.datetime_started = datetime.now()
        v.save()

        if latest_version is not None:
            for s in latest_version.subtitle_set.all():
                s.duplicate_for(v).save()
        return translation

def create_version(lang, subs=None, user=None):
    latest = lang.latest_version()
    version_no = latest and latest.version_no + 1 or 1
    version = SubtitleVersion(version_no=version_no,
                              user=user or User.objects.all()[0],
                              language=lang,
                              datetime_started=datetime.now())
    version.is_forked = lang.is_forked
    version.save()
    if subs is None:
        subs = []
        for x in xrange(0,5):
            subs.append({
                "subtitle_text": "hey %s" % x,
                "subtitle_id": "%s-%s-%s" % (version_no, lang.pk, x),
                "start_time": x,
                "end_time": (x* 1.0) - 0.1
            })
    for sub in subs:
        s = Subtitle(**sub)
        s.version  = version
        s.save()
    return version


class TestSubtitleMetadata(TestCase):
    fixtures = ['staging_users.json', 'staging_videos.json']

    def test_reviewed_by_setting(self):
        version = SubtitleVersion.objects.all()[0]
        user = User.objects.all()[0]

        self.assertEqual(version.get_reviewed_by(), None,
            "Version's reviewed_by metadata is not originally None.")

        version_pk = version.pk
        version.set_reviewed_by(user)

        version = SubtitleVersion.objects.get(pk=version_pk)

        self.assertEqual(version.get_reviewed_by().pk, user.pk,
            "Version's reviewed_by metadata is not the correct User.")

    def test_approved_by_setting(self):
        version = SubtitleVersion.objects.all()[0]
        user = User.objects.all()[0]

        self.assertEqual(version.get_approved_by(), None,
            "Version's approved_by metadata is not originally None.")

        version_pk = version.pk
        version.set_approved_by(user)

        version = SubtitleVersion.objects.get(pk=version_pk)

        self.assertEqual(version.get_approved_by().pk, user.pk,
            "Version's approved_by metadata is not the correct User.")


def create_langs_and_versions(video, langs, user=None):
    versions = []
    for lang in langs:
        l, c = SubtitleLanguage.objects.get_or_create(language=lang, video=video, is_forked=True)
        versions.append(create_version(l))
    return versions

def refresh_obj(m):
    return m.__class__._default_manager.get(pk=m.pk)


class FollowTest(WebUseTest):

    fixtures = ['test.json']

    def setUp(self):
        self._make_objects()
        self.vt = YoutubeVideoType
        self.data = [{
            'url': 'http://www.youtube.com/watch#!v=UOtJUmiUZ08&feature=featured&videos=Qf8YDn9mbGs',
            'video_id': 'UOtJUmiUZ08'
        },{
            'url': 'http://www.youtube.com/v/6Z5msRdai-Q',
            'video_id': '6Z5msRdai-Q'
        },{
            'url': 'http://www.youtube.com/watch?v=woobL2yAxD4',
            'video_id': 'woobL2yAxD4'
        },{
            'url': 'http://www.youtube.com/watch?v=woobL2yAxD4&amp;playnext=1&amp;videos=9ikUhlPnCT0&amp;feature=featured',
            'video_id': 'woobL2yAxD4'
        }]
        self.shorter_url = "http://youtu.be/HaAVZ2yXDBo"
        cache.clear()

    def test_create_video(self):
        """
        When a video is created, the submitter should follow that video.
        """
        self._login()
        video, created = Video.get_or_create_for_url(
                video_url="http://example.com/123.mp4", user=self.user)

        self.assertTrue(video.followers.filter(pk=self.user.pk).exists())

    def test_create_edit_subs(self):
        """
        Trascriber, translator should follow language, not video.
        """
        self._login()

        youtube_url = 'http://www.youtube.com/watch?v=XDhJ8lVGbl8'
        video, created = Video.get_or_create_for_url(youtube_url)
        self.assertEquals(2, SubtitleLanguage.objects.count())
        SubtitleVersion.objects.all().delete()

        # Create a transcription

        language = SubtitleLanguage.objects.get(language='en')
        language.is_original = True
        language.save()
        self.assertFalse(language.followers.filter(pk=self.user.pk).exists())

        version = SubtitleVersion(language=language, user=self.user,
                datetime_started=datetime.now(), version_no=0,
                is_forked=False)
        version.save()

        # Trascription author follows language, not video
        self.assertTrue(version.is_transcription)
        self.assertFalse(video.followers.filter(pk=self.user.pk).exists())
        self.assertTrue(language.followers.filter(pk=self.user.pk).exists())

        # Create a translation
        czech = SubtitleLanguage.objects.create(language='cz', is_original=False,
                video=video)
        self.assertEquals(3, SubtitleLanguage.objects.count())

        version = SubtitleVersion(language=czech, user=self.user,
                datetime_started=datetime.now(), version_no=0,
                is_forked=False)
        version.save()

        # Translation creator follows language, not video
        self.assertTrue(version.is_translation)
        self.assertFalse(video.followers.filter(pk=self.user.pk).exists())
        self.assertTrue(czech.followers.filter(pk=self.user.pk).exists())

        # Now editing --------------------------------------------------------

        self.assertNotEquals(language.pk, czech.pk)
        video.followers.clear()
        language.followers.clear()
        czech.followers.clear()

        version = SubtitleVersion(language=language, user=self.user,
                datetime_started=datetime.now(), version_no=1,
                is_forked=False)
        version.save()

        self.assertFalse(video.followers.filter(pk=self.user.pk).exists())
        self.assertTrue(language.followers.filter(pk=self.user.pk).exists())

        version = SubtitleVersion(language=czech, user=self.user,
                datetime_started=datetime.now(), version_no=1,
                is_forked=False)
        version.save()

        self.assertFalse(video.followers.filter(pk=self.user.pk).exists())
        self.assertTrue(czech.followers.filter(pk=self.user.pk).exists())

    def test_review_subs(self):
        """
        When you review a set of subtitles, you should follow that language.
        """
        self._login()
        youtube_url = 'http://www.youtube.com/watch?v=XDhJ8lVGbl8'

        vt = self.vt(youtube_url)
        video, created = Video.get_or_create_for_url(youtube_url)

        lang = vt.get_subtitled_languages()[0]

        language = SubtitleLanguage.objects.get(language='en')
        version = SubtitleVersion(language=language,
                datetime_started=datetime.now(), version_no=10)
        version.save()

        team, created = Team.objects.get_or_create(name='name', slug='slug')
        TeamMember.objects.create(team=team, user=self.user,
                role=TeamMember.ROLE_OWNER)
        team_video, _= TeamVideo.objects.get_or_create(team=team, video=video,
                added_by=self.user)
        Workflow.objects.create(team=team, team_video=team_video,
                review_allowed=30
                )

        sl = video.subtitle_language(lang['lang_code'])
        self.assertEquals(1, sl.followers.count())
        latest = video.latest_version(language_code='en')
        latest.set_reviewed_by(self.user)
        latest.save()

        self.assertEquals(2, sl.followers.count())

    def test_approve_not(self):
        """
        When you approve subtitles, you should *not* follow anything.
        """
        self._login()
        youtube_url = 'http://www.youtube.com/watch?v=XDhJ8lVGbl8'

        vt = self.vt(youtube_url)
        video, created = Video.get_or_create_for_url(youtube_url)

        lang = vt.get_subtitled_languages()[0]

        language = SubtitleLanguage.objects.get(language='en')
        version = SubtitleVersion(language=language,
                datetime_started=datetime.now(), version_no=10)
        version.save()

        team, created = Team.objects.get_or_create(name='name', slug='slug')
        TeamMember.objects.create(team=team, user=self.user,
                role=TeamMember.ROLE_OWNER)
        team_video, _= TeamVideo.objects.get_or_create(team=team, video=video,
                added_by=self.user)
        Workflow.objects.create(team=team, team_video=team_video,
                review_allowed=30
                )

        sl = video.subtitle_language(lang['lang_code'])
        self.assertEquals(1, sl.followers.count())
        latest = video.latest_version(language_code='en')
        latest.set_approved_by(self.user)
        latest.save()

        self.assertEquals(1, sl.followers.count())

class MarkupHtmlTest(TestCase):

    def test_markup_to_html(self):
        t = "there **bold text** there"
        self.assertEqual(
            "there <b>bold text</b> there",
            markup_to_html(t)
        )

    def test_html_to_markup(self):
        t = "there <b>bold text</b> there"
        self.assertEqual(
            "there **bold text** there",
            html_to_markup(t)
        )
class BaseDownloadTest(object):

    def _download_subs(self, language, format):
        url = reverse("widget:download_" + format)
        res = self.client.get(url, {
            'video_id': language.video.video_id,
            'lang_pk': language.pk
        })
        return res.content

class TestSRT(WebUseTest, BaseDownloadTest):
    fixtures = ['test.json']

    def setUp(self):
        self.auth = dict(username='admin', password='admin')
        self.video = Video.get_or_create_for_url("http://www.example.com/video.mp4")[0]
        self.language = SubtitleLanguage.objects.get_or_create(
            video=self.video, is_forked=True, language='en')[0]

    def test_download_markup(self):
        subs_data = ['one line',
                     'line **with** bold',
                     'line *with* italycs',
                     'line <script> with dangerous tag',
                     'line with double gt >>',
        ]
        add_subs(self.language,subs_data)
        content = self._download_subs(self.language, 'srt')
        self.assertIn('<b>with</b>' , content)
        self.assertIn('<i>with</i>' , content)
        self.assertIn('double gt >>' , content)
        # don't let evildoes into our precisou home
        self.assertNotIn('<script>' , content)
        subs = [x for x in SrtSubtitleParser(content)]
        # make sure we can parse them back
        self.assertEqual(len(subs_data), len(subs))

    def test_upload_markup(self):
        data = {
            'language': self.language.language,
            'video': self.video.pk,
            'video_language': 'en',
            'draft': open(os.path.join(os.path.dirname(__file__), 'fixtures/with-markdown.srt'))
        }
        self._login()
        response = self.client.post(reverse('videos:upload_subtitles'), data)
        self.assertEqual(response.status_code, 200)
        subs = self.video.subtitle_language().version().subtitles()
        self.assertIn("**bold text in it**", subs[0].text)
        self.assertIn(" *multiline\nitalics*", subs[1].text)
        self.assertNotIn("script", subs[2].text)


def add_subs(language, subs_texts):
    version = language.version()
    version_no = 0
    if version:
        version_no = version.version_no + 1
    new_version = SubtitleVersion.objects.create(
        language=language,
        version_no=version_no,
        datetime_started=datetime.now(),
        is_forked = language.is_forked
    )
    for i, text in enumerate(subs_texts):
        s= Subtitle.objects.create(
            version = new_version,
            subtitle_id=i,
            subtitle_order=i,
            subtitle_text=text,
            start_time = i,
            end_time = i + 1 - 0.1
        )


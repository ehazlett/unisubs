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
from datetime import datetime

import chardet
from django import forms
from django.conf import settings
from django.core.mail import EmailMessage, send_mail
from django.db.models import ObjectDoesNotExist
from django.template.loader import render_to_string
from django.utils.encoding import force_unicode, DjangoUnicodeDecodeError
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from math_captcha.forms import MathCaptchaForm

from teams.models import Task, Workflow
from teams.moderation_const import UNMODERATED, WAITING_MODERATION, APPROVED
from teams.permissions import (
        can_create_and_edit_subtitles, can_assign_task,
        can_create_and_edit_translations, can_publish_edits_immediately
)

from utils.subtitles import ParserList, SubtitleParserError

from utils.forms import AjaxForm, EmailListField, UsernameListField, StripRegexField, FeedURLField, ReCaptchaField
from utils.http import url_exists
from utils.subtitles import save_subtitle, is_version_same
from utils.translation import get_language_choices
from videos.feed_parser import FeedParser
from videos.models import (
    Video, UserTestResult, SubtitleLanguage, 
    VideoUrl, record_workflow_origin, SubtitleVersion
)
from videos.tasks import video_changed_tasks, import_videos_from_feeds
from videos.types import video_type_registrar, VideoTypeError
from videos.types.youtube import yt_service

ALL_LANGUAGES = [(val, _(name)) for val, name in settings.ALL_LANGUAGES]
KB_SIZELIMIT = 512

import logging
logger = logging.getLogger("videos-forms")

class TranscriptionFileForm(forms.Form, AjaxForm):
    txtfile = forms.FileField()

    def clean_txtfile(self):
        f = self.cleaned_data['txtfile']

        if f.name.split('.')[-1] != 'txt':
            raise forms.ValidationError(_('File should have txt format'))

        if f.size > KB_SIZELIMIT * 1024:
            raise forms.ValidationError(_(
                    u'File size should be less {0} kb'.format(KB_SIZELIMIT)))

        text = f.read()
        encoding = chardet.detect(text)['encoding']
        if not encoding:
            raise forms.ValidationError(_(u'Can not detect file encoding'))
        try:
            self.file_text = force_unicode(text, encoding)
        except DjangoUnicodeDecodeError:
            raise forms.ValidationError(_(u'Can\'t encode file. It should have utf8 encoding.'))
        f.seek(0)

        return f

    def clean_subtitles(self):
        subtitles = self.cleaned_data['subtitles']
        if subtitles.size > KB_SIZELIMIT * 1024:
            raise forms.ValidationError(_(
                    u'File size should be less {0} kb'.format(KB_SIZELIMIT)))
        parts = subtitles.name.split('.')
        if len(parts) < 1 or not parts[-1].lower() in ['srt', 'ass', 'ssa', 'xml', 'sbv']:
            raise forms.ValidationError(_(u'Incorrect format. Upload .srt, .ssa, .sbv or .xml (TTML  format)'))
        try:
            text = subtitles.read()
            encoding = chardet.detect(text)['encoding']
            if not encoding:
                raise forms.ValidationError(_(u'Can not detect file encoding'))
            if not self._get_parser(subtitles.name)(force_unicode(text, encoding)):
                raise forms.ValidationError(_(u'Incorrect subtitles format'))
        except SubtitleParserError, e:
            raise forms.ValidationError(e)
        subtitles.seek(0)
        return subtitles

class CreateVideoUrlForm(forms.ModelForm):

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(CreateVideoUrlForm, self).__init__(*args, **kwargs)
        self.fields['video'].widget = forms.HiddenInput()

    class Meta:
        model = VideoUrl
        fields = ('url', 'video')

    def clean_url(self):
        url = self.cleaned_data['url']

        try:
            video_type = video_type_registrar.video_type_for_url(url)

            video_url = video_type.video_url(video_type)

            if not url_exists(video_url) :
                raise forms.ValidationError(_(u'This URL appears to be a broken link.'))

        except VideoTypeError, e:
            raise forms.ValidationError(e)

        if not video_type:
            raise forms.ValidationError(mark_safe(_(u"""Amara does not support that website or video format.
If you'd like to us to add support for a new site or format, or if you
think there's been some mistake, <a
href="mailto:%s">contact us</a>!""") % settings.FEEDBACK_EMAIL))
        self._video_type = video_type
        return video_type.convert_to_video_url()

    def clean(self):
        data = super(CreateVideoUrlForm, self).clean()
        video = data.get('video')
        if video and not video.allow_video_urls_edit and not self.user.has_perm('videos.add_videourl'):
            raise forms.ValidationError(_('You have not permission add video URL for this video'))

        return self.cleaned_data

    def save(self, commit=True):
        obj = super(CreateVideoUrlForm, self).save(False)
        obj.type = self._video_type.abbreviation
        obj.added_by = self.user
        obj.videoid = self._video_type.video_id or ''
        commit and obj.save()
        return obj

    def get_errors(self):
        output = {}
        for key, value in self.errors.items():
            output[key] = '/n'.join([force_unicode(i) for i in value])
        return output

class SubtitlesUploadBaseForm(forms.Form):
    language = forms.ChoiceField(choices=ALL_LANGUAGES, initial='en')
    video_language = forms.ChoiceField(required=False, choices=ALL_LANGUAGES, initial='en')
    video = forms.ModelChoiceField(Video.objects)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(SubtitlesUploadBaseForm, self).__init__(*args, **kwargs)
        self.fields['language'].choices = get_language_choices()
        self.fields['video_language'].choices = get_language_choices()

    def clean_video(self):
        video = self.cleaned_data['video']
        if video.is_writelocked:
            raise forms.ValidationError(_(u'Somebody is subtitling this video right now. Try later.'))

        return video

    def clean(self):
        video = self.cleaned_data['video']
        language = self.cleaned_data['language']
        video_language = self.cleaned_data['video_language']

        subtitle_language = video.subtitle_language(language)

        # first verify if this language for this video already exists.
        # if exists, verify if it's not writelocked
        if subtitle_language:
            if subtitle_language.is_writelocked and subtitle_language.writelock_owner != self.user:
                raise forms.ValidationError(_(u"Sorry, we can't upload your subtitles because work on this language is already in progress."))

            # we can't let the user upload a subtitle to a language that already
            # have dependents. that will fork the dependents and make everything break.
            # see sifter #1075
            if video.subtitlelanguage_set.filter(standard_language=subtitle_language).exists():
                for language in video.subtitlelanguage_set.filter(standard_language=subtitle_language):
                    # if it exists, let's verify if the version is not empty
                    if language.latest_subtitles(public_only=False):
                        raise forms.ValidationError(_(u"Sorry, we cannot upload subtitles for this language because this would ruin translations made from it"))

        team_video = video.get_team_video()

        if not team_video:
            return self.cleaned_data

        blocking_tasks = team_video.task_set.incomplete_subtitle_or_translate().filter(language__in=[language, ''])

        if blocking_tasks.exists():
            task = blocking_tasks.get()

            # only block if the user can't assign the task
            # aka he can't do himself or he can't actually
            # assign it to himself.
            # also block if the task is assigned to another user
            if (task.assignee and task.assignee != self.user) or (not task.assignee and not can_assign_task(task, self.user)):
                raise forms.ValidationError(_(u"Sorry, we can't upload your subtitles because work on this language is already in progress."))

        # Now we know that there are no transcribe/translate tasks that
        # should block this upload.
        #
        # However, if there are any review/approve tasks open they should
        # block it, even if the user is the assignee.
        #
        # TODO: Remove this restriction?
        blocking_tasks = team_video.task_set.incomplete_review_or_approve().filter(language=language)

        if blocking_tasks.exists():
            raise forms.ValidationError(_(u"Sorry, we can't upload your subtitles because a draft for this language is already in moderation."))

        # There are no tasks for this video that should block the upload.
        # The last thing to check is that the team's transcription policy doesn't block this.
        if video_language and (not subtitle_language or subtitle_language.is_original):
            if not can_create_and_edit_subtitles(self.user, team_video, language):
                raise forms.ValidationError(_(u"Sorry, we can't upload your subtitles because this language is moderated and you don't have sufficient permission."))
        else:
            if not can_create_and_edit_translations(self.user, team_video, language):
                raise forms.ValidationError(_(u"Sorry, we can't upload your subtitles because this language is moderated and you don't have sufficient permission."))

        return self.cleaned_data

    def _save_original_language(self, video, video_language):
        original_language = video.subtitle_language()

        if original_language:
            if original_language.language:
                try:
                    language_exists = video.subtitlelanguage_set.exclude(pk=original_language.pk) \
                        .get(language=video_language)
                    original_language.is_original = False
                    original_language.save()
                    language_exists.is_original = True
                    language_exists.save()
                except ObjectDoesNotExist:
                    original_language.language = video_language
                    original_language.save()
            else:
                try:
                    language_exists = video.subtitlelanguage_set.exclude(pk=original_language.pk) \
                        .get(language=video_language)

                    latest_version = original_language.latest_version()

                    if latest_version:
                        last_no = latest_version.version_no
                    else:
                        last_no = 0

                    for version in language_exists.subtitleversion_set.all():
                        version.language = original_language
                        last_no += 1
                        version.version_no = last_no
                        version.save()

                    language_exists.delete()
                except ObjectDoesNotExist:
                    pass

                original_language.language = video_language
                original_language.save()
        else:
            #original_language always exists, but...
            try:
                language_exists = video.subtitlelanguage_set.get(language=video_language)
                language_exists.is_original = True
                language_exists.save()
            except ObjectDoesNotExist:
                original_language = SubtitleLanguage()
                original_language.language = video_language
                original_language.is_original = True
                original_language.video = video
                original_language.save()

    def _best_existing(self, languages):
        for l in languages:
            # choosing first forked SL that has no dependent languages.
            if not l.is_dependent() and l.subtitlelanguage_set.count() == 0:
                return l
        return None

    def _find_appropriate_language(self, video, language_code):
        created = False
        language = video.subtitle_language(language_code)
        if not language:
            created = True
            language = SubtitleLanguage(
                video=video, is_original=False, is_forked=True)
        language.language = language_code
        language.save()
        return language, created

    def save_subtitles(self, parser, video=None, language=None, update_video=True, is_complete=True):
        video = video or self.cleaned_data['video']

        if not video.has_original_language():
            self._save_original_language(
                video, self.cleaned_data['video_language'])

        if language:
            self._sl_created = False
            language = language
        else:
            language, self._sl_created = self._find_appropriate_language(video, self.cleaned_data['language'])

        language = save_subtitle(video, language, parser, self.user, update_video)

        # If there are any outstanding tasks for this language, associate the
        # new version with them.
        # TODO: Refactor all of this out into some kind of generic "add subtitles" pipeline.
        team_video = video.get_team_video()

        if not team_video:
            return language

        workflow = Workflow.get_for_team_video(team_video)

        if not workflow.approve_enabled and not workflow.review_enabled:
            return language

        new_version = language.latest_version(public_only=False)
        record_workflow_origin(new_version, team_video)

        # Determine if we need to moderate these subtitles and create a
        # review/approve task for them.
        workflow = team_video.get_workflow()
        # user can bypass moderation if:
        # 1) he is a moderator and
        # 2) it's a post-publish edit
        # 3) subtitle is complete
        can_bypass_moderation = (
            is_complete
            and not self._sl_created
            and can_publish_edits_immediately(team_video, self.user,
                                              language.language))

        if can_bypass_moderation:
            new_version.moderate = APPROVED
        elif workflow.review_allowed or workflow.approve_allowed:
            new_version.moderation_status = WAITING_MODERATION
        else:
            new_version.moderation_status = UNMODERATED

        new_version.save()

        outstanding_tasks = team_video.task_set.incomplete().filter(language__in=[language.language, ''])

        if outstanding_tasks.exists():
            if new_version.moderation_status != WAITING_MODERATION:
                outstanding_tasks.update(subtitle_version=new_version,
                                         language=language.language)
        elif not can_bypass_moderation:
            # we just need to create review/approve/subtitle if the language
            # is a new one or, if it's a post-publish edit, if the user can't
            # approve subtitles by himself.
            task_type = None

            if new_version.is_synced() and is_complete:
                if workflow.review_allowed:
                    task_type = Task.TYPE_IDS['Review']
                elif workflow.approve_allowed:
                    task_type = Task.TYPE_IDS['Approve']
            else:
                task_type = Task.TYPE_IDS['Subtitle']

            if task_type:
                task = Task(team=team_video.team, team_video=team_video,
                            language=language.language, type=task_type,
                            subtitle_version=new_version)

                if not self._sl_created:
                    task.assignee = task._find_previous_assignee(Task.TYPE_NAMES[task_type])
                else:
                    if task_type == Task.TYPE_IDS['Subtitle']:
                        task.assignee = self.user

                task.save()

        return language

    def verify_tasks(self, is_complete):
        video = self.cleaned_data['video']
        language = self.cleaned_data['language']

        team_video = video.get_team_video()

        if team_video:
            tasks = team_video.task_set.incomplete_subtitle_or_translate().filter(language__in=[language, ''])

            if tasks.exists():
                task = tasks.get()

                if not task.assignee and self.user and can_assign_task(task, self.user):
                    task.assignee = self.user

                    # we save only if is_complete because
                    # .complete() actually saves the task too
                    if not is_complete:
                        task.save()

                if is_complete:
                    task.complete()

    def get_errors(self):
        output = {}
        for key, value in self.errors.items():
            output[key] = '/n'.join([force_unicode(i) for i in value])
        return output

class SubtitlesUploadForm(forms.Form):
    draft = forms.FileField(required=True)
    is_complete = forms.BooleanField(initial=False, required=False)
    video = forms.ModelChoiceField(Video.objects)

    language = forms.ChoiceField(choices=ALL_LANGUAGES, initial='en')
    video_language = forms.ChoiceField(required=False, choices=ALL_LANGUAGES, initial='en')
    translated_from = forms.ChoiceField(required=False, choices=ALL_LANGUAGES, initial='')

    def __init__(self, user, video, *args, **kwargs):
        self.video = video
        self.user = user
        self._sl_created = False

        super(SubtitlesUploadForm, self).__init__(*args, **kwargs)

        self.fields['language'].choices = get_language_choices()
        self.fields['video_language'].choices = get_language_choices()
        choices = [('', 'Directly from video')] + ([(sl.language, sl.language_display()) for sl in video.subtitlelanguage_set.all() if sl.is_complete_and_synced()])
        self.fields['translated_from'].choices = choices

    def clean_video(self):
        video = self.cleaned_data['video']
        if video.is_writelocked:
            raise forms.ValidationError(_(u'Somebody is subtitling this video right now. Try later.'))

        return video

    def clean_translated_from(self):
        language = self.cleaned_data.get('translated_from')

        allowed_languages = [sl.language for sl in self.video.subtitlelanguage_set.all() if sl.is_complete_and_synced()]

        if language and language not in allowed_languages:
            raise forms.ValidationError(_(u'Invalid language to translate from.'))

        return language

    def clean_draft(self):
        subtitles = self.cleaned_data['draft']

        if subtitles.size > 512 * 1024:
            raise forms.ValidationError(_(
                    u'File size should be less {0} kb'.format(512)))

        parts = subtitles.name.split('.')

        if len(parts) < 1 or not parts[-1].lower() in ParserList:
            raise forms.ValidationError(_(u'Incorrect format. Upload %s' % ParserList.extensions()))

        try:
            text = subtitles.read()
            encoding = chardet.detect(text)['encoding']

            if not encoding:
                raise forms.ValidationError(_(u'Can not detect file encoding'))

            self.extension = subtitles.name.split('.')[-1].lower()

            if self.extension not in ParserList:
                raise forms.ValidationError(_(u'Incorrect subtitles format'))

            self._parser = ParserList[self.extension](force_unicode(text, encoding))

        except SubtitleParserError, e:
            raise forms.ValidationError(e)

        subtitles.seek(0)

        return subtitles
    
    def clean(self):
        translated_from = self.cleaned_data.get('translated_from')
        language = self.cleaned_data['language']

        video = self.cleaned_data['video']
        video_language = self.cleaned_data['video_language']

        subtitle_language = video.subtitle_language(language)

        # first verify if this language for this video already exists.
        # if exists, verify if it's not writelocked
        if subtitle_language:
            if subtitle_language.is_writelocked and subtitle_language.writelock_owner != self.user:
                raise forms.ValidationError(_(u"Sorry, we can't upload your subtitles because work on this language is already in progress."))

            # if the user specified a translate from and the language is original
            # with a version, block it
            if translated_from and not subtitle_language.standard_language and subtitle_language.version(public_only=False):
                raise forms.ValidationError(_("The language already exists and already has a version"))

            # if the language already have a standard language that it's different
            # from the one specified by the user, block it.
            if subtitle_language.standard_language and subtitle_language.standard_language.language != translated_from:
                raise forms.ValidationError(_("The language already exists and you can't change its translation from %s" % subtitle_language.standard_language))

            # we can't let the user upload a subtitle to a language that already
            # have dependents. that will fork the dependents and make everything break.
            # see sifter #1075
            if video.subtitlelanguage_set.filter(standard_language=subtitle_language).exists():
                for language in video.subtitlelanguage_set.filter(standard_language=subtitle_language):
                    # if it exists, let's verify if the version is not empty
                    if language.latest_subtitles(public_only=False):
                        raise forms.ValidationError(_(u"Sorry, we cannot upload subtitles for this language because this would ruin translations made from it"))

        team_video = video.get_team_video()

        if not team_video:
            return self.cleaned_data

        blocking_tasks = team_video.task_set.incomplete_subtitle_or_translate().filter(language__in=[language, ''])

        if blocking_tasks.exists():
            task = blocking_tasks.get()

            # only block if the user can't assign the task
            # aka he can't do himself or he can't actually
            # assign it to himself.
            # also block if the task is assigned to another user
            if (task.assignee and task.assignee != self.user) or (not task.assignee and not can_assign_task(task, self.user)):
                raise forms.ValidationError(_(u"Sorry, we can't upload your subtitles because work on this language is already in progress."))

        # Now we know that there are no transcribe/translate tasks that
        # should block this upload.
        #
        # However, if there are any review/approve tasks open they should
        # block it, even if the user is the assignee.
        #
        # TODO: Remove this restriction?
        blocking_tasks = team_video.task_set.incomplete_review_or_approve().filter(language=language)

        if blocking_tasks.exists():
            raise forms.ValidationError(_(u"Sorry, we can't upload your subtitles because a draft for this language is already in moderation."))

        # There are no tasks for this video that should block the upload.
        # The last thing to check is that the team's transcription policy doesn't block this.
        if video_language and (not subtitle_language or subtitle_language.is_original):
            if not can_create_and_edit_subtitles(self.user, team_video, language):
                raise forms.ValidationError(_(u"Sorry, we can't upload your subtitles because this language is moderated and you don't have sufficient permission."))
        else:
            if not can_create_and_edit_translations(self.user, team_video, language):
                raise forms.ValidationError(_(u"Sorry, we can't upload your subtitles because this language is moderated and you don't have sufficient permission."))

        translated_from = video.subtitle_language(translated_from)

        # if the language has dependents, check if the transcript is smaller so we don't lose subtitles
        if subtitle_language and (subtitle_language.is_original or subtitle_language.is_forked):
            version = subtitle_language.version()
            if version and SubtitleLanguage.objects.filter(standard_language=subtitle_language).exists():
                if len(self._parser) < version.subtitle_set.count():
                    raise forms.ValidationError(_(u"Sorry, we couldn't upload your file because it has fewer lines ({0}) than the previous version ({1}).".format(len(self._parser), version.subtitle_set.count())))

        # if we are translating from another version, always check if we don't have
        # more subtitles than we need
        elif translated_from and translated_from.version():
            original_subs_count = translated_from.version().subtitle_set.count()
            if len(self._parser) > original_subs_count:
                raise forms.ValidationError(_(u"Sorry, we couldn't upload your file because the number of lines in your translation ({0}) doesn't match the original ({1}).".format(len(self._parser), original_subs_count)))

        return self.cleaned_data

    def save(self):
        is_complete = self.cleaned_data['is_complete']
        translated_from_language = self.cleaned_data['translated_from']
        video = self.cleaned_data['video']

        # no matter what, txt cannot be complete because they don't have time data.
        if self.extension == 'txt':
            is_complete = False

        translated_from = video.subtitle_language(translated_from_language)

        if is_complete and translated_from and translated_from.version():
            original_subs_count = translated_from.version().subtitle_set.count()
            is_complete = original_subs_count <= len(self._parser)

        new_version = self._save_subtitles(self._parser, is_complete=is_complete, translated_from=translated_from)
        subtitle_language = new_version.language

        subtitle_language.is_complete = is_complete
        
        if new_version and len(new_version.subtitles()) > 0:
            # this will eventually get updated on the async test
            # but if it takes too long on html file uplods
            # then users will not see the language added which is very
            # confusing from a UI point of view
            subtitle_language.had_version = subtitle_language.has_version = True

        subtitle_language.save()

        self._verify_tasks(is_complete)

        if new_version and subtitle_language.latest_version():
            video_changed_tasks.delay(subtitle_language.video_id, subtitle_language.latest_version().id)
        else:
            video_changed_tasks.delay(subtitle_language.video_id)

        return subtitle_language

    def get_errors(self):
        output = {}
        for key, value in self.errors.items():
            output[key] = '/n'.join([force_unicode(i) for i in value])
        return output

    def _save_new_language(self, video, lang_code, translated_from=None):
        language = SubtitleLanguage()
        language.language = lang_code

        if not translated_from:
            language.is_original = True
        else:
            language.is_original = False
            language.is_forked = False

            # iuck
            if translated_from.is_original:
                language.standard_language = translated_from
            else:
                language.standard_language = translated_from.standard_language

        language.video = video
        language.save()

        return language

    def _save_subtitles(self, parser, is_complete, translated_from=None):
        video = self.cleaned_data['video']
        draft_language = self.cleaned_data['language']
        video_language = self.cleaned_data['video_language']

        if not video.has_original_language():
            language = self._save_new_language(video, video_language)
            if video_language == draft_language:
                self._sl_created = True

        if not self._sl_created:
            if not video.subtitle_language(draft_language):
                language = self._save_new_language(video, draft_language, translated_from)
                self._sl_created = True
            else:
                language = video.subtitle_language(draft_language)
                self._sl_created = False

        if is_version_same(language.version(public_only=False), self._parser):
            return language.version(public_only=False)

        new_version = SubtitleVersion.objects.new_version(parser, language, self.user,
                                            note="Uploaded", translated_from=translated_from)

        team_video = video.get_team_video()

        if not team_video:
            return new_version

        team_video = video.get_team_video()

        if not team_video:
            return new_version

        workflow = Workflow.get_for_team_video(team_video)

        if not workflow.allows_tasks:
            return new_version

        record_workflow_origin(new_version, team_video)

        # Determine if we need to moderate these subtitles and create a
        # review/approve task for them.
        workflow = team_video.get_workflow()
        # user can bypass moderation if:
        # 1) he is a moderator and
        # 2) it's a post-publish edit
        # 3) subtitle is complete
        can_bypass_moderation = (
            is_complete
            and not self._sl_created
            and can_publish_edits_immediately(team_video, self.user,
                                              language.language))

        if can_bypass_moderation:
            new_version.moderate = APPROVED
        elif workflow.review_allowed or workflow.approve_allowed:
            new_version.moderation_status = WAITING_MODERATION
        else:
            new_version.moderation_status = UNMODERATED

        new_version.save()

        outstanding_tasks = team_video.task_set.incomplete().filter(language__in=[language.language, ''])

        if outstanding_tasks.exists():
            if new_version.moderation_status != WAITING_MODERATION:
                outstanding_tasks.update(subtitle_version=new_version,
                                         language=language.language)
        elif not can_bypass_moderation:
            # we just need to create review/approve/subtitle if the language
            # is a new one or, if it's a post-publish edit, if the user can't
            # approve subtitles by himself.
            task_type = None

            if new_version.is_synced() and is_complete:
                if workflow.review_allowed:
                    task_type = Task.TYPE_IDS['Review']
                elif workflow.approve_allowed:
                    task_type = Task.TYPE_IDS['Approve']
            else:
                if language.is_original:
                    task_type = Task.TYPE_IDS['Subtitle']
                else:
                    task_type = Task.TYPE_IDS['Translate']

            if task_type:
                task = Task(team=team_video.team, team_video=team_video,
                            language=language.language, type=task_type)

                if task.type not in (Task.TYPE_IDS['Subtitle'], Task.TYPE_IDS['Translate']):
                    task.subtitle_version = new_version

                if not self._sl_created:
                    task.assignee = task._find_previous_assignee(Task.TYPE_NAMES[task_type])
                else:
                    if task_type in (Task.TYPE_IDS['Subtitle'], Task.TYPE_IDS['Translate']):
                        task.assignee = self.user

                task.save()

        return new_version

    def _verify_tasks(self, is_complete):
        video = self.cleaned_data['video']
        language = self.cleaned_data['language']

        team_video = video.get_team_video()

        if team_video:
            tasks = team_video.task_set.incomplete_subtitle_or_translate().filter(language__in=[language, ''])

            if tasks.exists():
                task = tasks.get()

                if not task.assignee and self.user and can_assign_task(task, self.user):
                    task.assignee = self.user

                    # we save only if is_complete because
                    # .complete() actually saves the task too
                    if not is_complete:
                        task.save()

                if is_complete:
                    task.complete()

class UserTestResultForm(forms.ModelForm):

    class Meta:
        model = UserTestResult
        exclude = ('browser',)

    def save(self, request):
        obj = super(UserTestResultForm, self).save(False)
        obj.browser = request.META.get('HTTP_USER_AGENT', 'empty HTTP_USER_AGENT')
        obj.save()
        return obj

class VideoForm(forms.Form):
    # url validation is within the clean method
    video_url = forms.URLField(verify_exists=False)

    def __init__(self, user=None, *args, **kwargs):
        if user and not user.is_authenticated():
            user = None
        self.user = user
        super(VideoForm, self).__init__(*args, **kwargs)
        self.fields['video_url'].widget.attrs['class'] = 'main_video_form_field'

    def clean_video_url(self):
        video_url = self.cleaned_data['video_url']

        if video_url:
            try:
                video_type = video_type_registrar.video_type_for_url(video_url)
            except VideoTypeError, e:
                raise forms.ValidationError(e)
            if not video_type:
                for d in video_type_registrar.domains:
                    if d in video_url:
                        raise forms.ValidationError(mark_safe(_(u"""Please try again with a link to a video page.
                        <a href="mailto:%s">Contact us</a> if there's a problem.""") % settings.FEEDBACK_EMAIL))

                raise forms.ValidationError(mark_safe(_(u"""You must link to a video on a compatible site (like YouTube) or directly to a
                    video file that works with HTML5 browsers. For example: http://mysite.com/myvideo.ogg or http://mysite.com/myipadvideo.m4v
                    <a href="mailto:%s">Contact us</a> if there's a problem.""") % settings.FEEDBACK_EMAIL))

            else:
                self._video_type = video_type
                # we need to use the cannonical url as the user provided might need
                # redirection (i.e. youtu.be/fdaf/), and django's validator will
                # choke on redirection (urllib2 for python2.6), see https://unisubs.sifterapp.com/projects/12298/issues/427646/comments
                video_url = video_type.video_url(video_type)

                if not url_exists(video_url) :
                    raise forms.ValidationError(_(u'This URL appears to be a broken link.'))

        return video_url

    def save(self):
        video_url = self.cleaned_data['video_url']
        obj, created = Video.get_or_create_for_url(video_url, self._video_type, self.user)
        self.created = created
        return obj

youtube_user_url_re = re.compile(r'^(http://)?(www.)?youtube.com/user/(?P<username>[a-zA-Z0-9]+)/?.*$')

class AddFromFeedForm(forms.Form, AjaxForm):
    VIDEOS_LIMIT = 10

    youtube_feed_url_pattern =  'https://gdata.youtube.com/feeds/api/users/%s/uploads'
    usernames = UsernameListField(required=False, label=_(u'Youtube usernames'), help_text=_(u'Enter usernames separated by comma.'))
    youtube_user_url = StripRegexField(youtube_user_url_re, required=False, label=_(u'Youtube page link.'),
                                       help_text=_(u'For example: http://www.youtube.com/user/username'))
    feed_url = FeedURLField(required=False, help_text=_(u'Supported: Youtube, Vimeo, or Dailymotion. Only supported sites added.'))
    save_feed = forms.BooleanField(required=False, label=_(u'Save feed'), help_text=_(u'Choose this if you wish to add videos from this feed in the future. Only valid RSS feeds will be saved.'))

    def __init__(self, user, *args, **kwargs):
        if not user.is_authenticated():
            user = None
        self.user = user
        super(AddFromFeedForm, self).__init__(*args, **kwargs)

        self.yt_service = yt_service
        self.urls = []
        self.video_limit_routreach = False

    def clean_feed_url(self):
        url = self.cleaned_data.get('feed_url', '')

        if url:
            self.parse_feed_url(url)

        return url

    def clean_youtube_user_url(self):
        url = self.cleaned_data.get('youtube_user_url', '').strip()

        if url:
            username = youtube_user_url_re.match(url).groupdict()['username']
            url = self.youtube_feed_url_pattern % str(username)
            self.parse_feed_url(url)

        return url

    def clean_usernames(self):
        usernames = self.cleaned_data.get('usernames', [])

        for username in usernames:
            url = self.youtube_feed_url_pattern % str(username)
            self.parse_feed_url(url)

        return usernames

    def parse_feed_url(self, url):
        feed_parser = FeedParser(url)

        if not hasattr(feed_parser.feed, 'version') or not feed_parser.feed.version:
            raise forms.ValidationError(_(u'Sorry, we could not find a valid feed at the URL you provided. Please check the URL and try again.'))

        self.urls.append(url)

    def success_message(self):
        return _(u"The videos are being added in the background. "
                 u"If you are logged in, you will receive a message when it's done")

    def save(self):
        user_id = self.user.id if self.user else None
        import_videos_from_feeds.delay(self.urls, user_id)

class FeedbackForm(forms.Form):
    email = forms.EmailField(required=False)
    message = forms.CharField(widget=forms.Textarea())
    error = forms.CharField(required=False, widget=forms.HiddenInput)
    captcha = ReCaptchaField(label=_(u'captcha'))

    def __init__(self, *args, **kwargs):
        hide_captcha = kwargs.pop('hide_captcha', False)
        super(FeedbackForm, self).__init__(*args, **kwargs)
        if hide_captcha:
            del self.fields['captcha']

    def send(self, request):
        email = self.cleaned_data['email']
        message = self.cleaned_data['message']
        error = self.cleaned_data['error']
        user_agent_data = u'User agent: %s' % request.META.get('HTTP_USER_AGENT')
        timestamp = u'Time: %s' % datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        version = u'Version: %s' % settings.PROJECT_VERSION
        commit = u'Commit: %s' % settings.LAST_COMMIT_GUID
        url = u'URL: %s' % request.META.get('HTTP_REFERER', '')
        user = u'Logged in: %s' % (request.user.is_authenticated() and request.user or u'not logged in')
        message = u'%s\n\n%s\n%s\n%s\n%s\n%s\n%s' % (message, user_agent_data, timestamp, version, commit, url, user)
        if error in ['404', '500']:
            message += u'\nPage type: %s' % error
            feedback_emails = [settings.FEEDBACK_ERROR_EMAIL]
        else:
            feedback_emails = settings.FEEDBACK_EMAILS
        headers = {'Reply-To': email} if email else None
        bcc = getattr(settings, 'EMAIL_BCC_LIST', [])
        if email:
            subject = '%s (from %s)' % (settings.FEEDBACK_SUBJECT, email)
        else:
            subject = settings.FEEDBACK_SUBJECT
        EmailMessage(subject, message, email, \
                         feedback_emails, headers=headers, bcc=bcc).send()

        if email:
            headers = {'Reply-To': settings.FEEDBACK_RESPONSE_EMAIL}
            body = render_to_string(settings.FEEDBACK_RESPONSE_TEMPLATE, {})
            email = EmailMessage(settings.FEEDBACK_RESPONSE_SUBJECT, body, \
                         settings.FEEDBACK_RESPONSE_EMAIL, [email], headers=headers, bcc=bcc)
            email.content_subtype = 'html'
            email.send()

    def get_errors(self):
        from django.utils.encoding import force_unicode
        output = {}
        for key, value in self.errors.items():
            output[key] = '/n'.join([force_unicode(i) for i in value])
        return output

class EmailFriendForm(MathCaptchaForm):
    from_email = forms.EmailField(label='From')
    to_emails = EmailListField(label='To')
    subject = forms.CharField()
    message = forms.CharField(widget=forms.Textarea())

    def send(self):
        subject = self.cleaned_data['subject']
        message = self.cleaned_data['message']
        from_email = self.cleaned_data['from_email']
        to_emails = self.cleaned_data['to_emails']
        send_mail(subject, message, from_email, to_emails)

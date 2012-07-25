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

import chardet
from django import forms
from django.conf import settings
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from django.utils.encoding import force_unicode
from django.core.files.base import ContentFile
from auth.models import CustomUser as User
from teams.models import Team, TeamMember, TeamVideo, Task, Project, Workflow, Invite
from teams.permissions import (
    roles_user_can_invite, can_delete_task, can_add_video, can_perform_task,
    can_assign_task, can_unpublish_subs, can_remove_video
)
from teams.permissions_const import ROLE_NAMES
from utils.forms import ErrorableModelForm
from utils.forms.unisub_video_form import UniSubBoundVideoField
from utils.translation import get_language_choices
from utils.validators import MaxFileSizeValidator
from videos.forms import AddFromFeedForm
from videos.models import (
        VideoMetadata, VIDEO_META_TYPE_IDS, SubtitleVersion,
        Video, SubtitleLanguage, record_workflow_origin
)
from videos.search_indexes import VideoIndex

from utils.subtitles import ParserList, SubtitleParserError

from apps.teams.moderation_const import WAITING_MODERATION

ALL_LANGUAGES = [(val, _(name)) for val, name in settings.ALL_LANGUAGES]

class EditTeamVideoForm(forms.ModelForm):
    author = forms.CharField(max_length=255, required=False)
    creation_date = forms.DateField(required=False, input_formats=['%Y-%m-%d'],
                                    help_text="Format: YYYY-MM-DD")

    project = forms.ModelChoiceField(
        label=_(u'Project'),
        queryset = Project.objects.none(),
        required=True,
        empty_label=None,
        help_text=_(u"Let's keep things tidy, shall we?")
    )

    class Meta:
        model = TeamVideo
        fields = ('title', 'description', 'thumbnail', 'project',)

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")

        super(EditTeamVideoForm, self).__init__(*args, **kwargs)

        self.fields['project'].queryset = self.instance.team.project_set.all()

    def clean(self, *args, **kwargs):
        super(EditTeamVideoForm, self).clean(*args, **kwargs)

        return self.cleaned_data

    def save(self, *args, **kwargs):
        obj = super(EditTeamVideoForm, self).save(*args, **kwargs)

        video = obj.video

        author = self.cleaned_data['author'].strip()
        creation_date = VideoMetadata.date_to_string(self.cleaned_data['creation_date'])

        self._save_metadata(video, 'Author', author)
        self._save_metadata(video, 'Creation Date', creation_date)
        # store the uploaded thumb on the video itself
        # TODO: simply remove the teamvideo.thumbnail image
        if obj.thumbnail:
            content = ContentFile(obj.thumbnail.read())
            name = obj.thumbnail.url.split('/')[-1]
            video.s3_thumbnail.save(name, content)
            VideoIndex(Video).update_object(video)

    def _save_metadata(self, video, meta, data):
        '''Save a single piece of metadata for the given video.

        The metadata is only saved if necessary (i.e. it's not blank OR it's blank
        but there's already other data that needs to be overwritten).

        '''
        meta_type_id = VIDEO_META_TYPE_IDS[meta]

        try:
            meta = VideoMetadata.objects.get(video=video, key=meta_type_id)
            meta.data = data
            meta.save()
        except VideoMetadata.DoesNotExist:
            if data:
                VideoMetadata(video=video, key=meta_type_id, data=data).save()

class MoveTeamVideoForm(forms.Form):
    team_video = forms.ModelChoiceField(queryset=TeamVideo.objects.all(),
                                        required=True)
    team = forms.ModelChoiceField(queryset=Team.objects.all(),
                                  required=True)

    project = forms.ModelChoiceField(queryset=Project.objects.all(),
                                     required=False)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(MoveTeamVideoForm, self).__init__(*args, **kwargs)

    def clean(self):
        team_video = self.cleaned_data.get('team_video')
        team = self.cleaned_data.get('team')
        project = self.cleaned_data.get('project')

        if not team_video or not team:
            return

        if project and project.team != team:
            raise forms.ValidationError(u"That project does not belong to that team.")

        if team_video.team.pk == team.pk:
            raise forms.ValidationError(u"That video is already in that team.")

        if not can_add_video(team, self.user):
            raise forms.ValidationError(u"You can't add videos to that team.")

        if not can_remove_video(team_video, self.user):
            raise forms.ValidationError(u"You can't remove that video from its team.")

        return self.cleaned_data

class BaseVideoBoundForm(forms.ModelForm):
    video_url = UniSubBoundVideoField(label=_('Video URL'), verify_exists=True,
        help_text=_("Enter the URL of any compatible video or any video on our site. You can also browse the site and use the 'Add Video to Team' menu."))

    def __init__(self, *args, **kwargs):
        super(BaseVideoBoundForm, self).__init__(*args, **kwargs)
        if hasattr(self, 'user'):
            self.fields['video_url'].user = self.user

class AddTeamVideoForm(BaseVideoBoundForm):
    language = forms.ChoiceField(label=_(u'Video language'), choices=(),
                                 required=False,
                                 help_text=_(u'It will be saved only if video does not exist in our database.'))

    project = forms.ModelChoiceField(
        label=_(u'Project'),
        queryset = Project.objects.none(),
        required=True,
        empty_label=None,
        help_text=_(u"Let's keep things tidy, shall we?")
    )

    class Meta:
        model = TeamVideo
        fields = ('video_url', 'language', 'title', 'description', 'thumbnail', 'project',)

    def __init__(self, team, user, *args, **kwargs):
        self.team = team
        self.user = user
        super(AddTeamVideoForm, self).__init__(*args, **kwargs)


        projects = self.team.project_set.all()

        if len(projects) > 1:
            projects = projects.exclude(slug='_root')

        self.fields['project'].queryset = projects

        ordered_projects = ([p for p in projects if p.is_default_project] +
                            [p for p in projects if not p.is_default_project])
        ordered_projects = [p for p in ordered_projects if can_add_video(team, user, p)]

        self.fields['project'].choices = [(p.pk, p) for p in ordered_projects]

        writable_langs = team.get_writable_langs()
        self.fields['language'].choices = [c for c in get_language_choices(True)
                                           if c[0] in writable_langs]

    def clean_video_url(self):
        video_url = self.cleaned_data['video_url']
        video = self.fields['video_url'].video
        try:
            tv = TeamVideo.objects.get(team=self.team, video=video)
            raise forms.ValidationError(mark_safe(u'Team has this <a href="%s">video</a>' % tv.get_absolute_url()))
        except TeamVideo.DoesNotExist:
            pass

        return video_url

    def clean(self):
        language = self.cleaned_data.get('language')
        video = self.fields['video_url'].video

        if video:
            if TeamVideo.objects.filter(video=video, team__deleted=False).exists():
                msg = _(u'This video already belongs to a team.')
                self._errors['video_url'] = self.error_class([msg])

            original_sl = video.subtitle_language()

            if (original_sl and not original_sl.language) and not language:
                msg = _(u'Set original language for this video.')
                self._errors['language'] = self.error_class([msg])

        return self.cleaned_data

    def success_message(self):
        return 'Video successfully added to team.'

    def save(self, commit=True):
        video_language = self.cleaned_data['language']
        video = self.fields['video_url'].video
        if video_language:
            original_language = video.subtitle_language()
            if original_language and not original_language.language and \
                not video.subtitlelanguage_set.filter(language=video_language).exists():
                original_language.language = video_language
                original_language.save()

        obj = super(AddTeamVideoForm, self).save(False)
        obj.video = video
        obj.team = self.team
        commit and obj.save()
        return obj

class AddTeamVideosFromFeedForm(AddFromFeedForm):
    VIDEOS_LIMIT = None

    def __init__(self, team, user, *args, **kwargs):
        self.team = team
        super(AddTeamVideosFromFeedForm, self).__init__(user, *args, **kwargs)

    def save(self, *args, **kwargs):
        videos = super(AddTeamVideosFromFeedForm, self).save(*args, **kwargs)

        team_videos = []
        project = self.team.default_project
        for video, video_created in videos:
            try:
                tv = TeamVideo.objects.get(video=video, team=self.team)
                tv_created = False
            except TeamVideo.DoesNotExist:
                tv = TeamVideo(video=video, team=self.team, added_by=self.user,
                               project=project)
                tv.title = video.title
                tv.description = video.description
                tv.save()
                tv_created = True
            team_videos.append((tv, tv_created))

        return team_videos

    def success_message(self):
        if not self.video_limit_routreach:
            return _(u"%(count)s videos have been added. "
                     u"It will take a minute or so for them to appear.")
        else:
            return _(u"%(count)s videos have been added. "
                     u"It will take a minute or so for them to appear. "
                     u"To add the remaining videos from this feed, "
                     u"submit this feed again and make sure to "
                     u'check "Save feed" box.')

class CreateTeamForm(BaseVideoBoundForm):
    logo = forms.ImageField(validators=[MaxFileSizeValidator(settings.AVATAR_MAX_SIZE)], required=False)

    class Meta:
        model = Team
        fields = ('name', 'slug', 'description', 'logo', 'is_moderated',
                  'is_visible', 'video_url')

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(CreateTeamForm, self).__init__(*args, **kwargs)
        self.fields['video_url'].label = _(u'Team intro video URL')
        self.fields['video_url'].required = False
        self.fields['video_url'].help_text = _(u'''You can put an optional video
on your team homepage that explains what your team is about, to attract volunteers.
Enter a link to any compatible video, or to any video page on our site.''')
        self.fields['is_visible'].widget.attrs['class'] = 'checkbox'
        self.fields['is_moderated'].widget.attrs['class'] = 'checkbox'
        self.fields['slug'].label = _(u'Team URL: http://universalsubtitles.org/teams/')

    def clean_slug(self):
        slug = self.cleaned_data['slug']
        if re.match('^\d+$', slug):
            raise forms.ValidationError('Field can\'t contains only numbers')
        return slug

    def save(self, user):
        team = super(CreateTeamForm, self).save(False)
        video = self.fields['video_url'].video
        if video:
            team.video = video
        team.save()
        TeamMember.objects.create_first_member(team=team, user=user)
        return team

class TaskCreateForm(ErrorableModelForm):
    choices = [(10, 'Transcribe'), Task.TYPE_CHOICES[1]]
    type = forms.TypedChoiceField(choices=choices, coerce=int)
    language = forms.ChoiceField(choices=(), required=False)
    assignee = forms.ModelChoiceField(queryset=User.objects.none(), required=False)

    def __init__(self, user, team, team_video, *args, **kwargs):
        non_display_form = False
        if kwargs.get('non_display_form'):
            non_display_form = kwargs.pop('non_display_form')
        super(TaskCreateForm, self).__init__(*args, **kwargs)

        self.user = user
        self.team_video = team_video

        # TODO: This is bad for teams with 10k members.
        team_user_ids = team.members.values_list('user', flat=True)

        langs = [l for l in get_language_choices(with_empty=True)
                 if l[0] in team.get_writable_langs()]
        self.fields['language'].choices = langs
        self.fields['assignee'].queryset = User.objects.filter(pk__in=team_user_ids)

        if non_display_form:
            self.fields['type'].choices = Task.TYPE_CHOICES

    def _check_task_creation_subtitle(self, tasks, cleaned_data):
        if self.team_video.subtitles_finished():
            self.add_error(_(u"This video has already been transcribed."),
                           'type', cleaned_data)
            return

        if self.team_video.subtitles_started():
            self.add_error(_(u"Subtitling of this video is already in progress."),
                           'type', cleaned_data)
            return

    def _check_task_creation_translate(self, tasks, cleaned_data):
        if not self.team_video.subtitles_finished():
            self.add_error(_(u"No one has transcribed this video yet, so it can't be translated."),
                           'type', cleaned_data)
            return

        sl = self.team_video.video.subtitle_language(cleaned_data['language'])
        if sl and sl.is_complete_and_synced():
            self.add_error(_(u"This language already has a complete set of subtitles."),
                           'language', cleaned_data)
            return


    def clean(self):
        cd = self.cleaned_data

        type = cd['type']
        lang = cd['language']
        assignee = cd['assignee']

        team_video = self.team_video
        project, team = team_video.project, team_video.team

        # TODO: Manager method?
        existing_tasks = list(Task.objects.filter(deleted=False, language=lang,
                                                  team_video=team_video))

        if any(not t.completed for t in existing_tasks):
            self.add_error(_(u"There is already a task in progress for that video/language."))

        if assignee:
            # TODO: Check perms
            # if not can_assign_task(task, self.user):
            #     self.add_error(_(u"You are not allowed to assign this task."),
            #                    'assignee', cd)
            pass

        type_name = Task.TYPE_NAMES[type]

        # TODO: Move into _check_task_creation_translate()?
        if type_name == 'Translate':
            if lang == '':
                self.add_error(_(u"You must select a language for a Translate task."))

        {'Subtitle': self._check_task_creation_subtitle,
         'Translate': self._check_task_creation_translate,
         'Review': lambda x, y: x,
         'Approve': lambda x, y: x
        }[type_name](existing_tasks, cd)

        return cd


    class Meta:
        model = Task
        fields = ('type', 'language', 'assignee')

class TaskAssignForm(forms.Form):
    task = forms.ModelChoiceField(queryset=Task.objects.none())
    assignee = forms.ModelChoiceField(queryset=User.objects.none(), required=False)

    def __init__(self, team, user, *args, **kwargs):
        super(TaskAssignForm, self).__init__(*args, **kwargs)

        self.team = team
        self.user = user
        self.fields['assignee'].queryset = User.objects.filter(team_members__team=team)
        self.fields['task'].queryset = team.task_set.incomplete()


    def clean_assignee(self):
        assignee = self.cleaned_data['assignee']

        if assignee:
            member = self.team.members.get(user=assignee)
            if member.has_max_tasks():
                raise forms.ValidationError(_(
                    u'That user has already been assigned the maximum number of tasks.'))

        return assignee

    def clean(self):
        task = self.cleaned_data['task']
        assignee = self.cleaned_data.get('assignee', -1)

        if assignee != -1:
            # There are a bunch of edge cases here that we need to check.
            unassigning_from_self      = (not assignee) and task.assignee and task.assignee.id == self.user.id
            assigning_to_self          = assignee and self.user.id == assignee.id
            can_assign_to_other_people = can_assign_task(task, self.user)

            # Users can always unassign a task from themselves.
            if not unassigning_from_self:
                # They can also assign a task TO themselves, assuming they can
                # perform it (which is checked further down).
                if not assigning_to_self:
                    # Otherwise they must have assign permissions in the team.
                    if not can_assign_to_other_people:
                        raise forms.ValidationError(_(
                            u'You do not have permission to assign this task.'))

            if assignee is None:
                return self.cleaned_data
            else:
                if not can_perform_task(assignee, task):
                    raise forms.ValidationError(_(
                        u'This user cannot perform that task.'))

        return self.cleaned_data

class TaskDeleteForm(forms.Form):
    task = forms.ModelChoiceField(queryset=Task.objects.all())
    discard_subs = forms.BooleanField(required=False)

    def __init__(self, team, user, *args, **kwargs):
        super(TaskDeleteForm, self).__init__(*args, **kwargs)

        self.user = user

        self.fields['task'].queryset = team.task_set.incomplete()


    def clean_task(self):
        task = self.cleaned_data['task']

        if not can_delete_task(task, self.user):
            raise forms.ValidationError(_(
                u'You do not have permission to delete this task.'))

        return task

class GuidelinesMessagesForm(forms.Form):
    messages_invite = forms.CharField(max_length=4000, required=False, widget=forms.Textarea)
    messages_manager = forms.CharField(max_length=4000, required=False, widget=forms.Textarea)
    messages_admin = forms.CharField(max_length=4000, required=False, widget=forms.Textarea)
    messages_application = forms.CharField(max_length=4000, required=False, widget=forms.Textarea)

    guidelines_subtitle = forms.CharField(max_length=4000, required=False, widget=forms.Textarea)
    guidelines_translate = forms.CharField(max_length=4000, required=False, widget=forms.Textarea)
    guidelines_review = forms.CharField(max_length=4000, required=False, widget=forms.Textarea)

class RenameableSettingsForm(forms.ModelForm):
    logo = forms.ImageField(validators=[MaxFileSizeValidator(settings.AVATAR_MAX_SIZE)], required=False)

    class Meta:
        model = Team
        fields = ('name', 'description', 'logo', 'is_visible')

class SettingsForm(forms.ModelForm):
    logo = forms.ImageField(validators=[MaxFileSizeValidator(settings.AVATAR_MAX_SIZE)], required=False)

    class Meta:
        model = Team
        fields = ('description', 'logo', 'is_visible')

class WorkflowForm(forms.ModelForm):
    class Meta:
        model = Workflow
        fields = ('autocreate_subtitle', 'autocreate_translate',
                  'review_allowed', 'approve_allowed')

class PermissionsForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ('membership_policy', 'video_policy', 'subtitle_policy',
                  'translate_policy', 'task_assign_policy', 'workflow_enabled',
                  'max_tasks_per_member', 'task_expiration',)

class LanguagesForm(forms.Form):
    preferred = forms.MultipleChoiceField(required=False, choices=())
    blacklisted = forms.MultipleChoiceField(required=False, choices=())

    def __init__(self, team, *args, **kwargs):
        super(LanguagesForm, self).__init__(*args, **kwargs)

        self.team = team
        self.fields['preferred'].choices = get_language_choices(True)
        self.fields['blacklisted'].choices = get_language_choices(True)

    def clean(self):
        preferred = set(self.cleaned_data['preferred'])
        blacklisted = set(self.cleaned_data['blacklisted'])

        if len(preferred & blacklisted):
            raise forms.ValidationError(_(u'You cannot blacklist a preferred language.'))

        return self.cleaned_data

class InviteForm(forms.Form):
    user_id = forms.CharField(required=False, widget=forms.Select)
    message = forms.CharField(required=False, widget=forms.Textarea)
    role = forms.ChoiceField(choices=TeamMember.ROLES[1:][::-1], initial='contributor')

    def __init__(self, team, user, *args, **kwargs):
        super(InviteForm, self).__init__(*args, **kwargs)
        self.team = team
        self.user = user
        self.fields['role'].choices = [(r, ROLE_NAMES[r])
                                       for r in roles_user_can_invite(team, user)]


    def clean_user_id(self):
        user_id = self.cleaned_data['user_id']

        try:
            User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise forms.ValidationError(_(u'User does not exist!'))
        except ValueError:
            raise forms.ValidationError(_(u'User does not exist!'))

        try:
            self.team.members.get(user__id=user_id)
        except TeamMember.DoesNotExist:
            pass
        else:
            raise forms.ValidationError(_(u'User is already a member of this team!'))

        self.user_id = user_id
        return user_id


    def save(self):
        from messages import tasks as notifier
        user = User.objects.get(id=self.user_id)
        invite, created = Invite.objects.get_or_create(team=self.team, user=user, defaults={
            'note': self.cleaned_data['message'],
            'author': self.user,
            'role': self.cleaned_data['role'],
        })

        notifier.team_invitation_sent.delay(invite.pk)
        return invite

class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ('name', 'description', 'workflow_enabled')

class UnpublishForm(forms.Form):
    subtitle_version = forms.ModelChoiceField(queryset=SubtitleVersion.objects.all())

    should_delete = forms.BooleanField(
            label=_(u'Would you like to delete these subtitles completely?'),
            required=False)

    scope = forms.ChoiceField(
            label=_(u'What would you like to unpublish?'),
            choices=(
                ('version',    _(u'This version (and any later version) for this language.')),
                ('dependents', _(u'All versions for this language and any dependent languages.'))))


    def __init__(self, user, team, *args, **kwargs):
        super(UnpublishForm, self).__init__(*args, **kwargs)

        self.user = user
        self.team = team

    def clean(self):
        subtitle_version = self.cleaned_data.get('subtitle_version')
        if not subtitle_version:
            return self.cleaned_data

        team_video = subtitle_version.language.video.get_team_video()

        if not team_video:
            raise forms.ValidationError(_(
                u"These subtitles are not under a team's control."))

        if not can_unpublish_subs(team_video, self.user, subtitle_version.language.language):
            raise forms.ValidationError(_(
                u'You do not have permission to unpublish these subtitles.'))

        return self.cleaned_data

class UploadDraftForm(forms.Form):
    draft = forms.FileField(required=True)
    task = forms.ModelChoiceField(Task.objects, required=True)
    translate_from = forms.ChoiceField(required=False, choices=[("", "Direct")] + ALL_LANGUAGES, initial='en')
    language = forms.ChoiceField(required=False, choices=ALL_LANGUAGES, initial='')

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(UploadDraftForm, self).__init__(*args, **kwargs)
        self.fields['language'].choices = get_language_choices(True)

    def clean_task(self):
        task = self.cleaned_data['task']

        if not can_perform_task(self.user, task):
            raise forms.ValidationError(_(u'You cannot perform that task.'))

        return task

    def clean_translate_from(self):
        language = self.cleaned_data['translate_from']
        task = self.cleaned_data['task']

        video = Video.objects.get(teamvideo=task.team_video_id)
        allowed_languages = [sl.language for sl in video.subtitlelanguage_set.all() if sl.is_complete_and_synced()]

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

            self._parser = self._get_parser(subtitles.name)(force_unicode(text, encoding))

            if not self._parser:
                raise forms.ValidationError(_(u'Incorrect subtitles format'))
        except SubtitleParserError, e:
            raise forms.ValidationError(e)

        subtitles.seek(0)

        return subtitles

    def _get_parser(self, filename):
        end = filename.split('.')[-1].lower()
        return ParserList[end]

    def _save_new_language(self, video, lang_code, translate_from):
        language = SubtitleLanguage()
        language.language = lang_code

        if not translate_from:
            language.is_original = True
        else:
            language.is_original = False
            language.is_forked = False

            # iuck
            if translate_from.is_original:
                language.standard_language = translate_from
            else:
                language.standard_language = translate_from.standard_language

        language.video = video
        language.save()

        return language

    def save(self):
        from videos.tasks import video_changed_tasks

        task = self.cleaned_data['task']
        video = task.team_video.video
        language_to_translate = self.cleaned_data['translate_from']

        if not task.assignee:
            task.assignee = self.user
            task.set_expiration()

        if task.language:
            video_language = task.language
        else:
            video_language = self.cleaned_data['language']

        translated_from = None

        if task.get_subtitle_version():
            version = task.get_subtitle_version()
            language = task.get_subtitle_version().language

            if not language.is_original:
                translated_from = language.standard_language
        else:
            translated_from = video.subtitle_language(language_to_translate) if language_to_translate else None
            language = video.subtitle_language(video_language)

            if language and language.has_version:
                version = language.latest_version(public_only=False)
            else:
                version = None

                if not language:
                    language = self._save_new_language(video, video_language, translated_from)

        # if the language has dependents, check if the transcript is smaller so we don't lose subtitles
        if language.is_original or language.is_forked:
            if version and SubtitleLanguage.objects.filter(standard_language=language).exists():
                if len(self._parser) < version.subtitle_set.count():
                    raise Exception(_(u"Sorry, we couldn't upload your file because it has fewer lines ({0}) than the previous version ({1}).".format(len(self._parser), version.subtitle_set.count())))
        # if we are translating from another version, always check if we don't have
        # more subtitles than we need
        elif translated_from and translated_from.version():
            original_subs_count = translated_from.version().subtitle_set.count()
            if len(self._parser) > original_subs_count:
                raise Exception(_(u"Sorry, we couldn't upload your file because the number of lines in your translation ({0}) doesn't match the original ({1}).".format(len(self._parser), original_subs_count)))

        # we need to set the moderation_status to WAITING_MODERATION
        # so the version is not public. At the same time, we cannot
        # set task.subtitle_version if it's review/approve, otherwise
        # the task will get blocked. :(
        version = SubtitleVersion.objects.new_version(self._parser, language, self.user,
                                                      moderation_status=WAITING_MODERATION,
                                                      translated_from=translated_from,
                                                      note="Uploaded")

        # TODO: Can we please refactor the subtitle pipeline?  This is the third
        # place we need to do this :(
        record_workflow_origin(version, task.team_video)

        if task.type in (Task.TYPE_IDS['Review'], Task.TYPE_IDS['Approve']):
            task.subtitle_version = version

        if not task.language:
            task.language = video_language

        task.save()

        # we created a new subtitle version let's fire a notification
        video_changed_tasks.delay(video.id, version.id)

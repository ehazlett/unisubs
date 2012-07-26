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
from os import path

from django.conf import settings
from django.core.urlresolvers import reverse
from django.test import TestCase

from apps.teams.models import Team, TeamMember, TeamVideo, Project
from apps.videos.models import Video, VideoUrl
from auth.models import CustomUser as User
from utils.panslugify import pan_slugify


class ViewsTests(TestCase):
    fixtures = ["staging_users.json", "staging_videos.json", "staging_teams.json"]

    def setUp(self):
        self.auth = {
            "username": u"admin",
            "password": u"admin"}
        self.user = User.objects.get(username=self.auth["username"])

    def _create_base_team(self):
       self.team = Team(
           slug="new-team",
            membership_policy=4,
            video_policy =1,
           name="New-name")
       self.team.save()
       user, created = User.objects.get_or_create(
           username=self.auth["username"])
       TeamMember.objects.create_first_member(self.team, user)
       return self.team


    def test_team_create(self):


        self.client.login(**self.auth)

        #------- create ----------
        response = self.client.get(reverse("teams:create"))
        self.failUnlessEqual(response.status_code, 200)

        data = {
            "description": u"",
            "video_url": u"",
            "membership_policy": u"4",
            "video_policy": u"1",
            "logo": u"",
            "slug": u"new-team",
            "name": u"New team"
        }
        response = self.client.post(reverse("teams:create"), data)
        self.failUnlessEqual(response.status_code, 302)
        self.assertEqual(Team.objects.get(slug=data['slug']).slug, data["slug"])

    def test_team_edit(self):
        team = self._create_base_team()
        self.client.login(**self.auth)
        url = reverse("teams:settings_basic", kwargs={"slug": team.slug})
        response = self.client.get(url)

        member = self._create_member(team, TeamMember.ROLE_ADMIN)
        videos = []

        for video in Video.objects.all()[0:4]:
            self._create_team_video(video.get_video_url(), team, member.user)
            videos.append(video.video_id)

        self.failUnlessEqual(response.status_code, 200)
        self.assertTrue(all([v.is_public for v in Video.objects.all()[0:4]]))

        self.assertFalse(team.logo)

        data = {
            "name": u"New team",
            "is_visible": u"0",
            "description": u"testing",
            "logo": open(path.join(settings.MEDIA_ROOT, "test/71600102.jpg"), "rb")
        }

        url = reverse("teams:settings_basic", kwargs={"slug": team.slug})
        response = self.client.post(url, data)
        self.failUnlessEqual(response.status_code, 302)

        team = Team.objects.get(pk=team.pk)
        self.assertTrue(team.logo)
        self.assertEqual(team.name, u"New team")
        self.assertEqual(team.description, u"testing")
        self.assertFalse(team.is_visible)
        self.assertFalse(all([v.is_public for v in Video.objects.all()[0:4]]))

        data = {
            "name": u"New team",
            "is_visible": u"1",
            "description": u"testing",
        }

        url = reverse("teams:settings_basic", kwargs={"slug": team.slug})
        response = self.client.post(url, data)

        self.failUnlessEqual(response.status_code, 302)
        self.assertTrue(all([v.is_public for v in Video.objects.all()[0:4]]))

    def test_create_project(self):
        team = self._create_base_team()
        self.client.login(**self.auth)

        url = reverse("teams:add_project", kwargs={"slug": team.slug})

        data = {
            "name": u"Test Project",
            "description": u"Test Project",
            "review_allowed": u"0",
            "approve_allowed": u"0",
        }

        response = self.client.post(url, data)
        self.failUnlessEqual(response.status_code, 302)

        slug = pan_slugify(data['name'])

        project = Project.objects.get(slug=slug)
        self.assertEqual(project.name, data['name'])
        self.assertEqual(project.description, data['description'])

        # creating a duplicated project results in error
        response = self.client.post(url, data)
        self.failUnlessEqual(response.status_code, 200)
        messages = [m.message for m in list(response.context['messages'])]
        self.assertIn(u"There's already a project with this name", messages)

    def test_remove_video(self):
        video_url = Video.objects.all()[0].get_video_url()

        team = Team(slug="new-team", membership_policy=4, video_policy=1, name="New-name")
        team.save()

        TeamMember.objects.create_first_member(
            team, User.objects.create(username='void'))

        def create_member(role):
            user = User.objects.create(username='test' + role)
            user.set_password('test' + role)
            user.save()
            return TeamMember.objects.create(user=user, role=role, team=team)

        admin = create_member(TeamMember.ROLE_ADMIN)
        contributor = create_member(TeamMember.ROLE_CONTRIBUTOR)
        manager = create_member(TeamMember.ROLE_MANAGER)
        owner = create_member(TeamMember.ROLE_OWNER)

        def create_team_video():
           v, c = Video.get_or_create_for_url(video_url)
           tv, c = TeamVideo.objects.get_or_create(video=v, team=team,
                                                   defaults={'added_by': owner.user})
           return tv

        # The video policy determines who can remove videos from teams.
        for member in [contributor, manager, admin, owner]:
            self.client.login(username=member.user.username,
                              password=member.user.username)
            tv = create_team_video()

            url = reverse("teams:remove_video", kwargs={"team_video_pk": tv.pk})
            response = self.client.post(url)

            self.assertEqual(response.status_code, 302)
            self.assertFalse(TeamVideo.objects.filter(pk=tv.pk).exists())
            self.assertTrue(VideoUrl.objects.get(url=video_url).video)

        # Only owners can delete videos entirely.
        for role in [owner]:
            self.client.login(username=role.user.username,
                              password=role.user.username)
            tv = create_team_video()

            url = reverse("teams:remove_video", kwargs={"team_video_pk": tv.pk})
            response = self.client.post(url, {'del-opt': 'total-destruction'})

            self.assertEqual(response.status_code, 302)
            self.assertFalse(TeamVideo.objects.filter(pk=tv.pk).exists())
            self.assertFalse(VideoUrl.objects.filter(url=video_url).exists())

        for role in [contributor, manager, admin]:
            self.client.login(username=role.user.username,
                              password=role.user.username)
            tv = create_team_video()

            url = reverse("teams:remove_video", kwargs={"team_video_pk": tv.pk})
            response = self.client.post(url, {'del-opt': 'total-destruction'})

            self.assertEqual(response.status_code, 302)
            self.assertTrue(TeamVideo.objects.filter(pk=tv.pk).exists())
            self.assertTrue(VideoUrl.objects.filter(url=video_url).exists())

        # POST request required
        tv = create_team_video()
        url = reverse("teams:remove_video", kwargs={"team_video_pk": tv.pk})
        self.client.login(username=self.user.username,
                          password=self.user.username)
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(TeamVideo.objects.filter(pk=tv.pk).exists())
        self.assertTrue(VideoUrl.objects.filter(url=video_url).exists())


    def test_move_video_allowed(self):
        '''Check that moving works when the user has permission.'''
        video_pk = Video.objects.all()[0].pk

        # Convenient functions for pulling models fresh from the DB.
        get_video = lambda: Video.objects.get(pk=video_pk)
        get_team_video = lambda: get_video().get_team_video()

        old_team = Team.objects.get(pk=1)
        new_team = Team.objects.get(pk=2)

        # Create a member that's an admin of BOTH teams.
        # This member should be able to move the video.
        member = self._create_member(old_team, TeamMember.ROLE_ADMIN)
        self._create_member(new_team, TeamMember.ROLE_ADMIN, member.user)

        self._create_team_video(get_video().get_video_url(), old_team, member.user)

        self.assertEqual(get_team_video().team.pk, old_team.pk,
                         "Video did not start in the correct team.")

        # Move the video.
        self.client.login(username=member.user.username,
                          password=member.user.username)
        url = reverse("teams:move_video")
        response = self.client.post(url, {'team_video': get_team_video().pk,
                                          'team': new_team.pk,})
        self.assertEqual(response.status_code, 302)

        self.assertEqual(get_team_video().team.pk, new_team.pk,
                         "Video was not moved to the new team.")

        self.assertEqual(get_team_video().project.team, new_team,
                         "Video ended up with a project for the first team")

    def test_move_video_disallowed_old(self):
        '''Check that moving does not work when the user is blocked by the old team.'''
        video_pk = Video.objects.all()[0].pk

        get_video = lambda: Video.objects.get(pk=video_pk)
        get_team_video = lambda: get_video().get_team_video()

        old_team = Team.objects.get(pk=1)
        new_team = Team.objects.get(pk=2)

        # Create a member that's a contributor to the old/current team.
        # This member should NOT be able to move the video because they cannot
        # remove it from the first team.
        member = self._create_member(old_team, TeamMember.ROLE_CONTRIBUTOR)
        self._create_member(new_team, TeamMember.ROLE_ADMIN, member.user)

        self._create_team_video(get_video().get_video_url(), old_team, member.user)

        self.assertEqual(get_team_video().team.pk, old_team.pk,
                         "Video did not start in the correct team.")

        # Try to move the video.
        self.client.login(username=member.user.username,
                          password=member.user.username)
        url = reverse("teams:move_video")
        response = self.client.post(url, {'team_video': get_team_video().pk,
                                          'team': new_team.pk,})
        self.assertEqual(response.status_code, 302)

        self.assertEqual(get_team_video().team.pk, old_team.pk,
                         "Video did not stay in the old team.")

    def test_move_video_disallowed_new(self):
        '''Check that moving does not work when the user is blocked by the new team.'''
        video_pk = Video.objects.all()[0].pk

        get_video = lambda: Video.objects.get(pk=video_pk)
        get_team_video = lambda: get_video().get_team_video()

        old_team = Team.objects.get(pk=1)
        new_team = Team.objects.get(pk=2)

        # Create a member that's a contributor to the new/target team.
        # This member should NOT be able to move the video because they cannot
        # add it to the second team.
        member = self._create_member(old_team, TeamMember.ROLE_ADMIN)
        self._create_member(new_team, TeamMember.ROLE_CONTRIBUTOR, member.user)

        self._create_team_video(get_video().get_video_url(), old_team, member.user)

        self.assertEqual(get_team_video().team.pk, old_team.pk,
                         "Video did not start in the correct team.")

        # Try to move the video.
        self.client.login(username=member.user.username,
                          password=member.user.username)
        url = reverse("teams:move_video")
        response = self.client.post(url, {'team_video': get_team_video().pk,
                                          'team': new_team.pk,})
        self.assertEqual(response.status_code, 302)

        self.assertEqual(get_team_video().team.pk, old_team.pk,
                         "Video did not stay in the old team.")

    def test_team_permission(self):
        team = Team(slug="private-team", name="Private Team", is_visible=False)
        team.save()

        user, created = User.objects.get_or_create(
           username=self.auth["username"])

        TeamMember.objects.create_first_member(team, user)

        for video in Video.objects.all()[0:4]:
            self._create_team_video(video.get_video_url(), team, user)

            url = reverse("videos:video", kwargs={"video_id": video.video_id})

            response = self.client.get(url, follow=True)
            self.assertEqual(response.status_code, 403)

            self.client.login(**self.auth)

            response = self.client.get(url, follow=True)
            self.assertEquals(response.status_code, 200)

            self.client.logout()

    def _create_team_video(self, video_url, team, user):
        v, c = Video.get_or_create_for_url(video_url)
        tv, c = TeamVideo.objects.get_or_create(video=v, team=team,
                                                defaults={'added_by': user})
        return tv

    def _create_member(self, team, role, user=None):
        if not user:
            user = User.objects.create(username='test' + role)
            user.set_password('test' + role)
            user.save()
        return TeamMember.objects.create(user=user, role=role, team=team)


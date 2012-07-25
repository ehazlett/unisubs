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

import json, random
from datetime import datetime

from django.test import TestCase
from django.core.urlresolvers import reverse
from apps.auth.models import CustomUser as User
from apps.auth.models import EmailConfirmation
from django.core import mail

from apps.messages.models import Message
from apps.messages import tasks as notifier

from teams.models import Team, TeamMember, Application, Workflow,\
     TeamVideo, Task, Setting, Invite
from teams.forms import InviteForm
from videos.models import Action, Video, SubtitleVersion, SubtitleLanguage, \
     Subtitle
from utils import send_templated_email

class MessageTest(TestCase):

    def setUp(self):
        self.author = User.objects.all()[:1].get()
        self.subject = "Let's talk"
        self.body = "Will you please help me out with Portuguese trans?"
        self.user = User.objects.exclude(pk=self.author.pk)[:1].get()

    def _create_message(self, to_user):
        self.message = Message(user=to_user,
                           author=self.author,
                           subject=self.subject,
                          content=self.body)
        self.message.save()

    def _send_email(self, to_user):
        send_templated_email(to_user, "test email", "messages/email/email-confirmed.html", {})

    def test_send_email_to_allowed_user(self):
        self.user.notify_by_email = True
        self.user.save()
        assert self.user.is_active and self.user.email
        
        self._send_email(self.user)
        self.assertEqual(len(mail.outbox), 1)

    def test_send_email_to_optout_user(self):
        self.user.notify_by_email = False
        self.user.save()
        assert self.user.is_active and self.user.email
                
        self._send_email(self.user)
        self.assertEquals(len(mail.outbox), 0)

    def test_message_to_optout_user(self):
        self.user.notify_by_message = False
        self.user.notify_by_email = False
        self.user.save()
        self._send_email(self.user)
        self._create_message(self.user)
        self.assertEquals(len(mail.outbox), 0)
        self.assertEquals(Message.objects.unread().filter(user=self.user).count(), 0)
        self.assertEquals(Message.objects.filter(user=self.user).count(), 1)
        
    def test_member_join(self):
        def _get_counts(member):
            email_to = "%s" %( member.user.email) 
            return Message.objects.filter(user=member.user).count() , \
                len([x for x in mail.outbox if email_to in x.recipients()])
            
        
        team , created= Team.objects.get_or_create(name='test', slug='test')
        # creates dummy users:
        for x in xrange(0,5):
            user, member = User.objects.get_or_create(
                username="test%s" % x,
                email = "test%s@example.com" % x,
            )
            tm = TeamMember(team=team, user=user)
            if x == 0:
                tm.role = TeamMember.ROLE_OWNER
                owner = tm
            elif x == 1:
                tm.role = TeamMember.ROLE_ADMIN
                admin = tm
            elif x == 2:
                tm.role = TeamMember.ROLE_MANAGER
                manager = tm
            elif x == 3:
                tm.role = TeamMember.ROLE_CONTRIBUTOR
                contributor = tm
            if x < 4:
                # don't save the last role until we have counts
                tm.save()
            else:
                tm.role= TeamMember.ROLE_CONTRIBUTOR
            
        # now make sure we count previsou messages
        owner_messge_count_1, owner_email_count_1 = _get_counts(owner)
        admin_messge_count_1, admin_email_count_1 = _get_counts(admin)
        manager_messge_count_1, manager_email_count_1 = _get_counts(manager)
        contributor_messge_count_1, contributor_email_count_1 = _get_counts(contributor)
        # save the last team member and check that each group has appropriate counts 
        tm.save()
        notifier.team_member_new(tm.pk)
        # owner and admins should receive email + message
        owner_messge_count_2, owner_email_count_2 = _get_counts(owner)
        self.assertEqual(owner_messge_count_1 + 1, owner_messge_count_2)
        self.assertEqual(owner_email_count_1 + 1, owner_email_count_2)
        admin_messge_count_2, admin_email_count_2 = _get_counts(admin)
        self.assertEqual(admin_messge_count_1 + 1, admin_messge_count_2)
        self.assertEqual(admin_email_count_1 + 1, admin_email_count_2)
        # manager shoud not
        manager_messge_count_2, manager_email_count_2 = _get_counts(manager)
        self.assertEqual(manager_messge_count_1 , manager_messge_count_2)
        self.assertEqual(manager_email_count_1 , manager_email_count_2)
        # contributor shoud not
        contributor_messge_count_2, contributor_email_count_2 = _get_counts(contributor)
        self.assertEqual(contributor_messge_count_1 , contributor_messge_count_2)
        self.assertEqual(contributor_email_count_1 , contributor_email_count_2)


        # now, this has to show up on everybody activitis fed
        action = Action.objects.get(team=team, user=tm.user, action_type=Action.MEMBER_JOINED)
        self.assertTrue(Action.objects.for_user(tm.user).filter(pk=action.pk).exists())
        self.assertTrue(Action.objects.for_user(owner.user).filter(pk=action.pk).exists())
        self.assertTrue(Action.objects.for_user(manager.user).filter(pk=action.pk).exists())
        self.assertTrue(Action.objects.for_user(contributor.user).filter(pk=action.pk).exists())
        self.assertTrue(Action.objects.for_user(admin.user).filter(pk=action.pk).exists())
        
    def test_member_leave(self):
        return # fix me now
        def _get_counts(member):
            email_to = "%s" %( member.user.email) 
            return Message.objects.filter(user=member.user).count() , \
                len([x for x in mail.outbox if email_to in x.recipients()])
            
        
        team , created= Team.objects.get_or_create(name='test', slug='test')
        
        # creates dummy users:
        for x in xrange(0,5):
            user, member = User.objects.get_or_create(
                username="test%s" % x,
                email = "test%s@example.com" % x,
                notify_by_email = True,
            )
            tm = TeamMember(team=team, user=user)
            if x == 0:
                tm.role = TeamMember.ROLE_OWNER
                owner = tm
            elif x == 1:
                tm.role = TeamMember.ROLE_ADMIN
                admin = tm
            elif x == 2:
                tm.role = TeamMember.ROLE_MANAGER
                manager = tm
            elif x == 3:
                tm.role = TeamMember.ROLE_CONTRIBUTOR
                contributor = tm
            if x < 4:
                # don't save the last role until we have counts
                tm.save()
            else:
                tm.role= TeamMember.ROLE_CONTRIBUTOR
            
        tm.save()
        # now make sure we count previsou messages
        owner_messge_count_1, owner_email_count_1 = _get_counts(owner)
        admin_messge_count_1, admin_email_count_1 = _get_counts(admin)
        manager_messge_count_1, manager_email_count_1 = _get_counts(manager)
        contributor_messge_count_1, contributor_email_count_1 = _get_counts(contributor)

        # now delete and check numers
        
        tm_user = tm.user
        tm_user_pk = tm.user.pk
        team_pk = tm.team.pk
        tm.delete()
        notifier.team_member_leave(team_pk, tm_user_pk)
        # save the last team member and check that each group has appropriate counts 
        # owner and admins should receive email + message
        owner_messge_count_2, owner_email_count_2 = _get_counts(owner)
        self.assertEqual(owner_messge_count_1 + 1, owner_messge_count_2)
        self.assertEqual(owner_email_count_1 + 1, owner_email_count_2)
        admin_messge_count_2, admin_email_count_2 = _get_counts(admin)
        self.assertEqual(admin_messge_count_1 + 1, admin_messge_count_2)
        self.assertEqual(admin_email_count_1 + 1, admin_email_count_2)
        # manager shoud not
        manager_messge_count_2, manager_email_count_2 = _get_counts(manager)
        self.assertEqual(manager_messge_count_1 , manager_messge_count_2)
        self.assertEqual(manager_email_count_1 , manager_email_count_2)
        # contributor shoud not
        contributor_messge_count_2, contributor_email_count_2 = _get_counts(contributor)
        self.assertEqual(contributor_messge_count_1 , contributor_messge_count_2)
        self.assertEqual(contributor_email_count_1 , contributor_email_count_2)


        # now, this has to show up on everybody activitis fed
        action = Action.objects.get(team=team, user=tm_user, action_type=Action.MEMBER_LEFT)
        self.assertTrue(Action.objects.for_user(tm.user).filter(pk=action.pk).exists())
        self.assertTrue(Action.objects.for_user(owner.user).filter(pk=action.pk).exists())
        self.assertTrue(Action.objects.for_user(manager.user).filter(pk=action.pk).exists())
        self.assertTrue(Action.objects.for_user(contributor.user).filter(pk=action.pk).exists())
        self.assertTrue(Action.objects.for_user(admin.user).filter(pk=action.pk).exists())
        
    def test_application_new(self):
        def _get_counts(member):
            email_to = "%s" %(member.user.email) 
            return Message.objects.filter(user=member.user).count() , \
                len([x for x in mail.outbox if email_to in x.recipients()])
            
        
        team , created= Team.objects.get_or_create(name='test', slug='test')
        applying_user = User.objects.all()[0]
        # creates dummy users:
        for x in xrange(0,4):
            user, member = User.objects.get_or_create(
                username="test%s" % x,
                email = "test%s@example.com" % x,
                notify_by_email = True,
                notify_by_message = True,
            )
            tm = TeamMember(team=team, user=user)
            if x == 0:
                tm.role = TeamMember.ROLE_OWNER
                owner = tm
            elif x == 1:
                tm.role = TeamMember.ROLE_ADMIN
                admin = tm
            elif x == 2:
                tm.role = TeamMember.ROLE_MANAGER
                manager = tm
            elif x == 3:
                tm.role = TeamMember.ROLE_CONTRIBUTOR
                contributor = tm
            tm.save()
            
        # now make sure we count previsou messages
        owner_messge_count_1, owner_email_count_1 = _get_counts(owner)
        admin_messge_count_1, admin_email_count_1 = _get_counts(admin)
        manager_messge_count_1, manager_email_count_1 = _get_counts(manager)
        contributor_messge_count_1, contributor_email_count_1 = _get_counts(contributor)

        # now delete and check numers
        app = Application.objects.create(team=team,user=applying_user)
        app.save()
        notifier.application_sent.run(app.pk)
        # owner and admins should receive email + message
        owner_messge_count_2, owner_email_count_2 = _get_counts(owner)
        self.assertEqual(owner_messge_count_1 + 1, owner_messge_count_2)
        self.assertEqual(owner_email_count_1 + 1, owner_email_count_2)
        admin_messge_count_2, admin_email_count_2 = _get_counts(admin)
        self.assertEqual(admin_messge_count_1 + 1, admin_messge_count_2)
        self.assertEqual(admin_email_count_1 + 1, admin_email_count_2)
        # manager shoud not
        manager_messge_count_2, manager_email_count_2 = _get_counts(manager)
        self.assertEqual(manager_messge_count_1 , manager_messge_count_2)
        self.assertEqual(manager_email_count_1 , manager_email_count_2)
        # contributor shoud not
        contributor_messge_count_2, contributor_email_count_2 = _get_counts(contributor)
        self.assertEqual(contributor_messge_count_1 , contributor_messge_count_2)
        self.assertEqual(contributor_email_count_1 , contributor_email_count_2)


    def test_account_verified(self):
       user = User.objects.filter(
           notify_by_email=True, email__isnull=False)[0]
       c = EmailConfirmation.objects.send_confirmation(user)
       num_emails = len(mail.outbox)
       num_messages = Message.objects.filter(user=user).count()
       EmailConfirmation.objects.confirm_email(c.confirmation_key)
       self.assertEqual(num_emails +1, len(mail.outbox))
       self.assertEqual(num_messages +1,
                        Message.objects.filter(user=user).count())

    def test_team_inviation_sent(self):
        team, created= Team.objects.get_or_create(name='test', slug='test')
        owner, created = TeamMember.objects.get_or_create(
            team=team, user=User.objects.all()[2], role='owner')
        applying_user = User.objects.all()[0]
        applying_user.notify_by_email = True
        applying_user.save()
        mail.outbox = []
        message = "Will you be my valentine?"
        f = InviteForm(user=owner.user, team=team,data={
            "user_id":applying_user.id,
            "role":"admin",
            "message": message,
        })
        f.is_valid()
        f.save()
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn(applying_user.email, msg.to[0] )
        self.assertIn(message, msg.body, )


    def test_moderated_notifies_only_when_published(self):
        """
        Set up a public team, add new video and new version.
        Notification should be sent.
        Setup  a team with moderated videos
        """
        from teams.moderation_const import WAITING_MODERATION, APPROVED
        def video_with_two_followers():
            v, c = Video.get_or_create_for_url("http://blip.tv/file/get/Miropcf-AboutUniversalSubtitles847.ogv")
            f1 = User.objects.all()[0]
            f2 = User.objects.all()[1]
            f1.notify_by_email = f2.notify_by_email = True
            f1.save()
            f2.save()
            v.followers.add(f1, f2)
            return v
        def new_version(v):
            
            language, created = SubtitleLanguage.objects.get_or_create(video=v, language='en', is_original=True)
            prev = language.version(public_only=False)
            version_no = 0
            if prev:
                version_no = prev.version_no + 1
            sv = SubtitleVersion(
                language=language, user=User.objects.all()[2], version_no=version_no,
                datetime_started = datetime.now()
            )
            sv.save()
            s = Subtitle(
                version=sv, subtitle_text=str(version_no + random.random()),
                subtitle_order=1, subtitle_id=str(version_no),
                start_time = random.random())
            s.save()
            return sv
   
        v = video_with_two_followers()
        mail.outbox = []
        from videos.tasks import  video_changed_tasks
        v = video_with_two_followers()
        sv = new_version(v)
        video_changed_tasks(v.pk, sv.pk)
        # notifications are only sent on the second version of a video
        # as optimization
        sv = new_version(v)
        video_changed_tasks(v.pk, sv.pk)
        # video is public , followers should be notified
        self.assertEquals(len(mail.outbox), 2)
        mail.outbox = []
        # add to a moderated video
        team = Team.objects.create(slug='my-team', name='myteam', workflow_enabled=True)
        workflow = Workflow(team=team, review_allowed=20,approve_allowed=20 )
        workflow.save()

        tv = TeamVideo(team=team, video=v, added_by=User.objects.all()[2])
        tv.save()
        sv = new_version(v)
        # with the widget, this would set up correctly
        sv.moderation_status = WAITING_MODERATION
        sv.save()
        
        video_changed_tasks(v.pk, sv.pk)
        sv = SubtitleVersion.objects.get(pk=sv.pk)
        self.assertFalse(sv.is_public)
        # approve video
        t = Task(type=40, approved=20, team_video=tv, team=team, language='en', subtitle_version=sv)
        t.save()
        t.complete()
        video_changed_tasks(v.pk, sv.pk)
        
        self.assertEqual(len(mail.outbox), 2)

    def test_send_message_view(self):
        to_user = User.objects.filter(notify_by_email=True)[0]
        user, c = User.objects.get_or_create(username='username')
        user.notify_by_email = True
        user.set_password('username')
        user.save()
        mail.outbox = []
        self.client.login(username='username', password='username')
        self.client.post(reverse('messages:new'), {"user":to_user.pk, "subject": "hey", 'content':'test'})
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertTrue(to_user.email in m.to)
        

    def test_messages_remain_after_team_membership(self):
        # Here's the scenario:
        # User is invited to a team
        # - User accepts invitation
        # - Message for the invitation gets deleted -> wrong!
        user = User.objects.filter(notify_by_message=True)[0]
        owner = User.objects.filter(notify_by_message=True)[1]
        team = Team.objects.create(name='test-team', slug='test-team', membership_policy=Team.APPLICATION)

        invite_form = InviteForm(team, owner, {
            'user_id': user.pk,
            'message': 'Subtitle ALL the things!',
            'role':'contributor',
        })
        invite_form.is_valid()
        self.assertFalse(invite_form.errors)
        self.assertEquals(Message.objects.for_user(user).count(), 0)
        invite = invite_form.save()
        # user has the invitation message on their inbox now
        self.assertEquals(Message.objects.for_user(user).count(), 1)
        invite_message = Message.objects.for_user(user)[0]
        # now user accepts invite
        invite.accept()
        # he should be a team memebr
        self.assertTrue(team.members.filter(user=user).exists())
        # message should be still on their inbos
        self.assertIn(invite_message, Message.objects.for_user(user))


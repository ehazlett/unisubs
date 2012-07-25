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

import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.utils.http import cookie_date
from django.utils.translation import ugettext_lazy as _
from django.views.generic.list_detail import object_list

from apps.auth.models import CustomUser as User
from apps.messages.forms import SendMessageForm, NewMessageForm
from apps.messages.models import Message
from apps.messages.rpc import MessagesApiClass
from messages.tasks import send_new_message_notification
from utils import render_to_json, render_to
from utils.rpc import RpcRouter

rpc_router = RpcRouter('messages:rpc_router', {
    'MessagesApi': MessagesApiClass()
})

MAX_MEMBER_SEARCH_RESULTS = 40
MESSAGES_ON_PAGE = getattr(settings, 'MESSAGES_ON_PAGE', 30)


@login_required
def index(request, message_pk=None):
    user = request.user
    qs = Message.objects.for_user(user)

    extra_context = {
        'send_message_form': SendMessageForm(request.user, auto_id='message_form_id_%s'),
        'messages_display': True,
        'user_info': user,
        'can_edit': True
    }

    reply = request.GET.get('reply')

    if reply:
        try:
            reply_msg = Message.objects.get(pk=reply, user=user)
            reply_msg.read = True
            reply_msg.save()
            extra_context['reply_msg'] = reply_msg
        except (Message.DoesNotExist, ValueError):
            pass

    response = object_list(request, queryset=qs,
                       paginate_by=MESSAGES_ON_PAGE,
                       template_name='messages/list.html',
                       template_object_name='message',
                       extra_context=extra_context)
    try:
        last_message = qs[:1].get()
        max_age = 60*60*24*365
        expires = cookie_date(time.time()+max_age)
        response.set_cookie(Message.hide_cookie_name, last_message.pk, max_age, expires)
    except Message.DoesNotExist:
        pass

    return response

@login_required
def sent(request):
    user = request.user
    qs = Message.objects.for_author(request.user)
    extra_context = {
        'send_message_form': SendMessageForm(request.user, auto_id='message_form_id_%s'),
        'messages_display': True,
        'user_info': user
    }
    return object_list(request, queryset=qs,
                       paginate_by=MESSAGES_ON_PAGE,
                       template_name='messages/sent.html',
                       template_object_name='message',
                       extra_context=extra_context)

@login_required
@render_to('messages/new.html')
def new(request):
    selected_user = None

    if request.POST:
        form = NewMessageForm(request.user, request.POST)

        if form.is_valid():
            if form.cleaned_data['user']:
                m = Message(user=form.cleaned_data['user'], author=request.user,
                        content=form.cleaned_data['content'],
                        subject=form.cleaned_data['subject'])
                m.save()
                send_new_message_notification.delay(m.pk)
            elif form.cleaned_data['team']:
                # TODO: Move this into a task for performance?
                # Once we switch to Django 1.4, this should be replaced with
                # `bulk_create`.
                for member in form.cleaned_data['team'].members.all():
                    if member.user != request.user:
                        m = Message(user=member.user, author=request.user,
                                content=form.cleaned_data['content'],
                                subject=form.cleaned_data['subject'])
                        m.save()
                        send_new_message_notification.delay(m.pk)

            messages.success(request, _(u'Message sent.'))
            return HttpResponseRedirect(reverse('messages:index'))
        else:
            if request.GET.get('user'):
                selected_user = User.objects.get(username=request.GET['user'])
    else:
        form = NewMessageForm(request.user)

        if request.GET.get('user'):
            selected_user = User.objects.get(username=request.GET['user'])

    return {
        'selected_user': selected_user,
        'user_info': request.user,
        'form': form,
    }

@render_to_json
def search_users(request):
    users = User.objects.all()
    q = request.GET.get('term')

    results = [[u.id, u.username, unicode(u)]
               for u in users.filter(username__icontains=q,
                                            is_active=True)]

    results = results[:MAX_MEMBER_SEARCH_RESULTS]

    return { 'results': results }

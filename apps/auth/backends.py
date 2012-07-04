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
import random

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User as AuthUser

from auth.models import CustomUser as User
from socialauth.models import OpenidProfile as UserAssociation, AuthMeta


class CustomUserBackend(ModelBackend):
    supports_object_permissions = False
    supports_anonymous_user = False

    def authenticate(self, username=None, password=None):
        try:
            user = User.objects.get(username=username, is_active=True)
            if user.check_password(password):
                return user
        except User.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

class OpenIdBackend(object):
    supports_object_permissions = False
    supports_anonymous_user = False

    def authenticate(self, openid_key, request, provider):
        try:
            assoc = UserAssociation.objects.get(openid_key = openid_key)
            if assoc.user.is_active:
                return assoc.user
            else:
                return
        except UserAssociation.DoesNotExist:
            #fetch if openid provider provides any simple registration fields
            nickname = None
            email = None
            if request.openid and request.openid.sreg:
                email = request.openid.sreg.get('email')
                nickname = request.openid.sreg.get('nickname')
            elif request.openid and request.openid.ax:
                if provider in ('Google', 'Yahoo'):
                    email = request.openid.ax.get('http://axschema.org/contact/email')
                    email = email.pop()
                else:
                    try:
                        email = request.openid.ax.get('email')
                    except KeyError:
                        pass

                    try:
                        nickname = request.openid.ax.get('nickname')
                    except KeyError:
                        pass

            if nickname is None :
                if email:
                    nickname = email.split('@')[0]
                else:
                    nickname =  ''.join([random.choice('abcdefghijklmnopqrstuvwxyz') for i in xrange(10)])
            if email is None :
                valid_username = False
                email =  None #'%s@example.openid.com'%(nickname)
            else:
                valid_username = True
            name_count = AuthUser.objects.filter(username__startswith = nickname).count()

            if name_count:
                username = '%s%s'%(nickname, name_count + 1)
                user = User.objects.create_user(username,email or '')
            else:
                user = User.objects.create_user(nickname,email or '')
            user.save()

            #create openid association
            assoc = UserAssociation()
            assoc.openid_key = openid_key
            assoc.user = user#AuthUser.objects.get(pk=user.pk)
            if email:
                assoc.email = email
            if nickname:
                assoc.nickname = nickname
            if valid_username:
                assoc.is_username_valid = True
            assoc.save()

            #Create AuthMeta
            auth_meta = AuthMeta(user = user, provider = provider)
            auth_meta.save()
            return user

    def get_user(self, user_id):
        try:
            user = User.objects.get(pk = user_id)
            return user
        except User.DoesNotExist:
            return None


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

import requests
from django.conf import settings
from django.core.files.base import ContentFile

from apps.auth.models import CustomUser as User
from apps.thirdpartyaccounts.models import FacebookAccount, TwitterAccount
from socialauth.lib import oauthtwitter


TWITTER_CONSUMER_KEY = getattr(settings, 'TWITTER_CONSUMER_KEY', '')
TWITTER_CONSUMER_SECRET = getattr(settings, 'TWITTER_CONSUMER_SECRET', '')
FACEBOOK_API_KEY = getattr(settings, 'FACEBOOK_API_KEY', '')
FACEBOOK_API_SECRET = getattr(settings, 'FACEBOOK_API_SECRET', '')
FACEBOOK_REST_SERVER = getattr(settings, 'FACEBOOK_REST_SERVER',
                               'http://api.facebook.com/restserver.php')


class TwitterAuthBackend(object):
    def _get_existing_user(self, data):
        try:
            tpa = TwitterAccount.objects.get(username=data.screen_name)
            return User.objects.get(pk=tpa.user_id)
        except (TwitterAccount.DoesNotExist, User.DoesNotExist):
            return None

    def _find_available_username(self, data):
        username = data.screen_name

        name_count = User.objects.filter(username__startswith=username).count()
        if name_count:
            username = '%s%d' % (username, name_count + 1)

        return username

    def _get_first_last_name(self, data):
        name_data = data.name.split()

        try:
            first_name, last_name = name_data[0], ' '.join(name_data[1:])
        except:
            first_name, last_name = data.screen_name, ''

        return first_name, last_name

    def _create_user(self, access_token, data):
        username = self._find_available_username(data)

        twitter_username = data.screen_name
        first_name, last_name = self._get_first_last_name(data)
        avatar = data.profile_image_url

        email = '%s@twitteruser.%s.com' % (twitter_username, settings.SITE_NAME)

        user = User(username=username, email=email, first_name=first_name,
                    last_name=last_name)
        temp_password = User.objects.make_random_password(length=24)
        user.set_password(temp_password)
        user.save()

        TwitterAccount.objects.create(user=user, username=twitter_username,
                                      access_token=access_token.key,
                                      avatar=avatar)

        return user


    def authenticate(self, access_token):
        twitter = oauthtwitter.OAuthApi(TWITTER_CONSUMER_KEY,
                                        TWITTER_CONSUMER_SECRET,
                                        access_token)
        try:
            userinfo = twitter.GetUserInfo()
        except:
            # If we cannot get the user information, user cannot be authenticated
            raise

        user = self._get_existing_user(userinfo)
        if not user:
            user = self._create_user(access_token, userinfo)

        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except:
            return None


class FacebookAuthBackend(object):
    def _get_existing_user(self, data):
        try:
            tpa = FacebookAccount.objects.get(uid=data['uid'])
            return User.objects.get(pk=tpa.user_id)
        except (FacebookAccount.DoesNotExist, User.DoesNotExist):
            return None

    def _find_available_username(self, data):
        username = data.get('first_name', 'FACEBOOK_USER')

        name_count = User.objects.filter(username__istartswith=username).count()
        if name_count:
            username = '%s%d' % (username, name_count + 1)

        return username

    def _create_user(self, data):
        username = self._find_available_username(data)

        first_name = data.get('first_name')
        last_name = data.get('last_name')
        facebook_uid = data.get('uid')
        img_url = data.get('pic_square')

        email = '%s@facebookuser.%s.com' % (first_name, settings.SITE_NAME)

        user = User(username=username, email=email, first_name=first_name,
                    last_name=last_name)
        temp_password = User.objects.make_random_password(length=24)
        user.set_password(temp_password)
        user.save()

        if img_url:
            img = ContentFile(requests.get(img_url).content)
            name = img_url.split('/')[-1]
            user.picture.save(name, img, False)

        FacebookAccount.objects.create(uid=facebook_uid, user=user,
                                       avatar=img_url)

        return user


    def authenticate(self, facebook, request):
        facebook.oauth2_check_session(request)

        facebook.uid = facebook.users.getLoggedInUser()
        user_info = facebook.users.getInfo([facebook.uid],
                                           ['first_name', 'last_name', 'pic_square'])[0]

        # Check if we already have an active user for this Facebook user
        user = self._get_existing_user(user_info)
        if user:
            # If so, then we authenticate them if the user account is active, or
            # just return None if it's not.
            if user.is_active:
                return user
            else:
                return None

        # Otherwise this is a Facebook user we've never seen before, so we'll
        # make them an Amara account, Facebook TPA, and link the two.
        return self._create_user(user_info)


    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except:
            return None



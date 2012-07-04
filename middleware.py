import re
import random
import time

import debug_toolbar
import django.db.backends.mysql.base
from debug_toolbar.middleware import DebugToolbarMiddleware
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_ipv4_address
from django.db.backends.mysql.base import CursorWrapper as _CursorWrapper
from django.utils.cache import patch_vary_headers
from django.utils.hashcompat import sha_constructor
from django.utils.http import cookie_date

from utils.metrics import ManualTimer, Meter, Timer


SECTIONS = {
    'widget': 'widget',
    'api': 'api-v1',
    'api2': 'api-v2',
    'teams': 'teams',
}


class SaveUserIp(object):
    def process_request(self, request):
        if request.user.is_authenticated():
            ip = request.META.get('REMOTE_ADDR', '')
            try:
                validate_ipv4_address(ip)
                if request.user.last_ip != ip:
                    request.user.last_ip = ip
                    request.user.save()
            except ValidationError:
                pass

class ResponseTimeMiddleware(object):
    """Middleware for recording response times.

    Writes the time this request took to process, as a cookie in the response.
    In order for it to work, it must be the very first middleware in settings.py

    Also records the response type and time and sends them along to Riemann.

    If the request was for a section of the site we want to track, sends that
    information to Riemann as well.

    """
    def process_request(self, request):
        request.init_time = time.time()
        Meter('requests.started').inc()

        # Tracking the section of the site isn't trivial, because sometimes we
        # have the language prefix, like "/en/foo".
        paths = request.path.lstrip('/').split('/')[:2]
        p1 = paths[0] if len(paths) >= 1 else None
        p2 = paths[1] if len(paths) >= 2 else None

        if p1 in SECTIONS:
            request._metrics_section = SECTIONS[paths[0]]
        elif p2 in SECTIONS:
            request._metrics_section = SECTIONS[paths[1]]
        else:
            request._metrics_section = None

        if request._metrics_section:
            label = 'site-sections.%s-response-time' % request._metrics_section
            Meter(label).inc()

        return None

    def process_response(self, request, response):
        if hasattr(request, "init_time"):
            delta = time.time() - request.init_time
            ms = delta * 1000

            Meter('requests.completed').inc()

            try:
                response_type = response.status_code / 100 * 100
            except:
                response_type = 'unknown'
            Meter('requests.response-types.%s' % response_type).inc()

            response.set_cookie('response_time', str(ms))

            ManualTimer('response-time').record(ms)

            if request._metrics_section:
                label = 'site-sections.%s-response-time' % request._metrics_section
                ManualTimer(label).record(ms)

        return response

class P3PHeaderMiddleware(object):
    def process_response(self, request, response):
        response['P3P'] = settings.P3P_COMPACT
        return response


# Got this from CsrfViewMiddleware
# Use the system (hardware-based) random number generator if it exists.
if hasattr(random, 'SystemRandom'):
    randrange = random.SystemRandom().randrange
else:
    randrange = random.randrange

_MAX_CSRF_KEY = 18446744073709551616L     # 2 << 63

UUID_COOKIE_NAME = getattr(settings, 'UUID_COOKIE_NAME', 'unisub-user-uuid')
UUID_COOKIE_DOMAIN = getattr(settings, 'UUID_COOKIE_DOMAIN', None)

def _get_new_csrf_key():
    return sha_constructor("%s%s"
                % (randrange(0, _MAX_CSRF_KEY), settings.SECRET_KEY)).hexdigest()

class UserUUIDMiddleware(object):
    def process_request(self, request):
        try:
            request.browser_id = request.COOKIES[UUID_COOKIE_NAME]
        except KeyError:
            # No cookie or it is empty, so create one.  This will be sent with the next
            # response.
            if not hasattr(request, 'browser_id'):
                request.browser_id = _get_new_csrf_key()

    def process_response(self, request, response):
        if hasattr(request, 'browser_id'):
            browser_id = request.browser_id
            if request.COOKIES.get(UUID_COOKIE_NAME) != browser_id:
                max_age = 60 * 60 * 24 * 365
                response.set_cookie(
                    UUID_COOKIE_NAME,
                    browser_id,
                    max_age=max_age,
                    expires=cookie_date(time.time() + max_age),
                    domain=UUID_COOKIE_DOMAIN)
        # Content varies with the CSRF cookie, so set the Vary header.
        patch_vary_headers(response, ('Cookie',))
        return response


# I'm so sorry about this.
class MetricsCursorWrapper(_CursorWrapper):
    def _query_type(self, query):
        if not query:
            return 'UNKNOWN'
        elif query.startswith('SELECT COUNT(*) '):
            return 'COUNT'
        elif query.startswith('SELECT '):
            return 'SELECT'
        elif query.startswith('DELETE '):
            return 'DELETE'
        elif query.startswith('INSERT '):
            return 'INSERT'
        elif query.startswith('UPDATE '):
            return 'UPDATE'
        else:
            return 'OTHER'

    def execute(self, query, params=None):
        op = self._query_type(query)

        with Timer('db-query-time'):
            with Timer('db-query-time.%s' % op):
                return super(MetricsCursorWrapper, self).execute(query, params)

    def executemany(self, query, params_list):
        op = self._query_type(query)
        start = time.time()

        try:
            return super(MetricsCursorWrapper, self).executemany(query, params_list)
        finally:
            end = time.time()
            delta = end - start
            ms = delta * 1000

            # This is an ugly hack to get at least a rough measurement of query
            # times for executemany() queries.
            ms_per_query = ms / len(params_list)

            for _ in xrange(len(params_list)):
                ManualTimer('db-query-time').record(ms_per_query)
                ManualTimer('db-query-time.%s' % op).record(ms_per_query)

django.db.backends.mysql.base.CursorWrapper = MetricsCursorWrapper


# http://www.randallmorey.com/blog/2010/feb/17/django-cache-sessions-and-google-analytics/
class StripGoogleAnalyticsCookieMiddleware(object):
    strip_re = re.compile(r'(__utm.=.+?(?:; |$))')
    def process_request(self, request):
        try:
            cookie = self.strip_re.sub('', request.META['HTTP_COOKIE'])
            request.META['HTTP_COOKIE'] = cookie
        except:
            pass

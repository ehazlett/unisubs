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
from __future__ import with_statement

import os, sys, string, random
from datetime import datetime
from functools import wraps
import time

import fabric.colors as colors
from fabric.api import run, sudo, env, cd, local as _local, abort
from fabric.context_managers import settings, hide
from fabric.utils import fastprint


ADD_TIMESTAMPS = """ | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' """
WRITE_LOG = """ | tee /tmp/%s.log """

# Output Management -----------------------------------------------------------
PASS_THROUGH = ('sudo password: ', 'Sorry, try again.')
class CustomFile(file):
    def __init__(self, *args, **kwargs):
        self.log = ""
        return super(CustomFile, self).__init__(*args, **kwargs)

    def _record(self, s):
        self.log = self.log[-255:] + s.lower()

        if any(pt in self.log for pt in PASS_THROUGH):
            sys.__stdout__.write('\n\n' + self.log.rsplit('\n', 1)[-1])
            self.log = ""

    def write(self, s, *args, **kwargs):
        self._record(s)
        return super(CustomFile, self).write(s, *args, **kwargs)


_out_log = CustomFile('fabric.log', 'w')
class Output(object):
    """A context manager for wrapping up standard output/error nicely.

    Basic usage:

        with Output("Performing task foo"):
            ...

    This will print a nice header, redirect all output (except for password
    prompts) to a log file, and then unredirect the output when it's finished.

    If you need to override the redirection inside the body, you can use the
    fastprint and fastprintln methods on the manager:

        with Output("Performing task foo") as out:
            ...
            if something:
                out.fastprintln('Warning: the disk is getting close to full.')
            ...

    WARNING: Do not nest 'with Output(...)' blocks!  I have no idea how that
    will behave at the moment.  This includes calling a function that contains
    an Output block from within an Output block.

    TODO: Fix this.

    """
    def __init__(self, message=""):
        self.message = message

    def __enter__(self):
        if self.message:
            fastprint(colors.white(self.message.ljust(60) + " -> ", bold=True))

        sys.stdout = _out_log
        sys.stderr = _out_log

        if self.message:
            fastprint("\n\n")
            fastprint(colors.yellow("+" + "-" * 78 + "+\n", bold=True))
            fastprint(colors.yellow("| " + self.message.ljust(76) + " |\n", bold=True))
            fastprint(colors.yellow("+" + "-" * 78 + "+\n", bold=True))

        return self

    def __exit__(self, type, value, tb):
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        if type is None:
            fastprint(colors.green("OK\n", bold=True))
        else:
            fastprint(colors.red("FAILED\n", bold=True))
            fastprint(colors.red(
                "\nThere was an error.  "
                "See ./fabric.log for the full transcript of this run.\n",
                bold=True))

    def fastprint(self, s):
        sys.stdout = sys.__stdout__
        fastprint(s)
        sys.stdout = _out_log

    def fastprintln(self, s):
        self.fastprint(s + '\n')

def _lock(*args, **kwargs):
    """
    Creates a temporary "lock" file to prevent concurrent deployments

    """
    with settings(hide('warnings', 'running', 'stdout', 'stderr'), warn_only=True):
        res = run('cat {0}'.format(env.deploy_lock))
    if res.succeeded:
        abort('Another operation is currently in progress: {0}'.format(res))
    else:
        task = kwargs.get('task', '')
        with settings(hide('running', 'stdout', 'stderr'), warn_only=True):
            run('echo "{0} : {1}" > {2} {3}'.format(datetime.now(), env.user, env.deploy_lock, task))

def _unlock(*args, **kwargs):
    """
    Removes deploy lock

    """
    with settings(hide('running', 'stdout', 'stderr'), warn_only=True):
        run('rm -f {0}'.format(env.deploy_lock))

def remove_lock():
    """
    Removes lock from hosts (in the event of a failed task)

    """
    with Output('Removing lock'):
        _execute_on_all_hosts(lambda dir: _unlock(dir))

def lock_required(f):
    """
    Decorator for the lock / unlock functionality

    """
    @wraps(f)
    def decorated(*args, **kwargs):
        _execute_on_all_hosts(lambda dir: _lock(dir, task=f.func_name))
        out = None
        try:
            out = f(*args, **kwargs)
        except:
            pass
        finally:
            _execute_on_all_hosts(lambda dir: _unlock(dir))
        return out
    return decorated

def local(*args, **kwargs):
    '''Override Fabric's local() to facilitate output logging.'''
    capture = kwargs.get('capture')

    kwargs['capture'] = True
    out = _local(*args, **kwargs)

    if capture:
        return out
    else:
        print out


#:This environment is responsible for:
#:
#:- syncdb on all environment
#:- memechached and solr for `dev`
#:- media compilation on all environments
DEV_HOST = 'dev.universalsubtitles.org:2191'


def _create_env(username, hosts, hostnames_squid_cache, s3_bucket,
                installation_dir, static_dir, name, git_branch,
                memcached_bounce_cmd,
                admin_dir, admin_host, celeryd_host, celeryd_proj_root,
                separate_uslogging_db=False,
                celeryd_start_cmd="",
                celeryd_stop_cmd="",
                celeryd_bounce_cmd="",
                web_dir=None):
    env.user = username
    env.web_hosts = hosts
    env.hosts = []
    env.hostnames_squid_cache = hostnames_squid_cache
    env.s3_bucket = s3_bucket
    env.deploy_lock = '/tmp/.unisubs_deploy_dev'.format(git_branch)
    env.web_dir = web_dir or '/var/www/{0}'.format(installation_dir)
    env.static_dir = static_dir
    env.installation_name = name
    env.git_branch = git_branch
    env.memcached_bounce_cmd = memcached_bounce_cmd
    env.admin_dir = admin_dir
    env.admin_host = admin_host
    env.separate_uslogging_db = separate_uslogging_db
    env.celeryd_start_cmd=celeryd_start_cmd
    env.celeryd_stop_cmd=celeryd_stop_cmd
    env.celeryd_bounce_cmd=celeryd_bounce_cmd
    env.celeryd_host = celeryd_host
    env.celeryd_proj_root = celeryd_proj_root

def staging(username):
    with Output("Configuring task(s) to run on STAGING"):
        _create_env(username              = username,
                    hosts                 = ['pcf-us-staging3.pculture.org:2191',
                                            'pcf-us-staging4.pculture.org:2191'],
                    hostnames_squid_cache = ['staging.universalsubtitles.org',
                                             'staging.amara.org'
                                             ],
                    s3_bucket             = 's3.staging.universalsubtitles.org',
                    installation_dir      = 'universalsubtitles.staging',
                    static_dir            = '/var/static/staging',
                    name                  = 'staging',
                    git_branch            = 'staging',
                    memcached_bounce_cmd  = '/etc/init.d/memcached restart',
                    admin_dir             = '/usr/local/universalsubtitles.staging',
                    admin_host            = 'pcf-us-adminstg.pculture.org:2191',
                    celeryd_host          = 'pcf-us-adminstg.pculture.org:2191',
                    celeryd_proj_root     = 'universalsubtitles.staging',
                    separate_uslogging_db = True,
                    celeryd_start_cmd     = "/etc/init.d/celeryd start",
                    celeryd_stop_cmd      = "/etc/init.d/celeryd stop",
                    celeryd_bounce_cmd    = "/etc/init.d/celeryd restart &&  /etc/init.d/celeryevcam start")

def dev(username):
    with Output("Configuring task(s) to run on DEV"):
        _create_env(username              = username,
                    hosts                 = ['dev.universalsubtitles.org:2191'],
                    hostnames_squid_cache = ['dev.universalsubtitles.org',
                                             'dev.amara.org'
                                             ],
                    s3_bucket             = None,
                    installation_dir      = 'universalsubtitles.dev',
                    static_dir            = '/var/www/universalsubtitles.dev',
                    name                  = 'dev',
                    git_branch            = 'dev',
                    memcached_bounce_cmd  = '/etc/init.d/memcached restart',
                    admin_dir             = None,
                    admin_host            = 'dev.universalsubtitles.org:2191',
                    celeryd_host          = DEV_HOST,
                    celeryd_proj_root     = 'universalsubtitles.dev',
                    separate_uslogging_db = False,
                    celeryd_start_cmd     = "/etc/init.d/celeryd.dev start",
                    celeryd_stop_cmd      = "/etc/init.d/celeryd.dev stop",
                    celeryd_bounce_cmd    = "/etc/init.d/celeryd.dev restart &&  /etc/init.d/celeryevcam.dev start")

def production(username):
    with Output("Configuring task(s) to run on PRODUCTION"):
        _create_env(username              = username,
                    hosts                 = ['pcf-us-cluster3.pculture.org:2191',
                                             'pcf-us-cluster4.pculture.org:2191',
                                             'pcf-us-cluster5.pculture.org:2191',
                                             'pcf-us-cluster8.pculture.org:2191',
                                             'pcf-us-cluster9.pculture.org:2191',
                                             'pcf-us-cluster10.pculture.org:2191',
                                             ],
                    hostnames_squid_cache = ['www.universalsubtitles.org',
                                             'www.amara.org',
                                             'universalsubtitles.org',
                                             'amara.org'
                                             ],
                    s3_bucket             = 's3.www.universalsubtitles.org',
                    installation_dir      = 'universalsubtitles',
                    static_dir            = '/var/static/production',
                    name                  =  None,
                    git_branch            = 'production',
                    memcached_bounce_cmd  = '/etc/init.d/memcached restart',
                    admin_dir             = '/usr/local/universalsubtitles',
                    admin_host            = 'pcf-us-admin.pculture.org:2191',
                    celeryd_host          = 'pcf-us-admin.pculture.org:2191',
                    celeryd_proj_root     = 'universalsubtitles',
                    separate_uslogging_db = True,
                    celeryd_start_cmd     = "/etc/init.d/celeryd start",
                    celeryd_stop_cmd      = "/etc/init.d/celeryd stop",
                    celeryd_bounce_cmd    = "/etc/init.d/celeryd restart  && /etc/init.d/celeryevcam start ")

def temp(username):
    with Output("Configuring task(s) to run on TEMP"):
        _create_env(username              = username,
                    hosts                 = ['pcf-us-tmp1.pculture.org:2191',],
                    hostnames_squid_cache = ['tmp.universalsubtitles.org',
                                             'tmp.amara.org'
                                             ],
                    s3_bucket             = 's3.temp.universalsubtitles.org',
                    installation_dir      = 'universalsubtitles.staging',
                    static_dir            = '/var/static/tmp',
                    name                  = 'staging',
                    git_branch            = 'staging',
                    memcached_bounce_cmd  = '/etc/init.d/memcached-staging restart',
                    admin_dir             = '/usr/local/universalsubtitles.staging',
                    admin_host            = 'pcf-us-admintmp.pculture.org:2191',
                    celeryd_host          = 'pcf-us-admintmp.pculture.org:2191',
                    celeryd_proj_root     = 'universalsubtitles.staging',
                    separate_uslogging_db = True,
                    celeryd_start_cmd     = "/etc/init.d/celeryd.staging start",
                    celeryd_stop_cmd      = "/etc/init.d/celeryd.staging stop",
                    celeryd_bounce_cmd    = "/etc/init.d/celeryd.staging restart &&  /etc/init.d/celeryevcam.staging start")

def nf(username):
    with Output("Configuring task(s) to run on NF env"):
        _create_env(username              = username,
                    hosts                 = ['nf.universalsubtitles.org:2191'],
                    hostnames_squid_cache = ['nf.universalsubtitles.org',
                                             'nf.amara.org'
                                             ],
                    s3_bucket             = 's3.nf.universalsubtitles.org',
                    installation_dir      = 'universalsubtitles.nf',
                    static_dir            = '/var/static/nf',
                    name                  = 'nf',
                    git_branch            = 'x-nf',
                    memcached_bounce_cmd  = '/etc/init.d/memcached restart',
                    admin_dir             = '/usr/local/universalsubtitles.nf',
                    admin_host            = 'pcf-us-adminnf.pculture.org:2191',
                    celeryd_host          = 'pcf-us-adminnf.pculture.org:2191',
                    celeryd_proj_root     = 'universalsubtitles.nf',
                    separate_uslogging_db = True,
                    celeryd_start_cmd     = "/etc/init.d/celeryd start",
                    celeryd_stop_cmd      = "/etc/init.d/celeryd stop",
                    celeryd_bounce_cmd    = "/etc/init.d/celeryd restart &&  /etc/init.d/celeryevcam start")

@lock_required
def syncdb():
    """Run python manage.py syncdb for the main and logging databases"""

    with Output("Syncing database"):
        env.host_string = DEV_HOST
        with cd(os.path.join(env.static_dir, 'unisubs')):
            _git_pull()
            run('{0}/env/bin/python manage.py syncdb '
                '--settings=unisubs_settings'.format(env.static_dir))
            if env.separate_uslogging_db:
                run('{0}/env/bin/python manage.py syncdb '
                    '--database=uslogging --settings=unisubs_settings'.format(
                        env.static_dir))

@lock_required
def migrate(app_name=''):
    with Output("Performing migrations"):
        env.host_string = DEV_HOST
        with cd(os.path.join(env.static_dir, 'unisubs')):
            _git_pull()
            if env.separate_uslogging_db:
                run('{0}/env/bin/python manage.py migrate uslogging '
                    '--database=uslogging --settings=unisubs_settings'.format(
                        env.static_dir))

            manage_cmd = 'yes no | {0}/env/bin/python -u manage.py migrate {1} --settings=unisubs_settings 2>&1'.format(env.static_dir, app_name)
            timestamp_cmd = ADD_TIMESTAMPS.replace("'", r"\'")
            log_cmd = WRITE_LOG % 'database_migrations'

            cmd = (
                "screen sh -c $'" +
                    manage_cmd +
                    timestamp_cmd +
                    log_cmd +
                "'"
            )
            run(cmd)

def run_command(command):
    '''Run a python manage.py command'''
    cmdname = command.split(' ', 1)[0]
    with Output("Running python manage.py {0} ...".format(cmdname)):
        env.host_string = DEV_HOST
        with cd(os.path.join(env.static_dir, 'unisubs')):
            _git_pull()
            run('{0}/env/bin/python manage.py {1} '
                '--settings=unisubs_settings'.format(env.static_dir, command))

def _run_shell(base_dir, command, is_sudo=False):
    if is_sudo:
        f = sudo
    else:
        f = run
    with cd(os.path.join(base_dir, 'unisubs')):
        f('sh ../env/bin/activate && %s' % command)

def run_shell(command, is_sudo=False):
    """Run the given command inside the virtual env for each host/environment."""

    with Output("Running '{0}' on all hosts".format(command)):
        _execute_on_all_hosts(lambda dir: _run_shell(dir, command, bool(is_sudo)))

def migrate_fake(app_name):
    '''Fake a migration to 0001 for the specified app

    Unfortunately, one must do this when moving an app to South for the first
    time.

    See http://south.aeracode.org/docs/convertinganapp.html and
    http://south.aeracode.org/ticket/430 for more details. Perhaps this will be
    changed in a subsequent version, but now we're stuck with this solution.

    '''
    with Output("Faking migration for {0}".format(app_name)):
        env.host_string = DEV_HOST
        with cd(os.path.join(env.static_dir, 'unisubs')):
            run('yes no | {0}/env/bin/python manage.py migrate {1} 0001 --fake --settings=unisubs_settings'.format(env.static_dir, app_name))

@lock_required
def refresh_db():
    # Should really be checking for 'production'
    if env.installation_name is None:
        Output("Cannot refresh production database")
        return

    with Output("Refreshing database"):
        add_disabled()
        stop_celeryd()

        env.host_string = env.web_hosts[0]
        sudo('/scripts/amara_reset_db.sh {0}'.format(env.installation_name))
        sudo('/scripts/amara_refresh_db.sh {0}'.format(env.installation_name))
        promote_django_admins()
        bounce_memcached()
        run('{0}/env/bin/python manage.py fix_static_files '
            '--settings=unisubs_settings'.format(env.static_dir))

        start_celeryd()
        removed_disabled()

def _execute_on_all_hosts(cmd):
    # horrible hack to not have dev_host be called twice ; this needs refactoring
    dev_host = False
    for host in env.web_hosts:
        if host == DEV_HOST: dev_host = True
        env.host_string = host
        cmd(env.web_dir)
    if not dev_host:
        env.host_string = DEV_HOST
        cmd(env.static_dir)
    if env.admin_dir is not None:
        env.host_string = env.admin_host
        cmd(env.admin_dir)


def _switch_branch(dir, branch_name):
    with cd(os.path.join(dir, 'unisubs')):
        _git_pull()
        run('git fetch')
        # the following command will harmlessly fail if branch already exists.
        # don't be intimidated by the one-line message.
        with settings(warn_only=True):
            run('git branch --track {0} origin/{0}'.format(branch_name))
            run('git checkout {0}'.format(branch_name))
        _git_pull()

def switch_branch(branch_name):
    """Switch the unisubs repository to the given git branch"""

    with Output("Switching to branch {0}".format(branch_name)):
        _execute_on_all_hosts(lambda dir: _switch_branch(dir, branch_name))


def _remove_pip_package(base_dir, package_name):
    with cd(os.path.join(base_dir, 'unisubs', 'deploy')):
        run('yes y | {0}/env/bin/pip uninstall {1}'.format(base_dir, package_name), pty=True)
        #_clear_permissions(os.path.join(base_dir, 'env'))

def remove_pip_package(package_egg_name):
    with Output("Removing pip package '{0}'".format(package_egg_name)):
        _execute_on_all_hosts(lambda dir: _remove_pip_package(dir, package_egg_name))

def _update_environment(base_dir, flags=''):
    with cd(os.path.join(base_dir, 'unisubs', 'deploy')):
        _git_pull()
        run('export PIP_REQUIRE_VIRTUALENV=true')
        # see http://lincolnloop.com/blog/2010/jul/1/automated-no-prompt-deployment-pip/
        run('yes i | {0}/env/bin/pip install {1} -r requirements.txt'.format(base_dir, flags), pty=True)
        #_clear_permissions(os.path.join(base_dir, 'env'))

def _update_environment_parallel(base_dir, flags=''):
    """
    This is the new way to build the virtualenv ; it will completely re-build
    each time.  However, this must also be done only when parallel tasks
    are implemented as this takes a long time to run on staging and production.

    """
    with cd(os.path.join(base_dir, 'unisubs', 'deploy')):
        _git_pull()
        env_dir = '{0}/env'.format(base_dir)
        tmp_env_dir = '{0}/env_{1}'.format(base_dir, int(time.time()))
        # gather existing envs
        envs = run('find {0}/ -type d -name "env_*"'.format(base_dir))
        run('export PIP_REQUIRE_VIRTUALENV=true')
        # create new venv for fresh environment
        run('virtualenv --no-site-packages {0}'.format(tmp_env_dir))
        # see http://lincolnloop.com/blog/2010/jul/1/automated-no-prompt-deployment-pip/
        res = run('yes i | {0}/bin/pip install {1} -r requirements.txt'.format(tmp_env_dir, flags), pty=True)
        # check if pip failed and abort if so
        if res.failed:
            # if fail ; abort
            abort('Error occurred during pip install: {0}'.format(res))
        # all good ; overwrite symlink to prod
        run('if [ -e {1} ]; then rm -rf {1}; fi ; ln -sf {0} {1}'.format(tmp_env_dir, env_dir))
        # remove previous envs
        run('rm -rf {0}'.format(' '.join(envs.split('\n'))))
        #_clear_permissions(os.path.join(base_dir, 'env'))

@lock_required
def update_environment(flags=''):
    with Output("Updating virtualenv"):
        _execute_on_all_hosts(lambda dir: _update_environment(dir, flags))

def _clear_permissions(dir):
    sudo('chgrp pcf-web -R {0}'.format(dir))
    sudo('chmod g+w -R {0}'.format(dir))

def clear_environment_permissions():
    with Output("Clearing environment permissions"):
        _execute_on_all_hosts(
            lambda dir: _clear_permissions(os.path.join(dir, 'env')))

def clear_permissions():
    with Output("Clearing permissions"):
        for host in env.web_hosts:
            env.host_string = host
            _clear_permissions('{0}/unisubs'.format(env.web_dir))


def _git_pull():
    run('git checkout --force')
    run('git pull --ff-only')
    run('chgrp pcf-web -R .git 2> /dev/null; /bin/true')
    run('chmod g+w -R .git 2> /dev/null; /bin/true')
    _clear_permissions('.')

def _git_checkout(commit, as_sudo=False):
    cmd = run
    if as_sudo:
        cmd = sudo
    cmd('git fetch')
    cmd('git checkout --force %s' % commit)
    cmd('chgrp pcf-web -R .git 2> /dev/null; /bin/true')
    cmd('chmod g+w -R .git 2> /dev/null; /bin/true')
    _clear_permissions('.')

def _git_checkout_branch_and_reset(commit, branch='master', as_sudo=False):
    cmd = run
    if as_sudo:
        cmd = sudo
    cmd('git fetch')
    cmd('git checkout %s' % branch)
    cmd('git reset --hard %s' % commit)
    cmd('chgrp pcf-web -R .git 2> /dev/null; /bin/true')
    cmd('chmod g+w -R .git 2> /dev/null; /bin/true')
    _clear_permissions('.')


def _get_optional_repo_version(dir, repo):
    '''Find the optional repo version by looking at its file in optional/.'''
    with cd(os.path.join(dir, 'unisubs', 'optional')):
        return run('cat {0}'.format(repo))


def _reload_app_server(dir=None):
    """
    Reloading the app server will both make sure we have a
    valid commit guid (by running the create_commit_file)
    and also that we make the server reload code (currently
    with mod_wsgi this is touching the wsgi file)
    """
    with cd('{0}/unisubs'.format(dir or env.web_dir)):
        run('python deploy/create_commit_file.py')
        run('touch deploy/unisubs.wsgi')

def reload_app_servers():
    with Output("Reloading application servers"):
        for host in env.web_hosts:
            env.host_string = host
            _reload_app_server()


# Maintenance Mode
def add_disabled():
    with Output("Putting the site into maintenance mode"):
        for host in env.web_hosts:
            env.host_string = host
            run('touch {0}/unisubs/disabled'.format(env.web_dir))

def remove_disabled():
    with Output("Taking the site out of maintenance mode"):
        for host in env.web_hosts:
            env.host_string = host
            run('rm {0}/unisubs/disabled'.format(env.web_dir))


def _update_integration(dir, as_sudo=True):
    '''
    Actually update the integration repo on a single host.
    Has to be run as root, else all users on all servers must have
    the right key for the private repo.
    '''

    with cd(os.path.join(dir, 'unisubs', 'unisubs-integration')):
        with settings(warn_only=True):
            _git_checkout_branch_and_reset(
                _get_optional_repo_version(dir, 'unisubs-integration'),
                branch=env.git_branch,
                as_sudo=as_sudo
            )

def update_integration():
    '''Update the integration repo to the version recorded in the site repo.

    At the moment it is assumed that the optional/unisubs-integration file
    exists, and that the unisubs-integration repo has already been cloned down.

    The file should contain the commit hash and nothing else.

    TODO: Run this from update_web automatically

    '''
    with Output("Updating nested unisubs-integration repositories"):
        _execute_on_all_hosts(_update_integration)

def _notify(subj, msg, audience='ehazlett@pculture.org'):
    mail_from_host = 'pcf-us-dev.pculture.org:2191'

    old_host = env.host_string
    env.host_string = mail_from_host
    run("echo '{1}' | mailx -s '{0}' {2}".format(subj, msg, audience))
    env.host_string = old_host

def update_web():
    """
    This is how code gets reloaded:

    - Checkout code on the auxiliary server ADMIN whost
    - Checkout the latest code on all appservers
    - Remove all pyc files from app servers
    - Bounce celeryd, memcached , test services
    - Reload app code (touch wsgi file)

    Until we implement the checking out code to an isolated dir
    any failure on these steps need to be fixed or will result in
    breakage
    """
    with Output("Updating the main unisubs repositories"):
        if env.admin_dir is not None:
            env.host_string = env.admin_host
            with cd(os.path.join(env.admin_dir, 'unisubs')):
                _git_pull()
                _update_integration(env.admin_dir)

    with Output("Updating the unisubs-integration repositories"):
        for host in env.web_hosts:
            env.host_string = host
            with cd('{0}/unisubs'.format(env.web_dir)):
                _git_pull()
                _update_integration(env.web_dir)
                with settings(warn_only=True):
                    run("find . -name '*.pyc' -print0 | xargs -0 rm")

    bounce_celeryd()
    bounce_memcached()
    test_services()
    reload_app_servers()

    # Workaround that 'None' implies 'production'
    installation_name = 'production' if env.installation_name is None else env.installation_name

    if env.installation_name != 'dev' or env.user != 'jenkins':
        _notify("Amara {0} deployment".format(env.installation_name), "Deployed by {0} to {1} at {2} UTC".format(env.user,  installation_name, datetime.utcnow()))

# Services
def update_solr_schema():
    '''Update the Solr schema and rebuild the index.

    The rebuilding will be done asynchronously with screen and an email will
    be sent when it finishes.

    '''
    with Output("Updating Solr schema (and rebuilding the index)"):
        if env.admin_dir:
            # staging and production
            env.host_string = env.admin_host
            dir = env.admin_dir
            python_exe = '{0}/env/bin/python'.format(env.admin_dir)
            with cd(os.path.join(dir, 'unisubs')):
                _git_pull()
                run('{0} manage.py build_solr_schema --settings=unisubs_settings > /etc/solr/conf/{1}/conf/schema.xml'.format(
                        python_exe,
                        'production' if env.installation_name is None else 'staging'))
                run('{0} manage.py reload_solr_core --settings=unisubs_settings'.format(python_exe))
        else:
            # dev
            env.host_string = DEV_HOST
            dir = env.web_dir
            python_exe = '{0}/env/bin/python'.format(env.web_dir)
            with cd(os.path.join(dir, 'unisubs')):
                _git_pull()
                run('{0} manage.py build_solr_schema --settings=unisubs_settings > /etc/solr/conf/main/conf/schema.xml'.format(python_exe))
                run('{0} manage.py build_solr_schema --settings=unisubs_settings > /etc/solr/conf/testing/conf/schema.xml'.format(python_exe))
            sudo('service tomcat6 restart')

        # Fly, you fools!

        managepy_file = os.path.join(dir, 'unisubs', 'manage.py')

        # The -u here is for "unbuffered" so the lines get outputted immediately.
        manage_cmd = '%s -u %s rebuild_index_ordered --noinput --settings=unisubs_settings 2>&1' % (python_exe, managepy_file)
        mail_cmd = ' | mail -s Solr_index_rebuilt_on_%s universalsubtitles-dev@pculture.org' % env.host_string
        log_cmd = WRITE_LOG % 'solr_reindexing'

        # The single quotes in the ack command needs to be escaped, because
        # we're in a single quoted ANSI C-style string from the sh -c in the
        # screen command.
        #
        # We can't use a double quoted string for the sh -c call because of the
        # $0 in the ack script.
        timestamp_cmd = ADD_TIMESTAMPS.replace("'", r"\'")

        cmd = (
            "screen -d -m sh -c $'" +
                manage_cmd +
                timestamp_cmd +
                log_cmd +
                mail_cmd +
            "'"
        )

        run(cmd, pty=False)

def bounce_memcached():
    '''Bounce the memcached server (purging the cache).

    Should be done at the end of each deploy.

    '''
    with Output("Bouncing memcached"):
        if env.admin_dir:
            env.host_string = env.admin_host
        else:
            env.host_string = DEV_HOST
        sudo(env.memcached_bounce_cmd, pty=False)


def _do_celeryd(cmd):
    if env.admin_dir:
        env.host_string = env.admin_host
    else:
        env.host_string = DEV_HOST
    if bool(cmd):
        sudo(cmd, pty=False)

def start_celeryd():
    """Start the celeryd workers

    """
    with Output("Starting celeryd"):
        _do_celeryd(env.celeryd_start_cmd)

def stop_celeryd():
    """Stop the celeryd workers safely

    This should allow them to finish the task they're working on.

    """
    with Output("Stopping celeryd"):
        _do_celeryd(env.celeryd_stop_cmd)

def bounce_celeryd():
    """Bounce the celeryd workers safely

    This should allow them to finish the task they're working on before
    restarting.

    """
    with Output("Bouncing celeryd"):
        _do_celeryd(env.celeryd_bounce_cmd)


def test_celeryd():
    """Ensure celeryd is running

    Only checks for the presence of a running process -- not whether that
    process is still responding to requests and such.

    TODO: Perform a stricter check.

    """
    with Output("Testing Celery"):
        env.host_string = env.celeryd_host
        output = run('ps aux | grep "%s/unisubs/manage\.py.*celeryd.*-B" | grep -v grep' % env.celeryd_proj_root)
        assert len(output.split('\n'))

def test_services():
    """Test Celery, memcached, and assorted other services"""
    test_memcached()
    test_celeryd()
    with Output("Testing other services"):
        for host in env.web_hosts:
            env.host_string = host
            with cd(os.path.join(env.web_dir, 'unisubs')):
                run('{0}/env/bin/python manage.py test_services --settings=unisubs_settings'.format(
                    env.web_dir))

def test_memcached():
    """Ensure memcached is running, working, and sane"""
    with Output("Testing memcached"):
        alphanum = string.letters+string.digits
        host_set = set([(h, env.web_dir,) for h in env.web_hosts])
        if env.admin_dir:
            host_set.add((env.admin_host, env.admin_dir,))
        for host in host_set:
            random_string = ''.join(
                [alphanum[random.randint(0, len(alphanum)-1)]
                for i in xrange(12)])
            env.host_string = host[0]
            with cd(os.path.join(host[1], 'unisubs')):
                run('../env/bin/python manage.py set_memcached {0} --settings=unisubs_settings'.format(
                    random_string))
            other_hosts = host_set - set([host])
            for other_host in other_hosts:
                env.host_string = other_host[0]
                output = ''
                with cd(os.path.join(other_host[1], 'unisubs')):
                    output = run('../env/bin/python manage.py get_memcached --settings=unisubs_settings')
                if output.find(random_string) == -1:
                    raise Exception('Machines {0} and {1} are using different memcached instances'.format(
                            host[0], other_host[0]))


# Static Media
def _update_static(dir, compilation_level):
    with cd(os.path.join(dir, 'unisubs')):
        media_dir = '{0}/unisubs/media/'.format(dir)
        python_exe = '{0}/env/bin/python'.format(dir)
        _git_pull()
        _update_integration(dir)
        _clear_permissions(media_dir)
        run('{0} manage.py  compile_media --compilation-level={1} --settings=unisubs_settings'.format(python_exe, compilation_level))

def _save_embedjs_on_app_servers():
    '''
    For mozilla, we'll craft a special url that servers the embed.js file
    straight from squid in order to be able to set the CORS heades
    (amazon's s3 does not allow that header to be set)
    '''
    # to find the url, we must revsolve the current STATIC_ROOT
    if env.admin_dir:
        env.host_string = env.admin_host
        base_dir = env.admin_dir
    else:
        env.host_string = DEV_HOST
        base_dir = env.web_dir
    # we need to update the rep for the admin host, else
    # we'll end up with an old STATIC_URL, we should fix this with
    # the corect layouts for each server (and stop all special casing
    # for each env)
    with cd(os.path.join(base_dir, 'unisubs')):
        _git_pull()

    with cd(os.path.join(base_dir, 'unisubs')):
        python_exe = '{0}/env/bin/python'.format(base_dir)
        res = run('{0} manage.py  get_settings_values STATIC_URL_BASE --single-host --settings=unisubs_settings'.format(python_exe))
        media_url = res.replace("\n", "").strip()
        url = "%sembed.js" % media_url
    for host in env.web_hosts:
        # save STATIC_URL/embed.js in the local file system so squid can serve it
        final_path = os.path.join(env.web_dir, "unisubs", "media", "js", "embed.js")
        env.host_string = host
        cmd_str = "curl --compressed --silent %s > %s" % (url, final_path)
        run(cmd_str)
        # now  purge the squid cache
        for hostname_in_cache in env.hostnames_squid_cache:
           sudo('/usr/bin/squidclient -p  80 -m PURGE  http://{0}/unisubs/media/js/embed.js'.format(hostname_in_cache))
           sudo('/usr/bin/squidclient -p 443 -m PURGE https://{0}/unisubs/media/js/embed.js'.format(hostname_in_cache))

def update_static(compilation_level='ADVANCED_OPTIMIZATIONS'):
    """Recompile static media and upload the results to S3"""

    with Output("Recompiling and uploading static media"):
        env.host_string = DEV_HOST
        if env.s3_bucket is not None:
            with cd(os.path.join(env.static_dir, 'unisubs')):
                _update_static(env.static_dir, compilation_level)
                python_exe = '{0}/env/bin/python'.format(env.static_dir)
                run('{0} manage.py  send_to_s3 --settings=unisubs_settings'.format(python_exe))
        else:
            _update_static(env.web_dir, compilation_level)
        _save_embedjs_on_app_servers()

@lock_required
def update():
    update_static()
    update_web()

def _promote_django_admins(dir, email=None, new_password=None, userlist_path=None):
    with cd(os.path.join(dir, 'unisubs')):
        python_exe = '{0}/env/bin/python'.format(dir)
        args = ""
        if email is not None:
            args += "--email=%s" % (email)
        if new_password is not None:
            args += "--pass=%s" % (new_password)
        if userlist_path is not None:
            args += "--userlist-path=%s" % (userlist_path)
        cmd_str ='{0} manage.py promote_admins {1} --settings=unisubs_settings'.format(python_exe, args)
        run(cmd_str)

def promote_django_admins(email=None, new_password=None, userlist_path=None):
    """
    Make sure identified users are can access the admin site.
    If new_password is provided will reset the user's password
    You can pass either one user email, or a path to a json file with
    'email', 'new_password' objects.

    Examples:
    fab staging:serveruser promote_django_admins:email=arthur@example.com
    """
    env.host_string = env.web_hosts[0]
    return _promote_django_admins(env.web_dir, email, new_password, userlist_path)

@lock_required
def update_translations():
    """Update the translations

    What it does:

    - Pushes new strings in english and new languages to transifex.
    - Pulls all changes from transifex, for all languages.
    - Adds only the *.mo and *.po files to the index area.
    - Commits to the rep with a predefined message.
    - Pushes to origin.

    Caveats:

    - If any of these steps fail, it will stop execution.
    - At some point, this is pretty much about syncing two repos, so conflicts
      can appear.
    - This assumes that we do not edit translation .po files on the file system.
    - This assumes that we want to push with a "git push".
    - You must have the  .transifexrc file into your home (this has auth
      credentials is stored outside of source control).

    """
    with Output("Updating translations"):
        run('cd {0} && sh update_translations.sh'.format(os.path.dirname(__file__)))


def _test_email(dir, to_address):
    with cd(os.path.join(dir, 'unisubs')):
        run('{0}/env/bin/python manage.py test_email {1} '
            '--settings=unisubs_settings'.format(dir, to_address))

def test_email(to_address):
    with Output("Testing email"):
        _execute_on_all_hosts(lambda dir: _test_email(dir, to_address))


def build_docs():
    """
    Builds the documentation using sphinx.
    If the environment uses s3, will also uplaod the generated docs
    dir to the root of the bucket.
    """
    with Output("Generating documentation"):
        env.host_string = DEV_HOST
        with cd(os.path.join(env.static_dir, 'unisubs')):
            run('%s/env/bin/sphinx-build docs/ media/docs/' % (env.static_dir))
        if env.s3_bucket is not None:
            with cd(os.path.join(env.static_dir, 'unisubs')):
                python_exe = '{0}/env/bin/python'.format(env.static_dir)
                run('{0} manage.py  upload_docs --settings=unisubs_settings'.format(python_exe))

def _get_settings_values(dir, *settings_name):
    with cd(os.path.join(dir, 'unisubs')):
        run('../env/bin/python manage.py get_settings_values %s --settings=unisubs_settings' % " ".join(settings_name))

def get_settings_values(*settings_names):
    """Connect to all servers and print a given Django setting

    Usage:

        fab env:user get_settings_values:EMAIL_BACKEND,MEDIA_URL

    """
    _execute_on_all_hosts(lambda dir: _get_settings_values(dir, *settings_names))

def test_access(is_sudo=False):
    """
    Makes sure the user can connect to all relevant hosts.
    If any value is passed as an argument, makes sure the user can
    connect and sudo on all hosts.
    """
    run_command = run
    if is_sudo:
        run_command = sudo
    _execute_on_all_hosts(lambda dir: run_command('date'))

try:
    from local_env import *
    def local (username):
        _create_env(**local_env_data)
except ImportError:
    pass


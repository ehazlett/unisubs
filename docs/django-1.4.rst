Backwards incompatible changes in 1.4
=====================================

This page mirrors the *Backwards incompatible changes* section in the `Django
1.4 release notes`_.  Please refer to it when you make changes to this page.
The goal of this document is to spot any places where upgrading to Django 1.4
might break our app.

SECRET_KEY setting is required
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No issues.  The ``SECRET_KEY`` is already populated.

django.contrib.admin
~~~~~~~~~~~~~~~~~~~~

The ``ADMIN_MEDIA_PREFIX`` setting has been removed.  Admin static files might
be missing after upgrading.  This can be fixed with a one-time copying of the
files from the Django distribution to the right place on the web server (or
S3).

For example:

::

    cp -rf \
        /venv/lib/python2.6/site-packages/django/contrib/admin/static/admin \
        /opt/unisubs/media/.'

The vagrant environmnet has a ``fixadminmedia`` bash `alias`_.

Supported browsers for the admin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No issues.  Obviously, nobody who uses our admin interface still uses IE6.

Removed admin icons
~~~~~~~~~~~~~~~~~~~

Not critical.  Some of our admin icons have been missing for a while.

CSS class names in admin forms
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Compatibility with old signed data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No issues.  Only applies to upgrades from Django 1.2.

django.contrib.flatpages
~~~~~~~~~~~~~~~~~~~~~~~~

No issues.  We aren't using ``flatpages``.

Serialization of :class:`~datetime.datetime` and :class:`~datetime.time`
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The only place where this could be an issue is when loading fixtures and those
will still work.

``supports_timezone`` changed to ``False`` for SQLite
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``MySQLdb``-specific exceptions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No issues here.  ``grep -r OperationalError *`` comes back empty.

Database connection's thread-locality
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No issues here.

`COMMENTS_BANNED_USERS_GROUP` setting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No issues here.

`IGNORABLE_404_STARTS` and `IGNORABLE_404_ENDS` settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No issues here.

CSRF protection extended to PUT and DELETE
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Password reset view now accepts ``subject_template_name``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``django.core.template_loaders``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No issues.

``django.db.models.fields.URLField.verify_exists``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No issues.

``django.core.files.storage.Storage.open``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

YAML deserializer now uses ``yaml.safe_load``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No issues.

Session cookies now have the ``httponly`` flag by default
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Unknown

The ``urlize`` filter no longer escapes every URL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``assertTemplateUsed`` and ``assertTemplateNotUsed`` as context manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Database connections after running the test suite
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Output of ``manage.py help <help>``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No issues.

``extends`` template tag
~~~~~~~~~~~~~~~~~~~~~~~~

Loading some incomplete fixtures no longer works
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Development Server Multithreading
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

I haven't noticed anything strange.  If it becomes a problem, add the
``--nothreading`` flag.

Attributes disabled in markdown when safe mode set
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FormMixin get_initial returns an instance-specific dictionary
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~




.. _Django 1.4 release notes: https://docs.djangoproject.com/en/dev/releases/1.4/#backwards-incompatible-changes-in-1-4
.. _alias: https://github.com/pculture/unisubs/commit/cb712b3ca55c8862105f4fc456f993947d149852

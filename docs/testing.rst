Testing
=======

The Amara project uses the `Nose <http://nose.readthedocs.org/en/latest/>`_
testing framework.

Running tests
-------------

You should always run your tests inside the Vagrant VM because the test suite
depends on a running Solr instance.

To run all unittests:

::

    $ vagrant ssh
    $ pmt

The ``pmt`` command is just a bash alias that expands to this:

::

    $ python manage.py test --settings=dev_settings_test

To run tests for a specific Django app:

::

    $ pmt videos

To run a specific test class:

::

    $ pmt videos.tests:ViewsTest


To run a specific test case within a test class:

::

    $ pmt videos.tests:ViewsTest.test_index


Switching to default Django unittesting
---------------------------------------

If Nose isn't your cup of tea, you may wish to switch to the default
unittesting framework that comes with Django.  Open the
``dev_settings_test.py`` file and comment out the line that reads:

::

    TEST_RUNNER = 'django_nose.NoseTestSuiteRunner'

Then you can run tests like you are used to:

::

    $ pmt videos.ViewsTest


Troubleshooting
---------------

Sometimes, the ``pmt`` command wil throw the following error:

::

    django.db.utils.DatabaseError: no such table: django_site

This just means that the testing sqlite database hasn't been created yet.  Run
the following command to create it:

::

    $ preparetestdb

.. warning:: Unfortunately, the test suite isn't deterministic.  If you think
    your tests should pass, try running them again.  Hopefully, this will get
    addressed soon.

:orphan:

.. _postbuild:


What you can do with a built project
====================================

Once you have successfully built a project with Buildstream,
there are 2 things you can do with it:


Shell
=====

The :ref:`shell <invoking_shell>` command allows you to peek inside of a built project.
This is useful for debugging and ensuring the system built everything properly


Checkout
========

The :ref:`checkout <invoking_checkout>` command returns all :ref:`artifacts <artifacts>` that are defined in the install-root


Artifacts
=========

:ref:`Artifacts <artifacts>` are the build output of an element which is stored in the local artifact cache.
Artifacts in a cache are accessed using a "cache key"

For more information on Cache Keys, see :ref:`cachekeys`

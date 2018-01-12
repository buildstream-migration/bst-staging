:orphan:

.. _buildproject:


Building a basic project
========================

This section assumes you have installed BuildStream already.

If not, go to :ref:`installing`

Or :ref:`docker`

Setup
-----


Only run the following section if using docker:

----

.. code:: bash

 bst-here

in the directory you want to use

----

This example will be using `gnome-modulesets`, but this will apply to any buildable repo.

Download or clone `gnome-Modulesets  <http://gnome7.codethink.co.uk/gnome-modulesets.git/>`_

Then move into the repo

Building
--------

Building is the main imperative for any element of the project. Building elements in the project will involve a sequence of activities for each element such as ensuring the sources are downloaded (see: bst :ref:`invoking_fetch`) and running the build commands required to produce output artifacts (see: :ref:`artifacts`).

All elements will be built in order of their dependencies.

Once elements have been built, their output can be obtained with ref: bst checkout (see: :ref:`invoking_checkout`)

To build an element, you need to do the following:

1: Find the .bst file that you want to build

.. note::
 In this case, we will be using `gedit.bst` from elements/core

2: Use the :ref:`invoking_build` command, from the root of the project repo, targeting the chosen element.

.. note::
 This command will skip the `elements/` part of the path.
 This is because, inside the `project.conf` the `elements-path` is set to `elements`
 This means that BuildStream will use `[projectRoot]/elements` as a starting point when looking for elements.

.. code:: bash

 bst build core/gedit.bst

This will attempt to build the element.

In this case, Gedit uses "autotools", so will therefore run:

* `autoreconf;`
* `./configure;`
* `make;`
* `make install`

BuildStream will run the commands needed to build each plugin in the same way the user would.

This removes the need for the user to type dozens of different commands if using multiple build files

----

You may get an error requesting the use of bst :ref:`invoking_track`. This occurs when a ref has not been provided for an element source.

This means that BuildStream does not know where to look to download something.

bst track resolves this issue by checking for the latest commit on the branch provided in the source of the file.

There are 2 main ways of resolving this error:

1:
.. code:: bash

 bst track [element]

Where element is the element listed in the error message

2:
.. code:: bash

 bst track --deps all core/gedit.bst``

This command will go through each element and repeat the process of tracking them.

After tracking all untracked elements, run the build command again and this time it should succeed.

:orphan:

.. _installing:


BuildStream on your host
========================
Until BuildStream is available in your distro, there are a few hoops to jump
through to get started. Follow the instructions below to install BuildStream's
dependencies on your system and install BuildStream itself from source.

Alternately, we have instructions on running BuildStream from a
:ref:`prebuilt Docker container <docker>`.


System requirements
-------------------
BuildStream requires the following base system requirements:

* python3 >= 3.4
* ruamel.yaml python library
* PyGObject introspection bindings
* OSTree >= v2017.8 with introspection data

Note that ``ruamel.yaml`` is a pure python library which is normally
obtainable via pip, however there seems to be some problems with installing
this package so we recommend installing it with your package manager first.

For the purpose of installing BuildStream while there are no distro packages,
you will additionally need:

* pip for python3 (only required for setup)
* Python 3 development libraries and headers
* git (to checkout buildstream)

Here are some examples of how to prepare the base requirements on
some distros.

Arch
~~~~
Install the dependencies with:

  sudo pacman -S fuse2 python python-pip python-gobject git \
                 ostree bubblewrap python-ruamel-yaml

Debian Stretch
~~~~~~~~~~~~~~
With stretch, you first need to ensure that you have the backports repository
setup as described `here <https://backports.debian.org/Instructions/>`_

By adding the following line to your sources.list::

  deb http://ftp.debian.org/debian stretch-backports main

And then running::

  sudo apt-get update

At this point you should be able to get the system requirements with::

  sudo apt-get install \
      python3-dev python3-pip git python3-gi \
      python3-ruamel.yaml bubblewrap fuse libfuse2
  sudo apt-get install -t stretch-backports \
      gir1.2-ostree-1.0 ostree


Debian Buster or Sid
~~~~~~~~~~~~~~~~~~~~
For debian unstable or testing, only the following line should be enough
to get the base system requirements installed::

  sudo apt-get install \
      python3-dev python3-pip git \
      python3-gi gir1.2-ostree-1.0 ostree \
      bubblewrap python3-ruamel.yaml fuse libfuse2


Fedora
~~~~~~
For recent fedora systems, the following line should get you the system
requirements you need::

  dnf install -y bubblewrap fuse fuse-libs git python3-gobject \
                 python3-psutil ostree python3-ruamel-yaml


User installation with pip
--------------------------
Once you have the base system dependencies, you can clone the BuildStream
git repository and install it as a regular user::

  git clone https://gitlab.com/BuildStream/buildstream.git
  cd buildstream
  pip3 install --user .

This will install buildstream and it's pure python dependencies directly into
your user's homedir in ``~/.local``

If you are installing as a developer and want to easily test changes
or if you would like to update your BuildStream installation via git,
then you can specify the ``-e`` option when invoking pip::

  pip3 install --user -e .

.. warning::

   This will run BuildStream directly from your git checkout and will break
   if you ever move the git checkout or run ``git clean -xdf``.


Adjust PATH
~~~~~~~~~~~
Since BuildStream is now installed under your local user's install directories,
you need to ensure that ``PATH`` is adjusted.

A regular way to do this is to add the following line to the end of your ``~/.bashrc``::

  export PATH=${PATH}:~/.local/bin


Bash Completions
~~~~~~~~~~~~~~~~
Bash completions are supported by sourcing the ``buildstream/data/bst``
script found in the BuildStream repository. On many systems this script
can be installed into a completions directory but when installing BuildStream
without a package manager this is not an option.

To enable completions for an installation of BuildStream you
installed yourself from git, just append the script verbatim
to your ``~/.bash_completion``:

.. literalinclude:: ../../buildstream/data/bst
   :language: yaml


Upgrading with pip
~~~~~~~~~~~~~~~~~~
To upgrade a previously install BuildStream, you will need to pull the latest
changes and reinstall as such::

  pip3 uninstall buildstream
  cd buildstream
  git pull --rebase
  pip3 install --user .

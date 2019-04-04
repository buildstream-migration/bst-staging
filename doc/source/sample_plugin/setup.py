from setuptools import setup, find_packages

setup(name='BuildStream Autotools',
      version="0.1",
      description="A better autotools element for BuildStream",
      packages=find_packages(),
      install_requires=[
          'setuptools'
      ],
      include_package_data=True,
      entry_points={
          'buildstream2.plugins': [
              'autotools = elements.autotools'
          ]
      })

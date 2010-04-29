from setuptools import setup, find_packages
import sys, os

version = '0.1'

setup(name='openid-redis',
      version=version,
      description="A Redis storage backend for pthe python-openid package",
      long_description="""\
""",
      classifiers=[], # Get strings from http://pypi.python.org/pypi?%3Aaction=list_classifiers
      keywords='openid redis',
      author='Ben Bangert',
      author_email='ben@groovie.org',
      url='',
      license='MIT',
      packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
      include_package_data=True,
      zip_safe=False,
      install_requires=[
          # -*- Extra requirements: -*-
      ],
      entry_points="""
      # -*- Entry points: -*-
      """,
      )

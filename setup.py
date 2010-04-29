from setuptools import setup, find_packages
import sys, os

version = '0.5'

setup(name='openid-redis',
      version=version,
      description="A Redis storage backend for the python-openid package",
      long_description="""\
""",
      classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Topic :: Internet :: WWW/HTTP"
      ],
      keywords='openid redis',
      author='Ben Bangert',
      author_email='ben@groovie.org',
      url='http://bbangert.github.com/openid-redis',
      license='MIT',
      packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
      include_package_data=True,
      zip_safe=False,
      install_requires=["redis>=1.34.1", "python-openid>=2.2.4"],
      entry_points="""
      # -*- Entry points: -*-
      """,
)

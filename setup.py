from setuptools import setup, find_packages

setup(
    name='cmenu',
    version='1.0.0',
    description=('A Python alternative to cmd.Cmd.'),
    long_description=('A Python alternative to cmd.Cmd with more features.'),
    url='https://github.com/kynikos/lib.py.cmenu',
    author='Dario Giovannetti',
    author_email='dev@dariogiovannetti.net',
    license='GPLv3+',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Topic :: System :: Shells',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',  # noqa
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ],
    keywords='commandline',
    py_modules=["cmenu"],
)

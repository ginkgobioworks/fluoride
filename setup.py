from setuptools import setup

setup(
    name='fluoride_cli',
    version='1.31',
    description='Friendly command line interface for managing and interacting with fluoride architectures!',
    author='Jacob Mevorach',
    author_email='jacob@ginkgobioworks.com',
    packages=['fluoride_cli'],
    entry_points = {'console_scripts': ['fluoride_cli=fluoride_cli.cli:run']},
    python_requires='>=3.6'
)


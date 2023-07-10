import setuptools


with open('README.md', 'r', encoding='utf-8') as fh:
    long_description = fh.read()

setuptools.setup(
    name='nil_lib',
    version='2.0',
    author='Katlin Sampson',
    author_email='katlinvsampson@gmail.com',
    description='Python libary of switch and various commands',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/Niltak/nil_lib',
    project_urls={
        'Bug Tracker': 'https://github.com/Niltak/nil_lib/issues',
    },
    license="LICENSE.md",
    packages=setuptools.find_packages(),
    python_requires='>=3.7',
    install_requires=['netmiko>=3.4.0', 'pyyaml'],
)

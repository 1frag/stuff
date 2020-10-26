from setuptools import find_packages, setup
import glob

with open('requirements/read_flow.txt') as r:
    req = r.read()

setup(
    name='read_flow',
    version='0.0.3pre',
    install_requires=req.split('\n'),
    data_files=[('read_flow', glob.glob('read_flow/*.json'))],
    packages=find_packages(),
)

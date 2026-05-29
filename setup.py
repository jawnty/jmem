from setuptools import find_packages, setup


setup(
    name="jmem",
    version="0.2.0",
    packages=find_packages(include=["jmem", "jmem.*"]),
)

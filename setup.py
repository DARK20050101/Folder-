"""Package setup for DiskExplorer."""

from setuptools import find_packages, setup

with open("README.md", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="DiskExplorer",
    version="1.0.0",
    author="DiskExplorer Team",
    description="A lightweight disk space analysis tool",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.9",
    install_requires=[
        "psutil>=5.9.0",
        "PyQt6>=6.4.0",
    ],
    extras_require={
        "data": ["pandas>=1.5.0", "numpy>=1.23.0"],
        "dev": ["pytest>=7.0", "pytest-cov>=4.0"],
    },
    entry_points={
        "console_scripts": [
            "diskexplorer=main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: System :: Filesystems",
        "Topic :: Utilities",
    ],
)

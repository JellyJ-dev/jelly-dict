"""Single dependency policy shared by installers and runtime probes."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

POLICY_SCHEMA_VERSION = 1
PYTHON_MIN = (3, 11)
PYTHON_MAX_EXCLUSIVE = (3, 13)
SUPPORTED_PYTHON_MINORS = ("3.11", "3.12")
PYSIDE_SUPPORTED = ">=6.7,<6.11"


class RequirementRule(NamedTuple):
    distribution: str
    module: str
    specifier: str
    requirement: str
    marker: str = ""


RUNTIME_REQUIREMENTS = (
    RequirementRule("PySide6", "PySide6", PYSIDE_SUPPORTED, "PySide6>=6.7,<6.11"),
    RequirementRule(
        "beautifulsoup4",
        "bs4",
        ">=4.12,<4.15",
        "beautifulsoup4>=4.12,<4.15",
    ),
    RequirementRule("lxml", "lxml", ">=5.0,<6.2", "lxml>=5.0,<6.2"),
    RequirementRule(
        "playwright",
        "playwright",
        ">=1.45,<1.61",
        "playwright>=1.45,<1.61",
    ),
    RequirementRule("openpyxl", "openpyxl", ">=3.1,<3.2", "openpyxl>=3.1,<3.2"),
    RequirementRule("genanki", "genanki", ">=0.13,<0.14", "genanki>=0.13,<0.14"),
    RequirementRule("keyring", "keyring", ">=24,<26", "keyring>=24,<26"),
    RequirementRule(
        "pyobjc-framework-Cocoa",
        "AppKit",
        ">=10,<13",
        'pyobjc-framework-Cocoa>=10,<13; platform_system == "Darwin"',
        "darwin",
    ),
    RequirementRule(
        "pyobjc-framework-Vision",
        "Vision",
        ">=10,<13",
        'pyobjc-framework-Vision>=10,<13; platform_system == "Darwin"',
        "darwin",
    ),
)

TTS_REQUIREMENTS = (
    RequirementRule("kokoro", "kokoro", ">=0.9.4,<0.10", "kokoro>=0.9.4,<0.10"),
    RequirementRule(
        "soundfile",
        "soundfile",
        ">=0.12,<0.14",
        "soundfile>=0.12,<0.14",
    ),
    RequirementRule("spacy", "spacy", ">=3.8,<3.9", "spacy>=3.8,<3.9"),
    RequirementRule("misaki", "misaki", ">=0.9.4,<0.10", "misaki[ja]>=0.9.4,<0.10"),
)

KOKORO_CORE_INSTALL_REQUIREMENTS = tuple(
    rule.requirement for rule in TTS_REQUIREMENTS if rule.distribution != "misaki"
)
KOKORO_JA_INSTALL_REQUIREMENTS = tuple(
    rule.requirement for rule in TTS_REQUIREMENTS if rule.distribution == "misaki"
)

REQUIREMENT_GROUPS = {
    "runtime": RUNTIME_REQUIREMENTS,
    "tts": TTS_REQUIREMENTS,
}

CONSTRAINT_FILES = {
    "3.11": {
        "runtime": "constraints/python311.txt",
        "tts": "constraints/tts-python311.txt",
    },
    "3.12": {
        "runtime": "constraints/python312.txt",
        "tts": "constraints/tts-python312.txt",
    },
}

RUNTIME_PINS = (
    "PySide6==6.10.3",
    "beautifulsoup4==4.14.3",
    "lxml==6.1.1",
    "playwright==1.60.0",
    "openpyxl==3.1.5",
    "genanki==0.13.1",
    "keyring==25.7.0",
    'pyobjc-framework-Cocoa==12.2; platform_system == "Darwin"',
    'pyobjc-framework-Vision==12.2; platform_system == "Darwin"',
)

TTS_PINS = (
    "kokoro==0.9.4",
    "soundfile==0.13.1",
    "spacy==3.8.14",
    "misaki==0.9.4",
    "en-core-web-sm==3.8.0",
    "pyopenjtalk==0.4.1",
    "fugashi==1.5.2",
    "unidic==1.1.0",
    "huggingface-hub==1.17.0",
    "numpy==2.4.6",
    "torch==2.12.0",
    "transformers==5.9.0",
)

CONSTRAINT_PINS = {
    "3.11": {"runtime": RUNTIME_PINS, "tts": TTS_PINS},
    "3.12": {"runtime": RUNTIME_PINS, "tts": TTS_PINS},
}


def constraint_path(group: str, python_minor: str | None = None) -> Path:
    minor = python_minor or f"{sys.version_info.major}.{sys.version_info.minor}"
    relative = CONSTRAINT_FILES[minor][group]
    return Path(__file__).resolve().parents[2] / relative


KOKORO_REQUIRED_MODULES = (
    "soundfile",
    "kokoro",
    "spacy",
    "en_core_web_sm",
    "misaki",
    "pyopenjtalk",
    "fugashi",
    "unidic",
)

KOKORO_REQUIRED_FILES = (
    "config.json",
    "kokoro-v1_0.pth",
    "voices/af_heart.pt",
    "voices/jf_alpha.pt",
    "voices/jf_gongitsune.pt",
    "voices/jm_kumo.pt",
)

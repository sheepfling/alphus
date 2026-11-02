"""Shared source-language literals used by policy models."""

from typing import Literal

PythonLanguage = Literal["python"]
JavaScriptLanguage = Literal["javascript"]
CppLanguage = Literal["cpp"]
SourceLanguage = PythonLanguage | JavaScriptLanguage | CppLanguage

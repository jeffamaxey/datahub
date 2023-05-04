import re
from abc import ABC, abstractmethod
from typing import IO, Any, Dict, List, Optional, Pattern, cast

from pydantic import BaseModel


class ConfigModel(BaseModel):
    class Config:
        extra = "forbid"


class DynamicTypedConfig(ConfigModel):
    type: str
    # This config type is declared Optional[Any] here. The eventual parser for the
    # specified type is responsible for further validation.
    config: Optional[Any]


class MetaError(Exception):
    """A base class for all meta exceptions"""


class PipelineExecutionError(MetaError):
    """An error occurred when executing the pipeline"""


class OperationalError(PipelineExecutionError):
    """An error occurred because of client-provided metadata"""

    message: str
    info: dict

    def __init__(self, message: str, info: dict = None):
        self.message = message
        self.info = info if info else {}


class ConfigurationError(MetaError):
    """A configuration error has happened"""


class SensitiveError(Exception):
    """Wraps an exception that should not be logged with variable information."""

    @classmethod
    def get_sensitive_cause(cls, exc: Exception) -> Optional[Exception]:
        """
        Returns the underlying exception if the exception is sensitive, and None otherwise.
        """

        e: Optional[Exception] = exc
        while e:
            # This cast converts BaseException to Exception.
            inner = cast(Optional[Exception], e.__cause__)

            if isinstance(e, cls):
                return inner
            e = inner
        return None


class ConfigurationMechanism(ABC):
    @abstractmethod
    def load_config(self, config_fp: IO) -> dict:
        pass


class AllowDenyPattern(ConfigModel):
    """A class to store allow deny regexes"""

    allow: List[str] = [".*"]
    deny: List[str] = []
    ignoreCase: Optional[
        bool
    ] = True  # Name comparisons should default to ignoring case
    alphabet: str = "[A-Za-z0-9 _.-]"

    @property
    def alphabet_pattern(self) -> Pattern:
        return re.compile(f"^{self.alphabet}+$")

    @property
    def regex_flags(self) -> int:
        return re.IGNORECASE if self.ignoreCase else 0

    @classmethod
    def allow_all(cls) -> "AllowDenyPattern":
        return AllowDenyPattern()

    def allowed(self, string: str) -> bool:
        for deny_pattern in self.deny:
            if re.match(deny_pattern, string, self.regex_flags):
                return False

        return any(
            re.match(allow_pattern, string, self.regex_flags)
            for allow_pattern in self.allow
        )

    def is_fully_specified_allow_list(self) -> bool:
        """
        If the allow patterns are literals and not full regexes, then it is considered
        fully specified. This is useful if you want to convert a 'list + filter'
        pattern into a 'search for the ones that are allowed' pattern, which can be
        much more efficient in some cases.
        """
        return all(
            self.alphabet_pattern.match(allow_pattern)
            for allow_pattern in self.allow
        )

    def get_allowed_list(self) -> List[str]:
        """Return the list of allowed strings as a list, after taking into account deny patterns, if possible"""
        assert self.is_fully_specified_allow_list()
        return [a for a in self.allow if self.allowed(a)]


class KeyValuePattern(ConfigModel):
    """A class to store allow deny regexes"""

    rules: Dict[str, List[str]] = {".*": []}
    alphabet: str = "[A-Za-z0-9 _.-]"

    @property
    def alphabet_pattern(self) -> Pattern:
        return re.compile(f"^{self.alphabet}+$")

    @classmethod
    def all(cls) -> "KeyValuePattern":
        return KeyValuePattern()

    def value(self, string: str) -> List[str]:
        return next(
            (
                self.rules[key]
                for key in self.rules.keys()
                if re.match(key, string)
            ),
            [],
        )

    def matched(self, string: str) -> bool:
        return any(re.match(key, string) for key in self.rules.keys())

    def is_fully_specified_key(self) -> bool:
        """
        If the allow patterns are literals and not full regexes, then it is considered
        fully specified. This is useful if you want to convert a 'list + filter'
        pattern into a 'search for the ones that are allowed' pattern, which can be
        much more efficient in some cases.
        """
        return any(not self.alphabet_pattern.match(key) for key in self.rules.keys())

    def get(self) -> Dict[str, List[str]]:
        """Return the list of allowed strings as a list, after taking into account deny patterns, if possible"""
        assert self.is_fully_specified_key()
        return self.rules


class VersionedConfig(ConfigModel):
    version: str = "1"

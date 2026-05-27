"""Shared scraper exception classes that aren't tied to a specific platform
parser. Platform-specific exceptions (SchemaChangeError, BlockedError,
FetchError) live in parse_shopify.py for historical reasons — once a third
consumer lands, candidate for relocation here.

ConfigError lives here because it's strictly a user-side YAML / vendor-row
mistake, distinct from vendor HTML schema drift (SchemaChangeError) or
remote-block detection (BlockedError) or transport failure (FetchError).
Alert routing in run.py maps ConfigError → error_class='config' so on-call
investigates the config file, not the vendor surface.
"""

from __future__ import annotations


class ConfigError(ValueError):
    """Raised when a scraper config (YAML or vendors-row) is malformed or
    missing required fields. Distinct from SchemaChangeError, which signals
    vendor-side HTML drift. CTK-090 Session 4 /code-review finding #13.
    """

"""procedural_memory — Local procedural memory layer for Sensei Akira.
"""

from .config import (
    EXPIRY_DAYS,
    MAX_STORE_ENTRIES,
    REPLAY_ANNOUNCEMENT_CUE,
    SUCCESS_THRESHOLD,
    get_db_path,
    get_key_path,
    get_procedures_dir,
)
from .crypto import get_or_create_cipher
from .matcher import ExactNormalizedMatcher, MatchResult, Matcher
from .pipeline import (
    check_procedural_recall,
    get_mode,
    get_store,
    resolve_deferred_accounting,
    stage_pending_derivation,
)
from .schema import (
    StoredProcedure,
    compute_plan_hash,
    normalize_incoming_envelope,
    normalize_trigger,
)
from .shadow import ShadowStats, ShadowTelemetry, get_shadow_telemetry
from .scrubber import (
    contains_credentials,
    contains_pii,
    is_deictic_or_relative,
    normalize_and_check_path_exclusion,
    validate_procedure_safety,
)
from .store import ProceduralStore
from .tags import (
    TAG_ALWAYS_FRESH,
    TAG_CONTENT_GENERATED,
    TAG_RECALL_ELIGIBLE,
    VALID_SYSTEM_TOOLS,
    get_plan_tag,
    get_step_tag,
)

__all__ = [
    "ProceduralStore",
    "Matcher",
    "ExactNormalizedMatcher",
    "MatchResult",
    "StoredProcedure",
    "compute_plan_hash",
    "normalize_trigger",
    "normalize_incoming_envelope",
    "contains_credentials",
    "contains_pii",
    "is_deictic_or_relative",
    "normalize_and_check_path_exclusion",
    "validate_procedure_safety",
    "get_step_tag",
    "get_plan_tag",
    "TAG_RECALL_ELIGIBLE",
    "TAG_ALWAYS_FRESH",
    "TAG_CONTENT_GENERATED",
    "VALID_SYSTEM_TOOLS",
    "get_or_create_cipher",
    "get_procedures_dir",
    "get_db_path",
    "get_key_path",
    "MAX_STORE_ENTRIES",
    "EXPIRY_DAYS",
    "SUCCESS_THRESHOLD",
    "REPLAY_ANNOUNCEMENT_CUE",
]

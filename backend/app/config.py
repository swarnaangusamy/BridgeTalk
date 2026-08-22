"""Application configuration.

Every tunable value in BridgeTalk comes from the repository-root `.env` file and
passes through this module. Nothing else in the codebase reads `os.environ`
directly — that single rule is what makes it possible to answer "where does this
setting come from?" without grepping the whole project.

pydantic-settings validates and type-casts on startup, so a typo like
CONFIDENCE_THRESHOLD=0.8O (letter O instead of zero) fails loudly the moment the
server boots rather than silently at 2am during the demo.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py lives at backend/app/config.py, so the repository root is three
# parents up. Resolving it this way means the backend runs correctly no matter
# which directory uvicorn was launched from.
BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """Typed view of `.env`. Defaults here are development-safe, not secrets."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        # The same .env feeds the Vite frontend (VITE_* keys), so unknown keys
        # must be ignored rather than raising a validation error.
        extra="ignore",
    )

    # --- Database ---------------------------------------------------------
    # Swapping this one line to "sqlite:///./bridgetalk.db" is the documented
    # zero-setup fallback; no other code changes.
    database_url: str = "sqlite:///./bridgetalk.db"

    # --- Auth -------------------------------------------------------------
    jwt_secret_key: str = "change_me_to_a_long_random_string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # --- Server -----------------------------------------------------------
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    # Stored as a raw comma-separated string rather than a list: pydantic
    # -settings tries to JSON-decode list-typed env vars, which would force the
    # awkward CORS_ORIGINS=["http://..."] syntax in .env.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Machine learning -------------------------------------------------
    static_model_path: str = "ml/models/static_model.keras"
    dynamic_model_path: str = "ml/models/dynamic_model.keras"
    model_metadata_path: str = "ml/models/metadata.json"
    labels_path: str = "ml/models/labels.json"
    dynamic_metadata_path: str = "ml/models/dynamic_metadata.json"
    dynamic_labels_path: str = "ml/models/labels_dynamic.json"
    # Indian Sign Language alphabet. Two-handed, so 126 features rather than
    # 63 — ASL's weights are not merely less accurate here, they are the wrong
    # shape, which is why this is a separate model and not a retrained one.
    isl_model_path: str = "ml/models/isl_model.keras"
    isl_metadata_path: str = "ml/models/isl_metadata.json"
    isl_labels_path: str = "ml/models/labels_isl.json"

    # --- Real-time smoothing (Section 9 of the build spec) ----------------
    confidence_threshold: float = 0.80
    cooldown_ms: int = 1500
    majority_window: int = 10
    majority_min: int = 7
    neutral_reset_frames: int = 8
    sequence_length: int = 30

    # --- Dynamic (word-sign) mode ----------------------------------------
    # Separate values from the static ones, because the two modes have
    # genuinely different dynamics rather than because tuning was fun:
    #
    #   * threshold is LOWER (0.70) — 20 word classes trained on ~20 clips
    #     each produce less peaked softmax output than 28 letter classes
    #     trained on thousands. Reusing 0.80 would reject nearly everything.
    #   * cooldown is LONGER (2500 ms) — a word sign takes one to two seconds
    #     to perform, so a 1.5 s debounce could fire twice within one sign.
    #   * the majority window is SMALLER (5 of 3) — consecutive dynamic
    #     predictions come from windows overlapping by 29/30 frames, so they
    #     are far more correlated than consecutive static predictions. Ten
    #     such votes would add latency without adding independent evidence.
    dynamic_confidence_threshold: float = 0.70
    dynamic_cooldown_ms: int = 2500
    dynamic_majority_window: int = 5
    dynamic_majority_min: int = 3
    # Classify every Nth frame instead of every frame. See ml/sequence.py.
    dynamic_stride: int = 3
    # Fraction of a window that must contain a detected hand before it is
    # classified. Matches the threshold extraction used on training clips.
    dynamic_min_detection_rate: float = 0.30
    # Consecutive hand-free frames that count as a sign boundary.
    dynamic_reset_frames: int = 8

    # ------------------------------------------------------------------ #
    # Derived values
    # ------------------------------------------------------------------ #

    @property
    def cors_origins_list(self) -> list[str]:
        """`CORS_ORIGINS` split into the list FastAPI's middleware expects."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        """SQLite needs different engine arguments — see database.py."""
        return self.database_url.startswith("sqlite")

    def resolve_path(self, relative: str) -> Path:
        """Turn a repo-relative path from .env into an absolute path.

        Model paths in .env are written relative to the repository root so the
        file reads the same on every machine. Resolving them here means the
        backend finds the models regardless of the working directory.
        """
        candidate = Path(relative)
        return candidate if candidate.is_absolute() else BASE_DIR / candidate


@lru_cache
def get_settings() -> Settings:
    """Settings are read once and cached.

    Re-reading .env on every request would be wasted file I/O, and worse, would
    let configuration change underneath a running request. The cache also makes
    `get_settings` safe to use as a FastAPI dependency.
    """
    return Settings()


settings = get_settings()

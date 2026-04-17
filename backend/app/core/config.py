from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    # App
    APP_NAME: str = "JWT Auth API"
    DEBUG: bool = False
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/authdb"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # JWT — RS256 asymmetric keys (backend signs, frontend verifies)
    JWT_PRIVATE_KEY: str  # RSA private key PEM — backend only, never expose
    JWT_PUBLIC_KEY: str   # RSA public key PEM — safe to share with frontend
    JWT_ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Security
    CSRF_HEADER_NAME: str = "X-CSRF-Token"
    RATE_LIMIT_LOGIN: str = "5/minute"
    RATE_LIMIT_REGISTER: str = "3/hour"
    RATE_LIMIT_REFRESH: str = "30/minute"

    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 15


settings = Settings()

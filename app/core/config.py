from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ERB"
    debug: bool = False
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/inventory_db"
    secret_key: str = "33146f8e56abc80af6b1d6e8124812a8a962813eb03ff25fc46be4987c0b685c"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
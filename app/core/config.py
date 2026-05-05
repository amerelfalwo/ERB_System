from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ERB"
    debug: bool = False
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/inventory_db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
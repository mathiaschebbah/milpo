from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://hilpo:hilpo@localhost:5433/hilpo"

    model_config = {"env_prefix": "HILPO_"}


settings = Settings()

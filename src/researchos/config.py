from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESEARCHOS_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    model_base_url: str = "http://127.0.0.1:11434/v1"
    model_api_key: str = "ollama"
    model_name: str = ""
    model_runtime: str = "ollama"
    request_timeout_seconds: float = 120
    paper_analysis_timeout_seconds: float = 600
    max_search_results_per_source: int = 20
    max_papers_per_run: int = 48
    max_analysis_papers: int = 12
    max_open_access_fulltext_per_run: int = 3

    @property
    def database_path(self) -> Path:
        return self.data_dir / "researchos.sqlite3"


settings = Settings()

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    base_dir: Path = Path(__file__).resolve().parent.parent
    data_dir: Path = base_dir / "data"
    uploads_dir: Path = data_dir / "uploads"
    db_path: Path = data_dir / "rics.db"

    # ローカルGGUF（Gemma 4 等）— 未設定時はルールベースの簡易判定
    llm_model_path: str | None = None
    llm_n_ctx: int = 8192
    llm_n_gpu_layers: int = -1
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.1

    semantic_scholar_base: str = "https://api.semanticscholar.org/graph/v1"
    request_timeout_sec: float = 30.0

    @field_validator("llm_model_path", mode="before")
    @classmethod
    def empty_llm_path_is_none(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            # modelsフォルダ内に .gguf ファイルが1つだけあればそれを自動採用
            try:
                models_dir = Path(__file__).resolve().parent.parent / "models"
                ggufs = list(models_dir.glob("*.gguf"))
                if len(ggufs) == 1:
                    return str(ggufs[0])
            except:
                pass
            return None
        return v


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)

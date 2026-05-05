from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GenerateTestsConfig(BaseModel):
    model: str = "gpt-4.1-mini"
    max_tokens: int = 8000
    temperature: float = 0.2
    max_targets_per_run: int = 50
    output_dir: str = "generated_tests"
    enable_service_functions: bool = True
    enable_api_endpoints: bool = True

    @field_validator("max_tokens", "max_targets_per_run")
    @classmethod
    def validate_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than 0")
        return value

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, value: float) -> float:
        if not 0 <= value <= 2:
            raise ValueError("must be between 0 and 2")
        return value

    @field_validator("output_dir")
    @classmethod
    def validate_output_dir(cls, value: str) -> str:
        stripped = value.strip().strip("/")
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")
    supabase_url: str = Field(alias="SUPABASE_URL")
    supabase_anon_key: str | None = Field(default=None, alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(alias="SUPABASE_SERVICE_ROLE_KEY")
    supabase_storage_bucket: str = Field(alias="SUPABASE_STORAGE_BUCKET")
    supabase_jwt_audience: str = Field(default="authenticated", alias="SUPABASE_JWT_AUDIENCE")
    api_cors_origin: str = Field(default="http://localhost:3000", alias="API_CORS_ORIGIN")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    generate_tests_model: str = Field(default="gpt-4.1-mini", alias="GENERATE_TESTS_MODEL")
    generate_tests_max_tokens: int = Field(default=8000, alias="GENERATE_TESTS_MAX_TOKENS")
    generate_tests_temperature: float = Field(default=0.2, alias="GENERATE_TESTS_TEMPERATURE")
    generate_tests_max_targets_per_run: int = Field(default=50, alias="GENERATE_TESTS_MAX_TARGETS_PER_RUN")
    generate_tests_output_dir: str = Field(default="generated_tests", alias="GENERATE_TESTS_OUTPUT_DIR")
    generate_tests_enable_service_functions: bool = Field(default=True, alias="GENERATE_TESTS_ENABLE_SERVICE_FUNCTIONS")
    generate_tests_enable_api_endpoints: bool = Field(default=True, alias="GENERATE_TESTS_ENABLE_API_ENDPOINTS")

    def generate_tests_config(self) -> GenerateTestsConfig:
        try:
            return GenerateTestsConfig(
                model=self.generate_tests_model,
                max_tokens=self.generate_tests_max_tokens,
                temperature=self.generate_tests_temperature,
                max_targets_per_run=self.generate_tests_max_targets_per_run,
                output_dir=self.generate_tests_output_dir,
                enable_service_functions=self.generate_tests_enable_service_functions,
                enable_api_endpoints=self.generate_tests_enable_api_endpoints,
            )
        except ValidationError as exc:
            raise RuntimeError(f"Invalid generate_tests configuration: {exc}") from exc

    def require_openai_api_key_for_generate_tests(self) -> str:
        api_key = (self.openai_api_key or "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required when the generate_tests stage runs")
        return api_key


settings = Settings()

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


class ExecuteTestsConfig(BaseModel):
    image: str = "python:3.12-slim"
    workspace_root: str = "/workspace"
    output_dir: str = "execute_tests"
    shared_workspace_root: str = "/executor-workspaces"
    executor_base_url: str = "http://executor:8080"
    install_timeout_seconds: int = 300
    suite_timeout_seconds: int = 600
    cpus: float = 1.0
    memory_mb: int = 1024
    pids: int = 256
    tmpfs_mb: int = 128

    @field_validator("image", "workspace_root", "output_dir", "shared_workspace_root", "executor_base_url")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped

    @field_validator("install_timeout_seconds", "suite_timeout_seconds", "memory_mb", "pids", "tmpfs_mb")
    @classmethod
    def validate_positive_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than 0")
        return value

    @field_validator("cpus")
    @classmethod
    def validate_positive_cpus(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be greater than 0")
        return value


class AnalyzeConfig(BaseModel):
    enable_llm: bool = True
    model: str = "gpt-4.1-mini"
    max_tokens: int = 1200
    temperature: float = 0.1
    max_failures_for_llm: int = 10

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped

    @field_validator("max_tokens", "max_failures_for_llm")
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
    execute_tests_image: str = Field(default="python:3.12-slim", alias="EXECUTE_TESTS_IMAGE")
    execute_tests_workspace_root: str = Field(default="/workspace", alias="EXECUTE_TESTS_WORKSPACE_ROOT")
    execute_tests_output_dir: str = Field(default="execute_tests", alias="EXECUTE_TESTS_OUTPUT_DIR")
    execute_tests_shared_workspace_root: str = Field(
        default="/executor-workspaces",
        alias="EXECUTE_TESTS_SHARED_WORKSPACE_ROOT",
    )
    executor_base_url: str = Field(default="http://executor:8080", alias="EXECUTOR_BASE_URL")
    execute_tests_install_timeout_seconds: int = Field(default=300, alias="EXECUTE_TESTS_INSTALL_TIMEOUT_SECONDS")
    execute_tests_suite_timeout_seconds: int = Field(default=600, alias="EXECUTE_TESTS_SUITE_TIMEOUT_SECONDS")
    execute_tests_cpus: float = Field(default=1.0, alias="EXECUTE_TESTS_CPUS")
    execute_tests_memory_mb: int = Field(default=1024, alias="EXECUTE_TESTS_MEMORY_MB")
    execute_tests_pids: int = Field(default=256, alias="EXECUTE_TESTS_PIDS")
    execute_tests_tmpfs_mb: int = Field(default=128, alias="EXECUTE_TESTS_TMPFS_MB")
    analyze_enable_llm: bool = Field(default=True, alias="ANALYZE_ENABLE_LLM")
    analyze_model: str = Field(default="gpt-4.1-mini", alias="ANALYZE_MODEL")
    analyze_max_tokens: int = Field(default=1200, alias="ANALYZE_MAX_TOKENS")
    analyze_temperature: float = Field(default=0.1, alias="ANALYZE_TEMPERATURE")
    analyze_max_failures_for_llm: int = Field(default=10, alias="ANALYZE_MAX_FAILURES_FOR_LLM")

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

    def execute_tests_config(self) -> ExecuteTestsConfig:
        try:
            return ExecuteTestsConfig(
                image=self.execute_tests_image,
                workspace_root=self.execute_tests_workspace_root,
                output_dir=self.execute_tests_output_dir,
                shared_workspace_root=self.execute_tests_shared_workspace_root,
                executor_base_url=self.executor_base_url,
                install_timeout_seconds=self.execute_tests_install_timeout_seconds,
                suite_timeout_seconds=self.execute_tests_suite_timeout_seconds,
                cpus=self.execute_tests_cpus,
                memory_mb=self.execute_tests_memory_mb,
                pids=self.execute_tests_pids,
                tmpfs_mb=self.execute_tests_tmpfs_mb,
            )
        except ValidationError as exc:
            raise RuntimeError(f"Invalid execute_tests configuration: {exc}") from exc

    def analyze_config(self) -> AnalyzeConfig:
        try:
            return AnalyzeConfig(
                enable_llm=self.analyze_enable_llm,
                model=self.analyze_model,
                max_tokens=self.analyze_max_tokens,
                temperature=self.analyze_temperature,
                max_failures_for_llm=self.analyze_max_failures_for_llm,
            )
        except ValidationError as exc:
            raise RuntimeError(f"Invalid analyze configuration: {exc}") from exc


settings = Settings()

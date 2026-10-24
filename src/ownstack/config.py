from dataclasses import dataclass, field
import os
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlsplit
import ipaddress


load_dotenv(Path.cwd() / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("OWNSTACK_DATABASE_URL", "sqlite:///./ownstack.db"))
    signing_secret: str = field(default_factory=lambda: os.getenv("OWNSTACK_SIGNING_SECRET", "local-demo-secret-not-for-deployment"))
    ai_mode: str = field(default_factory=lambda: os.getenv("OWNSTACK_AI_MODE", "fixture"))
    nebius_key: str = field(default_factory=lambda: os.getenv("NEBIUS_API_KEY", ""))
    nebius_model: str = field(default_factory=lambda: os.getenv("NEBIUS_MODEL_ID", ""))
    nebius_patch_model: str = field(default_factory=lambda: os.getenv("NEBIUS_PATCH_MODEL_ID", ""))
    ai_timeout: float = field(default_factory=lambda: float(os.getenv("OWNSTACK_AI_TIMEOUT_SECONDS", "20")))
    stream_inference: bool = field(default_factory=lambda: os.getenv("OWNSTACK_STREAM_INFERENCE", "false").lower() == "true")
    max_live_calls: int = field(default_factory=lambda: int(os.getenv("OWNSTACK_MAX_LIVE_CALLS", "0")))
    demo_password: str = field(default_factory=lambda: os.getenv("OWNSTACK_DEMO_PASSWORD", "demo-only-pass"))
    environment: str = field(default_factory=lambda: os.getenv("OWNSTACK_ENV", "local"))
    public_origin: str = field(default_factory=lambda: os.getenv("OWNSTACK_PUBLIC_ORIGIN", "http://127.0.0.1:8080").rstrip("/"))
    require_background: bool = field(default_factory=lambda: os.getenv("OWNSTACK_REQUIRE_BACKGROUND", "true" if os.getenv("OWNSTACK_ENV") == "production" else "false").lower() == "true")
    trusted_proxy_ips: str = field(default_factory=lambda: os.getenv('OWNSTACK_TRUSTED_PROXY_IPS', ''))

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"

    def validate(self) -> None:
        if self.ai_mode not in {"fixture", "nebius", "off"}:
            raise ValueError("OWNSTACK_AI_MODE must be fixture, nebius, or off")
        if self.ai_mode == "nebius" and (not self.nebius_key or not self.nebius_model):
            raise ValueError("Live mode requires NEBIUS_API_KEY and NEBIUS_MODEL_ID")
        if self.ai_mode == "nebius" and (
            not self.nebius_model.lower().startswith("nvidia/") or "nemotron" not in self.nebius_model.lower()
        ):
            raise ValueError("Live mode requires a verified NVIDIA Nemotron model ID")
        if self.ai_mode == "nebius" and self.max_live_calls <= 0:
            raise ValueError("Live mode requires OWNSTACK_MAX_LIVE_CALLS > 0")
        if self.nebius_patch_model and (not self.nebius_patch_model.lower().startswith("nvidia/") or
                                       "nemotron" not in self.nebius_patch_model.lower()):
            raise ValueError("Patch model must be a verified NVIDIA Nemotron model ID")
        if self.environment not in {"local", "production"}:
            raise ValueError("OWNSTACK_ENV must be local or production")
        if not 1 <= self.ai_timeout <= 120:
            raise ValueError("AI timeout must be between 1 and 120 seconds")
        if not 0 <= self.max_live_calls <= 10:
            raise ValueError("This build is authorized for at most 10 live calls")
        if self.environment == "production":
            origin = urlsplit(self.public_origin)
            if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
                    or origin.path or origin.query or origin.fragment or origin.netloc.endswith(':')
                    or any(character.isspace() for character in self.public_origin)):
                raise ValueError("Production requires an HTTPS OWNSTACK_PUBLIC_ORIGIN")
            try:
                origin.port
            except ValueError:
                raise ValueError('Invalid production origin port') from None
            if len(self.signing_secret) < 32 or self.signing_secret == "local-demo-secret-not-for-deployment":
                raise ValueError("Production requires a new 32+ character signing secret")
            if not self.database_url.startswith("postgresql+"):
                raise ValueError("Production requires PostgreSQL")
            if self.ai_mode == "fixture":
                raise ValueError("Production requires live Nebius mode or an explicit AI-off maintenance mode")
            if len(self.demo_password) < 16 or self.demo_password == "demo-only-pass":
                raise ValueError("Production requires a new 16+ character demo password")
            if any(value.lower().startswith(('replace-', 'changeme', 'example-'))
                   for value in (self.signing_secret, self.demo_password)):
                raise ValueError('Replace template credentials before production startup')
            if self.signing_secret == self.demo_password:
                raise ValueError('Use independent signing and authentication secrets')
            if not self.require_background:
                raise ValueError('Production requires worker and kernel-isolation readiness checks')
            if not self.trusted_proxy_ips:
                raise ValueError('Production requires explicit trusted proxy IP addresses')
            try:
                for value in self.trusted_proxy_ips.split(','):
                    ipaddress.ip_address(value.strip())
            except ValueError:
                raise ValueError('Trusted proxies must be exact IP addresses, never wildcards or CIDRs') from None

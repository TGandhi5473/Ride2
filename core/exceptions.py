class RideTheTrendsError(Exception):
    """Base exception for the entire engine."""
    pass

class QuotaExceededError(RideTheTrendsError):
    """Raised when a platform (like YouTube) hits its daily API unit limit."""
    def __init__(self, platform, message="API Quota limit reached for the day."):
        self.platform = platform
        super().__init__(f"[{platform.upper()}] {message}")

class DatabaseConnectionError(RideTheTrendsError):
    """Raised when Neon/Postgres is unreachable or refusing connections."""
    pass

class ProviderAuthenticationError(RideTheTrendsError):
    """Raised when API keys are invalid or expired (BSky login, etc)."""
    pass

class TransformationError(RideTheTrendsError):
    """Raised when raw data fails to map to the Bronze/Silver format."""
    pass

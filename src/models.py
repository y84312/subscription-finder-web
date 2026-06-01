"""Data models for subscription finder."""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Transaction:
    """Single bank transaction."""
    id: str
    merchant_name: str
    amount: float
    currency: str
    date: date
    description: str = ""
    is_debit: bool = True


@dataclass
class DetectedSubscription:
    """A detected recurring subscription."""
    merchant_name: str
    amount: float
    currency: str
    frequency: str  # monthly, weekly, yearly, bi-weekly, quarterly, irregular
    occurrences: int
    first_seen: date
    last_seen: date
    total_spent: float
    confidence: float  # 0-1
    estimated_yearly_cost: float
    dates: list = field(default_factory=list)
    amounts: list = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        """Check if subscription appears active (charged in last 45 days)."""
        return (date.today() - self.last_seen).days <= 45

    @property
    def monthly_equivalent(self) -> float:
        """Convert to monthly equivalent for comparison."""
        multipliers = {
            "weekly": 4.33,
            "bi-weekly": 2.17,
            "monthly": 1.0,
            "quarterly": 0.33,
            "yearly": 0.083,
        }
        return self.amount * multipliers.get(self.frequency, 0)

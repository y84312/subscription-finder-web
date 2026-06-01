"""
Subscription detection algorithm.

Groups transactions by merchant, identifies recurring patterns,
scores subscription likelihood, and classifies frequency.
"""
import statistics
import re
from typing import Optional

from src.models import Transaction, DetectedSubscription


class SubscriptionDetector:
    """Detects subscriptions from a list of transactions."""

    # Common subscription merchants (Estonia-focused)
    KNOWN_SUBSCRIPTION_KEYWORDS = [
        "spotify", "netflix", "youtube", "google one", "apple", "icloud",
        "adobe", "microsoft", "github", "figma", "notion", "slack",
        "discord", "twitch", "amazon prime", "disney+", "hulu",
        "telia", "elis", "tele2", "top", "bite",
        "gym", "fitness", "spordiklubi",
        "kindl", "audible", "playlist", "tidal", "deezer",
        "dropbox", "onedrive", "pcloud", "zoom", "canva",
        "chatgpt", "openai", "claude", "anthropic",
        "patreon", "substack", "medium",
    ]

    # Merchant name cleanup patterns
    CLEANUP_PATTERNS = [
        (r'\bEE\b', ''),           # Country code
        (r'\bEUR\b', ''),          # Currency
        (r'\d{4,}', ''),           # Long numbers (card refs)
        (r'[^\w\s]', ' '),         # Special chars
        (r'\s+', ' '),             # Multiple spaces
    ]

    def __init__(
        self,
        amount_tolerance_pct: float = 5.0,
        min_occurrences: int = 2,
        monthly_range: tuple = (25, 35),
        weekly_range: tuple = (5, 9),
        yearly_range: tuple = (350, 380),
    ):
        self.amount_tolerance_pct = amount_tolerance_pct
        self.min_occurrences = min_occurrences
        self.monthly_range = monthly_range
        self.weekly_range = weekly_range
        self.yearly_range = yearly_range

    def detect(self, transactions: list[Transaction]) -> list[DetectedSubscription]:
        """Main detection pipeline."""
        # 1. Normalize merchant names
        normalized = [self._normalize_tx(tx) for tx in transactions]

        # 2. Group by merchant
        groups = self._group_by_merchant(normalized)

        # 3. Detect recurring patterns
        subscriptions = []
        for merchant, txs in groups.items():
            if len(txs) < self.min_occurrences:
                continue

            result = self._analyze_pattern(merchant, txs)
            if result:
                subscriptions.append(result)

        # 4. Sort by confidence (highest first)
        subscriptions.sort(key=lambda s: s.confidence, reverse=True)
        return subscriptions

    def _normalize_tx(self, tx: Transaction) -> Transaction:
        """Clean up merchant name for grouping."""
        name = tx.merchant_name.strip().upper()
        for pattern, repl in self.CLEANUP_PATTERNS:
            name = re.sub(pattern, repl, name, flags=re.IGNORECASE)
        name = name.strip()

        # Map known variations to canonical names
        name = self._canonical_merchant(name)

        return Transaction(
            id=tx.id,
            merchant_name=name,
            amount=tx.amount,
            currency=tx.currency,
            date=tx.date,
            description=tx.description,
            is_debit=tx.is_debit,
        )

    @staticmethod
    def _canonical_merchant(name: str) -> str:
        """Map merchant name variations to canonical form."""
        name_lower = name.lower().strip()

        mappings = {
            "spotify": ["spotify", "spotify ab", "spotify usa"],
            "netflix": ["netflix", "netflix.com"],
            "youtube": ["youtube", "youtube premium", "google youtube"],
            "google one": ["google one", "google one subscription"],
            "apple": ["apple.com/bill", "apple", "itunes"],
            "adobe": ["adobe", "adobe systems"],
            "microsoft": ["microsoft", "msft", "microsoft 365", "office 365"],
            "github": ["github", "github inc"],
            "figma": ["figma", "figma inc"],
            "notion": ["notion", "notion labs"],
            "slack": ["slack", "slack technologies"],
            "discord": ["discord", "discord inc"],
            "amazon prime": ["amazon prime", "amazon prime video"],
            "disney+": ["disney", "disney plus", "disney+"],
            "telia": ["telia", "telia eesti"],
            "tele2": ["tele2", "tele2 eesti"],
            "top": ["top eesti", "top telecom"],
            "bite": ["bite", "bite eesti"],
            "chatgpt": ["chatgpt", "openai", "open ai"],
        }

        for canonical, variations in mappings.items():
            for var in variations:
                if var in name_lower or name_lower in var:
                    return canonical.upper()

        return name

    def _group_by_merchant(self, transactions: list[Transaction]) -> dict[str, list[Transaction]]:
        """Group transactions by normalized merchant name."""
        groups: dict[str, list[Transaction]] = {}
        for tx in transactions:
            if not tx.is_debit:
                continue  # Only outgoing payments
            if tx.amount <= 0:
                continue

            key = tx.merchant_name
            if key not in groups:
                groups[key] = []
            groups[key].append(tx)

        # Sort each group by date
        for key in groups:
            groups[key].sort(key=lambda t: t.date)

        return groups

    def _analyze_pattern(
        self, merchant: str, transactions: list[Transaction]
    ) -> Optional[DetectedSubscription]:
        """Analyze a group of transactions for recurring patterns."""
        if len(transactions) < self.min_occurrences:
            return None

        amounts = [tx.amount for tx in transactions]
        dates = [tx.date for tx in transactions]

        # Check amount consistency
        avg_amount = statistics.mean(amounts)
        if avg_amount == 0:
            return None

        amount_cv = (statistics.stdev(amounts) / avg_amount * 100) if len(amounts) > 1 else 0
        if amount_cv > self.amount_tolerance_pct:
            return None  # Too varied to be a subscription

        # Calculate day gaps between consecutive transactions
        gaps = []
        for i in range(1, len(dates)):
            gap = (dates[i] - dates[i - 1]).days
            if gap > 0:
                gaps.append(gap)

        if not gaps:
            return None

        avg_gap = statistics.mean(gaps)
        frequency = self._classify_frequency(avg_gap)

        if frequency == "irregular":
            return None

        # Calculate confidence score
        confidence = self._calculate_confidence(
            merchant=merchant,
            occurrences=len(transactions),
            amount_cv=amount_cv,
            gaps=gaps,
            frequency=frequency,
        )

        total_spent = sum(amounts)
        estimated_yearly = self._estimate_yearly(avg_amount, frequency)

        return DetectedSubscription(
            merchant_name=merchant,
            amount=round(avg_amount, 2),
            currency=transactions[0].currency,
            frequency=frequency,
            occurrences=len(transactions),
            first_seen=dates[0],
            last_seen=dates[-1],
            total_spent=round(total_spent, 2),
            confidence=round(confidence, 3),
            estimated_yearly_cost=round(estimated_yearly, 2),
        )

    def _classify_frequency(self, avg_gap_days: float) -> str:
        """Classify payment frequency from average gap."""
        lo, hi = self.monthly_range
        if lo <= avg_gap_days <= hi:
            return "monthly"

        lo, hi = self.weekly_range
        if lo <= avg_gap_days <= hi:
            return "weekly"

        lo, hi = self.yearly_range
        if lo <= avg_gap_days <= hi:
            return "yearly"

        # Check for bi-weekly (10-18 days)
        if 10 <= avg_gap_days <= 18:
            return "bi-weekly"

        # Check for quarterly (80-100 days)
        if 80 <= avg_gap_days <= 100:
            return "quarterly"

        return "irregular"

    def _calculate_confidence(
        self,
        merchant: str,
        occurrences: int,
        amount_cv: float,
        gaps: list[int],
        frequency: str,
    ) -> float:
        """Calculate subscription confidence score (0-1)."""
        score = 0.0

        # More occurrences = higher confidence
        if occurrences >= 6:
            score += 0.3
        elif occurrences >= 4:
            score += 0.2
        elif occurrences >= 2:
            score += 0.1

        # Low coefficient of variation = amount is consistent
        if amount_cv < 1:
            score += 0.3
        elif amount_cv < 3:
            score += 0.2
        elif amount_cv < 5:
            score += 0.1

        # Low gap variance = regular timing
        if len(gaps) > 1:
            gap_std = statistics.stdev(gaps)
            gap_cv = gap_std / statistics.mean(gaps) * 100
            if gap_cv < 5:
                score += 0.2
            elif gap_cv < 10:
                score += 0.1

        # Monthly/weekly/yearly > irregular
        if frequency in ("monthly", "weekly"):
            score += 0.1
        elif frequency == "yearly":
            score += 0.05

        # Check against known subscription keywords
        merchant_lower = merchant.lower()
        for kw in self.KNOWN_SUBSCRIPTION_KEYWORDS:
            if kw in merchant_lower:
                score += 0.1
                break

        return min(score, 1.0)

    @staticmethod
    def _estimate_yearly(amount: float, frequency: str) -> float:
        """Estimate yearly cost from frequency and amount."""
        multipliers = {
            "weekly": 52,
            "bi-weekly": 26,
            "monthly": 12,
            "quarterly": 4,
            "yearly": 1,
        }
        return amount * multipliers.get(frequency, 0)

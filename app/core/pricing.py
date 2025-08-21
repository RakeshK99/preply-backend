from typing import Dict, Any, List
from dataclasses import dataclass


@dataclass
class SubscriptionPlan:
    """Subscription plan configuration"""
    key: str
    name: str
    description: str
    price_cents: int
    interval: str  # "month" or "year"
    monthly_credits: int
    ai_features: Dict[str, Any]
    stripe_price_id: str = ""


@dataclass
class CreditPack:
    """Credit pack configuration"""
    key: str
    name: str
    description: str
    credits: int
    price_cents: int
    discount_percentage: float = 0.0


@dataclass
class AIUsageLimits:
    """AI usage limits per subscription plan"""
    qa_requests_per_month: int
    summaries_per_month: int
    flashcards_per_month: int
    quizzes_per_month: int
    max_tokens_per_request: int


# Subscription Plans
SUBSCRIPTION_PLANS = {
    "starter": SubscriptionPlan(
        key="starter",
        name="Starter",
        description="Perfect for students getting started with tutoring",
        price_cents=1999,  # $19.99/month
        interval="month",
        monthly_credits=2,
        ai_features={
            "qa_requests_per_month": 50,
            "summaries_per_month": 10,
            "flashcards_per_month": 5,
            "quizzes_per_month": 3,
            "max_tokens_per_request": 2000
        },
        stripe_price_id="price_starter_monthly"
    ),
    "pro": SubscriptionPlan(
        key="pro",
        name="Pro",
        description="For serious students who want to excel",
        price_cents=3999,  # $39.99/month
        interval="month",
        monthly_credits=5,
        ai_features={
            "qa_requests_per_month": 200,
            "summaries_per_month": 25,
            "flashcards_per_month": 15,
            "quizzes_per_month": 10,
            "max_tokens_per_request": 4000
        },
        stripe_price_id="price_pro_monthly"
    ),
    "premium": SubscriptionPlan(
        key="premium",
        name="Premium",
        description="Unlimited access for power users",
        price_cents=7999,  # $79.99/month
        interval="month",
        monthly_credits=10,
        ai_features={
            "qa_requests_per_month": -1,  # Unlimited
            "summaries_per_month": -1,  # Unlimited
            "flashcards_per_month": -1,  # Unlimited
            "quizzes_per_month": -1,  # Unlimited
            "max_tokens_per_request": 8000
        },
        stripe_price_id="price_premium_monthly"
    )
}

# Credit Packs
CREDIT_PACKS = {
    "starter": CreditPack(
        key="starter",
        name="Starter Pack",
        description="Perfect for trying out tutoring sessions",
        credits=5,
        price_cents=2500,  # $25.00
        discount_percentage=0.0
    ),
    "popular": CreditPack(
        key="popular",
        name="Popular Pack",
        description="Most popular choice for regular students",
        credits=10,
        price_cents=4500,  # $45.00
        discount_percentage=10.0  # 10% discount
    ),
    "premium": CreditPack(
        key="premium",
        name="Premium Pack",
        description="Best value for serious learners",
        credits=20,
        price_cents=8000,  # $80.00
        discount_percentage=20.0  # 20% discount
    )
}

# Pay-as-you-go pricing
PAY_AS_YOU_GO_RATES = {
    "default": 5000,  # $50.00 per session
    "discounted": 4000,  # $40.00 per session (for subscribers)
}

# AI Usage Limits by Plan
AI_USAGE_LIMITS = {
    "starter": AIUsageLimits(
        qa_requests_per_month=50,
        summaries_per_month=10,
        flashcards_per_month=5,
        quizzes_per_month=3,
        max_tokens_per_request=2000
    ),
    "pro": AIUsageLimits(
        qa_requests_per_month=200,
        summaries_per_month=25,
        flashcards_per_month=15,
        quizzes_per_month=10,
        max_tokens_per_request=4000
    ),
    "premium": AIUsageLimits(
        qa_requests_per_month=-1,  # Unlimited
        summaries_per_month=-1,  # Unlimited
        flashcards_per_month=-1,  # Unlimited
        quizzes_per_month=-1,  # Unlimited
        max_tokens_per_request=8000
    ),
    "free": AIUsageLimits(
        qa_requests_per_month=5,
        summaries_per_month=1,
        flashcards_per_month=1,
        quizzes_per_month=1,
        max_tokens_per_request=1000
    )
}


def get_subscription_plan(plan_key: str) -> SubscriptionPlan:
    """Get subscription plan by key"""
    return SUBSCRIPTION_PLANS.get(plan_key)


def get_credit_pack(pack_key: str) -> CreditPack:
    """Get credit pack by key"""
    return CREDIT_PACKS.get(pack_key)


def get_ai_usage_limits(plan_key: str) -> AIUsageLimits:
    """Get AI usage limits by plan key"""
    return AI_USAGE_LIMITS.get(plan_key, AI_USAGE_LIMITS["free"])


def get_all_subscription_plans() -> List[SubscriptionPlan]:
    """Get all subscription plans"""
    return list(SUBSCRIPTION_PLANS.values())


def get_all_credit_packs() -> List[CreditPack]:
    """Get all credit packs"""
    return list(CREDIT_PACKS.values())


def calculate_credit_pack_price(pack_key: str, quantity: int = 1) -> int:
    """Calculate total price for credit pack with quantity"""
    pack = get_credit_pack(pack_key)
    if not pack:
        return 0
    
    base_price = pack.price_cents
    if pack.discount_percentage > 0:
        discount = base_price * (pack.discount_percentage / 100)
        base_price = base_price - discount
    
    return int(base_price * quantity)


def get_pay_as_you_go_rate(has_subscription: bool = False) -> int:
    """Get pay-as-you-go rate based on subscription status"""
    if has_subscription:
        return PAY_AS_YOU_GO_RATES["discounted"]
    return PAY_AS_YOU_GO_RATES["default"]

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, Field
import json

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.pricing import get_all_credit_packs, calculate_credit_pack_price
from app.models.user import User, UserRole
from app.models.stripe_models import StripeSubscription, SubscriptionStatus
from app.models.payment import Payment, PaymentType, PaymentStatus
from app.models.credit_ledger import CreditLedger, CreditReason
from app.models.student_profile import StudentProfile
from app.services.stripe_service import StripeService
from app.core.exceptions import PaymentError, SubscriptionError

router = APIRouter()


# Pydantic models for request/response
class SubscriptionPlanResponse(BaseModel):
    key: str
    name: str
    description: str
    price_cents: int
    currency: str
    interval: str
    monthly_credits: int
    ai_features: dict
    stripe_price_id: str


class CheckoutSessionResponse(BaseModel):
    session_id: str
    checkout_url: str


class PaymentIntentResponse(BaseModel):
    payment_intent_id: str
    client_secret: str
    amount: int
    currency: str


class SubscriptionResponse(BaseModel):
    subscription_id: str
    status: str
    plan_key: str
    current_period_end: str
    created_at: str


class PaymentResponse(BaseModel):
    payment_id: str
    amount_cents: int
    type: str
    status: str
    created_at: str


class CreditBalanceResponse(BaseModel):
    balance: int
    ledger_entries: List[dict]


class CreditPackRequest(BaseModel):
    credit_amount: int = Field(..., description="Number of credits to purchase")
    price_cents: int = Field(..., description="Price in cents")


# Subscription Endpoints
@router.get("/plans", response_model=List[SubscriptionPlanResponse])
async def get_subscription_plans(
    current_user: User = Depends(get_current_user)
):
    """Get available subscription plans"""
    try:
        stripe_service = StripeService()
        plans = await stripe_service.get_subscription_plans()
        
        return [
            SubscriptionPlanResponse(
                key=plan["key"],
                name=plan["name"],
                description=plan["description"],
                price_cents=plan["price_cents"],
                currency=plan["currency"],
                interval=plan["interval"],
                monthly_credits=plan["monthly_credits"],
                ai_features=plan["ai_features"],
                stripe_price_id=plan["stripe_price_id"]
            )
            for plan in plans
        ]
        
    except PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/subscription/checkout", response_model=CheckoutSessionResponse)
async def create_subscription_checkout(
    plan_key: str = Body(..., embed=True),
    success_url: str = Body(..., embed=True),
    cancel_url: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create Stripe Checkout session for subscription"""
    try:
        from app.core.pricing import get_subscription_plan
        
        # Get plan configuration
        plan = get_subscription_plan(plan_key)
        if not plan:
            raise HTTPException(status_code=400, detail="Invalid plan key")
        
        stripe_service = StripeService()
        result = await stripe_service.create_subscription_checkout_session(
            user=current_user,
            price_id=plan.stripe_price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            db_session=db
        )
        
        return CheckoutSessionResponse(
            session_id=result["session_id"],
            checkout_url=result["checkout_url"]
        )
        
    except PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/subscriptions", response_model=List[SubscriptionResponse])
async def get_user_subscriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's subscriptions"""
    try:
        subscriptions = await db.execute(
            select(StripeSubscription).where(
                and_(
                    StripeSubscription.user_id == str(current_user.id),
                    StripeSubscription.deleted_at.is_(None)
                )
            ).order_by(StripeSubscription.created_at.desc())
        ).scalars().all()
        
        return [
            SubscriptionResponse(
                subscription_id=str(subscription.id),
                status=subscription.status.value,
                plan_key=subscription.plan_key,
                current_period_end=subscription.current_period_end.isoformat(),
                created_at=subscription.created_at.isoformat()
            )
            for subscription in subscriptions
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/subscription/cancel")
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel user's active subscription"""
    try:
        stripe_service = StripeService()
        success = await stripe_service.cancel_subscription(current_user, db)
        
        if success:
            return {"message": "Subscription canceled successfully"}
        else:
            raise HTTPException(status_code=400, detail="Failed to cancel subscription")
        
    except SubscriptionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/customer-portal")
async def get_customer_portal_url(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get Stripe Customer Portal URL"""
    try:
        stripe_service = StripeService()
        portal_url = await stripe_service.get_customer_portal_url(current_user, db)
        
        return {"portal_url": portal_url}
        
    except PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Payment Intent Endpoints
@router.post("/payment-intent", response_model=PaymentIntentResponse)
async def create_payment_intent(
    amount_cents: int = Body(..., embed=True),
    description: str = Body(..., embed=True),
    metadata: Optional[dict] = Body({}, embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create Stripe PaymentIntent for one-time payment"""
    try:
        stripe_service = StripeService()
        result = await stripe_service.create_payment_intent(
            user=current_user,
            amount_cents=amount_cents,
            description=description,
            metadata=metadata,
            db_session=db
        )
        
        return PaymentIntentResponse(
            payment_intent_id=result["payment_intent_id"],
            client_secret=result["client_secret"],
            amount=result["amount"],
            currency=result["currency"]
        )
        
    except PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Credit Pack Endpoints
@router.post("/credit-pack/checkout", response_model=CheckoutSessionResponse)
async def create_credit_pack_checkout(
    request: CreditPackRequest,
    success_url: str = Body(..., embed=True),
    cancel_url: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create Stripe Checkout session for credit pack purchase"""
    try:
        stripe_service = StripeService()
        result = await stripe_service.create_credit_pack_checkout(
            user=current_user,
            credit_amount=request.credit_amount,
            price_cents=request.price_cents,
            success_url=success_url,
            cancel_url=cancel_url,
            db_session=db
        )
        
        return CheckoutSessionResponse(
            session_id=result["session_id"],
            checkout_url=result["checkout_url"]
        )
        
    except PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Credit Management Endpoints
@router.get("/credits/balance", response_model=CreditBalanceResponse)
async def get_credit_balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's credit balance and ledger"""
    try:
        # Get student profile
        student_profile = await db.execute(
            select(StudentProfile).where(StudentProfile.user_id == str(current_user.id))
        ).scalar_one_or_none()
        
        balance = student_profile.credit_balance if student_profile else 0
        
        # Get recent ledger entries
        ledger_entries = await db.execute(
            select(CreditLedger).where(
                and_(
                    CreditLedger.user_id == str(current_user.id),
                    CreditLedger.deleted_at.is_(None)
                )
            ).order_by(CreditLedger.created_at.desc()).limit(10)
        ).scalars().all()
        
        ledger_data = [
            {
                "id": str(entry.id),
                "delta": entry.delta,
                "reason": entry.reason.value,
                "balance_after": entry.balance_after,
                "created_at": entry.created_at.isoformat()
            }
            for entry in ledger_entries
        ]
        
        return CreditBalanceResponse(
            balance=balance,
            ledger_entries=ledger_data
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/credits/ledger", response_model=List[dict])
async def get_credit_ledger(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's credit ledger entries"""
    try:
        ledger_entries = await db.execute(
            select(CreditLedger).where(
                and_(
                    CreditLedger.user_id == str(current_user.id),
                    CreditLedger.deleted_at.is_(None)
                )
            ).order_by(CreditLedger.created_at.desc()).offset(offset).limit(limit)
        ).scalars().all()
        
        return [
            {
                "id": str(entry.id),
                "delta": entry.delta,
                "reason": entry.reason.value,
                "balance_after": entry.balance_after,
                "created_at": entry.created_at.isoformat()
            }
            for entry in ledger_entries
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Payment History Endpoints
@router.get("/payments", response_model=List[PaymentResponse])
async def get_payment_history(
    payment_type: Optional[PaymentType] = Query(None),
    status: Optional[PaymentStatus] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's payment history"""
    try:
        query = select(Payment).where(
            and_(
                Payment.user_id == str(current_user.id),
                Payment.deleted_at.is_(None)
            )
        )
        
        if payment_type:
            query = query.where(Payment.type == payment_type)
        
        if status:
            query = query.where(Payment.status == status)
        
        query = query.order_by(Payment.created_at.desc())
        
        payments = await db.execute(query).scalars().all()
        
        return [
            PaymentResponse(
                payment_id=str(payment.id),
                amount_cents=payment.amount_cents,
                type=payment.type.value,
                status=payment.status.value,
                created_at=payment.created_at.isoformat()
            )
            for payment in payments
        ]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Webhook Endpoint
@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle Stripe webhook events"""
    try:
        # Get the raw body
        body = await request.body()
        
        # Get the signature from headers
        signature = request.headers.get("stripe-signature")
        
        if not signature:
            raise HTTPException(status_code=400, detail="Missing stripe-signature header")
        
        # Process webhook
        stripe_service = StripeService()
        success = await stripe_service.process_webhook(body, signature, db)
        
        if success:
            return {"status": "success"}
        else:
            raise HTTPException(status_code=400, detail="Webhook processing failed")
        
    except PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Admin Endpoints (for managing credits)
@router.post("/admin/credits/add")
async def admin_add_credits(
    user_id: str = Body(..., embed=True),
    amount: int = Body(..., embed=True),
    reason: str = Body("manual", embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin endpoint to add credits to user (requires admin role)"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        stripe_service = StripeService()
        await stripe_service._add_credits(user_id, amount, reason, db)
        
        return {"message": f"Added {amount} credits to user {user_id}"}
        
    except PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/credits/deduct")
async def admin_deduct_credits(
    user_id: str = Body(..., embed=True),
    amount: int = Body(..., embed=True),
    reason: str = Body("manual", embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Admin endpoint to deduct credits from user (requires admin role)"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        stripe_service = StripeService()
        success = await stripe_service.deduct_credits(user_id, amount, reason, db)
        
        if success:
            return {"message": f"Deducted {amount} credits from user {user_id}"}
        else:
            raise HTTPException(status_code=400, detail="Insufficient credits")
        
    except PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Credit Pack Templates
@router.get("/credit-packs")
async def get_credit_pack_templates():
    """Get available credit pack templates"""
    try:
        credit_packs = get_all_credit_packs()
        
        return {
            "credit_packs": [
                {
                    "key": pack.key,
                    "name": pack.name,
                    "description": pack.description,
                    "credits": pack.credits,
                    "price_cents": pack.price_cents,
                    "discount_percentage": pack.discount_percentage
                }
                for pack in credit_packs
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Subscription Status Endpoint
@router.get("/subscription/status")
async def get_subscription_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's subscription status and limits"""
    try:
        stripe_service = StripeService()
        status = await stripe_service.get_user_subscription_status(str(current_user.id), db)
        
        return status
        
    except PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# Booking Payment Endpoint
@router.post("/booking/payment-intent", response_model=PaymentIntentResponse)
async def create_booking_payment_intent(
    tutor_rate_cents: int = Body(..., embed=True),
    booking_id: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create PaymentIntent for booking payment"""
    try:
        stripe_service = StripeService()
        result = await stripe_service.create_booking_payment_intent(
            user=current_user,
            tutor_rate_cents=tutor_rate_cents,
            booking_id=booking_id,
            db_session=db
        )
        
        return PaymentIntentResponse(
            payment_intent_id=result["payment_intent_id"],
            client_secret=result["client_secret"],
            amount=result["amount"],
            currency=result["currency"]
        )
        
    except PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

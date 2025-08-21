from fastapi import APIRouter, Request, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Dict, Any
import stripe
import json
import uuid
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from app.models.stripe_models import StripeCustomer, StripeSubscription, SubscriptionStatus
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.credit_ledger import CreditLedger, CreditReason
from app.services.stripe_service import StripeService

router = APIRouter()

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle all Stripe webhook events with signature verification and idempotency"""
    try:
        # Get the raw body
        body = await request.body()
        signature = request.headers.get("stripe-signature")
        
        if not signature:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Stripe signature"
            )
        
        # Verify webhook signature
        try:
            event = stripe.Webhook.construct_event(
                body, signature, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payload"
            )
        except stripe.error.SignatureVerificationError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signature"
            )
        
        # Check idempotency
        event_id = event.get("id")
        if event_id:
            # Check if we've already processed this event
            existing_payment = await db.execute(
                select(Payment).where(Payment.stripe_event_id == event_id)
            )
            if existing_payment.scalar_one_or_none():
                return {"status": "already_processed"}
        
        # Process the event
        event_type = event.get("type")
        event_data = event.get("data", {}).get("object", {})
        
        stripe_service = StripeService()
        
        if event_type == "checkout.session.completed":
            await handle_checkout_session_completed(event_data, db, stripe_service)
            
        elif event_type == "customer.subscription.created":
            await handle_subscription_created(event_data, db, stripe_service)
            
        elif event_type == "customer.subscription.updated":
            await handle_subscription_updated(event_data, db, stripe_service)
            
        elif event_type == "customer.subscription.deleted":
            await handle_subscription_deleted(event_data, db, stripe_service)
            
        elif event_type == "invoice.payment_succeeded":
            await handle_invoice_payment_succeeded(event_data, db, stripe_service)
            
        elif event_type == "invoice.payment_failed":
            await handle_invoice_payment_failed(event_data, db, stripe_service)
            
        elif event_type == "payment_intent.succeeded":
            await handle_payment_intent_succeeded(event_data, db, stripe_service)
            
        elif event_type == "payment_intent.payment_failed":
            await handle_payment_intent_failed(event_data, db, stripe_service)
        
        # Record the event processing
        payment_record = Payment(
            id=uuid.uuid4(),
            user_id=None,  # Will be set based on event type
            amount_cents=0,  # Will be set based on event type
            currency="usd",
            type=PaymentType.STRIPE_WEBHOOK,
            status=PaymentStatus.PROCESSED,
            stripe_event_id=event_id,
            stripe_payment_intent_id=event_data.get("id"),
            metadata={"event_type": event_type, "event_data": event_data},
            created_at=datetime.now(timezone.utc)
        )
        
        db.add(payment_record)
        await db.commit()
        
        return {"status": "success"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Webhook processing failed: {str(e)}"
        )


async def handle_checkout_session_completed(event_data: Dict[str, Any], db: AsyncSession, stripe_service: StripeService):
    """Handle checkout.session.completed event"""
    session = event_data
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    
    if customer_id and subscription_id:
        # Get or create Stripe customer
        customer = await stripe_service.get_or_create_stripe_customer(customer_id, db)
        
        # Get subscription details
        subscription = stripe.Subscription.retrieve(subscription_id)
        
        # Create or update subscription record
        await stripe_service.create_or_update_subscription(
            customer.user_id,
            subscription,
            db
        )


async def handle_subscription_created(event_data: Dict[str, Any], db: AsyncSession, stripe_service: StripeService):
    """Handle customer.subscription.created event"""
    subscription = event_data
    customer_id = subscription.get("customer")
    
    if customer_id:
        customer = await stripe_service.get_stripe_customer(customer_id, db)
        if customer:
            await stripe_service.create_or_update_subscription(
                customer.user_id,
                subscription,
                db
            )


async def handle_subscription_updated(event_data: Dict[str, Any], db: AsyncSession, stripe_service: StripeService):
    """Handle customer.subscription.updated event"""
    subscription = event_data
    customer_id = subscription.get("customer")
    
    if customer_id:
        customer = await stripe_service.get_stripe_customer(customer_id, db)
        if customer:
            await stripe_service.create_or_update_subscription(
                customer.user_id,
                subscription,
                db
            )


async def handle_subscription_deleted(event_data: Dict[str, Any], db: AsyncSession, stripe_service: StripeService):
    """Handle customer.subscription.deleted event"""
    subscription = event_data
    customer_id = subscription.get("customer")
    
    if customer_id:
        customer = await stripe_service.get_stripe_customer(customer_id, db)
        if customer:
            # Update subscription status to cancelled
            await stripe_service.update_subscription_status(
                customer.user_id,
                SubscriptionStatus.CANCELLED,
                db
            )


async def handle_invoice_payment_succeeded(event_data: Dict[str, Any], db: AsyncSession, stripe_service: StripeService):
    """Handle invoice.payment_succeeded event"""
    invoice = event_data
    customer_id = invoice.get("customer")
    subscription_id = invoice.get("subscription")
    
    if customer_id and subscription_id:
        customer = await stripe_service.get_stripe_customer(customer_id, db)
        if customer:
            # Grant monthly credits
            await stripe_service.grant_monthly_credits(customer.user_id, db)
            
            # Record payment
            payment = Payment(
                id=uuid.uuid4(),
                user_id=customer.user_id,
                amount_cents=invoice.get("amount_paid", 0),
                currency=invoice.get("currency", "usd"),
                type=PaymentType.SUBSCRIPTION,
                status=PaymentStatus.SUCCEEDED,
                stripe_invoice_id=invoice.get("id"),
                stripe_subscription_id=subscription_id,
                created_at=datetime.now(timezone.utc)
            )
            db.add(payment)


async def handle_invoice_payment_failed(event_data: Dict[str, Any], db: AsyncSession, stripe_service: StripeService):
    """Handle invoice.payment_failed event"""
    invoice = event_data
    customer_id = invoice.get("customer")
    
    if customer_id:
        customer = await stripe_service.get_stripe_customer(customer_id, db)
        if customer:
            # Record failed payment
            payment = Payment(
                id=uuid.uuid4(),
                user_id=customer.user_id,
                amount_cents=invoice.get("amount_due", 0),
                currency=invoice.get("currency", "usd"),
                type=PaymentType.SUBSCRIPTION,
                status=PaymentStatus.FAILED,
                stripe_invoice_id=invoice.get("id"),
                created_at=datetime.now(timezone.utc)
            )
            db.add(payment)


async def handle_payment_intent_succeeded(event_data: Dict[str, Any], db: AsyncSession, stripe_service: StripeService):
    """Handle payment_intent.succeeded event"""
    payment_intent = event_data
    customer_id = payment_intent.get("customer")
    
    if customer_id:
        customer = await stripe_service.get_stripe_customer(customer_id, db)
        if customer:
            # Record successful payment
            payment = Payment(
                id=uuid.uuid4(),
                user_id=customer.user_id,
                amount_cents=payment_intent.get("amount", 0),
                currency=payment_intent.get("currency", "usd"),
                type=PaymentType.CREDIT_PACK if "credit_pack" in payment_intent.get("metadata", {}) else PaymentType.BOOKING,
                status=PaymentStatus.SUCCEEDED,
                stripe_payment_intent_id=payment_intent.get("id"),
                metadata=payment_intent.get("metadata"),
                created_at=datetime.now(timezone.utc)
            )
            db.add(payment)
            
            # Add credits if it's a credit pack purchase
            if payment.type == PaymentType.CREDIT_PACK:
                credit_amount = int(payment_intent.get("metadata", {}).get("credit_amount", 0))
                if credit_amount > 0:
                    await stripe_service.add_credits(
                        customer.user_id,
                        credit_amount,
                        CreditReason.CREDIT_PACK,
                        db
                    )


async def handle_payment_intent_failed(event_data: Dict[str, Any], db: AsyncSession, stripe_service: StripeService):
    """Handle payment_intent.payment_failed event"""
    payment_intent = event_data
    customer_id = payment_intent.get("customer")
    
    if customer_id:
        customer = await stripe_service.get_stripe_customer(customer_id, db)
        if customer:
            # Record failed payment
            payment = Payment(
                id=uuid.uuid4(),
                user_id=customer.user_id,
                amount_cents=payment_intent.get("amount", 0),
                currency=payment_intent.get("currency", "usd"),
                type=PaymentType.CREDIT_PACK if "credit_pack" in payment_intent.get("metadata", {}) else PaymentType.BOOKING,
                status=PaymentStatus.FAILED,
                stripe_payment_intent_id=payment_intent.get("id"),
                metadata=payment_intent.get("metadata"),
                created_at=datetime.now(timezone.utc)
            )
            db.add(payment)

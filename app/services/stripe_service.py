from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import stripe
import logging
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.config import settings
from app.core.pricing import (
    get_subscription_plan, get_credit_pack, get_ai_usage_limits,
    calculate_credit_pack_price, get_pay_as_you_go_rate
)
from app.models.user import User
from app.models.stripe_models import StripeCustomer, StripeSubscription, SubscriptionStatus
from app.models.payment import Payment, PaymentType, PaymentStatus
from app.models.credit_ledger import CreditLedger, CreditReason
from app.models.student_profile import StudentProfile
from app.core.exceptions import PaymentError, SubscriptionError

logger = logging.getLogger(__name__)


class StripeService:
    """Comprehensive Stripe service for payment processing and subscription management"""
    
    def __init__(self):
        stripe.api_key = settings.STRIPE_SECRET_KEY
        self.webhook_secret = settings.STRIPE_WEBHOOK_SECRET
    
    async def create_customer(self, user: User, db_session: AsyncSession) -> StripeCustomer:
        """Create Stripe customer for user"""
        try:
            # Check if customer already exists
            existing_customer = await db_session.execute(
                select(StripeCustomer).where(StripeCustomer.user_id == str(user.id))
            ).scalar_one_or_none()
            
            if existing_customer:
                return existing_customer
            
            # Create customer in Stripe
            customer = stripe.Customer.create(
                email=user.email,
                name=user.name,
                metadata={
                    "user_id": str(user.id),
                    "role": user.role.value
                }
            )
            
            # Save to database
            stripe_customer = StripeCustomer(
                user_id=str(user.id),
                stripe_customer_id=customer.id
            )
            
            db_session.add(stripe_customer)
            await db_session.commit()
            await db_session.refresh(stripe_customer)
            
            logger.info(f"Created Stripe customer {customer.id} for user {user.id}")
            return stripe_customer
            
        except Exception as e:
            logger.error(f"Error creating Stripe customer for user {user.id}: {e}")
            raise PaymentError(f"Failed to create Stripe customer: {str(e)}")
    
    async def create_subscription_checkout_session(
        self,
        user: User,
        price_id: str,
        success_url: str,
        cancel_url: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """Create Stripe Checkout session for subscription"""
        try:
            # Ensure customer exists
            customer = await self.create_customer(user, db_session)
            
            # Create checkout session
            session = stripe.checkout.Session.create(
                customer=customer.stripe_customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": str(user.id),
                    "price_id": price_id
                },
                subscription_data={
                    "metadata": {
                        "user_id": str(user.id)
                    }
                }
            )
            
            logger.info(f"Created subscription checkout session {session.id} for user {user.id}")
            return {
                "session_id": session.id,
                "checkout_url": session.url
            }
            
        except Exception as e:
            logger.error(f"Error creating subscription checkout session for user {user.id}: {e}")
            raise PaymentError(f"Failed to create checkout session: {str(e)}")
    
    async def create_payment_intent(
        self,
        user: User,
        amount_cents: int,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
        db_session: AsyncSession = None
    ) -> Dict[str, Any]:
        """Create Stripe PaymentIntent for one-time payment"""
        try:
            # Ensure customer exists
            customer = await self.create_customer(user, db_session)
            
            # Create payment intent
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency='usd',
                customer=customer.stripe_customer_id,
                description=description,
                metadata=metadata or {},
                automatic_payment_methods={
                    'enabled': True,
                }
            )
            
            logger.info(f"Created payment intent {intent.id} for user {user.id}")
            return {
                "payment_intent_id": intent.id,
                "client_secret": intent.client_secret,
                "amount": intent.amount,
                "currency": intent.currency
            }
            
        except Exception as e:
            logger.error(f"Error creating payment intent for user {user.id}: {e}")
            raise PaymentError(f"Failed to create payment intent: {str(e)}")
    
    async def create_credit_pack_checkout(
        self,
        user: User,
        credit_amount: int,
        price_cents: int,
        success_url: str,
        cancel_url: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """Create Stripe Checkout session for credit pack purchase"""
        try:
            # Ensure customer exists
            customer = await self.create_customer(user, db_session)
            
            # Create checkout session
            session = stripe.checkout.Session.create(
                customer=customer.stripe_customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': f'{credit_amount} Credits',
                            'description': f'Credit pack for {credit_amount} tutoring sessions'
                        },
                        'unit_amount': price_cents,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": str(user.id),
                    "credit_amount": credit_amount,
                    "payment_type": "credit_pack"
                }
            )
            
            logger.info(f"Created credit pack checkout session {session.id} for user {user.id}")
            return {
                "session_id": session.id,
                "checkout_url": session.url
            }
            
        except Exception as e:
            logger.error(f"Error creating credit pack checkout for user {user.id}: {e}")
            raise PaymentError(f"Failed to create credit pack checkout: {str(e)}")
    
    async def process_webhook(
        self,
        payload: bytes,
        signature: str,
        db_session: AsyncSession
    ) -> bool:
        """Process Stripe webhook events"""
        try:
            # Verify webhook signature
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            
            logger.info(f"Processing webhook event: {event['type']}")
            
            # Handle different event types
            if event['type'] == 'checkout.session.completed':
                await self._handle_checkout_completed(event, db_session)
            elif event['type'] == 'customer.subscription.created':
                await self._handle_subscription_created(event, db_session)
            elif event['type'] == 'customer.subscription.updated':
                await self._handle_subscription_updated(event, db_session)
            elif event['type'] == 'customer.subscription.deleted':
                await self._handle_subscription_deleted(event, db_session)
            elif event['type'] == 'invoice.payment_succeeded':
                await self._handle_invoice_payment_succeeded(event, db_session)
            elif event['type'] == 'invoice.payment_failed':
                await self._handle_invoice_payment_failed(event, db_session)
            elif event['type'] == 'payment_intent.succeeded':
                await self._handle_payment_intent_succeeded(event, db_session)
            elif event['type'] == 'payment_intent.payment_failed':
                await self._handle_payment_intent_failed(event, db_session)
            else:
                logger.info(f"Unhandled webhook event type: {event['type']}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            raise PaymentError(f"Failed to process webhook: {str(e)}")
    
    async def _handle_checkout_completed(self, event: Dict[str, Any], db_session: AsyncSession):
        """Handle checkout.session.completed event"""
        try:
            session = event['data']['object']
            user_id = session['metadata'].get('user_id')
            
            if not user_id:
                logger.warning("No user_id in checkout session metadata")
                return
            
            # Handle different checkout types
            if session['mode'] == 'subscription':
                # Subscription will be handled by subscription.created event
                logger.info(f"Subscription checkout completed for user {user_id}")
            elif session['mode'] == 'payment':
                # Handle one-time payment (credit pack)
                await self._process_credit_pack_payment(session, user_id, db_session)
            
        except Exception as e:
            logger.error(f"Error handling checkout completed: {e}")
    
    async def _handle_subscription_created(self, event: Dict[str, Any], db_session: AsyncSession):
        """Handle customer.subscription.created event"""
        try:
            subscription = event['data']['object']
            user_id = subscription['metadata'].get('user_id')
            
            if not user_id:
                logger.warning("No user_id in subscription metadata")
                return
            
            # Create subscription record
            stripe_subscription = StripeSubscription(
                user_id=user_id,
                stripe_subscription_id=subscription['id'],
                status=SubscriptionStatus.ACTIVE,
                current_period_end=datetime.fromtimestamp(subscription['current_period_end'], tz=timezone.utc),
                plan_key=self._get_plan_key_from_price_id(subscription['items']['data'][0]['price']['id'])
            )
            
            db_session.add(stripe_subscription)
            await db_session.commit()
            
            # Grant monthly credits based on plan
            await self._grant_monthly_credits(user_id, stripe_subscription.plan_key, db_session)
            
            logger.info(f"Subscription created for user {user_id}: {subscription['id']}")
            
        except Exception as e:
            logger.error(f"Error handling subscription created: {e}")
    
    async def _handle_subscription_updated(self, event: Dict[str, Any], db_session: AsyncSession):
        """Handle customer.subscription.updated event"""
        try:
            subscription = event['data']['object']
            user_id = subscription['metadata'].get('user_id')
            
            if not user_id:
                return
            
            # Update subscription record
            stripe_subscription = await db_session.execute(
                select(StripeSubscription).where(
                    StripeSubscription.stripe_subscription_id == subscription['id']
                )
            ).scalar_one_or_none()
            
            if stripe_subscription:
                stripe_subscription.status = SubscriptionStatus(subscription['status'])
                stripe_subscription.current_period_end = datetime.fromtimestamp(
                    subscription['current_period_end'], tz=timezone.utc
                )
                await db_session.commit()
                
                logger.info(f"Subscription updated for user {user_id}: {subscription['id']}")
            
        except Exception as e:
            logger.error(f"Error handling subscription updated: {e}")
    
    async def _handle_subscription_deleted(self, event: Dict[str, Any], db_session: AsyncSession):
        """Handle customer.subscription.deleted event"""
        try:
            subscription = event['data']['object']
            user_id = subscription['metadata'].get('user_id')
            
            if not user_id:
                return
            
            # Update subscription record
            stripe_subscription = await db_session.execute(
                select(StripeSubscription).where(
                    StripeSubscription.stripe_subscription_id == subscription['id']
                )
            ).scalar_one_or_none()
            
            if stripe_subscription:
                stripe_subscription.status = SubscriptionStatus.CANCELED
                await db_session.commit()
                
                logger.info(f"Subscription canceled for user {user_id}: {subscription['id']}")
            
        except Exception as e:
            logger.error(f"Error handling subscription deleted: {e}")
    
    async def _handle_invoice_payment_succeeded(self, event: Dict[str, Any], db_session: AsyncSession):
        """Handle invoice.payment_succeeded event"""
        try:
            invoice = event['data']['object']
            
            # Only process subscription invoices
            if invoice['subscription']:
                subscription = await db_session.execute(
                    select(StripeSubscription).where(
                        StripeSubscription.stripe_subscription_id == invoice['subscription']
                    )
                ).scalar_one_or_none()
                
                if subscription:
                    # Grant monthly credits
                    await self._grant_monthly_credits(
                        subscription.user_id, 
                        subscription.plan_key, 
                        db_session
                    )
                    
                    logger.info(f"Monthly credits granted for user {subscription.user_id}")
            
        except Exception as e:
            logger.error(f"Error handling invoice payment succeeded: {e}")
    
    async def _handle_invoice_payment_failed(self, event: Dict[str, Any], db_session: AsyncSession):
        """Handle invoice.payment_failed event"""
        try:
            invoice = event['data']['object']
            
            # Update subscription status
            if invoice['subscription']:
                subscription = await db_session.execute(
                    select(StripeSubscription).where(
                        StripeSubscription.stripe_subscription_id == invoice['subscription']
                    )
                ).scalar_one_or_none()
                
                if subscription:
                    subscription.status = SubscriptionStatus.PAST_DUE
                    await db_session.commit()
                    
                    logger.info(f"Subscription marked as past due for user {subscription.user_id}")
            
        except Exception as e:
            logger.error(f"Error handling invoice payment failed: {e}")
    
    async def _handle_payment_intent_succeeded(self, event: Dict[str, Any], db_session: AsyncSession):
        """Handle payment_intent.succeeded event"""
        try:
            payment_intent = event['data']['object']
            
            # Create payment record
            payment = Payment(
                user_id=payment_intent['metadata'].get('user_id'),
                stripe_payment_intent_id=payment_intent['id'],
                amount_cents=payment_intent['amount'],
                type=PaymentType.ONE_OFF,
                status=PaymentStatus.SUCCEEDED
            )
            
            db_session.add(payment)
            await db_session.commit()
            
            logger.info(f"Payment succeeded: {payment_intent['id']}")
            
        except Exception as e:
            logger.error(f"Error handling payment intent succeeded: {e}")
    
    async def _handle_payment_intent_failed(self, event: Dict[str, Any], db_session: AsyncSession):
        """Handle payment_intent.payment_failed event"""
        try:
            payment_intent = event['data']['object']
            
            # Create payment record
            payment = Payment(
                user_id=payment_intent['metadata'].get('user_id'),
                stripe_payment_intent_id=payment_intent['id'],
                amount_cents=payment_intent['amount'],
                type=PaymentType.ONE_OFF,
                status=PaymentStatus.FAILED
            )
            
            db_session.add(payment)
            await db_session.commit()
            
            logger.info(f"Payment failed: {payment_intent['id']}")
            
        except Exception as e:
            logger.error(f"Error handling payment intent failed: {e}")
    
    async def _process_credit_pack_payment(self, session: Dict[str, Any], user_id: str, db_session: AsyncSession):
        """Process credit pack payment"""
        try:
            credit_amount = int(session['metadata'].get('credit_amount', 0))
            
            if credit_amount > 0:
                # Add credits to user's balance
                await self._add_credits(user_id, credit_amount, "credit_pack", db_session)
                
                # Create payment record
                payment = Payment(
                    user_id=user_id,
                    stripe_payment_intent_id=session['payment_intent'],
                    amount_cents=session['amount_total'],
                    type=PaymentType.CREDIT_PACK,
                    status=PaymentStatus.SUCCEEDED
                )
                
                db_session.add(payment)
                await db_session.commit()
                
                logger.info(f"Credit pack payment processed for user {user_id}: {credit_amount} credits")
            
        except Exception as e:
            logger.error(f"Error processing credit pack payment: {e}")
    
    async def _grant_monthly_credits(self, user_id: str, plan_key: str, db_session: AsyncSession):
        """Grant monthly credits based on subscription plan"""
        try:
            # Get plan configuration
            plan = get_subscription_plan(plan_key)
            
            if plan and plan.monthly_credits > 0:
                await self._add_credits(user_id, plan.monthly_credits, "subscription", db_session)
                logger.info(f"Granted {plan.monthly_credits} monthly credits to user {user_id} for plan {plan_key}")
            
        except Exception as e:
            logger.error(f"Error granting monthly credits: {e}")
    
    async def _add_credits(self, user_id: str, amount: int, reason: str, db_session: AsyncSession):
        """Add credits to user's balance"""
        try:
            # Get current balance
            student_profile = await db_session.execute(
                select(StudentProfile).where(StudentProfile.user_id == user_id)
            ).scalar_one_or_none()
            
            if not student_profile:
                # Create student profile if it doesn't exist
                student_profile = StudentProfile(
                    user_id=user_id,
                    credit_balance=0
                )
                db_session.add(student_profile)
                await db_session.flush()
            
            # Calculate new balance
            new_balance = student_profile.credit_balance + amount
            
            # Create ledger entry
            ledger_entry = CreditLedger(
                user_id=user_id,
                delta=amount,
                reason=CreditReason(reason),
                balance_after=new_balance
            )
            
            # Update balance
            student_profile.credit_balance = new_balance
            
            db_session.add(ledger_entry)
            await db_session.commit()
            
            logger.info(f"Added {amount} credits to user {user_id}, new balance: {new_balance}")
            
        except Exception as e:
            logger.error(f"Error adding credits: {e}")
            raise PaymentError(f"Failed to add credits: {str(e)}")
    
    async def deduct_credits(self, user_id: str, amount: int, reason: str, db_session: AsyncSession) -> bool:
        """Deduct credits from user's balance"""
        try:
            # Get current balance
            student_profile = await db_session.execute(
                select(StudentProfile).where(StudentProfile.user_id == user_id)
            ).scalar_one_or_none()
            
            if not student_profile or student_profile.credit_balance < amount:
                return False
            
            # Calculate new balance
            new_balance = student_profile.credit_balance - amount
            
            # Create ledger entry
            ledger_entry = CreditLedger(
                user_id=user_id,
                delta=-amount,
                reason=CreditReason(reason),
                balance_after=new_balance
            )
            
            # Update balance
            student_profile.credit_balance = new_balance
            
            db_session.add(ledger_entry)
            await db_session.commit()
            
            logger.info(f"Deducted {amount} credits from user {user_id}, new balance: {new_balance}")
            return True
            
        except Exception as e:
            logger.error(f"Error deducting credits: {e}")
            raise PaymentError(f"Failed to deduct credits: {str(e)}")
    
    async def get_customer_portal_url(self, user: User, db_session: AsyncSession) -> str:
        """Get Stripe Customer Portal URL"""
        try:
            # Ensure customer exists
            customer = await self.create_customer(user, db_session)
            
            # Create portal session
            session = stripe.billing_portal.Session.create(
                customer=customer.stripe_customer_id,
                return_url=f"{settings.FRONTEND_URL}/dashboard"
            )
            
            return session.url
            
        except Exception as e:
            logger.error(f"Error creating customer portal session for user {user.id}: {e}")
            raise PaymentError(f"Failed to create customer portal session: {str(e)}")
    
    async def cancel_subscription(self, user: User, db_session: AsyncSession) -> bool:
        """Cancel user's active subscription"""
        try:
            # Get active subscription
            subscription = await db_session.execute(
                select(StripeSubscription).where(
                    and_(
                        StripeSubscription.user_id == str(user.id),
                        StripeSubscription.status == SubscriptionStatus.ACTIVE
                    )
                )
            ).scalar_one_or_none()
            
            if not subscription:
                raise SubscriptionError("No active subscription found")
            
            # Cancel in Stripe
            stripe.Subscription.modify(
                subscription.stripe_subscription_id,
                cancel_at_period_end=True
            )
            
            # Update local record
            subscription.status = SubscriptionStatus.CANCELED
            await db_session.commit()
            
            logger.info(f"Subscription canceled for user {user.id}")
            return True
            
        except Exception as e:
            logger.error(f"Error canceling subscription for user {user.id}: {e}")
            raise SubscriptionError(f"Failed to cancel subscription: {str(e)}")
    
    def _get_plan_key_from_price_id(self, price_id: str) -> str:
        """Get plan key from Stripe price ID"""
        # Map Stripe price IDs to plan keys
        plan_mapping = {
            "price_starter_monthly": "starter",
            "price_pro_monthly": "pro",
            "price_premium_monthly": "premium"
        }
        
        return plan_mapping.get(price_id, "starter")
    
    async def get_subscription_plans(self) -> List[Dict[str, Any]]:
        """Get available subscription plans"""
        try:
            # Use our pricing configuration
            from app.core.pricing import get_all_subscription_plans
            
            plans = []
            for plan in get_all_subscription_plans():
                plans.append({
                    "key": plan.key,
                    "name": plan.name,
                    "description": plan.description,
                    "price_cents": plan.price_cents,
                    "currency": "usd",
                    "interval": plan.interval,
                    "monthly_credits": plan.monthly_credits,
                    "ai_features": plan.ai_features,
                    "stripe_price_id": plan.stripe_price_id
                })
            
            return plans
            
        except Exception as e:
            logger.error(f"Error fetching subscription plans: {e}")
            raise PaymentError(f"Failed to fetch subscription plans: {str(e)}")
    
    async def get_user_subscription_status(self, user_id: str, db_session: AsyncSession) -> Dict[str, Any]:
        """Get user's subscription status and limits"""
        try:
            # Get active subscription
            subscription = await db_session.execute(
                select(StripeSubscription).where(
                    and_(
                        StripeSubscription.user_id == user_id,
                        StripeSubscription.status == SubscriptionStatus.ACTIVE
                    )
                )
            ).scalar_one_or_none()
            
            if subscription:
                plan = get_subscription_plan(subscription.plan_key)
                ai_limits = get_ai_usage_limits(subscription.plan_key)
                
                return {
                    "has_subscription": True,
                    "plan_key": subscription.plan_key,
                    "plan_name": plan.name if plan else subscription.plan_key,
                    "status": subscription.status.value,
                    "current_period_end": subscription.current_period_end.isoformat(),
                    "monthly_credits": plan.monthly_credits if plan else 0,
                    "ai_limits": {
                        "qa_requests_per_month": ai_limits.qa_requests_per_month,
                        "summaries_per_month": ai_limits.summaries_per_month,
                        "flashcards_per_month": ai_limits.flashcards_per_month,
                        "quizzes_per_month": ai_limits.quizzes_per_month,
                        "max_tokens_per_request": ai_limits.max_tokens_per_request
                    }
                }
            else:
                # Free tier limits
                ai_limits = get_ai_usage_limits("free")
                
                return {
                    "has_subscription": False,
                    "plan_key": "free",
                    "plan_name": "Free",
                    "status": "none",
                    "monthly_credits": 0,
                    "ai_limits": {
                        "qa_requests_per_month": ai_limits.qa_requests_per_month,
                        "summaries_per_month": ai_limits.summaries_per_month,
                        "flashcards_per_month": ai_limits.flashcards_per_month,
                        "quizzes_per_month": ai_limits.quizzes_per_month,
                        "max_tokens_per_request": ai_limits.max_tokens_per_request
                    }
                }
                
        except Exception as e:
            logger.error(f"Error getting subscription status for user {user_id}: {e}")
            raise PaymentError(f"Failed to get subscription status: {str(e)}")
    
    async def check_ai_usage_limit(self, user_id: str, feature: str, db_session: AsyncSession) -> bool:
        """Check if user has exceeded AI usage limits"""
        try:
            # Get subscription status
            subscription_status = await self.get_user_subscription_status(user_id, db_session)
            
            # Get current month's usage
            from datetime import datetime, timezone
            current_month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # TODO: Implement usage tracking in database
            # For now, we'll allow usage (this should be implemented with a usage tracking table)
            
            limit = subscription_status["ai_limits"].get(f"{feature}_per_month", 0)
            
            # -1 means unlimited
            if limit == -1:
                return True
            
            # TODO: Check actual usage against limit
            # current_usage = await self._get_current_month_usage(user_id, feature, db_session)
            # return current_usage < limit
            
            return True  # Temporary - always allow for now
            
        except Exception as e:
            logger.error(f"Error checking AI usage limit for user {user_id}: {e}")
            return False
    
    async def create_booking_payment_intent(
        self,
        user: User,
        tutor_rate_cents: int,
        booking_id: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """Create PaymentIntent for booking payment"""
        try:
            # Check if user has subscription for discounted rate
            subscription_status = await self.get_user_subscription_status(str(user.id), db_session)
            has_subscription = subscription_status["has_subscription"]
            
            # Determine rate
            if has_subscription:
                rate_cents = get_pay_as_you_go_rate(has_subscription=True)
            else:
                rate_cents = tutor_rate_cents or get_pay_as_you_go_rate(has_subscription=False)
            
            # Create payment intent
            result = await self.create_payment_intent(
                user=user,
                amount_cents=rate_cents,
                description=f"Tutoring session booking",
                metadata={
                    "booking_id": booking_id,
                    "tutor_rate_cents": tutor_rate_cents,
                    "has_subscription": has_subscription,
                    "payment_type": "booking"
                },
                db_session=db_session
            )
            
            return {
                **result,
                "rate_cents": rate_cents,
                "has_subscription": has_subscription
            }
            
        except Exception as e:
            logger.error(f"Error creating booking payment intent for user {user.id}: {e}")
            raise PaymentError(f"Failed to create booking payment intent: {str(e)}")
